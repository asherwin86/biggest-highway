"""The endless city under the highway. Each 200 m chunk is generated from a
hash of its grid position, so the same streets come back every time you pass.
Chunks are built a couple per frame and cached."""
import math
import random
from collections import OrderedDict

from ursina import Entity

from .. import coords
from ..citylayout import (CX, CZ, EW_STREETS, MAX_H, NS_STREETS, NZ, SPOT_DEPTH, SPOT_PITCH, X_ORIGIN,
                          chunk_layout, chunk_origin_x)
from ..config import (CITY_AHEAD, CITY_BEHIND, CITY_BUILDS_PER_FRAME, CITY_CACHE, CITY_RADIUS_X, CITY_Y)
from .meshkit import MeshKit

ROAD = (0.17, 0.17, 0.19, 1)
WALK = (0.55, 0.55, 0.56, 1)
LINE = (0.85, 0.75, 0.3, 1)
GRASS = (0.27, 0.5, 0.24, 1)
TRUNK = (0.4, 0.27, 0.15, 1)
LEAF = [(0.18, 0.45, 0.2, 1), (0.25, 0.55, 0.22, 1), (0.15, 0.38, 0.25, 1)]
WATER = (0.2, 0.42, 0.6, 1)
FACADES = [(0.75, 0.72, 0.68, 1), (0.6, 0.62, 0.66, 1), (0.82, 0.78, 0.7, 1), (0.45, 0.5, 0.58, 1),
           (0.7, 0.55, 0.45, 1), (0.35, 0.38, 0.42, 1), (0.85, 0.85, 0.86, 1), (0.55, 0.6, 0.52, 1)]
CAR_COLS = [(0.8, 0.1, 0.1, 1), (0.1, 0.2, 0.6, 1), (0.9, 0.9, 0.9, 1), (0.1, 0.1, 0.1, 1),
            (0.5, 0.5, 0.55, 1), (0.9, 0.7, 0.1, 1)]
WIN_WARM = (1.0, 0.85, 0.55, 1)
WIN_COOL = (0.75, 0.88, 1.0, 1)


def chunk_seed(cx, cz):
    return (cx * 73_856_093) ^ (cz * 19_349_663) ^ 0x5F3759DF


def _windows(glow, rng, x0, z0, x1, z1, h):
    col = WIN_WARM if rng.random() < 0.6 else WIN_COOL
    floors = int(h / 3.6)
    for f in range(1, floors):
        if rng.random() > 0.42:
            continue
        y0, y1 = f * 3.6, f * 3.6 + 1.3
        o = 0.06
        face = rng.randrange(4)
        if face == 0:
            glow.quad_z(z0 - o, y0, y1, x0 + 1, x1 - 1, col, -1, 1.0)
        elif face == 1:
            glow.quad_z(z1 + o, y0, y1, x0 + 1, x1 - 1, col, 1, 1.0)
        elif face == 2:
            glow.quad_x(x0 - o, y0, y1, z0 + 1, z1 - 1, col, -1, 1.0)
        else:
            glow.quad_x(x1 + o, y0, y1, z0 + 1, z1 - 1, col, 1, 1.0)


def _towers(k, glow, rng, bx0, bz0, bx1, bz1, landmark=False):
    k.box(bx0, 0, bz0, bx1, 0.25, bz1, WALK, sides=True)
    n = rng.choice((1, 2, 2, 3))
    w = (bx1 - bx0 - 4) / n
    d = (bz1 - bz0 - 4) / n
    for i in range(n):
        for j in range(n):
            lx0 = bx0 + 2 + i * w + rng.uniform(1, 3)
            lz0 = bz0 + 2 + j * d + rng.uniform(1, 3)
            lx1 = bx0 + 2 + (i + 1) * w - rng.uniform(1, 3)
            lz1 = bz0 + 2 + (j + 1) * d - rng.uniform(1, 3)
            h = min(MAX_H, rng.choice((8, 12, 16, 22, 30, 38, 46)) + rng.uniform(-2, 6))
            if landmark and i == 0 and j == 0:
                h = MAX_H - 4
            col = rng.choice(FACADES)
            k.box(lx0, 0.25, lz0, lx1, h, lz1, col)
            # roof details
            if rng.random() < 0.7:
                rx, rz = (lx0 + lx1) / 2, (lz0 + lz1) / 2
                k.box_c(rx, h + 1.2, rz, (lx1 - lx0) * 0.35, 2.4, (lz1 - lz0) * 0.35,
                        (0.5, 0.5, 0.52, 1))
            if landmark and i == 0 and j == 0:
                rx, rz = (lx0 + lx1) / 2, (lz0 + lz1) / 2
                k.box_c(rx, h + 2.5, rz, 0.4, 5, 0.4, (0.7, 0.7, 0.7, 1))
                glow.box_c(rx, h + 5.2, rz, 0.8, 0.8, 0.8, (1.0, 0.15, 0.1, 1))
            _windows(glow, rng, lx0, lz0, lx1, lz1, h)


def _park(k, glow, rng, bx0, bz0, bx1, bz1):
    k.box(bx0, 0, bz0, bx1, 0.3, bz1, GRASS)
    if rng.random() < 0.4:
        cx, cz = (bx0 + bx1) / 2, (bz0 + bz1) / 2
        r = (bx1 - bx0) * 0.2
        k.quad_up(cx - r, cz - r * 0.7, cx + r, cz + r * 0.7, 0.32, WATER)
    for _ in range(rng.randint(8, 16)):
        x = rng.uniform(bx0 + 3, bx1 - 3)
        z = rng.uniform(bz0 + 3, bz1 - 3)
        h = rng.uniform(3, 6)
        k.box_c(x, 0.3 + h / 2, z, 0.5, h, 0.5, TRUNK, top=False)
        s = rng.uniform(2.5, 4.5)
        k.box_c(x, 0.3 + h + s / 2 - 0.5, z, s, s, s, rng.choice(LEAF), bottom=True)
    for i in range(4):   # path lamps
        x = bx0 + (bx1 - bx0) * (0.2 + 0.2 * i)
        k.box_c(x, 1.8, (bz0 + bz1) / 2, 0.15, 3.6, 0.15, (0.3, 0.3, 0.3, 1))
        glow.box_c(x, 3.7, (bz0 + bz1) / 2, 0.5, 0.3, 0.5, WIN_WARM)


def _parking_lot(k, glow, rng, lot, ox, s0, bx0, bz0, bx1, bz1, pillars):
    """Lot surface, painted spaces, parked cars and a P sign (from the shared layout)."""
    k.box(bx0, 0, bz0, bx1, 0.15, bz1, (0.3, 0.3, 0.33, 1))
    line = (0.92, 0.92, 0.9, 1)
    hatch = (0.85, 0.7, 0.15, 1)
    y = 0.17
    for sp in lot.spots:
        lx, lz = sp.x - ox, sp.s - s0
        x0, x1 = lx - SPOT_DEPTH / 2, lx + SPOT_DEPTH / 2
        k.quad_up(x0, lz - SPOT_PITCH / 2 - 0.06, x1, lz - SPOT_PITCH / 2 + 0.06, y, line)
        back = x1 if sp.side > 0 else x0
        k.quad_up(back - 0.06, lz - SPOT_PITCH / 2, back + 0.06, lz + SPOT_PITCH / 2, y, line)
        if sp.blocked:
            k.quad_up(x0 + 0.5, lz - 1.0, x1 - 0.5, lz + 1.0, y + 0.005, hatch)
        elif sp.occupied:
            col = rng.choice(CAR_COLS)
            k.box_c(lx, 0.85, lz, 4.3, 1.2, 1.85, col)
            k.box_c(lx + sp.side * 0.3, 1.7, lz, 2.2, 0.6, 1.6, (0.15, 0.18, 0.22, 1))
    # P sign at the entrance
    sx, sz = bx0 + 3, bz0 + 1.5
    k.box_c(sx, 2.2, sz, 0.2, 4.4, 0.2, (0.35, 0.35, 0.38, 1))
    glow.box_c(sx, 5.0, sz, 2.2, 2.2, 0.25, (0.15, 0.4, 0.95, 1))
    glow.box_c(sx - 0.35, 5.0, sz - 0.15, 0.3, 1.5, 0.05, (1, 1, 1, 1))
    glow.box_c(sx + 0.15, 5.45, sz - 0.15, 0.7, 0.25, 0.05, (1, 1, 1, 1))
    glow.box_c(sx + 0.15, 5.0, sz - 0.15, 0.7, 0.2, 0.05, (1, 1, 1, 1))
    glow.box_c(sx + 0.45, 5.22, sz - 0.15, 0.2, 0.55, 0.05, (1, 1, 1, 1))


def build_chunk(cx, cz):
    """Returns (base_mesh, glow_mesh) for chunk (cx, cz) in chunk-local coords."""
    lay = chunk_layout(cx, cz)
    rng = random.Random(chunk_seed(cx, cz))
    ox, s0 = chunk_origin_x(cx), (cz % NZ) * CZ
    k, glow = MeshKit(), MeshKit()
    k.quad_up(0, 0, CX, CZ, 0, ROAD)
    # dashed centre lines on every street
    for sx in NS_STREETS:
        z = 0.0
        while z < CZ:
            k.quad_up(sx - 0.15, z, sx + 0.15, z + 3, 0.02, LINE)
            z += 8
    for sz in EW_STREETS:
        x = 0.0
        while x < CX:
            k.quad_up(x, sz - 0.15, x + 3, sz + 0.15, 0.02, LINE)
            x += 8
    for bi, blk in enumerate(lay.blocks):
        if blk.kind == 'towers':
            _towers(k, glow, rng, blk.x0, blk.z0, blk.x1, blk.z1, lay.landmark and bi == 0)
        elif blk.kind == 'park':
            _park(k, glow, rng, blk.x0, blk.z0, blk.x1, blk.z1)
        else:
            _parking_lot(k, glow, rng, blk.lot, ox, s0, blk.x0, blk.z0, blk.x1, blk.z1, lay.pillars)
    # street lights on the corners
    for x in NS_STREETS:
        for z in EW_STREETS:
            k.box_c(x + 9, 3.5, z + 9, 0.2, 7, 0.2, (0.3, 0.3, 0.32, 1))
            glow.box_c(x + 9, 7.1, z + 9, 0.7, 0.25, 0.7, WIN_WARM)
    return k.build(), glow.build()


class City:
    def __init__(self, parent, glow_parent):
        nx = CITY_RADIUS_X * 2 + 1
        nz = CITY_BEHIND + CITY_AHEAD + 1
        self.slots = []
        for _ in range(nx * nz):
            base = Entity(parent=parent)
            glow = Entity(parent=glow_parent)
            self.slots.append([None, base, glow, []])   # key, base, glow, instances
        self.cache = OrderedDict()
        self.visible = True
        self.root = parent

    def _mesh(self, key, allow_build):
        m = self.cache.get(key)
        if m is not None:
            self.cache.move_to_end(key)
            return m
        if not allow_build:
            return None
        m = build_chunk(*key)
        self.cache[key] = m
        while len(self.cache) > CITY_CACHE:
            self.cache.popitem(last=False)
        return m

    def update(self, player_s, player_x, budget=CITY_BUILDS_PER_FRAME):
        pcx = math.floor((player_x - X_ORIGIN) / CX)
        pcz = math.floor(player_s / CZ)
        wanted = []
        for dz in range(-CITY_BEHIND, CITY_AHEAD + 1):
            for dx in range(-CITY_RADIUS_X, CITY_RADIUS_X + 1):
                wanted.append((pcx + dx, (pcz + dz) % NZ, abs(dx) + abs(dz)))
        wanted.sort(key=lambda t: t[2])                 # build nearest first
        wanted_keys = {(a, b) for a, b, _ in wanted}
        slot_by_key = {s[0]: s for s in self.slots if s[0] in wanted_keys}
        free = [s for s in self.slots if s[0] not in wanted_keys]

        for cx, cz, _ in wanted:
            key = (cx, cz)
            slot = slot_by_key.get(key)
            if slot is None:
                if key not in self.cache and budget <= 0:
                    continue                        # build it on a later frame
                if key not in self.cache:
                    budget -= 1
                mesh = self._mesh(key, True)
                slot = free.pop()
                slot_by_key[key] = slot
                self._show(slot, key, mesh)
            slot[1].position = (chunk_origin_x(cx) - player_x, CITY_Y, coords.delta_s(player_s, cz * CZ))
            slot[2].position = slot[1].position
        for s in free:
            self._show(s, None, None)

    @staticmethod
    def _show(slot, key, mesh):
        for inst in slot[3]:
            inst.detachNode()
        slot[3] = []
        slot[0] = key
        if mesh is None:
            return
        base, glow = mesh
        if base is not None:
            base.reparentTo(slot[1])
            slot[3].append(base)
        if glow is not None:
            glow.reparentTo(slot[2])
            slot[3].append(glow)
