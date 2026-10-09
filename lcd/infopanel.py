#!/usr/bin/env python3
"""HanzHub Infopanel v2: samostatný framebuffer a dotykové stránky."""
import argparse
from datetime import datetime
import json
import logging
import mmap
import os
from pathlib import Path
import re
import signal
import sqlite3
import sys
import threading
import time
from urllib.parse import urlsplit

from PIL import Image, ImageDraw

from infopanel_data import InfoData, ServiceHealth, finite, meteo_records
from infopanel_touch import Calibration, TouchReader, list_touch_devices
from infopanel_ui import BG, WHITE, GREEN, AMBER, PAGES, VERSION, font, layout_for, render
from infopanel_system import SystemMonitor
from infopanel_gpio import TouchOutputs, gpio_probe
from lcd_info import (FBIOGET_FSCREENINFO, FBIOGET_VSCREENINFO, fb_fix_screeninfo,
                      fb_var_screeninfo, fb_ioctl_struct, rgb_to_rgb565_bytes,
                      _try_parse_line)

DEFAULTS = {"fb":"/dev/fb0","rotate":0,"touch":"auto","layout":"auto",
            "font":"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "meteo_csv":"/opt/meteo3/meteo_log.csv","meteo_refresh":15,"meteo_stale":3600,
            "iface":"eth0","api":"http://127.0.0.1:4011/api/iot",
            "panel_id":None,"plug_id":None,"iot_refresh":5,"idle_seconds":60,
            "home_tiles":["meteo","heater","plug"],
            "health_api":"http://127.0.0.1:4010/api/health",
            "backlight_gpio":21,"haptic_gpio":20,"haptic_ms":50,
            "data_dir":"/var/lib/hanzhub-infopanel"}


def validate_settings(settings):
    if set(settings)-set(DEFAULTS):
        raise ValueError("Neznámá nastavení: "+", ".join(sorted(set(settings)-set(DEFAULTS))))
    result = {**DEFAULTS,**settings}
    tiles = result["home_tiles"]
    if not isinstance(tiles,list) or not 1<=len(tiles)<=9 or any(
        not isinstance(tile,str) or tile not in ("meteo","heater","plug") for tile in tiles
    ) or len(set(tiles))!=len(tiles):
        raise ValueError("home_tiles musí být seznam různých podporovaných dlaždic: meteo, heater, plug.")
    result["home_tiles"] = list(tiles)
    for name in ("backlight_gpio","haptic_gpio"):
        if result[name] is not None and (type(result[name]) is not int or not 0<=result[name]<=27):
            raise ValueError(f"{name} musí být BCM číslo 0–27 nebo null pro vypnutí.")
    if result["backlight_gpio"] is not None and result["backlight_gpio"]==result["haptic_gpio"]:
        raise ValueError("Podsvícení a haptika musí mít různé GPIO.")
    if type(result["haptic_ms"]) is not int or not 10<=result["haptic_ms"]<=150:
        raise ValueError("haptic_ms musí být celé číslo 10–150 ms.")
    health = urlsplit(result["health_api"]) if isinstance(result["health_api"],str) else None
    if not health or health.scheme not in ("http","https") or not health.hostname or health.username or health.password or health.query or health.fragment or health.path!="/api/health":
        raise ValueError("health_api musí být URL dashboardu zakončené /api/health.")
    if type(result["rotate"]) is not int or result["rotate"] not in (0,90,180,270):
        raise ValueError("rotate musí být 0, 90, 180 nebo 270 (proti směru hodin).")
    layout_for((320,480),result["layout"])
    for name,low,high in (("meteo_refresh",2,3600),("meteo_stale",60,86400),("iot_refresh",5,60),("idle_seconds",0,3600)):
        if not finite(result[name]) or not low<=result[name]<=high:
            raise ValueError(f"{name} musí být mezi {low} a {high}.")
    for name in ("fb","font","meteo_csv","data_dir"):
        if not isinstance(result[name],str) or not Path(result[name]).is_absolute() or "\n" in result[name]:
            raise ValueError(f"{name} musí být absolutní cesta.")
    if result["touch"]!="auto" and (not isinstance(result["touch"],str) or not result["touch"].startswith("/dev/input/") or "\n" in result["touch"]):
        raise ValueError("touch musí být auto nebo cesta /dev/input/…")
    if not isinstance(result["iface"],str) or not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,32}",result["iface"]):
        raise ValueError("Neplatný název síťového rozhraní iface.")
    for name in ("panel_id","plug_id"):
        if result[name] is not None and not re.fullmatch(r"[a-f0-9]{12}",str(result[name])):
            raise ValueError(f"{name} musí být ID modulu z HanzHub API (12 znaků), nikoli Tuya Device ID.")
    parts = urlsplit(result["api"])
    if parts.scheme not in ("http","https") or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path.rstrip("/")!="/api/iot":
        raise ValueError("api musí mít tvar http://127.0.0.1:4011/api/iot bez přihlašovacích údajů.")
    result["api"] = result["api"].rstrip("/")
    return result


def arguments(argv=None):
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config",default="/etc/hanzhub-infopanel.json")
    known,_ = pre.parse_known_args(argv)
    settings = {}
    if Path(known.config).exists():
        settings = json.loads(Path(known.config).read_text(encoding="utf-8"))
        if not isinstance(settings,dict):
            raise ValueError("Konfigurace musí být JSON objekt.")
    elif known.config!="/etc/hanzhub-infopanel.json":
        raise ValueError(f"Konfigurace {known.config} neexistuje.")
    ap = argparse.ArgumentParser(description=__doc__,parents=[pre])
    for name,value in DEFAULTS.items():
        kwargs = {"default":settings.get(name,value)}
        if name=="rotate":
            kwargs["type"] = int
        elif name=="layout":
            kwargs["choices"] = ("auto","portrait","landscape")
        elif name in ("home_tiles","backlight_gpio","haptic_gpio"):
            kwargs["type"] = json.loads
        elif name=="haptic_ms":
            kwargs["type"] = int
        elif name in ("meteo_refresh","meteo_stale","iot_refresh","idle_seconds"):
            kwargs["type"] = float
        ap.add_argument("--"+name.replace("_","-"),dest=name,**kwargs)
    ap.add_argument("--diagnose",action="store_true",help="Vypíše framebuffer a dotyk, nic nezapíná.")
    ap.add_argument("--calibrate",action="store_true",help="Zopakuje kalibraci dotyku.")
    ap.add_argument("--check",action="store_true",help="Ověří nastavení a hardware bez zápisu na displej nebo API.")
    ap.add_argument("--version",action="version",version=VERSION)
    args = ap.parse_args(argv)
    validate_settings(settings)  # zachytí i překlep v klíči konfigurace
    validated = validate_settings({name:getattr(args,name) for name in DEFAULTS})
    for name,value in validated.items():
        setattr(args,name,value)
    return args


class Framebuffer:
    def __init__(self, path, map_memory=True):
        self.fd = os.open(path,os.O_RDWR)
        self.memory = None
        try:
            v = fb_ioctl_struct(self.fd,FBIOGET_VSCREENINFO,fb_var_screeninfo())
            f = fb_ioctl_struct(self.fd,FBIOGET_FSCREENINFO,fb_fix_screeninfo())
            self.size = (int(v.xres),int(v.yres))
            self.bpp,self.stride = int(v.bits_per_pixel),int(f.line_length)
            layout = [(field.offset,field.length) for field in (v.red,v.green,v.blue)]
            if (self.bpp==16 and layout!=[(11,5),(5,6),(0,5)]) or (self.bpp==32 and layout!=[(16,8),(8,8),(0,8)]) or self.bpp not in (16,32):
                raise ValueError(f"Nepodporovaný formát framebufferu: {self.bpp} bitů, RGB {layout}. Podporováno RGB565 a BGRX8888.")
            self.row_bytes = self.size[0]*(self.bpp//8)
            self.offset = int(v.yoffset)*self.stride+int(v.xoffset)*(self.bpp//8)
            if min(self.size)<240 or self.stride<self.row_bytes or self.offset+(self.size[1]-1)*self.stride+self.row_bytes>f.smem_len:
                raise ValueError("Framebuffer má příliš malé rozlišení nebo neplatný stride/offset.")
            if map_memory:
                self.memory = mmap.mmap(self.fd,f.smem_len,mmap.MAP_SHARED,mmap.PROT_WRITE|mmap.PROT_READ)
        except BaseException:
            os.close(self.fd)
            raise

    def write(self, image):
        if image.size!=self.size:
            raise ValueError("Bitmapa neodpovídá framebufferu.")
        raw = rgb_to_rgb565_bytes(image) if self.bpp==16 else image.convert("RGB").tobytes("raw","BGRX")
        for row in range(self.size[1]):
            start = self.offset+row*self.stride
            self.memory[start:start+self.row_bytes] = raw[row*self.row_bytes:(row+1)*self.row_bytes]

    def close(self):
        if self.memory is not None:
            self.memory.close()
        os.close(self.fd)


class Weather:
    def __init__(self, path, refresh=15, stale=3600):
        self.path,self.refresh,self.stale = path,refresh,stale
        self.lock,self.stop = threading.Lock(),threading.Event()
        self.records = []
        self.thread = None

    def start(self):
        def run():
            while not self.stop.is_set():
                records = meteo_records(self.path,_try_parse_line)
                with self.lock:
                    self.records = records
                self.stop.wait(self.refresh)
        self.thread = threading.Thread(target=run,daemon=True)
        self.thread.start()

    def snapshot(self, hours, now=None):
        now = time.time() if now is None else now
        with self.lock:
            rows = list(self.records)
        rows = [row for row in rows if row["ts"].timestamp()<=now+60]
        record = dict(rows[-1]) if rows else {}
        timestamp = record.pop("ts",None)
        for field in ("temp","soc","vbat"):
            if not finite(record.get(field)):
                record[field] = None
        record["stale"] = timestamp is None or now-timestamp.timestamp()>self.stale
        record["age_seconds"] = max(0,now-timestamp.timestamp()) if timestamp else None
        record["last_label"] = timestamp.strftime("%H:%M · %d.%m.%y") if timestamp else "Bez dat"
        samples = [(row["ts"].timestamp(),row["temp"]) for row in rows
                   if now-hours*3600<=row["ts"].timestamp()<=now and finite(row.get("temp"))]
        return record,samples

    def close(self):
        self.stop.set()


class ScreenState:
    def __init__(self, idle_seconds=60, outputs=None):
        self.outputs = outputs
        self.page = "home"
        self.services_page = 0
        self.window = {"meteo":24,"plug":24}
        self.timer_dialog = False
        self.last_touch = time.monotonic()
        self.idle_seconds = idle_seconds
        self.temperature = None
        self.sent_temperature = None
        self.notice, self.notice_until = "", 0

    def queue_temperature(self, delta, data, now=None):
        now = time.monotonic() if now is None else now
        snapshot = data.snapshot()
        heater = snapshot.get("heater") or {}
        target = heater.get("target_temp_c")
        module_id = snapshot.get("heater_id")
        if snapshot.get("busy") or heater.get("online") is not True or type(heater.get("power")) is not bool or type(target) is not int or not 0<=target<=37 or not module_id or delta not in (-1,1):
            return False
        pending = self.temperature
        current = pending["value"] if pending and pending["id"]==module_id else target
        value = max(0,min(37,current+delta))
        if value==current:
            return False
        self.temperature = {"id":module_id,"value":value,"due":now+2} if value!=target else None
        return True

    def tick(self, data, now=None):
        """Jeden poslední cíl po dvou sekundách klidu; žádné opakování zápisu."""
        now = time.monotonic() if now is None else now
        snapshot = data.snapshot()
        if self.sent_temperature and (not snapshot.get("busy") or snapshot.get("heater_id")!=self.sent_temperature["id"]):
            self.sent_temperature = None
        pending = self.temperature
        if not pending:
            return False
        heater = snapshot.get("heater") or {}
        if snapshot.get("heater_id")!=pending["id"] or heater.get("online") is not True or snapshot.get("busy"):
            self.temperature = None
            self.notice, self.notice_until = "Změna teploty zrušena: zařízení není připravené",now+8
            return True
        if now<pending["due"]:
            return False
        self.temperature = None
        if heater.get("target_temp_c")==pending["value"]:
            return True
        if data.submit("heater","target_temp_c",pending["value"],expected_module_id=pending["id"]):
            self.sent_temperature = pending
        else:
            self.notice, self.notice_until = "Změnu teploty se nepodařilo odeslat",now+8
        return True

    def display_model(self, snapshot, now=None):
        now = time.monotonic() if now is None else now
        model = dict(snapshot)
        draft = self.temperature or self.sent_temperature
        if draft and draft["id"]==snapshot.get("heater_id"):
            model["target_draft_c"] = draft["value"]
            model["temperature_waiting"] = self.temperature is not None
            if self.temperature:
                model["message"] = f"Nový cíl {draft['value']} °C · odešlu po 2 s bez klepnutí"
        elif now<self.notice_until and not model.get("message"):
            model["message"] = self.notice
        return model

    def tap(self, tap, calibration, hits, data):
        if tap.moved or tap.duration<.025 or tap.duration>3:
            return False
        x,y = calibration.point(tap.x,tap.y)
        start = calibration.point(tap.start_x,tap.start_y)
        self.last_touch = time.monotonic()
        # The first valid touch wakes a dark LCD without issuing any hidden command.
        if self.outputs and not self.outputs.backlight_on:
            accepted = self.outputs.set_backlight(True)
            if accepted:
                self.outputs.pulse()
            return accepted
        for hit in reversed(hits):
            # Lehký pohyb je možný, přesun mezi tlačítky nedá příkaz.
            if hit.contains(x,y) and hit.contains(*start):
                action = hit.action
                accepted = True
                if action[0]=="page" and action[1] in PAGES+("system",):
                    self.page,self.timer_dialog = action[1],False
                    self.services_page = 0
                elif action[0]=="services_page" and self.page=="system" and type(action[1]) is int and 0<=action[1]<=1000:
                    self.services_page = action[1]
                elif action[0]=="window" and self.page in self.window and action[1] in (1,6,24):
                    self.window[self.page] = action[1]
                elif action[0]=="timer":
                    self.timer_dialog = action[1]=="open"
                elif action[0]=="temperature":
                    accepted = self.queue_temperature(action[1],data)
                elif action[0]=="command":
                    accepted = data.submit(*action[1:])
                    if accepted:
                        self.temperature = None
                        self.timer_dialog = False
                elif action[0]=="backlight":
                    accepted = bool(self.outputs and self.outputs.set_backlight(not self.outputs.backlight_on))
                    if not accepted:
                        self.notice,self.notice_until = "Podsvícení nelze přepnout · zkontroluj GPIO a log",time.monotonic()+8
                else:
                    accepted = False
                if accepted and self.outputs:
                    self.outputs.pulse()
                return accepted
        return False

    def idle(self, busy=False, now=None):
        now = time.monotonic() if now is None else now
        if self.idle_seconds and now-self.last_touch>=self.idle_seconds and not busy and not self.temperature:
            changed = self.page!="home" or self.timer_dialog
            self.page,self.timer_dialog = "home",False
            return changed
        return False


def calibration_targets(size):
    w,h = size
    margin = max(30,round(min(size)*.1))
    return [(margin,margin),(w-margin,margin),(w-margin,h-margin),(margin,h-margin)]


def calibration_image(size, step, font_path, error=""):
    image = Image.new("RGB",size,BG)
    draw = ImageDraw.Draw(image)
    w,h = size
    scale = min(w/320,h/480)
    draw.text((w/2,h/2-45*scale),"Kalibrace dotyku",font=font(round(22*scale),True,font_path),fill=WHITE,anchor="mm")
    draw.text((w/2,h/2-12*scale),f"Klepni na křížek {step+1}/4",font=font(round(16*scale),False,font_path),fill=GREEN,anchor="mm")
    draw.text((w/2,h/2+20*scale),"Po klepnutí zvedni prst",font=font(round(12*scale),False,font_path),fill=WHITE,anchor="mm")
    if error:
        draw.text((w/2,h/2+55*scale),"Zkus to znovu přesněji",font=font(round(13*scale),False,font_path),fill=AMBER,anchor="mm")
    x,y = calibration_targets(size)[step]
    draw.ellipse((x-18*scale,y-18*scale,x+18*scale,y+18*scale),outline=GREEN,width=2)
    draw.line((x-25*scale,y,x+25*scale,y),fill=GREEN,width=2)
    draw.line((x,y-25*scale,x,y+25*scale),fill=GREEN,width=2)
    return image


def check_hardware(args):
    framebuffer = Framebuffer(args.fb,map_memory=False)
    try:
        reader = TouchReader(args.touch)
        try:
            size = framebuffer.size[::-1] if args.rotate in (90,270) else framebuffer.size
            print(json.dumps({"framebuffer":{"path":args.fb,"size":framebuffer.size,"bpp":framebuffer.bpp,"stride":framebuffer.stride},
                              "display":{"logical_size":size,"layout":layout_for(size,args.layout),"rotate":args.rotate},
                              "touch":reader.description},ensure_ascii=False,indent=2))
        finally:
            reader.close()
    finally:
        framebuffer.close()
    font(14,path=args.font)
    # Discovery only: --check must not claim GPIO or alter a running output.
    for bcm in (args.backlight_gpio,args.haptic_gpio):
        if bcm is not None:
            try:
                logging.info("GPIO kontrola (bez zápisu): %s",gpio_probe(bcm))
            except (OSError,ValueError) as error:
                logging.warning("Volitelné GPIO%s: %s",bcm,error)


def main(argv=None):
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    try:
        args = arguments(argv)
        if args.diagnose:
            print("Infopanel",VERSION)
            try:
                fb = Framebuffer(args.fb,map_memory=False)
                print("Framebuffer:",args.fb,fb.size,fb.bpp,"bitů, stride",fb.stride)
                size = fb.size[::-1] if args.rotate in (90,270) else fb.size
                print("Rozložení:",layout_for(size,args.layout),"logické rozlišení:",size,"otočení:",args.rotate)
                fb.close()
            except (OSError,ValueError) as error:
                print("Framebuffer:",str(error))
            print(json.dumps(list_touch_devices(),ensure_ascii=False,indent=2))
            return 0
        if args.check:
            check_hardware(args)
            return 0
        check_hardware(args)
    except (OSError,ValueError,ImportError) as error:
        logging.error("Infopanel: %s",error)
        return 1

    stopping = threading.Event()
    for sig in (signal.SIGTERM,signal.SIGINT):
        signal.signal(sig,lambda *_:stopping.set())
    fb = reader = data = weather = services = monitor = outputs = None
    try:
        fb = Framebuffer(args.fb)
        size = fb.size[::-1] if args.rotate in (90,270) else fb.size
        reader = TouchReader(args.touch)
        directory = Path(args.data_dir)
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        calibration_path = directory/"touch-calibration.json"
        calibration = None if args.calibrate else Calibration.load(calibration_path,reader.description,size,args.rotate)
        raw_points,error = [],""
        outputs = TouchOutputs(args.backlight_gpio,args.haptic_gpio,args.haptic_ms)
        state = ScreenState(args.idle_seconds,outputs)
        data = InfoData(args.api,directory,args.panel_id,args.plug_id,args.iot_refresh)
        weather = Weather(args.meteo_csv,args.meteo_refresh,args.meteo_stale)
        services = ServiceHealth(args.health_api)
        monitor = SystemMonitor(args.iface)
        data.start()
        weather.start()
        services.start()
        monitor.start()
        next_render,history_next = 0,0
        history = []
        history_key = None
        hits = []
        logging.info("Infopanel %s běží; %s, rozložení %s, otočení %s; dotyk %s",VERSION,size,layout_for(size,args.layout),args.rotate,reader.description["name"])
        while not stopping.is_set():
            now = time.monotonic()
            taps = reader.read(.05)
            # Při změně stránky zahodíme zbytek dávky; další dotyk musí přijít na nový snímek.
            for tap in taps:
                if calibration is None:
                    if tap.moved or not .025<=tap.duration<=3:
                        continue
                    raw_points.append((tap.x,tap.y))
                    outputs.pulse()
                    if len(raw_points)==4:
                        try:
                            calibration = Calibration.fit(reader.description["ranges"],size,raw_points,calibration_targets(size))
                            calibration.save(calibration_path,reader.description["fingerprint"],args.rotate)
                            logging.info("Kalibrace uložena.")
                        except ValueError as problem:
                            logging.warning("%s",problem)
                            calibration,raw_points,error = None,[],str(problem)
                    next_render = 0
                    break
                if state.tap(tap,calibration,hits,data):
                    next_render = 0
                    break
            if state.tick(data,now):
                next_render = 0
            snapshot = state.display_model(data.snapshot(),now)
            if state.idle(snapshot["busy"],now):
                next_render = 0
            if now>=next_render:
                next_render = now+1
                if calibration is None:
                    image = calibration_image(size,len(raw_points),args.font,error)
                    hits = []
                else:
                    window = state.window.get(state.page,24)
                    meteo,meteo_history = weather.snapshot(window)
                    key = (snapshot["plug_id"],window)
                    if now>=history_next or key!=history_key:
                        history_next,history_key = now+10,key
                        try:
                            history = data.history.series(snapshot["plug_id"],window) if snapshot["plug_id"] else []
                        except (OSError,sqlite3.Error):
                            history = []
                    snapshot.update(now=datetime.now(),system=monitor.snapshot(),meteo=meteo,meteo_history=meteo_history,plug_history=history,
                                    services=services.snapshot(),home_tiles=args.home_tiles,services_page=state.services_page,
                                    backlight_control=outputs.backlight_available)
                    if snapshot["history_error"] and state.page=="plug" and not snapshot["message"]:
                        snapshot["message"] = "Historii příkonu nelze uložit"
                    image,hits = render(state.page,snapshot,window,state.timer_dialog,size,args.font,args.layout)
                if args.rotate:
                    image = image.rotate(args.rotate,expand=True)
                fb.write(image)
    except (OSError,ValueError,sqlite3.Error) as error:
        logging.exception("Infopanel zastaven: %s",error)
        return 1
    finally:
        for resource in (outputs,monitor,services,weather,data,reader,fb):
            if resource is not None:
                resource.close()
    return 0


if __name__=="__main__":
    raise SystemExit(main())
