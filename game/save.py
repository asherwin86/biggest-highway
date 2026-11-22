"""Save/load settings and the car's last position.

save.json is personal (it is git-ignored). Loading never trusts it: anything
missing, the wrong type or out of range falls back to a safe default, so an
old, edited or broken save can't crash the game."""
import json
import math
import sys
from pathlib import Path

from .config import CITY_Y, EARTH_LOOP_M, MAX_ALT

from .device import IS_ANDROID

if IS_ANDROID:                             # the app's private storage
    from .device import android_data_dir
    SAVE_PATH = android_data_dir() / 'files' / 'save.json'
elif getattr(sys, 'frozen', False):        # running as the built .exe: save next to it
    SAVE_PATH = Path(sys.executable).resolve().parent / 'save.json'
else:
    SAVE_PATH = Path(__file__).resolve().parents[1] / 'save.json'

CAMERAS = ('Chase', 'Far', 'Cockpit', 'Top', 'Side')


def _num(d, key, default, lo, hi, cast=float):
    v = d.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return default
    return cast(max(lo, min(hi, v)))


def sanitize(data) -> dict:
    """Only known keys, with valid types and ranges. Unknown keys are dropped."""
    from . import coords
    from .vehicles import CAR_BY_ID
    if not isinstance(data, dict):
        return {}
    out = {}
    car = data.get('car')
    if isinstance(car, str) and car in CAR_BY_ID:
        out['car'] = car
    if 's' in data:
        out['s'] = _num(data, 's', 150.0, -1e12, 1e12) % EARTH_LOOP_M
    if 'x' in data:
        out['x'] = coords.clamp_x(_num(data, 'x', coords.lane_center_x(500_000), -1e12, 1e12))
    if 'alt' in data:
        out['alt'] = _num(data, 'alt', 0.0, CITY_Y, MAX_ALT)
    out['laps'] = _num(data, 'laps', 0, -1e9, 1e9, int)
    out['odometer'] = _num(data, 'odometer', 0.0, 0.0, 1e15)
    out['hour'] = _num(data, 'hour', 16.5, -1e9, 1e9) % 24
    out['cruise'] = _num(data, 'cruise', 33.0, 30 / 3.6, 120.0)
    out['traffic_manual'] = _num(data, 'traffic_manual', 0.45, 0.0, 1.0)
    for key in ('flying', 'traffic_auto'):
        if isinstance(data.get(key), bool):
            out[key] = data[key]
    if data.get('camera') in CAMERAS:
        out['camera'] = data['camera']
    return out


def load():
    try:
        return sanitize(json.loads(SAVE_PATH.read_text(encoding='utf-8')))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}


def store(data: dict):
    try:
        tmp = SAVE_PATH.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, indent=1), encoding='utf-8')
        tmp.replace(SAVE_PATH)
    except OSError as e:
        print('could not save:', e)
