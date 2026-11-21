"""Draws the AI traffic from traffic.TrafficSim using pooled entities that
share a handful of instanced car meshes."""
from ursina import Entity

from .. import coords
from ..config import DECK_Y, MAX_TRAFFIC
from .car_models import traffic_meshes


class TrafficView:
    def __init__(self, parent):
        self.meshes = traffic_meshes()
        self.slots = []
        for _ in range(MAX_TRAFFIC + 8):
            e = Entity(parent=parent, enabled=False)
            self.slots.append([e, None, None])     # entity, style, instance
        self.brightness = 1.0

    def update(self, cars, player_x):
        n = min(len(cars), len(self.slots))
        for i in range(n):
            car = cars[i]
            slot = self.slots[i]
            e = slot[0]
            style = car.style % len(self.meshes)
            if slot[1] != style:
                if slot[2] is not None:
                    slot[2].removeNode()
                slot[2] = self.meshes[style].instanceTo(e)
                slot[1] = style
            if not e.enabled:
                e.enabled = True
            dx = coords.lane_center_x(car.lane) - car.x
            e.position = (car.x - player_x, DECK_Y, car.rel_s)
            e.rotation_y = max(-12, min(12, dx * 6))
        for i in range(n, len(self.slots)):
            e = self.slots[i][0]
            if e.enabled:
                e.enabled = False

    def set_brightness(self, b):
        self.brightness = b
        for e, _, _ in self.slots:
            e.setColorScale(b, b, b, 1)
