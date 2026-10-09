"""Nature asset library: pines, rocks, cliffs, spires, ice crystals.

All assets are built at the origin (base centre at z = 0, front = +Y) and
returned as MeshBuilders. Trees are baked into ONE palette-textured part
(one Roblox MeshPart per tree -> cheap instancing); rocks/cliffs keep a
ROCK part and a SNOW part (up-facing faces).
"""

import math

import numpy as np

from . import materials
from .meshbuild import MeshBuilder, bake_palette, icosphere, rot_z

# ---------------------------------------------------------------------------
# pine trees
# ---------------------------------------------------------------------------

PINE_VARIANTS = {
    # name: height, radius ratio, tiers, points, snow amount, droop, colour set
    "PineTall":   dict(h=20.0, rr=0.26, tiers=7, pts=8, snow=0.80, droop=0.30, col="mid", seed=1),
    "PineMedium": dict(h=14.0, rr=0.32, tiers=6, pts=8, snow=0.65, droop=0.25, col="dark", seed=2),
    "PineWide":   dict(h=11.0, rr=0.40, tiers=5, pts=9, snow=0.55, droop=0.20, col="light", seed=3),
    "PineSmall":  dict(h=6.5, rr=0.36, tiers=4, pts=7, snow=0.85, droop=0.20, col="mid", seed=4),
    "PineBlue":   dict(h=16.0, rr=0.30, tiers=6, pts=8, snow=0.70, droop=0.35, col="blue", seed=5),
    "PineSparse": dict(h=10.0, rr=0.27, tiers=4, pts=7, snow=0.45, droop=0.15, col="dark", seed=6,
                       sparse=True),
}
PINE_LOD = {"PineFar": dict(h=14.0, rr=0.31, tiers=2, pts=6, snow=0.6, droop=0.0, col="mid", seed=7,
                            lod=True)}

_COLSETS = {
    "dark": ("needle_dark", "needle_dark"),
    "mid": ("needle_mid", "needle_dark"),
    "light": ("needle_light", "needle_mid"),
    "blue": ("needle_blue", "needle_dark"),
}


def build_pine(p):
    rng = np.random.default_rng(1000 + p["seed"])
    H = p["h"]
    R = p["rr"] * H
    N = p["tiers"]
    P = p["pts"]
    mb = MeshBuilder()
    trunk_top = H * 0.32
    tr = max(0.18, 0.035 * H)
    mb.cylinder("trunk", (0, 0, -0.6), (0, 0, trunk_top), tr, tr * 0.7, seg=6)
    clear = H * (0.10 if not p.get("sparse") else 0.22)
    top_set, under_set = _COLSETS[p["col"]]
    span = H - clear
    spacing = span / (N + 0.6)
    for k in range(N):
        t = k / max(N - 1, 1)
        zb = clear + k * spacing
        tier_h = spacing * (2.05 if not p.get("lod") else 2.6)
        zt = min(H, zb + tier_h)
        if k == N - 1:
            zt = H
        r = R * (1.0 - 0.82 * t) ** 0.95 * rng.uniform(0.92, 1.08)
        if p.get("sparse"):
            r *= rng.uniform(0.7, 1.15)
        _tier(mb, rng, zb, zt, r, P, p["droop"], p["snow"], top_set if k > 0 else under_set,
              under_set, lod=p.get("lod", False))
    mapping = {"trunk": "trunk", "green_top": top_set, "green_under": under_set, "green_top2": top_set,
               "snow": "snow", "snow_edge": "snow_shadow"}
    # all "green_*" parts map to their palette swatch
    used = {m: mapping[m] for m in mb.parts}
    return bake_palette(mb, "SV_TreeAtlas", used, materials.palette_uv)


def _tier(mb, rng, zb, zt, r, P, droop, snow, top_key, under_key, lod=False):
    n = 2 * P
    ang0 = rng.uniform(0, 2 * math.pi)
    ang = ang0 + np.arange(n) * math.pi / P + rng.uniform(-0.12, 0.12, n)
    rad = np.where(np.arange(n) % 2 == 0, r, r * rng.uniform(0.62, 0.75))
    rad = rad * rng.uniform(0.9, 1.08, n)
    zr = zb - np.where(np.arange(n) % 2 == 0, droop * r * 0.35, droop * r * 0.12)
    outer = np.column_stack([rad * np.cos(ang), rad * np.sin(ang), zr])
    apex = np.array([[0.0, 0.0, zt]])
    # top (green) skirt
    v = np.vstack([outer, apex])
    f = [(i, (i + 1) % n, n) for i in range(n)]
    shade = np.column_stack([np.full(n + 1, 0.9), np.full(n + 1, 0.9), np.full(n + 1, 0.9), np.ones(n + 1)])
    shade[n] = (1.05, 1.05, 1.05, 1)
    mb.add("green_top", v, f, shade, smooth=True)
    if not lod:
        # underside: slightly concave towards the trunk
        inner_r = r * 0.22
        inner = np.column_stack([inner_r * np.cos(ang), inner_r * np.sin(ang), np.full(n, zb + (zt - zb) * 0.18)])
        v = np.vstack([outer, inner])
        f = [((i + 1) % n, i, n + i, n + (i + 1) % n) for i in range(n)]
        dark = np.tile((0.55, 0.6, 0.6, 1.0), (2 * n, 1))
        mb.add("green_under", v, f, dark, smooth=True)
    # snow cap: covers the upper part of the tier, irregular rim
    if snow > 0.05:
        frac = np.clip(snow * rng.uniform(0.75, 1.05, n), 0.3, 0.97)
        sr = rad * frac
        # height of the green cone at radius sr (linear between rim and apex)
        zc = zt + (zr - zt) * frac + 0.10 + 0.05 * r
        rim = np.column_stack([sr * np.cos(ang), sr * np.sin(ang), zc])
        sapex = np.array([[0.0, 0.0, zt + 0.12]])
        v = np.vstack([rim, sapex])
        f = [(i, (i + 1) % n, n) for i in range(n)]
        c = np.tile((1.0, 1.0, 1.0, 1.0), (n + 1, 1))
        mb.add("snow", v, f, c, smooth=True)


# ---------------------------------------------------------------------------
# rocks & cliffs
# ---------------------------------------------------------------------------

def _noise3(p, seed, freq):
    """Cheap smooth 3D value noise via sums of random sinusoids."""
    rng = np.random.default_rng(seed)
    out = np.zeros(len(p))
    for _ in range(6):
        d = rng.normal(size=3)
        d /= np.linalg.norm(d)
        ph = rng.uniform(0, 2 * math.pi)
        f = freq * rng.uniform(0.7, 1.6)
        out += np.sin(p @ d * f + ph)
    return out / 6.0


def _boxy(v, amount):
    """Blend unit-sphere vertices towards the unit cube surface (flat faces)."""
    cube = v / np.max(np.abs(v), axis=1, keepdims=True)
    return v * (1.0 - amount) + cube * amount


def _planar_cuts(v, rng, n_cuts, depth_lo, depth_hi, bias_up=0.0):
    for _ in range(n_cuts):
        nrm = rng.normal(size=3)
        nrm[2] += bias_up
        nrm /= np.linalg.norm(nrm)
        d = rng.uniform(depth_lo, depth_hi)
        over = v @ nrm - d
        v = v - np.maximum(over, 0)[:, None] * nrm[None, :]
    return v


def _split_snow(mb, v, faces, snow_thr, rock_mat, snow_mat="SV_Snow", rock_col=None,
                min_rel_z=0.45):
    v = np.asarray(v)
    tri = np.asarray(faces)
    a, b, c = v[tri[:, 0]], v[tri[:, 1]], v[tri[:, 2]]
    n = np.cross(b - a, c - a)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
    zc = (a[:, 2] + b[:, 2] + c[:, 2]) / 3.0
    rel = (zc - v[:, 2].min()) / max(np.ptp(v[:, 2]), 1e-6)
    up = (n[:, 2] > snow_thr) & (rel > min_rel_z)
    for mat, sel in ((snow_mat, up), (rock_mat, ~up)):
        if not np.any(sel):
            continue
        ts = tri[sel]
        used = np.unique(ts)
        remap = -np.ones(len(v), dtype=np.int64)
        remap[used] = np.arange(len(used))
        vv = v[used]
        if mat == snow_mat:
            col = np.tile((1, 1, 1, 1.0), (len(vv), 1))
        else:
            z = vv[:, 2]
            g = 0.82 + 0.18 * (z - z.min()) / max(np.ptp(z), 1e-6)
            col = np.column_stack([g, g, g, np.ones(len(vv))])
        mb.add(mat, vv, remap[ts], col, smooth=False)


ROCK_VARIANTS = {
    "Boulder":     dict(scale=(2.2, 1.9, 1.6), subdiv=2, cuts=7, snow=0.8, seed=11, mat="SV_Rock", boxy=0.35),
    "BoulderFlat": dict(scale=(3.0, 2.4, 1.2), subdiv=2, cuts=6, snow=0.82, seed=12, mat="SV_Rock", boxy=0.45),
    "Slab":        dict(scale=(4.2, 2.6, 1.3), subdiv=2, cuts=8, snow=0.8, seed=13, mat="SV_RockDark",
                        tilt=0.35, boxy=0.6),
    "Crag":        dict(scale=(2.6, 2.2, 4.4), subdiv=2, cuts=9, snow=0.82, seed=14, mat="SV_Rock", boxy=0.5),
    "RockSmall":   dict(scale=(1.1, 0.9, 0.75), subdiv=1, cuts=5, snow=0.85, seed=15, mat="SV_Rock", boxy=0.3),
    "RockWarm":    dict(scale=(2.4, 2.0, 1.8), subdiv=2, cuts=7, snow=0.8, seed=16, mat="SV_RockWarm", boxy=0.4),
}


def build_rock(p):
    rng = np.random.default_rng(p["seed"])
    v, f = icosphere(p["subdiv"])
    v = _boxy(v, p.get("boxy", 0.3))
    v = v * (1.0 + 0.16 * _noise3(v, p["seed"], 2.3)[:, None])
    v = _planar_cuts(v, rng, p["cuts"], 0.6, 0.92)
    v = v * np.asarray(p["scale"])
    if p.get("tilt"):
        a = p["tilt"]
        R = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])
        v = v @ R.T
    v[:, 2] -= v[:, 2].min() + 0.25 * np.asarray(p["scale"])[2]  # sink base below ground
    mb = MeshBuilder()
    _split_snow(mb, v, f, p["snow"], p["mat"])
    return mb


CLIFF_VARIANTS = {
    "CliffWall":  dict(w=26.0, d=9.0, h=18.0, seed=21, mat="SV_Rock", ledges=1),
    "CliffLedge": dict(w=20.0, d=10.0, h=12.0, seed=22, mat="SV_RockDark", ledges=2),
    "CliffTall":  dict(w=16.0, d=8.0, h=26.0, seed=23, mat="SV_Rock", ledges=1),
    "CliffSpur":  dict(w=12.0, d=12.0, h=16.0, seed=24, mat="SV_RockDark", ledges=0),
    "CliffBand":  dict(w=34.0, d=7.0, h=9.0, seed=25, mat="SV_Rock", ledges=0),
}


def build_cliff(p):
    """Jointed cliff face: staggered rock columns with a jagged skyline and
    snow on the column tops/ledges. Front face looks towards +Y."""
    rng = np.random.default_rng(p["seed"])
    mb = MeshBuilder()
    n_cols = max(3, int(round(p["w"] / 5.0)))
    xs = np.linspace(-p["w"] / 2, p["w"] / 2, n_cols + 1)
    for k in range(n_cols):
        cw = (xs[k + 1] - xs[k]) * rng.uniform(1.05, 1.35)
        cx = 0.5 * (xs[k] + xs[k + 1]) + rng.uniform(-0.6, 0.6)
        centre_bias = 1.0 - 0.35 * abs(cx) / (p["w"] / 2)
        ch = p["h"] * rng.uniform(0.6, 1.0) * centre_bias
        cd = p["d"] * rng.uniform(0.65, 1.0)
        v, f = icosphere(2)
        v = _boxy(v, 0.85)
        v = v * (1.0 + 0.07 * _noise3(v, p["seed"] * 31 + k, 3.0)[:, None])
        v = _planar_cuts(v, rng, 5, 0.7, 0.95)
        v = v * np.array([cw / 2, cd / 2, ch / 2 + 1.5])
        v[:, 1] -= (v[:, 2] + ch / 2) * rng.uniform(0.04, 0.14)   # lean back
        lean = rng.uniform(-0.06, 0.06)
        v[:, 0] += v[:, 2] * lean
        v = v + np.array([cx, rng.uniform(-1.2, 1.2), ch / 2 - 3.0])
        _split_snow(mb, v, f, 0.8, p["mat"] if k % 3 else "SV_RockDark", min_rel_z=0.55)
    # one or two ledges across the face
    for j in range(0):
        lz = p["h"] * rng.uniform(0.3, 0.55)
        v, f = icosphere(2)
        v = _boxy(v, 0.9)
        v = v * np.array([p["w"] * 0.42, p["d"] * 0.32, 0.9])
        v = v + np.array([rng.uniform(-2, 2), p["d"] * 0.38, lz])
        _split_snow(mb, v, f, 0.75, p["mat"], min_rel_z=0.3)
    return mb


SPIRE_VARIANTS = {
    "SpireTall":  dict(h=28.0, r=4.5, seed=31),
    "SpireTwin":  dict(h=20.0, r=4.0, seed=32, twin=True),
    "SpireBroad": dict(h=16.0, r=6.5, seed=33),
}


def build_spire(p):
    rng = np.random.default_rng(p["seed"])
    mb = MeshBuilder()
    cols = [(0.0, 0.0, 1.0)]
    if p.get("twin"):
        cols = [(-2.6, 0.0, 1.0), (3.0, 1.0, 0.72)]
    for cx, cy, hs in cols:
        h = p["h"] * hs
        segs = 5
        z = -3.0
        for k in range(segs):
            sh = h / segs * rng.uniform(0.9, 1.15)
            r = p["r"] * (1.0 - 0.13 * k) * rng.uniform(0.9, 1.1)
            v, f = icosphere(2)
            v = _boxy(v, 0.75)
            v = _planar_cuts(v, rng, 6, 0.62, 0.9)
            v = v * np.array([r, r * rng.uniform(0.75, 1.0), sh / 1.6 * 1.1])
            v = v @ rot_z(rng.uniform(0, math.pi)).T
            v = v + np.array([cx + rng.uniform(-0.5, 0.5), cy + rng.uniform(-0.5, 0.5), z + sh / 2])
            _split_snow(mb, v, f, 0.82, "SV_Rock" if k % 2 == 0 else "SV_RockDark", min_rel_z=0.55)
            z += sh * 0.92
    return mb


ICE_VARIANTS = {
    "IceCrystalCluster": dict(n=7, h=4.5, seed=41),
    "IceShards":         dict(n=11, h=2.6, seed=42),
    "IcicleCluster":     dict(n=9, h=3.0, seed=43, hanging=True),
}


def build_ice(p):
    rng = np.random.default_rng(p["seed"])
    mb = MeshBuilder()
    for k in range(p["n"]):
        h = p["h"] * rng.uniform(0.45, 1.0)
        r = h * rng.uniform(0.12, 0.2)
        ang = rng.uniform(0, 2 * math.pi)
        dist = rng.uniform(0.0, p["h"] * 0.35)
        base = np.array([math.cos(ang) * dist, math.sin(ang) * dist, 0.0])
        if p.get("hanging"):
            tip = base + np.array([0, 0, -h])
            mb.cone("SV_IceGlow" if k % 3 == 0 else "SV_Glacier", base, tip, r, seg=5)
        else:
            lean = np.array([math.cos(ang), math.sin(ang), 0.0]) * rng.uniform(0.1, 0.45) * h
            tip = base + lean + np.array([0, 0, h])
            mat = "SV_IceGlow" if k % 2 == 0 else "SV_Glacier"
            body = base + (tip - base) * 0.72
            mb.cylinder(mat, base - np.array([0, 0, 0.5]), body, r, r * 0.9, seg=6)
            mb.cone(mat, body, tip, r * 0.9, seg=6, cap=False)
    return mb


def all_nature_builders():
    out = {}
    for k, p in PINE_VARIANTS.items():
        out[k] = ("Forest", build_pine(p))
    for k, p in PINE_LOD.items():
        out[k] = ("Forest", build_pine(p))
    for k, p in ROCK_VARIANTS.items():
        out[k] = ("Rocks", build_rock(p))
    for k, p in CLIFF_VARIANTS.items():
        out[k] = ("Rocks", build_cliff(p))
    for k, p in SPIRE_VARIANTS.items():
        out[k] = ("Rocks", build_spire(p))
    for k, p in ICE_VARIANTS.items():
        out[k] = ("Environment", build_ice(p))
    return out
