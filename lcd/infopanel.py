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
import psutil

from infopanel_data import InfoData, finite, meteo_records
from infopanel_touch import Calibration, TouchReader, list_touch_devices
from infopanel_ui import BG, WHITE, GREEN, AMBER, PAGES, font, layout_for, render
from lcd_info import (FBIOGET_FSCREENINFO, FBIOGET_VSCREENINFO, fb_fix_screeninfo,
                      fb_var_screeninfo, fb_ioctl_struct, rgb_to_rgb565_bytes,
                      _try_parse_line, get_cpu_temp_c, get_iface_ip, get_uptime_str)

VERSION = "2.1.0"
DEFAULTS = {"fb":"/dev/fb0","rotate":0,"touch":"auto","layout":"auto",
            "font":"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "meteo_csv":"/opt/meteo3/meteo_log.csv","meteo_refresh":15,"meteo_stale":3600,
            "iface":"eth0","api":"http://127.0.0.1:4011/api/iot",
            "panel_id":None,"plug_id":None,"iot_refresh":5,"idle_seconds":60,
            "data_dir":"/var/lib/hanzhub-infopanel"}


def validate_settings(settings):
    if set(settings)-set(DEFAULTS):
        raise ValueError("Neznámá nastavení: "+", ".join(sorted(set(settings)-set(DEFAULTS))))
    result = {**DEFAULTS,**settings}
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
        record["last_label"] = timestamp.strftime("%H:%M · %d.%m.%y") if timestamp else "Bez dat"
        samples = [(row["ts"].timestamp(),row["temp"]) for row in rows
                   if now-hours*3600<=row["ts"].timestamp()<=now and finite(row.get("temp"))]
        return record,samples

    def close(self):
        self.stop.set()


class ScreenState:
    def __init__(self, idle_seconds=60):
        self.page = "home"
        self.window = {"meteo":24,"plug":24}
        self.timer_dialog = False
        self.last_touch = time.monotonic()
        self.idle_seconds = idle_seconds

    def tap(self, tap, calibration, hits, data):
        if tap.moved or tap.duration<.025 or tap.duration>3:
            return False
        x,y = calibration.point(tap.x,tap.y)
        start = calibration.point(tap.start_x,tap.start_y)
        for hit in reversed(hits):
            # Lehký pohyb je možný, přesun mezi tlačítky nedá příkaz.
            if hit.contains(x,y) and hit.contains(*start):
                action = hit.action
                self.last_touch = time.monotonic()
                if action[0]=="page" and action[1] in PAGES:
                    self.page,self.timer_dialog = action[1],False
                elif action[0]=="window" and self.page in self.window and action[1] in (1,6,24):
                    self.window[self.page] = action[1]
                elif action[0]=="timer":
                    self.timer_dialog = action[1]=="open"
                elif action[0]=="command":
                    if data.submit(*action[1:]):
                        self.timer_dialog = False
                return True
        self.last_touch = time.monotonic()
        return False

    def idle(self, busy=False, now=None):
        now = time.monotonic() if now is None else now
        if self.idle_seconds and now-self.last_touch>=self.idle_seconds and not busy:
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
    fb = reader = data = weather = None
    try:
        fb = Framebuffer(args.fb)
        size = fb.size[::-1] if args.rotate in (90,270) else fb.size
        reader = TouchReader(args.touch)
        directory = Path(args.data_dir)
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        calibration_path = directory/"touch-calibration.json"
        calibration = None if args.calibrate else Calibration.load(calibration_path,reader.description,size,args.rotate)
        raw_points,error = [],""
        state = ScreenState(args.idle_seconds)
        data = InfoData(args.api,directory,args.panel_id,args.plug_id,args.iot_refresh)
        weather = Weather(args.meteo_csv,args.meteo_refresh,args.meteo_stale)
        data.start()
        weather.start()
        next_render,system_next,history_next = 0,0,0
        system,history = {},[]
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
            snapshot = data.snapshot()
            if state.idle(snapshot["busy"],now):
                next_render = 0
            if now>=next_render:
                next_render = now+1
                if calibration is None:
                    image = calibration_image(size,len(raw_points),args.font,error)
                    hits = []
                else:
                    if now>=system_next:
                        system_next = now+2
                        system = {"cpu":psutil.cpu_percent(),"ram":psutil.virtual_memory().percent,
                                  "disk":psutil.disk_usage("/").percent,"temp":get_cpu_temp_c(),
                                  "uptime":get_uptime_str(),"ip":get_iface_ip(args.iface)}
                    window = state.window.get(state.page,24)
                    meteo,meteo_history = weather.snapshot(window)
                    key = (snapshot["plug_id"],window)
                    if now>=history_next or key!=history_key:
                        history_next,history_key = now+10,key
                        try:
                            history = data.history.series(snapshot["plug_id"],window) if snapshot["plug_id"] else []
                        except (OSError,sqlite3.Error):
                            history = []
                    snapshot.update(now=datetime.now(),system=system,meteo=meteo,meteo_history=meteo_history,plug_history=history)
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
        for resource in (weather,data,reader,fb):
            if resource is not None:
                resource.close()
    return 0


if __name__=="__main__":
    raise SystemExit(main())
