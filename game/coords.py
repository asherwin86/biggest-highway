"""Coordinate math for the looping, million-lane highway.

Positions are stored as doubles:
  s : distance along the loop, 0 <= s < EARTH_LOOP_M
  x : lateral distance in metres from the left edge of lane 0
"""
import math

from .config import (BAND_LANES, BAND_PERIOD, BAND_W, EARTH_LOOP_M, EARTH_R,
                     LANE_W, LANES, NUM_BANDS)

C = EARTH_LOOP_M


def wrap_s(s: float) -> float:
    return s % C


def delta_s(a: float, b: float) -> float:
    """Signed shortest distance from a to b along the loop (-C/2, C/2]."""
    d = (b - a) % C
    if d > C / 2:
        d -= C
    return d


def forward_s(a: float, b: float) -> float:
    """Distance driving forward from a to reach b (0 <= d < C)."""
    return (b - a) % C


def clamp_lane(lane: int) -> int:
    return max(0, min(LANES - 1, int(lane)))


def lane_center_x(lane: int) -> float:
    lane = clamp_lane(lane)
    band, i = divmod(lane, BAND_LANES)
    return band * BAND_PERIOD + i * LANE_W + LANE_W / 2


def band_lane_count(band: int) -> int:
    return max(0, min(BAND_LANES, LANES - band * BAND_LANES))


def band_left_x(band: int) -> float:
    return band * BAND_PERIOD


def band_width(band: int) -> float:
    return band_lane_count(band) * LANE_W


TOTAL_WIDTH = band_left_x(NUM_BANDS - 1) + band_width(NUM_BANDS - 1)


def lane_at_x(x: float):
    """Lane under lateral position x, or None if over a glass gap / off the edge."""
    if x < 0 or x >= TOTAL_WIDTH:
        return None
    band = int(x // BAND_PERIOD)
    within = x - band * BAND_PERIOD
    if within >= band_width(band):
        return None
    return clamp_lane(band * BAND_LANES + int(within // LANE_W))


def nearest_lane(x: float) -> int:
    lane = lane_at_x(x)
    if lane is not None:
        return lane
    if x < 0:
        return 0
    if x >= TOTAL_WIDTH:
        return LANES - 1
    band = int(x // BAND_PERIOD)
    within = x - band * BAND_PERIOD
    # in the gap after `band`: pick the closer of last lane of band / first of next
    last = band * BAND_LANES + band_lane_count(band) - 1
    nxt = clamp_lane((band + 1) * BAND_LANES)
    if within - band_width(band) < (BAND_PERIOD - within):
        return last
    return nxt


def surface_at_x(x: float) -> str:
    """'road', 'glass' (median between bands) or 'air' (off the highway)."""
    if x < 0 or x >= TOTAL_WIDTH:
        return 'air'
    return 'road' if lane_at_x(x) is not None else 'glass'


def clamp_x(x: float) -> float:
    return max(LANE_W / 2, min(TOTAL_WIDTH - LANE_W / 2, x))


def highway_to_map(s: float, x: float):
    """Map coordinates (metres) of a highway point: the highway is a ring
    around the Earth, lane 0 on the inside, lane 999,999 on the outside."""
    a = wrap_s(s) / C * 2 * math.pi
    r = EARTH_R + x
    return (r * math.cos(a), r * math.sin(a))


def map_to_highway(mx: float, my: float):
    """Nearest highway point (s, x) to a map point; x clamped to the highway."""
    a = math.atan2(my, mx) % (2 * math.pi)
    r = math.hypot(mx, my)
    return (a / (2 * math.pi) * C, clamp_x(r - EARTH_R))


def fmt_int(n) -> str:
    return f"{int(n):,}"


def fmt_dist(m: float) -> str:
    m = abs(m)
    if m < 1000:
        return f"{m:.0f} m"
    km = m / 1000
    if km < 100:
        return f"{km:.1f} km"
    return f"{km:,.0f} km"
