"""Self-driving everywhere: city streets, ramps, the highway and the air.

The Navigator picks a mode from where the car is each frame:
  * city (under the deck, on the ground): drives the street grid itself,
    keeping to the right-hand side of the street, and takes ENTRANCE ramps
    up to the highway when the destination needs it;
  * highway (on the deck): the existing lane Autopilot, plus taking an EXIT
    ramp down when the destination is in the city;
  * air (flying): flies a 3D route, through a glass median if needed, and lands.
Pure Python. step() returns Controls for the physics, or None when it has
moved the car itself (city and air routes)."""
import math

from . import coords, ramps
from .autopark import Stage, _finish, fillet, sample_stage
from .citylayout import nearest_ns_street_x
from .config import CITY_Y, DECK_Y, HYPER_SPEED
from .destinations import Destination
from .vehicles import Controls

EW_STEP = 100.0          # east-west streets every 100 m
KEEP_RIGHT = 6.5         # drive this far right of a street's centre line (clear of ramps)
STREET_SPEED = 14.0
TURN_SPEED = 5.5
RAMP_SPEED = 18.0
CITY_DRIVE_LIMIT = 3000.0   # further than this: use the highway
CRUISE_ALT = 150.0
ACCEL, DECEL = 3.0, 3.0


def _ew(s):
    return round(s / EW_STEP) * EW_STEP


class Navigator:
    def __init__(self, autopilot):
        self.ap = autopilot
        self.status = ''
        self.plan_lane = None
        self.events = []
        self._route = None       # city route: Stage
        self._d = 0.0
        self._v = 0.0
        self._key = None
        self._end_speed = 0.0
        self._air = None         # air route: list of (x, s, alt) with s unwrapped
        self._air_key = None
        self._exit_key = None
        self._exit_pick = None

    def reset(self):
        self._route = self._air = None
        self._key = self._air_key = self._exit_key = None
        self._exit_pick = None
        self._v = 0.0
        self.status = ''

    # ================================================================ entry
    def step(self, dt, car, traffic_cars):
        dest = self.ap.destination
        if dest is not None and dest.space:
            dest = None
        if car.flying:
            self._route = None
            return self._air_step(dt, car, dest)
        self._air = None
        if car.under_deck:
            return self._city_step(dt, car, dest)
        self._route = None
        return self._highway_step(dt, car, dest, traffic_cars)

    def _arrive(self, car, name):
        self.events.append(('arrived', name))
        self.ap.set_destination(None)
        self.reset()
        car.speed = 0.0

    # ================================================================ highway
    def _highway_step(self, dt, car, dest, traffic_cars):
        if dest is not None and dest.city:
            return self._exit_step(dt, car, dest, traffic_cars)
        self._exit_key = None
        plan = self.ap.plan(dt, car, traffic_cars)
        self.status = plan.status
        self.plan_lane = plan.path_lane
        if plan.arrived:
            name = dest.name if dest else ''
            self._arrive(car, name)
        return plan.controls

    def _exit_step(self, dt, car, dest, traffic_cars):
        """Head for the EXIT ramp nearest the city destination and take it."""
        # pick an exit once and stick to it until we take it or pass it
        if (self._exit_pick is None or self._exit_pick[0] != dest.name
                or coords.delta_s(car.s, coords.wrap_s(self._exit_pick[1])) < -20):
            ahead = coords.delta_s(car.s, dest.s)
            s_dest = car.s + max(0.0, ahead)
            self._exit_pick = (dest.name, coords.wrap_s(ramps.exit_for(s_dest, car.s, 500.0)))
        s_exit = car.s + coords.delta_s(car.s, self._exit_pick[1])
        xm = ramps.nearest_median_x(dest.x)
        on_glass = abs(car.x - xm) < 10.0
        near_lane = coords.lane_center_x(coords.nearest_lane(xm - 14 if car.x < xm else xm + 14))
        fwd = s_exit - car.s
        if (fwd < 350 and abs(car.x - near_lane) < 9) or (on_glass and fwd < 600):
            self.status = 'Taking the EXIT to the city'
            self.plan_lane = None
            return Controls(target_speed=20.0, target_x=xm)
        key = (round(s_exit), round(near_lane, 1))
        if key != self._exit_key:
            self._exit_key = key
            # aim past the exit so the lane autopilot doesn't slow down before it
            self._exit_dest = Destination('EXIT', 'Exit', coords.wrap_s(s_exit + 500),
                                          coords.nearest_lane(near_lane))
            self.ap.target_lane = None
        real = self.ap.destination
        self.ap.destination = self._exit_dest
        try:
            plan = self.ap.plan(dt, car, traffic_cars)
        finally:
            self.ap.destination = real                    # the real destination stays shown
        self.status = f'{plan.status} to the EXIT, {coords.fmt_dist(fwd)}'
        self.plan_lane = plan.path_lane
        return plan.controls

    # ================================================================ city
    def _city_goal(self, car, dest):
        if dest is None:
            return ('cruise',)
        dist = math.hypot(coords.delta_s(car.s, dest.s), dest.x - car.x)
        if dest.city and dist <= CITY_DRIVE_LIMIT:
            return ('point', dest.x, car.s + coords.delta_s(car.s, dest.s))
        return ('onramp',)

    def _city_step(self, dt, car, dest):
        goal = self._city_goal(car, dest)
        key = (goal[0], dest.name if dest else None)
        if self._route is None or key != self._key:
            self._key = key
            self._plan_city(car, goal)
            self._d = 0.0
        st = self._route
        remaining = st.total - self._d
        if goal[0] == 'cruise' and remaining < 150:
            self._plan_city(car, goal)
            self._d = 0.0
            st = self._route
            remaining = st.total
        x, s, heading, cap = sample_stage(st, self._d)
        target = min(cap, math.sqrt(self._end_speed ** 2 + 2 * DECEL * max(0.0, remaining - 0.05)))
        if self._v < target:
            self._v = min(target, self._v + ACCEL * dt)
        else:
            self._v = max(target, self._v - DECEL * 2 * dt)
        step = max(self._v, 0.4 if remaining > 0.05 else 0.0) * dt
        self._d = min(st.total, self._d + step)
        x, s, heading, _ = sample_stage(st, self._d)
        rs = ramps.surface(x, s)
        car.alt = rs if rs is not None and abs(rs - car.alt) < 2.5 else CITY_Y
        car.x, car.s = x, coords.wrap_s(s)
        car.yaw = heading
        car.speed = self._v
        car.vx = car.vy = 0.0
        car.odometer += step
        self.plan_lane = None
        if rs is not None and car.alt > CITY_Y + 1:
            self.status = 'Taking the ENTRANCE ramp up' if ramps.ramp_kind(s) == 'on' else 'Coming down the EXIT ramp'
        elif goal[0] == 'onramp':
            self.status = 'City: heading for an ENTRANCE ramp'
        elif goal[0] == 'point':
            self.status = f'City: driving to {dest.name}'
        else:
            self.status = 'City: cruising'
        if self._d >= st.total - 0.05:
            if goal[0] == 'point':
                self._arrive(car, dest.name)
            else:
                self._route = None          # at the top of the ramp: highway takes over next frame
        return None

    def _plan_city(self, car, goal):
        """Street-grid route with rounded corners, keeping right."""
        x0, s0 = car.x, car.s
        a = math.radians(car.yaw)
        h = (math.sin(a), math.cos(a))
        pts = []                                   # (x, s, keep_centre)
        # finish the ramp we are on first
        rs = ramps.surface(x0, s0)
        if rs is not None and car.alt > CITY_Y + 0.5:
            base = math.floor(s0 / ramps.RAMP_PERIOD) * ramps.RAMP_PERIOD
            end = base + (ramps.OFF_END if ramps.ramp_kind(s0) == 'off' else ramps.ON_END)
            if ramps.ramp_kind(s0) == 'on':          # already climbing: go to the top
                self._finish_route(car, [(car.x, car.s, True), (x0, end, True)], end_speed=RAMP_SPEED)
                return
            pts.append((x0, end + 12, True))
            x0, s0, h = x0, end + 12, (0.0, 1.0)
        # start street
        ns_x = nearest_ns_street_x(x0)
        ew_s = _ew(s0)
        on_ns, on_ew = abs(x0 - ns_x) <= 8.5, abs(s0 - ew_s) <= 8.5
        if not on_ns and not on_ew:
            if abs(x0 - ns_x) <= abs(s0 - ew_s):
                x0, on_ns = ns_x, True
            else:
                s0, on_ew = ew_s, True
            pts.append((x0, s0, False))
        if on_ns and on_ew:
            orient = 'ns' if abs(h[1]) >= abs(h[0]) else 'ew'
        else:
            orient = 'ns' if on_ns else 'ew'
        X, S = (ns_x if orient == 'ns' else x0), (ew_s if orient == 'ew' else s0)

        end_speed = 0.0
        tail = []
        if goal[0] == 'cruise':
            if orient == 'ns':
                sgn = 1 if h[1] >= 0 else -1
                gx, gs, g_or = X, s0 + sgn * 600, 'ns'
            else:
                sgn = 1 if h[0] >= 0 else -1
                gx, gs, g_or = x0 + sgn * 600, S, 'ew'
            end_speed = STREET_SPEED
        elif goal[0] == 'point':
            gx0, gs0 = goal[1], goal[2]
            gns, gew = nearest_ns_street_x(gx0), _ew(gs0)
            if abs(gx0 - gns) <= abs(gs0 - gew):
                gx, gs, g_or = gns, gs0, 'ns'
            else:
                gx, gs, g_or = gx0, gew, 'ew'
        else:                                       # ENTRANCE ramp on the nearest median street
            xm = ramps.nearest_median_x(x0)
            s_on = ramps.next_start(s0, 'on', 60.0)
            if orient == 'ns' and abs(X - xm) > 1:
                while math.floor((s_on - 40) / EW_STEP) * EW_STEP < s0 + 20:
                    s_on += ramps.RAMP_PERIOD
            gx, gs, g_or = xm, s_on - 30, 'ns'
            tail = [(xm, s_on, True), (xm, s_on + ramps.RAMP_LEN, True)]
            end_speed = RAMP_SPEED

        wps = []
        if orient == 'ns':
            if g_or == 'ns' and abs(gx - X) < 1:
                pass
            elif g_or == 'ns':
                s_t = (math.floor((gs - 10) / EW_STEP) * EW_STEP) if goal[0] == 'onramp' else _ew(gs)
                wps += [(X, s_t), (gx, s_t)]
            else:
                wps += [(X, gs)]
        else:
            if g_or == 'ew' and abs(gs - S) < 1:
                pass
            elif g_or == 'ew':
                x_t = nearest_ns_street_x(gx)
                wps += [(x_t, S), (x_t, gs)]
            else:
                wps += [(gx, S)]
        wps.append((gx, gs))
        route = [(car.x, car.s, True)] + pts + [(wx, ws, False) for wx, ws in wps] + tail
        route = _dedupe(route)
        # turning back first? do a U-turn to the left
        if len(route) > 1:
            d1 = _unit(route[1][0] - route[0][0], route[1][1] - route[0][1])
            if d1[0] * h[0] + d1[1] * h[1] < -0.2:
                route = _u_turn(route[0], h) + route[1:]
        self._finish_route(car, route, end_speed)

    def _finish_route(self, car, route, end_speed):
        pts2 = _keep_right(route, KEEP_RIGHT)
        dense = fillet(pts2, 8.0, STREET_SPEED, TURN_SPEED)
        dense = [(x, s, RAMP_SPEED if (ramps.surface(x, s) is not None and v >= STREET_SPEED) else v)
                 for x, s, v in dense]
        self._route = _finish(Stage('drive', dense, 1, CITY_Y))
        self._end_speed = end_speed

    # ================================================================ air
    def _air_step(self, dt, car, dest):
        if dest is None:
            self._air = None
            self.status = 'Air: cruising'
            self.plan_lane = None
            alt = max(car.alt, 40.0) if not car.under_deck else car.alt
            return Controls(target_speed=min(car.spec.max_speed * 1.5, self.ap.cruise * 1.6),
                            target_x=car.x, target_alt=alt)
        key = dest.name
        if self._air is None or key != self._air_key:
            self._air_key = key
            self._air = self._plan_air(car, dest)
        pts = self._air
        tx, ts, ta = pts[0]
        dx, ds, da = tx - car.x, coords.delta_s(car.s, coords.wrap_s(ts)), ta - car.alt
        dist = math.sqrt(dx * dx + ds * ds + da * da)
        horiz = math.hypot(dx, ds)
        total = dist + sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
        if horiz > 1.0:
            top = HYPER_SPEED if total > 30_000 else car.spec.max_speed * 1.5
            want = min(top, max(25.0, total * 0.45))
        else:
            want = 20.0
        if self._v < want:
            self._v = min(want, self._v + max(ACCEL * 3, self._v * 0.9) * dt)
        else:
            self._v = max(want, self._v - max(DECEL * 3, self._v * 0.9) * dt)
        step = min(dist, self._v * dt)
        if dist > 1e-6:
            car.x += dx / dist * step
            car.s = coords.wrap_s(car.s + ds / dist * step)
            car.alt += da / dist * step
        if horiz > 1.0:
            car.yaw = math.degrees(math.atan2(dx, ds))
        car.speed = self._v if horiz > 1.0 else 0.0
        car.vx = car.vy = 0.0
        car.odometer += step
        car.hyper_active = self._v > 300
        self.plan_lane = None
        self.status = ('Air: hyper flight' if self._v > 300 else
                       'Air: landing' if len(pts) <= 2 and abs(da) > 2 and horiz < 2 else f'Air: flying to {dest.name}')
        if dist - step < 0.5:
            car.x, car.s, car.alt = tx, coords.wrap_s(ts), ta      # snap onto the waypoint
            pts.pop(0)
            if not pts:
                car.flying = False
                car.hyper_active = False
                self._arrive(car, dest.name)
        return None

    def _plan_air(self, car, dest):
        s_d = car.s + coords.delta_s(car.s, dest.s)
        pts = []
        x, s, alt = car.x, car.s, car.alt
        if car.under_deck:                         # out through the nearest glass median
            xm = ramps.nearest_median_x(x)
            pts += [(xm, s, alt), (xm, s, 40.0)]
            x = xm
        cruise = CRUISE_ALT if math.hypot(dest.x - x, s_d - s) > 800 else 60.0
        pts.append((x, s, max(cruise, alt if not car.under_deck else cruise)))
        if dest.city:
            gx, gs = _street_point(dest.x, s_d)
            xm = ramps.nearest_median_x(gx)
            pts += [(xm, gs, cruise), (xm, gs, -40.0), (gx, gs, -40.0), (gx, gs, CITY_Y)]
        else:
            pts += [(dest.x, s_d, cruise), (dest.x, s_d, DECK_Y)]
        return _dedupe3(pts)


# ==================================================================== helpers
def _unit(dx, ds):
    n = math.hypot(dx, ds) or 1.0
    return dx / n, ds / n


def _dedupe(route):
    out = [route[0]]
    for p in route[1:]:
        if math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 0.5:
            out.append(p)
    return out


def _dedupe3(pts):
    out = [pts[0]]
    for p in pts[1:]:
        if math.dist(p, out[-1]) > 0.5:
            out.append(p)
    return out


def _keep_right(route, off):
    """Shift street waypoints to the right-hand side of travel. Points flagged
    keep_centre (the car itself, ramps) stay on the centre line."""
    out = []
    n = len(route)
    for i, (x, s, centre) in enumerate(route):
        if centre:
            out.append((x, s))
            continue
        rights = []
        if i > 0:
            d = _unit(x - route[i - 1][0], s - route[i - 1][1])
            rights.append((d[1], -d[0]))
        if i < n - 1:
            d = _unit(route[i + 1][0] - x, route[i + 1][1] - s)
            rights.append((d[1], -d[0]))
        if len(rights) == 2:
            r1, r2 = rights
            k = 1 + r1[0] * r2[0] + r1[1] * r2[1]
            r = ((r1[0] + r2[0]) / k, (r1[1] + r2[1]) / k) if k > 0.3 else r1
        else:
            r = rights[0]
        out.append((x + r[0] * off, s + r[1] * off))
    return out


def _u_turn(start, h, r=KEEP_RIGHT):
    """Semicircle to the left, ending on the other side of the street going back."""
    x, s = start[0], start[1]
    left = (-h[1], h[0])
    cx, cs = x + left[0] * r, s + left[1] * r
    pts = []
    for i in range(0, 13):
        t = math.pi * i / 12
        # rotate from -left to +left around the centre, through the forward direction
        px = cx - left[0] * r * math.cos(t) + h[0] * r * math.sin(t)
        ps = cs - left[1] * r * math.cos(t) + h[1] * r * math.sin(t)
        pts.append((px, ps, True))
    return pts


def _street_point(x, s):
    gns, gew = nearest_ns_street_x(x), _ew(s)
    if abs(x - gns) <= abs(s - gew):
        return gns + KEEP_RIGHT, s
    return x, gew - KEEP_RIGHT
