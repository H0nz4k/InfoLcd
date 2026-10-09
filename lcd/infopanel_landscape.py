"""Nativní dotykové rozložení pro HDMI LCD 1024 × 600 na šířku."""
from datetime import datetime

from PIL import Image, ImageDraw

from infopanel_ui import (AMBER, BG, BLUE, BORDER, GREEN, MUTED, RED,
                         TITLES, WHITE, Canvas, Hit, fit_canvas, fmt, font, number, status, usable)

SIZE = (1024,600)


def timer_label(state):
    minutes = state.get("timer_minutes") if usable(state) else None
    return "—" if type(minutes) is not int else ("Vypnutý" if minutes==0 else f"{minutes//60}:{minutes%60:02d}")


def gauge(c, center, radius, state, large=False, draft=None):
    x,y = center
    values = state if usable(state) and state["power"] else {}
    target = number(draft if draft is not None else values.get("target_temp_c"))
    rect = (x-radius,y-radius,x+radius,y+radius)
    c.draw.arc(rect,135,405,fill=BORDER,width=7 if large else 5)
    if target is not None:
        c.draw.arc(rect,135,135+270*target/37,fill=AMBER,width=7 if large else 5)
    c.text((x,y-40 if large else y-32),"Nový cíl" if draft is not None else "Cílová teplota",18 if large else 16,MUTED,anchor="mm")
    c.text((x,y+5),fmt(target,0)+("°" if target is not None else ""),76 if large else 52,WHITE,True,anchor="mm")
    c.text((x,y+58 if large else y+50),"Aktuálně "+fmt(values.get("current_temp_c"),0," °C"),21 if large else 18,WHITE,anchor="mm")


def stat(c, x, y, label, value, size=24, color=WHITE, width=None):
    c.text((x,y),label,16,MUTED,width=width)
    c.text((x,y+24),value,size,color,True,width=width)


def window_buttons(c, window):
    for i,hours in enumerate((1,6,24)):
        x = 756+i*78
        c.button((x,100,x+68,160),str(hours)+" h",("window",hours),selected=hours==window,size=16)


def tile_rects(count):
    """Až devět stejně velkých dlaždic, bez prázdných náhradních karet."""
    if not 0<=count<=9:
        raise ValueError("Na jednu stránku se vejde nejvýše devět dlaždic.")
    return [(20+(i%3)*334,138+(i//3)*154,336+(i%3)*334,274+(i//3)*154)
            for i in range(count)]


def service_tile(c, rect, role, model):
    x0,y0,x1,y1 = rect
    data = model.get(role) or {}
    color = {"meteo":BLUE,"heater":AMBER,"plug":GREEN}[role]
    c.card(rect,color,("page",role))
    c.icon(role,x0+27,y0+28,color)
    if role=="meteo":
        secondary = fmt(data.get("soc"),0," %")
        state_color = AMBER if data.get("stale") or number(data.get("soc")) is None or data["soc"]<20 else GREEN
        value = fmt(data.get("temp"),1," °C")
        value_color = AMBER if data.get("stale") else WHITE
        title = "Meteo"
    else:
        label,state_color = status(data)
        secondary = label if label in ("ON","OFF") else "—"
        value = fmt(data.get("target_temp_c"),0," °C") if role=="heater" else fmt(data.get("power_w"),1," W")
        if not usable(data):
            value = "—"
        value_color = WHITE
        title = model.get(role+"_name") or TITLES[role]
    c.text((x1-16,y0+18),secondary,18,state_color,True,anchor="ra")
    reserve = c.draw.textlength(secondary,font=font(18,True,c.font_path))+26
    c.text((x0+48,y0+17),title,18,WHITE,True,width=x1-x0-64-reserve)
    room = model.get(role+"_room")
    if role!="meteo" and room:
        c.text((x0+20,y0+43),room,16,MUTED,width=x1-x0-40)
    c.text(((x0+x1)/2,y0+89),value,44,value_color,True,anchor="mm",width=x1-x0-36)


def overview(c, model):
    roles = model.get("home_tiles",["meteo","heater","plug"])
    for rect,role in zip(tile_rects(len(roles)),roles):
        service_tile(c,rect,role,model)


def system_summary(c, model):
    system = model.get("system") or {}
    services = model.get("services")
    count = str(services["online"])+"/"+str(services["total"]) if services else "—"
    summary = ("CPU "+fmt(system.get("cpu"),0," %")+"   RAM "+fmt(system.get("ram"),0," %")+
               "   Disk "+fmt(system.get("disk"),0," %")+"   "+fmt(system.get("temp"),1," °C")+
               "   Uptime "+str(system.get("uptime","—")))
    c.draw.line((20,75,1004,75),fill=BORDER)
    c.text((20,84),summary,17,MUTED,width=760)
    c.text((1004,84),"Služby "+count,17,GREEN if services and services["online"]==services["total"] else AMBER,anchor="ra")


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
    gauge(c,(273,298),132,heater,large=True,draft=model.get("target_draft_c"))
    c.text((40,469),"Chyba E1: teplotní čidlo" if heater.get("fault_code") else "Cílová teplota 0–37 °C",16,
           RED if heater.get("fault_code") else MUTED,width=466)
    c.card((542,84,1004,500))
    c.text((562,107),"Nastavení termostatu",19,WHITE,True)
    target = model.get("target_draft_c",heater.get("target_temp_c"))
    can_temp = active and type(target) is int and 0<=target<=37
    c.button((562,155,640,219),"−",("temperature",-1),
             active=can_temp and target>0,size=32)
    c.text((773,174),"Nastavený cíl",16,MUTED,anchor="mm")
    c.text((773,202),fmt(target if usable(heater) else None,0," °C"),25,WHITE,True,anchor="mm")
    c.button((906,155,984,219),"+",("temperature",1),
             active=can_temp and target<37,size=30)
    c.button((562,240,984,304),"Vypnout infrapanel" if heater.get("power") else "Zapnout infrapanel",
             ("command","heater","power",not heater.get("power")),active=active,
             color=GREEN if heater.get("power") else RED,size=19)
    c.button((562,322,984,386),"Odemknout" if heater.get("locked") else "Dětský zámek: zamknout",
             ("command","heater","locked",not heater.get("locked")),active=active and type(heater.get("locked")) is bool,size=18)
    c.button((562,404,984,468),"Časovač: "+timer_label(heater),("timer","open"),active=active,size=19)
    c.text((773,485),"Čeká na odeslání…" if model.get("temperature_waiting") else "Změny potvrzuje zařízení",16,MUTED,anchor="mm")


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
    c.hits[:] = [hit for hit in c.hits if hit.action==("page","home")]
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
    c.hits.append(Hit((20,0,190,64),("page","home")))
    if page!="home":
        c.text((208,19),TITLES.get(page,"HanzHub"),21,WHITE,True)
    c.text((816,15),now.strftime("%H:%M:%S"),27,WHITE,anchor="ra")
    c.text((1004,15),now.strftime("%d.%m.%Y"),27,WHITE,anchor="ra")
    message = model.get("message")
    subtitle = system.get("ip") or "Bez sítě"
    c.text((20,54),subtitle,16,MUTED,width=190)
    if page!="home" and message:
        c.text((220,54),message,16,AMBER,width=784)
    {"home":overview,"meteo":lambda canvas,data:weather_page(canvas,data,window),
     "heater":heater_page,"plug":lambda canvas,data:plug_page(canvas,data,window)}.get(page,overview)(c,model)
    if page=="home":
        system_summary(c,model)
        if message:
            c.text((20,111),message,16,AMBER,width=984)
    if timer_dialog:
        timer_modal(c,model)
        c.icon("home",35,30,GREEN)
        c.text((56,15),"HanzHub",24,GREEN,True)
    return fit_canvas(c,size)
