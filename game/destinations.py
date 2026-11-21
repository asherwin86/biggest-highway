"""Destinations on the highway, in the city below and out in space,
plus the search used by the map's search bar. Pure Python."""
import difflib
import math
import random
from dataclasses import dataclass

from . import coords
from .config import EARTH_LOOP_M, LANES

C = EARTH_LOOP_M
AU = 149_597_870_700.0


@dataclass
class Destination:
    name: str
    kind: str
    s: float = 0.0
    lane: int = 0
    city: bool = False            # in the city under the highway
    space: bool = False           # far-away landmark on the map, not on the highway
    map_xy: tuple = None          # map position for space landmarks
    blurb: str = ''

    @property
    def x(self) -> float:
        return coords.lane_center_x(self.lane)

    @property
    def reachable(self) -> bool:
        return not self.space

    def map_pos(self):
        if self.map_xy is not None:
            return self.map_xy
        return coords.highway_to_map(self.s, self.x)


def _orbit(r, deg, around=(0.0, 0.0)):
    a = math.radians(deg)
    return (around[0] + r * math.cos(a), around[1] + r * math.sin(a))


SUN = _orbit(AU, 200)

HANDMADE = [
    Destination('Start / Finish Line', 'Landmark', 0, 500_000, blurb='Kilometre zero of the loop'),
    Destination('Lane Zero Lookout', 'Overlook', 1_200, 0, blurb='The innermost lane, edge of the world'),
    Destination('Lane 1,000,000 Edge', 'Overlook', 5_000, LANES - 1, blurb='The very last lane'),
    Destination('Million Lane Monument', 'Landmark', 2_500, 500_000, blurb='Dead centre of the highway'),
    Destination('Halfway Around The World', 'Landmark', C / 2, 500_000, blurb='20,037.5 km from the start'),
    Destination('Midnight City', 'City', 120_000, 500_010, city=True, blurb='Neon district under the deck'),
    Destination('Orbit Diner', 'Diner', 3_400, 499_995, blurb='Pancakes at 300 km/h'),
    Destination('MegaCharge Plaza', 'Charging', 8_000, 500_020, blurb='4,000 chargers, zero queues'),
    Destination('Glass Median Overlook', 'Overlook', 1_800, 500_015, blurb='Look down at the city through the glass'),
    Destination('Neon District', 'City', 15_000, 499_960, city=True),
    Destination('Harbor Underpass', 'City', 42_000, 500_100, city=True),
    Destination('Old Town Market', 'City', 9_500, 499_900, city=True),
    Destination('Drive-In Theater 9000', 'Entertainment', 26_000, 500_200),
    Destination('Infinity Car Wash', 'Service', 600, 500_006),
    Destination('Cloud Parking Tower', 'Parking', 11_000, 500_050),
    Destination('Sunrise Point', 'Overlook', 10_018_750, 250_000, blurb='A quarter of the way around'),
    Destination('Sunset Strip', 'Entertainment', 30_056_250, 750_000),
    Destination('Equator Rest Stop', 'Rest Stop', 5_000_000, 600_000),
    Destination('Great Interchange', 'Interchange', 2_000_000, 100_000),
    Destination('Lane 42 Library', 'Landmark', 4_200, 42),
    Destination('Stadium Exit', 'Exit', 64_000, 500_300),
    Destination('Tunnel Arcade', 'City', 7_300, 500_030, city=True),
    Destination('Ring Road Museum', 'Museum', 300_000, 400_000),
    Destination('Far Lane Farms', 'Rest Stop', 1_000_000, 900_000),
    Destination('Inner Ring Hotel', 'Hotel', 700_000, 5_000),
    Destination('Lap Counter Cafe', 'Diner', C - 2_000, 500_000, blurb='Right before the loop starts again'),
    Destination('Skyway Launch Pad', 'Landmark', 3_000, 500_040, blurb='Popular with Volt Roadster pilots'),
    # far-away landmarks: shown on the 1-billion-km map
    Destination('The Moon', 'Space', space=True, map_xy=_orbit(384_400_000, 35), blurb='384,400 km away'),
    Destination('Sun', 'Space', space=True, map_xy=SUN, blurb='1 AU'),
    Destination('Venus', 'Space', space=True, map_xy=_orbit(0.723 * AU, 120, SUN)),
    Destination('Mercury', 'Space', space=True, map_xy=_orbit(0.387 * AU, 300, SUN)),
    Destination('Mars', 'Space', space=True, map_xy=_orbit(1.524 * AU, 60, SUN)),
    Destination('Asteroid Belt Truck Stop', 'Space', space=True, map_xy=_orbit(2.7 * AU, 15, SUN)),
    Destination('Edge Of The Map', 'Space', space=True, map_xy=(4.9e11, 0.0),
                blurb='500,000,000 km from Earth'),
]

_PRE = ['Silver', 'Cedar', 'Nova', 'Echo', 'Maple', 'Quartz', 'Harbor', 'Aurora', 'Granite', 'Willow',
        'Copper', 'Velvet', 'Summit', 'Coral', 'Ember', 'Lumen', 'Atlas', 'Juniper', 'Pioneer', 'Zephyr',
        'Indigo', 'Saffron', 'Falcon', 'Meadow', 'Polar', 'Cobalt', 'Sable', 'Orchid', 'Comet', 'Birch']
_SUF = ['ridge', 'field', 'port', 'gate', 'brook', 'view', 'wood', 'haven', 'crest', 'point',
        'dale', 'stone', 'bay', 'side', 'fall', 'heights', 'glen', 'ton', 'more', 'shore']
_KINDS = [('Rest Stop', False), ('Charge Plaza', False), ('Diner', False), ('Overlook', False),
          ('Exit', False), ('Hotel', False), ('Mall', False), ('Garage', False),
          ('District', True), ('Park', True), ('Market', True), ('Towers', True), ('Arcade', True)]


def generate(count=1500, seed=1234):
    rng = random.Random(seed)
    out, used = [], set()
    while len(out) < count:
        k, city = rng.choice(_KINDS)
        name = f'{rng.choice(_PRE)}{rng.choice(_SUF)} {k}'
        if name in used:
            name = f'{name} {rng.randint(2, 99)}'
            if name in used:
                continue
        used.add(name)
        # most places cluster near the middle lanes where people start
        if rng.random() < 0.4:
            lane = 500_000 + int(rng.gauss(0, 400))
            s = rng.uniform(0, 300_000)
        else:
            lane = rng.randrange(LANES)
            s = rng.uniform(0, C)
        out.append(Destination(name, k, s, coords.clamp_lane(lane), city=city))
    return out


class Directory:
    def __init__(self, procedural=1500):
        self.all = list(HANDMADE) + generate(procedural)

    @staticmethod
    def distance(car_s, car_x, d: Destination) -> float:
        if d.space:
            mx, my = coords.highway_to_map(car_s, car_x)
            px, py = d.map_xy
            return math.hypot(px - mx, py - my)
        along = coords.delta_s(car_s, d.s)
        return math.hypot(along, d.x - car_x)

    def nearest(self, car_s, car_x, limit=8):
        ds = [d for d in self.all if not d.space]
        ds.sort(key=lambda d: self.distance(car_s, car_x, d))
        return ds[:limit]

    def search(self, query: str, car_s=0.0, car_x=None, limit=8):
        q = query.strip().lower()
        if car_x is None:
            car_x = coords.lane_center_x(500_000)
        if not q:
            return self.nearest(car_s, car_x, limit)
        scored = []
        for d in self.all:
            name = d.name.lower()
            hay = f'{name} {d.kind.lower()}'
            if name.startswith(q):
                score = 3.0
            elif any(w.startswith(q) for w in hay.split()):
                score = 2.5
            elif q in hay:
                score = 2.0
            else:
                words = hay.split()
                per_word = [max(difflib.SequenceMatcher(None, qw, w).ratio() for w in words)
                            for qw in q.split()]
                r = max(difflib.SequenceMatcher(None, q, name).ratio(),
                        sum(per_word) / len(per_word))
                if r < 0.72:
                    continue
                score = r
            scored.append((score, -self.distance(car_s, car_x, d) / 1e15, d))
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return [t[2] for t in scored[:limit]]
