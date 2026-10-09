"""Optional GPIO outputs; held kernel requests and bounded background haptic pulses."""
import logging
from pathlib import Path
import threading


def gpio_location(bcm, gpiod):
    """Find the Pi header by chip label and line name, never by gpiochip number."""
    for path in sorted(Path("/dev").glob("gpiochip[0-9]*")):
        with gpiod.Chip(str(path)) as chip:
            info = chip.get_info()
            if not (info.label or "").startswith(("pinctrl-rp1", "pinctrl-bcm")):
                continue
            for offset in range(info.num_lines):
                if chip.get_line_info(offset).name == f"GPIO{bcm}":
                    return str(path), offset
    raise OSError(f"GPIO{bcm} nebylo nalezeno na konektoru Raspberry.")


def gpio_library():
    try:
        import gpiod
    except ImportError as error:
        raise OSError("Chybí python3-libgpiod (libgpiod 2.x).") from error
    if not hasattr(gpiod, "LineSettings"):
        raise OSError("GPIO vyžaduje libgpiod 2.x; nainstaluj python3-libgpiod pro Trixie.")
    return gpiod


def gpio_probe(bcm):
    """Read-only discovery, also usable while the running service owns the line."""
    gpiod = gpio_library()
    path, offset = gpio_location(bcm, gpiod)
    with gpiod.Chip(path) as chip:
        info = chip.get_line_info(offset)
        return {"bcm": bcm, "chip": path, "offset": offset,
                "used": info.used, "consumer": info.consumer}


class GpioLine:
    def __init__(self, bcm):
        gpiod = gpio_library()
        path, self.offset = gpio_location(bcm, gpiod)
        self.value = gpiod.line.Value
        self.request = gpiod.request_lines(path, consumer="hanzhub-infopanel",
            config={self.offset: gpiod.LineSettings(
                direction=gpiod.line.Direction.OUTPUT,
                bias=gpiod.line.Bias.PULL_DOWN,
                output_value=self.value.INACTIVE)})
        logging.info("Infopanel drží GPIO%s na %s, počáteční LOW.", bcm, path)

    def set(self, high):
        self.request.set_value(self.offset, self.value.ACTIVE if high else self.value.INACTIVE)

    def close(self):
        if self.request is not None:
            try:
                self.set(False)
            finally:
                self.request.release()
                self.request = None


class TouchOutputs:
    """LOW = backlight ON through NC; HIGH = motor ON through its driver."""
    def __init__(self, backlight_gpio=21, haptic_gpio=20, haptic_ms=50, line_factory=GpioLine):
        self.backlight = self.motor = None
        self.backlight_on = True  # commanded state, not an optical measurement
        self.haptic_seconds = haptic_ms / 1000
        self.condition = threading.Condition()
        self.stopping = threading.Event()
        self.pending = False  # at most one waiting pulse; rapid taps cannot build a backlog
        self.thread = None
        for attribute, bcm in (("backlight", backlight_gpio), ("motor", haptic_gpio)):
            if bcm is None:
                continue
            try:
                setattr(self, attribute, line_factory(bcm))
            except (OSError, ValueError) as error:
                logging.warning("GPIO%s (%s) není dostupné: %s", bcm, attribute, error)
        if self.motor is not None:
            self.thread = threading.Thread(target=self._haptic_worker, name="infopanel-haptic", daemon=True)
            self.thread.start()

    @property
    def backlight_available(self):
        return self.backlight is not None

    def set_backlight(self, on):
        if self.backlight is None or self.stopping.is_set():
            return False
        try:
            self.backlight.set(not on)
            self.backlight_on = on
            return True
        except (OSError, ValueError) as error:
            logging.error("Podsvícení nelze přepnout: %s", error)
            return False

    def pulse(self):
        with self.condition:
            if self.motor is None or self.stopping.is_set():
                return False
            self.pending = True
            self.condition.notify()
            return True

    def _haptic_worker(self):
        motor = self.motor
        try:
            while not self.stopping.is_set():
                with self.condition:
                    self.condition.wait_for(lambda: self.pending or self.stopping.is_set())
                    if self.stopping.is_set():
                        break
                    self.pending = False
                try:
                    motor.set(True)
                    self.stopping.wait(self.haptic_seconds)
                finally:
                    motor.set(False)
                # Separate consecutive pulses, never extend a running pulse.
                self.stopping.wait(.03)
        except (OSError, ValueError) as error:
            logging.error("Haptika zastavena: %s", error)
        finally:
            self._close_line(motor)
            with self.condition:
                self.motor = None
                self.pending = False

    @staticmethod
    def _close_line(line):
        if line is not None:
            try:
                line.close()
            except (OSError, ValueError) as error:
                logging.error("GPIO nelze vrátit do LOW: %s", error)

    def close(self):
        self.stopping.set()
        with self.condition:
            self.pending = False
            self.condition.notify_all()
        if self.thread is not None:
            self.thread.join()
        self._close_line(self.backlight)
        self.backlight = None
        self.backlight_on = True
