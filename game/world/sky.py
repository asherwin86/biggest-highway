"""Day/night cycle: sky colour, fog and how bright the world is."""
import math

from ursina import Color, Entity, camera, scene, window

from ..config import DAY_LENGTH_S, FOG_END, START_HOUR

KEYS = [  # hour, sky colour, world brightness, window-light strength
    (0.0, (0.02, 0.03, 0.08), 0.28, 1.0),
    (5.0, (0.05, 0.06, 0.14), 0.32, 1.0),
    (6.5, (0.95, 0.6, 0.45), 0.7, 0.5),
    (8.0, (0.55, 0.75, 0.95), 1.0, 0.0),
    (16.5, (0.55, 0.75, 0.95), 1.0, 0.0),
    (18.5, (0.98, 0.5, 0.35), 0.7, 0.6),
    (19.8, (0.12, 0.1, 0.25), 0.4, 1.0),
    (24.0, (0.02, 0.03, 0.08), 0.28, 1.0),
]


def sample(hour):
    h = hour % 24
    for (h0, c0, b0, w0), (h1, c1, b1, w1) in zip(KEYS, KEYS[1:]):
        if h0 <= h <= h1:
            t = (h - h0) / (h1 - h0)
            t = t * t * (3 - 2 * t)
            col = tuple(a + (b - a) * t for a, b in zip(c0, c1))
            return col, b0 + (b1 - b0) * t, w0 + (w1 - w0) * t
    return KEYS[0][1], KEYS[0][2], KEYS[0][3]


class DayNight:
    def __init__(self, hour=START_HOUR):
        self.hour = hour
        self.speed = 24.0 / DAY_LENGTH_S      # in-game hours per second
        self.paused = False
        self._last_apply = -1.0
        self.sky, self.brightness, self.lights = sample(hour)
        self.fog_end = FOG_END

    def update(self, dt):
        if not self.paused:
            self.hour = (self.hour + dt * self.speed) % 24

    def due(self, t_now):
        """Only re-tint the world every half second (it touches many entities)."""
        if t_now - self._last_apply >= 0.5:
            self._last_apply = t_now
            return True
        return False

    def apply(self, fog_end=None):
        self.sky, self.brightness, self.lights = sample(self.hour)
        c = Color(*self.sky, 1)
        window.color = c
        scene.fog_color = c
        scene.fog_density = (0, fog_end or self.fog_end)

    @property
    def clock(self):
        h = int(self.hour)
        m = int((self.hour - h) * 60)
        return f'{h:02d}:{m:02d}'
