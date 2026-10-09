"""Roblox export: FBX asset packs + JSON metadata.

Coordinate contract (verified by parsing the written FBX files):
    Roblox (X, Y, Z) [studs] = (x, z, -y) [Blender meters] * STUDS_PER_METER
    FBX export: axis_forward=-Z, axis_up=Y, bake_space_transform,
                global_scale=STUDS_PER_METER, FBX_SCALE_UNITS
        -> raw vertex values are studs, Y-up, every object has an identity
           transform and its geometry centred on its own pivot.

Placement never relies on where Roblox drops an imported mesh. Every part
is positioned from this manifest by the CFrame of its bounding-box centre
(which is how Roblox defines a MeshPart's position) and its expected Size
is stored so the Roblox importer can verify scale/axes after import.
"""

import json
import math
import os

import numpy as np

from . import config, materials, routes

K = config.STUDS_PER_METER
C = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]])   # Blender -> Roblox axes


def to_rbx(p):
    p = np.asarray(p, dtype=float)
    return (C @ p.T).T * K if p.ndim == 2 else (C @ p) * K


def rot_to_rbx(R):
    return C @ np.asarray(R, dtype=float) @ C.T


def quat_from_matrix(R):
    """(x, y, z, w) from a proper rotation matrix (column vectors = axes)."""
    m = np.asarray(R, dtype=float)
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        w = 0.25 * s
        x = (m[2, 1] - m[1, 2]) / s
        y = (m[0, 2] - m[2, 0]) / s
        z = (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        w = (m[2, 1] - m[1, 2]) / s
        x = 0.25 * s
        y = (m[0, 1] + m[1, 0]) / s
        z = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        w = (m[0, 2] - m[2, 0]) / s
        x = (m[0, 1] + m[1, 0]) / s
        y = 0.25 * s
        z = (m[1, 2] + m[2, 1]) / s
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        w = (m[1, 0] - m[0, 1]) / s
        x = (m[0, 2] + m[2, 0]) / s
        y = (m[1, 2] + m[2, 1]) / s
        z = 0.25 * s
    q = np.array([x, y, z, w])
    q /= np.linalg.norm(q)
    if q[3] < 0:
        q = -q
    return q


def rz(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])


def rx(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def ry(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def inst_rotation(rec):
    tx, ty = rec.get("tilt", (0.0, 0.0))
    return rz(rec["yaw"]) @ rx(tx) @ ry(ty)


def r3(v, nd=3):
    return [round(float(x), nd) for x in v]


def frame_quat(back_b, up_hint=(0, 0, 1)):
    """Rotation with local +Z (back) along back_b (Blender vector), +Y up.
    Returned as a Roblox-axis quaternion."""
    b = np.asarray(back_b, dtype=float)
    b /= np.linalg.norm(b)
    u = np.asarray(up_hint, dtype=float)
    u = u - b * np.dot(u, b)
    u /= np.linalg.norm(u)
    rgt = np.cross(u, b)
    # Roblox basis: columns right(X), up(Y), back(Z) expressed in Roblox axes
    Rr = np.column_stack([C @ rgt, C @ u, C @ b])
    if np.linalg.det(Rr) < 0:
        Rr[:, 0] = -Rr[:, 0]
    return quat_from_matrix(Rr)


# ---------------------------------------------------------------------------
# metadata assembly
# ---------------------------------------------------------------------------

PROBE_DIR = np.array([1.0, 2.13, 3.71])   # skewed direction: unique extreme vertex


def mesh_local_bounds(obj, with_probe=False):
    """Bounding-box centre + size of an object's mesh in Roblox studs/axes.
    with_probe also returns the vertex that maximises PROBE_DIR . v relative
    to the centre: an asymmetric landmark the Roblox importer compares with
    the imported mesh to detect rotated / mirrored imports."""
    import bpy  # noqa: F401
    n = len(obj.data.vertices)
    co = np.empty(n * 3, dtype=np.float32)
    obj.data.vertices.foreach_get("co", co)
    v = co.reshape(-1, 3).astype(float)
    vr = to_rbx(v)
    lo, hi = vr.min(axis=0), vr.max(axis=0)
    c = 0.5 * (lo + hi)
    if with_probe:
        return c, hi - lo, vr[int(np.argmax(vr @ PROBE_DIR))] - c
    return c, hi - lo


TEMPLATE_FILE = {
    "Forest": "Forest/SV_Trees.fbx", "Rocks": "Rocks/SV_Rocks.fbx", "Buildings": "Buildings/SV_Buildings.fbx",
    "Gondola": "Gondola/SV_Gondola.fbx", "Props": "Props/SV_Props.fbx", "Start": "Props/SV_StartFinish.fbx",
    "Finish": "Props/SV_StartFinish.fbx", "Bridges": "Bridges/SV_Bridges.fbx",
    "Environment": "Environment/SV_IceProps.fbx",
}
UNIQUE_FILE = {
    "Terrain": "Terrain/SV_Terrain.fbx", "TerrainFar": "Terrain/SV_TerrainFar.fbx", "Pistes": "Pistes/SV_Pistes.fbx",
    "ForestCanopy": "Forest/SV_ForestCanopy.fbx", "Bridges": "Bridges/SV_Bridges.fbx",
    "IceCave": "Environment/SV_IceCave.fbx", "Environment": "Environment/SV_FrozenLake.fbx",
    "Finish": "Props/SV_StartFinish.fbx",
}
STREAM_GROUP = {"Terrain": "Terrain", "TerrainFar": "Backdrop", "Pistes": "Pistes", "ForestCanopy": "Forest",
                "Forest": "Forest", "Rocks": "Rocks", "Buildings": "Village", "Gondola": "Gondola",
                "Props": "Props", "Start": "Start", "Finish": "Finish", "Bridges": "Bridges",
                "Environment": "Environment", "IceCave": "IceCave"}


def build_manifest(ctx):
    import bpy  # noqa: F401
    templates = {}
    for name, objs in ctx.templates.items():
        info = ctx.template_info[name]
        parts = []
        for o in objs:
            c, sz, pr = mesh_local_bounds(o, with_probe=True)
            mat = o["sv_material"]
            parts.append(dict(mesh=o.name, material=mat, roblox=materials.roblox_info(mat),
                              offset=r3(c), size=r3(sz), probe=r3(pr), tris=len(o.data.polygons)))
        templates[name] = dict(category=info["category"], file=TEMPLATE_FILE[info["category"]],
                               parts=parts, tris=info["tris"])
    asset_index = {name: i for i, name in enumerate(sorted(templates))}
    instances = []
    animated = 0
    for rec in ctx.instances:
        if rec.get("animated"):
            animated += 1
            continue
        R = inst_rotation(rec)
        q = quat_from_matrix(rot_to_rbx(R))
        p = to_rbx(rec["loc"])
        sc = rec["scale"]
        instances.append([asset_index[rec["asset"]], *r3(p, 2), *[round(float(v), 5) for v in q],
                          round(float(sc), 4), rec["collide"], STREAM_GROUP.get(rec["category"], "Props")])
    uniques = []
    for u in ctx.unique:
        o = u["obj"]
        c_local, sz, pr = mesh_local_bounds(o, with_probe=True)
        center_world = to_rbx(np.array(o.location)) + c_local
        uniques.append(dict(mesh=o.name, category=u["category"], file=UNIQUE_FILE[u["category"]],
                            material=u["material"], roblox=materials.roblox_info(u["material"]),
                            position=r3(center_world, 2), size=r3(sz), probe=r3(pr), tris=u["tris"],
                            collide="None" if u["category"] not in ("Bridges", "Finish") else "Visual",
                            group=STREAM_GROUP.get(u["category"], "Props")))
    lights = _lights(ctx)
    texts = _texts(ctx)
    return dict(
        version=__import__("sv").GENERATOR_VERSION,
        units=dict(studs_per_meter=K, axes="Roblox (X, Y up, Z) = Blender (x, z, -y) * studs_per_meter",
                   instance_format=["asset", "px", "py", "pz", "qx", "qy", "qz", "qw", "scale", "collide", "group"]),
        assets=sorted(templates), templates=templates, instances=instances, unique=uniques,
        lights=lights, texts=texts, counts=dict(templates=len(templates), instances=len(instances),
                                                unique=len(uniques), animated_cabins=animated))


def _lights(ctx):
    out = []
    for rec in ctx.instances:
        if rec.get("light") and rec["asset"] == "Lamp":
            R = inst_rotation(rec)
            p = np.asarray(rec["loc"]) + R @ np.array([0.6, 0.0, 3.75]) * rec["scale"]
            out.append(dict(kind="Lamp", position=r3(to_rbx(p), 2), color=[255, 196, 130], range=34,
                            brightness=1.6, shadows=False))
    for lt in ctx.markers.get("cave", {}).get("lights", []):
        out.append(dict(kind="Cave", position=r3(to_rbx(lt["pos"]), 2), color=list(lt["color"]),
                        range=round(lt["range"] * K * 0.5, 1), brightness=lt["brightness"], shadows=False))
    for lt in ctx.markers.get("bridge", {}).get("lights", []):
        out.append(dict(kind="BridgeIce", position=r3(to_rbx(lt["pos"]), 2), color=list(lt["color"]),
                        range=round(lt["range"] * K * 0.5, 1), brightness=lt["brightness"], shadows=False))
    for rec in ctx.instances:
        if rec["asset"] == "XmasTree":
            out.append(dict(kind="Plaza", position=r3(to_rbx(np.asarray(rec["loc"]) + np.array([0, 0, 7.0])), 2),
                            color=[255, 210, 150], range=60, brightness=1.8, shadows=False))
    return out


def _board(rec, local_center, local_normal, size_m):
    R = inst_rotation(rec)
    sc = rec["scale"]
    p = np.asarray(rec["loc"]) + R @ (np.asarray(local_center, dtype=float) * sc)
    n = R @ np.asarray(local_normal, dtype=float)
    q = frame_quat(-n)   # Roblox Front face (-Z) looks along n
    return dict(position=r3(to_rbx(p), 2), rotation=[round(float(v), 5) for v in q],
                size=r3(np.asarray(size_m) * K * sc, 2))


def _texts(ctx):
    out = []
    from . import layout
    for rec in ctx.instances:
        a = rec["asset"]
        if a == "SectionSign" and rec.get("sign"):
            sg = rec["sign"]
            b = _board(rec, (0, 0.16, 3.1), (0, 1, 0), (3.3, 2.1))
            b.update(kind="Section", lines=["%02d" % sg["id"], sg["name"].upper()],
                     badge=list(layout.LEGEND[sg["legend"]]))
            out.append(b)
        elif a == "JunctionSign" and rec.get("sign"):
            sg = rec["sign"]
            b = _board(rec, (0.0, 0.16, 3.3), (0, 1, 0), (1.9, 0.5))
            b.update(kind="Junction", lines=[sg["name"].upper()],
                     badge=list(materials.MATERIALS[materials.DIFFICULTY_PAINT[sg["difficulty"]]][1]))
            out.append(b)
        elif a == "StartGate":
            for nrm, y in ((1, 0.3), (-1, -0.3)):
                b = _board(rec, (0, y, 8.0 - 1.2), (0, nrm, 0), (32.0, 1.6))
                b.update(kind="Banner", lines=["AVALANCHE RIDERS"], badge=[200, 38, 38])
                out.append(b)
            b = _board(rec, (0, 0.22, 9.0), (0, 1, 0), (7.4, 1.6))
            b.update(kind="Title", lines=["START"], badge=[200, 38, 38])
            out.append(b)
            b = _board(rec, (0, -0.22, 9.0), (0, -1, 0), (7.4, 1.6))
            b.update(kind="Title", lines=["SUMMIT"], badge=[200, 38, 38])
            out.append(b)
        elif a == "FinishArch":
            for nrm in (1, -1):
                b = _board(rec, (0, 0.17 * nrm, 11.6), (0, nrm, 0), (17.6, 2.8))
                b.update(kind="Banner", lines=["FINISH", "VALLEY PLAZA"], badge=[36, 92, 190])
                out.append(b)
        elif a in ("StationTop", "StationMid", "StationValley"):
            from .assets_buildings import STATION_VARIANTS
            p = STATION_VARIANTS[a]
            b = _board(rec, (0, p["d"] / 2 + 0.06, 1.5 + p["h"] + 0.2), (0, 1, 0), (p["w"] * 0.48, 1.3))
            b.update(kind="Title", lines=["GONDOLA"], badge=[24, 44, 78])
            out.append(b)
        elif a in ("Lodge", "Restaurant", "Shop", "SkiService"):
            from .assets_buildings import BUILDING_VARIANTS
            p = BUILDING_VARIANTS[a]
            label = {"Lodge": "ALPINE LODGE", "Restaurant": "RESTAURANT", "Shop": "SKI SHOP",
                     "SkiService": "SKI SERVICE"}[a]
            b = _board(rec, (0, p["d"] / 2 + 0.19, p.get("base_h", 1.1) + 2.85), (0, 1, 0),
                       (min(p["w"] - 1.0, 5.0) - 0.2, 0.7))
            b.update(kind="Shop", lines=[label], badge=[24, 44, 78])
            out.append(b)
    return out


# ---------------------------------------------------------------------------
# gameplay + routes + collision + gondola
# ---------------------------------------------------------------------------

def build_checkpoints(ctx):
    net = ctx.net
    groups = {}
    for r in net.routes:
        for g in r.gates:
            s = g["s"]
            p = r.point(s)
            t = r.tangent(s)
            W = float(r.interp("width", s))
            ml = float(r.interp("margin_l", s))
            mr = float(r.interp("margin_r", s))
            z = float(r.interp("z", s))
            center = np.array([p[0], p[1], z + 5.0])
            q = frame_quat((-t[0], -t[1], 0.0))     # look vector (-Z) = travel direction
            width = W + ml + mr + 8.0
            gid = "CP%02d_%s" % (g["group"], r.id)
            entry = dict(id=gid, group=g["group"], route=r.id, station_m=round(s, 2),
                         progress_m=round(g["progress"], 2), progress_studs=round(g["progress"] * K, 1),
                         position=r3(to_rbx(center), 2), rotation=[round(float(v), 5) for v in q],
                         size=r3([width * K, 13.0 * K, 4.0 * K], 1),
                         is_finish=(g["group"] == 18 and r.id == "MAIN"),
                         is_start=(g["group"] == 1 and r.id == "MAIN"),
                         section=next((d["name"] for d in net.main.sections if d["id"] == g["group"]), ""))
            groups.setdefault(g["group"], []).append(entry)
    out = []
    for k in sorted(groups):
        out.append(dict(group=k, name=next(d["name"] for d in net.main.sections if d["id"] == k),
                        gates=groups[k]))
    spawns = []
    for sp in ctx.markers.get("spawns", []):
        q = frame_quat((-sp["dir"][0], -sp["dir"][1], 0.0))
        spawns.append(dict(position=r3(to_rbx(np.asarray(sp["pos"]) + np.array([0, 0, 1.2])), 2),
                           rotation=[round(float(v), 5) for v in q]))
    boosts = []
    m = net.main
    sec = {d["id"]: d for d in m.sections}
    br = ctx.T.features["bridge"]
    tun = ctx.T.features["tunnel"]
    boost_s = [70.0, br["s1"] + 25.0, tun["s1"] + 20.0, sec[15]["s0"] + 30.0, sec[16]["s0"] + 25.0]
    for s in boost_s:
        p = m.point(s)
        t = m.tangent(s)
        W = float(m.interp("width", s))
        center = np.array([p[0], p[1], float(m.interp("z", s)) + 1.5])
        q = frame_quat((-t[0], -t[1], 0.0))
        boosts.append(dict(id="BOOST_%04d" % int(s), station_m=round(s, 1),
                           position=r3(to_rbx(center), 2), rotation=[round(float(v), 5) for v in q],
                           size=r3([W * 0.55 * K, 4.0 * K, 9.0 * K], 1),
                           direction=r3(C @ np.array([t[0], t[1], 0.0])), strength=1.0))
    return dict(groups=out, spawns=spawns, boosts=boosts, group_count=len(out),
                finish_group=18, rule="Pass any gate of group N after group N-1. Equivalent gates on "
                                      "alternatives share the group number; skipping a group is invalid.")


def build_route_data(ctx):
    net = ctx.net
    out = []
    for r in net.routes:
        step = 4
        idx = np.arange(0, len(r.s), step)
        if idx[-1] != len(r.s) - 1:
            idx = np.append(idx, len(r.s) - 1)
        pts = np.column_stack([r.x[idx], r.y[idx], r.z[idx]])
        rb = to_rbx(pts)
        prog = r.progress[idx] if hasattr(r, "progress") else r.s[idx]
        samples = []
        for k, i in enumerate(idx):
            samples.append([*r3(rb[k], 2), round(float(r.s[i]), 2), round(float(prog[k]), 2),
                            round(float(r.width[i] / 2 * K), 2),
                            round(float(r.margin_l[i] * K), 2), round(float(r.margin_r[i] * K), 2),
                            int(r.surface[i]), int(r.section[i])])
        out.append(dict(id=r.id, name=r.name, difficulty=r.difficulty, kind=r.kind,
                        length_m=round(r.length, 2),
                        race_length_m=round(r.race_end_s, 2) if r.kind == "main" else None,
                        branch_main_m=None if r.kind == "main" else round(r.branch_s, 2),
                        merge_main_m=None if r.kind == "main" else round(r.merge_s, 2),
                        sample_format=["x", "y", "z", "s_m", "progress_m", "halfwidth", "margin_l",
                                       "margin_r", "surface", "section"],
                        samples=samples))
    m = net.main
    sections = [dict(id=d["id"], name=d["name"], legend=d["legend"], character=d["character"],
                     start_m=round(d["s0"], 2), end_m=round(d["s1"], 2), width_m=d["width"],
                     drop_m=round(float(m.interp("z", d["s0"]) - m.interp("z", d["s1"])), 2))
                for d in m.sections]
    return dict(units=dict(studs_per_meter=K), routes=out, sections=sections,
                main=dict(race_length_m=round(m.race_end_s, 2), drop_m=round(float(m.z[0] - m.interp("z", m.race_end_s)), 2)))


def build_collision_data(ctx, col):
    strips = []
    for rid, sl in col["strips"].items():
        for rows in sl:
            strips.append(dict(route=rid, surface=rows[0]["surface"], kinds=rows[0]["kinds"],
                               rows=[[*np.round(to_rbx(rw["pts"]), 3).ravel().tolist()] for rw in rows]))
    boxes = []
    for b in col["boxes"]:
        h = b["yaw"]
        back = np.array([math.cos(h), math.sin(h), math.tan(b["pitch"]) * -1.0])
        back = np.array([math.cos(h) * math.cos(b["pitch"]), math.sin(h) * math.cos(b["pitch"]),
                         math.sin(b["pitch"])])
        q = frame_quat(back)
        sz = b["size"]
        boxes.append(dict(kind=b["kind"], position=r3(to_rbx(b["center"]), 2),
                          rotation=[round(float(v), 5) for v in q], size=r3(np.asarray(sz) * K, 2)))
    for b in col["catch"]:
        boxes.append(dict(kind="CatchFloor", position=r3(to_rbx(b["center"]), 2), rotation=[0, 0, 0, 1],
                          size=r3([b["size"][0] * K, b["size"][1] * K, b["size"][2] * K], 1)))
    patches = []
    for p in col["patches"]:
        z = np.asarray(p["z"])
        ny, nx = z.shape
        pts = []
        for j in range(ny):
            for i in range(nx):
                pts.append(to_rbx([p["x0"] + i * p["step"], p["y0"] + j * p["step"], z[j, i]]))
        patches.append(dict(name=p["name"], nx=nx, ny=ny, points=np.round(np.asarray(pts), 3).ravel().tolist(),
                            mask=[int(v) for v in np.asarray(p["mask"]).ravel()]))
    kickers = []
    for kk in col["kickers"]:
        Rb = np.column_stack([kk["right"], kk["up"], kk["back"]])
        Rr = rot_to_rbx(Rb)
        if np.linalg.det(Rr) < 0:
            Rr[:, 0] = -Rr[:, 0]
        q = quat_from_matrix(Rr)
        kickers.append(dict(position=r3(to_rbx(kk["center"]), 2), rotation=[round(float(v), 5) for v in q],
                            size=r3(np.asarray(kk["size"]) * K, 2)))
    return dict(units=dict(studs_per_meter=K),
                note="Strip rows hold lateral surface points (x,y,z studs) left->right; each quad between "
                     "consecutive rows = triangles (A[c],B[c],B[c+1]) and (A[c],B[c+1],A[c+1]).",
                strips=strips, boxes=boxes, patches=patches, kickers=kickers)


def build_gondola_data(ctx):
    out = []
    for ln in ctx.markers.get("gondolas", []):
        pts = to_rbx(np.asarray(ln["loop"]["points"]))
        out.append(dict(id=ln["id"], name=ln["name"], speed_studs=round(ln["speed"] * K, 2),
                        spacing_studs=round(ln["spacing"] * K, 2), cabin_template="Cabin",
                        hang_studs=round(ln["hang"] * K, 2), gauge_studs=round(ln["gauge"] * K, 2),
                        loop_length_studs=round(ln["loop"]["length"] * K, 1),
                        path=np.round(pts, 2).ravel().tolist(),
                        stations=[dict(asset=s["asset"], position=r3(to_rbx([s["xy"][0], s["xy"][1], s["ground"]]), 2),
                                       cable_y=round(s["cable_z"] * K, 2)) for s in ln["stations"]],
                        pylons=[dict(asset=p["asset"], position=r3(to_rbx(p["pos"]), 2),
                                     cable_y=round(p["cable_z"] * K, 2)) for p in ln["pylons"]],
                        passenger_transport=False,
                        note="Visual + animation-ready. Cabins follow the closed loop path at constant speed; "
                             "boarding/passenger transport is not implemented in this phase."))
    return dict(lines=out)


ENVIRONMENT = dict(
    name="SnowyValley",
    lighting=dict(ClockTime=16.4, GeographicLatitude=46.5, Brightness=3.0, ExposureCompensation=0.15,
                  EnvironmentDiffuseScale=1.0, EnvironmentSpecularScale=0.8, Ambient=[86, 94, 120],
                  OutdoorAmbient=[146, 158, 190], ColorShift_Top=[255, 220, 186], ColorShift_Bottom=[120, 140, 190],
                  ShadowSoftness=0.25, GlobalShadows=True, FogColor=[196, 212, 236], FogStart=0, FogEnd=100000),
    atmosphere=dict(Density=0.34, Offset=0.22, Color=[202, 216, 240], Decay=[118, 140, 196], Glare=0.35, Haze=1.9),
    sky=dict(SunAngularSize=14, MoonAngularSize=11, StarCount=0, CelestialBodiesShown=True),
    clouds=dict(Cover=0.5, Density=0.55, Color=[255, 238, 226]),
    bloom=dict(Intensity=0.55, Size=28, Threshold=1.4),
    color_correction=dict(Brightness=0.02, Contrast=0.08, Saturation=0.12, TintColor=[255, 248, 240]),
    sun_rays=dict(Intensity=0.05, Spread=0.6),
    notes="Apply through the existing WorldEnvironmentController when Snowy Valley is active; "
          "revert to the controller's defaults for other worlds.",
)


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    return os.path.getsize(path)


# ---------------------------------------------------------------------------
# FBX export
# ---------------------------------------------------------------------------

def export_fbx(objs, path, log):
    import bpy
    os.makedirs(os.path.dirname(path), exist_ok=True)
    saved = []
    for o in objs:
        saved.append((o, o.matrix_world.copy(), o.hide_viewport, o.hide_get()))
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.hide_viewport = False
        o.hide_set(False)
        o.matrix_world = __import__("mathutils").Matrix.Identity(4)
        o.select_set(True)
    bpy.context.view_layer.update()
    bpy.ops.export_scene.fbx(filepath=path, use_selection=True, object_types={"MESH"},
                             use_mesh_modifiers=True, mesh_smooth_type="FACE", use_triangles=True,
                             add_leaf_bones=False, axis_forward="-Z", axis_up="Y",
                             global_scale=K, apply_unit_scale=True, apply_scale_options="FBX_SCALE_UNITS",
                             bake_space_transform=True, path_mode="COPY", embed_textures=True,
                             colors_type="SRGB", use_custom_props=False, bake_anim=False)
    for o, M, hv, hs in saved:
        o.matrix_world = M
        o.hide_viewport = hv
        o.hide_set(hs)
    bpy.ops.object.select_all(action="DESELECT")
    size = os.path.getsize(path)
    log("  FBX %-40s %4d objects %7.1f MB" % (os.path.relpath(path, config.EXPORT_DIR), len(objs), size / 1e6))
    return size


def export_all_fbx(ctx):
    import bpy
    vl = bpy.context.view_layer
    for lc in vl.layer_collection.children["SNOWY_VALLEY_ROOT"].children:
        lc.exclude = False
    groups = {}
    for name, objs in ctx.templates.items():
        f = TEMPLATE_FILE[ctx.template_info[name]["category"]]
        groups.setdefault(f, []).extend(objs)
    for u in ctx.unique:
        groups.setdefault(UNIQUE_FILE[u["category"]], []).append(u["obj"])
    total = 0
    files = {}
    for f, objs in sorted(groups.items()):
        path = os.path.join(config.EXPORT_DIR, f)
        total += export_fbx(objs, path, ctx.log)
        files[f] = dict(objects=len(objs), bytes=os.path.getsize(path))
    ctx.stats["fbx_files"] = files
    ctx.log("FBX total %.1f MB in %d files" % (total / 1e6, len(groups)))
    return files
