#!/usr/bin/env python3
"""Instalace Infopanelu v2 s kontrolou hardwaru, zálohou a automatickým návratem při chybě."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time

SOURCE = Path(__file__).resolve().parent
sys.path.insert(0,str(SOURCE/"lcd"))
APP = Path("/opt/hanzhub-infopanel")
CONFIG = Path("/etc/hanzhub-infopanel.json")
UNIT = Path("/etc/systemd/system/infopanel.service")
DATA = Path("/var/lib/hanzhub-infopanel")
RUNTIME_FILES = ("infopanel.py","infopanel_ui.py","infopanel_data.py","infopanel_touch.py","lcd_info.py","infrapanel_widget.py")


def run(command, check=True):
    result = subprocess.run(command,capture_output=True,text=True,timeout=40)
    if check and result.returncode:
        raise RuntimeError(" ".join(command[:3])+": "+(result.stderr.strip() or result.stdout.strip()))
    return result


def service_state(service):
    return {"active":run(["systemctl","is-active","--quiet",service],False).returncode==0,
            "enabled":run(["systemctl","is-enabled","--quiet",service],False).returncode==0}


def legacy_arguments(service):
    result = run(["systemctl","show",service,"--property=ExecStart","--value"],False)
    if result.returncode:
        return []
    match = re.search(r"argv\[\]=(.*?)(?: ;|\s*})",result.stdout)
    if match:
        return shlex.split(match.group(1))
    # Pro jednodušší výstup systemctl a testovací instalace.
    if "lcd_info.py" in result.stdout and "{" not in result.stdout:
        return shlex.split(result.stdout.strip())
    return []


def inherited_settings(argv):
    mapping = {"--fb":"fb","--rotate":"rotate","--font":"font","--meteo_csv":"meteo_csv",
               "--iface":"iface","--infrapanel_api":"api","--infrapanel_id":"panel_id"}
    settings = {}
    for i,arg in enumerate(argv):
        option,separator,value = arg.partition("=")
        if option in mapping:
            value = value if separator else (argv[i+1] if i+1<len(argv) else "")
            if option=="--rotate":
                value = int(value)
            elif option=="--infrapanel_api":
                value = value.rstrip("/").removesuffix("/panel")
            settings[mapping[option]] = value
    return settings


def unit_text(legacy_service, data_dir=None):
    data_dir = DATA if data_dir is None else Path(data_dir)
    writable = '"'+str(data_dir).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
    return f"""[Unit]
Description=HanzHub Infopanel v2 (LCD + touch)
After=network.target {legacy_service}
Conflicts={legacy_service}
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
ExecStart=/usr/bin/python3 {APP}/lcd/infopanel.py --config {CONFIG}
Restart=on-failure
RestartSec=5
TimeoutStopSec=5
Environment=PYTHONUNBUFFERED=1
StateDirectory=hanzhub-infopanel
StateDirectoryMode=0700
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths={writable}

[Install]
WantedBy=multi-user.target
"""


def restore_service(service, state):
    run(["systemctl","enable" if state["enabled"] else "disable",service],False)
    run(["systemctl","start" if state["active"] else "stop",service],False)


def replace_file(path, content, mode=0o644):
    temporary = path.with_name(path.name+".infopanel-new")
    temporary.write_text(content,encoding="utf-8")
    temporary.chmod(mode)
    temporary.replace(path)


def activate(stage, settings, legacy_service):
    """Voláno až po úspěšném --check; vrací zálohu, při neúspěchu obnoví předchozí stav."""
    old_state,new_state = service_state(legacy_service),service_state("infopanel.service")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = DATA/"install-backups"/stamp
    backup.mkdir(parents=True,mode=0o700)
    previous = {"legacy_service":legacy_service,"legacy_state":old_state,"infopanel_state":new_state,
                "had_app":APP.exists(),"had_config":CONFIG.exists(),"had_unit":UNIT.exists()}
    (backup/"state.json").write_text(json.dumps(previous,indent=2))
    for path in (CONFIG,UNIT):
        if path.exists():
            shutil.copy2(path,backup/path.name)
    moved_app = touched_app = False
    try:
        run(["systemctl","stop","infopanel.service"],False)
        run(["systemctl","stop",legacy_service],old_state["active"])
        if APP.exists():
            shutil.move(str(APP),str(backup/"app"))
            moved_app = True
        touched_app = True
        shutil.move(str(stage),str(APP))
        replace_file(CONFIG,json.dumps(settings,ensure_ascii=False,indent=2)+"\n",0o600)
        Path(settings["data_dir"]).mkdir(parents=True,exist_ok=True,mode=0o700)
        replace_file(UNIT,unit_text(legacy_service,settings["data_dir"]))
        run(["systemctl","daemon-reload"])
        run(["systemctl","disable",legacy_service],False)
        run(["systemctl","reset-failed","infopanel.service"],False)
        run(["systemctl","enable","--now","infopanel.service"])
        # Záchyt pádu při startu i opakovaného Restart=on-failure, nikoli jen okamžiku spuštění.
        time.sleep(2)
        run(["systemctl","is-active","--quiet","infopanel.service"])
        restarts = run(["systemctl","show","infopanel.service","--property=NRestarts","--value"]).stdout.strip()
        if restarts and int(restarts)!=0:
            raise RuntimeError("Infopanel při spuštění spadl; obnovuji předchozí LCD.")
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError):
        run(["systemctl","stop","infopanel.service"],False)
        if touched_app and APP.exists():
            shutil.rmtree(APP)
        if moved_app:
            shutil.move(str(backup/"app"),str(APP))
        for path,key in ((CONFIG,"had_config"),(UNIT,"had_unit")):
            if previous[key]:
                shutil.copy2(backup/path.name,path)
            else:
                path.unlink(missing_ok=True)
        run(["systemctl","daemon-reload"],False)
        run(["systemctl","reset-failed","infopanel.service"],False)
        restore_service("infopanel.service",new_state)
        restore_service(legacy_service,old_state)
        raise
    return backup


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--legacy-service",default="lcd-info.service")
    ap.add_argument("--fb")
    ap.add_argument("--rotate",type=int)
    ap.add_argument("--touch")
    ap.add_argument("--api")
    ap.add_argument("--meteo-csv")
    ap.add_argument("--iface")
    ap.add_argument("--panel-id")
    ap.add_argument("--plug-id")
    ap.add_argument("--diagnose",action="store_true")
    ap.add_argument("--check-only",action="store_true",help="Ověří hardware a připravená nastavení, nemění služby.")
    args = ap.parse_args()
    stage = staged_config = None
    try:
        from infopanel import validate_settings
        if not re.fullmatch(r"[a-zA-Z0-9_.@-]+\.service",args.legacy_service) or args.legacy_service=="infopanel.service":
            raise ValueError("Neplatné jméno původní LCD služby.")
        if args.diagnose:
            command = ["/usr/bin/python3",str(SOURCE/"lcd/infopanel.py"),"--diagnose"]
            for key in ("fb","rotate","touch"):
                if getattr(args,key) is not None:
                    command.extend(["--"+key,str(getattr(args,key))])
            result = run(command,False)
            print(result.stdout or result.stderr)
            return result.returncode
        if os.geteuid()!=0:
            raise ValueError("Instalaci spusť přes sudo python3 install.py.")
        if CONFIG.exists():
            settings = json.loads(CONFIG.read_text())
        else:
            legacy = legacy_arguments(args.legacy_service)
            if service_state(args.legacy_service)["active"] and not legacy and args.fb is None:
                raise ValueError("Nelze převzít framebuffer běžícího LCD. Použij --fb /dev/fbX a --rotate 0/90/180/270.")
            settings = inherited_settings(legacy)
        for key in ("fb","rotate","touch","api","meteo_csv","iface","panel_id","plug_id"):
            if getattr(args,key) is not None:
                settings[key] = getattr(args,key)
        settings = validate_settings(settings)
        # Nejprve pouze otevřít framebuffer a vstup. Původní LCD při kontrole stále běží.
        DATA.mkdir(parents=True,exist_ok=True,mode=0o700)
        APP.parent.mkdir(parents=True,exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        stage = APP.with_name(APP.name+".stage-"+stamp)
        (stage/"lcd").mkdir(parents=True)
        for name in RUNTIME_FILES:
            shutil.copy2(SOURCE/"lcd"/name,stage/"lcd"/name)
        staged_config = DATA/("config-check-"+stamp+".json")
        staged_config.write_text(json.dumps(settings),encoding="utf-8")
        staged_config.chmod(0o600)
        result = run(["/usr/bin/python3",str(stage/"lcd/infopanel.py"),"--config",str(staged_config),"--check"])
        print(result.stdout.strip())
        print("Nastavení:",json.dumps(settings,ensure_ascii=False,indent=2))
        if args.check_only:
            print("Kontrola prošla. Služby zůstaly beze změny.")
            return 0
        backup = activate(stage,settings,args.legacy_service)
        print("Infopanel v2 běží. Při prvním spuštění klepni na čtyři kalibrační křížky.")
        print("Záloha předchozí instalace:",backup)
        print("Logy: sudo journalctl -u infopanel.service -f")
    except (OSError,ValueError,RuntimeError,ImportError,subprocess.SubprocessError) as error:
        print("Instalace Infopanelu:",error,file=sys.stderr)
        return 1
    finally:
        if stage and stage.exists():
            shutil.rmtree(stage)
        if staged_config:
            staged_config.unlink(missing_ok=True)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
