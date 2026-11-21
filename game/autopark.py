"""Auto Park: plans a route from wherever the car is to a free space in a city
parking lot and drives it, including the glass lift down from the highway deck
and reversing into the space. Pure Python."""
import math
from dataclasses import dataclass, field

from . import coords
from .citylayout import CX, X_ORIGIN, median_center_x, nearest_ns_street_x
from .config import CITY_Y, DECK_Y, NUM_BANDS

DECK_SPEED = 14.0
STREET_SPEED = 12.0
TURN_SPEED = 5.0
LOT_SPEED = 3.2
REVERSE_SPEED = 1.6
ACCEL = 3.0
DECEL = 2.6
LIFT_TIME = 6.0
STREET_R = 8.0
AISLE_R = 6.0
SPOT_R = 4.6


@dataclass
class Stage:
    kind: str                      # 'drive' or 'lift'
    pts: list = field(default_factory=list)    # [(x, s, speed_cap)]
    direction: int = 1             # +1 forward, -1 reverse
    alt: float = DECK_Y
    lengths: list = field(default_factory=list)
    x: float = 0.0
    s: float = 0.0

    @property
    def total(self):
        return self.lengths[-1] if self.lengths else 0.0


def fillet(waypoints, radius, speed, turn_speed, step=0.6):
    """Dense path through waypoints with rounded corners (quadratic Bezier
    fillets). Returns [(x, s, speed_cap)]."""
    pts = []

    def line(a, b, v):
        n = max(1, int(math.dist(a, b) / step))
        for i in range(n):
            t = i / n
            pts.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, v))

    cur = waypoints[0]
    for i in range(1, len(waypoints) - 1):
        w, nxt = waypoints[i], waypoints[i + 1]
        din = math.dist(cur, w)
        dout = math.dist(w, nxt)
        if din < 1e-6 or dout < 1e-6:
            continue
        r = min(radius, din * 0.95, dout * 0.5)
        t1 = (w[0] + (cur[0] - w[0]) / din * r, w[1] + (cur[1] - w[1]) / din * r)
        t2 = (w[0] + (nxt[0] - w[0]) / dout * r, w[1] + (nxt[1] - w[1]) / dout * r)
        line(cur, t1, speed)
        n = max(4, int(r * 1.6 / step))
        for k in range(n):
            u = k / n
            x = (1 - u) ** 2 * t1[0] + 2 * (1 - u) * u * w[0] + u * u * t2[0]
            s = (1 - u) ** 2 * t1[1] + 2 * (1 - u) * u * w[1] + u * u * t2[1]
            pts.append((x, s, turn_speed))
        cur = t2
    line(cur, waypoints[-1], speed)
    pts.append((waypoints[-1][0], waypoints[-1][1], speed))
    return pts


def _finish(stage):
    total = 0.0
    stage.lengths = [0.0]
    for a, b in zip(stage.pts, stage.pts[1:]):
        total += math.hypot(b[0] - a[0], b[1] - a[1])
        stage.lengths.append(total)
    return stage


class AutoPark:
    def __init__(self):
        self.state = 'idle'        # idle / active / parked
        self.lot = None
        self.spot = None
        self.stages = []
        self.i = 0
        self.d = 0.0
        self.v = 0.0
        self.t = 0.0
        self.status = ''

    @property
    def active(self):
        return self.state == 'active'

    @property
    def stage(self):
        return self.stages[self.i] if self.active and self.i < len(self.stages) else None

    # ------------------------------------------------------------ planning
    def plan(self, car, lot):
        """Build the route. `lot` comes from citylayout.lots_near(car.x, car.s),
        so its s values are unwrapped around car.s. Returns (ok, message)."""
        free = lot.free
        if not free:
            return False, f'{lot.name} is full'
        if car.flying and car.alt > DECK_Y + 2:
            return False, 'Land first, then start Auto Park'
        x0, s0 = car.x, car.s
        stages = []
        on_deck = car.alt > DECK_Y - 1
        if on_deck:
            xm = median_center_x(car.x)
            if round((xm - X_ORIGIN) / CX) >= NUM_BANDS - 1:     # no median after the last band
                xm -= CX
            dx = xm - x0
            run = max(30.0, abs(dx) * 1.4)
            wps = [(x0, s0), (x0, s0 + 10), (xm, s0 + 10 + run), (xm, s0 + 22 + run)]
            stages.append(_finish(Stage('drive', fillet(wps, 10.0, DECK_SPEED, 9.0), 1, DECK_Y)))
            s_c = s0 + 22 + run
            stages.append(Stage('lift', x=xm, s=s_c, alt=CITY_Y))
            xs = xm
        else:
            xs = nearest_ns_street_x(x0)
            if abs(xs - x0) > 0.5:
                run = max(14.0, abs(xs - x0) * 1.4)
                wps = [(x0, s0), (x0, s0 + 4), (xs, s0 + 4 + run), (xs, s0 + 10 + run)]
                stages.append(_finish(Stage('drive', fillet(wps, 6.0, 8.0, TURN_SPEED), 1, CITY_Y)))
                s_c = s0 + 10 + run
            else:
                s_c = s0

        if lot.street_s - s_c < STREET_R + 6:
            return False, f'{lot.name} is behind you. Pick a lot further ahead'
        # choose the free space closest to the entrance
        spot = min(free, key=lambda sp: (sp.s - lot.s0) + abs(sp.aisle_x - xs) * 0.05)
        ax = spot.aisle_x
        pass_s = spot.s + 6.5
        wps = [(xs, s_c), (xs, lot.street_s), (ax, lot.street_s), (ax, pass_s)]
        pts = fillet(wps, STREET_R, STREET_SPEED, TURN_SPEED)
        pts = [(x, s, min(v, LOT_SPEED) if s > lot.s0 - 4 and lot.x0 - 2 < x < lot.x1 + 2 else v)
               for x, s, v in pts]
        stages.append(_finish(Stage('drive', pts, 1, CITY_Y)))
        # reverse into the space, nose ends up facing the aisle
        wps = [(ax, pass_s), (ax, spot.s), (spot.x, spot.s)]
        stages.append(_finish(Stage('drive', fillet(wps, SPOT_R, REVERSE_SPEED, REVERSE_SPEED, 0.3), -1, CITY_Y)))

        self.lot, self.spot = lot, spot
        self.stages = stages
        self.i, self.d, self.v, self.t = 0, 0.0, 0.0, 0.0
        self.state = 'active'
        self.status = 'Auto Park: heading to the glass lift' if on_deck else 'Auto Park: driving to the lot'
        return True, f'Auto Park started: {lot.name}'

    def cancel(self):
        if self.active:
            st = self.stage
            self.state = 'idle'
            self.status = ''
            return st is not None and st.kind == 'lift'
        self.state = 'idle'
        return False

    # ------------------------------------------------------------ driving
    def _sample(self, st, d):
        L = st.lengths
        if d <= 0:
            j = 0
        elif d >= L[-1]:
            j = len(L) - 2
        else:
            lo, hi = 0, len(L) - 1
            while hi - lo > 1:
                mid = (lo + hi) // 2
                if L[mid] <= d:
                    lo = mid
                else:
                    hi = mid
            j = lo
        j = max(0, min(j, len(st.pts) - 2))
        a, b = st.pts[j], st.pts[j + 1]
        seg = max(1e-6, L[j + 1] - L[j])
        u = max(0.0, min(1.0, (d - L[j]) / seg))
        x = a[0] + (b[0] - a[0]) * u
        s = a[1] + (b[1] - a[1]) * u
        heading = math.degrees(math.atan2(b[0] - a[0], b[1] - a[1]))
        cap = min(a[2], b[2])
        return x, s, heading, cap

    def update(self, dt, car):
        """Moves the car along the plan. Returns an event string or None."""
        if not self.active:
            return None
        st = self.stage
        if st is None:
            return self._parked(car)
        if st.kind == 'lift':
            started = self.t == 0.0
            self.t += dt
            u = min(1.0, self.t / LIFT_TIME)
            u = u * u * (3 - 2 * u)
            car.x, car.s = st.x, coords.wrap_s(st.s)
            car.alt = DECK_Y + (st.alt - DECK_Y) * u
            car.speed = 0.0
            car.yaw = 0.0
            self.status = 'Auto Park: glass lift down to the city'
            if self.t >= LIFT_TIME:
                self.i += 1
                self.d = self.v = self.t = 0.0
                self.status = 'Auto Park: driving to the lot'
                return 'landed'
            return 'lift' if started else None

        remaining = st.total - self.d
        x, s, heading, cap = self._sample(st, self.d)
        target = min(cap, math.sqrt(2 * DECEL * max(0.0, remaining - 0.05)))
        if self.v < target:
            self.v = min(target, self.v + ACCEL * dt)
        else:
            self.v = max(target, self.v - DECEL * 2 * dt)
        self.d = min(st.total, self.d + max(self.v, 0.25 if remaining > 0.05 else 0.0) * dt)
        x, s, heading, _ = self._sample(st, self.d)
        car.x, car.s, car.alt = x, coords.wrap_s(s), st.alt
        car.vx = car.vy = 0.0
        if st.direction < 0:
            heading = (heading + 360) % 360 - 180
            self.status = 'Auto Park: reversing into the space'
        elif st.alt < DECK_Y - 1 and self.lot and s > self.lot.s0 - 6:
            self.status = f'Auto Park: entering {self.lot.name}'
        car.yaw = heading
        car.speed = self.v * st.direction
        if remaining <= 0.05:
            self.i += 1
            self.d = self.v = 0.0
            if self.i >= len(self.stages):
                return self._parked(car)
        return None

    def _parked(self, car):
        self.state = 'parked'
        car.speed = 0.0
        if self.spot is not None:
            self.spot.occupied = True
        self.status = ''
        return 'parked'

    def route_points(self, step=4.0):
        """Remaining route as [(x, s)] (unwrapped s) for drawing."""
        out = []
        if not self.active:
            return out
        for k in range(self.i, len(self.stages)):
            st = self.stages[k]
            if st.kind == 'lift':
                out.append((st.x, st.s))
                continue
            d0 = self.d if k == self.i else 0.0
            d = d0
            while d < st.total:
                x, s, _, _ = self._sample(st, d)
                out.append((x, s))
                d += step
            out.append(st.pts[-1][:2])
        return out
