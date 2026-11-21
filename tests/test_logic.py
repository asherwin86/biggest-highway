import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game import coords
from game.autopilot import Autopilot
from game.config import EARTH_LOOP_M, LANES
from game.destinations import Destination, Directory
from game.traffic import AICar, TrafficDensity, TrafficSim
from game.vehicles import CAR_BY_ID, Controls, PlayerCar


def make_car(lane=500_000, s=1000.0, car='aero'):
    p = PlayerCar(CAR_BY_ID[car])
    p.teleport(s, coords.lane_center_x(lane))
    return p


def test_loop_wraps_back_to_start():
    p = make_car(s=EARTH_LOOP_M - 50)
    p.speed = 100
    p.update(1.0, Controls(target_speed=100))
    assert 0 <= p.s < 100
    assert p.laps == 1


def test_delta_s_wraps():
    assert coords.delta_s(EARTH_LOOP_M - 10, 10) == 20
    assert coords.delta_s(10, EARTH_LOOP_M - 10) == -20


def test_lane_math_round_trip_and_clamp():
    for lane in (0, 1, 47, 48, 499_999, LANES - 1):
        assert coords.lane_at_x(coords.lane_center_x(lane)) == lane
    assert coords.clamp_lane(-5) == 0
    assert coords.clamp_lane(LANES + 5) == LANES - 1
    gap_x = coords.lane_center_x(47) + 10        # inside the glass median
    assert coords.surface_at_x(gap_x) == 'glass'
    assert coords.nearest_lane(gap_x) in (47, 48)


def test_car_cannot_drive_off_the_edge():
    p = make_car(lane=0)
    p.update(1.0, Controls(steer=-1))
    for _ in range(100):
        p.update(0.1, Controls(steer=-1))
    assert p.x >= coords.LANE_W / 2
    assert p.lane == 0


def test_flyer_can_drop_through_glass_but_not_road():
    p = make_car(lane=47, car='volt')
    p.toggle_flight()
    for _ in range(50):
        p.update(0.1, Controls(down=1))
    assert p.alt >= -1        # solid road under lane 47
    p.x = coords.lane_center_x(47) + 14   # over the glass median
    for _ in range(80):
        p.update(0.1, Controls(down=1, target_x=p.x))
    assert p.alt < -30         # fell into the city


def test_traffic_density_stays_in_bounds():
    d = TrafficDensity(seed=1)
    for i in range(20000):
        v = d.update(0.1, (i * 0.01) % 24)
        assert TrafficDensity.MIN <= v <= TrafficDensity.MAX
    d.auto = False
    d.manual = 0.9
    for _ in range(200):
        d.update(0.1, 12)
    assert abs(d.value - 0.9) < 0.05


def test_traffic_fills_to_target():
    sim = TrafficSim(seed=2)
    p = make_car()
    for _ in range(60):
        sim.update(0.1, p, 0.5)
    assert abs(len(sim.cars) - sim.target_count(0.5)) <= 6


def ai(lane, rel, speed, player):
    c = AICar(0, coords.wrap_s(player.s + rel), coords.lane_center_x(lane), lane, speed, speed, 0)
    c.rel_s = rel
    return c


def test_autopilot_brakes_for_slow_car_ahead():
    p = make_car()
    p.speed = 30
    ap = Autopilot()
    # block both neighbours so it can't overtake
    cars = [ai(p.lane, 20, 5, p), ai(p.lane - 1, 0, 30, p), ai(p.lane + 1, 0, 30, p)]
    plan = ap.plan(0.1, p, cars)
    assert plan.controls.target_speed < 10


def test_autopilot_picks_free_lane_to_overtake():
    p = make_car(lane=500_000 - 500_000 % 48 + 10)
    p.speed = 30
    ap = Autopilot()
    cars = [ai(p.lane, 30, 10, p), ai(p.lane - 1, 0, 30, p)]   # left blocked, right free
    plan = ap.plan(0.1, p, cars)
    assert ap.target_lane == p.lane + 1
    assert plan.status == 'Changing lanes'


def test_autopilot_routes_far_destinations():
    p = make_car()
    ap = Autopilot()
    ap.set_destination(Destination('Far', 'x', 5_000_000, p.lane))
    assert ap.plan(0.1, p, []).status == 'Hyper mode'
    ap.set_destination(Destination('Wide', 'x', p.s + 100, p.lane + 10_000))
    plan = ap.plan(0.1, p, [])
    assert plan.status == 'Lane Express' and plan.controls.express


def test_autopilot_reaches_destination():
    p = make_car()
    ap = Autopilot()
    ap.set_destination(Destination('Near', 'x', p.s + 600, p.lane + 2))
    arrived = False
    for _ in range(3000):
        plan = ap.plan(0.05, p, [])
        p.update(0.05, plan.controls)
        if plan.arrived:
            arrived = True
            break
    assert arrived
    assert abs(coords.delta_s(p.s, p.s + 0)) == 0
    assert p.lane == 500_002


def test_search_finds_destinations():
    d = Directory()
    assert d.search('midnight')[0].name == 'Midnight City'
    assert d.search('mars')[0].name == 'Mars'
    assert d.search('midnigt city')[0].name == 'Midnight City'   # typo
    assert len(d.search('', 0, coords.lane_center_x(500_000))) == 8
    assert len(d.all) > 1000
