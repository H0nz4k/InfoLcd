"""Ověření dotyku na širokém displeji bez připojení skutečných zařízení."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"lcd"))
from infopanel import ScreenState, arguments, calibration_targets, validate_settings
from infopanel_touch import Calibration, Tap
from infopanel_ui import BG, CARD, PAGES, layout_for, render
from infopanel_landscape import tile_rects
from preview_infopanel import demo_model


class LandscapeTests(unittest.TestCase):
    def test_orientation_chooses_profile_with_explicit_override(self):
        self.assertEqual(layout_for((1024,600)),"landscape")
        self.assertEqual(layout_for((320,480)),"portrait")
        self.assertEqual(layout_for((600,1024)),"portrait")
        self.assertEqual(layout_for((1024,600),"portrait"),"portrait")
        self.assertEqual(validate_settings({})["layout"],"auto")
        for layout in ("auto","portrait","landscape"):
            self.assertEqual(arguments(["--layout",layout]).layout,layout)
        with self.assertRaises(ValueError):
            validate_settings({"layout":"sideways"})

    def test_overview_fills_screen_and_cards_open_details_without_commands(self):
        size = (1024,600)
        image,hits = render("home",demo_model(),size=size)
        self.assertEqual(image.getpixel((25,200)),CARD)
        self.assertEqual(image.getpixel((998,200)),CARD)
        calibration = Calibration(((0,1024),(0,600)),size,[[1024,0,0],[0,600,0]])
        calls = []
        data = SimpleNamespace(submit=lambda *args:calls.append(args))
        cards = [hit for hit in hits if hit.action[0]=="page" and hit.action[1] in ("meteo","heater","plug")]
        self.assertEqual([hit.action[1] for hit in cards],["meteo","heater","plug"])
        for hit in cards:
            x,y = (hit.rect[0]+hit.rect[2])/2,(hit.rect[1]+hit.rect[3])/2
            state = ScreenState()
            state.tap(Tap(x,y,x,y,False,.1),calibration,hits,data)
            self.assertEqual(state.page,hit.action[1])
        self.assertEqual(calls,[])

    def test_targets_fit_and_do_not_overlap_at_hdmi_resolutions(self):
        for size in ((1024,600),(800,480),(1280,720)):
            for page in PAGES:
                for modal in (False,True) if page=="heater" else (False,):
                    with self.subTest(size=size,page=page,modal=modal):
                        image,hits = render(page,demo_model(),size=size,timer_dialog=modal)
                        self.assertEqual(image.size,size)
                        for i,hit in enumerate(hits):
                            x0,y0,x1,y1 = hit.rect
                            self.assertTrue(0<=x0<x1<=size[0] and 0<=y0<y1<=size[1])
                            self.assertGreaterEqual(x1-x0,44)
                            self.assertGreaterEqual(y1-y0,44)
                            for other in hits[i+1:]:
                                a,b,c,d = other.rect
                                self.assertFalse(max(x0,a)<min(x1,c) and max(y0,b)<min(y1,d))

    def test_rotated_usb_calibration_dispatches_one_temperature_command(self):
        for size in ((1024,600),(800,480),(1280,720)):
            targets = calibration_targets(size)
            def raw(x,y):
                return ((1-y/size[1])*4095,x/size[0]*4095)
            calibration = Calibration.fit(((0,4095),(0,4095)),size,[raw(*point) for point in targets],targets)
            _,hits = render("heater",demo_model(),size=size)
            hit = next(hit for hit in hits if hit.action==("temperature",1))
            point = raw((hit.rect[0]+hit.rect[2])/2,(hit.rect[1]+hit.rect[3])/2)
            calls = []
            data = SimpleNamespace(submit=lambda *args,**kwargs:calls.append(args) or True,snapshot=demo_model)
            state = ScreenState()
            state.page = "heater"
            state.tap(Tap(*point,*point,False,.1),calibration,hits,data)
            self.assertEqual(calls,[])
            state.tick(data,state.temperature["due"])
            self.assertEqual(calls,[("heater","target_temp_c",26)])

    def test_offline_busy_and_incomplete_states_disable_controls(self):
        changes = ({"heater":{"online":False},"plug":{"online":False}},
                   {"busy":True},{"heater":{"online":True},"plug":{"online":True}})
        for change in changes:
            for page in ("heater","plug"):
                _,hits = render(page,{**demo_model(),**change},size=(1024,600))
                self.assertFalse(any(hit.action[0] in ("command","timer","temperature") for hit in hits))
            _,hits = render("heater",{**demo_model(),**change},size=(1024,600),timer_dialog=True)
            self.assertEqual([hit.action for hit in hits],[("page","home"),("timer","close")])

    def test_temperature_bounds_and_missing_values(self):
        for target,expected in ((0,1),(37,-1)):
            model = demo_model()
            model["heater"]["target_temp_c"] = target
            _,hits = render("heater",model,size=(1024,600))
            values = [hit.action[1] for hit in hits if hit.action[0]=="temperature"]
            self.assertEqual(values,[expected])
        for page in PAGES:
            model = {"meteo":{"temp":float("nan")},"heater":{},"plug":{},
                     "heater_name":"Velmi dlouhý název "*20,"plug_name":"Velmi dlouhý název "*20}
            self.assertEqual(render(page,model,size=(1024,600))[0].size,(1024,600))

    def test_modal_blocks_underlying_navigation_and_submits_timer_once(self):
        state = ScreenState()
        state.page,state.timer_dialog = "heater",True
        _,hits = render("heater",demo_model(),timer_dialog=True,size=(1024,600))
        self.assertEqual([hit.action for hit in hits if hit.action[0]=="page"],[("page","home")])
        calibration = Calibration(((0,1024),(0,600)),(1024,600),[[1024,0,0],[0,600,0]])
        calls = []
        data = SimpleNamespace(submit=lambda *args:calls.append(args) or True)
        state.tap(Tap(100,550,100,550,False,.1),calibration,hits,data)
        self.assertEqual((state.page,state.timer_dialog),("heater",True))
        self.assertEqual(calls,[])
        hit = next(hit for hit in hits if hit.action==("command","heater","timer_minutes",120))
        x,y = (hit.rect[0]+hit.rect[2])/2,(hit.rect[1]+hit.rect[3])/2
        state.tap(Tap(x,y,x,y,False,.1),calibration,hits,data)
        self.assertEqual(calls,[("heater","timer_minutes",120)])
        self.assertFalse(state.timer_dialog)

    def test_explicit_portrait_retains_letterbox_and_touch_mapping(self):
        image,hits = render("home",demo_model(),size=(1024,600),layout="portrait")
        self.assertEqual(image.getpixel((25,200)),BG)
        card = next(hit for hit in hits if hit.action==("page","meteo"))
        self.assertEqual(card.rect,(322,72.5,702,182.5))


if __name__=="__main__":
    unittest.main()
