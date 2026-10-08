# HanzHub · Infopanel v2

Dotykový informační panel pro Raspberry Pi: stručný přehled systému, Meteo a IoT, graf teploty, ovládání infrapanelu BOT IPH2 a zásuvky TP-Link Tapo P110M. Grafika navazuje na tmavý styl HanzHubu. Verze **2.0.0**.

![Čtyři stránky Infopanelu v2 – ukázková data](docs/infopanel-v2.png)

Obrázek vzniká přímo z vykreslovacího kódu. Čísla i průběhy v tomto náhledu jsou **ukázková data**. Nasazená aplikace načítá skutečné údaje.

## Stránky a dotyk

| Stránka | Zobrazení a ovládání |
| --- | --- |
| **Přehled** | Hodiny, IP, teplota Meteo a baterie; infrapanel ON/OFF a při ON aktuální/cílová teplota; příkon a dnešní spotřeba zásuvky. CPU, RAM, disk, teplota Raspberry a uptime ve spodním pásu. |
| **Meteo** | Teplota, baterie, čas posledního měření a graf za 1 / 6 / 24 hodin; minimum a maximum. |
| **Infrapanel** | Cílová a aktuální teplota, tlačítka − / +, zapnutí/vypnutí, dětský zámek a časovač vypnuto / 1 / 2 / 4 / 8 / 24 hodin. Rozsah cíle 0–37 °C. |
| **Zásuvka** | Aktuální příkon, dnešní/měsíční energie, místní graf příkonu za 1 / 6 / 24 hodin a zapnutí/vypnutí. |

Klepnutím na kartu v přehledu otevřeš detail. Spodní lišta je na všech stránkách a umožňuje přímé přepnutí. Po 60 sekundách nečinnosti se displej vrátí na Přehled; interval lze změnit. Aktivní dotykové plochy mají při rozlišení 320 × 480 alespoň 44 pixelů v obou směrech.

**ON je zeleně, OFF červeně, nedostupné zařízení oranžově.** OFF znamená ověřený stav vypnutí; výpadek komunikace se zobrazuje samostatně. Starší Meteo data zůstávají viditelná s upozorněním. Chybějící měření nezobrazujeme jako nulu. ON infrapanelu neznamená, že jeho topné těleso právě odebírá proud.

## Co musí na Raspberry fungovat

- Linux framebuffer `/dev/fbX`, obvykle `/dev/fb0` nebo `/dev/fb1`; podporované formáty RGB565 (16 bitů) a BGRX8888 (32 bitů). Doporučené rozlišení je **320 × 480 na výšku**. Otočení lze převzít z původní služby. Větší rozlišení zachovává poměr stran, případně s okraji.
- Dotyk dostupný přes Linux input/evdev: `ABS_X/Y + BTN_TOUCH` (např. resistivní čidlo), nebo multitouch protokol B se sloty. Ovladač displeje/dotyku musí být už nainstalovaný. Instalátor nezasahuje do boot konfigurace ani SPI overlay.
- Existující [HanzHub IoT služba](https://github.com/H0nz4k/LoT) dostupná na `http://127.0.0.1:4011/api/iot`, s již přidaným infrapanelem a zásuvkou. API lze použít i z jiného počítače v LAN.
- Pro Meteo log `/opt/meteo3/meteo_log.csv`, řádky ve stejném formátu jako původní LCD:

```text
2026-10-08T21:00:00+02:00,{"temp":21.48,"vbat":3.728,"soc":27}
```

Infopanel kreslí přímo na LCD, **nepotřebuje Chromium ani desktop a neotvírá nový webový port**. Stav a příkazy předává existující službě na portu 4011. Neukládá Tapo účet, heslo ani Tuya lokální klíč; ty spravuje IoT služba.

## Instalace na současném HUBu

```bash
sudo apt update
sudo apt install -y git python3-pil python3-psutil python3-evdev fonts-dejavu-core
git clone https://github.com/H0nz4k/InfoLcd.git ~/InfoLcd
cd ~/InfoLcd
sudo python3 install.py
```

Výchozí původní služba je `lcd-info.service`. Instalátor z jejího `ExecStart` převezme framebuffer, otočení, font, Meteo log, síťové rozhraní a URL/ID infrapanelu. Při aktualizaci zachová existující nastavení Infopanelu v2.

Nejprve ověří závislosti, konfiguraci, framebuffer a dotyk **bez změny stavu zařízení a bez zastavení původní služby**. Teprve po úspěšné kontrole uloží zálohu, zastaví původní vykreslování a zapne `infopanel.service`. Při neúspěšném spuštění obnoví předchozí soubory a stav služeb. Původní LCD skript ani jeho unit nepřepisuje. Služby mají `Conflicts`, aby nekreslily současně.

Samotná kontrola bez přepnutí služeb:

```bash
sudo python3 install.py --check-only
```

Pokud má stará služba jiné jméno, framebuffer nebo je potřeba explicitně vybrat vstup:

```bash
sudo python3 install.py --legacy-service lcd-info.service --fb /dev/fb1 --rotate 0 --touch /dev/input/event0
```

Čísla `/dev/fb1` a `event0` jsou **příklad**, použij skutečná zařízení. Diagnostika je vypíše:

```bash
sudo python3 lcd/infopanel.py --diagnose
```

Automatický výběr dotyku funguje při právě jednom podporovaném vstupu. Při více vstupech instalace skončí s vysvětlením a původní LCD zůstane běžet. Trvalá cesta `/dev/input/by-path/…` je vhodnější než číslo `eventX`, pokud ji ovladač poskytuje.

## První spuštění: kalibrace

Klepni postupně na **čtyři křížky** v rozích obrazovky a vždy zvedni prst. Do dokončení kalibrace nejsou přístupná ovládací tlačítka. Kalibrace řeší prohozené osy, zrcadlení i nastavené otočení; při nepřesných bodech se zopakuje.

Výsledek se ukládá do `/var/lib/hanzhub-infopanel/touch-calibration.json`. Změna rozlišení, rotace nebo identifikace vstupního zařízení vyvolá novou kalibraci. Ruční zopakování:

```bash
sudo systemctl stop infopanel.service
sudo rm -f /var/lib/hanzhub-infopanel/touch-calibration.json
sudo systemctl start infopanel.service
```

Dotyk provede akci až při uvolnění prstu. Tažení, druhý multitouch kontakt a ztracené input události nevydávají příkaz. Při čekání na odpověď jsou ovládací tlačítka zamknuta, navigace zůstává dostupná.

## Nastavení a výběr modulů

Nastavení je v **`/etc/hanzhub-infopanel.json`**; popisuje ho [config.example.json](config.example.json).

| Klíč | Výchozí hodnota / význam |
| --- | --- |
| `fb`, `rotate` | `/dev/fb0`, `0`; rotace 0 / 90 / 180 / 270 proti směru hodin |
| `touch` | `auto` nebo cesta podporovaného input zařízení |
| `api` | `http://127.0.0.1:4011/api/iot` |
| `panel_id`, `plug_id` | `null` pro první automatický výběr jednoho modulu daného typu; jinak explicitní ID modulu |
| `meteo_csv` | `/opt/meteo3/meteo_log.csv` |
| `meteo_refresh`, `meteo_stale` | Čtení logu každých 15 s; označení starších dat po 3600 s |
| `iot_refresh` | Polling každých 5 s; respektuje také cache IoT API |
| `idle_seconds` | Návrat na Přehled po 60 s; `0` návrat vypne |
| `iface` | `eth0`, lze změnit např. na `wlan0` |
| `data_dir` | `/var/lib/hanzhub-infopanel`; kalibrace, výběr modulů a historie příkonu |

Pokud máš jeden infrapanel a jednu Tapo P110M, načtou se automaticky. Vybraná **ID se uloží**, aby odebrání zařízení omylem nepřesměrovalo ovládání na jiný modul. Při více zařízeních stejného typu nastav `panel_id` / `plug_id`. Jde o **12místné ID z HanzHubu**, nikoli dlouhý Tuya Device ID. Získáš je:

```bash
curl -sS http://127.0.0.1:4011/api/iot/devices | python3 -m json.tool
sudo nano /etc/hanzhub-infopanel.json
sudo systemctl restart infopanel.service
```

Pro změnu `data_dir` použij znovu instalátor, aby se upravila i oprávnění systemd. Nová datová složka znamená nový výběr modulů, kalibraci a historii.

## Data, grafy a potvrzení příkazů

- Meteo graf čte skutečné časové značky a teploty z konce CSV (nejvýše 4 MiB). Nedokončené/rozbité řádky přeskakuje; chybějící log nezastaví ostatní stránky. Čas bez uvedeného pásma interpretuje v lokálním pásmu Raspberry, stejně jako původní LCD. Hodiny zobrazují systémové pásmo Raspberry.
- Dnešní a měsíční kWh jsou údaje **ze zásuvky Tapo přes HanzHub API**. Infopanel je nepřepočítává z grafu příkonu.
- Příkon se vzorkuje nejvýše jednou za minutu do `power-history.sqlite3`, odděleně podle ID zásuvky. Uchovává se 30 dní; graf nabízí posledních 1 / 6 / 24 hodin. Historie začíná spuštěním nové verze, nezískáváme starší placenou cloudovou historii. Výpadky se nevyplňují nulami a delší mezery v grafu se nepřemosťují.
- Infrapanel ovládá výkonový stav, nastavenou teplotu, dětský zámek a časovač. Chybu čidla E1 zobrazuje červeně. Spotřebu infrapanelu neodhadujeme z ON/OFF.
- Zápis probíhá pouze přes `POST /api/iot/devices/{id}/command`. UI ukáže potvrzení teprve při úspěšném výsledku a odpovídajícím skutečném stavu z backendu. Časovač ověřuje backend i s ohledem na běžící odpočet. Nejistý příkaz se **automaticky neopakuje**; místo toho se znovu načte stav.
- Síťová komunikace běží na pozadí, nezastavuje dotykové přepínání. Nedostupné, zakázané a staré stavy vypnou ovládání. Potvrzení chrání i před přepsáním opožděným starším čtením.

## Logy, aktualizace a návrat

```bash
sudo systemctl status infopanel.service
sudo journalctl -u infopanel.service -n 80 --no-pager
sudo journalctl -u infopanel.service -f
```

Aktualizace pouze LCD, bez přestavby IoT Dockeru:

```bash
cd ~/InfoLcd
sh update.sh
```

Soubory aplikace jsou v `/opt/hanzhub-infopanel/lcd`, konfigurace v `/etc/hanzhub-infopanel.json`, zálohy předchozí instalace v `/var/lib/hanzhub-infopanel/install-backups/<čas>`. Originální LCD služba zůstává k dispozici.

Návrat k původnímu LCD (u vlastního názvu služby ho nahraď):

```bash
sudo systemctl disable --now infopanel.service
sudo systemctl enable --now lcd-info.service
```

Pokud dotyk není detekován, nejprve zkontroluj `--diagnose`, `/dev/input/` a ovladač LCD. Pokud zařízení hlásí nedostupnost, ověř dostupnost API výše a stav v IoT webu; Infopanel neprovádí Wi-Fi reset ani nové párování zařízení.

## Vývoj, náhledy a ověření

Python **3.10+** na Linuxu (běžné Raspberry Pi OS s Pythonem 3.11+). Závislosti lze pro vývoj nainstalovat do venv:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m compileall -q lcd install.py tests
.venv/bin/python lcd/preview_infopanel.py
```

`evdev` při sestavení z PyPI potřebuje C překladač a Linux input hlavičky; na Raspberry je pro provoz vhodnější výše uvedený balík `python3-evdev` z apt. Testy a náhledy neodesílají příkazy skutečným zařízením a nepotřebují framebuffer. CI je spouští při push a pull requestu. Náhledy OFF/nedostupnosti/časovače jsou také v `docs/`.

Projekt navazuje na framebuffer a robustní Meteo parser z [LoT/lcd](https://github.com/H0nz4k/LoT/tree/main/lcd). Původní `lcd_info.py` a `infrapanel_widget.py` jsou zde kvůli společným hardwarovým funkcím a formátu logu; hlavní aplikace v2 je `lcd/infopanel.py`.

**Ověření na skutečném LCD:** automatické testy ověřují vykreslování, kalibraci, dotykové události, příkazy, historii a obnovu instalace. Přesný ovladač, rozlišení, otočení a dotykové zařízení konkrétního Raspberry je nutné ověřit při nasazení pomocí diagnostiky a čtyřbodové kalibrace.
