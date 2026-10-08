"""Linux evdev, jedno klepnutí při uvolnění prstu a kalibrace do logických pixelů."""
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import select
import time

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
SYN_REPORT, SYN_DROPPED = 0, 3
ABS_X, ABS_Y = 0, 1
ABS_MT_SLOT, ABS_MT_POSITION_X, ABS_MT_POSITION_Y, ABS_MT_TRACKING_ID = 47, 53, 54, 57
BTN_TOUCH = 330


@dataclass(frozen=True)
class Tap:
    x: float
    y: float
    start_x: float
    start_y: float
    moved: bool
    duration: float


class TouchDecoder:
    """Zpracuje dokončené SYN_REPORT rámce; tažení a ztracené události nejsou klepnutí."""
    def __init__(self, ranges, multitouch=False, initial=(None,None)):
        self.ranges = ranges
        self.multitouch = multitouch
        self.x,self.y = initial
        self.down = self.previous_down = False
        self.slot = 0
        self.started = None
        self.first = None
        self.moved = False
        self.dropped = False

    def feed(self, event, now=None):
        now = time.monotonic() if now is None else now
        if event.type==EV_SYN and event.code==SYN_DROPPED:
            self.dropped = True
            self.started,self.first = None,None
            return None
        if event.type==EV_ABS:
            if self.multitouch:
                if event.code==ABS_MT_SLOT:
                    self.slot = event.value
                elif self.slot==0:
                    if event.code==ABS_MT_TRACKING_ID:
                        self.down = event.value>=0
                    elif event.code==ABS_MT_POSITION_X:
                        self.x = event.value
                    elif event.code==ABS_MT_POSITION_Y:
                        self.y = event.value
            elif event.code==ABS_X:
                self.x = event.value
            elif event.code==ABS_Y:
                self.y = event.value
        elif event.type==EV_KEY and event.code==BTN_TOUCH and not self.multitouch:
            self.down = event.value!=0
        if event.type!=EV_SYN or event.code!=SYN_REPORT:
            return None
        valid = self.x is not None and self.y is not None and all(
            low<=value<=high for value,(low,high) in zip((self.x,self.y),self.ranges))
        result = None
        if self.dropped:
            # Po přetečení čekáme na uvolnění; nikdy neprovedeme původní dotyk.
            if not self.down:
                self.dropped = False
        elif self.down and not self.previous_down and valid:
            self.started,self.first,self.moved = now,(self.x,self.y),False
        elif self.down and self.first and valid:
            self.moved |= any(abs(value-start)/(high-low)>.06
                              for value,start,(low,high) in zip((self.x,self.y),self.first,self.ranges))
        elif not self.down and self.previous_down and self.first and valid:
            moved = self.moved or any(abs(value-start)/(high-low)>.06
                                     for value,start,(low,high) in zip((self.x,self.y),self.first,self.ranges))
            result = Tap(self.x,self.y,*self.first,moved,now-self.started)
            self.started,self.first = None,None
        if not valid:
            self.started,self.first = None,None
        self.previous_down = self.down
        return result


def describe_device(device):
    capabilities = device.capabilities(absinfo=False)
    axes = capabilities.get(EV_ABS,[])
    keys = capabilities.get(EV_KEY,[])
    mt = all(code in axes for code in (ABS_MT_SLOT,ABS_MT_POSITION_X,ABS_MT_POSITION_Y,ABS_MT_TRACKING_ID))
    classic = ABS_X in axes and ABS_Y in axes and BTN_TOUCH in keys
    if not mt and not classic:
        return None
    codes = (ABS_MT_POSITION_X,ABS_MT_POSITION_Y) if mt else (ABS_X,ABS_Y)
    info = [device.absinfo(code) for code in codes]
    if any(axis is None or axis.max<=axis.min for axis in info):
        return None
    ranges = [[axis.min,axis.max] for axis in info]
    identity = [device.name,device.phys,device.info.bustype,device.info.vendor,device.info.product,ranges]
    fingerprint = hashlib.sha256(json.dumps(identity,ensure_ascii=False).encode()).hexdigest()[:24]
    return {"path":device.path,"name":device.name,"ranges":ranges,"multitouch":mt,
            "fingerprint":fingerprint,"initial":[axis.value for axis in info]}


def list_touch_devices():
    import evdev
    descriptions = []
    for path in sorted(evdev.list_devices()):
        device = None
        try:
            device = evdev.InputDevice(path)
            description = describe_device(device)
            if description:
                descriptions.append(description)
        except OSError:
            continue
        finally:
            if device:
                device.close()
    return descriptions


class TouchReader:
    def __init__(self, path="auto"):
        import evdev
        if path=="auto":
            candidates = list_touch_devices()
            if len(candidates)!=1:
                raise ValueError("Nenalezen jednoznačný dotyk. Použij --diagnose a nastav touch na /dev/input/eventX nebo /dev/input/by-path/…")
            path = candidates[0]["path"]
        self.device = evdev.InputDevice(path)
        self.description = describe_device(self.device)
        if not self.description:
            self.device.close()
            raise ValueError(f"{path} není podporovaný dotykový vstup (ABS_X/Y + BTN_TOUCH nebo MT sloty).")
        self.decoder = TouchDecoder(self.description["ranges"],self.description["multitouch"],self.description["initial"])

    def read(self, timeout=.05):
        if not select.select([self.device.fd],[],[],timeout)[0]:
            return []
        taps = []
        try:
            for event in self.device.read():
                tap = self.decoder.feed(event)
                if tap:
                    taps.append(tap)
        except BlockingIOError:
            pass
        return taps

    def close(self):
        self.device.close()


def solve(matrix, vector):
    """Malá soustava bez numpy; pivotování odmítne neplatné kalibrační body."""
    rows = [list(row)+[value] for row,value in zip(matrix,vector)]
    for i in range(len(vector)):
        pivot = max(range(i,len(rows)),key=lambda j:abs(rows[j][i]))
        if abs(rows[pivot][i])<1e-9:
            raise ValueError("Kalibrace: body jsou příliš blízko sebe. Zopakuj kalibraci.")
        rows[i],rows[pivot] = rows[pivot],rows[i]
        divisor = rows[i][i]
        rows[i] = [value/divisor for value in rows[i]]
        for j in range(len(rows)):
            if j!=i:
                factor = rows[j][i]
                rows[j] = [a-factor*b for a,b in zip(rows[j],rows[i])]
    return [row[-1] for row in rows]


class Calibration:
    def __init__(self, ranges, size, coefficients):
        self.ranges,self.size,self.coefficients = ranges,tuple(size),coefficients

    def point(self, x, y):
        normalized = [(value-low)/(high-low) for value,(low,high) in zip((x,y),self.ranges)]+[1]
        return tuple(sum(a*b for a,b in zip(axis,normalized)) for axis in self.coefficients)

    @classmethod
    def fit(cls, ranges, size, raw, targets):
        if len(raw)!=4 or len(targets)!=4:
            raise ValueError("Kalibrace vyžaduje čtyři body.")
        rows = [[(value-low)/(high-low) for value,(low,high) in zip(point,ranges)]+[1] for point in raw]
        matrix = [[sum(row[i]*row[j] for row in rows) for j in range(3)] for i in range(3)]
        coefficients = [solve(matrix,[sum(row[i]*target[axis] for row,target in zip(rows,targets))
                                      for i in range(3)]) for axis in (0,1)]
        result = cls(ranges,size,coefficients)
        error = max(math.dist(result.point(*point),target) for point,target in zip(raw,targets))
        if not math.isfinite(error) or error>min(size)*.035:
            raise ValueError("Kalibrace není přesná. Zopakuj klepnutí na středy křížků.")
        # Každá osa musí pokrýt podstatnou část čidla, aby náhodná klepnutí neaktivovala ovládání.
        if any(max(row[i] for row in rows)-min(row[i] for row in rows)<.35 for i in (0,1)):
            raise ValueError("Kalibrace nepokrývá plochu dotyku.")
        return result

    def save(self, path, fingerprint, rotation):
        payload = {"size":self.size,"ranges":self.ranges,"coefficients":self.coefficients,
                   "fingerprint":fingerprint,"rotation":rotation}
        path = Path(path)
        temporary = path.with_suffix(".new")
        temporary.write_text(json.dumps(payload),encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(path)

    @classmethod
    def load(cls, path, description, size, rotation):
        try:
            data = json.loads(Path(path).read_text())
            if data["size"]!=list(size) or data["rotation"]!=rotation or data["fingerprint"]!=description["fingerprint"]:
                return None
            if data["ranges"]!=[list(axis) for axis in description["ranges"]]:
                return None
            coefficients = data["coefficients"]
            if len(coefficients)!=2 or any(len(axis)!=3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in axis) for axis in coefficients):
                return None
            return cls(data["ranges"],size,coefficients)
        except (OSError,ValueError,KeyError,TypeError):
            return None
