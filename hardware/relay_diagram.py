#!/usr/bin/env python3
"""Schéma podsvícení: dvě vektorové stránky PDF; nejde o ovládací program GPIO."""
from pathlib import Path
import math

from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "backlight-relay.pdf"
W,H = landscape(A4)
NAVY = "#101e32"
GREEN = "#00895c"
GRAY = "#526275"
LINE = "#d6e0e9"
BLUE = "#1566ae"
RED = "#be3237"
ORANGE = "#b76b10"
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
pdfmetrics.registerFont(TTFont("DejaVu",FONT))
pdfmetrics.registerFont(TTFont("DejaVuBold",FONT.replace(".ttf","-Bold.ttf")))


def text(c,x,y,value,size=11,color=NAVY,bold=False,align="left"):
    c.setFillColor(HexColor(color))
    c.setFont("DejaVuBold" if bold else "DejaVu",size)
    method = {"left":c.drawString,"right":c.drawRightString,"center":c.drawCentredString}[align]
    method(x,H-y,str(value))


def box(c,x,y,w,h,fill=None,stroke=LINE,radius=0):
    c.setStrokeColor(HexColor(stroke))
    c.setFillColor(HexColor(fill or "#ffffff"))
    c.setLineWidth(1)
    if radius:
        c.roundRect(x,H-y-h,w,h,radius,fill=bool(fill),stroke=True)
    else:
        c.rect(x,H-y-h,w,h,fill=bool(fill),stroke=True)


def paragraph(c,x,y,value,width,size=10,leading=15,color=GRAY):
    words=value.split(); line=""
    for word in words:
        candidate=(line+" "+word).strip()
        if pdfmetrics.stringWidth(candidate,"DejaVu",size)>width and line:
            text(c,x,y,line,size,color); y+=leading; line=word
        else: line=candidate
    if line: text(c,x,y,line,size,color); y+=leading
    return y


def header(c,title,subtitle,page):
    box(c,0,0,W,78,NAVY,NAVY)
    text(c,32,29,"HanzHub",16,"#34d399",True)
    text(c,32,57,title,23,"#ffffff",True)
    text(c,32,99,subtitle,10,GRAY)
    text(c,W-32,29,"HW návrh · 08.10.2026",9,"#cfdae6",align="right")
    text(c,32,H-18,"G5V-1-DC5 · logika NC = svítí · konkrétní plošky LCD vyžadují ověření",8,GRAY)
    text(c,W-32,H-18,f"{page} / 2",8,GRAY,align="right")


class Diagram:
    """Souřadnice shora, pro čitelné přesné vektorové schéma."""
    def __init__(self,c): self.c=c
    def line(self,points,color=NAVY,width=2,dashed=False):
        c=self.c;c.setStrokeColor(HexColor(color));c.setLineWidth(width)
        c.setDash(6,5) if dashed else c.setDash()
        p=c.beginPath();p.moveTo(points[0][0],-points[0][1])
        for x,y in points[1:]:p.lineTo(x,-y)
        c.drawPath(p);c.setDash()
    def rect(self,x,y,w,h,color=NAVY,fill=None):
        c=self.c;c.setStrokeColor(HexColor(color));c.setLineWidth(2)
        c.setFillColor(HexColor(fill or "#ffffff"));c.rect(x,-y-h,w,h,stroke=True,fill=bool(fill))
    def label(self,x,y,value,size=17,color=NAVY,bold=False,center=False):
        c=self.c;c.setFont("DejaVuBold" if bold else "DejaVu",size);c.setFillColor(HexColor(color))
        (c.drawCentredString if center else c.drawString)(x,-y,value)
    def dot(self,x,y,color=NAVY,r=4,open=False):
        c=self.c;c.setFillColor(HexColor("#ffffff" if open else color));c.setStrokeColor(HexColor(color));c.setLineWidth(2)
        c.circle(x,-y,r,fill=True,stroke=True)
    def triangle(self,points,color=NAVY):
        c=self.c;c.setFillColor(HexColor(color));c.setStrokeColor(HexColor(color))
        p=c.beginPath();p.moveTo(points[0][0],-points[0][1])
        for x,y in points[1:]:p.lineTo(x,-y)
        p.close();c.drawPath(p,fill=True,stroke=False)
    def arrow(self,start,end,color=NAVY):
        self.line([start,end],color)
        dx,dy=end[0]-start[0],end[1]-start[1];length=math.hypot(dx,dy);ux,uy=dx/length,dy/length
        self.triangle([end,(end[0]-13*ux+5*uy,end[1]-13*uy-5*ux),(end[0]-13*ux-5*uy,end[1]-13*uy+5*ux)],color)


def circuit(c):
    c.saveState();c.translate(32,H-114);c.scale((W-64)/1400,(W-64)/1400)
    d=Diagram(c)
    d.label(25,26,"OVLÁDÁNÍ CÍVKY",19,BLUE,True)
    d.label(820,26,"NÁHRADA PŘEPÍNAČE LCD",19,ORANGE,True)
    d.line([(760,45),(760,560)],LINE,1,dashed=True)

    # Napájecí větev; C1 je na napájení, nikoli přímo přes cívku.
    d.line([(25,130),(660,130)],RED)
    d.dot(85,130,RED,open=True);d.label(85,108,"+5 V / RPi pin 2",18,RED)
    d.line([(25,130),(25,221)],RED)
    d.line([(10,221),(40,221)]);d.line([(10,233),(40,233)])
    d.line([(25,233),(25,480)],GRAY)
    d.label(50,218,"C1 100 nF",16);d.label(50,241,"+5 V - GND",14,GRAY)
    d.line([(25,480),(660,480)],GRAY)
    d.dot(85,480,GRAY,open=True);d.label(85,511,"GND / RPi pin 6",18,GRAY)

    # Cívka K1 a antiparalelní dioda D1.
    d.line([(530,130),(530,158)],RED)
    d.rect(510,158,40,64)
    d.line([(530,222),(530,262)])
    d.label(443,74,"K1",20,bold=True);d.label(443,96,"Cívka 5 V / 30 mA",16)
    d.label(560,160,"2",16,RED);d.label(560,246,"9",16)
    d.dot(530,130,RED);d.dot(530,262)
    d.line([(660,130),(660,180)],RED)
    d.line([(646,180),(674,180)])
    d.triangle([(660,184),(647,213),(673,213)])
    d.line([(660,213),(660,262),(530,262)])
    d.label(682,193,"D1",17,bold=True);d.label(682,216,"1N4007",15)
    d.label(659,105,"Proužek",14,RED);d.label(659,123,"na +5 V",14,RED)

    # Vstup GPIO, R1, R2 a NPN tranzistor Q1.
    d.dot(85,325,BLUE,open=True)
    d.label(85,289,"GPIO17 / pin 11",18,BLUE)
    d.label(85,308,"BCM17, logika 3,3 V",14,BLUE)
    d.line([(85,325),(198,325)],BLUE)
    d.rect(198,314,75,22,BLUE)
    d.line([(273,325),(340,325),(462,325)],BLUE)
    d.label(206,359,"R1 1k",16,BLUE)
    d.dot(340,325,BLUE)
    d.line([(340,325),(340,380)],BLUE)
    d.rect(329,380,22,53)
    d.line([(340,433),(340,480)],GRAY)
    d.dot(340,480,GRAY)
    d.label(275,404,"R2",16);d.label(264,426,"10k",16)
    # BJT s šipkou ven z emitoru (NPN).
    c.setStrokeColor(HexColor(NAVY));c.setLineWidth(2);c.circle(493,-325,45,fill=False,stroke=True)
    d.line([(480,301),(480,349)])
    d.line([(462,325),(480,325)],BLUE)
    d.line([(480,312),(523,286),(530,286),(530,262)])
    d.line([(480,338),(523,364),(530,364),(530,480)])
    d.arrow((501,351),(523,364))
    d.dot(530,480,GRAY)
    d.label(557,326,"Q1 BC337-40",18,bold=True)
    d.label(557,349,"NPN",15,GRAY)
    d.label(444,306,"B",15,BLUE);d.label(537,288,"C",15);d.label(537,386,"E",15,GRAY)
    d.label(85,553,"R1: proud GPIO přibližně 2-3 mA. Cívka čerpá proud z +5 V.",16,GRAY)

    # Tentýž K1, kontakty galvanicky oddělené od ovládací části.
    d.label(835,91,"K1 G5V-1-DC5",19,bold=True)
    d.label(835,115,"Zobrazen klid: COM - NC",16,GRAY)
    d.dot(870,300,r=5,open=True)
    d.line([(870,300),(948,230)],ORANGE,3)
    d.dot(950,230,ORANGE,r=5,open=True)
    d.dot(950,370,ORANGE,r=5,open=True)
    d.line([(950,230),(1210,230)],ORANGE)
    d.line([(950,370),(1210,370)],ORANGE)
    d.line([(870,300),(820,300),(820,445),(1210,445)],ORANGE)
    d.label(837,277,"COM 5/6",16,ORANGE)
    d.label(970,211,"NC: pin 1",17,ORANGE)
    d.label(970,350,"NO: pin 10",17,ORANGE)
    d.rect(1210,161,160,329,ORANGE)
    d.label(1290,191,"LCD",20,ORANGE,True,True)
    for y,label in ((230,"SW_ON"),(370,"SW_OFF*"),(445,"SW_C")):
        d.dot(1210,y,ORANGE,r=5,open=True);d.label(1229,y+24,label,16,ORANGE)
    d.label(835,510,"* SW_OFF jen pokud je na desce použit.",16,GRAY)
    d.label(835,532,"U 2 kontaktů nechat NO nepřipojený.",16,GRAY)
    d.label(835,554,"Původní přepínač odpojit / odpájet.",16,ORANGE)
    c.restoreState()


def table(c,x,y,width,headers,rows,widths,size=9.5):
    heights=[25]+[27 for _ in rows]
    top=y
    for index,row in enumerate([headers]+rows):
        fill=NAVY if index==0 else ("#f1f5f9" if index%2 else "#ffffff")
        box(c,x,top,width,heights[index],fill,LINE)
        cursor=x
        for cell,cell_width in zip(row,widths):
            text(c,cursor+9,top+17,cell,size,"#ffffff" if index==0 else NAVY,index==0)
            cursor+=cell_width
        top+=heights[index]
    return top


def pinout(c,x,y):
    text(c,x,y,"K1: pohled zespodu na vývody",13,NAVY,True)
    text(c,x,y+21,"Orientační značka je vlevo; shora zrcadlově.",9,GRAY)
    box(c,x+5,y+37,300,127,"#f1f5f9",LINE,8)
    c.setFillColor(HexColor(NAVY));c.rect(x+5,H-(y+65)-55,6,55,fill=True,stroke=False)
    for px,py,pin,role,color in ((x+60,y+66,1,"NC",ORANGE),(x+136,y+66,2,"cívka",BLUE),(x+249,y+66,5,"COM",ORANGE),
                                (x+60,y+127,10,"NO",ORANGE),(x+136,y+127,9,"cívka",BLUE),(x+249,y+127,6,"COM",ORANGE)):
        c.setFillColor(HexColor(color));c.circle(px,H-py,5,fill=True,stroke=False)
        text(c,px+10,py+4,str(pin),11,color,True)
        text(c,px,py+22,role,9,GRAY,align="center")
    text(c,x,y+188,"5 a 6 jsou vnitřně spojeny (COM).",10,GRAY)
    text(c,x,y+207,"Cívka: 2 a 9, bez vlastní polarity.",10,GRAY)
    text(c,x,y+226,"Bez buzení: COM - 1; s buzením: COM - 10.",10,GRAY)


def main():
    OUT.parent.mkdir(parents=True,exist_ok=True)
    c=canvas.Canvas(str(OUT),pagesize=(W,H),pageCompression=1)
    c.setTitle("HanzHub - ovládání podsvícení LCD přes Omron G5V-1-DC5")
    c.setAuthor("HanzHub")
    header(c,"Podsvícení LCD přes relé","5V varianta GME 634-639. Návrh pro Raspberry Pi s 40pinovým konektorem a Waveshare LCD Rev3.1.",1)
    circuit(c)
    y=440
    text(c,32,y,"GPIO LOW: podsvícení ON. GPIO HIGH: podsvícení OFF.",12,GREEN,True)
    paragraph(c,32,y+23,"SW_C, SW_ON a SW_OFF označují funkce původního přepínače, nikoli pořadí pájecích plošek. Plošky konkrétního LCD musí být před pájením určeny měřením. Do LCD se připojují pouze kontakty relé; nepřivádět do nich 5 V z Raspberry ani GPIO.",W-64,10,15)
    paragraph(c,32,515,"D1: proužek na +5 V. C/B/E tranzistoru ověř podle jeho výrobce. GPIO17 musí být volné. Návrh dosud nebyl fyzicky sestaven; nejprve ověř spínání samotného relé.",W-64,9.5,14)
    c.showPage()

    header(c,"Součástky a ověření kontaktů","Kontakty LCD určujeme podle původního přepínače. Cívka relé a GPIO zůstávají oddělené od těchto plošek.",2)
    text(c,32,126,"Seznam součástek",14,NAVY,True)
    rows=[("K1","1","G5V-1-DC5, cívka 5 VDC (máš)"),
          ("Q1","1","BC337-40, NPN, TO-92"),("R1","1","1 kohm / 0,25 W"),("R2","1","10 kohm / 0,25 W"),
          ("D1","1","1N4007"),("C1","1","100 nF keramický, alespoň 16 V"),
          ("C2","vol.","47 uF / 16 V: + na +5 V, - na GND"),
          ("Montáž","dle potř.","Destička, vodiče, izolace, konektor")]
    table(c,32,141,442,("Díl","Počet","Hodnota / typ"),rows,(60,70,312),size=9)
    pinout(c,498,126)
    text(c,32,428,"Připojení místo mechanického přepínače",13,NAVY,True)
    y=451
    for value in ("1. Odpoj LCD i Raspberry od napájení, USB a HDMI. Původní přepínač odpájej / odpoj jeho kontakty.",
                  "2. Multimetrem urči společný kontakt SW_C a jeho spojení v polohách ON (SW_ON) a OFF (SW_OFF).",
                  "3. SW_C -> K1 pin 5; SW_ON -> K1 pin 1; použitý SW_OFF -> K1 pin 10. Kotvicí nožičky nejsou kontakty.",
                  "4. U 2 funkčních kontaktů použij jen COM a NC. Plošky při ponechaném přepínači naslepo nezkratuj."):
        y=paragraph(c,32,y,value,W-64,9.5,15)
    text(c,32,530,"Zdroje: Omron G5V-1 (pinout str. 4); onsemi BC337-FSC/D; Raspberry Pi GPIO; Waveshare LCD (C).",8,GRAY)
    links=[("Omron datasheet","https://omronfs.omron.com/en_US/ecb/products/pdf/en-g5v_1.pdf"),
           ("BC337 datasheet","https://www.onsemi.com/pdf/datasheet/bc337-fsc-d.pdf"),
           ("Raspberry GPIO","https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#gpio"),
           ("Podrobný návod","https://github.com/H0nz4k/InfoLcd/blob/main/docs/backlight-relay.md")]
    x=32
    for label,url in links:
        text(c,x,549,label,8.5,BLUE)
        tw=pdfmetrics.stringWidth(label,"DejaVu",8.5)
        c.linkURL(url,(x,H-554,x+tw,H-538),relative=0)
        x+=tw+25
    c.save();print(OUT)


if __name__=="__main__": main()
