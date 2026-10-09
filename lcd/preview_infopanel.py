#!/usr/bin/env python3
"""Náhledy skutečného rendereru s ukázkovými daty, bez přístupu k zařízením."""
import argparse
from datetime import datetime
import math
from pathlib import Path

from PIL import Image, ImageDraw
from infopanel_ui import BG, MUTED, PAGES, TITLES, font, render


def demo_model():
    now = datetime(2026,10,8,21,9)
    start = now.timestamp()-24*3600
    meteo = [(start+i*600,18.8+2*math.sin(i/27)+.8*math.sin(i/9)) for i in range(145)]
    plug = [(start+i*60,9.9+.4*math.sin(i/24)+(.9 if 430<i<570 else 0)) for i in range(1441)]
    return {"now":now,"system":{"cpu":2,"ram":16,"disk":57,"temp":46.9,"uptime":"00:58","ip":"192.168.1.3"},
            "services":{"online":7,"total":8},"heater_id":"123456abcdef","plug_id":"abcdef123456",
            "meteo":{"temp":21.48,"vbat":3.728,"soc":27,"last_label":"21:00 · 08.10.26","stale":False},
            "heater":{"online":True,"power":True,"current_temp_c":24,"target_temp_c":25,"locked":False,"timer_minutes":0,"fault_code":0},
            "plug":{"online":True,"power":True,"power_w":9.9,"energy_today_kwh":.017,"energy_month_kwh":.019,"voltage_v":229.7,"current_a":.061},
            "heater_name":"Infrapanel BOT","heater_room":"Kancl","plug_name":"TP-Link Tapo P110M","plug_room":"Kancl",
            "meteo_history":meteo,"plug_history":plug,"busy":False,"message":""}


def portrait_previews(output):
    composite = Image.new("RGB",(1376,548),BG)
    draw = ImageDraw.Draw(composite)
    model = demo_model()
    for i,page in enumerate(PAGES):
        image,_ = render(page,model)
        image.save(output/(page+".png"))
        x = 20+i*340
        composite.paste(image,(x,40))
        draw.text((x+160,18),"Přehled" if page=="home" else TITLES[page],font=font(16,True),fill=MUTED,anchor="mm")
    draw.text((688,535),"HanzHub · Infopanel v2 · ukázková data · obrazovky 320 × 480",font=font(13),fill=MUTED,anchor="mm")
    composite.save(output/"infopanel-v2.png")
    model.update(heater={"online":False},plug={"online":False},meteo={})
    render("home",model)[0].save(output/"offline.png")
    model = demo_model()
    model["heater"]["power"] = False
    model["plug"]["power"] = False
    render("home",model)[0].save(output/"off.png")
    render("heater",demo_model(),timer_dialog=True)[0].save(output/"timer.png")
    print(output/"infopanel-v2.png")


def landscape_previews(output):
    composite = Image.new("RGB",(1064,728),BG)
    draw = ImageDraw.Draw(composite)
    for i,page in enumerate(PAGES):
        image,_ = render(page,demo_model(),size=(1024,600))
        image.save(output/("landscape-"+page+".png"))
        x,y = 10+(i%2)*532,38+(i//2)*340
        composite.paste(image.resize((512,300),Image.Resampling.LANCZOS),(x,y))
        draw.text((x+256,y-20),"Přehled" if page=="home" else TITLES[page],font=font(16,True),fill=MUTED,anchor="mm")
    draw.text((532,708),"HanzHub · Infopanel v2.2.0 · ukázková data · obrazovky 1024 × 600",font=font(13),fill=MUTED,anchor="mm")
    composite.save(output/"infopanel-landscape.png")
    model = demo_model()
    model.update(heater={"online":False},plug={"online":False},meteo={})
    render("home",model,size=(1024,600))[0].save(output/"landscape-offline.png")
    model = demo_model()
    model["heater"]["power"] = model["plug"]["power"] = False
    render("home",model,size=(1024,600))[0].save(output/"landscape-off.png")
    render("heater",demo_model(),size=(1024,600),timer_dialog=True)[0].save(output/"landscape-timer.png")
    model = demo_model()
    model.update(target_draft_c=29,temperature_waiting=True,
                 message="Nový cíl 29 °C · odešlu po 2 s bez klepnutí")
    render("heater",model,size=(1024,600))[0].save(output/"landscape-temperature-draft.png")
    print(output/"infopanel-landscape.png")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=Path(__file__).resolve().parents[1]/"docs")
    parser.add_argument("--layout",choices=("portrait","landscape","both"),default="both")
    args = parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    if args.layout in ("portrait","both"):
        portrait_previews(args.output)
    if args.layout in ("landscape","both"):
        landscape_previews(args.output)


if __name__=="__main__":
    main()
