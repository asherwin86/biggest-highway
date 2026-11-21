"""Builds the five Biggest Highway cars in Blender and exports them as .glb
files the game loads from assets/models/.

Run (no Blender window needed):
    E:\\Blender\\blender.exe --background --factory-startup --python blender\\make_cars.py

Open the exported .glb files in Blender to tweak them; the game picks up any
<car id>.glb in assets/models automatically (delete one to get the box model back).
Conventions: metres, origin at ground centre, car front points +Y in Blender.
Colours are stored as a float colour attribute so they survive the trip into
the game's unlit renderer unchanged.
"""
import math
import os
import sys

import bmesh
import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), 'assets', 'models')

GLASS = (0.13, 0.17, 0.23, 1)
TYRE = (0.05, 0.05, 0.06, 1)
RIM = (0.62, 0.64, 0.68, 1)
HEAD = (0.97, 0.97, 1.0, 1)
TAIL = (0.95, 0.06, 0.08, 1)
TRIM = (0.12, 0.12, 0.14, 1)
THRUST = (0.3, 0.9, 1.0, 1)

CARS = {
    # id: (length, width, height, body colour, style)
    'aero': (4.7, 1.9, 1.45, (0.86, 0.88, 0.92, 1), 'sedan'),
    'trail': (4.9, 2.0, 1.75, (0.12, 0.2, 0.42, 1), 'suv'),
    'bolt': (4.5, 1.95, 1.25, (0.75, 0.05, 0.08, 1), 'gt'),
    'hauler': (9.5, 2.5, 3.4, (0.92, 0.92, 0.95, 1), 'hauler'),
    'volt': (4.3, 1.95, 1.15, (0.85, 0.1, 0.55, 1), 'roadster'),
}


def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()
    for m in list(bpy.data.meshes):
        bpy.data.meshes.remove(m)


LIGHT = (0.35, 0.45, 0.82)      # baked key light (the game renders unlit)


def shade(col, n):
    ln = math.sqrt(sum(v * v for v in LIGHT))
    d = (n.x * LIGHT[0] + n.y * LIGHT[1] + n.z * LIGHT[2]) / ln
    k = 0.5 + 0.5 * max(0.0, d) + 0.12 * max(0.0, n.z)    # key + sky fill
    return (min(1, col[0] * k), min(1, col[1] * k), min(1, col[2] * k), col[3])


def paint(obj, col_fn):
    """Fill a float colour attribute. col_fn(face_center, face_normal) -> rgba."""
    me = obj.data
    attr = me.color_attributes.get('Col') or me.color_attributes.new('Col', 'FLOAT_COLOR', 'CORNER')
    me.color_attributes.active_color = attr
    for poly in me.polygons:
        c = col_fn(poly.center, poly.normal)
        if c not in (HEAD, TAIL, THRUST):
            c = shade(c, poly.normal)
        for li in poly.loop_indices:
            attr.data[li].color = c


def solid(col):
    return lambda c, n: col


def profile_body(name, pts, width, bevel=0.07):
    """Extrude a side profile (list of (y, z)) across the car's width."""
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    left = [bm.verts.new((-width / 2, y, z)) for y, z in pts]
    right = [bm.verts.new((width / 2, y, z)) for y, z in pts]
    bm.faces.new(left[::-1])
    bm.faces.new(right)
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((left[i], left[j], right[j], right[i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()
    obj = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(obj)
    if bevel:
        mod = obj.modifiers.new('bevel', 'BEVEL')
        mod.width = bevel
        mod.segments = 3
        mod.limit_method = 'ANGLE'
        apply_mods(obj)
    return obj


def apply_mods(obj):
    bpy.context.view_layer.objects.active = obj
    for m in list(obj.modifiers):
        bpy.ops.object.modifier_apply(modifier=m.name)


def box(name, loc, size, col, bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.active_object
    o.name = name
    o.scale = size
    bpy.ops.object.transform_apply(scale=True)
    if bevel:
        mod = o.modifiers.new('bevel', 'BEVEL')
        mod.width = bevel
        mod.segments = 2
        apply_mods(o)
    paint(o, solid(col))
    return o


def wheel(x, y, r=0.36, w=0.26):
    bpy.ops.mesh.primitive_cylinder_add(vertices=20, radius=r, depth=w, location=(x, y, r),
                                        rotation=(0, math.pi / 2, 0))
    t = bpy.context.active_object
    paint(t, solid(TYRE))
    side = 1 if x > 0 else -1
    bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=r * 0.62, depth=0.03,
                                        location=(x + side * (w / 2 + 0.005), y, r), rotation=(0, math.pi / 2, 0))
    rim = bpy.context.active_object
    paint(rim, solid(RIM))
    return [t, rim]


def body_colors(body, belt):
    def fn(c, n):
        if c.z > belt and n.z < 0.97:
            return GLASS             # windows all round
        if c.z > belt and n.z >= 0.97:
            return (0.2, 0.26, 0.34, 1)   # glass roof catches the sky
        if c.z < 0.32:
            return TRIM              # dark lower trim
        return body
    return fn


def sedan_profile(L, H, roof=(-0.14, 0.1), wind=0.28, rear_win=-0.3, nose_h=0.42, tail_h=0.62):
    return [
        (-L / 2, 0.22), (-L / 2, H * tail_h), (-L / 2 + 0.25, H * (tail_h + 0.05)),
        (L * rear_win, H * 0.68), (L * roof[0], H), (L * roof[1], H),
        (L * wind, H * 0.66), (L * 0.44, H * (nose_h + 0.12)), (L / 2, H * nose_h), (L / 2, 0.22),
    ]


def build_car(cid, L, W, H, col, style):
    parts = []
    if style == 'hauler':
        cab_l = 3.2
        cab = profile_body('cab', [(L / 2 - cab_l, 0.5), (L / 2 - cab_l, H), (L / 2 - 0.6, H),
                                   (L / 2 - 0.05, H * 0.62), (L / 2, 0.5)], W, 0.12)
        paint(cab, lambda c, n: GLASS if (c.z > H * 0.6 and n.y > 0.3) else col)
        parts.append(cab)
        parts.append(box('trailer', (0, -L / 2 + (L - cab_l - 0.4) / 2, (H + 0.2 + 0.8) / 2),
                         (W, L - cab_l - 0.4, H + 0.2 - 0.8), (0.82, 0.84, 0.86, 1), 0.05))
        parts.append(box('chassis', (0, 0, 0.55), (W * 0.8, L * 0.96, 0.3), TRIM))
        for y in (L / 2 - 1.2, -L / 2 + 1.2, -L / 2 + 2.6):
            for x in (-W / 2 + 0.2, W / 2 - 0.2):
                parts += wheel(x, y, 0.5, 0.36)
        parts.append(box('head', (0, L / 2 + 0.01, 0.95), (W - 0.5, 0.04, 0.12), HEAD))
        parts.append(box('tail', (0, -L / 2 - 0.01, 1.0), (W - 0.4, 0.04, 0.12), TAIL))
    else:
        if style == 'suv':
            pts = sedan_profile(L, H, roof=(-0.4, 0.1), wind=0.27, rear_win=-0.47, tail_h=0.66)
        elif style == 'gt':
            pts = sedan_profile(L, H, roof=(-0.16, 0.0), wind=0.22, rear_win=-0.38, nose_h=0.36, tail_h=0.64)
        elif style == 'roadster':
            pts = sedan_profile(L, H, roof=(-0.2, -0.02), wind=0.16, rear_win=-0.32, nose_h=0.36, tail_h=0.6)
        else:
            pts = sedan_profile(L, H)
        body = profile_body('body', pts, W)
        paint(body, body_colors(col, H * 0.64))
        parts.append(body)
        for y in (L * 0.31, -L * 0.31):
            for x in (-W / 2 + 0.1, W / 2 - 0.1):
                parts += wheel(x, y)
        nose_z = H * (0.36 if style in ('gt', 'roadster') else 0.42)
        parts.append(box('headbar', (0, L / 2 + 0.005, nose_z + 0.06), (W - 0.35, 0.04, 0.05), HEAD))
        parts.append(box('tailbar', (0, -L / 2 - 0.005, H * 0.58), (W - 0.2, 0.04, 0.07), TAIL))
        if style == 'gt':
            parts.append(box('spoiler', (0, -L / 2 + 0.15, H * 0.7), (W * 0.9, 0.3, 0.04), TRIM))
        if style == 'roadster':
            for x in (-W / 2 - 0.12, W / 2 + 0.12):
                parts.append(box('pod', (x, -L / 2 + 0.75, 0.48), (0.3, 1.1, 0.3), TRIM, 0.04))
                parts.append(box('jet', (x, -L / 2 + 0.18, 0.48), (0.2, 0.05, 0.2), THRUST))
            parts.append(box('fin', (0, -L / 2 + 0.2, H * 0.66), (W * 0.85, 0.35, 0.04), col))

    bpy.ops.object.select_all(action='DESELECT')
    for p in parts:
        p.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    car = bpy.context.active_object
    car.name = cid
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bpy.ops.object.shade_flat()

    mat = bpy.data.materials.new(cid + '_paint')
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get('Principled BSDF')
    attr = nt.nodes.new('ShaderNodeVertexColor')
    attr.layer_name = 'Col'
    nt.links.new(attr.outputs['Color'], bsdf.inputs['Base Color'])
    car.data.materials.append(mat)
    return car


def export(obj, path):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    kw = dict(filepath=path, export_format='GLB', use_selection=True, export_apply=True)
    for extra in ({'export_vertex_color': 'ACTIVE'}, {'export_colors': True}, {}):
        try:
            bpy.ops.export_scene.gltf(**kw, **extra)
            return
        except TypeError:
            continue


def main():
    os.makedirs(OUT, exist_ok=True)
    only = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    for cid, (L, W, H, col, style) in CARS.items():
        if only and cid not in only:
            continue
        clear_scene()
        car = build_car(cid, L, W, H, col, style)
        path = os.path.join(OUT, cid + '.glb')
        export(car, path)
        print(f'exported {path}  ({len(car.data.polygons)} faces)')


main()
