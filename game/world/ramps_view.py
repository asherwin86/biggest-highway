"""Meshes for the ENTRANCE / EXIT ramps and their signs. The ramps are drawn
by each highway band slot, in the glass median to the right of its band."""
from .. import ramps
from ..config import CITY_Y, DECK_Y
from .meshkit import MeshKit

ASPHALT = (0.3, 0.31, 0.34, 1)
WALL = (0.72, 0.72, 0.74, 1)
LINE = (0.95, 0.95, 0.9, 1)
COLUMN = (0.55, 0.56, 0.58, 1)
SIGN_GREEN = (0.05, 0.42, 0.2, 1)
POST = (0.3, 0.33, 0.36, 1)
STEP = 10.0


def _height(kind, z):
    start = ramps.ON_START if kind == 'on' else ramps.OFF_START
    return ramps.surface(ramps.median_x(0), start + z)


def ramp_mesh(kind):
    """One 600 m ramp in local coords: x across (centred), z along, absolute y."""
    k = MeshKit()
    hw = ramps.HALF_W
    n = int(ramps.RAMP_LEN / STEP)
    for i in range(n):
        z0, z1 = i * STEP, (i + 1) * STEP
        h0, h1 = _height(kind, z0), _height(kind, z1)
        # road surface (top) and underside
        k._quad((-hw, h0, z0), (-hw, h1, z1), (hw, h1, z1), (hw, h0, z0), ASPHALT, 1.0)
        if max(h0, h1) > CITY_Y + 0.5:
            k._quad((-hw, h0 - 0.6, z0), (hw, h0 - 0.6, z0), (hw, h1 - 0.6, z1), (-hw, h1 - 0.6, z1), COLUMN, 0.5)
        # side walls (both faces)
        for x, f in ((-hw - 0.3, -1), (hw + 0.3, 1)):
            top0, top1 = h0 + 1.0, h1 + 1.0
            bot0, bot1 = h0 - 0.6, h1 - 0.6
            pts = [(x, bot0, z0), (x, top0, z0), (x, top1, z1), (x, bot1, z1)]
            if f > 0:
                k._quad(*pts, WALL, 0.8)
                k._quad(*reversed(pts), WALL, 0.7)
            else:
                k._quad(*reversed(pts), WALL, 0.8)
                k._quad(*pts, WALL, 0.7)
            k._quad((x - 0.3, top0, z0), (x - 0.3, top1, z1), (x + 0.3, top1, z1), (x + 0.3, top0, z0), WALL, 1.0)
        # dashed centre line and chevrons pointing the way
        if i % 2 == 0:
            y0, y1 = h0 + 0.03, h0 + 0.03 + (h1 - h0) * 0.4
            k._quad((-0.12, y0, z0), (-0.12, y1, z0 + 4), (0.12, y1, z0 + 4), (0.12, y0, z0), LINE, 1.0)
        # support columns
        if i % 4 == 0 and h0 - CITY_Y > 3:
            k.box(-0.7, CITY_Y, z0 - 0.7, 0.7, h0 - 0.6, z0 + 0.7, COLUMN, top=False)
    return k.build()


def exit_sign_mesh():
    """Gantry over the median, 24 m wide, sign facing oncoming traffic (-z)."""
    k = MeshKit()
    k.box_c(-11.5, 4.5, 0, 0.5, 9, 0.5, POST)
    k.box_c(11.5, 4.5, 0, 0.5, 9, 0.5, POST)
    k.box_c(0, 8.8, 0, 24, 0.6, 0.6, POST)
    k.box_c(0, 7.0, -0.45, 14, 3.0, 0.12, SIGN_GREEN)
    return k.build()


def entrance_sign_mesh():
    """Street-level sign beside the bottom of an ENTRANCE ramp."""
    k = MeshKit()
    k.box_c(-6.8, 2.5, 0, 0.3, 5.0, 0.3, POST)
    k.box_c(6.8, 2.5, 0, 0.3, 5.0, 0.3, POST)
    k.box_c(0, 5.2, -0.2, 14.5, 2.4, 0.12, SIGN_GREEN)
    return k.build()


# ---------------------------------------------------------------- per-median entities
from ursina import Color, Entity, Text, color   # noqa: E402

from .. import coords                            # noqa: E402
from ..config import DECK_AHEAD, DECK_BEHIND, EARTH_LOOP_M   # noqa: E402

GLASS = (0.55, 0.85, 1.0)
CENTRE_W = 2 * ramps.HALF_W            # 10 m strip that opens for ramps
SIDE_W = (24.0 - CENTRE_W) / 2         # 7 m of glass either side
L = DECK_BEHIND + DECK_AHEAD
Z_MID = (DECK_AHEAD - DECK_BEHIND) / 2
C = EARTH_LOOP_M
P = ramps.RAMP_PERIOD


def _view_intervals(ps):
    """The visible stretch of loop as wrapped [a, b) intervals."""
    a, b = ps - DECK_BEHIND - ramps.RAMP_LEN, ps + DECK_AHEAD
    if a < 0:
        return [(a % C, C), (0.0, b)]
    if b > C:
        return [(a, C), (0.0, b - C)]
    return [(a, b)]


def _ramp_starts(a, b, start):
    j = int((a - start) // P) - 1
    while True:
        s0 = j * P + start
        if s0 > b:
            break
        if s0 + ramps.RAMP_LEN > a and s0 >= 0 and s0 + ramps.RAMP_LEN <= C + 1e-6:
            yield s0
        j += 1


class MedianSlot:
    """Glass, ramps and signs for the median to the right of one band."""

    def __init__(self, parent, shared):
        glass = Color(*GLASS, 0.22)
        self.sides = [Entity(parent=parent, model='plane', color=glass, double_sided=True) for _ in range(2)]
        self.centres = [Entity(parent=parent, model='plane', color=glass, double_sided=True) for _ in range(5)]
        self.ramps = {}
        self._insts = []
        for kind in ('on', 'off'):
            ents = []
            for _ in range(2):
                e = Entity(parent=parent)
                self._insts.append(shared[kind].instanceTo(e))
                ents.append(e)
            self.ramps[kind] = ents
        self.exit_signs = []
        for _ in range(2):
            e = Entity(parent=parent)
            self._insts.append(shared['exit'].instanceTo(e))
            Text('EXIT   City streets', parent=e, scale=80, origin=(0, 0), y=7.0, z=-0.6, color=color.white)
            self.exit_signs.append(e)
        self.entrance_signs = []
        for _ in range(2):
            e = Entity(parent=parent)
            self._insts.append(shared['entrance'].instanceTo(e))
            Text('ENTRANCE   Highway', parent=e, scale=70, origin=(0, 0), y=5.2, z=-0.35, color=color.white)
            self.entrance_signs.append(e)
        self.all = (self.sides + self.centres + self.ramps['on'] + self.ramps['off']
                    + self.exit_signs + self.entrance_signs)
        self.on = True

    def set_enabled(self, on):
        self.on = on
        if not on:
            for e in self.all:
                e.enabled = False

    def place(self, ps, mx):
        """ps: player loop position, mx: median centre x relative to the player."""
        if not self.on:
            return
        for i, sx in enumerate((-CENTRE_W / 2 - SIDE_W / 2, CENTRE_W / 2 + SIDE_W / 2)):
            e = self.sides[i]
            e.enabled = True
            e.position = (mx + sx, -0.05, Z_MID)
            e.scale = (SIDE_W, 1, L)
        used = {'on': 0, 'off': 0, 'exit': 0, 'entr': 0, 'glass': 0}
        for a, b in _view_intervals(ps):
            holes = []
            for kind, start in (('on', ramps.ON_START), ('off', ramps.OFF_START)):
                for s0 in _ramp_starts(a, b, start):
                    holes.append((s0, s0 + ramps.RAMP_LEN))
                    if used[kind] < 2:
                        e = self.ramps[kind][used[kind]]
                        used[kind] += 1
                        e.enabled = True
                        e.position = (mx, 0, coords.delta_s(ps, s0))
                    if kind == 'off' and used['exit'] < 2:
                        e = self.exit_signs[used['exit']]
                        used['exit'] += 1
                        e.enabled = True
                        e.position = (mx, 0, coords.delta_s(ps, coords.wrap_s(s0 - 250)))
                    if kind == 'on' and used['entr'] < 2:
                        e = self.entrance_signs[used['entr']]
                        used['entr'] += 1
                        e.enabled = True
                        e.position = (mx, CITY_Y, coords.delta_s(ps, coords.wrap_s(s0 - 15)))
            # centre glass = the visible stretch minus the ramp holes
            cur = a
            for h0, h1 in sorted(holes):
                if h0 > cur:
                    self._glass(used, ps, mx, cur, min(h0, b))
                cur = max(cur, h1)
            if cur < b:
                self._glass(used, ps, mx, cur, b)
        for kind in ('on', 'off'):
            for e in self.ramps[kind][used[kind]:]:
                e.enabled = False
        for e in self.exit_signs[used['exit']:]:
            e.enabled = False
        for e in self.entrance_signs[used['entr']:]:
            e.enabled = False
        for e in self.centres[used['glass']:]:
            e.enabled = False

    def _glass(self, used, ps, mx, s0, s1):
        if s1 - s0 < 0.5 or used['glass'] >= len(self.centres):
            return
        e = self.centres[used['glass']]
        used['glass'] += 1
        e.enabled = True
        e.position = (mx, -0.05, coords.delta_s(ps, coords.wrap_s((s0 + s1) / 2)))
        e.scale = (CENTRE_W, 1, s1 - s0)

    def set_brightness(self, b):
        g = Color(GLASS[0] * b, GLASS[1] * b, GLASS[2] * b, 0.22)
        for e in self.sides + self.centres:
            e.color = g
        for e in self.ramps['on'] + self.ramps['off'] + self.exit_signs + self.entrance_signs:
            e.setColorScale(b, b, b, 1)
