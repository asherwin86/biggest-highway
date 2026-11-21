import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game import coords
from game.citylayout import CZ, chunk_layout, chunk_origin_x, chunk_of, solid_at
from game.config import CITY_Y
from game.vehicles import CAR_BY_ID, Controls, PlayerCar


def city_car(x, s, yaw=0.0, car='aero'):
    p = PlayerCar(CAR_BY_ID[car])
    p.teleport(s, x, CITY_Y)
    p.yaw = yaw
    return p


def intersection():
    x0 = coords.lane_center_x(500_000)
    cx, cz = chunk_of(x0, 1000.0)
    return chunk_origin_x(cx), cz * CZ          # under a glass median, on an east-west street


def test_right_turn_at_an_intersection():
    x, s = intersection()
    p = city_car(x, s - 20)
    p.speed = 7
    t = 0.0
    while t < 6 and abs(p.yaw - 90) > 3:
        steer = 1.0 if p.s > coords.wrap_s(s - 6) or p.s < s - 100 else 0.0
        p.update(1 / 60, Controls(throttle=0.15, steer=steer))
        t += 1 / 60
    assert abs(p.yaw - 90) <= 3, p.yaw           # now heading along the cross street (+x)
    x_before = p.x
    for _ in range(120):
        p.update(1 / 60, Controls(throttle=0.3))
    assert p.x > x_before + 8                    # and it actually drives that way
    assert abs(coords.delta_s(s, p.s)) < 8       # still on the cross street


def test_u_turn_is_possible():
    x, s = intersection()
    p = city_car(x, s - 4)
    p.speed = 5
    for _ in range(int(8 * 60)):
        p.update(1 / 60, Controls(throttle=0.1, steer=-1.0))
        if abs(abs(p.yaw) - 180) < 5:
            break
    assert abs(abs(p.yaw) - 180) < 5


def test_reverse_goes_backwards_along_heading():
    x, s = intersection()
    p = city_car(x, s, yaw=90)
    for _ in range(120):
        p.update(1 / 60, Controls(brake=1.0))
    assert p.speed < 0 and p.x < x - 1


def test_buildings_are_solid():
    x0 = coords.lane_center_x(500_000)
    cx, cz = chunk_of(x0, 1000.0)
    lay = chunk_layout(cx, cz)
    blk = next(b for b in lay.blocks if b.kind in ('towers', 'park') and b.x0 < 50)
    ox, s0 = chunk_origin_x(cx), cz * CZ
    s_mid = s0 + (blk.z0 + blk.z1) / 2
    assert solid_at(ox + blk.x0 + 5, s_mid)
    assert not solid_at(ox, s_mid)              # the street is open
    p = city_car(ox, s_mid, yaw=90)             # pointing straight at the block
    for _ in range(300):
        p.update(1 / 60, Controls(throttle=1.0))
    assert p.x < ox + blk.x0                    # stopped at the curb
    assert 'wall' in p.events or abs(p.speed) < 2


def test_slides_along_curb_instead_of_sticking():
    x0 = coords.lane_center_x(500_000)
    cx, cz = chunk_of(x0, 1000.0)
    ox, s0 = chunk_origin_x(cx), cz * CZ
    lay = chunk_layout(cx, cz)
    blk = next(b for b in lay.blocks if b.kind in ('towers', 'park') and b.x0 < 50 and b.z0 < 50)
    p = city_car(ox + blk.x0 - 2.0, s0 + blk.z0 + 5, yaw=30)   # glancing angle into the block
    s_start = p.s
    for _ in range(180):
        p.update(1 / 60, Controls(throttle=0.6))
    assert coords.delta_s(s_start, p.s) > 5     # kept moving along the street
    assert not solid_at(p.x, p.s)
