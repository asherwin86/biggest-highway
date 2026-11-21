"""Car models. Uses assets/models/<id>.glb (made by blender/make_cars.py) when
present, otherwise builds a low-poly model from boxes."""
from pathlib import Path

from ursina import Entity, load_model

from .meshkit import MeshKit

MODELS_DIR = Path(__file__).resolve().parents[2] / 'assets' / 'models'
GLASS = (0.08, 0.1, 0.13, 1)
TYRE = (0.06, 0.06, 0.07, 1)
RIM = (0.55, 0.57, 0.6, 1)
TAIL = (0.95, 0.08, 0.08, 1)
HEAD = (0.95, 0.95, 1.0, 1)

TRAFFIC_COLORS = [(0.86, 0.88, 0.92), (0.1, 0.1, 0.11), (0.55, 0.57, 0.6), (0.75, 0.05, 0.08),
                  (0.12, 0.22, 0.5), (0.95, 0.95, 0.96), (0.3, 0.32, 0.35), (0.6, 0.45, 0.25)]
TRAFFIC_SHAPES = [('sedan', 4.7, 1.9, 1.45), ('suv', 4.9, 2.0, 1.75), ('hatch', 4.2, 1.8, 1.5)]


def car_mesh(kind, length, width, height, body, can_fly=False):
    """Car pointing +z, origin at ground centre."""
    k = MeshKit()
    body = tuple(body) + (1,) if len(body) == 3 else tuple(body)
    hl, hw = length / 2, width / 2
    if kind == 'hauler':
        # cab + trailer
        k.box(-hw, 0.6, hl - 3.2, hw, height, hl, body)
        k.box(-hw + 0.1, height * 0.62, hl - 0.2, hw - 0.1, height * 0.92, hl + 0.02, GLASS, sides=False, top=False)
        k.box_c(0, height * 0.77, hl + 0.01, width - 0.3, height * 0.3, 0.05, GLASS)
        k.box(-hw, 0.8, -hl, hw, height + 0.2, hl - 3.6, (0.82, 0.84, 0.86, 1))
        for z in (hl - 1.2, -hl + 1.2, -hl + 2.6):
            for x in (-hw + 0.25, hw - 0.25):
                k.box_c(x, 0.5, z, 0.5, 1.0, 1.0, TYRE)
        k.box_c(-hw + 0.3, 1.0, hl + 0.02, 0.4, 0.2, 0.05, HEAD)
        k.box_c(hw - 0.3, 1.0, hl + 0.02, 0.4, 0.2, 0.05, HEAD)
        k.box_c(0, 1.0, -hl - 0.02, width - 0.4, 0.12, 0.05, TAIL)
        return k.build()

    clear = 0.18
    belt = height * 0.55
    k.box(-hw, clear, -hl, hw, belt, hl, body)
    # sloped-looking cabin from two stacked boxes
    roof_len = length * (0.42 if kind != 'suv' else 0.55)
    zc = -length * 0.06
    k.box(-hw + 0.12, belt, zc - roof_len / 2 - 0.35, hw - 0.12, belt + (height - belt) * 0.55,
          zc + roof_len / 2 + 0.45, GLASS)
    k.box(-hw + 0.22, belt + (height - belt) * 0.55, zc - roof_len / 2, hw - 0.22, height,
          zc + roof_len / 2, body if kind == 'suv' else GLASS)
    # nose taper
    k.box(-hw + 0.1, clear, hl - 0.01, hw - 0.1, belt - 0.15, hl + 0.12, body)
    # wheels
    for z in (hl - length * 0.2, -hl + length * 0.2):
        for x in (-hw + 0.02, hw - 0.02):
            k.box_c(x, 0.36, z, 0.32, 0.72, 0.72, TYRE)
            k.box_c(x + (0.17 if x > 0 else -0.17), 0.36, z, 0.03, 0.4, 0.4, RIM)
    # light bars (wraparound like modern EVs)
    k.box_c(0, belt - 0.12, hl + 0.13, width - 0.3, 0.07, 0.04, HEAD)
    k.box_c(0, belt - 0.05, -hl - 0.02, width - 0.2, 0.1, 0.04, TAIL)
    if can_fly:
        # thruster pods + side fins
        for x in (-hw - 0.15, hw + 0.15):
            k.box_c(x, 0.45, -hl + 0.7, 0.35, 0.35, 1.0, (0.2, 0.2, 0.24, 1))
            k.box_c(x, 0.45, -hl + 0.15, 0.25, 0.25, 0.05, (0.3, 0.8, 1.0, 1))
        k.box_c(0, belt + 0.02, -hl + 0.15, width * 0.9, 0.05, 0.35, body)
    return k.build()


def load_player_model(spec):
    """Entity-ready model for the player's car (glb if available)."""
    path = MODELS_DIR / f'{spec.id}.glb'
    if path.exists():
        try:
            m = load_model(spec.id, folder=MODELS_DIR, file_types=('.glb',))
            if m:
                return m, True
        except Exception as e:      # fall back to the box model
            print('could not load', path, e)
    kind = {'trail': 'suv', 'hauler': 'hauler'}.get(spec.id, 'sedan')
    return car_mesh(kind, spec.length, spec.width, spec.height, spec.color, spec.can_fly), False


def traffic_meshes():
    """Shared meshes for AI traffic: len(TRAFFIC_SHAPES) * len(TRAFFIC_COLORS) styles."""
    out = []
    for kind, l, w, h in TRAFFIC_SHAPES:
        for col in TRAFFIC_COLORS:
            out.append(car_mesh('suv' if kind == 'suv' else 'sedan', l, w, h, col))
    return out
