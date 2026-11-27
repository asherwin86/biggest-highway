"""The highway deck: bands of 48 lanes separated by glass medians, drawn only
around the player (floating origin) and recycled every frame."""
import math
import random

from panda3d.core import PNMImage
from panda3d.core import Texture as PandaTexture
from ursina import Color, Entity, Text, Texture, Vec2, color

from .. import coords, device
from ..config import (BAND_LANES, BAND_PERIOD, BAND_W, BANDS_EACH_SIDE, CITY_Y,
                      DECK_AHEAD, DECK_BEHIND, DECK_THICK, GAP_W, LANE_W, NUM_BANDS)
from ..citylayout import PILLAR_BAND_X
from .meshkit import MeshKit
from .ramps_view import MedianSlot, entrance_sign_mesh, exit_sign_mesh, ramp_mesh

L = DECK_BEHIND + DECK_AHEAD
Z_MID = (DECK_AHEAD - DECK_BEHIND) / 2
TILE = 12.0                 # metres per dash cycle (3 m dash, 9 m gap)
PILLAR_STEP = 90.0
LAMP_STEP = 45.0
GANTRY_STEP = 1000.0
SLOTS = BANDS_EACH_SIDE * 2 + 1


# Textures are drawn with Panda's own PNMImage (no Pillow, so this also runs on Android).
def _rect(img, x0, y0, x1, y1, rgb):
    c = tuple(v / 255 for v in rgb)
    for y in range(y0, y1 + 1):
        for x in range(x0, x1 + 1):
            img.setXel(x, y, *c)


def _to_texture(img, name):
    if device.IS_ANDROID:
        # grey anyway; one channel avoids BGRA uploads, which some OpenGL ES drivers draw black
        img.makeGrayscale()
    t = PandaTexture(name)
    t.load(img)
    return Texture(t)


def lane_texture():
    w, h = 64, 192
    rng = random.Random(7)
    img = PNMImage(w, h, 3)
    for y in range(h):
        for x in range(w):
            n = rng.randint(-6, 6)
            img.setXel(x, y, (52 + n) / 255, (54 + n) / 255, (58 + n) / 255)
    _rect(img, 0, 0, 2, h // 4, (235, 235, 230))                  # dashed lane divider
    _rect(img, w // 2 - 6, 0, w // 2 + 6, h - 1, (48, 50, 54))    # slightly darker tyre track
    tex = _to_texture(img, 'lane')
    tex.filtering = 'mipmap'
    return tex


def checker_texture():
    img = PNMImage(64, 8, 3)
    img.fill(1, 1, 1)
    for i in range(16):
        for j in range(2):
            if (i + j) % 2 == 0:
                _rect(img, i * 4, j * 4, i * 4 + 3, j * 4 + 3, (20, 20, 20))
    return _to_texture(img, 'checker')


def _structure_mesh(width):
    """Pillars under one band + lamp posts on its barriers, one row segment
    covering the whole deck length. Returns (structure, lamp_heads)."""
    k, glow = MeshKit(), MeshKit()
    concrete = (0.55, 0.56, 0.58, 1)
    post = (0.35, 0.36, 0.4, 1)
    lamp = (1.0, 0.92, 0.7, 1)
    n = int(L / PILLAR_STEP) + 2
    # keep pillars off the city streets below (see citylayout.PILLAR_BAND_X)
    xs = list(PILLAR_BAND_X) if width > 190 else [width / 2]
    for i in range(n):
        z = i * PILLAR_STEP
        for x in xs:
            k.box_c(x, (CITY_Y - DECK_THICK) / 2, z, 4.0, -CITY_Y - DECK_THICK, 4.0, concrete, top=False)
        k.box_c(width / 2, -DECK_THICK - 1.2, z, width - 4, 2.4, 3.0, concrete, top=False, bottom=True)
    n2 = int(L / LAMP_STEP) + 2
    for i in range(n2):
        z = i * LAMP_STEP
        for x, d in ((0.6, 1), (width - 0.6, -1)):
            k.box_c(x, 4.5, z, 0.25, 9.0, 0.25, post)
            k.box_c(x + d * 1.2, 9.0, z, 2.4, 0.2, 0.25, post)
            glow.box_c(x + d * 2.2, 8.85, z, 0.9, 0.15, 0.5, lamp)
    return k.build(), glow.build()


def _gantry_mesh(width):
    k = MeshKit()
    steel = (0.3, 0.33, 0.36, 1)
    k.box_c(1.0, 4.5, 0, 0.6, 9, 0.6, steel)
    k.box_c(width - 1.0, 4.5, 0, 0.6, 9, 0.6, steel)
    k.box_c(width / 2, 8.6, 0, width, 1.0, 0.8, steel)
    k.box_c(width / 2, 6.6, -0.45, min(70, width - 8), 3.0, 0.1, (0.05, 0.38, 0.18, 1), sides=True)
    return k.build()


class BandSlot:
    def __init__(self, parent, glow_parent, tex, meshes, ramp_meshes):
        self.band = None
        self.median = MedianSlot(parent, ramp_meshes)
        self.deck = Entity(parent=parent, model='plane', texture=tex, double_sided=True)
        self.slab = Entity(parent=parent, model='cube', color=color.rgb(0.42, 0.43, 0.46))
        self.edge_l = Entity(parent=parent, model='cube', color=color.rgb(0.95, 0.95, 0.92))
        self.edge_r = Entity(parent=parent, model='cube', color=color.rgb(0.95, 0.95, 0.92))
        self.bar_l = Entity(parent=parent, model='cube', color=color.rgb(0.7, 0.7, 0.72))
        self.bar_r = Entity(parent=parent, model='cube', color=color.rgb(0.7, 0.7, 0.72))
        self.struct = Entity(parent=parent)
        self.heads = Entity(parent=glow_parent)
        self.gantries = []
        for _ in range(3):
            g = Entity(parent=parent)
            t = Text('', parent=g, scale=36, origin=(0, 0), color=color.white, y=6.6, z=-0.6)
            self.gantries.append((g, t, [None]))
        self.meshes = meshes
        self._insts = []
        self.dimmable = [self.deck, self.slab, self.bar_l, self.bar_r, self.edge_l, self.edge_r]
        self.base_colors = [e.color for e in self.dimmable]

    def assign(self, band):
        if band == self.band:
            return
        self.band = band
        on = band is not None
        for e in (self.deck, self.slab, self.edge_l, self.edge_r, self.bar_l, self.bar_r,
                  self.struct, self.heads):
            e.enabled = on
        if not on:
            self.median.set_enabled(False)
            for g, _, _ in self.gantries:
                g.enabled = False
            return
        w = coords.band_width(band)
        lanes = coords.band_lane_count(band)
        self.deck.scale = (w, 1, L)
        self.deck.texture_scale = Vec2(lanes, L / TILE)
        self.slab.scale = (w, DECK_THICK, L)
        self.edge_l.scale = self.edge_r.scale = (0.25, 0.02, L)
        self.bar_l.scale = self.bar_r.scale = (0.5, 1.1, L)
        struct, heads, gantry = self.meshes(w)
        for inst in self._insts:
            inst.removeNode()
        # instance the shared meshes: same geometry under many parents, no copies
        self._insts = [struct.instanceTo(self.struct), heads.instanceTo(self.heads)]
        for g, t, key in self.gantries:
            self._insts.append(gantry.instanceTo(g))
            key[0] = None
        self.median.set_enabled(band < NUM_BANDS - 1)
        self.width = w

    def place(self, player_s, player_x, gantry_marks):
        if self.band is None:
            return
        left = coords.band_left_x(self.band) - player_x
        w = self.width
        cx = left + w / 2
        self.deck.position = (cx, 0, Z_MID)
        self.slab.position = (cx, -DECK_THICK / 2 - 0.04, Z_MID)
        self.edge_l.position = (left + 0.3, 0.012, Z_MID)
        self.edge_r.position = (left + w - 0.3, 0.012, Z_MID)
        self.bar_l.position = (left - 0.25, 0.55, Z_MID)
        self.bar_r.position = (left + w + 0.25, 0.55, Z_MID)
        self.median.place(player_s, left + w + GAP_W / 2)
        s0 = player_s - DECK_BEHIND
        self.deck.set_shader_input('texture_offset', Vec2(0, (s0 / TILE) % 1.0))
        # pillar/lamp rows are aligned to world multiples of PILLAR_STEP
        zp = -DECK_BEHIND - (s0 % PILLAR_STEP)
        self.struct.position = (left, 0, zp)
        self.heads.position = (left, 0, zp)
        first_lane = self.band * BAND_LANES
        last_lane = first_lane + coords.band_lane_count(self.band) - 1
        for (g, t, key), mark in zip(self.gantries, gantry_marks):
            g.enabled = True
            g.position = (left, 0, coords.delta_s(player_s, mark))
            if key[0] != mark:
                key[0] = mark
                km = int(round(mark / 1000)) % 40075
                t.text = (f'LANES {coords.fmt_int(first_lane + 1)} - {coords.fmt_int(last_lane + 1)}'
                          f'    KM {coords.fmt_int(km)}')

    def set_brightness(self, b):
        for e, c in zip(self.dimmable, self.base_colors):
            e.color = Color(c[0] * b, c[1] * b, c[2] * b, c[3])
        self.median.set_brightness(b)
        self.struct.setColorScale(b, b, b, 1)
        for g, t, _ in self.gantries:
            g.setColorScale(b, b, b, 1)


class Highway:
    def __init__(self, parent, glow_parent):
        self.tex = lane_texture()
        self._mesh_cache = {}
        ramp_meshes = {'on': ramp_mesh('on'), 'off': ramp_mesh('off'),
                       'exit': exit_sign_mesh(), 'entrance': entrance_sign_mesh()}
        self.slots = [BandSlot(parent, glow_parent, self.tex, self._meshes, ramp_meshes)
                      for _ in range(SLOTS)]
        self.finish = Entity(parent=parent, model='plane', texture=checker_texture(), enabled=False)
        self.finish_text = Text('START / FINISH', parent=parent, scale=120, origin=(0, 0), y=14,
                                color=color.white, enabled=False)
        self.brightness = 1.0

    def _meshes(self, width):
        key = round(width, 2)
        if key not in self._mesh_cache:
            struct, heads = _structure_mesh(width)
            self._mesh_cache[key] = (struct, heads, _gantry_mesh(width))
        return self._mesh_cache[key]

    def update(self, player_s, player_x):
        b0 = int(math.floor(player_x / BAND_PERIOD))
        wanted = [b for b in range(b0 - BANDS_EACH_SIDE, b0 + BANDS_EACH_SIDE + 1) if 0 <= b < NUM_BANDS]
        # keep slots that already show a wanted band, reuse the rest
        by_band = {s.band: s for s in self.slots if s.band in wanted}
        free = [s for s in self.slots if s.band not in by_band]
        for b in wanted:
            if b not in by_band:
                slot = free.pop()
                slot.assign(b)
                slot.set_brightness(self.brightness)
                by_band[b] = slot
        for s in free:
            s.assign(None)

        first = math.ceil((player_s - DECK_BEHIND * 0.5) / GANTRY_STEP) * GANTRY_STEP
        marks = [coords.wrap_s(first + i * GANTRY_STEP) for i in range(3)]
        for s in self.slots:
            s.place(player_s, player_x, marks)

        # start / finish line across the visible bands
        dz = coords.delta_s(player_s, 0.0)
        near = -DECK_BEHIND < dz < DECK_AHEAD
        self.finish.enabled = self.finish_text.enabled = near
        if near:
            span = (SLOTS + 1) * BAND_PERIOD
            self.finish.position = (0, 0.03, dz)
            self.finish.scale = (span, 1, 6)
            self.finish.texture_scale = Vec2(span / 32, 1)
            self.finish_text.position = (0, 14, dz)

    def set_brightness(self, b):
        self.brightness = b
        for s in self.slots:
            s.set_brightness(b)
