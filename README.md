# HanzHub · Infopanel v2

Dotykový informační panel pro Raspberry Pi: stručný přehled systému, Meteo a IoT, graf teploty, ovládání infrapanelu BOT IPH2 a zásuvky TP-Link Tapo P110M. Grafika navazuje na tmavý styl HanzHubu. Verze **2.2.0** podporuje samostatné rozložení **320 × 480 na výšku** a **1024 × 600 na šířku**, vhodné pro Waveshare 7inch HDMI LCD (C).

![Infopanel na šířku – přehled s ukázkovými daty](docs/landscape-home.png)

![Čtyři stránky na šířku – ukázková data](docs/infopanel-landscape.png)

![Čtyři stránky Infopanelu v2 – ukázková data](docs/infopanel-v2.png)

Obrázek vzniká přímo z vykreslovacího kódu. Čísla i průběhy v tomto náhledu jsou **ukázková data**. Nasazená aplikace načítá skutečné údaje.

## Stránky a dotyk

| Stránka | Zobrazení a ovládání |
| --- | --- |
| **Hlavní stránka na šířku** | HanzHub jako tlačítko domů, čas a datum, IP, CPU, RAM, disk, teplota Raspberry, uptime a dostupné/celkové služby dashboardu. Jednoduché dlaždice Meteo (teplota/baterie), infrapanelu (cílová teplota/ON či OFF) a zásuvky (příkon/ON či OFF). |
| **Meteo** | Teplota, baterie, čas posledního měření a graf za 1 / 6 / 24 hodin; minimum a maximum. |
| **Infrapanel** | Cílová a aktuální teplota, tlačítka − / +, zapnutí/vypnutí, dětský zámek a časovač vypnuto / 1 / 2 / 4 / 8 / 24 hodin. Rozsah cíle 0–37 °C. |
| **Zásuvka** | Aktuální příkon, dnešní/měsíční energie, místní graf příkonu za 1 / 6 / 24 hodin a zapnutí/vypnutí. |

Klepnutím na dlaždici na hlavní stránce otevřeš detail. **Na šířku není spodní navigace ani nadbytečný nadpis Přehled. HanzHub vlevo nahoře vždy vrací domů, i z dialogu časovače.** Původní výškový profil si ponechává spodní navigaci. Po 60 sekundách nečinnosti se displej vrátí na Přehled; interval lze změnit. Aktivní dotykové plochy mají při rozlišení 320 × 480 alespoň 44 pixelů v obou směrech; v rozložení 1024 × 600 alespoň 60 pixelů. Ověřeno je i zmenšení širokého rozložení na 800 × 480, kde mají plochy alespoň 44 pixelů.

Na šířku jsou **minimalistické dlaždice v mřížce až 3 × 3**. Vlevo nahoře mají ikonku a název, vpravo sekundární údaj nebo stav, uprostřed velkou hodnotu s jednotkou. Zobrazené dlaždice a jejich pořadí vybírá `home_tiles`. Nyní jsou podporované tři typy: `meteo`, `heater`, `plug`, každý jednou. Mřížka má kapacitu devět dlaždic pro budoucí typy; další zařízení či typy tímto nevznikají a nevyplňujeme volná místa kopiemi. Systémové údaje a počet služeb jsou v horní části. Grafy a další měření zůstávají v detailech. Detail Meteo má velký graf a samostatný sloupec s měřením a baterií. Infrapanel má velký teplotní kruh a ovládání vedle něj; zásuvka měření a vypínač vedle grafu. Napětí a proud zásuvky se zobrazí, pokud je API poskytuje. Všechno se vejde na obrazovku bez posouvání.

**ON je zeleně, OFF červeně, nedostupné zařízení oranžově.** OFF znamená ověřený stav vypnutí; výpadek komunikace se zobrazuje samostatně. Na minimalistické dlaždici znamená oranžová pomlčka nedostupný či pozastavený modul; detail stav vysvětlí. Starší Meteo teplota se na dlaždici zbarví oranžově, detail přidá upozornění. Chybějící měření nezobrazujeme jako nulu. ON infrapanelu neznamená, že jeho topné těleso právě odebírá proud.

## Co musí na Raspberry fungovat

- Linux framebuffer `/dev/fbX`, obvykle `/dev/fb0` nebo `/dev/fb1`; podporované formáty RGB565 (16 bitů) a BGRX8888 (32 bitů). Výchozí `layout: auto` vybere rozložení podle rozlišení **po započtení rotace**: širší obraz používá profil 1024 × 600, ostatní profil 320 × 480. Otočení lze převzít z původní služby. Jiná rozlišení zachovávají poměr stran vybraného profilu, případně s okraji.
- Dotyk dostupný přes Linux input/evdev: `ABS_X/Y + BTN_TOUCH` (např. resistivní čidlo), nebo multitouch protokol B se sloty. Ovladač displeje/dotyku musí být už nainstalovaný. Instalátor nezasahuje do boot konfigurace ani SPI overlay.
- Existující [HanzHub IoT služba](https://github.com/H0nz4k/LoT) dostupná na `http://127.0.0.1:4011/api/iot`, s již přidaným infrapanelem a zásuvkou. API lze použít i z jiného počítače v LAN.
- Pro počet služeb používáme GET `http://127.0.0.1:4010/api/health` z existujícího dashboardu. Počet znamená dostupné/celkové služby podle HTTP health kontrol, nikoli počet všech systemd jednotek. Kontrola běží na pozadí každých 30 s; při chybě nebo stáří nad 90 s ukážeme pomlčku.
- Pro Meteo log `/opt/meteo3/meteo_log.csv`, řádky ve stejném formátu jako původní LCD:

```text
2026-10-08T21:00:00+02:00,{"temp":21.48,"vbat":3.728,"soc":27}
```

Infopanel kreslí přímo na LCD, **nepotřebuje Chromium ani desktop a neotvírá nový webový port**. Stav a příkazy předává existující službě na portu 4011. Neukládá Tapo účet, heslo ani Tuya lokální klíč; ty spravuje IoT služba.

## Instalace na současném HUBu

```bash
sudo apt update
sudo apt install -y git python3-pil python3-psutil python3-evdev fonts-dejavu-core
sudo git clone https://github.com/H0nz4k/InfoLcd.git /opt/InfoLcd
cd /opt/InfoLcd
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

Verze **2.1.1** zvětšuje drobné popisky a osy grafů v rozložení na šířku na 16 px. Datum má stejný font, velikost 27 px a zarovnání jako čas. Aktualizace zachovává konfiguraci displeje, dotyku i zařízení.

## Přechod na 7″ HDMI displej na šířku

Waveshare 7inch HDMI LCD (C) má obraz přes HDMI a dotyk přes datové USB. Aplikace nadále používá framebuffer a evdev. Konfigurace a přidané IoT moduly zůstávají v existujících službách; LCD nemusí zařízení znovu párovat.

Po připojení HDMI a USB nejprve aktualizuj zdrojové soubory a zjisti skutečný framebuffer a dotyk:

```bash
cd /opt/InfoLcd
git pull --ff-only
sudo python3 lcd/infopanel.py --diagnose --fb /dev/fb0 --rotate 0
```

`/dev/fb0` je příklad pro HDMI. Pokud diagnostika ukáže jiný displej, použij odpovídající `/dev/fbX`. Pro 7″ panel očekáváme obraz 1024 × 600, logické rozlišení 1024 × 600 a rozložení `landscape`. Pokud je fyzická orientace správná, nastav `rotate: 0`; nepřebírej rotaci původního SPI LCD.

Příklad pro **ověřený HDMI framebuffer `/dev/fb0`** a jediný připojený dotykový vstup:

```bash
sudo python3 install.py --fb /dev/fb0 --rotate 0 --touch auto --layout auto --check-only
sudo python3 install.py --fb /dev/fb0 --rotate 0 --touch auto --layout auto
```

Při více dotykových zařízeních nahraď `auto` cestou USB dotyku z diagnostiky. Po změně displeje se automaticky zopakuje čtyřbodová kalibrace. Rotace otáčí obraz, volba `layout` mění rozložení; jde o dvě samostatná nastavení. Rozložení lze vynutit pomocí `--layout landscape` nebo `--layout portrait`.

Instalátor nenastavuje HDMI rozlišení ani neodstraňuje staré SPI/display overlay z boot konfigurace. Pro uvolnění GPIO je po odebrání původního LCD potřeba odstranit jeho konkrétní overlay podle konfigurace daného Raspberry. Tuto změnu nelze spolehlivě odvodit pouze z typu nového displeje.

## Ovládání podsvícení

Zapojení pro ovládání podsvícení přes relé Omron G5V-1-DC5 je popsáno v [hardwarovém návodu](docs/backlight-relay.md), včetně [schématu a součástek v PDF](docs/backlight-relay.pdf). Jde o návrh zapojení; před montáží je potřeba určit kontakty přepínače konkrétního LCD. Samostatné [skripty podsvícení](gpios/README.md) ovládají BCM GPIO21 (fyzický pin 40) a instalují se do `/opt/gpios`. ON znamená LOW a vypnutou cívku, OFF znamená HIGH a buzenou cívku; používáme NC kontakt relé. Do obrazovky Infopanelu tyto skripty zatím nejsou připojené.

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
| `layout` | `auto`: výběr podle orientace obrazu po rotaci; `portrait` / `landscape` vynutí profil |
| `touch` | `auto` nebo cesta podporovaného input zařízení |
| `api` | `http://127.0.0.1:4011/api/iot` |
| `health_api` | `http://127.0.0.1:4010/api/health`; zdroj počtu služeb dashboardu |
| `home_tiles` | `["meteo", "heater", "plug"]`; výběr a pořadí dlaždic na šířku, bez opakování |
| `panel_id`, `plug_id` | `null` pro první automatický výběr jednoho modulu daného typu; jinak explicitní ID modulu |
| `meteo_csv` | `/opt/meteo3/meteo_log.csv` |
| `meteo_refresh`, `meteo_stale` | Čtení logu každých 15 s; označení starších dat po 3600 s |
| `iot_refresh` | Polling každých 5 s; respektuje také cache IoT API |
| `idle_seconds` | Návrat na Přehled po 60 s; `0` návrat vypne |
| `iface` | `eth0`, lze změnit např. na `wlan0` |
| `data_dir` | `/var/lib/hanzhub-infopanel`; kalibrace, výběr modulů a historie příkonu |

Pro zobrazení jen některých dlaždic změň např. `"home_tiles": ["plug", "heater"]` v konfiguraci a restartuj `infopanel.service`. Změna seznamu nespáruje ani neodebere zařízení.

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
- **Teplota se odešle až 2 sekundy po posledním klepnutí na − / +**, jedním příkazem s posledním zvoleným cílem. V detailu se okamžitě zobrazí „Nový cíl“ a informace o čekání; potvrzený stav zařízení se tím nepřepisuje. Návrat na původní hodnotu zápis zruší. Navigace čekající změnu ponechá; jiný příkaz ji zruší, stejně jako nedostupnost, změna vybraného zařízení či rozpracovaný příkaz. Čekající změna se při restartu neobnovuje. Po odeslání platí původní čekání na potvrzení zařízení a žádné automatické opakování.
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
cd /opt/InfoLcd
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
.venv/bin/python lcd/preview_infopanel.py --layout landscape --output /tmp/infopanel-wide
```

`evdev` při sestavení z PyPI potřebuje C překladač a Linux input hlavičky; na Raspberry je pro provoz vhodnější výše uvedený balík `python3-evdev` z apt. Testy a náhledy neodesílají příkazy skutečným zařízením a nepotřebují framebuffer. CI je spouští při push a pull requestu. Generátor standardně vytvoří obě orientace; `--layout portrait` / `landscape` vybere jednu. Náhledy OFF/nedostupnosti/časovače jsou také v `docs/`, široké mají prefix `landscape-`.

Projekt navazuje na framebuffer a robustní Meteo parser z [LoT/lcd](https://github.com/H0nz4k/LoT/tree/main/lcd). Původní `lcd_info.py` a `infrapanel_widget.py` jsou zde kvůli společným hardwarovým funkcím a formátu logu; hlavní aplikace v2 je `lcd/infopanel.py`.

**Ověření na skutečném LCD:** uživatel potvrdil fungující výškový panel včetně přepínání stránek a ovládání zařízení. Uživatel také potvrdil obraz i dotykové přepínání stránek na 7″ HDMI LCD 1024 × 600. Dlaždice a odložený zápis verze 2.2.0 jsou ověřeny v náhledech a automatických testech; ověření této aktualizace na fyzickém LCD proběhne po instalaci. Sada 53 testů zahrnuje rychlou sérii klepnutí s jedním odloženým zápisem, návrat na původní cíl bez zápisu, zrušení při nedostupnosti a změně modulu, návrat přes HanzHub i z dialogu a počty služeb při výpadku health API. Testy ověřují také kalibraci prohozených os ve širokém rozlišení, shodu ovládacích oblastí s obrazem a blokování příkazů při nedostupnosti nebo otevřeném dialogu. Přesný ovladač, rozlišení, otočení a dotykové zařízení Raspberry se ověřují při nasazení pomocí diagnostiky a čtyřbodové kalibrace.
