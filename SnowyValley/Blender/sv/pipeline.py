"""Generator pipeline: builds the complete Snowy Valley scene in Blender."""

import math
import os
import time

import bpy
import numpy as np

from . import bl, config, materials, ribbons, routes, terrain, terrain_mesh
from .mathutil import NoiseBank


class Context:
    """Shared state between pipeline stages."""

    def __init__(self, quick=False):
        self.quick = quick
        self.t0 = time.time()
        self.log_lines = []
        self.net = None
        self.T = None
        self.nb = NoiseBank(config.SEED + 17)
        self.templates = {}       # asset id -> list of template objects
        self.template_info = {}   # asset id -> dict(category, parts, notes)
        self.instances = []       # placement records for the manifest
        self.unique = []          # unique world meshes (terrain, ribbons, bridge, ...)
        self.markers = {}         # gameplay metadata
        self.stats = {}

    def log(self, msg):
        line = "[%7.1fs] %s" % (time.time() - self.t0, msg)
        print(line, flush=True)
        self.log_lines.append(line)


# ---------------------------------------------------------------------------

def stage_network(ctx):
    ctx.net = routes.Network()
    for line in routes.summarize(ctx.net).splitlines():
        ctx.log(line)


def stage_terrain(ctx):
    ctx.T = terrain.build_terrain(ctx.net, quick=ctx.quick)
    ctx.log("terrain grid %dx%d @ %.1f m" % (ctx.T.nx, ctx.T.ny, ctx.T.res))


def _emit_chunk(ctx, ch, collection, category):
    created = []
    for is_rock, mat in ((False, "SV_Snow"), (True, "SV_Rock")):
        sel_all = np.where(ch.rock_mask == is_rock)[0]
        if len(sel_all) == 0:
            continue
        bands = terrain_mesh.band_split(ch.verts, ch.tris[sel_all])
        for bi, band in enumerate(bands):
            suffix = "" if len(bands) == 1 else "_b%d" % bi
            created += _emit_tris(ctx, ch, ch.tris[sel_all[band]], mat, is_rock, suffix,
                                  collection, category)
    return created


def _emit_tris(ctx, ch, tris, mat, is_rock, suffix, collection, category):
    created = []
    if True:
        used = np.unique(tris)
        remap = -np.ones(len(ch.verts), dtype=np.int64)
        remap[used] = np.arange(len(used))
        v = ch.verts[used]
        t = remap[tris]
        n = ch.normals[used]
        uv = ch.verts[t.reshape(-1)][:, :2] / 8.0
        col = ch.colors[used]
        lo, hi = v.min(axis=0), v.max(axis=0)
        center = 0.5 * (lo + hi)
        name = "%s_%s%s" % (ch.name, "Rock" if is_rock else "Snow", suffix)
        me = bl.mesh_from_arrays(name, v - center, t, uv, col, smooth=True, material=mat)
        me.normals_split_custom_set_from_vertices([tuple(x) for x in n])
        ob = bl.new_object(name, me, collection, location=tuple(center))
        ob["sv_material"] = mat
        ob["sv_category"] = category
        created.append(ob)
        ctx.unique.append(dict(name=name, category=category, material=mat, obj=ob,
                               tris=int(len(t))))
    return created


def stage_terrain_meshes(ctx):
    T = ctx.T
    plan = terrain_mesh.split_if_tall(T, terrain_mesh.plan_detail_chunks(T))
    col = bl.coll("TERRAIN_VISUAL")
    tri_total = 0
    for name, x0, y0, x1, y1, res in plan:
        ch = terrain_mesh.build_chunk(T, name, x0, y0, x1, y1, res, ctx.nb)
        objs = _emit_chunk(ctx, ch, col, "Terrain")
        tri_total += sum(len(o.data.polygons) for o in objs)
    ctx.log("terrain detail chunks: %d plans, %d tris" % (len(plan), tri_total))
    plan = terrain_mesh.split_if_tall(T, terrain_mesh.plan_far_chunks(T))
    col = bl.coll("TERRAIN_FAR")
    tri_total = 0
    for name, x0, y0, x1, y1, res in plan:
        ch = terrain_mesh.build_chunk(T, name, x0, y0, x1, y1, res, ctx.nb, skirt=18.0)
        objs = _emit_chunk(ctx, ch, col, "TerrainFar")
        tri_total += sum(len(o.data.polygons) for o in objs)
    ctx.log("terrain far chunks: %d plans, %d tris" % (len(plan), tri_total))


def stage_ribbons(ctx):
    T, net = ctx.T, ctx.net
    col = bl.coll("PISTES_VISUAL")
    total = 0
    for r in net.routes:
        for ch in ribbons.build_route_ribbon(T, net, r):
            for mat, (v, t, n, uv, c) in ch.parts.items():
                lo, hi = v.min(axis=0), v.max(axis=0)
                center = 0.5 * (lo + hi)
                name = "%s_%s" % (ch.name, mat.replace("SV_", ""))
                me = bl.mesh_from_arrays(name, v - center, t, uv, c, smooth=True, material=mat)
                me.normals_split_custom_set_from_vertices([tuple(x) for x in n])
                ob = bl.new_object(name, me, col, location=tuple(center))
                ob["sv_material"] = mat
                ob["sv_category"] = "Pistes"
                ctx.unique.append(dict(name=name, category="Pistes", material=mat, obj=ob,
                                       tris=int(len(t))))
                total += len(t)
        stripe = ribbons.build_edge_stripes(T, net, r)
        if stripe is not None:
            v, t = stripe
            mat = materials.DIFFICULTY_PAINT[r.difficulty]
            # split long stripe meshes to respect the part size limit
            for k, (vv, tt) in enumerate(_split_by_extent(v, t)):
                lo, hi = vv.min(axis=0), vv.max(axis=0)
                center = 0.5 * (lo + hi)
                name = "SV_STRIPE_%s_%02d" % (r.id, k)
                me = bl.mesh_from_arrays(name, vv - center, tt, None, None, smooth=False,
                                         material=mat)
                ob = bl.new_object(name, me, col, location=tuple(center))
                ob["sv_material"] = mat
                ob["sv_category"] = "Pistes"
                ctx.unique.append(dict(name=name, category="Pistes", material=mat, obj=ob,
                                       tris=int(len(tt))))
    ctx.log("piste ribbons: %d tris" % total)


def _split_by_extent(v, t, max_extent=500.0):
    """Split a triangle soup into pieces whose AABB stays below max_extent m."""
    cen = v[t].mean(axis=1)
    out = []
    order = np.arange(len(t))
    stack = [order]
    while stack:
        idx = stack.pop()
        c = cen[idx]
        ext = c.max(axis=0) - c.min(axis=0)
        if ext.max() > max_extent and len(idx) > 2:
            ax = int(np.argmax(ext))
            med = np.median(c[:, ax])
            a = idx[c[:, ax] <= med]
            b = idx[c[:, ax] > med]
            if len(a) == 0 or len(b) == 0:
                out.append(idx)
                continue
            stack += [a, b]
        else:
            out.append(idx)
    res = []
    for idx in out:
        tt = t[idx]
        used = np.unique(tt)
        remap = -np.ones(len(v), dtype=np.int64)
        remap[used] = np.arange(len(used))
        res.append((v[used], remap[tt]))
    return res


# ---------------------------------------------------------------------------
# preview cameras
# ---------------------------------------------------------------------------

def camera_presets(ctx):
    """name -> (location, target, lens) computed from the generated world."""
    from mathutils import Vector
    T, m = ctx.T, ctx.net.main

    def ground(x, y, up):
        return (x, y, float(T.height(x, y)) + up)

    def on_route(r, s, back=30.0, up=6.0, ahead=60.0, side=0.0):
        se = max(0.0, s - back)
        p = r.point(se)
        rt = r.right(se)
        eye = (p[0] + rt[0] * side, p[1] + rt[1] * side, float(r.interp("z", se)) + up)
        tgt = r.point(min(r.length, s + ahead))
        return eye, (tgt[0], tgt[1], tgt[2] + 2.0)

    cams = {}
    cams["topdown"] = ((40.0, -63.0, 4000.0), (40.0, -62.0, 0.0), dict(ortho=2300.0, res=(1400, 1400)))
    cams["aerial"] = ((-420.0, -2250.0, 1150.0), (40.0, -60.0, 300.0), dict(lens=30.0))
    sec = {d["id"]: d for d in m.sections}
    # summit: from behind the start grid over the start gate down the course
    p0, t0, r0 = m.point(12.0), m.tangent(12.0), m.right(12.0)
    z0 = float(m.interp("z", 12.0))
    eye = (p0[0] - t0[0] * 58.0 + r0[0] * 12.0, p0[1] - t0[1] * 58.0 + r0[1] * 12.0, z0 + 16.0)
    p1 = m.point(110.0)
    cams["summit"] = (eye, (p1[0], p1[1], float(m.interp("z", 110.0)) + 2.0), dict(lens=26.0))
    s4 = 0.5 * (sec[4]["s0"] + sec[4]["s1"])
    loc, tgt = on_route(m, s4, back=35.0, up=3.0, ahead=70.0)
    cams["forest"] = (loc, tgt, dict(lens=28.0))
    br = ctx.T.features["bridge"]
    cams["bridge"] = ((br["x"] - 40.0, br["y"] - 150.0, br["deck_z"] - 8.0),
                      (br["x"], br["y"], br["deck_z"] - 12.0), dict(lens=28.0))
    # bridge from the ravine side, close up (arches + deck)
    bmid = 0.5 * (br_s0 := float(sec[8]["bridge_s"][0])) + 0.5 * float(sec[8]["bridge_s"][1])
    bp, bt, brt = m.point(bmid), m.tangent(bmid), m.right(bmid)
    bz = float(m.interp("z", bmid))
    cams["bridge_side"] = ((bp[0] + brt[0] * 70.0 - bt[0] * 20.0, bp[1] + brt[1] * 70.0 - bt[1] * 20.0, bz - 22.0),
                           (bp[0], bp[1], bz - 18.0), dict(lens=24.0))
    t0, t1 = sec[12]["tunnel_s"]
    loc, tgt = on_route(m, t0 + 25.0, back=20.0, up=2.5, ahead=45.0)
    cams["cave"] = (loc, tgt, dict(lens=24.0))
    pz = ctx.T.features["plaza"]
    cams["village"] = ((pz["x"] + 30.0, pz["y"] + 150.0, pz["z"] + 28.0),
                       (pz["x"], pz["y"] - 30.0, pz["z"] + 3.0), dict(lens=30.0))
    lk = ctx.T.features["lake"]
    cams["lake"] = ((lk["x"] - 160.0, lk["y"] + 70.0, lk["z"] + 45.0),
                    (lk["x"] + 20.0, lk["y"] - 10.0, lk["z"]), dict(lens=30.0))
    s11 = sec[11]["s0"] + 0.55 * (sec[11]["s1"] - sec[11]["s0"])
    loc, tgt = on_route(m, s11, back=25.0, up=4.0, ahead=70.0)
    cams["canyon"] = (loc, tgt, dict(lens=24.0))
    return cams


def stage_render(ctx, names):
    from . import render
    if not names:
        return
    # the asset library sits at the origin: keep it out of renders
    vl = bpy.context.view_layer
    for lc in vl.layer_collection.children["SNOWY_VALLEY_ROOT"].children:
        if lc.name in ("ASSET_LIBRARY", "COLLISION_REFERENCE", "GAMEPLAY_MARKERS"):
            lc.exclude = True
    render.setup_world()
    render.setup_render(res=(1280, 720), samples=24 if ctx.quick else 48)
    presets = camera_presets(ctx)
    for nm in names:
        if nm not in presets:
            ctx.log("unknown camera %s" % nm)
            continue
        loc, tgt, kw = presets[nm]
        res = kw.get("res", (1280, 720))
        bpy.context.scene.render.resolution_x, bpy.context.scene.render.resolution_y = res
        cam = render.camera("CAM_" + nm, loc, tgt, lens=kw.get("lens", 35.0),
                            ortho_scale=kw.get("ortho"))
        path = os.path.join(config.PREVIEW_DIR, "%s.png" % nm)
        render.render_to(cam, path)
        ctx.log("rendered %s" % path)


def stage_assets(ctx):
    from . import placement
    placement.build_templates(ctx)
    ctx.placer = placement.Placer(ctx)


def stage_population(ctx):
    from . import gondola, placement
    P = ctx.placer
    placement.place_unique(ctx, P)
    gondola.build_lines(ctx, P)
    placement.place_start_area(ctx, P)
    placement.place_village(ctx, P)
    placement.place_mountain_buildings(ctx, P)
    placement.place_route_furniture(ctx, P)
    placement.place_kickers(ctx, P)
    placement.place_rocks(ctx, P)
    placement.place_forest(ctx, P)
    ctx.log("instances: %d total; per asset: %s" % (
        len(ctx.instances), ", ".join("%s=%d" % kv for kv in sorted(P.counts.items()))))


def stage_collision(ctx):
    from . import collision
    ctx.collision = collision.CollisionBuilder(ctx.T, ctx.net, ctx.markers).build()
    ctx.log("collision: %d wedges, %d boxes" % (collision.wedge_count(ctx.collision),
                                                 len(ctx.collision["boxes"]) + len(ctx.collision["catch"])))
    _collision_preview(ctx)


def _collision_preview(ctx):
    """Collision surfaces as a (hidden-in-render) mesh for inspection in Blender."""
    from . import collision
    verts, tris = [], []
    for rid, strips in ctx.collision["strips"].items():
        for rows in strips:
            for (a, b, c, kind) in collision.strip_triangles(rows):
                base = len(verts)
                verts += [a, b, c]
                tris.append((base, base + 1, base + 2))
    if not verts:
        return
    v = np.asarray(verts)
    t = np.asarray(tris)
    lo, hi = v.min(axis=0), v.max(axis=0)
    c = 0.5 * (lo + hi)
    me = bl.mesh_from_arrays("SV_COLLISION_Surface", v - c, t, None, None, smooth=False, material="SV_PaintOrange")
    ob = bl.new_object("SV_COLLISION_Surface", me, bl.coll("COLLISION_REFERENCE"), location=tuple(c))
    ob.display_type = "WIRE"


def stage_export(ctx):
    from . import export
    if ctx.opts.get("export", True):
        export.export_all_fbx(ctx)
    man = export.build_manifest(ctx)
    cps = export.build_checkpoints(ctx)
    rd = export.build_route_data(ctx)
    cd = export.build_collision_data(ctx, ctx.collision)
    gd = export.build_gondola_data(ctx)
    md = config.METADATA_DIR
    sizes = {}
    for name, data in (("AssetManifest.json", man), ("Checkpoints.json", cps), ("RouteData.json", rd),
                       ("CollisionData.json", cd), ("GondolaData.json", gd), ("Environment.json", export.ENVIRONMENT)):
        sizes[name] = export.write_json(os.path.join(md, name), data)
    ctx.log("metadata: " + ", ".join("%s %.0f KB" % (k, v / 1024) for k, v in sizes.items()))
    ctx.manifest, ctx.checkpoints = man, cps


def stage_validate(ctx):
    from . import validate
    R = validate.run(ctx, ctx.collision, ctx.manifest, ctx.checkpoints)
    validate.write(R, ctx)
    ctx.report = R


ALL_STAGES = ["network", "terrain", "terrain_meshes", "ribbons", "assets", "population", "collision",
              "export", "validate"]


def run(ctx, opts):
    ctx.opts = opts
    stages = opts.get("stages") or ALL_STAGES
    bl.reset_scene()
    tex_dir = os.path.join(config.EXPORT_DIR, "Textures")
    os.makedirs(tex_dir, exist_ok=True)
    materials.write_palette_png(os.path.join(tex_dir, "SV_TreePalette.png"))
    bl.set_texture_dir(tex_dir)
    for st in ALL_STAGES:
        if st in stages or st in ("network", "terrain"):
            ctx.log("== stage %s" % st)
            globals()["stage_" + st](ctx)
    if opts.get("render"):
        stage_render(ctx, opts["render"])
    if opts.get("save"):
        bpy.ops.wm.save_as_mainfile(filepath=config.BLEND_PATH, compress=True)
        ctx.log("saved %s" % config.BLEND_PATH)
