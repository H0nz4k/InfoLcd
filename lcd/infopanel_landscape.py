"""Nativní dotykové rozložení pro HDMI LCD 1024 × 600 na šířku."""
from datetime import datetime

from PIL import Image, ImageDraw

from infopanel_ui import (AMBER, BG, BLUE, BORDER, GREEN, MUTED, PAGES, RED,
                         TITLES, WHITE, Canvas, fit_canvas, fmt, number, usable)

SIZE = (1024,600)


def timer_label(state):
    minutes = state.get("timer_minutes") if usable(state) else None
    return "—" if type(minutes) is not int else ("Vypnutý" if minutes==0 else f"{minutes//60}:{minutes%60:02d}")


def heading(c, rect, title, icon, color, state=None, action=None):
    c.card(rect,color,action)
    c.icon(icon,rect[0]+30,rect[1]+29,color)
    c.text((rect[0]+50,rect[1]+17),title,18,WHITE,True)
    if state is not None:
        c.badge(rect[2]-16,rect[1]+16,state,16,28)


def gauge(c, center, radius, state, large=False):
    x,y = center
    values = state if usable(state) and state["power"] else {}
    target = number(values.get("target_temp_c"))
    rect = (x-radius,y-radius,x+radius,y+radius)
    c.draw.arc(rect,135,405,fill=BORDER,width=7 if large else 5)
    if target is not None:
        c.draw.arc(rect,135,135+270*target/37,fill=AMBER,width=7 if large else 5)
    c.text((x,y-40 if large else y-32),"Cílová teplota",18 if large else 16,MUTED,anchor="mm")
    c.text((x,y+5),fmt(target,0)+("°" if target is not None else ""),76 if large else 52,WHITE,True,anchor="mm")
    c.text((x,y+58 if large else y+50),"Aktuálně "+fmt(values.get("current_temp_c"),0," °C"),21 if large else 18,WHITE,anchor="mm")


def stat(c, x, y, label, value, size=24, color=WHITE, width=None):
    c.text((x,y),label,16,MUTED,width=width)
    c.text((x,y+24),value,size,color,True,width=width)


def window_buttons(c, window):
    for i,hours in enumerate((1,6,24)):
        x = 756+i*78
        c.button((x,100,x+68,160),str(hours)+" h",("window",hours),selected=hours==window,size=16)


def navigation(c, page):
    c.draw.line((20,510,1004,510),fill=BORDER)
    for i,name in enumerate(PAGES):
        rect = (20+i*250,520,254+i*250,584)
        selected = name==page
        c.button(rect,"",("page",name),selected=selected)
        x = (rect[0]+rect[2])/2
        color = GREEN if selected else MUTED
        c.icon(name,x-61,552,color)
        c.text((x+15,552),"Přehled" if name=="home" else TITLES[name],17,color,True,anchor="mm")


def overview(c, model):
    meteo,heater,plug,system = (model.get(name) or {} for name in ("meteo","heater","plug","system"))
    heading(c,(20,84,337,452),"Meteo","meteo",BLUE,action=("page","meteo"))
    c.text((40,140),"Poslední teplota" if meteo.get("stale") else "Aktuální teplota",16,MUTED)
    c.text((40,163),fmt(meteo.get("temp"),1," °C"),44,WHITE,True)
    c.text((40,222),"Baterie "+fmt(meteo.get("soc"),0," %")+" · "+fmt(meteo.get("vbat"),3," V"),16,
           AMBER if number(meteo.get("soc")) is not None and meteo["soc"]<20 else GREEN,width=278)
    c.chart((38,273,318,390),model.get("meteo_history",[]),BLUE,"°C",label_size=16)
    c.text((40,421),meteo.get("last_label","Bez dat")+(" · starší data" if meteo.get("stale") else ""),16,
           AMBER if meteo.get("stale") else MUTED,width=278)

    heading(c,(353,84,670,452),"Infrapanel","heater",AMBER,heater,("page","heater"))
    c.text((373,134),model.get("heater_room","") or "Termostat",16,MUTED,width=277)
    gauge(c,(511,254),96,heater)
    c.text((373,364),"Časovač",16,MUTED)
    c.text((650,364),timer_label(heater),16,WHITE,anchor="ra")
    lock = heater.get("locked") if usable(heater) else None
    c.text((373,396),"Dětský zámek",16,MUTED)
    c.text((650,396),"—" if type(lock) is not bool else ("Zamčeno" if lock else "Odemčeno"),16,WHITE,anchor="ra")
    c.text((373,427),"Chyba E1: teplotní čidlo" if heater.get("fault_code") else "Otevřít ovládání →",16,
           RED if heater.get("fault_code") else AMBER,width=277)

    heading(c,(686,84,1004,452),"Zásuvka","plug",GREEN,plug,("page","plug"))
    values = plug if usable(plug) else {}
    c.text((706,140),"Aktuální příkon",16,MUTED)
    c.text((706,163),fmt(values.get("power_w"),1," W"),44,WHITE,True)
    stat(c,706,226,"Dnes",fmt(values.get("energy_today_kwh"),3," kWh"),18,width=134)
    stat(c,856,226,"Tento měsíc",fmt(values.get("energy_month_kwh"),3," kWh"),18,width=130)
    c.chart((704,315,985,390),model.get("plug_history",[]),GREEN,"W",label_size=16)
    c.text((706,421),"Příkon, spotřeba a ovládání →",16,GREEN,width=278)

    c.card((20,466,1004,500))
    c.text((36,483),"Raspberry Pi",16,MUTED,True,anchor="lm")
    summary = ("CPU "+fmt(system.get("cpu"),0," %")+"   RAM "+fmt(system.get("ram"),0," %")+
               "   Disk "+fmt(system.get("disk"),0," %")+"   "+fmt(system.get("temp"),1," °C")+
               "   Uptime "+str(system.get("uptime","—")))
    c.text((988,483),summary,16,WHITE,anchor="rm",width=804)


def weather_page(c, model, window):
    meteo = model.get("meteo") or {}
    c.card((20,84,326,500),BLUE)
    c.text((40,105),"Poslední teplota" if meteo.get("stale") else "Aktuální teplota",17,MUTED)
    c.text((40,135),fmt(meteo.get("temp"),1," °C"),44,WHITE,True)
    battery_color = AMBER if number(meteo.get("soc")) is not None and meteo["soc"]<20 else GREEN
    stat(c,40,213,"Baterie",fmt(meteo.get("soc"),0," %"),27,color=battery_color)
    stat(c,187,213,"Napětí",fmt(meteo.get("vbat"),3," V"),23,width=120)
    samples = model.get("meteo_history",[])
    values = [number(value) for _,value in samples if number(value) is not None]
    stat(c,40,302,"Minimum",fmt(min(values) if values else None,1," °C"),24,width=130)
    stat(c,187,302,"Maximum",fmt(max(values) if values else None,1," °C"),24,width=120)
    c.draw.line((40,387,306,387),fill=BORDER)
    c.text((40,407),"Poslední měření",16,MUTED)
    c.text((40,430),meteo.get("last_label","Bez dat"),17,WHITE,width=266)
    c.text((40,468),"Starší data" if meteo.get("stale") else "Záznamy z meteostanice",16,
           AMBER if meteo.get("stale") else MUTED,width=266)
    c.card((342,84,1004,500))
    c.text((364,112),"Teplota",20,WHITE,True)
    window_buttons(c,window)
    c.chart((362,207,982,441),samples,BLUE,"°C",label_size=16,line_width=3)
    c.text((364,473),"Skutečná měření · posledních "+str(window)+" hodin",16,MUTED,width=610)


def heater_page(c, model):
    heater = model.get("heater") or {}
    active = usable(heater) and not model.get("busy")
    c.card((20,84,526,500),AMBER)
    badge_left = c.badge(506,102,heater,16,30)
    c.text((40,105),model.get("heater_name","") or "Infrapanel",20,WHITE,True,width=badge_left-56)
    c.text((40,137),model.get("heater_room","") or "Termostat",16,MUTED,width=330)
    gauge(c,(273,298),132,heater,large=True)
    c.text((40,469),"Chyba E1: teplotní čidlo" if heater.get("fault_code") else "Cílová teplota 0–37 °C",16,
           RED if heater.get("fault_code") else MUTED,width=466)
    c.card((542,84,1004,500))
    c.text((562,107),"Nastavení termostatu",19,WHITE,True)
    target = heater.get("target_temp_c")
    can_temp = active and type(target) is int and 0<=target<=37
    c.button((562,155,640,219),"−",("command","heater","target_temp_c",target-1 if can_temp else 0),
             active=can_temp and target>0,size=32)
    c.text((773,174),"Nastavený cíl",16,MUTED,anchor="mm")
    c.text((773,202),fmt(target if usable(heater) else None,0," °C"),25,WHITE,True,anchor="mm")
    c.button((906,155,984,219),"+",("command","heater","target_temp_c",target+1 if can_temp else 0),
             active=can_temp and target<37,size=30)
    c.button((562,240,984,304),"Vypnout infrapanel" if heater.get("power") else "Zapnout infrapanel",
             ("command","heater","power",not heater.get("power")),active=active,
             color=GREEN if heater.get("power") else RED,size=19)
    c.button((562,322,984,386),"Odemknout" if heater.get("locked") else "Dětský zámek: zamknout",
             ("command","heater","locked",not heater.get("locked")),active=active and type(heater.get("locked")) is bool,size=18)
    c.button((562,404,984,468),"Časovač: "+timer_label(heater),("timer","open"),active=active,size=19)
    c.text((773,485),"Změny potvrzuje zařízení",16,MUTED,anchor="mm")


def plug_page(c, model, window):
    plug = model.get("plug") or {}
    values = plug if usable(plug) else {}
    active = usable(plug) and not model.get("busy")
    c.card((20,84,426,500),GREEN)
    badge_left = c.badge(406,102,plug,16,30)
    c.text((40,105),model.get("plug_name","") or "Zásuvka",19,WHITE,True,width=badge_left-56)
    c.text((40,138),model.get("plug_room","") or "Aktuální příkon",16,MUTED,width=366)
    c.text((223,206),fmt(values.get("power_w"),1," W"),54,WHITE,True,anchor="mm")
    stat(c,40,266,"Dnes",fmt(values.get("energy_today_kwh"),3," kWh"),23,width=176)
    stat(c,234,266,"Tento měsíc",fmt(values.get("energy_month_kwh"),3," kWh"),23,width=172)
    stat(c,40,344,"Napětí",fmt(values.get("voltage_v"),1," V"),22,width=176)
    stat(c,234,344,"Proud",fmt(values.get("current_a"),3," A"),22,width=172)
    c.button((40,419,406,483),"Vypnout zásuvku" if plug.get("power") else "Zapnout zásuvku",
             ("command","plug","power",not plug.get("power")),active=active,
             color=GREEN if plug.get("power") else RED,size=19)
    c.card((442,84,1004,500))
    c.text((464,112),"Příkon",20,WHITE,True)
    window_buttons(c,window)
    c.chart((462,207,982,441),model.get("plug_history",[]),GREEN,"W",label_size=16,line_width=3)
    c.text((464,473),"Historie na HUBu · posledních "+str(window)+" hodin",16,MUTED,width=510)


def timer_modal(c, model):
    c.hits.clear()
    c.image = Image.blend(c.image,Image.new("RGB",SIZE,BG),.75)
    c.draw = ImageDraw.Draw(c.image)
    c.card((232,122,792,468))
    c.text((512,158),"Nastavit časovač infrapanelu",22,WHITE,True,anchor="mm")
    active = usable(model.get("heater")) and not model.get("busy")
    for i,hours in enumerate((0,1,2,4,8,24)):
        x,y = 256+(i%3)*174,199+(i//3)*83
        c.button((x,y,x+164,y+66),"Vypnout" if hours==0 else str(hours)+" h",
                 ("command","heater","timer_minutes",hours*60),active=active,size=20)
    c.button((256,383,768,447),"Zpět",("timer","close"),size=19)


def render_landscape(page, model, window, timer_dialog, size, font_path):
    c = Canvas(font_path,SIZE)
    now = model.get("now") or datetime.now()
    system = model.get("system") or {}
    c.icon("home",35,30,GREEN)
    c.text((56,15),"HanzHub",24,GREEN,True)
    c.text((208,19),"Přehled" if page=="home" else TITLES.get(page,"HanzHub"),21,WHITE,True)
    c.text((1004,15),now.strftime("%H:%M:%S"),27,WHITE,anchor="ra")
    c.text((834,15),now.strftime("%d.%m.%Y"),27,WHITE,anchor="ra")
    message = model.get("message")
    subtitle = message or (system.get("ip") or "Bez sítě")
    c.text((20,54),subtitle,16,AMBER if message else MUTED,width=984)
    {"home":overview,"meteo":lambda canvas,data:weather_page(canvas,data,window),
     "heater":heater_page,"plug":lambda canvas,data:plug_page(canvas,data,window)}.get(page,overview)(c,model)
    navigation(c,page)
    if timer_dialog:
        timer_modal(c,model)
    return fit_canvas(c,size)
