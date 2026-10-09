"""Nativní dotykové rozložení pro HDMI LCD 1024 × 600 na šířku."""
from datetime import datetime

from PIL import Image, ImageDraw

from infopanel_ui import (AMBER, BG, BLUE, BORDER, GREEN, MUTED, RED,
                         TITLES, WHITE, HEADER_VERSION, Canvas, Hit, fit_canvas, fmt, font, number, status, usable)
from infopanel_system import age_label, warnings

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
    if role=="meteo":
        c.text(((x0+x1)/2,y1-23),age_label(data.get("age_seconds")),16,
               AMBER if data.get("stale") else MUTED,anchor="ma",width=x1-x0-36)


def overview(c, model):
    roles = model.get("home_tiles",["meteo","heater","plug"])
    for rect,role in zip(tile_rects(len(roles)),roles):
        service_tile(c,rect,role,model)


def system_summary(c, model):
    system = model.get("system") or {}
    services = model.get("services")
    count = str(services["online"])+"/"+str(services["total"]) if services else "—"
    c.draw.line((20,56,1004,56),fill=BORDER)
    # Labels, values and units have separate fixed columns. A longer value
    # cannot move the following statistic or its unit.
    for x,right,unit_x,label,key in ((20,107,114,"CPU","cpu"),
                                    (144,236,243,"RAM","ram"),
                                    (274,363,370,"Disk","disk")):
        c.text((x,65),label,18,WHITE,True,width=48 if key=="ram" else 44)
        c.text((right,65),fmt(system.get(key),0),18,WHITE,True,anchor="ra",width=40)
        c.text((unit_x,65),"%",18,WHITE,True)
    c.text((477,65),fmt(system.get("temp"),1),18,WHITE,True,anchor="ra",width=69)
    c.text((486,65),"°C",18,WHITE,True)
    c.text((532,65),"Uptime",18,WHITE,True,width=80)
    c.text((624,65),str(system.get("uptime","—")),18,WHITE,True,width=150)
    iot = model.get("iot")
    iot_count = str(iot["online"])+"/"+str(iot["total"]) if iot else "—"
    iot_color = GREEN if iot and iot["online"]==iot["total"] else AMBER
    c.text((806,97),"IoT online",18,iot_color,True,width=118)
    c.text((1004,97),iot_count,18,iot_color,True,anchor="ra",width=72)
    service_color = GREEN if services and services["online"]==services["total"] else AMBER
    c.text((806,65),"Služby",18,service_color,True,width=88)
    c.text((1004,65),count,18,service_color,True,anchor="ra",width=104)
    alerts = warnings(model)
    if alerts:
        c.text((20,99),"! "+" · ".join(alerts),16,
               RED if any(not item.startswith("Meteo:") for item in alerts) else AMBER,True,width=780)
    elif model.get("message"):
        c.text((20,99),model["message"],16,AMBER,width=780)


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
    c.text((40,468),age_label(meteo.get("age_seconds"))+(" · starší data" if meteo.get("stale") else ""),16,
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


def byte_label(value, rate=False):
    if number(value) is None or value < 0:
        return "—"
    units = ("B","KiB","MiB","GiB","TiB")
    index = 0
    while value >= 1024 and index < len(units)-1:
        value /= 1024
        index += 1
    return fmt(value,1," "+units[index]+("/s" if rate else ""))


def firmware_label(flags):
    if type(flags) is not int:
        return "Napájení: neznámé", AMBER
    return ("Napájení: PODPĚTÍ", RED) if flags & 1 else ("Napájení: bez podpětí", GREEN)


def firmware_history(flags):
    if type(flags) is not int:
        return "Firmware: údaje nedostupné"
    labels = [name for bit,name in ((16,"podpětí"),(17,"omezení frekvence"),(18,"throttling"),(19,"teplotní limit")) if flags & (1<<bit)]
    return "Dříve: "+", ".join(labels) if labels else "Dřívější problémy: žádné hlášené"


def system_page(c, model):
    system, services, iot = model.get("system") or {}, model.get("services"), model.get("iot")
    c.card((20,84,504,582),BLUE)
    c.text((40,104),"Raspberry Pi",22,WHITE,True)
    c.text((484,108),"Uptime "+str(system.get("uptime","—")),16,MUTED,anchor="ra")
    stat(c,40,146,"CPU",fmt(system.get("cpu"),0," %"),26,width=206)
    stat(c,266,146,"RAM",fmt(system.get("ram"),0," %"),26,width=218)
    stat(c,40,215,"Volné místo /",byte_label(system.get("disk_free")),26,
         color=AMBER if any("disku" in w for w in warnings(model)) else WHITE,width=206)
    stat(c,266,215,"Teplota CPU",fmt(system.get("temp"),1," °C"),26,
         color=RED if number(system.get("temp")) is not None and system["temp"]>=80 else WHITE,width=218)
    c.draw.line((40,279,484,279),fill=BORDER)
    link = system.get("link")
    c.text((40,295),"Síť · "+str(system.get("iface","—")),18,WHITE,True,width=318)
    c.text((484,295),"UP" if link is True else "DOWN" if link is False else "—",18,
           GREEN if link else AMBER,True,anchor="ra")
    c.text((40,323),system.get("ip") or "Bez IPv4 adresy",20,WHITE,True,width=444)
    stat(c,40,361,"Příjem",byte_label(system.get("rx_rate"),True),21,width=206)
    stat(c,266,361,"Odesílání",byte_label(system.get("tx_rate"),True),21,width=218)
    stat(c,40,423,"Přijato celkem",byte_label(system.get("rx_bytes")),20,width=206)
    stat(c,266,423,"Odesláno celkem",byte_label(system.get("tx_bytes")),20,width=218)
    label,color = firmware_label(system.get("flags"))
    c.text((40,491),label,18,color,True,width=444)
    history = firmware_history(system.get("flags"))
    # Wrap the finite firmware history without hiding a second reported fault.
    words, lines, line = history.split(), [], ""
    for word in words:
        candidate = (line+" "+word).strip()
        if c.draw.textlength(candidate,font=font(16,False,c.font_path))>444:
            lines.append(line)
            line = word
        else:
            line = candidate
    for i,line in enumerate(lines+[line]):
        c.text((40,526+i*21),line,16,MUTED,width=444)
    c.card((520,84,1004,582))
    count = f"{services['online']}/{services['total']} dostupných" if services else "Stav nedostupný"
    c.text((540,105),"Služby HanzHub",22,WHITE,True)
    c.text((984,110),count,16,GREEN if services and services["online"]==services["total"] else AMBER,anchor="ra")
    c.text((540,143),"Monitorovaná IoT: "+(f"{iot['online']}/{iot['total']} online" if iot else "stav neznámý"),17,WHITE,True,width=444)
    items = services.get("items",[]) if services else []
    pages = max(1,(len(items)+7)//8)
    page = min(max(0,model.get("services_page",0)),pages-1)
    for i,item in enumerate(items[page*8:(page+1)*8]):
        y = 183+i*27
        c.text((540,y),item["name"],18,WHITE,width=330)
        c.text((984,y),"Online" if item["online"] else "Offline",17,GREEN if item["online"] else AMBER,True,anchor="ra")
    if not items:
        c.text((540,189),"Čekám na přehled služeb" if not services else "Žádné služby",18,MUTED,width=444)
    if pages>1:
        c.button((540,410,656,470),"←",("services_page",page-1),active=page>0,size=24)
        c.text((762,440),f"{page+1}/{pages}",18,MUTED,anchor="mm")
        c.button((868,410,984,470),"→",("services_page",page+1),active=page<pages-1,size=24)
    alerts = warnings(model)
    if alerts:
        for i,alert in enumerate(alerts):
            c.text((540,484+i*18),"! "+alert,16,AMBER if alert.startswith("Meteo:") else RED,True,width=444)
    else:
        c.text((540,514),"Žádné zjištěné varování",18,MUTED,width=444)
    if not system:
        c.text((540,553),"Systémové údaje nedostupné",16,AMBER,width=444)


def brand(c, page, with_hit=True):
    c.icon("home",35,31,GREEN)
    c.text((56,9),"HanzHub",30,GREEN,True)
    c.text((228,25),HEADER_VERSION,14,MUTED)
    if with_hit:
        c.hits.append(Hit((20,0,292,64),("page","system" if page=="home" else "home")))


def render_landscape(page, model, window, timer_dialog, size, font_path):
    c = Canvas(font_path,SIZE)
    now = model.get("now") or datetime.now()
    brand(c,page)
    c.text((816,15),now.strftime("%H:%M:%S"),27,WHITE,anchor="ra")
    c.text((1004,15),now.strftime("%d.%m.%Y"),27,WHITE,anchor="ra")
    message = model.get("message")
    if page!="home" and message:
        c.text((20,54),message,16,AMBER,width=984)
    {"home":overview,"meteo":lambda canvas,data:weather_page(canvas,data,window),
     "heater":heater_page,"plug":lambda canvas,data:plug_page(canvas,data,window),
     "system":system_page}.get(page,overview)(c,model)
    if page=="home":
        system_summary(c,model)
    if timer_dialog:
        timer_modal(c,model)
        brand(c,page,with_hit=False)
    return fit_canvas(c,size)
