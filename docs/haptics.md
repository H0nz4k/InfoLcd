# Haptická odezva Infopanelu · GPIO20

Od 2.5.0 Infopanel vyšle krátký impulz při přijatém klepnutí na aktivní ovládací prvek.
Výchozí délka je 50 ms; změna v konfiguraci `haptic_ms` (10–150 ms).
Jde o potvrzení dotyku, ne potvrzení výsledku vzdáleného IoT příkazu.

| Výstup | BCM | Fyzický pin Raspberry | Úroveň |
| --- | --- | --- | --- |
| Haptika | **20** | **38** | HIGH zapne budič motůrku, LOW vypne |
| Podsvícení | 21 | 40 | LOW = světlo ON přes COM–NC relé, HIGH = OFF |
| Společná zem | — | 6 (GND) | Zem budiče a napájení motůrku |

**Fyzický pin 20 je GND, nikoli GPIO20. Motůrek ani cívku relé nepřipojuj přímo na GPIO.**
GPIO slouží k řízení budiče; motůrek se napájí z větve odpovídající jeho jmenovitému napětí.
Typ a napětí uživatelova motůrku zatím nejsou ověřené. Následující návrh je pro malý
**dvouvodičový kartáčový DC/ERM motůrek**. LRA a jiné haptické prvky potřebují odpovídající řadič.

## Návrh budiče pro malý DC motůrek

Použij N-MOSFET s garantovaným nízkým RDS(on) při VGS 2,5–3,3 V a proudovou rezervou
pro rozběh motoru, například **AO3400A** (SOT-23, vhodný na adaptéru). Jeho výrobce uvádí
RDS(on) i při VGS 2,5 V. Ověř vývody konkrétní součástky podle datasheetu.

| Propojení | Kam |
| --- | --- |
| GPIO20 / fyzický pin 38 | Přes **100 Ω** na gate MOSFETu |
| Gate | Přes **10 kΩ** na source/GND (motor vypnutý i bez běžícího procesu) |
| Source | GND Raspberry i zem zdroje motůrku |
| Drain | Záporný vývod motůrku |
| Kladný vývod motůrku | Napájení podle štítku/datasheetu motůrku |
| Ochranná dioda přes motůrek | Katoda/proužek na motor +, anoda na drain/motor − |
| Kondenzátor **100 nF** | Přes vývody motůrku, co nejblíže motoru |

Diodu vyber s proudovou rezervou pro motor, například 1N5819 pro malý motůrek do 1 A.
Případný filtrační kondenzátor 47–100 µF na jeho napájení musí mít správnou polaritu
a napěťovou rezervu. Samostatný zdroj má s Raspberry společnou zem, jeho kladný výstup
se kvůli řízení motůrku nemusí spojovat s 5V pinem Raspberry.
Nepřipojuj neznámý motůrek automaticky na 5 V; běžné haptické motůrky mohou mít jiné jmenovité napětí.
Přepojování a pájení prováděj s odpojeným napájením.

## Instalace a ověření

```bash
sudo apt update
sudo apt install -y python3-libgpiod
cd /opt/InfoLcd
sudo sh update.sh
sudo journalctl -u infopanel.service -n 30 --no-pager
```

Ve startovacím logu mají být rezervované linky GPIO21 a GPIO20 s počáteční LOW.
Pokud linku drží jiný ovladač, aplikace ji nepřevezme a vypíše chybu; zbytek obrazovky funguje dál.
GPIO20/21 se mohou překrývat s I²S/PCM nebo SPI1. Boot konfiguraci automaticky neměníme.
`--check-only` nebudí motor ani relé a GPIO nerezervuje.
Před zapojením motůrku lze řídicí výstup zkontrolovat osciloskopem nebo logickým analyzátorem
při klepnutí na dlaždici/HanzHub. Běžný multimetr může 50ms impulz přehlédnout.

Po zapojení klepni na HanzHub či dlaždici: jeden krátký pulz. Klepnutí do prázdna či přetažení nevibruje.
Na zhasnutém LCD první platné klepnutí rozsvítí a zavibruje, ale nic neovládá.
Při ukončení služby se motor vrátí do LOW a podsvícení do ON. Externí 10kΩ odpor drží gate
vypnutý při bootu a při uvolnění GPIO po pádu procesu. Nejde o bezpečnostní časovač nezávislý
na operačním systému; při úplném zatuhnutí OS nelze délku pulzu softwarově garantovat.
Rychlá klepnutí neroztahují běžící pulz: může čekat nejvýše jeden další, mezi pulzy je 30 ms pauza.

Pro vypnutí haptiky do montáže nastav `"haptic_gpio": null` v `/etc/hanzhub-infopanel.json`
a restartuj službu. Automatický test používaný při vývoji skutečné GPIO nenapájí.

Zdroje: [Raspberry Pi – GPIO a připojování motorů](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html),
[AO3400A – výrobce a datasheet](https://www.aosmd.com/products/mosfets/low-voltage-mosfets-12v-30v/ao3400a),
[libgpiod – držení GPIO linek](https://libgpiod.readthedocs.io/en/v2.3/python_line_request.html),
[Debian Trixie – python3-libgpiod](https://packages.debian.org/trixie/python3-libgpiod).
