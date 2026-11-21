"""Tiny helper that builds one combined, vertex-coloured mesh out of boxes and
quads. One mesh per chunk keeps draw calls low. Lighting is baked into the
vertex colours (tops bright, sides darker) so the unlit shader looks shaded."""
from ursina import Mesh

TOP, SIDE_A, SIDE_B, BOTTOM = 1.0, 0.78, 0.62, 0.45


class MeshKit:
    def __init__(self):
        self.v = []      # flat xyz
        self.c = []      # flat rgba
        self.t = []      # flat triangle indices
        self.n = 0

    def _quad(self, p0, p1, p2, p3, col, shade=1.0):
        r, g, b = col[0] * shade, col[1] * shade, col[2] * shade
        a = col[3] if len(col) > 3 else 1.0
        for p in (p0, p1, p2, p3):
            self.v.extend(p)
            self.c.extend((r, g, b, a))
        n = self.n
        # Ursina runs Panda3D in y-up-left: wind so the listed face is the front
        self.t.extend((n, n + 2, n + 1, n, n + 3, n + 2))
        self.n += 4

    def quad_up(self, x0, z0, x1, z1, y, col, shade=TOP):
        """Horizontal rectangle facing up."""
        self._quad((x0, y, z0), (x0, y, z1), (x1, y, z1), (x1, y, z0), col, shade)

    def quad_x(self, x, y0, y1, z0, z1, col, facing=1, shade=SIDE_A):
        """Vertical rectangle in the YZ plane facing +x (facing=1) or -x."""
        if facing > 0:
            self._quad((x, y0, z0), (x, y1, z0), (x, y1, z1), (x, y0, z1), col, shade)
        else:
            self._quad((x, y0, z1), (x, y1, z1), (x, y1, z0), (x, y0, z0), col, shade)

    def quad_z(self, z, y0, y1, x0, x1, col, facing=1, shade=SIDE_B):
        """Vertical rectangle in the XY plane facing +z (facing=1) or -z."""
        if facing > 0:
            self._quad((x1, y0, z), (x1, y1, z), (x0, y1, z), (x0, y0, z), col, shade)
        else:
            self._quad((x0, y0, z), (x0, y1, z), (x1, y1, z), (x1, y0, z), col, shade)

    def box(self, x0, y0, z0, x1, y1, z1, col, top=True, bottom=False, sides=True):
        if top:
            self.quad_up(x0, z0, x1, z1, y1, col)
        if bottom:
            self._quad((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1), col, BOTTOM)
        if sides:
            self.quad_x(x1, y0, y1, z0, z1, col, 1, SIDE_A)
            self.quad_x(x0, y0, y1, z0, z1, col, -1, SIDE_A * 0.9)
            self.quad_z(z1, y0, y1, x0, x1, col, 1, SIDE_B)
            self.quad_z(z0, y0, y1, x0, x1, col, -1, SIDE_B * 1.1)

    def box_c(self, cx, cy, cz, sx, sy, sz, col, **kw):
        """Box from centre + size."""
        self.box(cx - sx / 2, cy - sy / 2, cz - sz / 2, cx + sx / 2, cy + sy / 2, cz + sz / 2, col, **kw)

    def empty(self):
        return self.n == 0

    def build(self):
        if self.n == 0:
            return None
        return Mesh(vertices=self.v, triangles=self.t, colors=self.c, static=True)
