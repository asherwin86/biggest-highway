"""On-ramps and off-ramps that connect the city to the highway deck.

Every glass median has a street running underneath it. Along each median
there is, every RAMP_PERIOD metres:
  * an ENTRANCE (on-ramp): starts at street level and climbs through an opening
    in the glass to the deck, where you merge into the lanes;
  * an EXIT (off-ramp): you steer onto the median glass, drive into the opening
    and it takes you down to the street below.
Traffic on the highway only goes one way (+s), so both ramps run that way too.
Pure Python."""
import math

from .citylayout import CX, X_ORIGIN
from .config import CITY_Y, DECK_Y, NUM_BANDS

RAMP_PERIOD = 2000.0
ON_START, ON_END = 300.0, 900.0
OFF_START, OFF_END = 1300.0, 1900.0
RAMP_LEN = ON_END - ON_START
HALF_W = 5.0                        # drivable half width of a ramp
RISE = DECK_Y - CITY_Y


def _smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def median_index(x: float):
    m = round((x - X_ORIGIN) / CX)
    return m if 0 <= m < NUM_BANDS - 1 else None


def median_x(m: int) -> float:
    return X_ORIGIN + m * CX


def nearest_median_x(x: float) -> float:
    m = round((x - X_ORIGIN) / CX)
    m = max(0, min(NUM_BANDS - 2, m))
    return median_x(m)


def in_ramp_lane(x: float) -> bool:
    m = median_index(x)
    return m is not None and abs(x - median_x(m)) <= HALF_W


def ramp_kind(s: float):
    u = s % RAMP_PERIOD
    if ON_START <= u <= ON_END:
        return 'on'
    if OFF_START <= u <= OFF_END:
        return 'off'
    return None


def surface(x: float, s: float):
    """Ramp surface height at (x, s), or None if there is no ramp there."""
    if not in_ramp_lane(x):
        return None
    u = s % RAMP_PERIOD
    if ON_START <= u <= ON_END:
        return CITY_Y + RISE * _smooth((u - ON_START) / RAMP_LEN)
    if OFF_START <= u <= OFF_END:
        return DECK_Y - RISE * _smooth((u - OFF_START) / RAMP_LEN)
    return None


def opening(x: float, s: float) -> bool:
    """True where the median glass is open because a ramp passes through it."""
    h = surface(x, s)
    return h is not None and h < DECK_Y - 0.25


def glass_open_ranges():
    """Along-the-loop ranges (within one period) with no centre glass."""
    return ((ON_START, ON_END), (OFF_START, OFF_END))


def next_start(s: float, kind: str, min_ahead: float = 0.0) -> float:
    """Loop position of the next ramp start of `kind` at least min_ahead ahead (unwrapped)."""
    start = ON_START if kind == 'on' else OFF_START
    base = math.floor(s / RAMP_PERIOD) * RAMP_PERIOD + start
    while base < s + min_ahead:
        base += RAMP_PERIOD
    return base


def exit_for(dest_s: float, from_s: float, min_ahead: float = 500.0) -> float:
    """Start of the off-ramp to take to reach dest_s: the last one that lands
    before the destination, or the next one if the destination is too close.
    Values are unwrapped relative to from_s (dest_s must be too)."""
    j = math.floor((dest_s - 40 - OFF_END) / RAMP_PERIOD)
    s0 = j * RAMP_PERIOD + OFF_START
    if s0 < from_s + min_ahead:
        s0 = next_start(from_s, 'off', min_ahead)
    return s0
