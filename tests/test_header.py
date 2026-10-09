"""Visible header invariants across pages and changing system readings."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"lcd"))
from infopanel_ui import render
from preview_infopanel import demo_model


class HeaderTests(unittest.TestCase):
    def test_same_header_on_all_pages_and_home_does_not_expose_ip(self):
        for size in ((1024,600),(320,480)):
            model = demo_model()
            image,_ = render("home",model,size=size)
            header = image.crop((0,0,size[0],50)).tobytes()
            for page in ("meteo","heater","plug","system"):
                detail,_ = render(page,model,size=size)
                self.assertEqual(detail.crop((0,0,size[0],50)).tobytes(),header)
            model["system"]["ip"] = "10.123.123.123"
            changed,_ = render("home",model,size=size)
            self.assertEqual(image.tobytes(),changed.tobytes())

    def test_longer_readings_do_not_move_neighboring_statistics(self):
        image,_ = render("home",demo_model(),size=(1024,600))
        for field,value,regions in (
            ("cpu",100,[(140,60,1004,92)]),
            ("ram",100,[(20,60,140,92),(270,60,1004,92)]),
            ("disk",100,[(20,60,270,92),(402,60,1004,92)]),
            ("temp",140.0,[(20,60,400,92),(532,60,1004,92)]),
            ("uptime","999999 d 23:59",[(20,60,532,92),(800,60,1004,92)]),
        ):
            model = demo_model()
            model["system"][field] = value
            changed,_ = render("home",model,size=(1024,600))
            for region in regions:
                with self.subTest(field=field,region=region):
                    self.assertEqual(image.crop(region).tobytes(),changed.crop(region).tobytes())


if __name__=="__main__":
    unittest.main()
