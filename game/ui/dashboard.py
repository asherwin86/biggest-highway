"""EV-style centre touchscreen:
  speed | live 3D self-driving view | trip info + controls | city parking map
Tapping a P on the parking map opens an Auto Park pop-up above it."""
import math

from ursina import Button, Color, Entity, Mesh, Quad, Slider, Text, camera, color

from .. import coords, device
from ..citylayout import CX, CZ, EW_STREETS, NS_STREETS, X_ORIGIN, chunk_origin_x, lots_near
from .. import ramps
from ..config import LANES
from ..autopark import AutoPark
from .viz3d import FSDView

PANEL = Color(0.06, 0.07, 0.09, 0.94)
CARD = Color(0.1, 0.11, 0.14, 1)
ACCENT = Color(0.22, 0.52, 1.0, 1)
DIM = Color(0.6, 0.63, 0.68, 1)
BTN = Color(0.16, 0.17, 0.21, 1)
GREEN = Color(0.2, 0.95, 0.45, 1)
OFF = Color(0.25, 0.27, 0.3, 1)

PX, PY, PW, PH = 0.0, -0.335, 1.66, 0.31
VX0, VX1, VY0, VY1 = -0.645, -0.225, -0.475, -0.195          # 3D view
IX0 = -0.205                                                    # info column
MX0, MX1, MY0, MY1 = 0.38, 0.815, -0.475, -0.195               # parking map
MAP_M = 520.0                                                   # metres across the parking map


def _t(parent, text, x, y, scale=1.0, col=color.white, origin=(-0.5, 0), z=-0.02):
    return Text(text, parent=parent, position=(x, y, z), scale=scale, color=col, origin=origin)


def _tri():
    return Mesh(vertices=[(0, 0.5, 0), (-0.45, -0.5, 0), (0.45, -0.5, 0)], triangles=[0, 1, 2])


class Dashboard:
    def __init__(self, game):
        self.g = game
        self.root = Entity(parent=camera.ui)
        r = self.root
        Entity(parent=r, model=Quad(radius=0.02, aspect=PW / PH), scale=(PW, PH), position=(PX, PY, 0.01),
               color=PANEL)

        # --- speed column ---
        sx = -0.735
        self.speed = _t(r, '0', sx, -0.245, 3.1, origin=(0, 0))
        self.unit = _t(r, 'km/h', sx, -0.303, 0.85, DIM, origin=(0, 0))
        self.gear = _t(r, 'P  R  N  D', sx, -0.345, 0.9, DIM, origin=(0, 0))
        self.mode = _t(r, '', sx, -0.39, 0.62, color.orange, origin=(0, 0))
        self.cruise_lbl = _t(r, '', sx, -0.43, 0.62, DIM, origin=(0, 0))

        # --- live 3D view ---
        self.view = FSDView(r, ((VX0 + VX1) / 2, (VY0 + VY1) / 2, 0.0), (VX1 - VX0, VY1 - VY0))
        self.ap_status = _t(r, '', VX0 + 0.012, VY1 - 0.018, 0.68, color.white)
        self.blink_l = Entity(parent=r, model=_tri(), scale=(0.022, 0.026), rotation_z=-90,
                              position=(VX1 - 0.065, VY1 - 0.02, -0.03), color=OFF, double_sided=True)
        self.blink_r = Entity(parent=r, model=_tri(), scale=(0.022, 0.026), rotation_z=90,
                              position=(VX1 - 0.025, VY1 - 0.02, -0.03), color=OFF, double_sided=True)

        # --- info column ---
        self.lane = _t(r, '', IX0, -0.212, 0.98)
        self.clock = _t(r, '', 0.36, -0.212, 0.85, DIM, origin=(0.5, 0))
        self.loop = _t(r, '', IX0, -0.245, 0.72, DIM)
        self.nav = _t(r, '', IX0, -0.28, 0.8, ACCENT)
        self.traffic = _t(r, '', IX0, -0.318, 0.72)
        self.slider = Slider(0, 1, default=game.density.manual, parent=r, scale=0.3, position=(0.13, -0.318, -0.02),
                             dynamic=True)
        self.slider.label.enabled = False
        self.slider.on_value_changed = self._slider_changed
        self.auto_btn = Button('AUTO', parent=r, scale=(0.06, 0.03), position=(0.33, -0.318, -0.02),
                               color=BTN, on_click=game.toggle_traffic_auto)
        self.auto_btn.text_entity.scale *= 0.7
        rows = [[('Autopilot', game.toggle_autopilot), ('Signal L', lambda: game.signal(-1)),
                 ('Signal R', lambda: game.signal(1)), ('Map', game.toggle_map), ('Car', game.next_car)],
                [('Fly', game.toggle_flight), ('Warp', game.toggle_warp), ('Camera', game.cycle_camera),
                 ('Cruise -', lambda: game.cruise_delta(-10)), ('Cruise +', lambda: game.cruise_delta(10))]]
        self.buttons = {}
        bw, gap = 0.105, 0.0065
        for ri, row in enumerate(rows):
            for i, (name, fn) in enumerate(row):
                b = Button(name, parent=r, scale=(bw, 0.04),
                           position=(IX0 + bw / 2 + i * (bw + gap), -0.365 - ri * 0.047, -0.02),
                           color=BTN, on_click=fn)
                b.text_entity.scale *= 0.68
                self.buttons[name] = b
        self.footer = _t(r, '', IX0, -0.462, 0.6, DIM)

        # --- parking map ---
        Entity(parent=r, model=Quad(radius=0.01, aspect=(MX1 - MX0) / (MY1 - MY0)), scale=(MX1 - MX0, MY1 - MY0),
               position=((MX0 + MX1) / 2, (MY0 + MY1) / 2, 0.005), color=Color(0.13, 0.14, 0.17, 1))
        self.map_root = Entity(parent=r)
        self.streets = [Entity(parent=self.map_root, model='quad', color=Color(0.32, 0.34, 0.38, 1), z=-0.005)
                        for _ in range(24)]
        self.route = [Entity(parent=self.map_root, model='quad', color=ACCENT, z=-0.012) for _ in range(60)]
        self.ramp_marks = [Entity(parent=self.map_root, model='quad', z=-0.008, enabled=False) for _ in range(16)]
        self.lot_btns = []
        for _ in range(14):
            b = Button('P', parent=self.map_root, scale=(0.026, 0.026), color=ACCENT, z=-0.02,
                       radius=0.2)
            b.text_entity.scale *= 0.9
            b.enabled = False
            self.lot_btns.append(b)
        self.me = Entity(parent=self.map_root, model=_tri(), scale=(0.016, 0.022), color=color.white, z=-0.03,
                         double_sided=True)
        self.map_title = _t(r, 'Tap a P to park   green ENTRANCE   orange EXIT', MX0 + 0.01, MY1 - 0.016, 0.62, DIM, z=-0.04)

        # --- Auto Park pop-up ---
        self.popup = Entity(parent=r, enabled=False, z=-0.06)
        Entity(parent=self.popup, model=Quad(radius=0.012, aspect=0.4 / 0.125), scale=(0.4, 0.125),
               color=Color(0.1, 0.11, 0.14, 0.97))
        Entity(parent=self.popup, model='quad', scale=(0.02, 0.02), rotation_z=45, y=-0.0625,
               color=Color(0.1, 0.11, 0.14, 0.97))
        self.pop_title = _t(self.popup, 'Auto Park', -0.185, 0.04, 0.95, z=-0.01)
        self.pop_text = _t(self.popup, '', -0.185, 0.005, 0.68, DIM, z=-0.01)
        self.pop_go = Button('Start', parent=self.popup, scale=(0.11, 0.036), position=(-0.12, -0.037, -0.01),
                             color=ACCENT, on_click=self._popup_start)
        self.pop_x = Button('Cancel', parent=self.popup, scale=(0.11, 0.036), position=(0.0, -0.037, -0.01),
                            color=BTN, on_click=self._popup_cancel)
        for b in (self.pop_go, self.pop_x):
            b.text_entity.scale *= 0.75
        self.pop_lot = None
        self._lots = []
        self._ok = set()
        self._lots_t = 0.0
        self._tick = 0.0
        self._blink = 0.0

    # ------------------------------------------------------------------ pop-up
    def _slider_changed(self):
        self.g.density.auto = False
        self.g.density.manual = self.slider.value

    def open_popup(self, lot, btn_pos):
        g = self.g
        self.pop_lot = lot
        p = g.player
        dist = math.hypot(lot.center[0] - p.x, lot.center[1] - p.s)
        behind = not AutoPark().plan(p, lot)[0]
        self.pop_title.text = lot.name
        self.pop_text.text = (f'{len(lot.free)} free spaces  -  {coords.fmt_dist(dist)}'
                              + ('\nToo close or behind you: pick one further ahead' if behind else '\nStart Auto Park?'))
        pad = g.pad.using_pad
        self.pop_go.text = 'Start  (A)' if pad else 'Start'
        self.pop_go.enabled = not behind and bool(lot.free)
        self.pop_x.text = 'Close  (B)' if pad else 'Close'
        if pad:
            self.pop_text.text += '    LB/RB: other lots'
        self.popup.enabled = True
        x = min(0.62, max(MX0 + 0.05, btn_pos[0]))
        self.popup.position = (x, MY1 + 0.085, -0.06)

    def lot_ui_pos(self, lot):
        p = self.g.player
        k = (MX1 - MX0) / MAP_M
        u = ((MX0 + MX1) / 2 + (lot.center[0] - p.x) * k, MY0 + (MY1 - MY0) * 0.28 + (lot.center[1] - p.s) * k)
        return (max(MX0, min(MX1, u[0])), u[1])

    def _popup_start(self):
        if self.pop_lot is not None:
            self.g.start_autopark(self.pop_lot)

    def _popup_cancel(self):
        if self.g.autopark.active:
            self.g.cancel_autopark()
        self.popup.enabled = False
        self.pop_lot = None

    def toggle(self):
        self.root.enabled = not self.root.enabled

    # ------------------------------------------------------------------ frame
    def update(self, dt):
        g = self.g
        p = g.player
        self.speed.text = f'{abs(p.kmh):,.0f}'
        self.view.update(dt, g)
        self._update_blinkers(dt)
        self._update_parking_map(dt)
        self._tick -= dt
        if self._tick > 0:
            return
        self._tick = 0.1

        park = g.autopark
        gears = ['P', 'R', 'N', 'D']
        if park.state == 'parked' or (abs(p.speed) < 0.3 and not g.autopilot.enabled and not park.active):
            cur = 'P'
        else:
            cur = 'R' if p.speed < -0.3 else 'D'
        self.gear.text = '  '.join(f'<white>{x}<default>' if x == cur else x for x in gears)
        ap = g.autopilot
        if park.active:
            self.ap_status.text = park.status
            self.ap_status.color = ACCENT
        elif park.state == 'parked':
            self.ap_status.text = f'Parked: {park.lot.name}' if park.lot else 'Parked'
            self.ap_status.color = GREEN
        elif ap.enabled:
            self.ap_status.text = f'Self-driving: {g.ap_status}'
            self.ap_status.color = ACCENT
        else:
            self.ap_status.text = 'Self-driving off' + ('' if device.TOUCH else '  (T)')
            self.ap_status.color = DIM
        mode = []
        if p.flying:
            mode.append(f'FLYING {p.alt:,.0f} m')
        if p.under_deck and not p.flying:
            mode.append('CITY')
        if p.warp:
            mode.append('WARP')
        if p.express_active:
            mode.append('EXPRESS')
        if p.hyper_active:
            mode.append('HYPER')
        self.mode.text = '  '.join(mode)
        self.cruise_lbl.text = f'Set {ap.cruise * 3.6:.0f}'

        lane = p.lane + 1
        where = coords.surface_at_x(p.x)
        lane_txt = f'Lane {coords.fmt_int(lane)} of {coords.fmt_int(LANES)}'
        if p.under_deck:
            lane_txt = f'City level under lane {coords.fmt_int(lane)}'
        elif where == 'glass':
            lane_txt += '  (glass)'
        elif where == 'air':
            lane_txt = 'Off the edge of the highway'
        self.lane.text = lane_txt
        self.clock.text = f'{g.daynight.clock}   {p.spec.name}'
        self.loop.text = (f'KM {p.s / 1000:,.1f} of {coords.C / 1000:,.0f} around the Earth   '
                          f'Lap {p.laps}   Odo {p.odometer / 1000:,.0f} km')
        dest = ap.destination
        if dest is None:
            self.nav.text = ('No destination. Tap Map to search.' if device.TOUCH
                             else 'No destination. Press M to search the map.')
        else:
            d = g.directory.distance(p.s, p.x, dest)
            lanes = dest.lane - p.lane if not dest.space else 0
            lt = f'   lanes {lanes:+,}' if lanes else ''
            self.nav.text = f'> {dest.name}   {coords.fmt_dist(d)}{lt}'

        dens = g.density
        self.traffic.text = f'Traffic {dens.value * 100:.0f}%  {dens.status}'
        if dens.auto:
            self.slider.value_setter(dens.value, call_on_value_changed=False)
        self.auto_btn.color = ACCENT if dens.auto else BTN
        self.buttons['Autopilot'].color = ACCENT if ap.enabled else BTN
        self.buttons['Fly'].color = ACCENT if p.flying else (BTN if p.spec.can_fly else Color(0.1, 0.1, 0.12, 1))
        self.buttons['Warp'].color = ACCENT if p.warp else BTN
        if g.pad.using_pad:
            self.footer.text = 'A self-drive  B park  LB/RB signal  Start map  Back menu'
        elif device.TOUCH:
            self.footer.text = f'Camera: {g.camera_mode}   Signal L/R changes lane   Menu: everything else'
        else:
            self.footer.text = f'Camera: {g.camera_mode}   Q/E signal   P parking   Esc menu   F1 help'

        if park.active and self.popup.enabled:
            self.pop_title.text = park.lot.name if park.lot else 'Auto Park'
            stop = 'Pull the stick down' if device.TOUCH else 'Brake (S)'
            self.pop_text.text = f'{park.status.replace("Auto Park: ", "")}\n{stop} or Cancel to stop'
            self.pop_go.enabled = False
            self.pop_x.text = 'Cancel  (B)' if g.pad.using_pad else 'Cancel'

    def _update_blinkers(self, dt):
        self._blink = (self._blink + dt) % 0.8
        on = self._blink < 0.45
        ind = self.g.indicator
        dim_green = Color(0.1, 0.4, 0.2, 1)
        self.blink_l.color = (GREEN if on else dim_green) if ind < 0 else OFF
        self.blink_r.color = (GREEN if on else dim_green) if ind > 0 else OFF

    # ------------------------------------------------------------------ parking map
    def _update_parking_map(self, dt):
        g = self.g
        p = g.player
        k = (MX1 - MX0) / MAP_M
        cx_ui = (MX0 + MX1) / 2
        py = MY0 + (MY1 - MY0) * 0.28

        def ui(x, s_rel):
            return cx_ui + (x - p.x) * k, py + s_rel * k

        def inside(u, pad=0.006):
            return MX0 + pad < u[0] < MX1 - pad and MY0 + pad < u[1] < MY1 - 0.03

        # streets (north-south ones under the glass medians are drawn blue-ish)
        i = 0
        cx0 = math.floor((p.x - X_ORIGIN) / CX)
        for dcx in range(-2, 3):
            ox = chunk_origin_x(cx0 + dcx)
            for sx in NS_STREETS:
                u = ui(ox + sx, 0)
                if MX0 < u[0] < MX1 and i < len(self.streets):
                    e = self.streets[i]
                    e.enabled = True
                    e.position = (u[0], (MY0 + MY1) / 2, -0.005)
                    e.scale = (max(0.003, 16 * k), MY1 - MY0)
                    e.color = Color(0.3, 0.42, 0.6, 1) if sx == 0 else Color(0.3, 0.32, 0.36, 1)
                    i += 1
        base = math.floor(p.s / CZ) * CZ
        for kk in range(-2, 4):
            for sz in EW_STREETS:
                rel = base + kk * CZ + sz - p.s
                u = ui(p.x, rel)
                if MY0 < u[1] < MY1 and i < len(self.streets):
                    e = self.streets[i]
                    e.enabled = True
                    e.position = (cx_ui, u[1], -0.005)
                    e.scale = (MX1 - MX0, max(0.003, 16 * k))
                    e.color = Color(0.3, 0.32, 0.36, 1)
                    i += 1
        for e in self.streets[i:]:
            e.enabled = False

        # ENTRANCE (green) and EXIT (orange) ramps on the streets under the glass medians
        j = 0
        top_s, bot_s = (MY1 - py) / k, (MY0 - py) / k          # visible stretch relative to the car
        period = ramps.RAMP_PERIOD
        for dcx in range(-2, 3):
            mx = chunk_origin_x(cx0 + dcx)
            ux = ui(mx, 0)[0]
            if not (MX0 + 0.004 < ux < MX1 - 0.004) or ramps.median_index(mx) is None:
                continue
            first = math.floor((p.s + bot_s) / period) * period
            for base in (first - period, first, first + period):
                for start, end, col in ((ramps.ON_START, ramps.ON_END, Color(0.25, 0.85, 0.4, 1)),
                                        (ramps.OFF_START, ramps.OFF_END, Color(1.0, 0.55, 0.15, 1))):
                    a = max(base + start - p.s, bot_s)
                    b = min(base + end - p.s, top_s - 0.03 / k)
                    if b <= a or j >= len(self.ramp_marks):
                        continue
                    e = self.ramp_marks[j]
                    j += 1
                    e.enabled = True
                    e.color = col
                    e.position = (ux, py + (a + b) / 2 * k, -0.008)
                    e.scale = (0.006, (b - a) * k)
        for e in self.ramp_marks[j:]:
            e.enabled = False

        # parking lots (refresh the list a few times a second)
        self._lots_t -= dt
        if self._lots_t <= 0:
            self._lots_t = 0.3
            self._lots = lots_near(p.x, p.s, rx=MAP_M / 2 + 60, rs_behind=200, rs_ahead=420)
            self._ok = {l.key for l in self._lots if l.street_s > p.s and AutoPark().plan(p, l)[0]}
        park = g.autopark
        n = 0
        for lot in self._lots:
            if n >= len(self.lot_btns):
                break
            u = ui(lot.center[0], lot.center[1] - p.s)
            if not inside(u, 0.015):
                continue
            b = self.lot_btns[n]
            n += 1
            b.enabled = True
            b.position = (u[0], u[1], -0.02)
            target = park.lot is not None and park.lot.key == lot.key and park.state != 'idle'
            behind = lot.key not in self._ok
            b.color = GREEN if target else (Color(0.3, 0.32, 0.36, 1) if behind or not lot.free else ACCENT)
            b.on_click = (lambda l=lot, bb=b: self.open_popup(l, (bb.x, bb.y)))
        for b in self.lot_btns[n:]:
            b.enabled = False

        # route
        pts = []
        if park.active:
            for x, s in park.route_points(step=12.0):
                pts.append(ui(x, coords.delta_s(p.s, coords.wrap_s(s))))
        j = 0
        for a, b in zip(pts, pts[1:]):
            if j >= len(self.route):
                break
            if not (inside(a, 0) and inside(b, 0)):
                continue
            e = self.route[j]
            j += 1
            ln = math.hypot(b[0] - a[0], b[1] - a[1])
            e.enabled = True
            e.position = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, -0.012)
            e.scale = (ln + 0.003, 0.004)
            e.rotation_z = -math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
        for e in self.route[j:]:
            e.enabled = False
        self.me.position = (*ui(p.x, 0), -0.03)
        self.me.rotation_z = p.yaw
