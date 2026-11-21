"""The game: ties the simulation, world streaming, camera and UI together."""
import math
import random

from ursina import Color, Entity, Text, application, camera, held_keys, time, window

from . import coords, save
from .autopark import AutoPark
from .controller import Pad, is_pad_key
from .autopilot import Autopilot
from .citylayout import lots_near
from .config import (CITY_Y, DECK_Y, EARTH_LOOP_M, FOG_END, LANES, START_HOUR)
from .destinations import Directory
from .traffic import TrafficDensity, TrafficSim
from .vehicles import CAR_BY_ID, CARS, Controls, PlayerCar
from .world.car_models import load_player_model
from .world.city import City
from .world.highway import Highway
from .world.sky import DayNight
from .world.traffic_view import TrafficView
from .ui.dashboard import Dashboard
from .ui.map_view import MapView
from .ui.quick_menu import QuickMenu

HELP = """<white>BIGGEST HIGHWAY<default>   1,000,000 lanes around the whole Earth

W / S      accelerate / brake (hold S to reverse)
A / D      steer          Q / E   lane change / turn signal
[ / ]      jump 1,000 lanes        PageUp / PageDown also work
T          full self-driving        M   map + search
1 - 5      choose car  (5 = Volt Roadster, it flies)
F          fly (Roadster)   Space / Ctrl   up / down
               fly down through the glass medians into the city
X          warp (up to 30,000 km/h)     C   camera
P          Auto Park (or tap a P on the screen)    R  back to the highway deck
H          hide screen    F1  this help
"""

HELP_PAD = """<white>CONTROLLER<default>   1,000,000 lanes around the whole Earth

Left stick     steer                 RT / LT   accelerate / brake (hold LT to reverse)
LB / RB        change lane (hold to keep going)  -  with self-driving: turn signal
A              full self-driving      B   Auto Park  (in the pop-up: A start, B close, LB/RB other lots)
X              fly (Volt Roadster)    Right stick up/down: climb / descend
Y              next car               Right stick left/right: look around
D-pad up/down  cruise speed           D-pad left/right: jump 1,000 lanes
R3 (click RS)  camera                 L3 (click LS): warp
Start          map + search           Back   menu (everything else is in here)
"""

CAMERAS = ['Chase', 'Far', 'Cockpit', 'Top', 'Side']


class Game(Entity):
    def __init__(self, args):
        super().__init__()
        self.args = args
        data = {} if args.fresh else save.load()
        self.directory = Directory()
        self.density = TrafficDensity()
        self.density.auto = data.get('traffic_auto', True)
        self.density.manual = data.get('traffic_manual', 0.45)
        self.traffic = TrafficSim()
        self.autopilot = Autopilot()
        self.autopilot.cruise = data.get('cruise', 33.0)
        self.autopark = AutoPark()
        self.daynight = DayNight(data.get('hour', START_HOUR))

        spec = CAR_BY_ID.get(data.get('car'), CARS[0])
        self.player = PlayerCar(spec)
        start_x = coords.lane_center_x(500_000)
        self.player.teleport(data.get('s', 150.0), data.get('x', start_x), data.get('alt', DECK_Y))
        self.player.laps = data.get('laps', 0)
        self.player.odometer = data.get('odometer', 0.0)
        self.player.flying = spec.can_fly and data.get('flying', False)

        # --- world (everything is drawn relative to the car: floating origin) ---
        self._manual_signal = 0
        self._manual_signal_t = 0.0
        self._blink = 0.0
        self.cam_yaw = 0.0
        self.world = Entity()
        self.glow = Entity()
        self.highway = Highway(self.world, self.glow)
        self.city_root = Entity(parent=self.world)
        self.city_glow = Entity(parent=self.glow)
        self.city = City(self.city_root, self.city_glow)
        self.traffic_view = TrafficView(self.world)
        self.car = Entity()
        self._car_inst = None
        self.thrusters = [Entity(parent=self.car, model='cube', color=Color(0.35, 0.9, 1, 1),
                                 scale=(0.5, 0.12, 0.8), position=(x, 0.12, -1.1), enabled=False)
                          for x in (-0.75, 0.75)]
        amber = Color(1.0, 0.62, 0.05, 1)
        self.blinkers = {d: [Entity(parent=self.car, model='cube', color=amber, scale=(0.18, 0.12, 0.08),
                                    enabled=False) for _ in range(2)] for d in (-1, 1)}
        self.lift_pad = Entity(model='cube', color=Color(0.3, 0.85, 1, 1), scale=(3.4, 0.2, 5.8), enabled=False)
        self.lift_beam = Entity(model='cube', color=Color(0.3, 0.85, 1, 0.16), scale=(6, 60, 8), enabled=False)
        self._set_car_model()
        self.speed_lines = []
        rng = random.Random(3)
        for _ in range(40):
            e = Entity(model='cube', color=Color(1, 1, 1, 0.35), enabled=False)
            e._off = (rng.uniform(-26, 26), rng.uniform(-2, 14), rng.uniform(-20, 220))
            self.speed_lines.append(e)

        camera.fov = 72
        camera.clip_plane_far = 5000
        self.cam_i = CAMERAS.index(data.get('camera', 'Chase')) if data.get('camera') in CAMERAS else 0
        self.manual_target_x = coords.lane_center_x(self.player.lane)

        # --- UI ---
        self.pad = Pad(on_change=self._pad_changed)
        self.look_yaw = 0.0
        self._shoulder_t = {}
        self.dashboard = Dashboard(self)
        self.map = MapView(self)
        self.menu = QuickMenu(self)
        self.toast_text = Text('', parent=camera.ui, position=(0.25, 0.42, -2), origin=(0, 0), scale=1.15)
        self.toast_t = 0.0
        self.help = Text(HELP, parent=camera.ui, position=(-0.86, 0.47, -2), origin=(-0.5, 0.5), scale=0.78,
                         background=True)
        self.help_t = 14.0
        self.flash = Entity(parent=camera.ui, model='quad', scale=(4, 2), color=Color(1, 1, 1, 0), z=-3)
        self.ap_status = ''
        self.plan_lane = None
        self._save_t = 0.0
        self._hit_cool = 0.0
        self._clock = 0.0
        self.frame = 0
        window.fps_counter.enabled = True

        self.highway.update(self.player.s, self.player.x)
        self.city.update(self.player.s, self.player.x, budget=60)
        self._apply_daynight(force=True)
        if args.shot:
            self.help.enabled = False
        self.toast('Welcome to the biggest highway ever built', 4)
        if self.pad.connected:
            self.pad.using_pad = True
            self.help.text = HELP_PAD
            self.toast(f'Controller ready: {self.pad.names[0]}', 4)

    # ================================================================ helpers
    @property
    def camera_mode(self):
        return CAMERAS[self.cam_i]

    def toast(self, msg, secs=2.5):
        if self.args.shot and msg.startswith(('Welcome', 'Controller')):
            return                       # keep scripted screenshots clean
        self.toast_text.text = msg
        self.toast_t = secs

    def _set_car_model(self):
        if self._car_inst is not None:
            self._car_inst.removeNode()
        model, from_file = load_player_model(self.player.spec)
        self._car_inst = model
        model.reparentTo(self.car)
        self.car.shader = self.car.shader      # re-apply shader to the new child
        for t in self.thrusters:
            t.enabled = self.player.flying
        spec = self.player.spec
        for d, pair in self.blinkers.items():
            x = d * (spec.width / 2 - 0.12)
            pair[0].position = (x, spec.height * 0.55, -spec.length / 2 - 0.03)
            pair[1].position = (x, spec.height * 0.4, spec.length / 2 + 0.03)

    @property
    def indicator(self):
        if self.autopilot.enabled:
            return self.autopilot.indicator
        return self._manual_signal if self._manual_signal_t > 0 else 0

    def _do_flash(self):
        self.flash.color = Color(1, 1, 1, 0.9)

    # ================================================================ actions
    def toggle_autopilot(self):
        ap = self.autopilot
        if not ap.enabled and (self.player.flying or self.player.under_deck):
            self.toast('Self-driving needs the highway deck')
            return
        ap.enabled = not ap.enabled
        ap.target_lane = None
        self.toast('Full self-driving ON' if ap.enabled else 'Self-driving off')
        if not ap.enabled:
            self.manual_target_x = coords.lane_center_x(self.player.lane)

    def set_destination(self, d):
        self.autopilot.set_destination(d)
        if d is None:
            self.toast('Route cleared')
            return
        if not self.autopilot.enabled:
            if self.player.flying or self.player.under_deck:
                self.toast(f'Route set to {d.name}. Land on the deck and press T')
                return
            self.autopilot.enabled = True
        self.toast(f'Navigating to {d.name}', 3)

    def jump_to(self, d):
        p = self.player
        alt = CITY_Y if d.city else DECK_Y
        p.teleport(d.s - 40, d.x, alt)
        p.speed = 0.0
        if d.city and not p.spec.can_fly:
            p.flying = False
        self.autopilot.set_destination(None)
        self.autopilot.enabled = False
        self.manual_target_x = d.x
        self._do_flash()
        self.toast(f'Jumped to {d.name}' + ('  (city level, press R to go back up)' if d.city else ''), 3.5)

    def return_to_highway(self):
        p = self.player
        lane = p.lane
        p.flying = False
        p.teleport(p.s, coords.lane_center_x(lane), DECK_Y)
        self.manual_target_x = p.x
        for t in self.thrusters:
            t.enabled = False
        self._do_flash()
        self.toast(f'Back on the deck, lane {coords.fmt_int(lane + 1)}')

    def select_car(self, i):
        p = self.player
        p.spec = CARS[i % len(CARS)]
        if not p.spec.can_fly and p.flying:
            p.flying = False
        self._set_car_model()
        self.toast(f'{p.spec.name}: {p.spec.max_kmh:.0f} km/h, 0-100 in {p.spec.zero_100} s. {p.spec.blurb}', 3)

    def next_car(self):
        self.select_car(CARS.index(self.player.spec) + 1)

    def toggle_flight(self):
        p = self.player
        if not p.toggle_flight():
            self.toast('Only the Volt Roadster can fly (press 5)')
            return
        if p.flying and self.autopilot.enabled:
            self.autopilot.enabled = False
        for t in self.thrusters:
            t.enabled = p.flying
        self.toast('Flight mode: Space up, Ctrl down' if p.flying else 'Landing...')

    def toggle_warp(self):
        p = self.player
        p.warp = not p.warp
        self.toast('WARP ON: hold W, up to 30,000 km/h' if p.warp else 'Warp off')

    def cycle_camera(self, d=1):
        self.cam_i = (self.cam_i + d) % len(CAMERAS)

    def show_help(self):
        self.help.text = HELP_PAD if self.pad.using_pad else HELP
        self.help.enabled = True
        self.help_t = 1e9

    def _pad_changed(self, msg):
        self.toast(msg, 3)
        self.pad.using_pad = self.pad.connected

    def popup_cycle(self, d):
        """LB/RB in the Auto Park pop-up: show the previous/next lot."""
        lots = self.feasible_lots()
        if not lots:
            return
        p = self.player
        lots.sort(key=lambda l: abs(l.center[0] - p.x) + abs(l.center[1] - p.s))
        cur = self.dashboard.pop_lot
        keys = [l.key for l in lots]
        i = keys.index(cur.key) if cur is not None and cur.key in keys else -d
        lot = lots[(i + d) % len(lots)]
        self.dashboard.open_popup(lot, self.dashboard.lot_ui_pos(lot))

    def cruise_delta(self, kmh):
        ap = self.autopilot
        ap.cruise = max(30 / 3.6, min(self.player.spec.max_speed, ap.cruise + kmh / 3.6))

    def toggle_traffic_auto(self):
        self.density.auto = not self.density.auto
        self.toast('Auto-adapt traffic ON' if self.density.auto else 'Traffic: manual (use the slider)')

    def toggle_map(self):
        if self.map.is_open:
            self.map.close()
        else:
            self.map.open()

    # ---------------- turn signal / Auto Park
    def signal(self, d):
        """Turn signal. With self-driving on it asks the car to change lanes when safe."""
        if self.autopilot.enabled:
            self.autopilot.request_lane_change(d)
            if self.autopilot.signal:
                side = 'left' if d < 0 else 'right'
                self.toast(f'Signal {side}: changing lanes when it is safe', 2)
            else:
                self.toast('Signal cancelled', 1.2)
        else:
            self.lane_change(d)

    def feasible_lots(self):
        p = self.player
        out = []
        for lot in lots_near(p.x, p.s, rx=320, rs_behind=0, rs_ahead=500):
            ok, _ = AutoPark().plan(p, lot)
            if ok:
                out.append(lot)
        return out

    def open_nearest_parking(self):
        lots = self.feasible_lots()
        p = self.player
        if not lots:
            self.toast('No free parking lot ahead right now')
            return
        lot = min(lots, key=lambda l: abs(l.center[0] - p.x) + abs(l.center[1] - p.s))
        if not self.dashboard.root.enabled:
            self.dashboard.toggle()
        self.dashboard.open_popup(lot, (0.6, -0.3))

    def start_autopark(self, lot):
        p = self.player
        if self.autopark.active:
            return
        if p.flying:
            p.flying = False
            for t in self.thrusters:
                t.enabled = False
        ok, msg = self.autopark.plan(p, lot)
        self.toast(msg, 3)
        if ok:
            self.autopilot.enabled = False
            self.autopilot.signal = 0
        else:
            self.dashboard.popup.enabled = False

    def cancel_autopark(self):
        was_lifting = self.autopark.cancel()
        if was_lifting:
            self.player.alt = CITY_Y
        self.manual_target_x = None
        self.dashboard.popup.enabled = False
        self.toast('Auto Park cancelled')

    def lane_change(self, n):
        p = self.player
        if p.flying or p.under_deck:
            return
        self._manual_signal, self._manual_signal_t = (1 if n > 0 else -1), 1.6
        base = self.manual_target_x if self.manual_target_x is not None else p.x
        lane = coords.clamp_lane(coords.nearest_lane(base) + n)
        self.manual_target_x = coords.lane_center_x(lane)

    def lane_jump(self, n):
        p = self.player
        lane = coords.clamp_lane(p.lane + n)
        p.teleport(p.s, coords.lane_center_x(lane), p.alt if not p.under_deck else p.alt)
        self.manual_target_x = p.x
        self.autopilot.target_lane = None
        self._do_flash()
        self.toast(f'Lane {coords.fmt_int(lane + 1)}')
        self.pad.rumble(0.3, 0.5, 0.12)

    # ================================================================ input
    def input(self, key):
        if is_pad_key(key):
            self.pad.using_pad = True
        elif not key.endswith(' up') and 'mouse' not in key and 'scroll' not in key and key != 'escape':
            self.pad.using_pad = False
        if self.menu.is_open:
            self.menu.handle(key)
            return
        if self.map.is_open:
            if self.map.input(key):
                return
        if is_pad_key(key):
            self._pad_input(key)
            return
        if key == 'escape':
            if self.help.enabled:
                self.help.enabled = False
            elif self.dashboard.popup.enabled and not self.autopark.active:
                self.dashboard.popup.enabled = False
            else:
                self.menu.open()
            return
        if key in ('m', 'tab'):
            self.toggle_map()
        elif key == 't':
            self.toggle_autopilot()
        elif key == 'f':
            self.toggle_flight()
        elif key == 'x':
            self.toggle_warp()
        elif key == 'c':
            self.cycle_camera()
        elif key == 'h':
            self.dashboard.toggle()
        elif key == 'f1':
            if self.help.enabled:
                self.help.enabled = False
            else:
                self.show_help()
        elif key == 'r':
            self.return_to_highway()
        elif key == 'v':
            self.next_car()
        elif key in ('q', 'e'):
            d = -1 if key == 'q' else 1
            if self.autopilot.enabled:
                self.signal(d)
            else:
                self.lane_change(d * (10 if held_keys['shift'] else 1))
        elif key == 'p':
            self.open_nearest_parking()
        elif key in (']', 'page up'):
            self.lane_jump(1000)
        elif key in ('[', 'page down'):
            self.lane_jump(-1000)
        elif key in ('=', '+'):
            self.cruise_delta(10)
        elif key == '-':
            self.cruise_delta(-10)
        elif key in ('1', '2', '3', '4', '5'):
            self.select_car(int(key) - 1)
        elif key == 'f9':        # debug: just before the loop wraps around
            self.player.teleport(EARTH_LOOP_M - 400, self.player.x, self.player.alt)
            self.toast('Debug: 400 m before the loop wraps')

    def _pad_input(self, key):
        dash = self.dashboard
        popup = dash.popup.enabled
        if self.help.enabled and key in ('gamepad b', 'gamepad a'):
            self.help.enabled = False
            return
        if key == 'gamepad back':
            self.menu.open()
        elif key == 'gamepad start':
            self.toggle_map()
        elif popup and key == 'gamepad a' and not self.autopark.active:
            dash._popup_start()
        elif popup and key == 'gamepad b':
            dash._popup_cancel()
        elif popup and key in ('gamepad left shoulder', 'gamepad right shoulder') and not self.autopark.active:
            self.popup_cycle(-1 if 'left' in key else 1)
        elif key == 'gamepad b':
            if self.autopark.active:
                self.cancel_autopark()
            else:
                self.open_nearest_parking()
        elif key == 'gamepad a':
            self.toggle_autopilot()
        elif key == 'gamepad x':
            self.toggle_flight()
        elif key == 'gamepad y':
            self.next_car()
        elif key in ('gamepad left shoulder', 'gamepad right shoulder'):
            d = -1 if 'left' in key else 1
            self._shoulder_t[d] = 0.45
            self.signal(d)
        elif key == 'gamepad dpad up':
            self.cruise_delta(10)
            self.toast(f'Cruise {self.autopilot.cruise * 3.6:.0f} km/h', 1.2)
        elif key == 'gamepad dpad down':
            self.cruise_delta(-10)
            self.toast(f'Cruise {self.autopilot.cruise * 3.6:.0f} km/h', 1.2)
        elif key == 'gamepad dpad left':
            self.lane_jump(-1000)
        elif key == 'gamepad dpad right':
            self.lane_jump(1000)
        elif key == 'gamepad right stick':
            self.cycle_camera()
            self.toast(f'Camera: {self.camera_mode}', 1.2)
        elif key == 'gamepad left stick':
            self.toggle_warp()

    def _pad_frame(self, dt):
        """Per-frame controller work: menu navigation and hold-to-repeat lane changes."""
        pad = self.pad
        pad.update(dt)
        nav = pad.nav_events(dt)
        if self.menu.is_open:
            self.menu.nav(nav)
            return
        if self.map.is_open:
            self.map.pad_update(dt, nav)
            return
        for d, name in ((-1, 'left'), (1, 'right')):
            if held_keys[f'gamepad {name} shoulder'] and d in self._shoulder_t and not self.autopilot.enabled:
                self._shoulder_t[d] -= dt
                if self._shoulder_t[d] <= 0:
                    self._shoulder_t[d] = 0.22
                    self.lane_change(d)
            else:
                self._shoulder_t.pop(d, None)

    @property
    def menus_open(self):
        return self.map.is_open or self.menu.is_open

    # ================================================================ frame
    def _controls(self, dt):
        p = self.player
        ap = self.autopilot
        if ap.enabled and (p.flying or p.under_deck):
            ap.enabled = False
            self.toast('Self-driving needs the highway deck')
        if ap.enabled:
            if not self.menus_open and (held_keys['s'] or held_keys['down arrow'] or self.pad.brake() > 0.3):
                ap.enabled = False
                self.manual_target_x = coords.lane_center_x(p.lane)
                self.toast('Self-driving disengaged (brake)')
            else:
                plan = ap.plan(dt, p, self.traffic.nearby(p, 220, 60, 3))
                self.ap_status = plan.status
                self.plan_lane = plan.path_lane
                if plan.arrived:
                    name = ap.destination.name if ap.destination else ''
                    ap.set_destination(None)
                    ap.enabled = False
                    self.manual_target_x = p.x
                    self.toast(f'You have arrived: {name}', 4)
                return plan.controls
        self.plan_lane = None
        if self.menus_open:
            return Controls(target_x=self.manual_target_x)
        k = held_keys
        pad = self.pad
        steer = (k['d'] or k['right arrow']) - (k['a'] or k['left arrow'])
        if not steer:
            steer = pad.steer()
        _, ry = pad.right_stick()
        c = Controls(throttle=max(float(k['w'] or k['up arrow']), pad.throttle()),
                     brake=max(float(k['s'] or k['down arrow']), pad.brake()),
                     steer=float(steer), up=max(float(k['space']), ry if p.flying else 0.0),
                     down=max(float(k['left control'] or k['right control'] or k['control']),
                              -ry if p.flying else 0.0))
        if steer:
            self.manual_target_x = None
        elif self.manual_target_x is None and not p.flying and not p.under_deck:
            # let go of the wheel: settle into the nearest lane
            self.manual_target_x = coords.lane_center_x(p.lane)
        if p.flying or p.under_deck:
            self.manual_target_x = None
        c.target_x = self.manual_target_x
        return c

    def update(self):
        dt = min(time.dt, 0.05) * self.args.timescale
        self._clock += dt
        self.frame += 1
        p = self.player
        self._scripted_setup()
        if self.args.scene == 'cityturn' and self.frame > 2:     # turn right at the intersection
            near = coords.delta_s(p.s, 400.0) < 7
            held_keys['w'] = 0.0 if near and p.yaw < 80 else 1.0
            held_keys['d'] = 1.0 if (near or 5 < p.yaw < 85) else 0.0

        self.daynight.update(dt)
        dens = self.density.update(dt, self.daynight.hour)
        self._manual_signal_t -= dt
        park = self.autopark
        k = held_keys
        self._pad_frame(dt)
        pad = self.pad
        driver_input = not self.menus_open and (
            any(k[x] for x in ('w', 's', 'a', 'd', 'up arrow', 'down arrow'))
            or pad.throttle() > 0.2 or pad.brake() > 0.2 or abs(pad.steer()) > 0.3)
        if park.active:
            if not self.menus_open and (k['s'] or k['down arrow'] or pad.brake() > 0.3):
                self.cancel_autopark()
            else:
                ev = park.update(dt, p)
                if ev == 'lift':
                    self.toast('Glass lift: going down to the city', 3)
                    pad.rumble(0.25, 0.05, 0.5)
                elif ev == 'parked':
                    pad.rumble(0.5, 0.2, 0.18)
                    self.toast(f'Parked in {park.lot.name}, space {park.spot.index + 1}', 5)
                    self.dashboard.popup.enabled = False
        elif park.state == 'parked' and not driver_input:
            p.speed = 0.0                     # stay put in the space until you drive off
        else:
            if park.state == 'parked':
                park.state = 'idle'
            p.update(dt, self._controls(dt))
        while p.events:
            ev = p.events.pop()
            if ev == 'wall':
                pad.rumble(0.7, 0.4, 0.15)
            if ev == 'lap':
                self.toast(f'LAP {p.laps}! You drove all the way around the Earth', 5)
                pad.rumble(1.0, 1.0, 0.6)

        fast = abs(p.speed) > 300 or p.express_active
        self.traffic.suspended = fast
        hit = self.traffic.update(dt, p, dens)
        self._hit_cool -= dt
        if hit is not None and self._hit_cool <= 0 and not park.active:
            self._hit_cool = 1.0
            if hit.rel_s > 0:
                p.speed = min(p.speed, hit.speed * 0.8)
            else:
                hit.speed = max(hit.speed, p.speed + 2)
            self.toast('Bump! Watch the traffic (or press T)', 1.5)
            pad.rumble(0.9, 0.7, 0.25)

        self.highway.update(p.s, p.x)
        self.city_root.enabled = self.city_glow.enabled = not fast
        if not fast:
            self.city.update(p.s, p.x)
        self.traffic_view.update(self.traffic.cars, p.x)

        self.car.position = (0, p.alt, 0)
        self.car.rotation_y = p.yaw
        self.car.rotation_z = max(-20, min(20, -p.vx * 1.2)) if p.flying else 0
        self.car.rotation_x = max(-12, min(12, -p.vy * 0.6)) if p.flying else 0
        self._blink = (self._blink + dt) % 0.8
        ind = self.indicator
        for d, pair in self.blinkers.items():
            on = ind == d and self._blink < 0.45
            for b in pair:
                b.enabled = on
        lifting = park.active and park.stage is not None and park.stage.kind == 'lift'
        self.lift_pad.enabled = self.lift_beam.enabled = lifting
        if lifting:
            self.lift_pad.position = (0, p.alt - 0.12, 0)
            self.lift_beam.position = (0, CITY_Y / 2, 0)

        self._update_camera(dt)
        self._update_speed_lines(dt, fast)
        self._apply_daynight()

        self.dashboard.update(dt)
        self.map.update(dt, self._clock)
        if self.toast_t > 0:
            self.toast_t -= dt
            self.toast_text.color = Color(1, 1, 1, max(0.0, min(1.0, self.toast_t * 2)))
        if self.help_t < 1e8:
            self.help_t -= dt
            if self.help_t <= 0:
                self.help.enabled = False
                self.help_t = 1e9
        a = self.flash.color[3]
        if a > 0:
            self.flash.color = Color(1, 1, 1, max(0.0, a - dt * 2.5))

        self._save_t += dt
        if self._save_t > 5:
            self._save_t = 0
            self.save()
        self._scripted_capture()

    def _update_camera(self, dt):
        p = self.player
        mode = self.camera_mode
        follow = self.autopark.state != 'idle' or p.under_deck
        want = p.yaw if follow else 0.0
        diff = (want - self.cam_yaw + 180) % 360 - 180
        self.cam_yaw += diff * min(1.0, dt * (4.0 if p.under_deck else 2.5))
        rx_stick = 0.0 if self.menus_open else self.pad.right_stick()[0]
        self.look_yaw += (rx_stick * 120 - self.look_yaw) * min(1.0, dt * 6)
        view_yaw = self.cam_yaw + self.look_yaw
        y = p.alt
        if mode == 'Chase':
            tgt, rx = (0, y + 3.3 + (1.0 if p.flying else 0), -10.0), 13
        elif mode == 'Far':
            tgt, rx = (0, y + 9, -26), 17
        elif mode == 'Cockpit':
            tgt, rx = (0, y + p.spec.height * 0.8, 0.1), 2
        elif mode == 'Top':
            tgt, rx = (0, y + 70, -42), 55
        else:
            tgt, rx = (6.5, y + 1.7, 3.6), 8
        if mode != 'Side' and abs(view_yaw) > 0.05:
            a = math.radians(view_yaw)
            tx, ty, tz = tgt
            tgt = (tx * math.cos(a) + tz * math.sin(a), ty, -tx * math.sin(a) + tz * math.cos(a))
        cur = camera.position
        if abs(cur[1] - tgt[1]) > 40:
            camera.position = tgt
        else:
            k = min(1.0, dt * 6)
            camera.position = tuple(c + (t - c) * k for c, t in zip(cur, tgt))
        camera.rotation = (rx, -118 + self.look_yaw if mode == 'Side' else view_yaw, 0)
        speed = abs(p.speed)
        camera.fov = 72 + min(26.0, speed / 25.0)
        self.car.visible = mode != 'Cockpit'

    def _update_speed_lines(self, dt, fast):
        p = self.player
        show = abs(p.speed) > 110 or p.express_active
        v = min(abs(p.speed), 900) if not p.express_active else 600
        for e in self.speed_lines:
            if not show:
                if e.enabled:
                    e.enabled = False
                continue
            e.enabled = True
            ox, oy, oz = e._off
            oz -= v * dt * 0.35
            if oz < -20:
                oz += 240
            e._off = (ox, oy, oz)
            ln = min(40.0, 4 + v * 0.04)
            e.position = (ox, p.alt + oy, oz)
            e.scale = (0.05, 0.05, ln)

    def _apply_daynight(self, force=False):
        if not force and not self.daynight.due(self._clock):
            return
        p = self.player
        fog_end = FOG_END + max(0.0, p.alt) * 1.5
        self.daynight.apply(fog_end)
        b = self.daynight.brightness
        w = self.daynight.lights
        self.highway.set_brightness(b)
        self.city_root.setColorScale(b, b, b, 1)
        gs = (0.33 + 0.67 * w, 0.37 + 0.63 * w, 0.42 + 0.58 * w)
        self.glow.setColorScale(*gs, 1)
        self.traffic_view.set_brightness(max(b, 0.45))
        cb = max(b, 0.55)
        self.car.setColorScale(cb, cb, cb, 1)

    # ================================================================ save
    def save(self):
        p = self.player
        save.store({
            'car': p.spec.id, 's': p.s, 'x': p.x, 'alt': p.alt, 'flying': p.flying, 'laps': p.laps,
            'odometer': p.odometer, 'traffic_auto': self.density.auto, 'traffic_manual': self.density.manual,
            'hour': self.daynight.hour, 'cruise': self.autopilot.cruise, 'camera': self.camera_mode,
        })

    # ================================================================ test automation
    def _scripted_setup(self):
        a = self.args
        if not a.scene or self.frame != 2:
            return
        p = self.player
        sc = a.scene
        if sc in ('night', 'citynight'):
            self.daynight.hour = 21.5
            self._apply_daynight(force=True)
        if sc in ('city', 'fly', 'citynight'):
            self.select_car(4)
            p.flying = True
            for t in self.thrusters:
                t.enabled = True
            if sc in ('city', 'citynight'):
                p.teleport(p.s, coords.lane_center_x(47) + 12, CITY_Y + 8)
            else:
                p.teleport(p.s, p.x, 60)
        if sc == 'top':
            self.cam_i = CAMERAS.index('Top')
        if sc.startswith('show'):
            self.select_car(int(sc[-1]))
            self.cam_i = CAMERAS.index('Side')
            self.help.enabled = False
        if sc == 'map':
            self.map.open()
            self.map.search.text = 'mid'
        if sc == 'drive':
            p.speed = 30
        if sc == 'auto':
            self.set_destination(self.directory.search('orbit diner')[0])
        if sc == 'hyper':
            self.set_destination(self.directory.search('halfway around')[0])
        if sc == 'mapall':
            self.map.open()
            self.map.show_all()
            self.map.search.text = 'mars'
        if sc == 'flyover':
            self.select_car(4)
            p.flying = True
            for t in self.thrusters:
                t.enabled = True
            p.teleport(p.s, coords.lane_center_x(47) + 12, 35)
            self.cam_i = CAMERAS.index('Far')
            self.daynight.hour = 20.6
            self._apply_daynight(force=True)
        if sc in ('park', 'popup'):
            self.help.enabled = False
            lots = self.feasible_lots()
            lot = min(lots, key=lambda l: abs(l.center[0] - p.x) + abs(l.center[1] - p.s))
            self.dashboard.open_popup(lot, (0.6, -0.3))
            if sc == 'park':
                self.start_autopark(lot)
        if sc == 'signal':
            self.help.enabled = False
            self.autopilot.enabled = True
            p.speed = 30
            self.signal(1)
        if sc == 'padmenu':
            self.help.enabled = False
            self.input('gamepad back')
            for _ in range(4):
                self.menu.move(1)
            self.menu.adjust(1)
        if sc == 'padmap':
            self.input('gamepad start')
            self.input('gamepad left shoulder')
            self.map.osk.r, self.map.osk.c = 1, 6      # on-screen keyboard: 'U' -> types 'u'
            self.input('gamepad a')
            self.map.osk.r, self.map.osk.c = 3, 5      # 'N'
            self.input('gamepad a')
        if sc in ('cityturn', 'citywall'):
            from .citylayout import CZ, chunk_origin_x, X_ORIGIN, CX
            self.help.enabled = False
            cx = math.floor((p.x - X_ORIGIN) / CX)
            p.teleport(400 - 30, chunk_origin_x(cx), CITY_Y)
            p.speed = 9
            held_keys['w'] = 1
        if sc == 'paddrive':
            self.help.enabled = False
            self.pad.using_pad = True
            held_keys['gamepad right trigger'] = 1.0
            held_keys['gamepad left stick x'] = 0.6
            held_keys['gamepad right stick x'] = -0.7
            self.input('gamepad right shoulder')
        if sc == 'traffic':
            self.density.auto = False
            self.density.manual = 1.0
            self.density.value = 1.0

    def _scripted_capture(self):
        a = self.args
        if not a.shot or self.frame < a.frames:
            return
        from panda3d.core import Filename
        from ursina import application as app_mod
        base = app_mod.base
        base.graphicsEngine.renderFrame()
        base.win.saveScreenshot(Filename.fromOsSpecific(a.shot))
        p = self.player
        print(f'SHOT {a.shot} frame={self.frame} s={p.s:.1f} lane={p.lane} speed={p.kmh:.0f}km/h '
              f'alt={p.alt:.1f} cars={len(self.traffic.cars)} ap={self.ap_status!r} fps={window.fps_counter.text}')
        application.quit()
