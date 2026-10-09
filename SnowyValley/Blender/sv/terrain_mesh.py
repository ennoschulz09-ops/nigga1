"""Terrain chunk meshes (visual only - Roblox collision is built separately).

* detail area: 420 m chunks (1500 studs), 5 m grid near corridors, 10 m
  elsewhere; skirts hide T-junction cracks between resolutions
* far ring: 560 m chunks at 28 m resolution
* every chunk is split into a SNOW and a ROCK part along a smooth contour
  of the rockiness field (Roblox needs one material per MeshPart; the
  triangles are cut along the contour); chunks whose height range would exceed the
  2048-stud MeshPart limit are subdivided automatically
* vertex normals come from the heightfield gradient -> seamless shading
* the visual terrain is lowered under rideable corridors so the corridor
  ribbon (which matches collision exactly) always sits on top
"""

import math

import numpy as np

from . import config
from .mathutil import smoothstep

MAX_SPAN_M = 0.97 * config.ROBLOX_MAX_PART_STUDS * config.METERS_PER_STUD  # ~557 m


def _grid_tris(nx, ny):
    i = np.arange(nx - 1)
    j = np.arange(ny - 1)
    I, J = np.meshgrid(i, j)
    a = (J * nx + I).ravel()
    b = a + 1
    c = a + nx
    d = c + 1
    # alternate diagonal for nicer shading
    flip = ((I + J) % 2 == 0).ravel()
    t1 = np.where(flip[:, None], np.column_stack([a, b, d]), np.column_stack([a, b, c]))
    t2 = np.where(flip[:, None], np.column_stack([a, d, c]), np.column_stack([b, d, c]))
    return np.vstack([t1, t2])


class ChunkMesh:
    def __init__(self, name, verts, tris, normals, colors, uvs, rock_mask, bounds):
        self.name = name
        self.verts = verts
        self.tris = tris
        self.normals = normals
        self.colors = colors
        self.uvs = uvs
        self.rock_mask = rock_mask  # per triangle
        self.bounds = bounds


def visual_height(T, x, y):
    """Terrain height for the visual mesh (lowered under corridors)."""
    h = T.height(x, y)
    if np.ndim(x) == 0:
        return h
    inside = T.inside_detail(x, y)
    if not np.any(inside):
        return h
    xc, yc = np.clip(x, T.x0, T.x1), np.clip(y, T.y0, T.y1)
    ce = np.where(inside, T.corridor_dist(xc, yc), 1e3)
    cover = np.where(inside, T.ribbon_grid.bilinear(xc, yc), 0.0)
    lower = config.CORRIDOR_LOWER_TERRAIN_M * (1.0 - smoothstep(-4.0, 1.5, ce)) * cover
    return h - lower


def _normals(T, x, y, eps):
    hx = (T.height(x + eps, y) - T.height(x - eps, y)) / (2 * eps)
    hy = (T.height(x, y + eps) - T.height(x, y - eps)) / (2 * eps)
    n = np.column_stack([-hx, -hy, np.ones_like(hx)])
    return n / np.linalg.norm(n, axis=1, keepdims=True)


def build_chunk(T, name, x0, y0, x1, y1, res, nb, skirt=3.0):
    nx = int(round((x1 - x0) / res)) + 1
    ny = int(round((y1 - y0) / res)) + 1
    xs = np.linspace(x0, x1, nx)
    ys = np.linspace(y0, y1, ny)
    X, Y = np.meshgrid(xs, ys)
    x = X.ravel()
    y = Y.ravel()
    z = visual_height(T, x, y)
    verts = np.column_stack([x, y, z])
    tris = _grid_tris(nx, ny)
    normals = _normals(T, x, y, max(res * 0.5, 1.0))
    # skirts around the border
    border = []
    for i in range(nx):
        border.append((0, i))
    for j in range(1, ny):
        border.append((j, nx - 1))
    for i in range(nx - 2, -1, -1):
        border.append((ny - 1, i))
    for j in range(ny - 2, 0, -1):
        border.append((j, 0))
    bidx = np.array([j * nx + i for j, i in border])
    nb_ = len(bidx)
    sk = verts[bidx].copy()
    sk[:, 2] -= skirt
    base = len(verts)
    verts = np.vstack([verts, sk])
    normals = np.vstack([normals, normals[bidx]])
    k = np.arange(nb_)
    k1 = (k + 1) % nb_
    st1 = np.column_stack([bidx[k], base + k, bidx[k1]])
    st2 = np.column_stack([bidx[k1], base + k, base + k1])
    n_surface = len(tris)
    tris = np.vstack([tris, st1, st2])
    # rock / snow: split the triangles along the 0.5 iso-line of the rockiness
    # field, so the material boundary is a smooth contour instead of a
    # triangle staircase (skirt vertices copy their border vertex)
    f = T.rock(x, y) - 0.5
    f = np.concatenate([f, f[bidx]])
    f = np.where(np.abs(f) < 1e-4, 1e-4, f)
    verts, normals, tris, rock, src = split_by_field(verts, normals, tris, f)
    # faces steeper than ~52 deg hold no snow (cliff and canyon walls span a
    # whole grid cell, so the vertex field alone would leave snow slivers)
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    fn = np.cross(b - a, c - a)
    nz = np.abs(fn[:, 2]) / np.maximum(np.linalg.norm(fn, axis=1), 1e-9)
    rock |= (nz < 0.62) & (src < n_surface)
    # vertex colours: soft occlusion in hollows + altitude tint
    zz = verts[:, 2]
    cav = nb.fbm("tcav", verts[:, 0], verts[:, 1], 60.0, octaves=3)
    shade = 0.93 + 0.05 * cav - 0.05 * np.clip(1.0 - normals[:, 2], 0, 1)
    warm = np.clip((200.0 - zz) / 600.0, 0, 0.04)
    colors = np.column_stack([shade + warm, shade + warm * 0.5, shade, np.ones(len(zz))])
    colors = np.clip(colors, 0, 1)
    uvs = verts[tris.reshape(-1)][:, :2] / 8.0
    return ChunkMesh(name, verts, tris, normals, colors, uvs, rock, (x0, y0, x1, y1))


def split_by_field(verts, normals, tris, f):
    """Split triangles along the zero contour of the per-vertex field f.
    Returns (verts, normals, tris, positive_mask, source_triangle_index).
    Contour vertices are shared
    by both neighbours of an edge, so the two material parts stay watertight;
    every output triangle keeps the winding of its source triangle."""
    n = len(verts)
    pos = f[tris] > 0
    cnt = pos.sum(axis=1)
    pure = (cnt == 0) | (cnt == 3)
    out_t = [tris[pure]]
    out_r = [cnt[pure] == 3]
    out_s = [np.where(pure)[0]]
    mt, mp, mc = tris[~pure], pos[~pure], cnt[~pure]
    msrc = np.where(~pure)[0]
    if len(mt) == 0:
        return verts, normals, tris, cnt == 3, np.arange(len(tris))
    # the isolated vertex: the only positive (cnt 1) or the only negative (cnt 2)
    iso = np.where(mc == 1, np.argmax(mp, axis=1), np.argmin(mp, axis=1))
    rows = np.arange(len(mt))
    v0 = mt[rows, iso]
    v1 = mt[rows, (iso + 1) % 3]
    v2 = mt[rows, (iso + 2) % 3]
    k01 = np.minimum(v0, v1) * n + np.maximum(v0, v1)
    k02 = np.minimum(v0, v2) * n + np.maximum(v0, v2)
    keys, inv = np.unique(np.concatenate([k01, k02]), return_inverse=True)
    i, j = keys // n, keys % n
    t = (f[i] / (f[i] - f[j]))[:, None]
    nv = verts[i] + t * (verts[j] - verts[i])
    nn = normals[i] + t * (normals[j] - normals[i])
    nn /= np.maximum(np.linalg.norm(nn, axis=1, keepdims=True), 1e-9)
    new = n + np.arange(len(keys))
    p01 = new[inv[:len(mt)]]
    p02 = new[inv[len(mt):]]
    iso_pos = mc == 1
    out_t += [np.column_stack([v0, p01, p02]), np.column_stack([p01, v1, v2]), np.column_stack([p01, v2, p02])]
    out_r += [iso_pos, ~iso_pos, ~iso_pos]
    out_s += [msrc, msrc, msrc]
    return (np.vstack([verts, nv]), np.vstack([normals, nn]), np.vstack(out_t).astype(np.int64),
            np.concatenate(out_r), np.concatenate(out_s))


def plan_detail_chunks(T):
    """Return list of (name, x0, y0, x1, y1, res)."""
    out = []
    size = config.CHUNK_SIZE_M
    xs = np.arange(T.x0, T.x1 - 1e-6, size)
    ys = np.arange(T.y0, T.y1 - 1e-6, size)
    for j, cy0 in enumerate(ys):
        for i, cx0 in enumerate(xs):
            cx1 = min(cx0 + size, T.x1)
            cy1 = min(cy0 + size, T.y1)
            # resolution: 5 m if corridors are within 150 m
            sx = np.linspace(cx0, cx1, 24)
            sy = np.linspace(cy0, cy1, 24)
            SX, SY = np.meshgrid(sx, sy)
            dmin = float(np.min(T.route_dist_coarse.bilinear(SX, SY)))
            res = config.TERRAIN_RES_NEAR if dmin < 150.0 else config.TERRAIN_RES_FAR
            out.append(("SV_TER_%02d_%02d" % (i, j), cx0, cy0, cx1, cy1, res))
    return out


def plan_far_chunks(T):
    out = []
    size = config.OUTER_CHUNK_SIZE_M
    xs = np.arange(config.OUTER_MIN_X, config.OUTER_MAX_X - 1e-6, size)
    ys = np.arange(config.OUTER_MIN_Y, config.OUTER_MAX_Y - 1e-6, size)
    for j, cy0 in enumerate(ys):
        for i, cx0 in enumerate(xs):
            cx1 = min(cx0 + size, config.OUTER_MAX_X)
            cy1 = min(cy0 + size, config.OUTER_MAX_Y)
            # skip cells fully inside the detail area
            if cx0 >= T.x0 and cx1 <= T.x1 and cy0 >= T.y0 and cy1 <= T.y1:
                continue
            out.append(("SV_FAR_%02d_%02d" % (i, j), cx0, cy0, cx1, cy1, config.OUTER_RES))
    return out


def split_if_tall(T, plan, sample=True):
    """Kept for API compatibility: tall chunks are split into elevation
    bands after meshing (see band_split)."""
    return sorted(plan)


def band_split(verts, tris, max_span=MAX_SPAN_M - 25.0):
    """Split a triangle set into elevation bands whose AABB height stays
    below the Roblox part limit. Returns list of triangle index arrays."""
    zc = verts[tris].mean(axis=1)[:, 2]
    zmin, zmax = zc.min(), zc.max()
    tri_z = verts[tris][:, :, 2]
    full = tri_z.max() - tri_z.min()
    if full <= max_span:
        return [np.arange(len(tris))]
    n = int(np.ceil((zmax - zmin) / max_span)) + 0
    n = max(2, n)
    edges = np.linspace(zmin, zmax + 1e-3, n + 1)
    out = []
    for k in range(n):
        sel = np.where((zc >= edges[k]) & (zc < edges[k + 1]))[0]
        if len(sel):
            out.append(sel)
    return out


def far_height_mask(T):
    """Outside the detail area, chunks sample the outer macro grid."""
    return None
