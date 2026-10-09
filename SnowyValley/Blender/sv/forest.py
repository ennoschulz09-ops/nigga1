"""Baked forest canopy: dense, terrain-conforming low-poly forests.

Individual detailed pines are instanced only close to the pistes (they frame
the runs and are seen up close).  Everything beyond that is baked into
per-chunk canopy meshes made of very low-poly pines (~18 triangles each)
that sit exactly on the terrain.  This gives the dense dark forest masses of
the reference at a triangle budget Roblox can stream (one MeshPart per
<=18k triangles, palette textured).
"""

import math

import numpy as np

from . import config, materials
from .mathutil import smoothstep

TRI_BUDGET = 17500


def _canopy_tree(cx, cy, cz, h, r, yaw, snow, uv_green, uv_snow, uv_dark):
    """Return verts, tris, uvs (per vertex) for one canopy pine."""
    seg = 6
    ang = yaw + np.arange(seg) * 2 * math.pi / seg
    ca, sa = np.cos(ang), np.sin(ang)
    verts, tris, uvs = [], [], []

    def ring(rad, z):
        return [(cx + rad * c, cy + rad * s, z) for c, s in zip(ca, sa)]

    def cone(base_z, top_z, rad, uv):
        b = len(verts)
        verts.extend(ring(rad, base_z))
        verts.append((cx, cy, top_z))
        uvs.extend([uv] * (seg + 1))
        for i in range(seg):
            tris.append((b + i, b + (i + 1) % seg, b + seg))

    z0 = cz + h * 0.08
    cone(z0, cz + h * 0.72, r, uv_dark)
    cone(cz + h * 0.42, cz + h, r * 0.62, uv_green)
    # snow caps on both tiers
    cone(z0 + (h * 0.64) * (1 - snow) + 0.15, cz + h * 0.72 + 0.12, r * snow * 0.92, uv_snow)
    return verts, tris, uvs


def canopy_positions(T, net, placer, rng, nb):
    """Dense forest sample points beyond the near-piste band."""
    step = 6.5
    xs = np.arange(T.x0 + 25, T.x1 - 25, step)
    ys = np.arange(T.y0 + 25, T.y1 - 25, step)
    X, Y = np.meshgrid(xs, ys)
    X = X + rng.uniform(-2.6, 2.6, X.shape)
    Y = Y + rng.uniform(-2.6, 2.6, Y.shape)
    x, y = X.ravel(), Y.ravel()
    z = T.height(x, y)
    sl = T.slope(x, y)
    rock = T.rock(x, y)
    ce = T.corridor_dist(x, y)
    tl = 610.0 + 35.0 * nb.fbm("treeline", x, y, 300.0, octaves=2)
    d = (1.0 - smoothstep(tl - 60.0, tl + 15.0, z)) * (1.0 - smoothstep(31.0, 40.0, sl))
    d *= 1.0 - smoothstep(0.2, 0.55, rock)
    patches = smoothstep(-0.05, 0.3, nb.fbm("forest", x, y, 260.0, octaves=4))
    d *= patches
    d *= smoothstep(40.0, 55.0, ce)            # near-piste band uses instanced trees
    for key in ("plaza", "start_pad"):
        f = T.features[key]
        d *= smoothstep(f["r1"] * 1.2, f["r1"] * 2.6, np.hypot(x - f["x"], y - f["y"]))
    keep = rng.uniform(size=len(x)) < d * 0.9
    out = []
    for i in np.where(keep)[0]:
        if not placer.free(x[i], y[i], 0.0):
            continue
        out.append((x[i], y[i], z[i]))
    return np.asarray(out)


def build_canopy(T, net, placer, rng, nb):
    pts = canopy_positions(T, net, placer, rng, nb)
    if len(pts) == 0:
        return [], 0
    uv_g = materials.palette_uv("needle_dark")
    uv_d = materials.palette_uv("needle_blue")
    uv_s = materials.palette_uv("snow")
    # bucket by detail chunk so meshes stay local (streaming friendly)
    size = config.CHUNK_SIZE_M
    keys = np.floor((pts[:, 0] - T.x0) / size).astype(int) * 1000 + np.floor((pts[:, 1] - T.y0) / size).astype(int)
    meshes = []
    for key in np.unique(keys):
        sel = pts[keys == key]
        cx_i, cy_i = key // 1000, key % 1000
        verts, tris, uvs = [], [], []
        part = 0
        for (x, y, z) in sel:
            h = rng.uniform(8.5, 17.0)
            r = h * rng.uniform(0.26, 0.34)
            snow = rng.uniform(0.6, 0.92)
            v, t, uv = _canopy_tree(x, y, z - 0.8, h, r, rng.uniform(0, 6.28), snow, uv_g, uv_s, uv_d)
            b = len(verts)
            verts.extend(v)
            uvs.extend(uv)
            tris.extend([(a + b, c + b, d + b) for a, c, d in t])
            if len(tris) >= TRI_BUDGET:
                meshes.append(("SV_FOREST_%02d_%02d_%d" % (cx_i, cy_i, part), np.asarray(verts),
                               np.asarray(tris), np.asarray(uvs)))
                verts, tris, uvs = [], [], []
                part += 1
        if tris:
            meshes.append(("SV_FOREST_%02d_%02d_%d" % (cx_i, cy_i, part), np.asarray(verts),
                           np.asarray(tris), np.asarray(uvs)))
    return meshes, len(pts)
