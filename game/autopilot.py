"""Full self-driving. Pure logic: turns the car state + nearby traffic into
Controls each frame."""
import math
from dataclasses import dataclass

from . import coords
from .config import BAND_LANES, HYPER_SPEED
from .vehicles import Controls

EXPRESS_LANES = 40        # further than this many lanes -> lane express
HYPER_DIST = 30_000.0     # further than this (m) -> hyper mode
ARRIVE_RADIUS = 25.0


@dataclass
class Plan:
    controls: Controls
    status: str
    arrived: bool = False
    leader_gap: float = None
    path_lane: int = None


class Autopilot:
    def __init__(self):
        self.enabled = False
        self.cruise = 33.0            # m/s (~120 km/h), editable from the screen
        self.destination = None       # destinations.Destination
        self.target_lane = None
        self._change_cooldown = 0.0
        self.signal = 0               # lane change the driver asked for with the turn signal
        self.signal_t = 0.0
        self.indicator = 0            # which blinker is on right now (-1 left, +1 right)

    def request_lane_change(self, direction):
        """Driver taps the turn signal: change one lane that way when it is safe."""
        if self.signal == direction:
            self.signal = 0           # tapping the same way again cancels
        else:
            self.signal = direction
            self.signal_t = 12.0

    def set_destination(self, dest):
        self.destination = dest
        self.target_lane = None

    def plan(self, dt, car, traffic_cars) -> Plan:
        """car: vehicles.PlayerCar; traffic_cars: list of traffic.AICar (with rel_s)."""
        p = self._plan(dt, car, traffic_cars)
        diff = coords.lane_center_x(self.target_lane) - car.x if self.target_lane is not None else 0
        if self.signal:
            self.indicator = self.signal
        elif abs(diff) > 0.3 and not p.controls.express:
            self.indicator = 1 if diff > 0 else -1
            if p.status in ('Lane keeping', 'Following'):
                p.status = 'Changing lanes'
        else:
            self.indicator = 0
        return p

    def _plan(self, dt, car, traffic_cars) -> Plan:
        self._change_cooldown = max(0.0, self._change_cooldown - dt)
        lane = car.lane
        if self.target_lane is None or abs(coords.lane_center_x(self.target_lane) - car.x) > 400:
            self.target_lane = lane
        cruise = min(self.cruise, car.spec.max_speed)
        ctrl = Controls(target_speed=cruise, target_x=coords.lane_center_x(self.target_lane))
        status = 'Lane keeping'

        # --- route to destination -------------------------------------
        dest = self.destination
        if dest is not None:
            d_signed = coords.delta_s(car.s, dest.s)
            fwd = coords.forward_s(car.s, dest.s)
            lane_diff = dest.lane - lane
            if abs(lane_diff) <= 1 and -80 < d_signed < ARRIVE_RADIUS:
                self.target_lane = dest.lane
                ctrl.target_x = coords.lane_center_x(dest.lane)
                ctrl.target_speed = 0.0
                if abs(car.speed) < 1.0:
                    return Plan(ctrl, 'Arrived', arrived=True)
                return Plan(ctrl, 'Arriving', path_lane=dest.lane)
            if abs(lane_diff) > EXPRESS_LANES:
                self.target_lane = dest.lane
                ctrl.target_x = coords.lane_center_x(dest.lane)
                ctrl.express = True
                ctrl.target_speed = min(cruise, 25.0)
                return Plan(ctrl, 'Lane Express', path_lane=dest.lane)
            if fwd > HYPER_DIST:
                self.target_lane = dest.lane
                ctrl.target_x = coords.lane_center_x(dest.lane)
                ctrl.express = True
                ctrl.hyper = True
                ctrl.target_speed = min(HYPER_SPEED, max(cruise, (fwd - 15_000) * 0.6))
                return Plan(ctrl, 'Hyper mode', path_lane=dest.lane)
            # brake smoothly to stop at the destination
            stop_dist = max(0.0, fwd - 6)
            ctrl.target_speed = min(cruise, math.sqrt(2 * 3.0 * stop_dist) + 0.5)
            if fwd > 6_000:
                ctrl.target_speed = car.spec.max_speed
            status = 'Navigating'
            if lane_diff != 0 and self._lane_change_done(car):
                step = 1 if lane_diff > 0 else -1
                if self._safe(car, lane + step, traffic_cars):
                    self.target_lane = lane + step
                    self._change_cooldown = 0.6
                    status = 'Changing lanes'
                elif fwd < 400:
                    ctrl.target_speed = min(ctrl.target_speed, 12.0)

        # --- driver-requested lane change (turn signal) ---------------
        if self.signal:
            self.signal_t -= dt
            nl = lane + self.signal
            if self.signal_t <= 0 or nl < 0 or nl >= coords.LANES:
                self.signal = 0
                status = 'Lane change cancelled'
            elif self._lane_change_done(car):
                if self._safe(car, nl, traffic_cars):
                    self.target_lane = nl
                    self._change_cooldown = 1.5
                    self.signal = 0
                    status = 'Changing lanes (signal)'
                else:
                    status = 'Waiting for a gap to change lanes'

        # --- follow the car ahead -------------------------------------
        follow_lane = coords.nearest_lane(ctrl.target_x)
        leader = self._leader(traffic_cars, follow_lane)
        gap = None
        if leader is not None:
            gap = leader.rel_s - car.spec.length / 2 - 2.4
            desired = 6.0 + max(0.0, car.speed) * 2.0
            if gap < desired:
                v = max(0.0, leader.speed + (gap - desired) * 0.45)
                if gap < 4:
                    v = 0.0
                if v < ctrl.target_speed:
                    ctrl.target_speed = v
                    if status == 'Lane keeping':
                        status = 'Following'

            # --- overtake slow traffic (free driving only) ---
            if (dest is None and not self.signal and leader.speed < cruise * 0.85 and gap < 90
                    and self._lane_change_done(car)):
                best = None
                for d in (-1, 1):
                    nl = lane + d
                    if nl < 0 or nl >= coords.LANES or nl // BAND_LANES != lane // BAND_LANES:
                        continue
                    if not self._safe(car, nl, traffic_cars):
                        continue
                    nl_leader = self._leader(traffic_cars, nl)
                    room = 1e9 if nl_leader is None else nl_leader.rel_s
                    v = cruise if nl_leader is None else nl_leader.speed
                    score = v + min(room, 200) * 0.05
                    if score > leader.speed + 2 and (best is None or score > best[0]):
                        best = (score, nl)
                if best:
                    self.target_lane = best[1]
                    self._change_cooldown = 2.5
                    status = 'Changing lanes'

        ctrl.target_x = coords.lane_center_x(self.target_lane)
        return Plan(ctrl, status, leader_gap=gap, path_lane=self.target_lane)

    # ---- helpers ------------------------------------------------------
    def _lane_change_done(self, car):
        return (self._change_cooldown <= 0
                and abs(coords.lane_center_x(self.target_lane) - car.x) < 0.3)

    @staticmethod
    def _leader(cars, lane, horizon=160.0):
        best = None
        for c in cars:
            if c.lane == lane and 0 < c.rel_s < horizon:
                if best is None or c.rel_s < best.rel_s:
                    best = c
        return best

    @staticmethod
    def _safe(car, lane, cars):
        if lane < 0 or lane >= coords.LANES:
            return False
        for c in cars:
            if c.lane != lane:
                continue
            if -10 - max(0.0, c.speed - car.speed) * 1.5 < c.rel_s < 14 + max(0.0, car.speed - c.speed) * 1.5:
                return False
        return True
