"""Layout of the city under the highway: streets, blocks and parking lots with
individual spaces. Pure Python and deterministic, so the renderer, the screen
map and Auto Park all agree on where every parking space is.

Grid:
  * A north-south street (running along the highway) sits directly under every
    glass median, plus one under the middle of every band. Chunks are one band
    wide (BAND_PERIOD = 216 m) and start at a median centre.
  * East-west streets cross every 100 m along the loop.
"""
import math
import random
from dataclasses import dataclass, field
from functools import lru_cache

from .config import BAND_PERIOD, BAND_W, EARTH_LOOP_M, GAP_W

CX = BAND_PERIOD                 # chunk width (across the highway)
CZ = 200.0                       # chunk length (along the loop)
NZ = int(round(EARTH_LOOP_M / CZ))
X_ORIGIN = BAND_W + GAP_W / 2    # first median centre (204 m)
STREET_W = 16.0
NS_STREETS = (0.0, CX / 2)       # local x of north-south street centrelines
EW_STREETS = (0.0, CZ / 2)       # local z of east-west street centrelines
BLOCKS_X = ((10.0, 98.0), (118.0, 206.0))
BLOCKS_Z = ((10.0, 90.0), (110.0, 190.0))
MAX_H = 54.0

# parking lot geometry (block-relative)
AISLE_X = (14.0, 44.0, 74.0)
AISLE_W = 7.0
SPOT_DEPTH = 5.5
SPOT_PITCH = 2.8
SPOT_START = 8.0
PILLAR_STEP = 90.0
PILLAR_BAND_X = (6.0, 60.0, 132.0, 186.0)   # band-relative x of highway pillars (keep off streets)
PILLAR_HALF = 2.4

LOT_NAMES = ['Cedarfield', 'Harborview', 'Lumen', 'Quartz', 'Maple', 'Orbit', 'Granite', 'Willow',
             'Nova', 'Summit', 'Copper', 'Aurora', 'Juniper', 'Atlas', 'Echo', 'Coral', 'Pioneer', 'Ember']


def chunk_origin_x(cx: int) -> float:
    return cx * CX + X_ORIGIN


def chunk_of(x: float, s: float):
    return math.floor((x - X_ORIGIN) / CX), math.floor(s / CZ) % NZ


def seed(cx, cz, salt=0):
    return ((cx * 73_856_093) ^ (cz * 19_349_663) ^ (salt * 83_492_791) ^ 0x5F3759DF) & 0xFFFFFFFF


@dataclass
class Spot:
    index: int
    x: float            # world x of the spot centre
    s: float            # world s (unwrapped: chunk_s + local z)
    side: int           # -1 spot is left of its aisle, +1 right
    aisle_x: float      # world x of the aisle centreline
    occupied: bool
    blocked: bool       # a highway pillar stands here


@dataclass
class Lot:
    key: tuple          # (cx, cz, block index)
    name: str
    x0: float
    x1: float
    s0: float
    s1: float
    street_s: float     # the east-west street the entrance faces
    spots: list = field(default_factory=list)

    @property
    def center(self):
        return ((self.x0 + self.x1) / 2, (self.s0 + self.s1) / 2)

    @property
    def free(self):
        return [sp for sp in self.spots if not sp.occupied and not sp.blocked]


@dataclass
class Block:
    kind: str           # towers / park / parking
    x0: float           # chunk-local
    z0: float
    x1: float
    z1: float
    lot: Lot = None


@dataclass
class ChunkLayout:
    cx: int
    cz: int
    blocks: list
    pillars: list       # chunk-local (x, z) of pillar centres
    landmark: bool


def pillars_in_chunk(cx, cz):
    """Chunk-local positions of the highway pillars that stand in this chunk."""
    ox = chunk_origin_x(cx)
    s0 = cz * CZ
    out = []
    band = math.floor(ox / BAND_PERIOD)
    for b in (band - 1, band, band + 1):
        for bx in PILLAR_BAND_X:
            lx = b * BAND_PERIOD + bx - ox
            if -PILLAR_HALF <= lx <= CX + PILLAR_HALF:
                z = (-s0) % PILLAR_STEP
                while z <= CZ + PILLAR_HALF:
                    out.append((lx, z))
                    z += PILLAR_STEP
    return out


@lru_cache(maxsize=1024)
def chunk_layout(cx: int, cz: int) -> ChunkLayout:
    cz %= NZ
    rng = random.Random(seed(cx, cz, 1))
    ox, s0 = chunk_origin_x(cx), cz * CZ
    pillars = pillars_in_chunk(cx, cz)
    blocks = []
    bi = 0
    for bx0, bx1 in BLOCKS_X:
        for bz0, bz1 in BLOCKS_Z:
            r = rng.random()
            kind = 'towers' if r < 0.55 else ('park' if r < 0.78 else 'parking')
            blk = Block(kind, bx0, bz0, bx1, bz1)
            if kind == 'parking':
                blk.lot = _make_lot(rng, cx, cz, bi, ox, s0, bx0, bz0, bx1, bz1, pillars)
            blocks.append(blk)
            bi += 1
    return ChunkLayout(cx, cz, blocks, pillars, rng.random() < 0.05)


def _make_lot(rng, cx, cz, bi, ox, s0, bx0, bz0, bx1, bz1, pillars):
    name = f'{rng.choice(LOT_NAMES)} Parking'
    street_z = 0.0 if bz0 < CZ / 2 else CZ / 2
    lot = Lot((cx, cz, bi), name, ox + bx0, ox + bx1, s0 + bz0, s0 + bz1, s0 + street_z)
    n = int((bz1 - bz0 - SPOT_START - 3) // SPOT_PITCH)
    idx = 0
    for ax in AISLE_X:
        for side in (-1, 1):
            sx = bx0 + ax + side * (AISLE_W / 2 + SPOT_DEPTH / 2)
            for i in range(n):
                sz = bz0 + SPOT_START + SPOT_PITCH / 2 + i * SPOT_PITCH
                blocked = any(abs(px - sx) < SPOT_DEPTH / 2 + PILLAR_HALF and abs(pz - sz) < SPOT_PITCH / 2 + PILLAR_HALF
                              for px, pz in pillars)
                occ = (not blocked) and rng.random() < 0.6
                lot.spots.append(Spot(idx, ox + sx, s0 + sz, side, ox + bx0 + ax, occ, blocked))
                idx += 1
    return lot


def lots_near(x: float, s: float, rx: float = 450.0, rs_behind: float = 250.0, rs_ahead: float = 500.0):
    """Parking lots around a point. Lot s values are unwrapped relative to `s`
    (so they may be < 0 or > the loop length near the wrap)."""
    out = []
    cx0, _ = chunk_of(x, s)
    cz_base = math.floor(s / CZ)
    ncx = int(rx // CX) + 1
    for dcz in range(-int(rs_behind // CZ) - 1, int(rs_ahead // CZ) + 2):
        for dcx in range(-ncx, ncx + 1):
            czu = cz_base + dcz                      # unwrapped chunk index
            lay = chunk_layout(cx0 + dcx, czu % NZ)
            shift = (czu - czu % NZ) * CZ            # move wrapped chunks next to the player
            for blk in lay.blocks:
                if blk.lot is None:
                    continue
                lot = blk.lot
                if shift:
                    lot = _shifted(lot, shift)
                lx, ls = lot.center
                if abs(lx - x) <= rx and -rs_behind <= ls - s <= rs_ahead:
                    out.append(lot)
    return out


def _shifted(lot, ds):
    return Lot(lot.key, lot.name, lot.x0, lot.x1, lot.s0 + ds, lot.s1 + ds, lot.street_s + ds,
               [Spot(sp.index, sp.x, sp.s + ds, sp.side, sp.aisle_x, sp.occupied, sp.blocked) for sp in lot.spots])


def nearest_ns_street_x(x: float) -> float:
    cx = math.floor((x - X_ORIGIN) / CX)
    ox = chunk_origin_x(cx)
    best = None
    for k in range(-1, 3):
        sx = ox + k * CX / 2
        if best is None or abs(sx - x) < abs(best - x):
            best = sx
    return best


def median_center_x(x: float) -> float:
    """Centre of the glass median nearest to x (a north-south street lies under it)."""
    cx = round((x - X_ORIGIN) / CX)
    return chunk_origin_x(max(0, cx))


SOLID_KINDS = ('towers', 'park')


def solid_at(x: float, s: float, margin: float = 0.0) -> bool:
    """True if (x, s) at street level is inside a building block or park
    (the curb is the block edge). Streets and parking lots are drivable."""
    s = s % EARTH_LOOP_M
    cx, cz = chunk_of(x, s)
    lx = x - chunk_origin_x(cx)
    lz = s - math.floor(s / CZ) * CZ
    for blk in chunk_layout(cx, cz).blocks:
        if blk.kind in SOLID_KINDS and (blk.x0 - margin <= lx <= blk.x1 + margin
                                        and blk.z0 - margin <= lz <= blk.z1 + margin):
            return True
    return False
