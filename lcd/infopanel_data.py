"""Čtení HanzHub API, potvrzené dotykové příkazy a místní historie příkonu."""
from contextlib import contextmanager
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from urllib.request import Request, urlopen


def finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def valid_state(role, state):
    if not isinstance(state,dict):
        return None
    if state.get("online") is not True:
        return {"online":False,"paused":state.get("paused") is True}
    if type(state.get("power")) is not bool:
        return None
    if role=="heater":
        for key,high in (("current_temp_c",99),("target_temp_c",37),("timer_minutes",1440)):
            if type(state.get(key)) is not int or not 0<=state[key]<=high:
                return None
        if type(state.get("locked")) is not bool:
            return None
        if type(state.get("fault_code",0)) is not int or not 0<=state.get("fault_code",0)<2**32:
            return None
    return dict(state)


class PowerHistory:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path = directory/"power-history.sqlite3"
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS power_samples (module_id TEXT NOT NULL, at INTEGER NOT NULL, watts REAL NOT NULL, PRIMARY KEY(module_id,at))")
            db.execute("CREATE INDEX IF NOT EXISTS power_time ON power_samples(at)")
        self.path.chmod(0o600)
        self.last_prune = 0

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path,timeout=2)
        try:
            with db:
                yield db
        finally:
            db.close()

    def record(self, module_id, state):
        if state.get("online") is not True or not finite(state.get("power_w")) or state["power_w"]<0:
            return False
        try:
            # Čas skutečného měření: stejné API cache se do historie neopakují.
            at = int(datetime.fromisoformat(state["checked_at"]).timestamp())
        except (KeyError,ValueError,TypeError,OverflowError):
            return False
        with self.connect() as db:
            previous = db.execute("SELECT MAX(at) FROM power_samples WHERE module_id=?",(module_id,)).fetchone()[0]
            if previous is not None and at-previous<60:
                return False
            db.execute("INSERT OR IGNORE INTO power_samples VALUES (?,?,?)",(module_id,at,state["power_w"]))
            if at-self.last_prune>=3600:
                db.execute("DELETE FROM power_samples WHERE at<?",(at-30*86400,))
                self.last_prune = at
        return True

    def series(self, module_id, hours=24, now=None):
        now = time.time() if now is None else now
        with self.connect() as db:
            return db.execute("SELECT at,watts FROM power_samples WHERE module_id=? AND at BETWEEN ? AND ? ORDER BY at",
                              (module_id,now-hours*3600,now)).fetchall()


def meteo_records(path, parser, max_bytes=4*1024*1024):
    """Omezený konec CSV; rozpracované řádky používají původní robustní parser."""
    try:
        with open(path,"rb") as f:
            f.seek(0,os.SEEK_END)
            length = f.tell()
            f.seek(max(0,length-max_bytes))
            lines = f.read(max_bytes).splitlines()
        records = []
        for line in lines:
            record = parser(line.decode("utf-8",errors="ignore"))
            if record and isinstance(record.get("ts"),datetime):
                records.append(record)
        records.sort(key=lambda item:item["ts"].timestamp())
        return records
    except (OSError,ValueError,OverflowError):
        return []


class InfoData:
    def __init__(self, api, directory, panel_id=None, plug_id=None, interval=5, transport=None):
        self.api = api.rstrip("/")
        self.directory = Path(directory)
        self.history = PowerHistory(directory)
        self.transport = transport or self._request
        self.interval = max(5,float(interval))
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.wake = {role:threading.Event() for role in ("heater","plug")}
        self.states = {}
        self.generation = {"heater":0,"plug":0}
        self.modules = {}
        self.selected = {"heater":panel_id,"plug":plug_id}
        self.selection_file = self.directory/"selection.json"
        try:
            saved = json.loads(self.selection_file.read_text())
            for role in self.selected:
                if not self.selected[role] and re.fullmatch(r"[a-f0-9]{12}",str(saved.get(role,""))):
                    self.selected[role] = saved[role]
        except (OSError,ValueError,AttributeError):
            pass
        self.busy = False
        self.busy_role = None
        self.message = ""
        self.message_until = 0
        self.threads = []
        self.command_thread = None
        self.history_error = False

    def _request(self, path, body=None):
        payload = None if body is None else json.dumps(body,allow_nan=False).encode()
        request = Request(self.api+path,data=payload,headers={"Accept":"application/json","Content-Type":"application/json"})
        with urlopen(request,timeout=20 if path.endswith(("/state","/command")) else 4) as r:
            data = json.load(r)
        if not isinstance(data,dict):
            raise ValueError("Neplatná odpověď API")
        return data

    def refresh_registry(self):
        payload = self.transport("/devices")
        rows = payload.get("devices")
        if not isinstance(rows,list):
            raise ValueError("Neplatný seznam modulů")
        rows = [row for row in rows if isinstance(row,dict) and re.fullmatch(r"[a-f0-9]{12}",str(row.get("id","")))]
        with self.lock:
            self.modules = {row["id"]:{key:row.get(key) for key in ("id","name","room","driver","enabled")} for row in rows}
            changed = False
            for role,driver in (("heater","bot_iph2"),("plug","tapo_p110m")):
                candidates = [row for row in rows if row.get("driver")==driver]
                # Více modulů vyžaduje explicitní volbu, odstraněný modul nenahradíme jiným.
                if self.selected[role] is None and len(candidates)==1:
                    self.selected[role] = candidates[0]["id"]
                    changed = True
                    self.wake[role].set()
            selected = dict(self.selected)
        if changed:
            temporary = self.selection_file.with_suffix(".new")
            temporary.write_text(json.dumps(selected),encoding="utf-8")
            temporary.chmod(0o600)
            temporary.replace(self.selection_file)

    def poll(self, role):
        with self.lock:
            module_id = self.selected[role]
            generation = self.generation[role]
            module = self.modules.get(module_id)
            if self.busy_role==role:
                return
        try:
            if not module or module.get("driver")!={"heater":"bot_iph2","plug":"tapo_p110m"}[role]:
                state = None
            elif module.get("enabled") is not True:
                state = {"online":False,"paused":True}
            else:
                state = valid_state(role,self.transport(f"/devices/{module_id}/state").get("state"))
        except (OSError,ValueError,TypeError):
            state = None
        with self.lock:
            if self.selected[role]==module_id and self.busy_role!=role and self.generation[role]==generation:
                self.states[role] = (time.monotonic(),state)
            else:
                return
        if role=="plug" and state:
            try:
                self.history.record(module_id,state)
                self.history_error = False
            except (OSError,sqlite3.Error):
                self.history_error = True

    def start(self):
        def registry():
            while not self.stop.is_set():
                try:
                    self.refresh_registry()
                except (OSError,ValueError,TypeError,sqlite3.Error):
                    pass
                self.stop.wait(30)
        def device(role):
            while not self.stop.is_set():
                try:
                    self.poll(role)
                except (OSError,ValueError,TypeError,sqlite3.Error):
                    with self.lock:
                        if self.busy_role!=role:
                            self.states[role] = (time.monotonic(),None)
                self.wake[role].wait(self.interval)
                self.wake[role].clear()
        for callback,args in ((registry,()),(device,("heater",)),(device,("plug",))):
            thread = threading.Thread(target=callback,args=args,daemon=True)
            self.threads.append(thread)
            thread.start()

    def snapshot(self):
        with self.lock:
            result = {"busy":self.busy,"message":self.message if time.monotonic()<self.message_until else "",
                      "history_error":self.history_error}
            for role in ("heater","plug"):
                cached = self.states.get(role)
                state = cached[1] if cached and time.monotonic()-cached[0]<=max(25,self.interval*3) else None
                result[role] = dict(state) if state else None
                module = self.modules.get(self.selected[role],{})
                result[role+"_name"] = module.get("name") or {"heater":"Infrapanel","plug":"Zásuvka"}[role]
                result[role+"_room"] = module.get("room") or ""
                result[role+"_id"] = self.selected[role]
            return result

    def submit(self, role, control, value):
        snapshot = self.snapshot()
        state = snapshot.get(role)
        valid = role in ("heater","plug") and isinstance(state,dict) and state.get("online") is True
        if control in ("power","locked"):
            valid = valid and type(value) is bool and (control=="power" or role=="heater")
        elif control=="target_temp_c":
            valid = valid and role=="heater" and type(value) is int and 0<=value<=37
        elif control=="timer_minutes":
            valid = valid and role=="heater" and type(value) is int and 0<=value<=1440 and value%60==0
        else:
            valid = False
        with self.lock:
            if not valid or self.busy:
                return False
            module_id = self.selected[role]
            module = self.modules.get(module_id,{})
            if module.get("enabled") is not True or module.get("driver")!={"heater":"bot_iph2","plug":"tapo_p110m"}[role]:
                return False
            self.busy,self.busy_role = True,role
            self.generation[role] += 1
            self.message,self.message_until = "Odesílám příkaz…",float("inf")
        def execute():
            state = None
            message = "Příkaz není potvrzen. Načítám stav."
            try:
                response = self.transport(f"/devices/{module_id}/command",{"control":control,"value":value})
                state = valid_state(role,response.get("state"))
                confirmed = response.get("ok") is True and state and state.get("online") is True
                if control!="timer_minutes":
                    confirmed = confirmed and type(state.get(control)) is type(value) and state[control]==value
                if confirmed:
                    message = "Potvrzeno zařízením"
                else:
                    state = None
            except (OSError,ValueError,TypeError):
                pass
            finally:
                with self.lock:
                    self.states[role] = (time.monotonic(),state)
                    self.busy,self.busy_role = False,None
                    self.message,self.message_until = message,time.monotonic()+8
                self.wake[role].set()
        thread = threading.Thread(target=execute,daemon=True)
        self.command_thread = thread
        thread.start()
        return True

    def close(self):
        self.stop.set()
        for wake in self.wake.values():
            wake.set()
