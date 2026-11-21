"""Car specs and player physics. Pure Python (no engine imports)."""
import math
from dataclasses import dataclass, field

from . import citylayout, coords
from .config import (CITY_Y, DECK_THICK, DECK_Y, EXPRESS_LATERAL, GHOST_SPEED,
                     HYPER_SPEED, MAX_ALT)


@dataclass(frozen=True)
class CarSpec:
    id: str
    name: str
    max_kmh: float
    zero_100: float          # seconds
    color: tuple             # body colour (r, g, b) 0..1
    can_fly: bool = False
    length: float = 4.7
    width: float = 1.9
    height: float = 1.45
    blurb: str = ''

    @property
    def max_speed(self) -> float:
        return self.max_kmh / 3.6

    @property
    def accel(self) -> float:
        return 27.78 / self.zero_100


CARS = [
    CarSpec('aero', 'Aero Sedan', 250, 3.1, (0.86, 0.88, 0.92), blurb='Sleek electric sedan'),
    CarSpec('trail', 'Trail SUV', 217, 3.8, (0.12, 0.2, 0.42), length=4.9, width=2.0, height=1.75,
            blurb='Seven seats, falcon-ish doors not included'),
    CarSpec('bolt', 'Bolt GT', 330, 2.0, (0.75, 0.05, 0.08), length=4.5, width=1.95, height=1.25,
            blurb='Tri-motor track car'),
    CarSpec('hauler', 'Cargo Hauler', 160, 6.5, (0.92, 0.92, 0.95), length=9.5, width=2.5, height=3.4,
            blurb='Electric semi cab'),
    CarSpec('volt', 'Volt Roadster', 410, 1.9, (0.85, 0.1, 0.55), can_fly=True, length=4.3, width=1.95,
            height=1.15, blurb='Two seats, cold-gas thrusters. It flies.'),
]
CAR_BY_ID = {c.id: c for c in CARS}


@dataclass
class Controls:
    throttle: float = 0.0       # 0..1
    brake: float = 0.0          # 0..1
    steer: float = 0.0          # -1..1, free lateral steering
    up: float = 0.0             # flight
    down: float = 0.0
    target_speed: float = None  # autopilot: speed to hold (m/s)
    target_x: float = None      # lane-change target (lateral metres)
    express: bool = False       # fast lateral transfer across many lanes
    hyper: bool = False         # allow hyper speed


@dataclass
class PlayerCar:
    spec: CarSpec
    s: float = 0.0
    x: float = 0.0
    alt: float = DECK_Y
    speed: float = 0.0
    vx: float = 0.0
    vy: float = 0.0
    flying: bool = False
    warp: bool = False          # manual hyper speed toggle
    laps: int = 0
    odometer: float = 0.0
    yaw: float = 0.0            # visual yaw in degrees
    express_active: bool = False
    hyper_active: bool = False
    steer_angle: float = 0.0    # front wheel angle (radians) for city driving
    _touching: bool = False     # scraping a curb right now
    events: list = field(default_factory=list)

    # ---- queries -------------------------------------------------------
    @property
    def lane(self) -> int:
        return coords.nearest_lane(self.x)

    @property
    def kmh(self) -> float:
        return self.speed * 3.6

    @property
    def ghost(self) -> bool:
        """True when the car is not interacting with ground traffic."""
        return (abs(self.speed) > GHOST_SPEED or self.express_active or self.hyper_active
                or self.alt > DECK_Y + 4 or self.alt < DECK_Y - 1)

    @property
    def under_deck(self) -> bool:
        return self.alt < DECK_Y - 1

    def ground_and_ceiling(self, x: float, alt: float):
        surface = coords.surface_at_x(x)
        if alt >= DECK_Y - 1:                      # at or above the deck
            if surface == 'road' or (surface == 'glass' and not self.flying):
                return DECK_Y, MAX_ALT
            return CITY_Y, MAX_ALT                 # fly down through glass / off the edge
        ceiling = DECK_Y - DECK_THICK - 1.0
        if surface == 'air' or (surface == 'glass' and self.flying):
            ceiling = MAX_ALT                      # can climb back up here
        return CITY_Y, ceiling

    # ---- commands ------------------------------------------------------
    def teleport(self, s: float, x: float, alt: float = DECK_Y):
        self.s = coords.wrap_s(s)
        self.x = coords.clamp_x(x)
        self.alt = alt
        self.vx = self.vy = 0.0
        self.steer_angle = 0.0

    def toggle_flight(self) -> bool:
        if not self.spec.can_fly:
            return False
        self.flying = not self.flying
        if self.flying:
            self.vy = 4.0
        return True

    # ---- simulation ----------------------------------------------------
    def update(self, dt: float, c: Controls):
        spec = self.spec
        free = self.under_deck            # city level: real steering, the car goes where it points
        top = HYPER_SPEED if (self.warp or c.hyper) else spec.max_speed
        if self.flying:
            top = max(top, spec.max_speed * 1.5)
        if free:
            top = min(top, 70.0 if self.flying else 33.0)     # city speed limit (120 km/h on the ground)
        accel = spec.accel
        self.hyper_active = c.hyper
        if top > spec.max_speed * 1.6:
            accel = max(accel * 1.5, self.speed * 0.9)   # hyper/warp ramps up exponentially
        decel = max(11.0, accel * 1.2, abs(self.speed) * 0.9)

        if c.target_speed is not None:
            tgt = max(-8.0, min(top, c.target_speed))
            if self.speed < tgt:
                self.speed = min(tgt, self.speed + accel * dt)
            else:
                self.speed = max(tgt, self.speed - decel * dt)
        else:
            if c.throttle > 0:
                self.speed += c.throttle * accel * dt
            if c.brake > 0:
                if self.speed > 0.5:
                    self.speed = max(0.0, self.speed - c.brake * decel * dt)
                else:
                    self.speed = max(-10.0, self.speed - c.brake * 4.0 * dt)  # reverse
            if c.throttle == 0 and c.brake == 0:
                drag = 0.6 + abs(self.speed) * 0.004
                if self.speed > 0:
                    self.speed = max(0.0, self.speed - drag * dt)
                elif self.speed < 0:
                    self.speed = min(0.0, self.speed + drag * dt)
            if self.speed > top:
                self.speed = max(top, self.speed - decel * dt)

        # --- lateral ---
        self.express_active = False
        old_s = self.s
        if free:
            self._free_move(dt, c)
        elif c.target_x is not None:
            err = c.target_x - self.x
            if c.express and abs(err) > 8:
                lat_max = min(EXPRESS_LATERAL, abs(err) * 1.8 + 30)
                self.express_active = True
            else:
                lat_max = 3.6 if not self.flying else 12
            want = max(-lat_max, min(lat_max, err * 2.5))
            self.vx = want
            if abs(err) < 0.02:
                self.vx = 0.0
                self.x = c.target_x
        else:
            cap = (30.0 if self.flying else min(9.0, 1.2 + abs(self.speed) * 0.12))
            want = c.steer * cap
            k = min(1.0, dt * 6)
            self.vx += (want - self.vx) * k
        if free:
            new_x = self.x
        else:
            new_x = self.x + self.vx * dt
        if self.flying or self.under_deck:
            new_x = max(-3000.0, min(coords.TOTAL_WIDTH + 3000.0, new_x))
        else:
            new_x = coords.clamp_x(new_x)
            if coords.surface_at_x(new_x) == 'air':
                new_x = coords.clamp_x(self.x)
        self.x = new_x

        # --- vertical ---
        ground, ceiling = self.ground_and_ceiling(self.x, self.alt)
        if self.flying:
            want_vy = (c.up - c.down) * 28.0
            self.vy += (want_vy - self.vy) * min(1.0, dt * 4)
            new_alt = self.alt + self.vy * dt
        else:
            if self.alt > ground + 0.01:
                self.vy = max(self.vy - 9.81 * dt, -14.0)   # gentle auto-land
                new_alt = self.alt + self.vy * dt
            else:
                self.vy = 0.0
                new_alt = ground
        if new_alt < ground:
            new_alt, self.vy = ground, max(0.0, self.vy)
        if new_alt > ceiling:
            new_alt, self.vy = ceiling, min(0.0, self.vy)
        self.alt = new_alt

        # --- along the loop ---
        if not free:
            self.s = coords.wrap_s(self.s + self.speed * dt)
        if self.speed > 0 and self.s < old_s - coords.C / 2:
            self.laps += 1
            self.events.append('lap')
        elif self.speed < 0 and self.s > old_s + coords.C / 2:
            self.laps -= 1
        self.odometer += abs(self.speed) * dt

        # --- visuals ---
        if free:
            pass                          # yaw is the real heading in the city
        elif self.express_active:
            self.yaw = 0.0
        else:
            target_yaw = math.degrees(math.atan2(self.vx, max(abs(self.speed), 2.0)))
            target_yaw = max(-35.0, min(35.0, target_yaw))
            self.yaw += (target_yaw - self.yaw) * min(1.0, dt * 8)

    # ---- city driving --------------------------------------------------
    def _free_move(self, dt, c):
        """Bicycle-model steering: turn the wheels, the car follows its heading.
        Buildings and parks are solid; the car slides along their curbs."""
        spec = self.spec
        wheelbase = spec.length * 0.6
        max_angle = math.radians(38) / (1 + abs(self.speed) / 14)      # less lock at speed
        target = c.steer * max_angle
        rate = math.radians(220) * dt
        self.steer_angle += max(-rate, min(rate, target - self.steer_angle))
        if self.flying:
            yaw_rate = c.steer * math.radians(75) + self.speed / wheelbase * math.tan(self.steer_angle) * 0.3
        else:
            yaw_rate = self.speed / wheelbase * math.tan(self.steer_angle)
        self.yaw = (self.yaw + math.degrees(yaw_rate) * dt + 180) % 360 - 180
        a = math.radians(self.yaw)
        dx = self.speed * math.sin(a) * dt
        ds = self.speed * math.cos(a) * dt
        self.vx = self.speed * math.sin(a)
        on_ground = not self.flying or self.alt < CITY_Y + 2
        if on_ground and (dx or ds) and self._blocked(self.x + dx, self.s + ds, a):
            if not self._blocked(self.x + dx, self.s, a):
                ds = 0.0                       # slide along the curb
            elif not self._blocked(self.x, self.s + ds, a):
                dx = 0.0
            else:
                dx = ds = 0.0
            if not self._touching and abs(self.speed) > 6:
                self.events.append('wall')
            self._touching = True
            if dx or ds:
                # scrape along the curb: a little friction, and ease the nose parallel to it
                self.speed *= max(0.0, 1 - 1.2 * dt)
                axis = (0.0 if abs(self.yaw) < 90 else 180.0) if dx == 0.0 else (90.0 if self.yaw > 0 else -90.0)
                diff = (axis - self.yaw + 180) % 360 - 180
                self.yaw += diff * min(1.0, dt * 3)
            else:
                self.speed *= -0.15                    # head-on: small bounce back
        else:
            self._touching = False
        self.x = max(-3000.0, min(coords.TOTAL_WIDTH + 3000.0, self.x + dx))
        self.s = coords.wrap_s(self.s + ds)

    def _blocked(self, x, s, a):
        hl, hw = self.spec.length / 2, self.spec.width / 2
        ca, sa = math.cos(a), math.sin(a)
        for fl, fw in ((hl, hw), (hl, -hw), (-hl, hw), (-hl, -hw)):
            px = x + sa * fl + ca * fw
            ps = s + ca * fl - sa * fw
            if citylayout.solid_at(px, ps):
                return True
        return False
