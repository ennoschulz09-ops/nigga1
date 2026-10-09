"""World population: asset templates + deterministic placement of forests,
rocks, cliffs, village, route furniture, start/finish areas and gondolas.

Every placement is recorded in ctx.instances (asset id + Blender world
transform + flags) - the export stage converts these records into the
Roblox AssetManifest.  Blender gets linked duplicates (shared mesh data).
"""

import math

import numpy as np
from mathutils import Matrix

from . import (assets_buildings, assets_nature, assets_props, assets_unique, bl, config,
               materials, routes)
from .mathutil import NoiseBank, footprint_xy, smoothstep

# category -> Blender collection
CAT_COLL = {
    "Forest": "FOREST", "Rocks": "ROCKS", "Buildings": "BUILDINGS", "Gondola": "GONDOLA",
    "Start": "START_AREA", "Finish": "FINISH_AREA", "Props": "DECORATION", "Bridges": "BRIDGES",
    "Environment": "FROZEN_LAKE", "IceCave": "ICE_CAVE",
}
# footprint shrink per category for corridor / ground checks (rocks are round)
FOOTPRINT_SHRINK = {"Rocks": 0.8, "Buildings": 1.0}
# collision mode per category for Roblox ("None", "Box", "Hull")
CAT_COLLIDE = {"Forest": "None", "Rocks": "Hull", "Buildings": "Box", "Gondola": "Box",
               "Start": "Box", "Finish": "Box", "Props": "None", "Bridges": "Hull",
               "Environment": "None", "IceCave": "None"}


# ---------------------------------------------------------------------------
# templates
# ---------------------------------------------------------------------------

def build_templates(ctx):
    lib = bl.coll("ASSET_LIBRARY")
    builders = {}
    builders.update(assets_nature.all_nature_builders())
    builders.update(assets_buildings.all_building_builders())
    builders.update(assets_props.all_prop_builders())
    for name, (cat, mb) in builders.items():
        objs = bl.builder_objects(mb, "SVA_" + name, lib, origin=(0, 0, 0),
                                  tag={"sv_asset": name, "sv_kind": "template"})
        lo, hi = mb.bounds()
        ctx.templates[name] = objs
        ctx.template_info[name] = dict(category=cat, tris=mb.tri_count(), bounds=(lo.tolist(), hi.tolist()),
                                       parts=[o.name for o in objs])
    ctx.log("asset templates: %d (%d parts)" % (len(builders), sum(len(v) for v in ctx.templates.values())))


class Placer:
    def __init__(self, ctx):
        self.ctx = ctx
        self.T = ctx.T
        self.net = ctx.net
        self.rng = np.random.default_rng(config.SEED + 99)
        self.nb = NoiseBank(config.SEED + 5)
        # occupancy grid (2 m) to keep objects from overlapping
        self.occ_res = 2.0
        self.ox0, self.oy0 = config.DETAIL_MIN_X, config.DETAIL_MIN_Y
        nx = int((config.DETAIL_MAX_X - config.DETAIL_MIN_X) / self.occ_res) + 1
        ny = int((config.DETAIL_MAX_Y - config.DETAIL_MIN_Y) / self.occ_res) + 1
        self.occ = np.zeros((ny, nx), dtype=np.uint8)
        self.counts = {}

    # ------------------------------------------------------------------
    def occupy(self, x, y, r, val=1):
        i0 = int((x - r - self.ox0) / self.occ_res)
        i1 = int((x + r - self.ox0) / self.occ_res) + 1
        j0 = int((y - r - self.oy0) / self.occ_res)
        j1 = int((y + r - self.oy0) / self.occ_res) + 1
        i0, j0 = max(i0, 0), max(j0, 0)
        i1, j1 = min(i1, self.occ.shape[1]), min(j1, self.occ.shape[0])
        if i0 < i1 and j0 < j1:
            sub = self.occ[j0:j1, i0:i1]
            np.maximum(sub, val, out=sub)

    def free(self, x, y, r=0.0):
        i0 = int((x - r - self.ox0) / self.occ_res)
        i1 = int((x + r - self.ox0) / self.occ_res) + 1
        j0 = int((y - r - self.oy0) / self.occ_res)
        j1 = int((y + r - self.oy0) / self.occ_res) + 1
        if i0 < 0 or j0 < 0 or i1 > self.occ.shape[1] or j1 > self.occ.shape[0]:
            return False
        return not np.any(self.occ[j0:j1, i0:i1])

    def footprint(self, asset, x, y, yaw, scale=1.0):
        info = self.ctx.template_info[asset]
        return footprint_xy(info["bounds"], x, y, yaw, scale, FOOTPRINT_SHRINK.get(info["category"], 1.0))

    def clear_of_corridors(self, asset, x, y, yaw, scale=1.0, min_ce=0.0):
        """True if the asset footprint stays min_ce m outside every corridor."""
        fp = self.footprint(asset, x, y, yaw, scale)
        return float(np.min(self.T.corridor_dist(fp[:, 0], fp[:, 1]))) >= min_ce

    def ground_range(self, asset, x, y, yaw, scale=1.0):
        """(centre ground, min, max) terrain height under the footprint."""
        fp = self.footprint(asset, x, y, yaw, scale)
        gz = self.T.height(fp[:, 0], fp[:, 1])
        return float(self.T.height(x, y)), float(gz.min()), float(gz.max())

    def place(self, asset, x, y, z=None, yaw=0.0, scale=1.0, tilt=(0.0, 0.0), sink=0.0, tag=None,
              collide=None, occupy_r=None, category=None):
        T = self.T
        if z is None:
            z = float(T.height(x, y)) - sink
        cat = category or self.ctx.template_info[asset]["category"]
        coll = bl.coll(CAT_COLL.get(cat, "DECORATION"))
        M = bl.matrix_trs((x, y, z), yaw, scale, tilt)
        idx = len(self.ctx.instances)
        name = "SVI_%s_%05d" % (asset, idx)
        bl.instance_parts(self.ctx.templates[asset], name, M, coll, tag={"sv_asset": asset})
        rec = dict(asset=asset, name=name, loc=(x, y, z), yaw=yaw, scale=scale, tilt=tilt,
                   category=cat, collide=collide or CAT_COLLIDE.get(cat, "None"))
        if tag:
            rec.update(tag)
        self.ctx.instances.append(rec)
        self.counts[asset] = self.counts.get(asset, 0) + 1
        if occupy_r:
            self.occupy(x, y, occupy_r)
        return rec


# ---------------------------------------------------------------------------
# helpers on routes
# ---------------------------------------------------------------------------

def yaw_facing(dx, dy):
    """Yaw so that the asset's local +Y points along (dx, dy)."""
    return math.atan2(dy, dx) - math.pi / 2


def route_frame(r, s):
    p = r.point(s)
    t = r.tangent(s)
    rt = np.array([t[1], -t[0]])
    return p, t, rt


def edge_point(r, s, side, extra=0.0, margin=True):
    p, t, rt = route_frame(r, s)
    W = float(r.interp("width", s))
    m = float(r.interp("margin_r" if side > 0 else "margin_l", s)) if margin else 0.0
    d = side * (W / 2 + m + extra)
    return p[0] + rt[0] * d, p[1] + rt[1] * d, t, rt


# ---------------------------------------------------------------------------
# stages
# ---------------------------------------------------------------------------

def place_unique(ctx, P):
    """Bridge, ice cave, lake, ponds, creek & ravine ice, plaza paving."""
    T, net = ctx.T, ctx.net
    meta = {}
    specs = []
    mb, bmeta = assets_unique.build_bridge(T, net)
    specs.append(("SV_UNQ_StoneBridge", "Bridges", "BRIDGES", mb))
    meta["bridge"] = bmeta
    mb, cmeta = assets_unique.build_ice_cave(T, net)
    specs.append(("SV_UNQ_IceCave", "IceCave", "ICE_CAVE", mb))
    meta["cave"] = cmeta
    lk = T.features["lake"]
    specs.append(("SV_UNQ_FrozenLake", "Environment", "FROZEN_LAKE",
                  assets_unique.build_ice_disk(lk, lk["z"], 31)))
    for key, seed in (("pond_w", 32), ("pond_e", 33)):
        pd = T.features[key]
        specs.append(("SV_UNQ_" + key.title().replace("_", ""), "Environment", "FROZEN_LAKE",
                      assets_unique.build_ice_disk(pd, pd["z"], seed)))
    ck = T.features["creek"]
    # the creek is ~700 m long: split it so every MeshPart stays < 2048 studs
    cpts = ck["pts"][::2]
    cnrm = assets_unique.ribbon_normals(cpts)
    n_seg = max(1, int(math.ceil(len(cpts) / 24.0)))
    cuts = np.linspace(0, len(cpts) - 1, n_seg + 1).round().astype(int)
    for k in range(n_seg):
        sl = slice(cuts[k], cuts[k + 1] + 1)
        specs.append(("SV_UNQ_CreekIce%02d" % k, "Environment", "FROZEN_LAKE",
                      assets_unique.build_ice_ribbon(T, cpts[sl], 4.0, lift=0.15, nrm=cnrm[sl])))
    rv = T.features["ravine"]
    from .routes import catmull_rom_chain
    rpts = catmull_rom_chain(rv["pts"], samples_per_m=0.25)
    specs.append(("SV_UNQ_RavineIce", "Environment", "FROZEN_LAKE",
                  assets_unique.build_ice_ribbon(T, rpts, 6.0, lift=0.2, mat="SV_IceDeep")))
    # frozen waterfall from the lake outlet into the ravine
    from .meshbuild import MeshBuilder
    wf = MeshBuilder()
    ox, oy = lk["x"] - lk["a"] * 0.98, lk["y"] + 4.0
    zr = float(T.height(ox - 18.0, oy))
    assets_unique._ice_curtain(wf, (ox - 6.0, oy), (1.0, 0.0), zr - 1.0, lk["z"] + 0.5, width=14.0, seed=77)
    specs.append(("SV_UNQ_LakeIcefall", "Environment", "FROZEN_LAKE", wf))
    pz = T.features["plaza"]
    specs.append(("SV_UNQ_PlazaPaving", "Finish", "FINISH_AREA",
                  assets_unique.build_plaza_paving(T, (pz["x"], pz["y"]), 52.0, pz["z"])))
    for name, cat, collname, mb in specs:
        lo, hi = mb.bounds()
        center = 0.5 * (lo + hi)
        objs = bl.builder_objects(mb, name, bl.coll(collname), origin=tuple(center),
                                  tag={"sv_kind": "unique", "sv_category": cat})
        for o in objs:
            ctx.unique.append(dict(name=o.name, category=cat, material=o["sv_material"], obj=o,
                                   tris=len(o.data.polygons)))
    # occupancy for set pieces: ellipses covered by circles along the major
    # axis (a single circle would block the whole shore)
    def occupy_ellipse(e, pad):
        ca, sa = math.cos(e["angle"]), math.sin(e["angle"])
        for t in np.linspace(-1.0, 1.0, 13):
            r = e["b"] * math.sqrt(max(0.0, 1.0 - t * t)) + pad
            P.occupy(e["x"] + ca * e["a"] * t, e["y"] + sa * e["a"] * t, max(r, pad))

    occupy_ellipse(lk, 12.0)
    for key in ("pond_w", "pond_e"):
        occupy_ellipse(T.features[key], 10.0)
    for x, y in ck["pts"][::4]:
        P.occupy(x, y, 5.0)
    for x, y in rpts[::3]:
        P.occupy(x, y, 14.0)
    P.occupy(pz["x"], pz["y"], 56.0)
    # decorative ice + icicles around the bridge, cave and lake
    for (x, y, z) in bmeta["icicles"]:
        P.place("IcicleCluster", x, y, z=z, yaw=float(P.rng.uniform(0, 6.28)), category="Environment")
    for c in meta["cave"]["crystals"]:
        P.place("IceCrystalCluster", c["pos"][0], c["pos"][1], z=c["pos"][2], yaw=c["yaw"],
                scale=float(P.rng.uniform(0.8, 1.3)), category="IceCave")
    for c in meta["cave"]["icicles"]:
        P.place("IcicleCluster", c["pos"][0], c["pos"][1], z=c["pos"][2], yaw=float(P.rng.uniform(0, 6.28)),
                scale=1.3, category="IceCave")
    for k in range(14):
        a = 2 * math.pi * k / 14 + 0.2
        x = lk["x"] + lk["a"] * 1.08 * math.cos(a)
        y = lk["y"] + lk["b"] * 1.15 * math.sin(a)
        if float(T.corridor_dist(x, y)) < 2.0:
            continue
        P.place("IceShards" if k % 2 else "IceCrystalCluster", x, y, yaw=a, scale=float(P.rng.uniform(0.8, 1.5)),
                sink=0.3, category="Environment")
    ctx.markers["bridge"] = bmeta
    ctx.markers["cave"] = meta["cave"]
    ctx.log("set pieces: bridge (%d arches), ice cave (%d lights), lake + ponds + creek" % (
        len(bmeta["arches"]), len(meta["cave"]["lights"])))


def place_village(ctx, P):
    T, net = ctx.T, ctx.net
    pz = T.features["plaza"]
    cx, cy = pz["x"], pz["y"]
    m = net.main
    finish_s = m.race_end_s
    fp, ft, frt = route_frame(m, finish_s)
    # finish structures
    P.place("FinishArch", fp[0], fp[1], z=float(m.interp("z", finish_s)), yaw=yaw_facing(ft[0], ft[1]),
            occupy_r=4.0, collide="Box")
    for side in (-1, 1):
        for k, s in enumerate(np.arange(finish_s - 90.0, finish_s + 40.0, 26.0)):
            x, y, t, rt = edge_point(m, s, side, extra=7.0)
            P.place("Bleachers", x, y, yaw=yaw_facing(-rt[0] * side, -rt[1] * side), occupy_r=6.0)
        for s in np.arange(finish_s - 160.0, finish_s + 30.0, 14.0):
            x, y, t, rt = edge_point(m, s, side, extra=1.5)
            P.place("FlagRed" if int(s / 14) % 2 else "FlagBlue", x, y, yaw=yaw_facing(t[0], t[1]),
                    sink=0.4)
    # Christmas tree + market stalls + lamps + benches around the paved ring
    tx, ty = cx - 2.0, cy - 22.0
    P.place("XmasTree", tx, ty, occupy_r=7.0, collide="Hull")
    ring = 44.0
    for k in range(18):
        a = math.radians(200 + k * (300 / 18))
        x, y = cx + ring * math.cos(a), cy + ring * math.sin(a)
        if float(T.corridor_dist(x, y)) < 4.0:
            continue
        yaw = yaw_facing(cx - x, cy - y)
        if k % 3 == 0:
            P.place("MarketStall", x, y, yaw=yaw, occupy_r=3.0, collide="Box")
        elif k % 3 == 1:
            P.place("Lamp", x, y, yaw=yaw, sink=0.3, tag={"light": dict(kind="lamp")})
        else:
            P.place("Bench", x, y, yaw=yaw)
    P.place("Snowman", cx + 18.0, cy - 30.0, yaw=yaw_facing(0.3, 1.0))
    P.place("SkiRack", cx - 30.0, cy + 26.0, yaw=yaw_facing(1.0, 0.0))
    # buildings: inner ring facing the plaza, then outer village
    inner = ["Lodge", "Restaurant", "Shop", "Townhouse", "ChaletB", "Shop", "Townhouse", "ChaletA",
             "SkiService", "Restaurant"]
    placed = 0
    for k in range(40):
        if placed >= len(inner):
            break
        a = math.radians(150 + k * 11.0)
        r = 78.0 + 8.0 * math.sin(k * 1.3)
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        name = inner[placed]
        yaw = yaw_facing(cx - x, cy - y)
        z = _ok_building_site(P, x, y, 14.0, name, yaw=yaw, sink=0.6)
        if z is not None:
            P.place(name, x, y, z=z, yaw=yaw, occupy_r=13.0)
            placed += 1
    outer_pool = ["ChaletA", "ChaletB", "Cabin", "Townhouse", "ChaletA", "Hut", "Cabin", "ChaletB", "Shop"]
    n_outer = 0
    for k in range(900):
        if n_outer >= 46:
            break
        a = P.rng.uniform(0, 2 * math.pi)
        r = P.rng.uniform(105.0, 290.0)
        x, y = cx + r * math.cos(a), cy + r * math.sin(a) * 0.85
        name = outer_pool[n_outer % len(outer_pool)]
        face = yaw_facing(cx - x, cy - y) + P.rng.uniform(-0.35, 0.35)
        bz = _ok_building_site(P, x, y, 11.0, name, yaw=face, sink=0.7)
        if bz is None:
            continue
        z = float(T.height(x, y))
        if abs(z - pz["z"]) > 38.0:
            continue
        P.place(name, x, y, z=bz, yaw=face, occupy_r=11.0)
        if P.rng.uniform() < 0.35:
            lx, ly = x + 9.0 * math.cos(face + 1.2), y + 9.0 * math.sin(face + 1.2)
            if P.free(lx, ly, 1.0) and float(T.corridor_dist(lx, ly)) > 3.0:
                P.place("Lamp", lx, ly, yaw=face, sink=0.3, tag={"light": dict(kind="lamp")})
        n_outer += 1
    # village approach (section 17) lamps + fences
    sec17 = m.sections[16]
    for side in (-1, 1):
        for s in np.arange(sec17["s0"] - 60.0, finish_s - 5.0, 22.0):
            x, y, t, rt = edge_point(m, s, side, extra=1.2)
            if P.free(x, y, 0.5):
                P.place("Lamp", x, y, yaw=yaw_facing(-rt[0] * side, -rt[1] * side), sink=0.3,
                        tag={"light": dict(kind="lamp")})
    # footbridges over the creek near the village
    ck = T.features["creek"]["pts"]
    for frac in (0.62, 0.78, 0.9):
        i = int(frac * (len(ck) - 1))
        p0, p1 = ck[i], ck[min(i + 1, len(ck) - 1)]
        d = p1 - p0
        P.place("FootBridge", float(p0[0]), float(p0[1]), yaw=yaw_facing(-d[1], d[0]), sink=0.3, collide="Hull")
    ctx.log("village: %d inner + %d outer buildings" % (placed, n_outer))


# A building's stone base reaches its template's lowest point (2 m below the
# origin, 5 m for the terrace restaurant). The origin sits `sink` below the
# centre ground; the uphill side may be buried at most SITE_MAX_RISE and the
# base must reach the lowest footprint corner. Terrace buildings are raised
# so their uphill side is never buried more than 1 m.
SITE_MAX_RISE = 1.6


def _base_depth(P, asset):
    """Depth of an asset's stone base below its origin (template bounds)."""
    return -float(P.ctx.template_info[asset]["bounds"][0][2])


def _site_z(P, x, y, asset, yaw, sink):
    """Origin height for a building at (x, y), or None if the ground under its
    footprint cannot be covered by its base."""
    gc, gmin, gmax = P.ground_range(asset, x, y, yaw)
    bd = _base_depth(P, asset)
    z = gc - sink
    if bd > 2.5:
        z = max(z, gmax - 1.0)
    elif gmax - gc > SITE_MAX_RISE:
        return None
    if (z - bd) - gmin > -0.05:
        return None
    return z


def _ok_building_site(P, x, y, r, asset, yaw=0.0, sink=0.7):
    """Returns the origin z for a valid site, None otherwise."""
    T = P.T
    if not P.free(x, y, r):
        return None
    if float(T.corridor_dist(x, y)) < r + 6.0:
        return None
    # buildings with a deep terrace base (mountain restaurant) may sit on a slope
    extra = max(0.0, _base_depth(P, asset) - 2.0)
    if float(T.slope(x, y)) > 16.0 + 4.0 * extra:
        return None
    if not P.clear_of_corridors(asset, x, y, yaw, min_ce=4.0):
        return None
    return _site_z(P, x, y, asset, yaw, sink)


def place_mountain_buildings(ctx, P):
    T, net = ctx.T, ctx.net
    m = net.main
    sec = {d["id"]: d for d in m.sections}
    spots = [
        ("Lodge", sec[1]["s0"] + 40.0, 1, 34.0),        # summit lodge beside the start
        ("Hut", sec[4]["s0"] + 260.0, -1, 22.0),        # forest hut
        ("Cabin", sec[7]["s0"] + 330.0, 1, 26.0),
        ("Restaurant", sec[9]["s0"] + 150.0, -1, 30.0),  # mountain restaurant by the lake
        ("Hut", sec[13]["s0"] + 120.0, 1, 26.0),
        ("Cabin", sec[15]["s0"] + 120.0, 1, 30.0),
        ("Hut", sec[5]["s0"] + 230.0, 1, 30.0),
    ]
    n = 0
    skipped = []
    # search outwards from the preferred spot: along the route (both ways),
    # further from the piste, then the other side of the piste
    offsets = sorted(np.arange(-63.0, 100.0, 9.0), key=abs)
    for name, s, side, extra in spots:
        done = False
        for sd in (side, -side):
            for ext in (0.0, 10.0, 20.0, 32.0):
                for ds in offsets:
                    x, y, t, rt = edge_point(m, s + ds, sd, extra=extra + ext)
                    yaw = yaw_facing(-rt[0] * sd, -rt[1] * sd)
                    bz = _ok_building_site(P, x, y, 9.0, name, yaw=yaw, sink=0.8)
                    if bz is not None:
                        P.place(name, x, y, z=bz, yaw=yaw, occupy_r=11.0)
                        n += 1
                        done = True
                        break
                if done:
                    break
            if done:
                break
        if not done:
            skipped.append(name)
    ctx.log("mountain buildings: %d (no valid site for: %s)" % (n, ", ".join(skipped) or "-"))


def place_start_area(ctx, P):
    T, net = ctx.T, ctx.net
    m = net.main
    s_gate = 12.0
    p, t, rt = route_frame(m, s_gate)
    z = float(m.interp("z", s_gate))
    P.place("StartGate", p[0], p[1], z=z, yaw=yaw_facing(t[0], t[1]), occupy_r=3.0, collide="Box")
    # spawn grid behind the start line (4 x 4), facing downhill
    spawns = []
    W = 30.0
    for row in range(4):
        for col in range(4):
            back = 8.0 + row * 6.0
            lat = (col - 1.5) * (W / 4)
            sx = p[0] - t[0] * back + rt[0] * lat
            sy = p[1] - t[1] * back + rt[1] * lat
            sz = float(T.height(sx, sy))
            spawns.append(dict(pos=(sx, sy, sz), dir=(float(t[0]), float(t[1]), 0.0)))
    ctx.markers["spawns"] = spawns
    # flags & fences around the start pad
    sp = T.features["start_pad"]
    for k in range(16):
        a = 2 * math.pi * k / 16
        x, y = sp["x"] + 50.0 * math.cos(a), sp["y"] + 50.0 * math.sin(a)
        if float(T.corridor_dist(x, y)) < 1.0 and float(T.piste_dist(x, y)) < 6.0:
            continue
        P.place("FenceRail", x, y, yaw=a, sink=0.2)
    for side in (-1, 1):
        for k in range(5):
            x, y = p[0] - t[0] * (k * 7.0 - 6.0) + rt[0] * side * 19.0, p[1] - t[1] * (k * 7.0 - 6.0) + rt[1] * side * 19.0
            P.place("FlagRed" if (k + side) % 2 else "FlagBlue", x, y, yaw=yaw_facing(t[0], t[1]), sink=0.4)
    for lat in np.arange(34.0, 60.0, 2.0):
        hx, hy = p[0] + rt[0] * lat - t[0] * 6.0, p[1] + rt[1] * lat - t[1] * 6.0
        hyaw = yaw_facing(-rt[0], -rt[1])
        if P.clear_of_corridors("Hut", hx, hy, hyaw, min_ce=2.0):
            hz = _site_z(P, hx, hy, "Hut", hyaw, 0.5)
            if hz is not None:
                P.place("Hut", hx, hy, z=hz, yaw=hyaw, occupy_r=6.0)
                break
    P.place("Lookout", sp["x"] + 40.0, sp["y"] - 30.0, yaw=yaw_facing(0.4, -1.0), sink=1.0)
    # summit crags behind the start
    sx, sy = T.features["summit"]["x"], T.features["summit"]["y"]
    for k in range(9):
        a = math.radians(30 + k * 40)
        r = 26.0 + 10.0 * (k % 3)
        x, y = sx + r * math.cos(a), sy + r * math.sin(a)
        kind = ["Crag", "SpireBroad", "Boulder"][k % 3]
        if P.clear_of_corridors(kind, x, y, a, 1.2, min_ce=2.0):
            P.place(kind, x, y, yaw=a, scale=1.2, sink=1.2)
    ctx.log("start area: gate, %d spawns" % len(spawns))


def place_route_furniture(ctx, P):
    T, net = ctx.T, ctx.net
    m = net.main
    pole_assets = {"blue": "PoleBlue", "green": "PoleGreen", "red": "PoleRed", "black": "PoleBlack"}
    for r in net.routes:
        pole = pole_assets[r.difficulty]
        for side in (-1, 1):
            for s in np.arange(25.0, r.length - 10.0, 34.0):
                k = r.index_at(s)
                if r.surface[k] != routes.SURF_GROUND:
                    continue
                x, y, t, rt = edge_point(r, s, side, extra=0.8, margin=False)
                if float(T.piste_dist(x, y)) < -1.0:
                    continue
                P.place(pole, x, y, yaw=float(P.rng.uniform(0, 6.28)), sink=0.2,
                        tilt=(float(P.rng.uniform(-0.04, 0.04)), float(P.rng.uniform(-0.04, 0.04))))
    # fences along hairpin outsides, cliff edge, bridge approaches; nets on red runs
    fence_ranges = []
    for d in m.sections:
        if d["id"] in (4, 5, 7, 8, 11):
            fence_ranges.append((d["s0"] - 10.0, d["s0"] + 95.0, "outer"))
        if d.get("fence"):
            fence_ranges.append((d["s0"], d["s1"], d["fence"]))
    br = T.features["bridge"]
    fence_ranges.append((br["s0"] - 40.0, br["s0"] - 2.0, "both"))
    fence_ranges.append((br["s1"] + 2.0, br["s1"] + 40.0, "both"))
    for s0, s1, mode in fence_ranges:
        for s in np.arange(s0, s1, 4.0):
            kap = float(m.interp("kappa", s))
            if mode == "outer":
                sides = [1 if kap > 0 else -1]
            elif mode == "right":
                sides = [1]
            elif mode == "left":
                sides = [-1]
            else:
                sides = [-1, 1]
            for side in sides:
                x, y, t, rt = edge_point(m, s, side, extra=-0.6)
                if float(T.piste_dist(x, y)) < -1.0 or m.surface[m.index_at(s)] != routes.SURF_GROUND:
                    continue
                P.place("FenceRail", x, y, yaw=math.atan2(t[1], t[0]), sink=0.15)
    for r in net.alts:
        if r.difficulty not in ("red", "black"):
            continue
        for s in np.arange(30.0, r.length - 30.0, 6.0):
            kap = float(r.interp("kappa", s))
            if abs(kap) < 1.0 / 70.0:
                continue
            side = 1 if kap > 0 else -1
            x, y, t, rt = edge_point(r, s, side, extra=-0.4)
            P.place("SafetyNet", x, y, yaw=math.atan2(t[1], t[0]), sink=0.2)
    # section signs at each section start (facing the riders)
    for d in m.sections:
        if d["id"] in (1, 18):
            continue
        s = d["s0"] + 6.0
        x, y, t, rt = edge_point(m, s, 1, extra=2.5)
        P.place("SectionSign", x, y, yaw=yaw_facing(-t[0], -t[1]), sink=0.3,
                tag={"sign": dict(kind="section", id=d["id"], name=d["name"], legend=d["legend"])})
        if d["character"] in ("red",) or d["id"] in (4, 5, 7, 8, 11):
            x, y, t, rt = edge_point(m, d["s0"] - 40.0, -1, extra=1.5)
            P.place("WarningSign", x, y, yaw=yaw_facing(-t[0], -t[1]), sink=0.2)
    # checkpoint gates (visual posts + banner metadata)
    gate_vis = []
    for r in net.routes:
        for g in r.gates:
            s = g["s"]
            p, t, rt = route_frame(r, s)
            W = float(r.interp("width", s))
            k = r.index_at(s)
            z = float(r.interp("z", s))
            span = W + 3.0
            for side in (-1, 1):
                x = p[0] + rt[0] * side * span / 2
                y = p[1] + rt[1] * side * span / 2
                zz = z + side * span / 2 * math.tan(float(r.interp("bank", s))) if r.surface[k] != 0 else None
                P.place("GatePost", x, y, z=zz, yaw=yaw_facing(t[0], t[1]), sink=0.3)
            gate_vis.append(dict(route=r.id, group=g["group"], s=s, center=(p[0], p[1], z), dir=(t[0], t[1]),
                                 span=span))
    ctx.markers["gate_visuals"] = gate_vis
    # junction signs + difficulty markers
    for r in net.alts:
        x, y, t, rt = edge_point(m, r.branch_s - 35.0, 1, extra=2.0)
        P.place("JunctionSign", x, y, yaw=yaw_facing(-t[0], -t[1]), sink=0.3,
                tag={"sign": dict(kind="junction", alt=r.id, name=r.name, difficulty=r.difficulty)})
        mk = {"green": "MarkerGreen", "red": "MarkerRed", "black": "MarkerBlack"}[r.difficulty]
        x, y, t, rt = edge_point(r, 45.0, -1, extra=1.0, margin=False)
        P.place(mk, x, y, yaw=yaw_facing(-t[0], -t[1]), sink=0.2)
        x, y, t, rt = edge_point(m, r.branch_s + 45.0, 1, extra=1.0, margin=False)
        P.place("MarkerBlue", x, y, yaw=yaw_facing(-t[0], -t[1]), sink=0.2)
    # snow cannons & lookouts
    for s in np.arange(300.0, m.race_end_s - 300.0, 230.0):
        k = m.index_at(s)
        if m.surface[k] != routes.SURF_GROUND:
            continue
        x, y, t, rt = edge_point(m, s, -1 if int(s) % 2 else 1, extra=4.0)
        if P.free(x, y, 2.0):
            P.place("SnowCannon", x, y, yaw=math.atan2(t[1], t[0]), sink=0.3)
    sec = {d["id"]: d for d in m.sections}
    for sid, frac, side in ((9, 0.6, -1), (14, 0.05, 1), (6, 0.6, -1)):
        s = sec[sid]["s0"] + frac * (sec[sid]["s1"] - sec[sid]["s0"])
        x, y, t, rt = edge_point(m, s, side, extra=6.0)
        P.place("Lookout", x, y, yaw=yaw_facing(-rt[0] * side, -rt[1] * side), sink=1.2, occupy_r=5.0)
    ctx.log("route furniture placed")


def place_kickers(ctx, P):
    """Optional jumps on one side of the piste before steeper pitches."""
    T, net = ctx.T, ctx.net
    m = net.main
    sec = {d["id"]: d for d in m.sections}
    jumps = []
    plan = [("MAIN", 5, 0.45, -0.25), ("MAIN", 7, 0.55, 0.25), ("MAIN", 13, 0.3, -0.25),
            ("MAIN", 15, 0.4, 0.22), ("MAIN", 16, 0.25, -0.2)]
    for rid, sid, frac, lat in plan:
        r = net.route(rid)
        if sid:
            s0, s1 = sec[sid]["s0"], sec[sid]["s1"]
        else:
            s0, s1 = 0.0, r.length
        best = None
        for s in np.linspace(s0 + 0.2 * (s1 - s0), s0 + 0.8 * (s1 - s0), 25):
            k = r.index_at(s)
            if r.surface[k] != routes.SURF_GROUND:
                continue
            curv = abs(float(r.interp("kappa", s)))
            gain = float(r.interp("grad", s + 18.0)) - float(r.interp("grad", s - 8.0))
            score = curv * 300.0 - gain * 10.0 + abs(s - (s0 + frac * (s1 - s0))) * 0.01
            if best is None or score < best[0]:
                best = (score, s)
        s = best[1]
        p, t, rt = route_frame(r, s)
        W = float(r.interp("width", s))
        d = lat * W
        x, y = p[0] + rt[0] * d, p[1] + rt[1] * d
        z = float(T.height(x, y))
        g = float(r.interp("grad", s))
        pitch = math.atan(g)
        P.place("Kicker", x, y, z=z - 0.05, yaw=yaw_facing(t[0], t[1]), tilt=(-pitch, 0.0),
                collide="Kicker")
        jumps.append(dict(route=rid, s=float(s), pos=(x, y, z), dir=(float(t[0]), float(t[1])), pitch=pitch,
                          length=10.0, width=8.0, lip=1.8))
    ctx.markers["kickers"] = jumps
    ctx.log("kickers: %d" % len(jumps))


def place_rocks(ctx, P):
    T, net = ctx.T, ctx.net
    rng = np.random.default_rng(config.SEED + 7)
    cliffs = ["CliffWall", "CliffLedge", "CliffTall", "CliffSpur", "CliffBand"]
    boulders = ["Boulder", "BoulderFlat", "Slab", "Crag", "RockSmall", "RockWarm"]
    xs = np.arange(T.x0 + 40, T.x1 - 40, 16.0)
    ys = np.arange(T.y0 + 40, T.y1 - 40, 16.0)
    X, Y = np.meshgrid(xs, ys)
    X = X + rng.uniform(-6, 6, X.shape)
    Y = Y + rng.uniform(-6, 6, Y.shape)
    x, y = X.ravel(), Y.ravel()
    rock = T.rock(x, y)
    sl = T.slope(x, y)
    ce = T.corridor_dist(x, y)
    rd = T.route_dist_coarse.bilinear(x, y)
    cand_cliff = (rock > 0.6) & (sl > 36) & (ce > 9.0) & (rd < 360)
    n_cliff = 0
    for i in np.where(cand_cliff)[0]:
        if n_cliff >= 300:
            break
        if rng.uniform() > (0.32 if rd[i] < 200 else 0.14):
            continue
        if not P.free(x[i], y[i], 6.0):
            continue
        gx, gy = T.base_grid.gradient(x[i], y[i]) if hasattr(T, "base_grid") else (0, 0)
        gx = float(gx)
        gy = float(gy)
        yaw = yaw_facing(-gx, -gy) + rng.uniform(-0.3, 0.3)
        name = cliffs[int(rng.integers(len(cliffs)))]
        sc = float(rng.uniform(0.75, 1.35))
        if not P.clear_of_corridors(name, x[i], y[i], yaw, sc, min_ce=2.0):
            continue
        P.place(name, x[i], y[i], yaw=yaw, scale=sc, sink=3.2 * sc, occupy_r=10.0 * sc)
        n_cliff += 1
    cand_b = (sl > 12) & (ce > 4.0) & (rd < 400) & ((rock > 0.25) | (rng.uniform(size=len(x)) < 0.05))
    n_b = 0
    for i in np.where(cand_b)[0]:
        if n_b >= 560:
            break
        if rng.uniform() > 0.3:
            continue
        if not P.free(x[i], y[i], 2.5):
            continue
        name = boulders[int(rng.integers(len(boulders)))]
        sc = float(rng.uniform(0.7, 1.6))
        byaw = float(rng.uniform(0, 6.28))
        if not P.clear_of_corridors(name, x[i], y[i], byaw, sc, min_ce=1.0):
            continue
        P.place(name, x[i], y[i], yaw=byaw, scale=sc, sink=0.3 * sc, occupy_r=2.5 * sc,
                tilt=(float(rng.uniform(-0.12, 0.12)), float(rng.uniform(-0.12, 0.12))))
        n_b += 1
    # signature formations: Rocky Pass (6), Mountain Pass (10), Cliff Descent (3), canyon walls (11)
    m = net.main
    sec = {d["id"]: d for d in m.sections}
    n_f = 0
    for sid, spacing, kinds, extra in ((6, 26.0, ["SpireTall", "SpireTwin", "Crag", "SpireBroad"], 7.0),
                                       (10, 24.0, ["SpireBroad", "CliffSpur", "SpireTall", "Crag"], 6.0),
                                       (3, 30.0, ["CliffTall", "CliffWall", "Crag"], 7.0)):
        for k, s in enumerate(np.arange(sec[sid]["s0"] + 10, sec[sid]["s1"] - 5, spacing)):
            for side in (-1, 1):
                if sid == 3 and side > 0:
                    continue
                xx, yy, t, rt = edge_point(m, s, side, extra=extra + rng.uniform(0, 6))
                kind = kinds[(k + (side > 0)) % len(kinds)]
                fyaw = float(rng.uniform(0, 6.28))
                fsc = float(rng.uniform(0.9, 1.3))
                if not P.free(xx, yy, 3.0) or not P.clear_of_corridors(kind, xx, yy, fyaw, fsc, min_ce=1.0):
                    continue
                P.place(kind, xx, yy, yaw=fyaw, scale=fsc, sink=2.0, occupy_r=4.0)
                n_f += 1
    for s in np.arange(sec[11]["s0"] + 80, sec[11]["s1"] - 10, 22.0):
        for side in (-1, 1):
            kind = cliffs[int(rng.integers(len(cliffs)))]
            csc = float(rng.uniform(0.8, 1.1))
            extra = 7.0 + rng.uniform(0, 4)
            for _ in range(4):
                xx, yy, t, rt = edge_point(m, s, side, extra=extra)
                cyaw = yaw_facing(-rt[0] * side, -rt[1] * side)
                if P.clear_of_corridors(kind, xx, yy, cyaw, csc, min_ce=1.0):
                    break
                extra += 4.0
            else:
                continue
            if not P.free(xx, yy, 3.0):
                continue
            P.place(kind, xx, yy, yaw=cyaw, scale=csc, sink=3.0, occupy_r=6.0)
            n_f += 1
    ctx.log("rocks: %d cliffs, %d boulders, %d formation pieces" % (n_cliff, n_b, n_f))


def place_forest(ctx, P):
    T, net = ctx.T, ctx.net
    nb = P.nb
    rng = np.random.default_rng(config.SEED + 13)
    step = 5.0
    xs = np.arange(T.x0 + 20, T.x1 - 20, step)
    ys = np.arange(T.y0 + 20, T.y1 - 20, step)
    X, Y = np.meshgrid(xs, ys)
    X = X + rng.uniform(-2.2, 2.2, X.shape)
    Y = Y + rng.uniform(-2.2, 2.2, Y.shape)
    x, y = X.ravel(), Y.ravel()
    z = T.height(x, y)
    sl = T.slope(x, y)
    rock = T.rock(x, y)
    ce = T.corridor_dist(x, y)
    rd = T.route_dist_coarse.bilinear(x, y)
    tl = 650.0 + 35.0 * nb.fbm("treeline", x, y, 300.0, octaves=2)
    d_elev = 1.0 - smoothstep(tl - 70.0, tl + 25.0, z)
    d_slope = 1.0 - smoothstep(30.0, 41.0, sl)
    d_rock = 1.0 - smoothstep(0.25, 0.6, rock)
    patches = smoothstep(-0.18, 0.32, nb.fbm("forest", x, y, 240.0, octaves=4))
    dens = (0.12 + 0.88 * patches) * d_elev * d_slope * d_rock
    dens *= smoothstep(3.0, 8.0, ce) * (1.0 - smoothstep(45.0, 55.0, ce))
    # trees frame the forest sections closely
    m = net.main
    sec = {d["id"]: d for d in m.sections}
    near = (ce > 3.0) & (ce < 30.0)
    for sid in (4, 7):
        a, b = sec[sid]["s0"], sec[sid]["s1"]
        seg = np.arange(a, b, 10.0)
        px, py = m.interp("x", seg), m.interp("y", seg)
        for k in range(0, len(x), 60000):
            sl_ = slice(k, k + 60000)
            dd = np.min(np.hypot(x[sl_, None] - px[None, :], y[sl_, None] - py[None, :]), axis=1)
            boost = near[sl_] & (dd < 70.0)
            dens[sl_] = np.where(boost, np.maximum(dens[sl_], 0.9 * d_slope[sl_] * d_rock[sl_]), dens[sl_])
    # clearings at junctions
    for r in net.alts:
        for s in (r.branch_s, r.merge_s):
            p = m.point(s)
            dd = np.hypot(x - p[0], y - p[1])
            dens *= smoothstep(25.0, 60.0, dd) * 0.85 + 0.15
    # never near the plaza / start / stations
    for key in ("plaza", "start_pad"):
        f = T.features[key]
        dd = np.hypot(x - f["x"], y - f["y"])
        dens *= smoothstep(f["r1"] * 0.9, f["r1"] * 1.4, dd)
    keep = rng.uniform(size=len(x)) < dens * 0.85
    order = np.where(keep)[0]
    rng.shuffle(order)
    variants_mid = ["PineTall", "PineMedium", "PineBlue", "PineMedium", "PineTall"]
    variants_low = ["PineWide", "PineMedium", "PineSmall", "PineBlue"]
    variants_high = ["PineSparse", "PineSmall", "PineMedium"]
    n = 0
    cap = 5200
    spacing_grid = {}
    cell = 5.5
    for i in order:
        if n >= cap:
            break
        key = (int(x[i] // cell), int(y[i] // cell))
        if key in spacing_grid:
            continue
        if not P.free(x[i], y[i], 1.0):
            continue
        spacing_grid[key] = 1
        zz = z[i]
        if zz > tl[i] - 60:
            name = variants_high[int(rng.integers(len(variants_high)))]
        elif zz < 120:
            name = variants_low[int(rng.integers(len(variants_low)))]
        else:
            name = variants_mid[int(rng.integers(len(variants_mid)))]
        sc = float(rng.uniform(0.75, 1.25))
        P.place(name, x[i], y[i], z=zz - 0.6, yaw=float(rng.uniform(0, 6.28)), scale=sc,
                tilt=(float(rng.uniform(-0.04, 0.04)), float(rng.uniform(-0.04, 0.04))))
        n += 1
    ctx.log("forest: %d instanced trees near pistes" % n)
    # dense baked canopy beyond the near-piste band
    from . import forest
    meshes, count = forest.build_canopy(T, net, P, np.random.default_rng(config.SEED + 21), nb)
    tri = 0
    for name, v, t, uv in meshes:
        lo, hi = v.min(axis=0), v.max(axis=0)
        c = 0.5 * (lo + hi)
        me = bl.mesh_from_arrays(name, v - c, t, uv[t.reshape(-1)], None, smooth=False, material="SV_TreeAtlas")
        ob = bl.new_object(name, me, bl.coll("FOREST"), location=tuple(c))
        ob["sv_material"] = "SV_TreeAtlas"
        ob["sv_category"] = "ForestCanopy"
        ctx.unique.append(dict(name=name, category="ForestCanopy", material="SV_TreeAtlas", obj=ob,
                               tris=int(len(t))))
        tri += len(t)
    ctx.stats["canopy_trees"] = int(count)
    ctx.log("forest canopy: %d trees baked into %d meshes (%d tris)" % (count, len(meshes), tri))
