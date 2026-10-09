"""Thin bpy helper layer: scene setup, collections, fast mesh creation,
linked-duplicate instancing and preview materials.
"""

import math
import os

import bpy
import numpy as np
from mathutils import Matrix, Vector

from . import config, materials
from .meshbuild import part_arrays

COLLECTIONS = [
    "TERRAIN_VISUAL", "TERRAIN_FAR", "PISTES_VISUAL", "ROCKS", "FOREST", "BUILDINGS",
    "BRIDGES", "ICE_CAVE", "FROZEN_LAKE", "GONDOLA", "START_AREA", "FINISH_AREA",
    "DECORATION", "GAMEPLAY_MARKERS", "COLLISION_REFERENCE", "ASSET_LIBRARY",
]


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scn = bpy.context.scene
    scn.unit_settings.system = "METRIC"
    scn.unit_settings.scale_length = 1.0
    scn.unit_settings.length_unit = "METERS"
    root = bpy.data.collections.new("SNOWY_VALLEY_ROOT")
    scn.collection.children.link(root)
    for name in COLLECTIONS:
        c = bpy.data.collections.new(name)
        root.children.link(c)
    return root


def coll(name):
    return bpy.data.collections[name]


# ---------------------------------------------------------------------------
# materials
# ---------------------------------------------------------------------------

_TEX_DIR = None


def set_texture_dir(path):
    global _TEX_DIR
    _TEX_DIR = path


def get_material(name):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    rbx, col, extra = materials.MATERIALS[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    lin = [materials.srgb_to_linear(c) for c in col] + [1.0]
    bsdf.inputs["Base Color"].default_value = lin
    bsdf.inputs["Roughness"].default_value = extra.get("rough", 0.6)
    bsdf.inputs["Metallic"].default_value = extra.get("metal", 0.0)
    m.diffuse_color = lin
    if "emit" in extra:
        bsdf.inputs["Emission Color"].default_value = lin
        bsdf.inputs["Emission Strength"].default_value = extra["emit"]
    if "transparency" in extra:
        bsdf.inputs["Alpha"].default_value = 1.0 - extra["transparency"]
    # vertex-colour variation (multiplied) for previews
    attr = nt.nodes.new("ShaderNodeVertexColor")
    attr.layer_name = "Col"
    if "texture" in extra and _TEX_DIR:
        tex = nt.nodes.new("ShaderNodeTexImage")
        path = os.path.join(_TEX_DIR, extra["texture"])
        if os.path.exists(path):
            tex.image = bpy.data.images.load(path, check_existing=True)
            tex.interpolation = "Closest"
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.inputs["Factor"].default_value = 0.35
        nt.links.new(tex.outputs["Color"], mix.inputs["A"])
        nt.links.new(attr.outputs["Color"], mix.inputs["B"])
        nt.links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
    else:
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.inputs["Factor"].default_value = 1.0
        mix.inputs["A"].default_value = lin
        nt.links.new(attr.outputs["Color"], mix.inputs["B"])
        nt.links.new(mix.outputs["Result"], bsdf.inputs["Base Color"])
    _detail_nodes(nt, bsdf, mix, rbx, lin)
    if rbx == "Snow":
        bsdf.inputs["Subsurface Weight"].default_value = 0.06
        bsdf.inputs["Subsurface Radius"].default_value = (0.9, 0.95, 1.0)
    m["roblox_material"] = rbx
    m["roblox_color"] = list(col)
    return m


def _detail_nodes(nt, bsdf, mix, rbx, lin):
    """Preview-only surface detail approximating Roblox's textured materials."""
    if rbx not in ("Rock", "Slate", "Snow", "Wood", "WoodPlanks", "Cobblestone", "Glacier", "Ice"):
        return
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    nt.links.new(geo.outputs["Position"], noise.inputs["Vector"])
    bump = nt.nodes.new("ShaderNodeBump")
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    mul = nt.nodes.new("ShaderNodeMix")
    mul.data_type = "RGBA"
    mul.blend_type = "MULTIPLY"
    mul.inputs["Factor"].default_value = 1.0
    nt.links.new(mix.outputs["Result"], mul.inputs["A"])
    nt.links.new(ramp.outputs["Color"], mul.inputs["B"])
    nt.links.new(mul.outputs["Result"], bsdf.inputs["Base Color"])
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    el = ramp.color_ramp.elements
    if rbx in ("Rock", "Slate"):
        noise.inputs["Scale"].default_value = 0.35
        noise.inputs["Detail"].default_value = 8.0
        noise.inputs["Roughness"].default_value = 0.65
        el[0].position, el[0].color = 0.3, (0.55, 0.55, 0.58, 1)
        el[1].position, el[1].color = 0.75, (1.25, 1.22, 1.2, 1)
        bump.inputs["Strength"].default_value = 0.6
        bump.inputs["Distance"].default_value = 0.6
    elif rbx == "Snow":
        noise.inputs["Scale"].default_value = 0.6
        noise.inputs["Detail"].default_value = 4.0
        el[0].position, el[0].color = 0.35, (0.93, 0.95, 0.99, 1)
        el[1].position, el[1].color = 0.7, (1.0, 1.0, 1.0, 1)
        bump.inputs["Strength"].default_value = 0.12
        bump.inputs["Distance"].default_value = 0.3
    elif rbx in ("Wood", "WoodPlanks"):
        noise.inputs["Scale"].default_value = 3.0
        noise.inputs["Detail"].default_value = 3.0
        el[0].position, el[0].color = 0.4, (0.8, 0.8, 0.8, 1)
        el[1].position, el[1].color = 0.6, (1.1, 1.1, 1.1, 1)
        bump.inputs["Strength"].default_value = 0.2
    elif rbx == "Cobblestone":
        noise.inputs["Scale"].default_value = 2.0
        el[0].position, el[0].color = 0.4, (0.7, 0.7, 0.7, 1)
        el[1].position, el[1].color = 0.6, (1.1, 1.1, 1.1, 1)
        bump.inputs["Strength"].default_value = 0.5
    else:  # ice
        noise.inputs["Scale"].default_value = 0.8
        el[0].position, el[0].color = 0.3, (0.85, 0.92, 1.0, 1)
        el[1].position, el[1].color = 0.7, (1.1, 1.1, 1.1, 1)
        bump.inputs["Strength"].default_value = 0.15


# ---------------------------------------------------------------------------
# meshes
# ---------------------------------------------------------------------------

def mesh_from_arrays(name, verts, tris, loop_uvs=None, colors=None, smooth=True,
                     sharp_angle=None, material=None):
    me = bpy.data.meshes.new(name)
    verts = np.asarray(verts, dtype=np.float32).reshape(-1, 3)
    tris = np.asarray(tris, dtype=np.int32).reshape(-1, 3)
    me.vertices.add(len(verts))
    me.vertices.foreach_set("co", verts.ravel())
    me.loops.add(len(tris) * 3)
    me.loops.foreach_set("vertex_index", tris.ravel())
    me.polygons.add(len(tris))
    me.polygons.foreach_set("loop_start", np.arange(0, len(tris) * 3, 3, dtype=np.int32))
    me.polygons.foreach_set("loop_total", np.full(len(tris), 3, dtype=np.int32))
    me.update(calc_edges=True)
    if loop_uvs is not None and len(tris):
        uvl = me.uv_layers.new(name="UVMap")
        uvl.data.foreach_set("uv", np.asarray(loop_uvs, dtype=np.float32).ravel())
    if len(verts):
        if colors is None:
            colors = np.ones((len(verts), 4), dtype=np.float32)
        ca = me.color_attributes.new(name="Col", type="FLOAT_COLOR", domain="POINT")
        ca.data.foreach_set("color", np.asarray(colors, dtype=np.float32).ravel())
    if smooth:
        me.shade_smooth()
        if sharp_angle is not None:
            try:
                me.set_sharp_from_angle(angle=math.radians(sharp_angle))
            except Exception:
                pass
    else:
        me.shade_flat()
    if material is not None:
        me.materials.append(get_material(material))
    me.validate(clean_customdata=False)
    return me


def new_object(name, me, collection, location=(0, 0, 0), matrix=None):
    ob = bpy.data.objects.new(name, me)
    if matrix is not None:
        ob.matrix_world = matrix
    else:
        ob.location = location
    collection.objects.link(ob)
    return ob


def builder_objects(builder, prefix, collection, origin=(0, 0, 0), world_uv=False,
                    sharp_angle=40.0, tag=None):
    """Create one object per material part. Geometry is stored relative to
    `origin`; the object's location is `origin`."""
    objs = []
    org = np.asarray(origin, dtype=float)
    for mat in sorted(builder.parts):
        p = builder.parts[mat]
        if not p.verts:
            continue
        verts, tris, uvs, cols = part_arrays(p, world_uv_offset=(0, 0, 0) if world_uv else -org * 0)
        if len(tris) == 0:
            continue
        name = "%s_%s" % (prefix, mat.replace("SV_", ""))
        me = mesh_from_arrays(name, verts - org, tris, uvs, cols, smooth=p.smooth,
                              sharp_angle=None if p.smooth and sharp_angle is None else sharp_angle,
                              material=mat)
        ob = new_object(name, me, collection, location=tuple(org))
        ob["sv_material"] = mat
        if tag:
            for k, v in tag.items():
                ob[k] = v
        objs.append(ob)
    return objs


def instance_parts(template_objs, name, matrix_world, collection, tag=None):
    """Linked duplicates (shared mesh data) of all parts of a template."""
    out = []
    for t in template_objs:
        suffix = t.name.split("__", 1)[-1] if "__" in t.name else t["sv_material"].replace("SV_", "")
        ob = bpy.data.objects.new("%s_%s" % (name, suffix), t.data)
        ob.matrix_world = matrix_world
        collection.objects.link(ob)
        ob["sv_material"] = t["sv_material"]
        if tag:
            for k, v in tag.items():
                ob[k] = v
        out.append(ob)
    return out


def matrix_trs(loc, rot_z=0.0, scale=1.0, tilt=(0.0, 0.0)):
    m = Matrix.Translation(Vector(loc)) @ Matrix.Rotation(rot_z, 4, "Z")
    if tilt[0] or tilt[1]:
        m = m @ Matrix.Rotation(tilt[0], 4, "X") @ Matrix.Rotation(tilt[1], 4, "Y")
    if isinstance(scale, (tuple, list)):
        m = m @ Matrix.Diagonal((scale[0], scale[1], scale[2], 1.0))
    else:
        m = m @ Matrix.Scale(scale, 4)
    return m
