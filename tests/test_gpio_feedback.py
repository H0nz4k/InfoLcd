"""Clock sleep/wake, accepted taps, kernel output ownership and pulse shutdown."""
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"lcd"))
from infopanel import ScreenState, validate_settings
from infopanel_gpio import GpioLine, TouchOutputs, gpio_location, gpio_probe
from infopanel_touch import Calibration, Tap
from infopanel_ui import Hit, render
from preview_infopanel import demo_model


class FakeLine:
    def __init__(self, bcm):
        self.bcm = bcm
        self.values = [False]
        self.closed = False
        self.high = threading.Event()
        self.low = threading.Event()

    def set(self, high):
        self.values.append(high)
        (self.high if high else self.low).set()

    def close(self):
        self.set(False)
        self.closed = True


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.outputs = TouchOutputs(21,None,line_factory=FakeLine)
        self.addCleanup(self.outputs.close)
        self.outputs.pulse = Mock(return_value=True)
        self.state = ScreenState(outputs=self.outputs)
        self.calibration = Calibration(((0,1024),(0,600)),(1024,600),[[1024,0,0],[0,600,0]])
        self.data = SimpleNamespace(submit=Mock(return_value=True),snapshot=lambda: demo_model())

    def tap(self,x,y,hits,moved=False):
        return self.state.tap(Tap(x,y,x,y,moved,.1),self.calibration,hits,self.data)

    def test_clock_sleeps_then_first_tap_only_wakes_without_hidden_power_command(self):
        _,hits = render("plug",demo_model(),size=(1024,600))
        self.state.page = "plug"
        self.assertTrue(self.tap(750,30,hits))
        self.assertFalse(self.outputs.backlight_on)
        self.assertTrue(self.outputs.backlight.values[-1])
        command = Hit((10,100,500,500),("command","plug","power",False))
        self.assertTrue(self.tap(100,150,[command]))
        self.assertTrue(self.outputs.backlight_on)
        self.assertFalse(self.outputs.backlight.values[-1])
        self.data.submit.assert_not_called()
        self.assertEqual(self.outputs.pulse.call_count,2)
        self.assertTrue(self.tap(100,150,[command]))
        self.data.submit.assert_called_once_with("plug","power",False)

    def test_invalid_drag_or_contact_in_blank_area_does_not_vibrate(self):
        _,hits = render("home",demo_model(),size=(1024,600))
        self.assertFalse(self.tap(100,30,hits,moved=True))
        self.assertFalse(self.tap(500,580,hits))
        self.outputs.pulse.assert_not_called()

    def test_rejected_api_command_and_unavailable_temperature_do_not_vibrate(self):
        self.data.submit.return_value = False
        self.assertFalse(self.tap(100,120,[Hit((0,100,500,200),("command","plug","power",True))]))
        self.data.snapshot = lambda: {"heater":{"online":False}}
        self.assertFalse(self.tap(100,120,[Hit((0,100,500,200),("temperature",1))]))
        self.outputs.pulse.assert_not_called()

    def test_accepted_navigation_vibrates_once_and_preserves_logo_behavior(self):
        for page,destination in (("home","system"),("system","home"),("heater","home")):
            self.state.page = page
            _,hits = render(page,demo_model(),size=(1024,600))
            self.assertTrue(self.tap(100,30,hits))
            self.assertEqual(self.state.page,destination)
        self.assertEqual(self.outputs.pulse.call_count,3)
        self.data.submit.assert_not_called()

    def test_failed_backlight_write_does_not_claim_sleep_or_vibrate(self):
        self.outputs.backlight.set = Mock(side_effect=OSError("driver failure"))
        with self.assertLogs(level="ERROR"):
            self.assertFalse(self.tap(750,30,[Hit((640,0,1004,64),("backlight",))]))
        self.assertTrue(self.outputs.backlight_on)
        self.outputs.pulse.assert_not_called()
        self.outputs.backlight.set = Mock()

    def test_clock_hit_is_separate_from_logo_on_every_page_and_timer_and_scaled_layout(self):
        for size in ((320,480),(1024,600),(800,480)):
            for page in ("home","meteo","heater","plug","system"):
                for modal in (False,True) if page=="heater" else (False,):
                    _,hits = render(page,demo_model(),size=size,timer_dialog=modal)
                    clock = [h for h in hits if h.action==("backlight",)]
                    self.assertEqual(len(clock),1)
                    self.assertGreaterEqual(clock[0].rect[2]-clock[0].rect[0],44)
                    self.assertGreaterEqual(clock[0].rect[3]-clock[0].rect[1],44)
                    logo = next(h for h in hits if h.action[0]=="page" and h.rect[1]==clock[0].rect[1])
                    self.assertLessEqual(logo.rect[2],clock[0].rect[0])
        _,hits = render("home",{**demo_model(),"backlight_control":False},size=(1024,600))
        self.assertFalse(any(h.action==("backlight",) for h in hits))


class PulseTests(unittest.TestCase):
    def test_motor_pulse_runs_off_ui_thread_and_returns_low(self):
        lines = {}
        def factory(bcm):
            lines[bcm] = FakeLine(bcm)
            return lines[bcm]
        outputs = TouchOutputs(21,20,50,line_factory=factory)
        self.addCleanup(outputs.close)
        motor = lines[20]
        self.assertTrue(outputs.pulse())
        self.assertTrue(motor.high.wait(1))
        # A busy haptic worker does not prevent a backlight change.
        self.assertTrue(outputs.set_backlight(False))
        self.assertTrue(motor.low.wait(1))
        self.assertEqual(motor.values[:3],[False,True,False])
        outputs.close()
        self.assertTrue(motor.closed)
        self.assertFalse(motor.values[-1])
        self.assertFalse(lines[21].values[-1])
        self.assertFalse(outputs.pulse())

    def test_shutdown_during_pulse_stops_motor_and_clears_pending_pulses(self):
        motor = FakeLine(20)
        outputs = TouchOutputs(None,20,150,line_factory=lambda bcm:motor)
        outputs.pulse()
        self.assertTrue(motor.high.wait(1))
        for _ in range(100):
            outputs.pulse()
        outputs.close()
        self.assertFalse(outputs.thread.is_alive())
        self.assertFalse(motor.values[-1])
        self.assertTrue(motor.closed)
        self.assertEqual(motor.values.count(True),1)

    def test_missing_or_busy_motor_does_not_disable_backlight_or_display(self):
        def factory(bcm):
            if bcm==20:
                raise OSError("Device or resource busy")
            return FakeLine(bcm)
        with self.assertLogs(level="WARNING"):
            outputs = TouchOutputs(line_factory=factory)
        self.addCleanup(outputs.close)
        self.assertTrue(outputs.set_backlight(False))
        self.assertFalse(outputs.pulse())
        with self.assertLogs(level="WARNING"):
            missing = TouchOutputs(line_factory=Mock(side_effect=OSError("missing GPIO")))
        self.addCleanup(missing.close)
        self.assertFalse(missing.backlight_available)
        self.assertFalse(missing.set_backlight(False))

    def test_motor_write_failure_attempts_low_and_releases_request(self):
        motor = FakeLine(20)
        normal_set = motor.set
        def fail_high(high):
            normal_set(high)
            if high:
                raise OSError("motor output failure")
        motor.set = fail_high
        outputs = TouchOutputs(None,20,line_factory=lambda bcm:motor)
        self.addCleanup(outputs.close)
        with self.assertLogs(level="ERROR"):
            outputs.pulse()
            outputs.thread.join(1)
        self.assertFalse(outputs.thread.is_alive())
        self.assertTrue(motor.closed)
        self.assertFalse(motor.values[-1])
        self.assertFalse(outputs.pulse())

    def test_configuration_rejects_shared_pins_boolean_pins_and_unbounded_pulse(self):
        self.assertEqual(validate_settings({})["haptic_ms"],50)
        self.assertIsNone(validate_settings({"haptic_gpio":None})["haptic_gpio"])
        for changes in ({"backlight_gpio":20},{"haptic_gpio":True},{"haptic_gpio":38},
                        {"haptic_gpio":"20"},{"haptic_ms":0},{"haptic_ms":151},{"haptic_ms":True}):
            with self.assertRaises(ValueError):
                validate_settings(changes)


class KernelOutputTests(unittest.TestCase):
    def library(self):
        chips = {
            "/dev/gpiochip0":SimpleNamespace(label="unrelated-expander",num_lines=2),
            "/dev/gpiochip4":SimpleNamespace(label="pinctrl-rp1",num_lines=28),
        }
        class Chip:
            def __init__(self,path): self.path = path
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def get_info(self): return chips[self.path]
            def get_line_info(self,offset):
                return SimpleNamespace(name=f"GPIO{offset}",used=True,consumer="infopanel")
        library = SimpleNamespace(Chip=Chip,LineSettings=lambda **kwargs:kwargs,
            line=SimpleNamespace(Value=SimpleNamespace(INACTIVE=0,ACTIVE=1),
                Direction=SimpleNamespace(OUTPUT="output"),Bias=SimpleNamespace(PULL_DOWN="down")),
            request_lines=Mock(return_value=SimpleNamespace(set_value=Mock(),release=Mock())))
        return library

    def test_header_is_discovered_without_assuming_gpiochip_zero_and_probe_does_not_write(self):
        library = self.library()
        with patch("infopanel_gpio.Path.glob",return_value=[Path("/dev/gpiochip0"),Path("/dev/gpiochip4")]), \
             patch("infopanel_gpio.gpio_library",return_value=library):
            self.assertEqual(gpio_location(20,library),("/dev/gpiochip4",20))
            self.assertEqual(gpio_probe(21)["consumer"],"infopanel")
            library.request_lines.assert_not_called()

    def test_request_starts_low_holds_ownership_and_releases_low(self):
        library = self.library()
        with patch("infopanel_gpio.gpio_library",return_value=library), \
             patch("infopanel_gpio.gpio_location",return_value=("/dev/gpiochip4",21)):
            line = GpioLine(21)
            self.assertEqual(library.request_lines.call_args.kwargs["config"][21]["output_value"],0)
            request = line.request
            line.set(True)
            request.release.assert_not_called()
            line.close()
            self.assertEqual(request.set_value.call_args.args,(21,0))
            request.release.assert_called_once()
            line.close()
            request.release.assert_called_once()


if __name__=="__main__":
    unittest.main()
