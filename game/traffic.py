"""Traffic simulation and the auto-adapt density controller. Pure Python."""
import math
import random
from dataclasses import dataclass

from . import coords
from .config import (BAND_LANES, LANE_W, MAX_TRAFFIC, TRAFFIC_AHEAD,
                     TRAFFIC_BEHIND, TRAFFIC_LANES_EACH_SIDE)

CAR_LEN = 4.8

EVENTS = [
    ('Rush hour wave', +0.35, (25, 50)),
    ('Stadium lets out', +0.45, (20, 40)),
    ('Holiday road trip', +0.30, (30, 60)),
    ('Traffic jam ahead', +0.55, (15, 30)),
    ('Open road', -0.30, (25, 50)),
    ('Everyone is at lunch', -0.20, (20, 40)),
    ('Midnight calm', -0.35, (20, 45)),
]


class TrafficDensity:
    """Density 0..1. In auto mode it follows a daily rush-hour curve plus
    random events, so traffic keeps going up and dropping on its own."""

    MIN, MAX = 0.03, 1.0

    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.auto = True
        self.manual = 0.45
        self.value = 0.4
        self.event = None          # (name, delta)
        self.event_left = 0.0
        self.next_event = self.rng.uniform(20, 45)

    @staticmethod
    def daily_curve(hour: float) -> float:
        h = hour % 24
        morning = 0.55 * math.exp(-((h - 8.0) / 1.5) ** 2)
        evening = 0.60 * math.exp(-((h - 17.5) / 1.8) ** 2)
        night = 0.18 if (h < 5 or h > 22) else 0.0
        return 0.28 + morning + evening - night

    def target(self, hour: float) -> float:
        if not self.auto:
            return self.manual
        t = self.daily_curve(hour)
        if self.event:
            t += self.event[1]
        return max(self.MIN, min(self.MAX, t))

    def update(self, dt: float, hour: float) -> float:
        if self.auto:
            if self.event:
                self.event_left -= dt
                if self.event_left <= 0:
                    self.event = None
                    self.next_event = self.rng.uniform(25, 70)
            else:
                self.next_event -= dt
                if self.next_event <= 0:
                    name, delta, (lo, hi) = self.rng.choice(EVENTS)
                    self.event = (name, delta)
                    self.event_left = self.rng.uniform(lo, hi)
        rate = 0.08 if self.auto else 0.6
        tgt = self.target(hour)
        self.value += (tgt - self.value) * min(1.0, dt * rate)
        self.value = max(self.MIN, min(self.MAX, self.value))
        return self.value

    @property
    def status(self) -> str:
        if not self.auto:
            return 'Manual'
        return self.event[0] if self.event else 'Auto-adapt'


@dataclass
class AICar:
    id: int
    s: float
    x: float
    lane: int
    speed: float
    v0: float
    style: int          # which mesh/colour variant to draw
    rel_s: float = 0.0  # cached distance from the player along the loop


class TrafficSim:
    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.cars: list[AICar] = []
        self._next_id = 0
        self._last_player = None
        self.suspended = False

    def clear(self):
        self.cars.clear()

    def target_count(self, density: float) -> int:
        return int(round(density * MAX_TRAFFIC))

    def _valid_lane(self, lane: int) -> bool:
        return 0 <= lane < coords.LANES

    def _spawn(self, p_s, p_lane, rel_lo, rel_hi):
        for _ in range(6):
            lane = p_lane + self.rng.randint(-TRAFFIC_LANES_EACH_SIDE, TRAFFIC_LANES_EACH_SIDE)
            if not self._valid_lane(lane):
                continue
            rel = self.rng.uniform(rel_lo, rel_hi)
            if any(c.lane == lane and abs(c.rel_s - rel) < 14 for c in self.cars):
                continue
            if lane == p_lane and abs(rel) < 25:
                continue
            v0 = self.rng.uniform(20, 42)
            car = AICar(self._next_id, coords.wrap_s(p_s + rel), coords.lane_center_x(lane),
                        lane, v0 * self.rng.uniform(0.8, 1.0), v0, self.rng.randrange(24), rel)
            self._next_id += 1
            self.cars.append(car)
            return car
        return None

    def update(self, dt, player, density):
        """Advance traffic. `player` needs .s .x .lane .speed .ghost.
        Returns the AICar the player hit this frame, or None."""
        p_s, p_lane = player.s, player.lane
        if self.suspended:
            self.cars.clear()
            self._last_player = None
            return None

        jumped = False
        if self._last_player is not None:
            ls, lx = self._last_player
            if abs(coords.delta_s(ls, p_s)) > 1500 or abs(lx - player.x) > 400:
                jumped = True
        self._last_player = (p_s, player.x)

        for c in self.cars:
            c.rel_s = coords.delta_s(p_s, c.s)
        if jumped:
            self.cars.clear()

        # drop cars that left the window
        keep = []
        for c in self.cars:
            if (-TRAFFIC_BEHIND - 60 < c.rel_s < TRAFFIC_AHEAD + 60
                    and abs(c.lane - p_lane) <= TRAFFIC_LANES_EACH_SIDE + 4):
                keep.append(c)
        self.cars = keep

        target = self.target_count(density)
        if not self.cars and target:
            # fresh start or just teleported: scatter cars over the whole window
            for _ in range(target):
                self._spawn(p_s, p_lane, -TRAFFIC_BEHIND, TRAFFIC_AHEAD)
        else:
            spawned = 0
            while len(self.cars) < target and spawned < 4:
                if self.rng.random() < 0.7:
                    self._spawn(p_s, p_lane, TRAFFIC_AHEAD * 0.7, TRAFFIC_AHEAD)
                else:
                    self._spawn(p_s, p_lane, -TRAFFIC_BEHIND, -TRAFFIC_BEHIND * 0.6)
                spawned += 1
            if len(self.cars) > target + 2:
                far = sorted(self.cars, key=lambda c: -abs(c.rel_s))
                for c in far[:2]:
                    if abs(c.rel_s) > 300:
                        self.cars.remove(c)

        self._drive(dt, player)
        return self._collision(player)

    def lanes_bucket(self):
        lanes = {}
        for c in self.cars:
            lanes.setdefault(c.lane, []).append(c)
        for lst in lanes.values():
            lst.sort(key=lambda c: c.rel_s)
        return lanes

    def lane_free(self, lane, rel_s, behind=12.0, ahead=25.0, exclude=None):
        for c in self.cars:
            if c is exclude or c.lane != lane:
                continue
            if -behind < c.rel_s - rel_s < ahead:
                return False
        return True

    def _drive(self, dt, player):
        lanes = self.lanes_bucket()
        p_lane = player.lane
        player_blocks = not player.ghost
        for lane, lst in lanes.items():
            for i, c in enumerate(lst):
                lead_rel, lead_v = None, None
                if i + 1 < len(lst):
                    lead_rel, lead_v = lst[i + 1].rel_s, lst[i + 1].speed
                if player_blocks and lane == p_lane and c.rel_s < 0:
                    if lead_rel is None or lead_rel > 0:
                        lead_rel, lead_v = 0.0, player.speed
                # simplified Intelligent Driver Model
                a_max, b = 2.2, 4.0
                v = c.speed
                acc = a_max * (1 - (v / c.v0) ** 4)
                if lead_rel is not None:
                    gap = max(0.5, lead_rel - c.rel_s - CAR_LEN)
                    s_star = 2.5 + v * 1.4 + v * (v - lead_v) / (2 * math.sqrt(a_max * b))
                    acc -= a_max * (max(0.0, s_star) / gap) ** 2
                acc = max(-9.0, acc)
                c.speed = max(0.0, v + acc * dt)

                # lane changes when stuck behind slower traffic
                if c.speed < 0.75 * c.v0 and self.rng.random() < 0.6 * dt:
                    band = c.lane // BAND_LANES
                    for d in self.rng.sample([-1, 1], 2):
                        nl = c.lane + d
                        if nl // BAND_LANES != band or not self._valid_lane(nl):
                            continue
                        if nl == p_lane and player_blocks and -12 < c.rel_s < 25:
                            continue
                        if self.lane_free(nl, c.rel_s, exclude=c):
                            c.lane = nl
                            break

        for c in self.cars:
            tx = coords.lane_center_x(c.lane)
            dx = tx - c.x
            step = 3.2 * dt
            c.x = tx if abs(dx) <= step else c.x + math.copysign(step, dx)
            c.s = coords.wrap_s(c.s + c.speed * dt)
            c.rel_s = coords.delta_s(player.s, c.s)

    def _collision(self, player):
        if player.ghost:
            return None
        hw = player.spec.width / 2 + 0.9
        hl = player.spec.length / 2 + CAR_LEN / 2 - 0.3
        for c in self.cars:
            if abs(c.x - player.x) < hw and abs(c.rel_s) < hl:
                return c
        return None

    def nearby(self, player, ahead=140.0, behind=40.0, lanes=3):
        p_lane = player.lane
        return [c for c in self.cars
                if -behind < c.rel_s < ahead and abs(c.lane - p_lane) <= lanes]
