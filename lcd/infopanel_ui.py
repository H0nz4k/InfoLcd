"""Dotykové stránky Infopanelu v2; renderer bez přístupu k síti nebo hardwaru."""
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
import math
from pathlib import Path
import statistics

from PIL import Image, ImageDraw, ImageFont

BG = (6, 12, 21)
CARD = (15, 25, 38)
BORDER = (41, 58, 77)
WHITE = (240, 246, 252)
MUTED = (151, 173, 196)
GREEN = (43, 213, 146)
RED = (255, 100, 108)
AMBER = (255, 173, 65)
BLUE = (75, 194, 255)
VERSION = "2.4.0"
HEADER_VERSION = "v"+".".join(VERSION.split(".")[:2])
PAGES = ("home", "meteo", "heater", "plug")
TITLES = {"home": "HanzHub", "meteo": "Meteo", "heater": "Infrapanel", "plug": "Zásuvka", "system": "Raspberry"}


def number(value):
    return float(value) if type(value) in (int, float) and math.isfinite(value) else None


def fmt(value, precision=1, suffix=""):
    value = number(value)
    return "—" if value is None else f"{value:.{precision}f}".replace(".", ",") + suffix


def usable(state):
    return isinstance(state, dict) and state.get("online") is True and type(state.get("power")) is bool


def status(state):
    if isinstance(state, dict) and state.get("paused"):
        return "Pozastaveno", AMBER
    if not usable(state):
        return "Nedostupný", AMBER
    return ("ON", GREEN) if state["power"] else ("OFF", RED)


@dataclass(frozen=True)
class Hit:
    rect: tuple
    action: tuple

    def contains(self, x, y):
        return self.rect[0] <= x < self.rect[2] and self.rect[1] <= y < self.rect[3]


@lru_cache(maxsize=96)
def font(size, bold=False, path="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
    candidate = str(Path(path).with_name(Path(path).stem + "-Bold.ttf")) if bold else path
    try:
        return ImageFont.truetype(candidate, size)
    except OSError:
        return ImageFont.truetype(path, size)


class Canvas:
    def __init__(self, font_path, size=(320,480)):
        self.image = Image.new("RGB", size, BG)
        self.draw = ImageDraw.Draw(self.image)
        self.hits = []
        self.font_path = font_path

    def text(self, xy, text, size=14, color=WHITE, bold=False, anchor=None, width=None):
        text = str(text)
        face = font(size, bold, self.font_path)
        if width:
            if self.draw.textlength(text, font=face) > width:
                while text and self.draw.textlength(text+"…", font=face) > width:
                    text = text[:-1]
                text = text+"…" if text else ""
        options = {"font": face, "fill": color}
        if anchor:
            options["anchor"] = anchor
        self.draw.text(xy, text, **options)

    def card(self, rect, accent=None, action=None):
        self.draw.rounded_rectangle(rect, radius=13, fill=CARD, outline=BORDER)
        if accent:
            self.draw.rounded_rectangle((rect[0], rect[1]+12, rect[0]+3, rect[3]-12), radius=2, fill=accent)
        if action:
            self.hits.append(Hit(rect, action))

    def button(self, rect, label, action, active=True, color=WHITE, selected=False, size=14):
        fill = (25, 57, 54) if selected else CARD
        self.draw.rounded_rectangle(rect, radius=10, fill=fill, outline=GREEN if selected else BORDER)
        self.text(((rect[0]+rect[2])/2, (rect[1]+rect[3])/2), label, size,
                  color if active else (79, 96, 115), anchor="mm", width=rect[2]-rect[0]-12)
        if active:
            self.hits.append(Hit(rect, action))

    def badge(self, x_right, y, state, size=12, height=24):
        label, color = status(state)
        face = font(size, True, self.font_path)
        width = math.ceil(self.draw.textlength(label, font=face)) + 18
        self.draw.rounded_rectangle((x_right-width, y, x_right, y+height), radius=height//2,
                                    fill=tuple(int(v*.14) for v in color), outline=color)
        self.text((x_right-width/2, y+height/2), label, size, color, True, anchor="mm")
        return x_right-width

    def icon(self, name, x, y, color):
        d = self.draw
        if name == "home":
            d.line([(x-9,y), (x,y-8), (x+9,y)], fill=color, width=2)
            d.line([(x-7,y-1), (x-7,y+8), (x+7,y+8), (x+7,y-1)], fill=color, width=2)
        elif name == "meteo":
            d.line([(x-9,y+8), (x-9,y-8)], fill=color, width=2)
            d.line([(x-9,y+8), (x+9,y+8)], fill=color, width=2)
            d.line([(x-5,y+2), (x-1,y-3), (x+3,y), (x+9,y-7)], fill=color, width=2)
        elif name == "heater":
            for offset in (-6,0,6):
                d.line([(x+offset,y+5),(x+offset+2,y+1),(x+offset-2,y-3),(x+offset,y-7)], fill=color, width=2)
            d.line((x-10,y+9,x+10,y+9), fill=color, width=2)
        else:
            d.line((x-5,y-10,x-5,y-4), fill=color, width=2)
            d.line((x+5,y-10,x+5,y-4), fill=color, width=2)
            d.line([(x-8,y-4),(x+8,y-4),(x+8,y+2),(x+4,y+6),(x-4,y+6),(x-8,y+2),(x-8,y-4)], fill=color, width=2)
            d.line((x,y+6,x,y+11), fill=color, width=2)

    def nav(self, page):
        self.draw.line((8,418,312,418), fill=BORDER)
        for i, name in enumerate(PAGES):
            rect = (8+i*76, 424, 80+i*76, 474)
            selected = name == page
            if selected:
                self.draw.rounded_rectangle(rect, radius=10, fill=(23,55,49))
            color = GREEN if selected else MUTED
            self.icon(name, rect[0]+36, 440, color)
            self.text((rect[0]+36, 460), "Přehled" if name == "home" else TITLES[name], 11,
                      color, anchor="mm")
            self.hits.append(Hit(rect, ("page", name)))

    def chart(self, rect, samples, color, unit, label_size=10, line_width=2):
        x0,y0,x1,y1 = rect
        points = [(number(t), number(v)) for t,v in samples]
        points = [(t,v) for t,v in points if t is not None and v is not None]
        points.sort()
        if len(points) < 2 or points[0][0] == points[-1][0]:
            self.text(((x0+x1)/2,(y0+y1)/2-8), "Zatím málo dat", 17, MUTED, anchor="mm")
            self.text(((x0+x1)/2,(y0+y1)/2+16), "Graf se doplní při načítání", max(11,label_size), MUTED, anchor="mm", width=x1-x0-8)
            return
        values = [v for _,v in points]
        low, high = min(values), max(values)
        span = max(high-low, 1 if unit == "°C" else 0.1)
        low, high = low-span*.15, high+span*.15
        if unit == "W":
            low = max(0, low)
        widest = max(self.draw.textlength(fmt(value,1),font=font(label_size,path=self.font_path)) for value in (low,high))
        left, right, top, bottom = x0+max(34,math.ceil(widest)+6), x1-2, y0+5, y1-label_size-10
        for i in range(3):
            yy = top+i*(bottom-top)/2
            self.draw.line((left,yy,right,yy), fill=BORDER)
            self.text((left-6,yy), fmt(high-i*(high-low)/2, 1), label_size, MUTED, anchor="rm")
        self.text((x0, y0-label_size-2), unit, label_size, MUTED)
        start, end = points[0][0], points[-1][0]
        intervals = [b[0]-a[0] for a,b in zip(points,points[1:]) if b[0]>a[0]]
        gap = max(180 if unit == "W" else 1800, statistics.median(intervals)*3)
        previous = None
        for t,v in points:
            point = (left+(t-start)/(end-start)*(right-left), bottom-(v-low)/(high-low)*(bottom-top))
            if previous and t-previous[0] <= gap:
                self.draw.line((previous[1],point), fill=color, width=line_width)
            previous = (t,point)
        different_day = datetime.fromtimestamp(start).date()!=datetime.fromtimestamp(end).date()
        for t,x,anchor in ((start,left,"la"),(end,right,"ra")):
            self.text((x,bottom+6), datetime.fromtimestamp(t).strftime("%d.%m. %H:%M" if different_day else "%H:%M"), label_size, MUTED, anchor=anchor)


def layout_for(size, layout="auto"):
    if layout not in ("auto","portrait","landscape"):
        raise ValueError("layout musí být auto, portrait nebo landscape.")
    return ("landscape" if size[0]>size[1] else "portrait") if layout=="auto" else layout


def fit_canvas(c, size):
    """Shodný přepočet bitmapy a dotykových oblastí, včetně okrajů."""
    if size==c.image.size:
        return c.image,c.hits
    width,height = c.image.size
    scale = min(size[0]/width,size[1]/height)
    target = (round(width*scale),round(height*scale))
    x,y = (size[0]-target[0])//2,(size[1]-target[1])//2
    image = Image.new("RGB",size,BG)
    image.paste(c.image.resize(target,Image.Resampling.LANCZOS),(x,y))
    sx,sy = target[0]/width,target[1]/height
    hits = [Hit((x+h.rect[0]*sx,y+h.rect[1]*sy,x+h.rect[2]*sx,y+h.rect[3]*sy),h.action) for h in c.hits]
    return image,hits


def render(page, model, window=24, timer_dialog=False, size=(320,480), font_path="/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", layout="auto"):
    """Vrací bitmapu a dotykové oblasti; samostatný profil na výšku i šířku."""
    if layout_for(size,layout)=="landscape":
        from infopanel_landscape import render_landscape
        return render_landscape(page,model,window,timer_dialog,size,font_path)
    c = Canvas(font_path)
    now = model.get("now") or datetime.now()
    heater, plug = model.get("heater") or {}, model.get("plug") or {}
    meteo, system = model.get("meteo") or {}, model.get("system") or {}
    c.text((12,6), "HanzHub", 24, GREEN, True)
    c.text((165,17), HEADER_VERSION, 12, MUTED)
    c.hits.append(Hit((8,0,210,50),("page","system" if page=="home" else "home")))
    c.text((308,12), now.strftime("%H:%M:%S"), 16, WHITE, anchor="ra")
    message = model.get("message")
    if message:
        c.text((12,36), message, 11, AMBER, width=296)
    h_active = usable(heater) and not model.get("busy")
    p_active = usable(plug) and not model.get("busy")
    ht = heater if usable(heater) and heater["power"] else {}

    if page == "system":
        from infopanel_landscape import byte_label, firmware_label
        from infopanel_system import warnings
        c.card((8,58,312,249),BLUE)
        c.text((20,70),"Raspberry Pi · "+str(system.get("uptime","—")),16,WHITE,True,width=280)
        c.text((20,100),"CPU "+fmt(system.get("cpu"),0," %")+" · RAM "+fmt(system.get("ram"),0," %"),14,WHITE,width=280)
        c.text((20,124),"Volno "+byte_label(system.get("disk_free"))+" · "+fmt(system.get("temp"),1," °C"),14,WHITE,width=280)
        c.text((20,148),str(system.get("iface","—"))+" · "+str(system.get("ip") or "Bez sítě"),14,WHITE,width=280)
        c.text((20,172),"RX "+byte_label(system.get("rx_rate"),True)+" · TX "+byte_label(system.get("tx_rate"),True),13,WHITE,width=280)
        label,color = firmware_label(system.get("flags"))
        c.text((20,196),label,14,color,width=280)
        c.text((20,222),"! "+" · ".join(warnings(model)) if warnings(model) else "Žádné zjištěné varování",12,AMBER,width=280)
        services = model.get("services")
        items = services.get("items",[]) if services else []
        pages = max(1,(len(items)+3)//4)
        section = min(model.get("services_page",0),pages-1)
        c.text((12,258),"Služby "+(f"{services['online']}/{services['total']}" if services else "—"),16,WHITE,True)
        for i,item in enumerate(items[section*4:(section+1)*4]):
            c.text((12,285+i*20),item["name"],13,WHITE,width=216)
            c.text((308,285+i*20),"Online" if item["online"] else "Offline",13,GREEN if item["online"] else AMBER,anchor="ra")
        if pages>1:
            c.button((8,369,104,415),"←",("services_page",section-1),active=section>0)
            c.text((160,391),f"{section+1}/{pages}",13,MUTED,anchor="mm")
            c.button((216,369,312,415),"→",("services_page",section+1),active=section<pages-1)
    elif page == "home":
        c.card((8,58,312,146), BLUE, ("page","meteo"))
        c.icon("meteo",29,76,BLUE)
        c.text((47,65), "Meteo", 15, WHITE, True)
        c.text((20,87), fmt(meteo.get("temp"),1," °C"), 34, WHITE, True)
        c.text((300,76), fmt(meteo.get("soc"),0," %"), 14, AMBER if number(meteo.get("soc")) is not None and meteo["soc"]<20 else GREEN, anchor="ra")
        c.text((20,126), meteo.get("last_label","Bez dat") + (" · starší data" if meteo.get("stale") else ""), 11, AMBER if meteo.get("stale") else MUTED, width=280)
        c.card((8,156,312,274), AMBER, ("page","heater"))
        c.icon("heater",29,175,AMBER)
        c.text((47,164), "Infrapanel", 15, WHITE, True)
        c.badge(300,164,heater)
        for x,label,field in ((20,"Aktuální","current_temp_c"),(174,"Cílová","target_temp_c")):
            c.text((x,198), label, 12, MUTED)
            c.text((x,214), fmt(ht.get(field),0," °C"), 30, WHITE, True)
        c.text((20,253), "Chyba E1: teplotní čidlo" if heater.get("fault_code") else model.get("heater_room", ""), 11,
               RED if heater.get("fault_code") else MUTED, width=280)
        c.card((8,284,312,370), GREEN, ("page","plug"))
        c.icon("plug",29,304,GREEN)
        c.text((47,292), "Zásuvka", 15, WHITE, True)
        c.badge(300,292,plug)
        c.text((20,320), fmt(plug.get("power_w") if usable(plug) else None,1," W"), 29, WHITE, True)
        c.text((300,325), "Dnes", 11, MUTED, anchor="ra")
        c.text((300,342), fmt(plug.get("energy_today_kwh") if usable(plug) else None,3," kWh"), 14, WHITE, anchor="ra")
        c.text((12,384), "CPU", 11, MUTED)
        c.text((85,382), fmt(system.get("cpu"),0," %"), 12, WHITE, anchor="ra",width=44)
        c.text((308,382), fmt(system.get("temp"),1," °C"), 12, WHITE, anchor="ra",width=96)
        c.text((12,402), "RAM", 10, MUTED)
        c.text((89,402), fmt(system.get("ram"),0," %"), 10, WHITE,anchor="ra",width=49)
        c.text((102,402), "Disk", 10, MUTED)
        c.text((177,402), fmt(system.get("disk"),0," %"), 10, WHITE,anchor="ra",width=49)
        c.text((308,402), str(system.get("uptime","—")), 10, WHITE,anchor="ra",width=110)
    elif page == "meteo":
        c.card((8,58,312,140),BLUE)
        c.text((20,66), "Aktuální teplota" if not meteo.get("stale") else "Poslední teplota", 12, MUTED)
        c.text((20,84), fmt(meteo.get("temp"),1," °C"), 33, WHITE, True)
        c.text((300,79), "Baterie "+fmt(meteo.get("soc"),0," %"), 12, GREEN, anchor="ra")
        c.text((300,100), fmt(meteo.get("vbat"),3," V"), 12, MUTED, anchor="ra")
        c.text((20,123), meteo.get("last_label","Bez dat")+(" · starší data" if meteo.get("stale") else ""), 10,
               AMBER if meteo.get("stale") else MUTED, width=280)
        for i,hours in enumerate((1,6,24)):
            c.button((8+i*104,150,104+i*104,196), str(hours)+" h", ("window",hours), selected=hours==window)
        samples = model.get("meteo_history",[])
        c.card((8,206,312,352))
        c.chart((16,225,304,340),samples,BLUE,"°C")
        values = [number(v) for _,v in samples if number(v) is not None]
        c.text((12,364), "Minimum  "+fmt(min(values) if values else None,1," °C"), 13, WHITE)
        c.text((308,364), "Maximum  "+fmt(max(values) if values else None,1," °C"), 13, WHITE, anchor="ra")
        c.text((12,395), "Záznamy z meteostanice · posledních "+str(window)+" h", 10, MUTED, width=296)
    elif page == "heater":
        c.badge(306,59,heater)
        c.text((14,63), model.get("heater_room", "") or "Termostat", 12, MUTED, width=170)
        c.draw.arc((75,78,245,248),135,405,fill=BORDER,width=7)
        target = number(model.get("target_draft_c",ht.get("target_temp_c")))
        if target is not None:
            c.draw.arc((75,78,245,248),135,135+270*target/37,fill=AMBER,width=7)
        c.text((160,125), "Nový cíl" if model.get("target_draft_c") is not None else "Cílová teplota", 12, MUTED, anchor="mm")
        c.text((160,164), fmt(target,0)+("°" if target is not None else ""), 48, WHITE, True, anchor="mm")
        c.text((160,204), "Aktuálně "+fmt(ht.get("current_temp_c"),0," °C"), 15, WHITE, anchor="mm")
        c.text((160,226), "Chyba E1: čidlo" if heater.get("fault_code") else "", 11, RED, anchor="mm")
        current_target = model.get("target_draft_c",heater.get("target_temp_c"))
        can_temp = h_active and type(current_target) is int and 0<=current_target<=37
        c.button((12,249,80,297), "−", ("temperature",-1),
                 active=can_temp and current_target>0,size=28)
        c.text((160,273), "Změnit cíl", 13, MUTED, anchor="mm")
        c.button((240,249,308,297), "+", ("temperature",1),
                 active=can_temp and current_target<37,size=25)
        c.button((12,307,156,355), "Vypnout" if heater.get("power") else "Zapnout", ("command","heater","power",not heater.get("power")),
                 active=h_active,color=GREEN if heater.get("power") else RED)
        c.button((164,307,308,355), "Odemknout" if heater.get("locked") else "Zamknout", ("command","heater","locked",not heater.get("locked")),
                 active=h_active and type(heater.get("locked")) is bool)
        minutes = heater.get("timer_minutes")
        timer = "—" if type(minutes) is not int else ("vypnutý" if minutes==0 else f"{minutes//60}:{minutes%60:02d}")
        c.button((12,365,308,413), "Časovač: "+timer, ("timer","open"), active=h_active)
    elif page == "plug":
        c.badge(306,59,plug)
        c.text((14,63), model.get("plug_room", "") or "Aktuální příkon", 12, MUTED, width=170)
        c.text((160,107), fmt(plug.get("power_w") if usable(plug) else None,1," W"), 35, WHITE, True, anchor="mm")
        for x,label,field in ((12,"Dnes","energy_today_kwh"),(174,"Tento měsíc","energy_month_kwh")):
            c.text((x,137),label,11,MUTED)
            c.text((x,154),fmt(plug.get(field) if usable(plug) else None,3," kWh"),17,WHITE,True)
        for i,hours in enumerate((1,6,24)):
            c.button((8+i*104,183,104+i*104,229), str(hours)+" h", ("window",hours), selected=hours==window)
        c.card((8,239,312,353))
        c.chart((16,257,304,343),model.get("plug_history",[]),GREEN,"W")
        c.text((160,363), "Historie příkonu uložená na HUBu", 10, MUTED, anchor="mm")
        c.button((12,370,308,414), "Vypnout zásuvku" if plug.get("power") else "Zapnout zásuvku", ("command","plug","power",not plug.get("power")),
                 active=p_active,color=GREEN if plug.get("power") else RED)
    c.nav(page)
    if timer_dialog:
        c.hits[:] = [hit for hit in c.hits if hit.action==("page","home") and hit.rect[3]<=50]
        shade = Image.new("RGB",c.image.size,BG)
        c.image = Image.blend(c.image,shade,.75)
        c.draw = ImageDraw.Draw(c.image)
        c.card((12,112,308,409))
        c.text((160,135),"Nastavit časovač",19,WHITE,True,anchor="mm")
        for i,hours in enumerate((0,1,2,4,8,24)):
            x,y = 24+(i%2)*142,163+(i//2)*57
            c.button((x,y,x+130,y+49), "Vypnout" if hours==0 else str(hours)+" h", ("command","heater","timer_minutes",hours*60),active=h_active)
        c.button((24,344,296,395),"Zpět",("timer","close"))
        c.text((12,6), "HanzHub", 24, GREEN, True)
        c.text((165,17), HEADER_VERSION, 12, MUTED)
    return fit_canvas(c,size)
