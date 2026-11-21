import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game import coords
from game.autopark import AutoPark
from game.autopilot import Autopilot
from game.citylayout import chunk_layout, lots_near
from game.config import CITY_Y, DECK_Y, EARTH_LOOP_M
from game.traffic import AICar
from game.vehicles import CAR_BY_ID, PlayerCar


def make_car(lane=500_000, s=1000.0, car='aero', alt=DECK_Y):
    p = PlayerCar(CAR_BY_ID[car])
    p.teleport(s, coords.lane_center_x(lane), alt)
    return p


def test_layout_is_deterministic():
    a = chunk_layout(2315, 17)
    chunk_layout.cache_clear()
    b = chunk_layout(2315, 17)
    assert [blk.kind for blk in a.blocks] == [blk.kind for blk in b.blocks]


def test_lots_have_free_spaces_and_no_pillar_clashes():
    p = make_car()
    lots = lots_near(p.x, p.s)
    assert lots
    for lot in lots:
        assert len(lot.spots) == 144
        assert lot.free
        assert all(lot.x0 <= sp.x <= lot.x1 and lot.s0 <= sp.s <= lot.s1 for sp in lot.spots)


def ahead_lot(p, min_ahead=200):
    lots = [l for l in lots_near(p.x, p.s) if l.street_s - p.s > min_ahead]
    return min(lots, key=lambda l: abs(l.center[0] - p.x) + (l.street_s - p.s))


def run(ap, p, secs=600, dt=1 / 30):
    events = []
    for _ in range(int(secs / dt)):
        ev = ap.update(dt, p)
        if ev:
            events.append(ev)
        if ap.state == 'parked':
            break
    return events


def test_auto_park_from_highway_deck():
    p = make_car()
    lot = ahead_lot(p)
    ap = AutoPark()
    ok, msg = ap.plan(p, lot)
    assert ok, msg
    events = run(ap, p)
    assert 'lift' in events and 'landed' in events and events[-1] == 'parked'
    sp = ap.spot
    assert abs(p.alt - CITY_Y) < 1e-6
    assert math.hypot(p.x - sp.x, coords.delta_s(p.s, coords.wrap_s(sp.s))) < 0.3
    assert abs(abs(p.yaw) - 90) < 3          # backed in, nose facing the aisle
    assert sp.occupied


def test_auto_park_from_city_level():
    p = make_car(alt=CITY_Y)
    p.x += 30                                # somewhere off the street grid
    ap = AutoPark()
    ok, msg = ap.plan(p, ahead_lot(p))
    assert ok, msg
    assert run(ap, p)[-1] == 'parked'


def test_auto_park_refuses_lots_behind_you():
    p = make_car(s=5000)
    behind = [l for l in lots_near(p.x, p.s) if l.street_s < p.s - 20]
    ok, msg = AutoPark().plan(p, behind[0])
    assert not ok and 'behind' in msg


def test_auto_park_across_the_loop_seam():
    p = make_car(s=EARTH_LOOP_M - 150)
    ap = AutoPark()
    ok, msg = ap.plan(p, ahead_lot(p, 250))
    assert ok, msg
    assert run(ap, p)[-1] == 'parked'
    assert 0 <= p.s < 2000                   # parked just past kilometre 0


def ai(lane, rel, speed, player):
    c = AICar(0, coords.wrap_s(player.s + rel), coords.lane_center_x(lane), lane, speed, speed, 0)
    c.rel_s = rel
    return c


def test_turn_signal_waits_for_gap_then_changes_lane():
    p = make_car(lane=500_000 - 500_000 % 48 + 10)
    p.speed = 30
    ap = Autopilot()
    ap.enabled = True
    ap.request_lane_change(+1)
    blocker = ai(p.lane + 1, 2, 30, p)
    plan = ap.plan(0.1, p, [blocker])
    assert plan.status.startswith('Waiting') and ap.indicator == 1
    assert ap.target_lane == p.lane
    plan = ap.plan(0.1, p, [])
    assert ap.target_lane == p.lane + 1 and ap.indicator == 1
    for _ in range(100):
        p.update(0.05, ap.plan(0.05, p, []).controls)
    assert p.lane == ap.target_lane and ap.indicator == 0


def test_turn_signal_tap_again_cancels():
    ap = Autopilot()
    ap.request_lane_change(-1)
    ap.request_lane_change(-1)
    assert ap.signal == 0
