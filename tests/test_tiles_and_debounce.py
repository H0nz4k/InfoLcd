"""Navigace dlaždic a odložený zápis bez síťových či hardwarových změn."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"lcd"))
from infopanel import ScreenState, validate_settings
from infopanel_data import ServiceHealth
from infopanel_landscape import tile_rects
from infopanel_touch import Calibration, Tap
from infopanel_ui import render
from preview_infopanel import demo_model


class DebounceTests(unittest.TestCase):
    def setUp(self):
        self.model = demo_model()
        self.calls = []
        self.data = SimpleNamespace(snapshot=lambda:self.model,submit=self.submit)
        self.state = ScreenState()
        self.state.page = "heater"

    def submit(self,*args,**kwargs):
        self.calls.append(args)
        self.model["busy"] = True
        return True

    def test_fast_taps_send_only_last_value_after_two_seconds_of_quiet(self):
        for i in range(5):
            self.assertTrue(self.state.queue_temperature(1,self.data,now=i*.2))
        self.assertEqual(self.calls,[])
        self.state.tick(self.data,2.79)
        self.assertEqual(self.calls,[])
        self.state.tick(self.data,2.81)
        self.assertEqual(self.calls,[("heater","target_temp_c",30)])
        self.state.tick(self.data,10)
        self.assertEqual(len(self.calls),1)

    def test_tapping_back_to_original_target_sends_nothing(self):
        self.state.queue_temperature(1,self.data,0)
        self.state.queue_temperature(-1,self.data,.2)
        self.assertIsNone(self.state.temperature)
        self.state.tick(self.data,20)
        self.assertEqual(self.calls,[])

    def test_limits_and_draft_do_not_change_observed_state(self):
        for value,delta in ((0,-1),(37,1)):
            self.model["heater"]["target_temp_c"] = value
            self.state.queue_temperature(delta,self.data,0)
            self.state.tick(self.data,3)
        self.assertEqual(self.calls,[])
        self.model["heater"]["target_temp_c"] = 25
        self.state.queue_temperature(1,self.data,0)
        display = self.state.display_model(self.model,1)
        self.assertEqual(display["target_draft_c"],26)
        self.assertEqual(display["heater"]["target_temp_c"],25)
        self.assertNotIn("target_draft_c",self.model)
        self.state.tick(self.data,3)
        self.assertEqual(self.state.display_model(self.model,3)["target_draft_c"],26)
        self.model["busy"] = False
        self.state.tick(self.data,4)
        self.assertNotIn("target_draft_c",self.state.display_model(self.model,4))

    def test_offline_busy_or_changed_selection_cancels_pending(self):
        for change in (lambda:self.model["heater"].update(online=False),
                       lambda:self.model.update(busy=True),
                       lambda:self.model.update(heater_id="abcdef123456")):
            self.model = demo_model()
            self.state.queue_temperature(1,self.data,0)
            change()
            self.state.tick(self.data,3)
            self.assertIsNone(self.state.temperature)
        self.assertEqual(self.calls,[])

    def test_leaving_page_keeps_explicit_change_and_failed_send_is_not_retried(self):
        self.state.queue_temperature(1,self.data,0)
        self.state.page = "home"
        self.data.submit = lambda *args,**kwargs:self.calls.append(args) or False
        self.state.tick(self.data,3)
        self.state.tick(self.data,30)
        self.assertEqual(self.calls,[("heater","target_temp_c",26)])


class TileNavigationTests(unittest.TestCase):
    def test_brand_goes_home_from_every_detail_and_timer(self):
        calibration = Calibration(((0,1024),(0,600)),(1024,600),[[1024,0,0],[0,600,0]])
        data = SimpleNamespace(submit=lambda *args:self.fail("Navigace nesmí poslat příkaz"))
        for page in ("meteo","heater","plug","system"):
            for modal in (False,True) if page=="heater" else (False,):
                state = ScreenState()
                state.page,state.timer_dialog = page,modal
                _,hits = render(page,demo_model(),size=(1024,600),timer_dialog=modal)
                self.assertEqual([h.action for h in hits if h.action[0]=="page"],[("page","home")])
                state.tap(Tap(100,30,100,30,False,.1),calibration,hits,data)
                self.assertEqual((state.page,state.timer_dialog),("home",False))

    def test_chosen_tiles_and_order_without_placeholder_cards(self):
        model = demo_model()
        model["home_tiles"] = ["plug","meteo"]
        _,hits = render("home",model,size=(1024,600))
        self.assertEqual([h.action for h in hits if h.action[0]=="page"],[("page","system"),("page","plug"),("page","meteo")])
        self.assertEqual(validate_settings({"home_tiles":["plug"]})["home_tiles"],["plug"])
        for bad in ([],["other"],["heater","heater"],"meteo",[None]):
            with self.assertRaises(ValueError):
                validate_settings({"home_tiles":bad})

    def test_grid_capacity_nine_nonoverlapping_touch_tiles(self):
        rects = tile_rects(9)
        for i,(x,y,a,b) in enumerate(rects):
            self.assertTrue(0<=x<a<=1024 and 0<=y<b<=600)
            self.assertGreaterEqual(b-y,100)
            for xx,yy,aa,bb in rects[i+1:]:
                self.assertFalse(max(x,xx)<min(a,aa) and max(y,yy)<min(b,bb))
        with self.assertRaises(ValueError):
            tile_rects(10)


class ServiceCountTests(unittest.TestCase):
    def test_dashboard_counts_unavailable_is_not_zero_and_stale_expires(self):
        rows = {"meteo":{"ok":True},"stream":{"ok":False},"iot":{"ok":True}}
        health = ServiceHealth("http://127.0.0.1:4010/api/health",lambda:rows)
        with patch("infopanel_data.time.monotonic",return_value=100):
            health.poll()
            self.assertEqual(health.snapshot(),{"online":2,"total":3,"items":[{"name":key,"online":row["ok"]} for key,row in rows.items()]})
        with patch("infopanel_data.time.monotonic",return_value=191):
            self.assertIsNone(health.snapshot())
        for invalid in ({"x":{"ok":"yes"}},[],None):
            health.transport = lambda:invalid
            health.poll()
            self.assertIsNone(health.snapshot())
        def fail():
            raise OSError("offline")
        health.transport = fail
        health.poll()
        self.assertIsNone(health.snapshot())


if __name__=="__main__":
    unittest.main()
