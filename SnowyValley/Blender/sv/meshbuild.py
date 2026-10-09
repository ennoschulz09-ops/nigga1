"""Procedural geometry builder (pure numpy, no bpy).

Assets are assembled from primitives into per-material parts. Each part
later becomes its own Blender object / Roblox MeshPart (Roblox allows one
material per MeshPart).  UVs are box-projected at a fixed texel density
(meters per tile) so Roblox material textures tile consistently.
"""

import math

import numpy as np

# meters per UV tile for each material family (consistent texel density)
UV_TILE = {"default": 4.0}


def rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=float)


def rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=float)


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=float)


def frame_from_dir(d, up=(0, 0, 1)):
    """Rotation matrix whose local +Z points along d."""
    d = np.asarray(d, dtype=float)
    d = d / np.linalg.norm(d)
    up = np.asarray(up, dtype=float)
    if abs(np.dot(d, up)) > 0.98:
        up = np.array([1.0, 0, 0])
    x = np.cross(up, d)
    x /= np.linalg.norm(x)
    y = np.cross(d, x)
    return np.column_stack([x, y, d])


class Part:
    __slots__ = ("verts", "faces", "colors", "uv_tile", "smooth", "vuvs")

    def __init__(self, uv_tile=4.0, smooth=False):
        self.verts = []
        self.faces = []
        self.colors = []
        self.uv_tile = uv_tile
        self.smooth = smooth
        self.vuvs = None   # optional explicit per-vertex UVs (palette atlases)


class MeshBuilder:
    def __init__(self):
        self.parts = {}

    def part(self, mat, uv_tile=None, smooth=None):
        if mat not in self.parts:
            self.parts[mat] = Part(uv_tile or UV_TILE.get(mat, UV_TILE["default"]),
                                   bool(smooth))
        p = self.parts[mat]
        if smooth is not None:
            p.smooth = p.smooth or smooth
        return p

    # ------------------------------------------------------------------
    def add(self, mat, verts, faces, color=(1, 1, 1, 1), smooth=None, uv_tile=None,
            closed=False, double_sided=False):
        """Add geometry. closed=True: winding is fixed so the signed volume is
        positive (outward normals). double_sided: also add reversed faces."""
        p = self.part(mat, uv_tile, smooth)
        base = sum(len(v) for v in p.verts)
        v = np.asarray(verts, dtype=float).reshape(-1, 3)
        faces = [tuple(f) for f in faces]
        if closed and faces:
            vol = 0.0
            for f in faces:
                for k in range(1, len(f) - 1):
                    vol += np.dot(v[f[0]], np.cross(v[f[k]], v[f[k + 1]]))
            if vol < 0:
                faces = [tuple(reversed(f)) for f in faces]
        if double_sided:
            faces = faces + [tuple(reversed(f)) for f in faces]
        p.verts.append(v)
        p.faces.extend([tuple(int(i) + base for i in f) for f in faces])
        c = np.asarray(color, dtype=float)
        if c.ndim == 1:
            c = np.tile(c, (len(v), 1))
        p.colors.append(c)
        return base

    def merge(self, other, matrix=None, offset=(0, 0, 0), mat_map=None):
        M = np.eye(3) if matrix is None else np.asarray(matrix, dtype=float)
        off = np.asarray(offset, dtype=float)
        for mat, p in other.parts.items():
            if not p.verts:
                continue
            tgt = mat_map.get(mat, mat) if mat_map else mat
            v = np.vstack(p.verts) @ M.T + off
            self.add(tgt, v, p.faces, np.vstack(p.colors), smooth=p.smooth, uv_tile=p.uv_tile)

    def transform(self, matrix=None, offset=(0, 0, 0)):
        M = np.eye(3) if matrix is None else np.asarray(matrix, dtype=float)
        off = np.asarray(offset, dtype=float)
        for p in self.parts.values():
            p.verts = [v @ M.T + off for v in p.verts]

    def bounds(self):
        allv = [np.vstack(p.verts) for p in self.parts.values() if p.verts]
        if not allv:
            return np.zeros(3), np.zeros(3)
        v = np.vstack(allv)
        return v.min(axis=0), v.max(axis=0)

    def tri_count(self):
        n = 0
        for p in self.parts.values():
            for f in p.faces:
                n += len(f) - 2
        return n

    # ------------------------------------------------------------------
    # primitives (all return the base index)
    # ------------------------------------------------------------------
    def box(self, mat, center, size, matrix=None, color=(1, 1, 1, 1), bevel=0.0):
        sx, sy, sz = (np.asarray(size, dtype=float) * 0.5)
        if bevel > 0:
            return self.rounded_box(mat, center, size, bevel, matrix, color)
        v = np.array([[-sx, -sy, -sz], [sx, -sy, -sz], [sx, sy, -sz], [-sx, sy, -sz],
                      [-sx, -sy, sz], [sx, -sy, sz], [sx, sy, sz], [-sx, sy, sz]])
        if matrix is not None:
            v = v @ np.asarray(matrix).T
        v = v + np.asarray(center, dtype=float)
        f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
        return self.add(mat, v, f, color, closed=True)

    def rounded_box(self, mat, center, size, r, matrix=None, color=(1, 1, 1, 1)):
        """Box with chamfered vertical edges (cheap bevel)."""
        sx, sy, sz = (np.asarray(size, dtype=float) * 0.5)
        r = min(r, sx * 0.9, sy * 0.9)
        ring = [(-sx + r, -sy), (sx - r, -sy), (sx, -sy + r), (sx, sy - r),
                (sx - r, sy), (-sx + r, sy), (-sx, sy - r), (-sx, -sy + r)]
        return self.prism(mat, ring, -sz, sz, center=center, matrix=matrix, color=color)

    def prism(self, mat, poly2d, z0, z1, center=(0, 0, 0), matrix=None, color=(1, 1, 1, 1),
              cap_bottom=True, cap_top=True):
        """Extrude a convex-ish CCW polygon between z0 and z1."""
        n = len(poly2d)
        v = [(x, y, z0) for x, y in poly2d] + [(x, y, z1) for x, y in poly2d]
        v = np.asarray(v, dtype=float)
        if matrix is not None:
            v = v @ np.asarray(matrix).T
        v = v + np.asarray(center, dtype=float)
        f = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
        if cap_bottom:
            f.append(tuple(reversed(range(n))))
        if cap_top:
            f.append(tuple(range(n, 2 * n)))
        return self.add(mat, v, f, color, closed=cap_bottom and cap_top)

    def cylinder(self, mat, p0, p1, r0, r1=None, seg=8, caps=True, color=(1, 1, 1, 1), phase=0.0):
        r1 = r0 if r1 is None else r1
        p0 = np.asarray(p0, dtype=float)
        p1 = np.asarray(p1, dtype=float)
        R = frame_from_dir(p1 - p0)
        ang = phase + np.arange(seg) * 2 * math.pi / seg
        ring = np.column_stack([np.cos(ang), np.sin(ang), np.zeros(seg)])
        v0 = (ring * r0) @ R.T + p0
        v1 = (ring * r1) @ R.T + p1
        verts = np.vstack([v0, v1])
        faces = [(i, (i + 1) % seg, seg + (i + 1) % seg, seg + i) for i in range(seg)]
        if caps:
            faces.append(tuple(reversed(range(seg))))
            if r1 > 1e-6:
                faces.append(tuple(range(seg, 2 * seg)))
        return self.add(mat, verts, faces, color, closed=caps)

    def cone(self, mat, base, tip, r, seg=8, color=(1, 1, 1, 1), cap=True, phase=0.0):
        base = np.asarray(base, dtype=float)
        tip = np.asarray(tip, dtype=float)
        R = frame_from_dir(tip - base)
        ang = phase + np.arange(seg) * 2 * math.pi / seg
        ring = np.column_stack([np.cos(ang), np.sin(ang), np.zeros(seg)]) * r
        verts = np.vstack([ring @ R.T + base, tip[None, :]])
        faces = [(i, (i + 1) % seg, seg) for i in range(seg)]
        if cap:
            faces.append(tuple(reversed(range(seg))))
        return self.add(mat, verts, faces, color, closed=cap)

    def lathe(self, mat, profile, seg=12, center=(0, 0, 0), color=(1, 1, 1, 1), matrix=None,
              cap_top=False, cap_bottom=False, smooth=None):
        """Revolve (r, z) profile around local Z."""
        prof = np.asarray(profile, dtype=float)
        m = len(prof)
        ang = np.arange(seg) * 2 * math.pi / seg
        verts = []
        for r, z in prof:
            for a in ang:
                verts.append((r * math.cos(a), r * math.sin(a), z))
        verts = np.asarray(verts)
        if matrix is not None:
            verts = verts @ np.asarray(matrix).T
        verts = verts + np.asarray(center, dtype=float)
        faces = []
        for i in range(m - 1):
            for j in range(seg):
                a = i * seg + j
                b = i * seg + (j + 1) % seg
                faces.append((a, b, b + seg, a + seg))
        if cap_bottom:
            faces.append(tuple(reversed(range(seg))))
        if cap_top:
            faces.append(tuple(range((m - 1) * seg, m * seg)))
        if cap_bottom and cap_top:
            return self.add(mat, verts, faces, color, smooth=smooth, closed=True)
        c0 = np.asarray(center, dtype=float)
        votes = 0.0
        for f in faces[:seg]:
            a, b, c = verts[f[0]], verts[f[1]], verts[f[2]]
            nrm = np.cross(b - a, c - a)
            radial = (a + b + c) / 3.0 - c0
            radial[2] = 0.0
            votes += float(np.dot(nrm, radial))
        if votes < 0:
            faces = [tuple(reversed(f)) for f in faces]
        return self.add(mat, verts, faces, color, smooth=smooth)

    def sweep(self, mat, path, profile, closed_profile=True, up=(0, 0, 1), color=(1, 1, 1, 1),
              smooth=None, scales=None, cap=False):
        """Sweep a 2D profile (x = right, y = up) along a 3D polyline."""
        path = np.asarray(path, dtype=float)
        prof = np.asarray(profile, dtype=float)
        n, m = len(path), len(prof)
        tang = np.gradient(path, axis=0)
        tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
        upv = np.asarray(up, dtype=float)
        verts = []
        for i in range(n):
            t = tang[i]
            right = np.cross(t, upv)
            if np.linalg.norm(right) < 1e-6:
                right = np.array([1.0, 0, 0])
            right /= np.linalg.norm(right)
            u = np.cross(right, t)
            sc = 1.0 if scales is None else scales[i]
            for px, py in prof:
                verts.append(path[i] + right * px * sc + u * py * sc)
        verts = np.asarray(verts)
        faces = []
        mm = m if closed_profile else m - 1
        for i in range(n - 1):
            for j in range(mm):
                a = i * m + j
                b = i * m + (j + 1) % m
                faces.append((a, b, b + m, a + m))
        if cap and closed_profile:
            faces.append(tuple(reversed(range(m))))
            faces.append(tuple(range((n - 1) * m, n * m)))
            return self.add(mat, verts, faces, color, smooth=smooth, closed=True)
        if faces:
            # orient so that normals point away from the path (outwards)
            out_votes = 0.0
            for f in faces[: max(1, len(faces) // 7)][:40]:
                a, b, c = verts[f[0]], verts[f[1]], verts[f[2]]
                nrm = np.cross(b - a, c - a)
                i_ring = f[0] // m
                out_votes += float(np.dot(nrm, (a + b + c) / 3.0 - path[i_ring]))
            if out_votes < 0:
                faces = [tuple(reversed(f)) for f in faces]
        return self.add(mat, verts, faces, color, smooth=smooth)

    def ico(self, mat, center, radius, subdiv=1, color=(1, 1, 1, 1), smooth=None, scale=(1, 1, 1),
            matrix=None):
        v, f = icosphere(subdiv)
        v = v * radius * np.asarray(scale, dtype=float)
        if matrix is not None:
            v = v @ np.asarray(matrix).T
        v = v + np.asarray(center, dtype=float)
        return self.add(mat, v, f, color, smooth=smooth, closed=True)

    def quad(self, mat, a, b, c, d, color=(1, 1, 1, 1)):
        return self.add(mat, [a, b, c, d], [(0, 1, 2, 3)], color)


_ICO_CACHE = {}


def icosphere(subdiv=1):
    if subdiv in _ICO_CACHE:
        v, f = _ICO_CACHE[subdiv]
        return v.copy(), list(f)
    t = (1.0 + math.sqrt(5.0)) / 2.0
    verts = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t),
             (0, -1, -t), (0, 1, -t), (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    faces = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4),
             (11, 10, 2), (10, 7, 6), (7, 1, 8), (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8),
             (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
    verts = [np.array(v, dtype=float) / np.linalg.norm(v) for v in verts]
    for _ in range(subdiv):
        cache = {}
        nf = []

        def mid(a, b):
            key = (min(a, b), max(a, b))
            if key not in cache:
                m = (verts[a] + verts[b]) / 2
                verts.append(m / np.linalg.norm(m))
                cache[key] = len(verts) - 1
            return cache[key]

        for a, b, c in faces:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            nf += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        faces = nf
    v = np.asarray(verts)
    _ICO_CACHE[subdiv] = (v, faces)
    return v.copy(), list(faces)


# ---------------------------------------------------------------------------
# mesh arrays: flatten a Part into numpy arrays + box-projected UVs
# ---------------------------------------------------------------------------

def part_arrays(p, world_uv_offset=(0.0, 0.0, 0.0)):
    """Return verts (N,3), triangles (M,3), loop uvs (M*3,2), vertex colors (N,4)."""
    verts = np.vstack(p.verts) if p.verts else np.zeros((0, 3))
    cols = np.vstack(p.colors) if p.colors else np.zeros((0, 4))
    tris = []
    for f in p.faces:
        for k in range(1, len(f) - 1):
            tris.append((f[0], f[k], f[k + 1]))
    tris = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
    if p.vuvs is not None:
        uvs = np.asarray(p.vuvs, dtype=float)[tris.reshape(-1)]
    else:
        uvs = box_uvs(verts, tris, p.uv_tile, world_uv_offset)
    return verts, tris, uvs, cols


def bake_palette(builder, target_mat, mapping, uv_of):
    """Merge parts into one palette-textured part.

    mapping: source material -> palette key; uv_of(key) -> (u, v).
    Returns a new MeshBuilder with a single part `target_mat`.
    """
    out = MeshBuilder()
    p_out = out.part(target_mat, smooth=False)
    vuvs = []
    base = 0
    for mat, p in builder.parts.items():
        if not p.verts:
            continue
        key = mapping[mat]
        v = np.vstack(p.verts)
        p_out.verts.append(v)
        p_out.colors.append(np.vstack(p.colors))
        p_out.faces.extend([tuple(i + base for i in f) for f in p.faces])
        vuvs.append(np.tile(np.asarray(uv_of(key), dtype=float), (len(v), 1)))
        base += len(v)
    p_out.vuvs = np.vstack(vuvs) if vuvs else np.zeros((0, 2))
    p_out.smooth = True
    return out


def box_uvs(verts, tris, tile, offset=(0, 0, 0)):
    if len(tris) == 0:
        return np.zeros((0, 2))
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    n = np.cross(b - a, c - a)
    ax = np.argmax(np.abs(n), axis=1)
    pts = verts[tris] + np.asarray(offset)          # (M,3,3)
    u = np.empty((len(tris), 3))
    v = np.empty((len(tris), 3))
    m0 = ax == 0
    m1 = ax == 1
    m2 = ax == 2
    u[m0], v[m0] = pts[m0][:, :, 1], pts[m0][:, :, 2]
    u[m1], v[m1] = pts[m1][:, :, 0], pts[m1][:, :, 2]
    u[m2], v[m2] = pts[m2][:, :, 0], pts[m2][:, :, 1]
    return np.column_stack([u.reshape(-1), v.reshape(-1)]) / tile
