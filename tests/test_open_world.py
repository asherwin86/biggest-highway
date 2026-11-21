import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game import coords, ramps
from game.config import CITY_Y, DECK_Y
from game.vehicles import CAR_BY_ID, Controls, PlayerCar

M = ramps.median_index(ramps.nearest_median_x(coords.lane_center_x(500_000)))
MX = ramps.median_x(M)


def car_at(x, s, alt, yaw=0.0, car='aero'):
    p = PlayerCar(CAR_BY_ID[car])
    p.teleport(s, x, alt)
    p.yaw = yaw
    return p


def run(p, ctrl, secs, until=None, dt=1 / 60):
    for _ in range(int(secs / dt)):
        p.update(dt, ctrl)
        if until and until(p):
            return True
    return False


# ---------------------------------------------------------------- ramps
def test_ramp_surfaces_are_flush_and_continuous():
    assert abs(ramps.surface(MX, ramps.ON_START) - CITY_Y) < 1e-6
    assert abs(ramps.surface(MX, ramps.ON_END) - DECK_Y) < 1e-6
    assert abs(ramps.surface(MX, ramps.OFF_START) - DECK_Y) < 1e-6
    assert abs(ramps.surface(MX, ramps.OFF_END) - CITY_Y) < 1e-6
    prev = ramps.surface(MX, ramps.ON_START)
    for i in range(1, 601):
        h = ramps.surface(MX, ramps.ON_START + i)
        assert abs(h - prev) < 0.2           # no steps
        prev = h
    assert ramps.surface(MX + 8, 500) is None    # only inside the ramp lane
    assert ramps.opening(MX, 600) and not ramps.opening(MX, 1100)


def test_exit_for_picks_last_exit_before_destination():
    s0 = ramps.exit_for(9_000, 0)
    assert s0 % ramps.RAMP_PERIOD == ramps.OFF_START
    assert s0 + ramps.RAMP_LEN <= 9_000
    assert ramps.exit_for(700, 0) >= 500             # too close: next one ahead


# ---------------------------------------------------------------- physics
def test_drive_up_an_entrance_ramp_onto_the_deck():
    p = car_at(MX, 200.0, CITY_Y)
    assert p.under_deck
    ok = run(p, Controls(throttle=0.5), 90, until=lambda c: not c.under_deck and c.s > 1000)
    assert ok, (p.s, p.alt)
    assert abs(p.alt - DECK_Y) < 1e-6
    assert abs(p.x - MX) < 1.0                       # in the median, ready to merge


def test_merge_from_the_ramp_onto_the_lanes():
    p = car_at(MX, 950.0, DECK_Y)
    p.speed = 20
    target = coords.lane_center_x(coords.nearest_lane(MX + 14))
    run(p, Controls(throttle=0.3, target_x=target), 6)
    assert coords.surface_at_x(p.x) == 'road' and abs(p.alt - DECK_Y) < 1e-6


def test_drive_down_an_exit_into_the_city():
    p = car_at(MX, 1100.0, DECK_Y)
    p.speed = 20
    ok = run(p, Controls(throttle=0.3), 60, until=lambda c: c.under_deck and abs(c.alt - CITY_Y) < 1e-6)
    assert ok, (p.s, p.alt)
    assert abs(p.x - MX) < 1.5


def test_cannot_slide_sideways_into_an_opening():
    p = car_at(MX - 8, 600.0, DECK_Y)               # on the glass beside an open ramp
    p.speed = 10
    run(p, Controls(throttle=0.2, steer=1.0), 2)
    assert p.x < MX - ramps.HALF_W
    assert abs(p.alt - DECK_Y) < 1e-6


def test_low_end_of_a_ramp_is_a_wall_from_the_street():
    p = car_at(MX + 7.5, 400.0, CITY_Y, yaw=-90)     # on the street beside the ramp, facing it
    run(p, Controls(throttle=1.0), 3)
    assert p.x > MX + ramps.HALF_W
    assert abs(p.alt - CITY_Y) < 1e-6


def test_flying_car_can_still_use_glass():
    p = car_at(MX, 1100.0, 30.0, car='volt')
    p.flying = True
    run(p, Controls(target_alt=CITY_Y + 10), 20)
    assert p.alt < -40                                # straight down through the median


# ---------------------------------------------------------------- navigator
from game.autopilot import Autopilot
from game.destinations import Destination
from game.navigator import Navigator


def nav_for(dest=None):
    ap = Autopilot()
    ap.enabled = True
    ap.set_destination(dest)
    return Navigator(ap)


def sim(nav, car, secs, dt=1 / 20, until=None):
    for _ in range(int(secs / dt)):
        ctrl = nav.step(dt, car, [])
        if ctrl is not None:
            car.update(dt, ctrl)
        if nav.events or (until and until(car)):
            return True
    return False


def test_city_drive_to_a_nearby_city_destination():
    dest = Destination('Corner Shop', 'City', 650.0, coords.nearest_lane(MX + 108), city=True)
    p = car_at(MX + 6.5, 200.0, CITY_Y)
    nav = nav_for(dest)
    assert sim(nav, p, 240)
    assert nav.events[0] == ('arrived', 'Corner Shop')
    assert p.under_deck and math.hypot(p.x - dest.x, coords.delta_s(p.s, dest.s)) < 20


def test_city_u_turn_when_destination_is_behind():
    dest = Destination('Back There', 'City', 250.0, coords.nearest_lane(MX + 30), city=True)
    p = car_at(MX + 6.5, 700.0, CITY_Y)               # facing +s, destination behind
    nav = nav_for(dest)
    assert sim(nav, p, 240)
    # the destination is inside a block 30 m from the street: we stop at the curb
    assert math.hypot(p.x - dest.x, coords.delta_s(p.s, dest.s)) < 40


def test_city_cruise_keeps_driving():
    p = car_at(MX + 6.5, 200.0, CITY_Y)
    nav = nav_for(None)
    sim(nav, p, 40)
    assert coords.delta_s(200.0, p.s) > 300 and p.under_deck


def test_city_to_highway_takes_an_entrance_ramp():
    dest = Destination('Far Away', 'Rest Stop', 30_000.0, 500_000)
    p = car_at(MX + 6.5 + 108, 150.0, CITY_Y)          # on a middle street, not a median one
    nav = nav_for(dest)
    assert sim(nav, p, 400, until=lambda c: not c.under_deck)
    sim(nav, p, 10)
    assert abs(p.alt - DECK_Y) < 1e-6 and not p.under_deck
    assert 'City' not in nav.status


def test_highway_to_city_takes_an_exit():
    dest = Destination('Downtown', 'City', 6_500.0, coords.nearest_lane(MX + 60), city=True)
    p = car_at(coords.lane_center_x(500_000), 1000.0, DECK_Y)
    nav = nav_for(dest)
    went_down = []
    assert sim(nav, p, 900, until=lambda c: went_down.append(c.under_deck) and False)
    assert any(went_down)
    assert nav.events[0] == ('arrived', 'Downtown')
    assert p.under_deck and math.hypot(p.x - dest.x, coords.delta_s(p.s, dest.s)) < 25


def test_fly_to_a_highway_destination_and_land():
    dest = Destination('Lookout', 'Overlook', 4_000.0, 500_200)
    p = car_at(coords.lane_center_x(500_000), 1000.0, 60.0, car='volt')
    p.flying = True
    nav = nav_for(dest)
    assert sim(nav, p, 300)
    assert not p.flying and abs(p.alt - DECK_Y) < 1e-6
    assert math.hypot(p.x - dest.x, coords.delta_s(p.s, dest.s)) < 5


def test_fly_from_the_city_to_a_city_destination():
    dest = Destination('Rooftop Diner', 'City', 3_000.0, coords.nearest_lane(MX + 300), city=True)
    p = car_at(MX + 50, 1000.0, CITY_Y + 10, car='volt')
    p.flying = True
    nav = nav_for(dest)
    assert sim(nav, p, 300)
    assert not p.flying and abs(p.alt - CITY_Y) < 1e-6 and p.under_deck
