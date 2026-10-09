from datetime import datetime, timezone
import importlib.util
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"lcd"))
from infopanel import DEFAULTS, Framebuffer, ScreenState, Weather, calibration_targets, validate_settings
from infopanel_data import InfoData, PowerHistory, meteo_records, valid_state
from infopanel_touch import (ABS_X,ABS_Y,ABS_MT_SLOT,ABS_MT_POSITION_X,ABS_MT_POSITION_Y,
                             ABS_MT_TRACKING_ID,BTN_TOUCH,EV_ABS,EV_KEY,EV_SYN,SYN_DROPPED,
                             SYN_REPORT,Calibration,Tap,TouchDecoder)
from infopanel_ui import Hit, render
from lcd_info import _try_parse_line, rgb_to_rgb565_bytes
from preview_infopanel import demo_model

spec = importlib.util.spec_from_file_location("infopanel_install",ROOT/"install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

HEATER_ID,PLUG_ID,OTHER_ID = "123456abcdef","abcdef123456","987654abcdef"


def heater(**changes):
    state = {"online":True,"power":True,"locked":False,"current_temp_c":24,"target_temp_c":25,
             "timer_minutes":0,"fault_code":0,"checked_at":datetime.now(timezone.utc).isoformat()}
    return {**state,**changes}


def event(kind,code,value=0):
    return SimpleNamespace(type=kind,code=code,value=value)


class TouchTests(unittest.TestCase):
    def test_contact_yields_one_release_not_move_or_press(self):
        decoder = TouchDecoder(((0,1000),(0,1000)))
        for item in (event(EV_ABS,ABS_X,100),event(EV_ABS,ABS_Y,200),event(EV_KEY,BTN_TOUCH,1)):
            self.assertIsNone(decoder.feed(item,1))
        self.assertIsNone(decoder.feed(event(EV_SYN,SYN_REPORT),1))
        self.assertIsNone(decoder.feed(event(EV_ABS,ABS_X,105),1.1))
        self.assertIsNone(decoder.feed(event(EV_SYN,SYN_REPORT),1.1))
        decoder.feed(event(EV_KEY,BTN_TOUCH,0),1.2)
        tap = decoder.feed(event(EV_SYN,SYN_REPORT),1.2)
        self.assertEqual((tap.x,tap.y),(105,200))
        self.assertFalse(tap.moved)
        self.assertIsNone(decoder.feed(event(EV_SYN,SYN_REPORT),1.3))

    def test_drag_out_and_back_still_is_drag(self):
        decoder = TouchDecoder(((0,1000),(0,1000)),initial=(100,200))
        decoder.feed(event(EV_KEY,BTN_TOUCH,1),1)
        decoder.feed(event(EV_SYN,SYN_REPORT),1)
        decoder.feed(event(EV_ABS,ABS_X,600),1.1)
        decoder.feed(event(EV_SYN,SYN_REPORT),1.1)
        decoder.feed(event(EV_ABS,ABS_X,100),1.2)
        decoder.feed(event(EV_KEY,BTN_TOUCH,0),1.2)
        self.assertTrue(decoder.feed(event(EV_SYN,SYN_REPORT),1.2).moved)

    def test_dropped_input_never_activates_contact(self):
        decoder = TouchDecoder(((0,1000),(0,1000)),initial=(100,200))
        decoder.feed(event(EV_KEY,BTN_TOUCH,1),1)
        decoder.feed(event(EV_SYN,SYN_REPORT),1)
        decoder.feed(event(EV_SYN,SYN_DROPPED),1.1)
        decoder.feed(event(EV_KEY,BTN_TOUCH,0),1.2)
        self.assertIsNone(decoder.feed(event(EV_SYN,SYN_REPORT),1.2))

    def test_mt_ignores_second_finger(self):
        decoder = TouchDecoder(((0,1000),(0,1000)),multitouch=True)
        for item in (event(EV_ABS,ABS_MT_TRACKING_ID,1),event(EV_ABS,ABS_MT_POSITION_X,100),
                     event(EV_ABS,ABS_MT_POSITION_Y,200),event(EV_SYN,SYN_REPORT)):
            decoder.feed(item,1)
        for item in (event(EV_ABS,ABS_MT_SLOT,1),event(EV_ABS,ABS_MT_TRACKING_ID,2),
                     event(EV_ABS,ABS_MT_POSITION_X,900),event(EV_SYN,SYN_REPORT)):
            self.assertIsNone(decoder.feed(item,1.1))
        decoder.feed(event(EV_ABS,ABS_MT_SLOT,0),1.2)
        decoder.feed(event(EV_ABS,ABS_MT_TRACKING_ID,-1),1.2)
        tap = decoder.feed(event(EV_SYN,SYN_REPORT),1.2)
        self.assertEqual((tap.x,tap.y),(100,200))

    def test_affine_calibration_handles_rotation_and_flip_and_persists(self):
        size,ranges = (320,480),[[0,4095],[0,4095]]
        targets = calibration_targets(size)
        raw = [((1-y/480)*4095,x/320*4095) for x,y in targets]
        calibration = Calibration.fit(ranges,size,raw,targets)
        x,y = calibration.point((1-200/480)*4095,100/320*4095)
        self.assertAlmostEqual(x,100)
        self.assertAlmostEqual(y,200)
        description = {"ranges":ranges,"fingerprint":"test"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"calibration.json"
            calibration.save(path,"test",90)
            self.assertIsNotNone(Calibration.load(path,description,size,90))
            self.assertIsNone(Calibration.load(path,description,size,0))
            self.assertIsNone(Calibration.load(path,{**description,"fingerprint":"other"},size,90))

    def test_bad_calibration_is_rejected(self):
        for raw in ([(10,10)]*4,[(0,0),(1,0),(1,1),(0,1)]):
            with self.assertRaises(ValueError):
                Calibration.fit(((0,1000),(0,1000)),(320,480),raw,calibration_targets((320,480)))


class InteractionTests(unittest.TestCase):
    def setUp(self):
        self.calibration = Calibration(((0,320),(0,480)),(320,480),[[320,0,0],[0,480,0]])
        self.calls = []
        self.data = SimpleNamespace(submit=lambda *args:self.calls.append(args) or True)

    def test_navigation_does_not_send_device_command(self):
        state = ScreenState()
        _,hits = render("home",demo_model())
        state.tap(Tap(100,100,100,100,False,.1),self.calibration,hits,self.data)
        self.assertEqual(state.page,"meteo")
        self.assertEqual(self.calls,[])

    def test_switch_requires_same_button_at_contact_and_release(self):
        state = ScreenState()
        hit = Hit((10,10,100,60),("command","plug","power",False))
        state.tap(Tap(20,20,150,20,False,.1),self.calibration,[hit],self.data)
        state.tap(Tap(20,20,20,20,True,.1),self.calibration,[hit],self.data)
        self.assertEqual(self.calls,[])
        state.tap(Tap(20,20,20,20,False,.1),self.calibration,[hit],self.data)
        self.assertEqual(self.calls,[("plug","power",False)])

    def test_idle_home_waits_for_pending_command(self):
        state = ScreenState(60)
        state.page,state.timer_dialog = "heater",True
        state.last_touch = 0
        self.assertFalse(state.idle(True,61))
        self.assertTrue(state.idle(False,61))
        self.assertEqual((state.page,state.timer_dialog),("home",False))

    def test_offline_and_busy_have_no_active_control_hits(self):
        for changes in ({"heater":{"online":False},"plug":{"online":False}},{"busy":True}):
            for page in ("heater","plug"):
                _,hits = render(page,{**demo_model(),**changes})
                self.assertFalse(any(hit.action[0] in ("command","timer","temperature") for hit in hits))

    def test_temperature_limits_and_touch_target_sizes(self):
        model = demo_model()
        for target in (0,37):
            model["heater"]["target_temp_c"] = target
            _,hits = render("heater",model)
            values = [hit.action[1] for hit in hits if hit.action[0]=="temperature"]
            self.assertEqual(values,[1] if target==0 else [-1])
        for page in ("home","meteo","heater","plug"):
            _,hits = render(page,demo_model())
            for hit in hits:
                self.assertGreaterEqual(hit.rect[2]-hit.rect[0],44)
                self.assertGreaterEqual(hit.rect[3]-hit.rect[1],44)

    def test_scaled_bitmap_and_hits_share_letterbox(self):
        image,hits = render("home",demo_model(),size=(480,800))
        self.assertEqual(image.size,(480,800))
        card = next(hit for hit in hits if hit.action==("page","meteo"))
        self.assertEqual(card.rect,(12,127,468,259))

    def test_render_missing_nonfinite_data_and_timer_modal(self):
        model = {"meteo":{"temp":float("nan")},"plug":{"online":True,"power":False,"power_w":None}}
        for page in ("home","meteo","heater","plug"):
            self.assertEqual(render(page,model)[0].size,(320,480))
        _,hits = render("heater",demo_model(),timer_dialog=True)
        self.assertFalse(any(hit.action[0]=="page" for hit in hits))
        self.assertEqual(len(hits),7)


class HistoryTests(unittest.TestCase):
    def test_real_measurement_only_missing_is_not_zero_and_devices_are_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            history = PowerHistory(directory)
            def sample(at,watts=10,online=True):
                return {"online":online,"power_w":watts,"checked_at":datetime.fromtimestamp(at,timezone.utc).isoformat()}
            self.assertTrue(history.record(PLUG_ID,sample(1000)))
            self.assertFalse(history.record(PLUG_ID,sample(1000)))
            self.assertFalse(history.record(PLUG_ID,sample(1060,None)))
            self.assertFalse(history.record(PLUG_ID,sample(1060,float("nan"))))
            self.assertFalse(history.record(PLUG_ID,sample(1060,0,False)))
            self.assertTrue(history.record(PLUG_ID,sample(1120,0)))
            history.record(OTHER_ID,sample(1120,99))
            self.assertEqual(history.series(PLUG_ID,1,1200),[(1000,10.0),(1120,0.0)])

    def test_retention_prunes_old_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            history = PowerHistory(directory)
            for at in (1000,1000+31*86400):
                history.record(PLUG_ID,{"online":True,"power_w":10,"checked_at":datetime.fromtimestamp(at,timezone.utc).isoformat()})
            with history.connect() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM power_samples").fetchone()[0],1)
            with self.assertRaises(sqlite3.ProgrammingError):
                db.execute("SELECT 1")  # context skutečně uzavírá spojení

    def test_weather_log_tail_partial_line_and_staleness(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"weather.csv"
            path.write_text('2026-10-08T19:00:00+00:00,{"temp":21.5,"vbat":3.7,"soc":27}\n'
                            'broken,{"temp":12}\n2026-10-08T19:10:00+00:00,{"temp":')
            rows = meteo_records(path,_try_parse_line)
            self.assertEqual(len(rows),1)
            weather = Weather(path,stale=3600)
            weather.records = rows
            at = datetime(2026,10,8,19,0,tzinfo=timezone.utc).timestamp()
            record,samples = weather.snapshot(6,at+100)
            self.assertFalse(record["stale"])
            self.assertEqual(samples,[(at,21.5)])
            self.assertTrue(weather.snapshot(6,at+3601)[0]["stale"])
            self.assertEqual(weather.snapshot(1,at+3601)[1],[])


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.rows = [{"id":HEATER_ID,"driver":"bot_iph2","enabled":True,"name":"Panel"},
                     {"id":PLUG_ID,"driver":"tapo_p110m","enabled":True,"name":"Plug"}]
        self.commands = []
        self.state = heater()
        self.transport = self.request
        self.data = InfoData("http://localhost:4011/api/iot",self.directory.name,transport=lambda *args:self.transport(*args))
        self.data.refresh_registry()
        self.data.poll("heater")

    def tearDown(self):
        self.data.close()
        if self.data.command_thread:
            self.data.command_thread.join(2)
        self.directory.cleanup()

    def request(self,path,body=None):
        if path=="/devices":
            return {"devices":self.rows}
        if body is None:
            return {"state":dict(self.state)}
        self.commands.append(body)
        state = {**self.state,body["control"]:body["value"]}
        return {"ok":True,"state":state}

    def test_confirmed_command_updates_observed_state(self):
        self.assertTrue(self.data.submit("heater","target_temp_c",26))
        self.data.command_thread.join(2)
        self.assertEqual(self.data.snapshot()["heater"]["target_temp_c"],26)
        self.assertEqual(len(self.commands),1)

    def test_deferred_command_cannot_target_a_different_selected_module(self):
        self.assertFalse(self.data.submit("heater","target_temp_c",26,expected_module_id=OTHER_ID))
        self.assertEqual(self.commands,[])
        self.assertTrue(self.data.submit("heater","target_temp_c",26,expected_module_id=HEATER_ID))
        self.data.command_thread.join(2)
        self.assertEqual(len(self.commands),1)

    def test_wrong_confirmation_never_fakes_requested_state_or_retries(self):
        self.transport = lambda path,body=None: {"ok":True,"state":heater(target_temp_c=25)}
        self.assertTrue(self.data.submit("heater","target_temp_c",26))
        self.data.command_thread.join(2)
        snapshot = self.data.snapshot()
        self.assertIsNone(snapshot["heater"])
        self.assertIn("není potvrzen",snapshot["message"])

    def test_timed_out_command_is_sent_once(self):
        calls = []
        def fail(path,body=None):
            calls.append(body)
            raise TimeoutError("timeout")
        self.transport = fail
        self.data.submit("heater","power",False)
        self.data.command_thread.join(2)
        self.assertEqual(len(calls),1)
        self.assertIsNone(self.data.snapshot()["heater"])

    def test_no_commands_for_offline_stale_or_wrong_type(self):
        for control,value in (("target_temp_c",38),("target_temp_c",True),("power",1),("timer_minutes",1),("unknown",True)):
            self.assertFalse(self.data.submit("heater",control,value))
        self.data.states["heater"] = (time.monotonic()-100,heater())
        self.assertFalse(self.data.submit("heater","power",False))
        self.data.states["heater"] = (time.monotonic(),{"online":False})
        self.assertFalse(self.data.submit("heater","power",False))

    def test_duplicate_commands_are_blocked_until_reply(self):
        entered,release = threading.Event(),threading.Event()
        def blocked(path,body=None):
            entered.set()
            release.wait(2)
            return {"ok":True,"state":heater(power=False)}
        self.transport = blocked
        self.assertTrue(self.data.submit("heater","power",False))
        entered.wait(1)
        self.assertFalse(self.data.submit("heater","power",False))
        release.set()
        self.data.command_thread.join(2)

    def test_inflight_read_cannot_replace_new_command_confirmation(self):
        entered,release = threading.Event(),threading.Event()
        def racing(path,body=None):
            if body is not None:
                return {"ok":True,"state":heater(target_temp_c=26)}
            entered.set()
            release.wait(2)
            return {"state":heater(target_temp_c=25)}
        self.transport = racing
        old_poll = threading.Thread(target=lambda:self.data.poll("heater"))
        old_poll.start()
        entered.wait(1)
        self.data.submit("heater","target_temp_c",26)
        self.data.command_thread.join(2)
        release.set()
        old_poll.join(2)
        self.assertEqual(self.data.snapshot()["heater"]["target_temp_c"],26)

    def test_inflight_read_error_cannot_clear_new_command_confirmation(self):
        entered,release = threading.Event(),threading.Event()
        def racing(path,body=None):
            if body is not None:
                return {"ok":True,"state":heater(target_temp_c=26)}
            entered.set()
            release.wait(2)
            raise TimeoutError("late old read")
        self.transport = racing
        old_poll = threading.Thread(target=lambda:self.data.poll("heater"))
        old_poll.start()
        entered.wait(1)
        self.data.submit("heater","target_temp_c",26)
        self.data.command_thread.join(2)
        release.set()
        old_poll.join(2)
        self.assertEqual(self.data.snapshot()["heater"]["target_temp_c"],26)

    def test_removed_device_does_not_silently_switch_to_another_heater(self):
        self.rows = [{"id":OTHER_ID,"driver":"bot_iph2","enabled":True}]
        self.data.refresh_registry()
        self.data.poll("heater")
        self.assertEqual(self.data.selected["heater"],HEATER_ID)
        self.assertIsNone(self.data.snapshot()["heater"])

    def test_multiple_candidates_require_selection_and_saved_selection_survives_reboot(self):
        self.rows.append({"id":OTHER_ID,"driver":"bot_iph2","enabled":True})
        with tempfile.TemporaryDirectory() as directory:
            data = InfoData("http://localhost/api/iot",directory,transport=self.request)
            data.refresh_registry()
            self.assertIsNone(data.selected["heater"])
        restored = InfoData("http://localhost/api/iot",self.directory.name,transport=self.request)
        self.assertEqual(restored.selected["heater"],HEATER_ID)
        restored.close()

    def test_disabled_module_cannot_receive_command(self):
        self.rows[0]["enabled"] = False
        self.data.refresh_registry()
        self.assertFalse(self.data.submit("heater","power",False))
        self.data.poll("heater")
        self.assertTrue(self.data.snapshot()["heater"]["paused"])

    def test_history_failure_does_not_hide_reachable_plug(self):
        self.state = {"online":True,"power":True,"power_w":10,"checked_at":datetime.now(timezone.utc).isoformat()}
        with patch.object(self.data.history,"record",side_effect=sqlite3.OperationalError("disk full")):
            self.data.poll("plug")
        self.assertTrue(self.data.snapshot()["plug"]["online"])
        self.assertTrue(self.data.snapshot()["history_error"])

    def test_schema_rejects_non_boolean_power_and_invalid_heater_temperature(self):
        self.assertIsNone(valid_state("heater",heater(power=1)))
        self.assertIsNone(valid_state("heater",heater(target_temp_c=38)))
        self.assertIsNone(valid_state("heater",heater(current_temp_c=True)))


class InstallationTests(unittest.TestCase):
    def test_settings_inherit_existing_hardware_and_api(self):
        settings = installer.inherited_settings(["python3","/opt/lcd/lcd_info.py","--fb","/dev/fb1","--rotate=90",
                "--meteo_csv","/opt/weather/log.csv","--infrapanel_api","http://127.0.0.1:4011/api/iot/panel"])
        self.assertEqual(settings["fb"],"/dev/fb1")
        self.assertEqual(settings["rotate"],90)
        self.assertEqual(settings["api"],"http://127.0.0.1:4011/api/iot")

    def test_unit_does_not_start_old_and_new_renderer_together(self):
        unit = installer.unit_text("lcd-info.service")
        self.assertIn("Conflicts=lcd-info.service",unit)
        self.assertIn("--config /etc/hanzhub-infopanel.json",unit)
        self.assertNotIn("--calibrate",unit)

    def test_invalid_settings_are_rejected(self):
        for changes in ({"rotate":45},{"panel_id":"bf66247c13125cd7bcs0vj"},{"api":"http://user:password@localhost/api/iot"},
                        {"touch":"/tmp/input"},{"iot_refresh":0},{"unknown":True}):
            with self.assertRaises(ValueError):
                validate_settings(changes)

    def test_failed_upgrade_restores_files_and_running_services(self):
        self._rollback_case("enable")

    def test_failure_before_app_swap_preserves_previous_app(self):
        self._rollback_case("stop")

    def _rollback_case(self, failure):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app,config,unit,data,stage = [root/name for name in ("app","config.json","unit.service","data","stage")]
            app.mkdir()
            (app/"original").write_text("old app")
            config.write_text("old config")
            unit.write_text("old unit")
            stage.mkdir()
            (stage/"new").write_text("new app")
            calls,failed = [],False
            def run(command,check=True):
                nonlocal failed
                calls.append(command)
                if not failed and ((failure=="enable" and command[1:3]==["enable","--now"]) or
                                   (failure=="stop" and command[1:]==["stop","lcd-info.service"])):
                    failed = True
                    raise RuntimeError("simulated start failure")
                return SimpleNamespace(returncode=0,stdout="0",stderr="")
            with patch.multiple(installer,APP=app,CONFIG=config,UNIT=unit,DATA=data),patch.object(installer,"run",side_effect=run), \
                 patch.object(installer,"service_state",return_value={"active":True,"enabled":True}):
                with self.assertRaises(RuntimeError):
                    installer.activate(stage,{**DEFAULTS,"data_dir":str(data)},"lcd-info.service")
            self.assertEqual((app/"original").read_text(),"old app")
            self.assertEqual(config.read_text(),"old config")
            self.assertEqual(unit.read_text(),"old unit")
            self.assertIn(["systemctl","start","lcd-info.service"],calls)


class HardwareAndTransportTests(unittest.TestCase):
    def test_framebuffer_rgb565_keeps_stride_padding_and_offset(self):
        fb = Framebuffer.__new__(Framebuffer)
        fb.size,fb.bpp,fb.stride,fb.row_bytes,fb.offset = (2,2),16,8,4,3
        fb.memory = bytearray([0xaa]*20)
        image = Image.new("RGB",(2,2))
        image.putdata([(255,0,0),(0,255,0),(0,0,255),(255,255,255)])
        fb.write(image)
        self.assertEqual(fb.memory[3:7],b"\x00\xf8\xe0\x07")
        self.assertEqual(fb.memory[11:15],b"\x1f\x00\xff\xff")
        self.assertEqual(fb.memory[7:11],b"\xaa"*4)
        self.assertEqual(fb.memory[:3],b"\xaa"*3)

    def test_real_http_transport_uses_hanzhub_contract_and_json_post(self):
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):
                pass
            def send(self,payload):
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type","application/json")
                self.send_header("Content-Length",str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def do_GET(self):
                requests.append(("GET",self.path,None))
                self.send({"devices":[{"id":HEATER_ID,"driver":"bot_iph2","enabled":True}]} if self.path.endswith("/devices") else {"state":heater()})
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                requests.append(("POST",self.path,body))
                self.send({"ok":True,"state":heater(**{body["control"]:body["value"]})})
        server = ThreadingHTTPServer(("127.0.0.1",0),Handler)
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                data = InfoData(f"http://127.0.0.1:{server.server_port}/api/iot",directory)
                data.refresh_registry()
                data.poll("heater")
                self.assertTrue(data.submit("heater","target_temp_c",26))
                data.command_thread.join(2)
                self.assertEqual(data.snapshot()["heater"]["target_temp_c"],26)
                data.close()
            self.assertEqual(requests[-1],("POST",f"/api/iot/devices/{HEATER_ID}/command",{"control":"target_temp_c","value":26}))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__=="__main__":
    unittest.main()
