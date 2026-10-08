# Ovládání podsvícení na BCM GPIO21

Dva samostatné Python skripty pro Raspberry Pi 5 používají nástroj `pinctrl`.
Nemají Python závislosti mimo standardní knihovnu a po dokončení nevracejí GPIO do vstupního režimu.
Stav platí do dalšího přenastavení pinu nebo restartu; skripty samy nezajišťují stav při bootu.

## Zapojení

Používáme [tranzistorový budič a NC kontakt relé](../docs/backlight-relay.md).
BCM GPIO21 znamená **fyzický pin 40**, nikoli fyzický pin 21.
GPIO21 připoj přes R1 1 kohm na bázi tranzistoru; cívka je napájená z 5 V a má ochrannou diodu.
Relé nepřipojuj přímo na GPIO. GPIO21 musí být volný pro tento obvod, bez jiného periferního ovladače.
Nástroj pinctrl zapisuje přímo do registrů a nerezervuje GPIO proti souběžnému použití jiným programem.

| Skript | GPIO21 | Cívka relé | Podsvícení přes COM–NC |
| --- | --- | --- | --- |
| `podsviceni_on.py` | LOW / 0 V | Vypnutá | ON |
| `podsviceni_off.py` | HIGH / 3,3 V | Zapnutá | OFF |

Názvy ON/OFF označují **podsvícení**, nikoli buzení cívky. Platí pro naše zapojení s NC kontaktem.
Skripty nečtou stav LCD a potvrzení příkazu neznamená, že bylo ověřeno fyzické rozsvícení.
Původní PDF kreslí GPIO17 jako příklad: pro tyto skripty zapoj R1 na pin 40 (GPIO21) místo pinu 11 (GPIO17).

## Instalace do /opt/gpios

Na HUBu:

```bash
cd /opt/InfoLcd
git pull --ff-only
sudo apt install -y raspi-utils
sudo install -d -m 755 /opt/gpios
sudo install -m 755 gpios/podsviceni_on.py gpios/podsviceni_off.py /opt/gpios/
sudo install -m 755 gpios/podsviceni_off.py /opt/gpios/podsvicedi_off.py
```

Poslední příkaz vytváří také požadované jméno `podsvicedi_off.py` (s písmenem d).
Jde o stejný skript jako `podsviceni_off.py`.
Instalace pouze kopíruje skripty; neovládá GPIO, nemění službu Infopanelu a nepřidává automatické spuštění.

```bash
# Kontrola bez změny pinu:
python3 /opt/gpios/podsviceni_on.py --dry-run
python3 /opt/gpios/podsviceni_off.py --dry-run

# Zapnout podsvícení:
sudo python3 /opt/gpios/podsviceni_on.py

# Vypnout podsvícení:
sudo python3 /opt/gpios/podsvicedi_off.py

# Přečíst režim a elektrickou úroveň GPIO:
sudo pinctrl get 21
```

Opakovaný stejný příkaz nastaví stejnou úroveň. Skripty nepřidávají pulzy, PWM ani cleanup.
Chybějící oprávnění, nástroj, timeout nebo chyba příkazu vrací nenulový návratový kód.
Bez skutečného Raspberry lze ověřit `--dry-run`; fyzické sepnutí relé je potřeba ověřit na HUBu.

Zdroj: [Raspberry Pi pinctrl – dokumentace a příklady](https://github.com/raspberrypi/utils/tree/master/pinctrl).
