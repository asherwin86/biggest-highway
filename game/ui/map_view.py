"""Full-screen map: a 1,000,000,000 km wide view with the highway ring around
the Earth, every destination, and a search bar."""
import math

from ursina import (Button, Circle, Color, Entity, InputField, Mesh, Quad, Text,
                    camera, color, held_keys, mouse)

from .. import coords, device
from .osk import OnScreenKeyboard
from ..config import EARTH_R, MAP_SIZE_M

MX0, MX1, MY0, MY1 = -0.86, 0.36, -0.46, 0.42      # map area (UI units)
AW, AH = MX1 - MX0, MY1 - MY0
ACX, ACY = (MX0 + MX1) / 2, (MY0 + MY1) / 2
MIN_W, MAX_W = 2_000.0, MAP_SIZE_M * 1.15
ACCENT = Color(0.22, 0.52, 1.0, 1)
DIM = Color(0.6, 0.63, 0.68, 1)
BTN = Color(0.16, 0.17, 0.21, 1)
KIND_COL = {'City': Color(1, 0.6, 0.25, 1), 'Space': Color(0.85, 0.8, 1, 1), 'Overlook': Color(0.4, 0.9, 1, 1),
            'Landmark': Color(1, 0.9, 0.3, 1)}
PINS = 45


def ring_mesh(inner, outer, segments=256):
    v, t = [], []
    for i in range(segments + 1):
        a = i / segments * 2 * math.pi
        c, s = math.cos(a), math.sin(a)
        v += [(c * inner, s * inner, 0), (c * outer, s * outer, 0)]
        if i < segments:
            n = i * 2
            t += [n, n + 1, n + 3, n, n + 3, n + 2]
    return Mesh(vertices=v, triangles=t)


class MapView:
    def __init__(self, game):
        self.g = game
        self.root = Entity(parent=camera.ui, enabled=False, z=-4)
        r = self.root
        Entity(parent=r, model='quad', scale=(3, 1.2), color=Color(0.03, 0.035, 0.05, 0.97), z=0.05)
        self.area = Entity(parent=r, model='quad', scale=(AW, AH), position=(ACX, ACY, 0.04),
                           color=Color(0.02, 0.025, 0.04, 1), collider='box')
        self.canvas = Entity(parent=r)
        outer = (EARTH_R + coords.TOTAL_WIDTH) / EARTH_R
        self.earth = Entity(parent=self.canvas, model=Circle(96), color=Color(0.15, 0.35, 0.7, 1), z=0.02)
        self.ring = Entity(parent=self.canvas, model=ring_mesh(1.0, outer), color=Color(0.35, 0.37, 0.42, 1),
                           z=0.015, double_sided=True)
        self.ring_edge = Entity(parent=self.canvas, model=ring_mesh(outer - 0.004, outer), color=Color(1, 1, 1, .4),
                                z=0.014, double_sided=True)
        self.route = Entity(parent=self.canvas, model='quad', color=Color(0.22, 0.52, 1.0, 0.8), enabled=False,
                            z=0.01)
        self.pins = []
        for _ in range(PINS):
            b = Button(parent=self.canvas, model=Circle(12), scale=0.011, color=color.white, z=0.0,
                       highlight_scale=1.6)
            lbl = Text('', parent=self.canvas, scale=0.62, origin=(-0.5, 0), color=DIM)
            self.pins.append((b, lbl))
        self.me = Entity(parent=self.canvas, model=Mesh(vertices=[(0, 0.012, 0), (-0.008, -0.009, 0),
                                                                 (0.008, -0.009, 0)], triangles=[0, 1, 2]),
                         color=ACCENT, z=-0.01, double_sided=True)
        self.me2 = Entity(parent=self.canvas, model=Circle(16), scale=0.024, color=Color(0.22, 0.52, 1.0, 0.3))
        # frame overlay to hide pins outside the map area
        for pos, sc in (((ACX, MY1 + 0.3), (AW + 0.02, 0.6)), ((ACX, MY0 - 0.3), (AW + 0.02, 0.6)),
                        ((MX0 - 0.6, 0), (1.2, 1.2)), ((MX1 + 0.6, 0), (1.2, 1.2))):
            Entity(parent=r, model='quad', position=(*pos, -0.03), scale=sc, color=Color(0.03, 0.035, 0.05, 1))

        Text('MAP', parent=r, position=(MX0, 0.465, -0.05), scale=1.4, origin=(-0.5, 0))
        self.scale_txt = Text('', parent=r, position=(MX0 + 0.12, 0.465, -0.05), scale=0.85, color=DIM,
                              origin=(-0.5, 0))
        tools = [('+', lambda: self.zoom(0.5)), ('-', lambda: self.zoom(2)), ('Me', self.center_me),
                 ('All', self.show_all), ('Close', self.close)]
        for i, (n, fn) in enumerate(tools):
            Button(n, parent=r, scale=(0.07, 0.04), position=(MX1 - 0.04 - (len(tools) - 1 - i) * 0.075, 0.465, -0.05),
                   color=BTN, on_click=fn)

        # --- side panel: search + results + selection ---
        sx = 0.39
        Text('Search destinations', parent=r, position=(sx, 0.43, -0.05), scale=0.9, origin=(-0.5, 0))
        self.search = InputField(parent=r, position=(sx + 0.235, 0.385, -0.05), scale=(0.47, 0.05),
                                 character_limit=40)
        self.results = []
        for i in range(8):
            b = Button('...', parent=r, scale=(0.47, 0.042), position=(sx + 0.235, 0.3 - i * 0.047, -0.05),
                       color=Color(0.1, 0.11, 0.14, 1), text_origin=(-0.5, 0))
            b.text_entity.scale *= 0.68
            b.text_entity.x = -0.47
            b.enabled = False
            self.results.append(b)
        self.res_title = Text('', parent=r, position=(sx, 0.343, -0.05), scale=0.7, color=DIM,
                              origin=(-0.5, 0))
        self.sel_name = Text('', parent=r, position=(sx, -0.12, -0.05), scale=1.1, origin=(-0.5, 0))
        self.sel_info = Text(' ', parent=r, position=(sx, -0.16, -0.05), scale=0.72, color=DIM,
                             origin=(-0.5, 0.5))
        self.nav_btn = Button('Navigate (self-driving)', parent=r, scale=(0.3, 0.045), position=(sx + 0.15, -0.37, -0.05),
                              color=ACCENT, on_click=self.navigate)
        self.jump_btn = Button('Jump', parent=r, scale=(0.15, 0.045), position=(sx + 0.395, -0.37, -0.05),
                               color=BTN, on_click=self.jump)
        self.clear_btn = Button('Clear route', parent=r, scale=(0.47, 0.04), position=(sx + 0.235, -0.425, -0.05),
                                color=BTN, on_click=self.clear_route)
        for b in (self.nav_btn, self.jump_btn, self.clear_btn):
            b.text_entity.scale *= 0.75

        # --- controller: crosshair, aim ring, results highlight, on-screen keyboard ---
        self.cross = [Entity(parent=r, model='quad', color=Color(1, 1, 1, 0.7), scale=sc,
                             position=(ACX, ACY, -0.02), enabled=False) for sc in ((0.03, 0.0025), (0.0025, 0.03))]
        self.aim_ring = Entity(parent=self.canvas, model=Circle(24, mode='line', thickness=2), scale=0.03,
                               color=color.yellow, enabled=False, z=-0.02)
        self.pad_hint = Text('', parent=r, position=(ACX, MY0 - 0.025, -0.05), scale=0.66, color=DIM,
                             origin=(0, 0))
        self.osk = OnScreenKeyboard(r, (ACX, ACY - 0.16, -0.08))
        if device.TOUCH:                     # finger-sized keys
            self.osk.root.scale = 1.45
            self.osk.root.y = ACY - 0.1
        self.focus = 'results'
        self.hl = 0
        self._aim = None

        self.center = (0.0, 0.0)
        self.width = 3.5e7
        self.selected = None
        self._q = None
        self._pending, self._pending_t = None, 0.0
        self._clock = 0.0
        self._drag = None
        self._pin_dest = [None] * PINS
        for d in game.directory.all:
            d._mp = d.map_pos()
        self._select(None)

    # ---- open / close ----
    @property
    def is_open(self):
        return self.root.enabled

    def open(self):
        self.root.enabled = True
        self.g.help.enabled = False
        self.g.toast_text.text = ''
        if self.selected is None and self.g.autopilot.destination is not None:
            self._select(self.g.autopilot.destination, recenter=False)
        self.center_me()
        self.search.active = not self.g.pad.using_pad and not device.TOUCH
        self.focus, self.hl = 'results', 0
        self.g.pad.reset_nav()
        self._q = self._pending = self.search.text
        self._run_search()

    def close(self):
        self.search.active = False
        self.osk.root.enabled = False
        self.root.enabled = False

    # ---- view helpers ----
    def to_ui(self, mx, my):
        k = AW / self.width
        return ACX + (mx - self.center[0]) * k, ACY + (my - self.center[1]) * k

    def zoom(self, f, about=None):
        new_w = max(MIN_W, min(MAX_W, self.width * f))
        if about is not None:
            ux, uy = about
            k = AW / self.width
            mx = self.center[0] + (ux - ACX) / k
            my = self.center[1] + (uy - ACY) / k
            f2 = new_w / self.width
            self.center = (mx - (mx - self.center[0]) * f2, my - (my - self.center[1]) * f2)
        self.width = new_w

    def center_me(self):
        p = self.g.player
        self.center = coords.highway_to_map(p.s, p.x)
        self.width = 20_000.0

    def show_all(self):
        self.center = (0.0, 0.0)
        self.width = MAX_W

    # ---- selection ----
    def _select(self, d, recenter=True):
        self.selected = d
        has = d is not None
        self.nav_btn.enabled = has and d.reachable
        self.jump_btn.enabled = has and d.reachable
        if not has:
            self.sel_name.text = ''
            how = '+ / - to zoom' if device.TOUCH else 'Scroll to zoom'
            self.sel_info.text = f'Pick a result or a pin on the map.\n{how}, drag to pan.'
            return
        p = self.g.player
        dist = self.g.directory.distance(p.s, p.x, d)
        self.sel_name.text = d.name
        if d.space:
            info = (f'{d.kind}  -  {coords.fmt_dist(dist)} away.\n{d.blurb}\n'
                    'The highway does not reach this far. Yet.')
        else:
            where = 'City under the highway' if d.city else 'On the highway'
            info = (f'{d.kind}  -  {where}\nLane {coords.fmt_int(d.lane + 1)}   KM {d.s / 1000:,.1f}\n'
                    f'{coords.fmt_dist(dist)} from you   ({d.lane - p.lane:+,} lanes)')
            if d.blurb:
                info += f'\n{d.blurb}'
        self.sel_info.text = info
        if recenter:
            self.center = d._mp if hasattr(d, '_mp') else d.map_pos()
            self.width = max(MIN_W * 4, min(MAX_W, dist * 2.6)) if d.space else max(8_000.0, min(4e7, dist * 2.6))

    def navigate(self):
        if self.selected and self.selected.reachable:
            self.g.set_destination(self.selected)
            self.close()

    def jump(self):
        if self.selected and self.selected.reachable:
            self.g.jump_to(self.selected)
            self.close()

    def clear_route(self):
        self.g.set_destination(None)

    # ---- per-frame ----
    def input(self, key):
        if not self.is_open:
            return False
        if key.startswith('gamepad'):
            return self.pad_input(key)
        if key == 'escape':
            self.close()
            return True
        if key in ('scroll up', 'scroll down') and self._in_area(mouse.position):
            self.zoom(0.8 if key == 'scroll up' else 1.25, about=(mouse.x, mouse.y))
            return True
        if key == 'enter':
            for b in self.results:
                if b.enabled:
                    b.on_click()
                    break
            return True
        return True     # swallow everything else while the map is open

    # ---- controller ----
    def pad_input(self, key):
        if self.osk.is_open:
            return self.osk.handle(key)
        if key in ('gamepad b', 'gamepad start'):
            self.close()
        elif key == 'gamepad a':
            if self.focus == 'map' and self._aim is not None:
                self._select(self._aim, recenter=False)
            elif self.focus == 'results' and self.results[self.hl].enabled:
                self.results[self.hl].on_click()
        elif key == 'gamepad x':
            self.navigate()
        elif key == 'gamepad y':
            self.jump()
        elif key == 'gamepad left shoulder':
            self.search.active = False
            self.osk.open(self.search)
            self.g.pad.reset_nav()
        elif key == 'gamepad right shoulder':
            self.center_me()
        elif key == 'gamepad right stick':
            self.show_all()
        elif key == 'gamepad back':
            self.clear_route()
        return True

    def pad_update(self, dt, nav):
        pad = self.g.pad
        if self.osk.is_open:
            for e in nav:
                self.osk.move(e)
            return
        for e in nav:
            if e in ('up', 'down'):
                n = sum(1 for b in self.results if b.enabled)
                if n:
                    if self.focus != 'results':
                        self.focus = 'results'
                    else:
                        self.hl = (self.hl + (1 if e == 'down' else -1)) % n
        lx, ly = pad.left_stick()
        if abs(lx) > 0 or abs(ly) > 0:
            if max(abs(lx), abs(ly)) > 0.25:
                self.focus = 'map'
            if self.focus == 'map':
                self.center = (self.center[0] + lx * self.width * 0.7 * dt,
                               self.center[1] + ly * self.width * 0.7 * dt)
        zoom = pad.throttle() - pad.brake()
        if zoom:
            self.zoom(1 - zoom * 1.6 * dt)

    @staticmethod
    def _in_area(pos):
        return MX0 < pos[0] < MX1 and MY0 < pos[1] < MY1

    def update(self, dt, t_now):
        if not self.is_open:
            return
        # drag to pan
        if held_keys['left mouse'] and (self._drag is not None or (mouse.hovered_entity == self.area)):
            if self._drag is None:
                self._drag = (mouse.x, mouse.y, self.center)
            else:
                k = self.width / AW
                x0, y0, c0 = self._drag
                self.center = (c0[0] - (mouse.x - x0) * k, c0[1] - (mouse.y - y0) * k)
        else:
            self._drag = None

        # touch screens have no keyboard: tapping the search box opens the on-screen one
        if device.TOUCH and self.search.active and not self.osk.is_open:
            self.search.active = False
            self.osk.open(self.search, touch=True)

        # search (debounced: matching 1,500+ names takes a moment)
        q = self.search.text
        if q != self._pending:
            self._pending, self._pending_t = q, t_now
        if self._pending != self._q and t_now - self._pending_t > 0.2:
            self._q = self._pending
            self._run_search()

        pad = self.g.pad.using_pad
        for c in self.cross:
            c.enabled = pad and self.focus == 'map'
        for i, b in enumerate(self.results):
            hot = pad and self.focus == 'results' and i == self.hl and b.enabled
            b.color = Color(0.22, 0.52, 1.0, 0.55) if hot else Color(0.1, 0.11, 0.14, 1)
        if pad:
            self.pad_hint.text = ('LS pan  LT/RT zoom  D-pad results  A select  X navigate  Y jump  '
                                  'LB search  RB me  R3 all  B close')
        elif device.TOUCH:
            self.pad_hint.text = 'Drag to pan   + / - zoom   tap the search box to type   tap a pin or result'
        else:
            self.pad_hint.text = 'Scroll zoom   drag pan   type to search   Enter pick first result   Esc close'
        self._draw()

    def _run_search(self):
        p = self.g.player
        res = self.g.directory.search(self._q, p.s, p.x, limit=len(self.results))
        self.res_title.text = 'Nearest to you' if not self._q.strip() else f'{len(res)} results'
        self.hl = min(self.hl, max(0, len(res) - 1))
        if self._q.strip() and not res:
            self.res_title.text = 'No matches'
        for b, d in zip(self.results, res + [None] * len(self.results)):
            b.enabled = d is not None
            if d is not None:
                dist = self.g.directory.distance(p.s, p.x, d)
                b.text = f'{d.name}   <gray>{d.kind}  {coords.fmt_dist(dist)}'
                b.text_entity.x = -0.47
                b.on_click = (lambda dd=d: self._select(dd))

    def _draw(self):
        k = AW / self.width
        ex, ey = self.to_ui(0, 0)
        er = EARTH_R * k
        self.canvas.position = (0, 0, 0)
        for e in (self.earth, self.ring, self.ring_edge):
            e.position = (ex, ey, e.z)
            e.scale = er * (2 if e is self.earth else 1)
        p = self.g.player
        mx, my = coords.highway_to_map(p.s, p.x)
        ux, uy = self.to_ui(mx, my)
        heading = math.degrees(coords.wrap_s(p.s) / coords.C * 2 * math.pi)
        self.me.position = (ux, uy, -0.01)
        self.me.rotation_z = -heading       # travel direction is counter-clockwise
        self.me2.position = (ux, uy, -0.005)

        dest = self.selected or self.g.autopilot.destination
        if dest is not None:
            dx, dy = self.to_ui(*dest._mp)
            ln = math.hypot(dx - ux, dy - uy)
            if ln > 0.002:
                self.route.enabled = True
                self.route.position = ((dx + ux) / 2, (dy + uy) / 2, 0.01)
                self.route.scale = (ln, 0.003)
                self.route.rotation_z = -math.degrees(math.atan2(dy - uy, dx - ux))
            else:
                self.route.enabled = False
        else:
            self.route.enabled = False

        self.scale_txt.text = f'View {coords.fmt_dist(self.width)} wide   (map is 1,000,000,000 km)'

        # pins: everything visible, landmarks first
        half_w, half_h = self.width / 2, self.width * AH / AW / 2
        cx, cy = self.center
        vis = []
        for d in self.g.directory.all:
            px, py = d._mp
            if abs(px - cx) < half_w and abs(py - cy) < half_h:
                vis.append(d)
                if len(vis) >= 400:
                    break
        vis.sort(key=lambda d: (d is not dest, d.kind not in KIND_COL, d.space is False and d.city))
        dots, labels = [], []
        i = 0
        for d in vis:
            if i >= PINS:
                break
            u = self.to_ui(*d._mp)
            if any(abs(u[0] - a) < 0.006 and abs(u[1] - b) < 0.006 for a, b in dots):
                continue
            dots.append(u)
            b, lbl = self.pins[i]
            b.enabled = True
            b.position = (u[0], u[1], 0)
            b.color = ACCENT if d is dest else KIND_COL.get(d.kind, color.white)
            b.on_click = (lambda dd=d: self._select(dd, recenter=False))
            room = not any(abs(u[0] - a) < 0.17 and abs(u[1] - c) < 0.024 for a, c in labels)                 and u[0] < MX1 - 0.1
            lbl.enabled = room
            if room:
                labels.append(u)
                if self._pin_dest[i] is not d:
                    lbl.text = d.name
                    self._pin_dest[i] = d
                lbl.position = (u[0] + 0.012, u[1], 0)
            i += 1
        for j in range(i, PINS):
            b, lbl = self.pins[j]
            b.enabled = lbl.enabled = False
        self._aim = None
        if self.g.pad.using_pad and self.focus == 'map':
            best = 0.04
            for d in vis[:200]:
                u = self.to_ui(*d._mp)
                dd = math.hypot(u[0] - ACX, u[1] - ACY)
                if dd < best:
                    best, self._aim = dd, d
        self.aim_ring.enabled = self._aim is not None
        if self._aim is not None:
            u = self.to_ui(*self._aim._mp)
            self.aim_ring.position = (u[0], u[1], -0.02)
