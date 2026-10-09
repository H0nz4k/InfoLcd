"""Health, network counters and read-only navigation without Raspberry hardware."""
from datetime import datetime, timezone
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"lcd"))
from infopanel import ScreenState, Weather
from infopanel_data import InfoData
from infopanel_system import SystemMonitor, age_label, firmware_flags, warnings
from infopanel_landscape import byte_label, firmware_history, firmware_label
from infopanel_touch import Calibration, Tap
from infopanel_ui import render
from preview_infopanel import demo_model


class SystemReadingTests(unittest.TestCase):
    def setUp(self):
        self.link = {"eth0":NS(isup=True)}
        self.counter = {"eth0":NS(bytes_recv=1000,bytes_sent=500)}
        self.stats = NS(cpu_percent=lambda:12, virtual_memory=lambda:NS(percent=25,available=6*2**30,total=8*2**30),
                        disk_usage=lambda _:NS(percent=57,free=24*2**30,total=56*2**30),boot_time=lambda:0,
                        net_if_stats=lambda:self.link,net_if_addrs=lambda:{"eth0":[NS(family=socket.AF_INET,address="192.168.1.3")]},
                        net_io_counters=lambda **kwargs:self.counter)
        self.monitor = SystemMonitor("eth0",self.stats,flags=lambda:0,temperature=lambda:46.9)

    def poll(self, at):
        with patch("infopanel_system.time.monotonic",return_value=at):
            self.monitor.poll()
            return self.monitor.snapshot()

    def test_first_sample_unknown_rate_then_actual_deltas(self):
        first = self.poll(10)
        self.assertNotIn("rx_rate",first)
        self.assertIsNone(first["cpu"])
        self.counter["eth0"] = NS(bytes_recv=3000,bytes_sent=1000)
        second = self.poll(12)
        self.assertEqual((second["rx_rate"],second["tx_rate"]),(1000,250))
        self.assertEqual((second["cpu"],second["disk_free"],second["ip"]),(12,24*2**30,"192.168.1.3"))

    def test_counter_reset_and_reconnection_do_not_create_false_rates(self):
        self.poll(10)
        self.counter["eth0"] = NS(bytes_recv=20,bytes_sent=10)
        self.assertNotIn("rx_rate",self.poll(12))
        self.link["eth0"].isup = False
        down = self.poll(14)
        self.assertFalse(down["link"])
        self.assertNotIn("rx_bytes",down)
        self.link["eth0"].isup = True
        self.assertNotIn("rx_rate",self.poll(16))

    def test_missing_interface_and_expired_sample_remain_unknown(self):
        self.link.clear()
        self.counter.clear()
        sample = self.poll(10)
        self.assertIsNone(sample["link"])
        self.assertNotIn("rx_bytes",sample)
        self.assertEqual(sample["temp"],46.9)
        with patch("infopanel_system.time.monotonic",return_value=21):
            self.assertEqual(self.monitor.snapshot(),{})

    def test_permission_failure_keeps_other_sensor_data(self):
        self.stats.disk_usage = lambda _: (_ for _ in ()).throw(PermissionError())
        sample = self.poll(10)
        self.assertNotIn("disk_free",sample)
        self.assertEqual(sample["ip"],"192.168.1.3")

    def test_firmware_missing_timeout_invalid_or_failed_is_unknown(self):
        for error in (FileNotFoundError(),PermissionError(),subprocess.TimeoutExpired("vcgencmd",1),subprocess.CalledProcessError(1,"vcgencmd")):
            with patch("infopanel_system.subprocess.run",side_effect=error):
                self.assertIsNone(firmware_flags())
        for output,expected in (("throttled=0x50005\n",0x50005),("throttled=0x0",0),("throttled=bad",None),("throttled=0x100000000",None)):
            with patch("infopanel_system.subprocess.run",return_value=NS(stdout=output)) as run:
                self.assertEqual(firmware_flags(),expected)
                self.assertEqual(run.call_args.args[0],["vcgencmd","get_throttled"])
                self.assertEqual(run.call_args.kwargs["timeout"],1)

    def test_current_faults_distinct_from_historical_flags(self):
        self.assertEqual(warnings({"system":{"temp":46,"flags":0x50000}}),[])
        self.assertIn("podpětí",firmware_history(0x50000))
        self.assertIn("bez podpětí",firmware_label(0x50000)[0])
        self.assertIn("neznámé",firmware_label(None)[0])
        active = warnings({"system":{"temp":80,"flags":5,"disk":90,"disk_free":2**30},"meteo":{"stale":True}})
        self.assertEqual(len(active),5)
        self.assertIn("Podpětí",active)
        self.assertIn("Dochází místo na disku",active)
        self.assertEqual(warnings({"system":{"temp":float("nan"),"flags":None,"disk":89,"disk_free":2**30}}),[])
        self.assertEqual(warnings({"system":{"disk":1,"disk_free":2**30-1}}),["Dochází místo na disku"])

    def test_age_and_units_do_not_fabricate_missing_measurements(self):
        self.assertEqual(byte_label(None),"—")
        self.assertEqual(byte_label(1024,True),"1,0 KiB/s")
        self.assertEqual(age_label(None),"Stáří neznámé")
        self.assertEqual(age_label(540),"Před 9 min")
        self.assertEqual(age_label(7200),"Před 2 h 0 min")
        self.assertEqual(age_label(86400),"Před 1 d")
        weather = Weather("unused",stale=3600)
        at = datetime(2026,10,8,tzinfo=timezone.utc)
        weather.records = [{"ts":at,"temp":21}]
        self.assertEqual(weather.snapshot(24,at.timestamp()+540)[0]["age_seconds"],540)
        self.assertTrue(weather.snapshot(24,at.timestamp()+3601)[0]["stale"])
        self.assertEqual(weather.snapshot(24,at.timestamp()-30)[0]["age_seconds"],0)
        self.assertIsNone(weather.snapshot(24,at.timestamp()-61)[0]["age_seconds"])


class IoTCountTests(unittest.TestCase):
    def test_selected_off_is_online_disabled_and_removed_are_excluded(self):
        rows = [{"id":"123456abcdef","driver":"bot_iph2","enabled":True},
                {"id":"abcdef123456","driver":"tapo_p110m","enabled":True},
                {"id":"112233445566","driver":"other","enabled":True}]
        model = demo_model()
        model["heater"]["power"] = model["plug"]["power"] = False
        def transport(path,body=None):
            if path=="/devices":
                return {"devices":rows}
            role = "heater" if "123456abcdef" in path else "plug"
            return {"state":model[role]}
        with tempfile.TemporaryDirectory() as directory:
            data = InfoData("http://localhost/api/iot",directory,transport=transport)
            self.assertIsNone(data.snapshot()["iot"])
            data.refresh_registry()
            data.poll("heater")
            data.poll("plug")
            self.assertEqual(data.snapshot()["iot"],{"online":2,"total":2})
            data.states["plug"] = (0,model["plug"])
            self.assertEqual(data.snapshot()["iot"],{"online":1,"total":2})
            rows[1]["enabled"] = False
            data.refresh_registry()
            self.assertEqual(data.snapshot()["iot"],{"online":1,"total":1})
            rows.pop(0)
            data.refresh_registry()
            self.assertEqual(data.snapshot()["iot"],{"online":0,"total":0})
            rows.append({"id":"invalid","enabled":True})
            with self.assertRaises(ValueError):
                data.refresh_registry()
            self.assertIsNone(data.snapshot()["iot"])
            data.registry_checked = 0
            self.assertIsNone(data.snapshot()["iot"])
            data.close()


class SystemNavigationTests(unittest.TestCase):
    def test_band_opens_detail_and_brand_goes_home_without_commands(self):
        size = (1024,600)
        calibration = Calibration(((0,1024),(0,600)),size,[[1024,0,0],[0,600,0]])
        data = NS(submit=lambda *args:self.fail("Read-only detail must not submit"))
        state = ScreenState()
        _,hits = render("home",demo_model(),size=size)
        state.tap(Tap(500,95,500,95,False,.1),calibration,hits,data)
        self.assertEqual(state.page,"system")
        _,hits = render(state.page,demo_model(),size=size)
        state.tap(Tap(100,30,100,30,False,.1),calibration,hits,data)
        self.assertEqual(state.page,"home")

    def test_service_pagination_navigation_and_bounds(self):
        model = demo_model()
        model["services"]["items"] = [{"name":"Služba s dlouhým názvem "+str(i),"online":i%2==0} for i in range(19)]
        for size in ((1024,600),(800,480),(1280,720),(320,480)):
            pages = 5 if size==(320,480) else 3
            for section in range(pages):
                model["services_page"] = section
                image,hits = render("system",model,size=size)
                self.assertEqual(image.size,size)
                for i,hit in enumerate(hits):
                    x,y,a,b = hit.rect
                    self.assertTrue(0<=x<a<=size[0] and 0<=y<b<=size[1])
                    self.assertGreaterEqual(a-x,44)
                    self.assertGreaterEqual(b-y,44)
                    for other in hits[i+1:]:
                        xx,yy,aa,bb = other.rect
                        self.assertFalse(max(x,xx)<min(a,aa) and max(y,yy)<min(b,bb))
                navigation = [hit.action for hit in hits if hit.action[0]=="services_page"]
                self.assertEqual(("services_page",section+1) in navigation,section<pages-1)
                self.assertEqual(("services_page",section-1) in navigation,section>0)
        model["services_page"] = 0
        _,hits = render("system",model,size=(1024,600))
        state = ScreenState()
        state.page = "system"
        calibration = Calibration(((0,1024),(0,600)),(1024,600),[[1024,0,0],[0,600,0]])
        state.tap(Tap(930,440,930,440,False,.1),calibration,hits,NS())
        self.assertEqual(state.services_page,1)

    def test_system_missing_data_and_all_historical_flags_render(self):
        for model in ({}, {**demo_model(),"system":{"flags":0xf000f},"services_page":999}):
            for size in ((1024,600),(320,480)):
                self.assertEqual(render("system",model,size=size)[0].size,size)


if __name__=="__main__":
    unittest.main()
