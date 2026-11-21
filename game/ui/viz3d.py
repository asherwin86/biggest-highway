"""Live 3D self-driving visualization for the centre screen.

A second camera renders a minimal, separate 3D scene (road lines, the cars
around you, the planned path, parking spaces) into a texture that is shown on
the dashboard. Geometry is plain Panda3D nodes so it never mixes with the
main world."""
import math

from panda3d.core import (Camera, FrameBufferProperties, NodePath, PerspectiveLens, Point3,
                          TransparencyAttrib, Vec4)
from ursina import Entity, Mesh, Texture, application

from .. import coords
from ..citylayout import CX, CZ, EW_STREETS, NS_STREETS, SPOT_DEPTH, SPOT_PITCH, chunk_of, chunk_origin_x, lots_near
from ..config import LANE_W, NUM_BANDS
from ..world.car_models import car_mesh
from ..world.meshkit import MeshKit

ROAD = (0.12, 0.13, 0.16)
LINE = Vec4(0.62, 0.65, 0.7, 1)
EDGE = Vec4(0.85, 0.87, 0.9, 1)
BLUE = Vec4(0.22, 0.52, 1.0, 1)
LEAD = Vec4(0.55, 0.75, 1.25, 1)
SPOT_LINE = Vec4(0.55, 0.58, 0.63, 1)
VIEW_AHEAD, VIEW_BEHIND = 140.0, 30.0
RD = -1          # Ursina's rotation direction for heading


def _unit_quad():
    k = MeshKit()
    k.quad_up(-0.5, -0.5, 0.5, 0.5, 0.0, (1, 1, 1, 1), 1.0)
    return k.build()


class Pool:
    def __init__(self, root, geom, n, name):
        self.nodes = []
        for i in range(n):
            nd = root.attachNewNode(f'{name}{i}')
            geom.instanceTo(nd)
            nd.hide()
            self.nodes.append(nd)
        self.i = 0

    def begin(self):
        self.i = 0

    def take(self):
        if self.i >= len(self.nodes):
            return None
        nd = self.nodes[self.i]
        self.i += 1
        nd.show()
        return nd

    def end(self):
        for nd in self.nodes[self.i:]:
            nd.hide()


class FSDView:
    def __init__(self, parent, position, size, res=(640, 448)):
        base = application.base
        fbp = FrameBufferProperties()
        fbp.setRgbColor(True)
        fbp.setDepthBits(24)
        fbp.setMultisamples(4)
        self.buffer = base.win.makeTextureBuffer('fsd-view', res[0], res[1], None, False, fbp)
        if self.buffer is None:                                     # no MSAA on this GPU
            self.buffer = base.win.makeTextureBuffer('fsd-view', res[0], res[1])
        self.buffer.setSort(-50)
        self.buffer.setClearColor(Vec4(0.07, 0.08, 0.1, 1))
        self.root = NodePath('fsd-root')
        self.root.setTransparency(TransparencyAttrib.MAlpha)
        lens = PerspectiveLens()
        lens.setFov(50)
        lens.setAspectRatio(res[0] / res[1])
        lens.setNearFar(0.5, 600)
        cam_node = Camera('fsd-cam', lens)
        cam_node.setScene(self.root)
        self.cam = self.root.attachNewNode(cam_node)
        dr = self.buffer.makeDisplayRegion()
        dr.setCamera(self.cam)
        self.screen = Entity(parent=parent, model='quad', texture=Texture(self.buffer.getTexture()),
                             position=position, scale=size)

        quad = _unit_quad()
        k = MeshKit()
        k.quad_up(-400, -200, 400, 600, -0.02, (*ROAD, 1), 1.0)
        self.ground = root_attach(self.root, k.build(), 'ground')
        self.lines = Pool(self.root, quad, 40, 'line')
        self.glass = Pool(self.root, quad, 6, 'glass')
        self.spots = Pool(self.root, quad, 160, 'spot')
        self.target = Pool(self.root, quad, 1, 'target')
        self.gray_car = car_mesh('sedan', 4.7, 1.9, 1.45, (0.6, 0.62, 0.66))
        self.gray_suv = car_mesh('suv', 4.9, 2.0, 1.75, (0.6, 0.62, 0.66))
        self.cars = Pool(self.root, self.gray_car, 36, 'car')
        self.suvs = Pool(self.root, self.gray_suv, 12, 'suv')
        self.parked = Pool(self.root, self.gray_car, 70, 'parked')
        self.me = self.root.attachNewNode('me')
        self._me_spec = None
        self.path_np = self.root.attachNewNode('path')
        self.path_mesh = None
        self.cam_yaw = 0.0

    # ------------------------------------------------------------------
    def _set_player_model(self, spec):
        if self._me_spec is spec:
            return
        self._me_spec = spec
        self.me.getChildren().detach()
        kind = {'trail': 'suv', 'hauler': 'hauler'}.get(spec.id, 'sedan')
        car_mesh(kind, spec.length, spec.width, spec.height, (0.96, 0.96, 0.98), spec.can_fly).reparentTo(self.me)

    def update(self, dt, game):
        p = game.player
        self._set_player_model(p.spec)
        park = game.autopark
        city = p.under_deck
        parking = city or park.active or park.state == 'parked'
        self.me.setPos(0, 0, 0)
        self.me.setH(RD * p.yaw)

        # camera: chase-style, turns with the car when it is manoeuvring in the city
        want = p.yaw if parking else 0.0
        diff = (want - self.cam_yaw + 180) % 360 - 180
        self.cam_yaw += diff * min(1.0, dt * 3)
        if parking:
            off, look = (0, 15, -11), (0, 0, 7)
        else:
            off, look = (0, 7.5, -12.5), (0, 0, 18)
        self.cam.setPos(*_rot(off, self.cam_yaw))
        self.cam.lookAt(Point3(*_rot(look, self.cam_yaw)))

        self._draw_lines(p, parking)
        self._draw_traffic(game, p, parking)
        self._draw_parking(game, p, parking)
        self._draw_path(game, p, parking)

    # ------------------------------------------------------------------
    def _line(self, x, z, w, length, col, heading=0.0, y=0.0):
        nd = self.lines.take()
        if nd is None:
            return
        nd.setPos(x, y, z)
        nd.setScale(w, 1, length)
        nd.setH(RD * heading)
        nd.setColorScale(col)

    def _draw_lines(self, p, parking):
        self.lines.begin()
        self.glass.begin()
        if not parking:
            lane = p.lane
            for l in range(lane - 6, lane + 8):
                if l < 0 or l > coords.LANES:
                    continue
                edge_x = coords.lane_center_x(min(l, coords.LANES - 1)) - LANE_W / 2
                if l == coords.LANES:
                    edge_x += LANE_W
                band_edge = l % 48 == 0 or l == coords.LANES
                x = edge_x - p.x
                self._line(x, 110, 0.22 if band_edge else 0.12, 300, EDGE if band_edge else LINE, y=0.01)
                if band_edge and l > 0 and l < coords.LANES:      # glass median before this band
                    g = self.glass.take()
                    if g is not None:
                        g.setPos(x - 12, 0.0, 110)
                        g.setScale(23.6, 1, 300)
                        g.setColorScale(0.25, 0.45, 0.8, 0.35)
                    self._line(x - 24, 110, 0.22, 300, EDGE, y=0.01)
        else:
            # street curbs of the city grid around the car
            cx, cz = chunk_of(p.x, p.s)
            for dcx in (-1, 0, 1, 2):
                ox = chunk_origin_x(cx + dcx)
                for sx in NS_STREETS:
                    for side in (-8, 8):
                        self._line(ox + sx + side - p.x, 0, 0.15, 400, EDGE, y=0.01)
            base = math.floor(p.s / CZ) * CZ
            for k in range(-1, 3):
                for sz in EW_STREETS:
                    for side in (-8, 8):
                        z = coords.delta_s(p.s, coords.wrap_s(base + k * CZ + sz + side))
                        self._line(0, z, 600, 0.15, EDGE, y=0.01)
        self.lines.end()
        self.glass.end()

    def _draw_traffic(self, game, p, parking):
        self.cars.begin()
        self.suvs.begin()
        if not p.under_deck:
            lead = None
            if game.autopilot.enabled:
                ahead = [c for c in game.traffic.cars if c.lane == game.plan_lane and 0 < c.rel_s < 160]
                lead = min(ahead, key=lambda c: c.rel_s) if ahead else None
            for c in game.traffic.cars:
                if not (-VIEW_BEHIND < c.rel_s < VIEW_AHEAD) or abs(c.x - p.x) > 30:
                    continue
                pool = self.suvs if c.style // 8 == 1 else self.cars
                nd = pool.take()
                if nd is None:
                    continue
                nd.setPos(c.x - p.x, 0, c.rel_s)
                nd.setH(0)
                nd.setColorScale(LEAD if c is lead else Vec4(1, 1, 1, 1))
        self.cars.end()
        self.suvs.end()

    def _draw_parking(self, game, p, parking):
        self.spots.begin()
        self.parked.begin()
        self.target.begin()
        if parking:
            park = game.autopark
            for lot in lots_near(p.x, p.s, rx=80, rs_behind=60, rs_ahead=90):
                for sp in lot.spots:
                    dz = coords.delta_s(p.s, coords.wrap_s(sp.s))
                    dx = sp.x - p.x
                    if abs(dx) > 55 or not (-45 < dz < 70):
                        continue
                    nd = self.spots.take()
                    if nd is not None:      # divider line between spaces
                        nd.setPos(dx, 0.01, dz - SPOT_PITCH / 2)
                        nd.setScale(SPOT_DEPTH, 1, 0.1)
                        nd.setColorScale(SPOT_LINE)
                    is_target = park.spot is not None and park.active and sp is park.spot
                    if sp.occupied and not is_target and not (park.state == 'parked' and sp is park.spot):
                        car = self.parked.take()
                        if car is not None:
                            car.setPos(dx, 0, dz)
                            car.setH(RD * (-90 * sp.side))
                    if is_target:
                        t = self.target.take()
                        t.setPos(dx, 0.02, dz)
                        t.setScale(SPOT_DEPTH - 0.4, 1, SPOT_PITCH - 0.3)
                        t.setColorScale(0.22, 0.52, 1.0, 0.75)
        self.spots.end()
        self.parked.end()
        self.target.end()

    def _draw_path(self, game, p, parking):
        pts = []
        park = game.autopark
        if park.active:
            for x, s in park.route_points(step=2.0):
                dz = coords.delta_s(p.s, coords.wrap_s(s))
                if dz > 120 or dz < -60:
                    break
                pts.append((x - p.x, dz))
            pts = pts[:40]
        elif game.autopilot.enabled and not p.under_deck and game.plan_lane is not None:
            tx = coords.lane_center_x(game.plan_lane) - p.x
            for i in range(24):
                z = i * 3.0
                u = min(1.0, z / 28.0)
                u = u * u * (3 - 2 * u)
                pts.append((tx * u, z + 2.5))
        if self.path_mesh is not None:
            self.path_mesh.removeNode()
            self.path_mesh = None
        if len(pts) < 2:
            return
        v, t, c = [], [], []
        hw = 0.8
        for i, (x, z) in enumerate(pts):
            j = min(i + 1, len(pts) - 1)
            k = max(i - 1, 0)
            dx, dz = pts[j][0] - pts[k][0], pts[j][1] - pts[k][1]
            ln = math.hypot(dx, dz) or 1.0
            nx, nz = dz / ln * hw, -dx / ln * hw
            a = 0.75 * (1 - i / len(pts)) + 0.1
            v += [x - nx, 0.03, z - nz, x + nx, 0.03, z + nz]
            c += [0.22, 0.52, 1.0, a, 0.22, 0.52, 1.0, a]
        for i in range(len(pts) - 1):
            n = i * 2
            t += [n, n + 1, n + 3, n, n + 3, n + 2]
        m = Mesh(vertices=v, triangles=t, colors=c, static=False)
        m.setTwoSided(True)
        m.reparentTo(self.path_np)
        self.path_mesh = m


def root_attach(root, mesh, name):
    nd = root.attachNewNode(name)
    mesh.reparentTo(nd)
    return nd


def _rot(v, yaw):
    a = math.radians(yaw)
    x, y, z = v
    return (x * math.cos(a) + z * math.sin(a), y, -x * math.sin(a) + z * math.cos(a))
