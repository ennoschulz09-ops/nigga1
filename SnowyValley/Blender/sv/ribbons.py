"""Corridor ribbons: the visible riding surface (piste + off-piste margin).

Every ribbon vertex samples the same carved heightfield H that the Roblox
collision triangles sample, so what the rider sees is what the rider hits.
Bridge decks and the ice-cave floor use the analytic piste plane instead.

* triangles inside any route's piste width -> groomed piste material
* margins and skirts -> powder material
* alternative ribbons dip 0.18 m under the main ribbon where they overlap
  (no coplanar z-fighting in Roblox at junctions)
* coloured difficulty stripes along the piste edges (as on the reference)
"""

import math

import numpy as np

from . import config, routes

ROW_SPACING = 2.5
LAT_SPACING = 4.0
CHUNK_LEN = 340.0


class RibbonChunk:
    def __init__(self, name, route_id, s0, s1):
        self.name = name
        self.route_id = route_id
        self.s0, self.s1 = s0, s1
        self.parts = {}   # material -> (verts, tris, normals, uvs, colors)


def _layout_counts(Wmax, mlmax, mrmax, surface):
    n_p = max(2, int(math.ceil(Wmax / LAT_SPACING)))
    if surface != routes.SURF_GROUND:
        return n_p, 0, 0, False
    nl = max(1, int(math.ceil(mlmax / LAT_SPACING)))
    nr = max(1, int(math.ceil(mrmax / LAT_SPACING)))
    return n_p, nl, nr, True


def _row_offsets(W, ml, mr, counts):
    n_p, nl, nr, has_margin = counts
    piste = list(np.linspace(-W / 2, W / 2, n_p + 1))
    if not has_margin:
        return piste, 0, n_p
    left = [-W / 2 - ml * k / nl for k in range(nl, 0, -1)]
    right = [W / 2 + mr * k / nr for k in range(1, nr + 1)]
    skl = -W / 2 - ml - config.RIBBON_SKIRT_M
    skr = W / 2 + mr + config.RIBBON_SKIRT_M
    p0 = 1 + nl
    return [skl] + left + piste + right + [skr], p0, p0 + n_p


def main_corridor_dist(net, x, y):
    """Distance beyond the MAIN corridor edge (negative inside) for points."""
    m = net.main
    idx = np.arange(0, len(m.s), 2)
    mx, my = m.x[idx], m.y[idx]
    half = (m.width[idx] / 2 + np.maximum(m.margin_l[idx], m.margin_r[idx]))
    out = np.full(len(x), 1e3)
    for k in range(0, len(x), 2048):
        px = x[k:k + 2048, None]
        py = y[k:k + 2048, None]
        d = np.hypot(px - mx[None, :], py - my[None, :]) - half[None, :]
        out[k:k + 2048] = d.min(axis=1)
    return out


def build_route_ribbon(T, net, r):
    """Return list of RibbonChunk for route r."""
    L = r.length
    n_rows = int(math.ceil(L / ROW_SPACING)) + 1
    stations = np.linspace(0.0, L, n_rows)
    chunks = []
    n_chunks = max(1, int(math.ceil(L / CHUNK_LEN)))
    bounds = np.linspace(0, n_rows - 1, n_chunks + 1).round().astype(int)
    for c in range(n_chunks):
        i0, i1 = bounds[c], bounds[c + 1]
        ch = RibbonChunk("SV_RIB_%s_%02d" % (r.id, c), r.id, stations[i0], stations[i1])
        rows = []
        for i in range(i0, i1 + 1):
            s = stations[i]
            k = r.index_at(s)
            W = float(r.interp("width", s))
            ml = float(r.interp("margin_l", s))
            mr = float(r.interp("margin_r", s))
            surf = int(r.surface[k])
            rows.append((s, W, ml, mr, surf))
        _emit_rows(T, net, r, ch, rows)
        chunks.append(ch)
    return chunks


def _emit_rows(T, net, r, ch, rows):
    """Triangulate consecutive rows; rows with a different lateral layout
    (surface change) are bridged by resampling to the common layout."""
    # use a constant layout per chunk segment run (same surface type)
    runs = []
    cur = [rows[0]]
    for row in rows[1:]:
        if row[4] == cur[-1][4]:
            cur.append(row)
        else:
            cur.append(row)  # include boundary row in both runs
            runs.append(cur)
            cur = [row]
    runs.append(cur)
    for run in runs:
        surf = run[0][4]
        counts = _layout_counts(max(rw[1] for rw in run), max(rw[2] for rw in run),
                                max(rw[3] for rw in run), surf)
        has_margin = counts[3]
        _, p0, p1 = _row_offsets(run[0][1], run[0][2], run[0][3], counts)
        nlat = len(_row_offsets(run[0][1], run[0][2], run[0][3], counts)[0])
        P = np.zeros((len(run), nlat, 3))
        N = np.zeros((len(run), nlat, 3))
        U = np.zeros((len(run), nlat, 2))
        for a, (s, W, ml, mr, sf) in enumerate(run):
            offs, _, _ = _row_offsets(W, ml, mr, counts)
            cx, cy = float(r.interp("x", s)), float(r.interp("y", s))
            h = float(r.interp("heading_unwrapped", s))
            rx, ry = math.sin(h), -math.cos(h)
            d = np.asarray(offs)
            px = cx + rx * d
            py = cy + ry * d
            if surf == routes.SURF_GROUND and not routes.adjacent_to_span(r, s):
                pz = T.height(px, py)
                if has_margin:
                    pz[0] -= config.RIBBON_SKIRT_DEPTH_M
                    pz[-1] -= config.RIBBON_SKIRT_DEPTH_M
                eps = 1.0
                hx = (T.height(px + eps, py) - T.height(px - eps, py)) / (2 * eps)
                hy = (T.height(px, py + eps) - T.height(px, py - eps)) / (2 * eps)
                nrm = np.column_stack([-hx, -hy, np.ones_like(hx)])
            else:
                zc = float(r.interp("z", s))
                bank = float(r.interp("bank", s))
                pz = zc + d * math.tan(bank)
                if surf == routes.SURF_GROUND and has_margin:
                    pz[0] -= config.RIBBON_SKIRT_DEPTH_M
                    pz[-1] -= config.RIBBON_SKIRT_DEPTH_M
                g = float(r.interp("grad", s))
                tv = np.array([math.cos(h), math.sin(h), -g])
                lv = np.array([rx, ry, math.tan(bank)])
                nv = np.cross(lv, tv)
                if nv[2] < 0:
                    nv = -nv
                nrm = np.tile(nv / np.linalg.norm(nv), (len(d), 1))
            P[a, :, 0], P[a, :, 1], P[a, :, 2] = px, py, pz
            N[a] = nrm / np.linalg.norm(nrm, axis=1, keepdims=True)
            U[a, :, 0] = d / 8.0
            U[a, :, 1] = s / 8.0
        # alternatives dip under the main ribbon where they overlap it
        if r.kind == "alt":
            flat = P.reshape(-1, 3)
            md = main_corridor_dist(net, flat[:, 0], flat[:, 1])
            dip = np.where(md < 0.0, 0.18 + np.clip(-md, 0, 3.0) * 0.1, 0.0)
            flat[:, 2] -= dip
            P = flat.reshape(P.shape)
        verts = P.reshape(-1, 3)
        normals = N.reshape(-1, 3)
        nr = len(run)
        A, B = np.meshgrid(np.arange(nr - 1), np.arange(nlat - 1), indexing="ij")
        v00 = (A * nlat + B).ravel()
        v01 = v00 + 1
        v10 = v00 + nlat
        v11 = v10 + 1
        bcol = B.ravel()
        cxm = (verts[v00, 0] + verts[v11, 0]) * 0.5
        cym = (verts[v00, 1] + verts[v11, 1]) * 0.5
        if has_margin:
            inside = ((bcol >= p0) & (bcol < p1)) | (T.piste_dist(cxm, cym) < -0.5)
            # skirts are never groomed
            inside &= (bcol > 0) & (bcol < nlat - 2)
        else:
            inside = np.ones(len(bcol), dtype=bool)
        t1 = np.column_stack([v00, v10, v11])
        t2 = np.column_stack([v00, v11, v01])
        for mat, sel in (("SV_PisteGroomed", inside), ("SV_Powder", ~inside)):
            if not np.any(sel):
                continue
            tl = np.vstack([t1[sel], t2[sel]])
            tl = _fix_winding(verts, tl)
            used = np.unique(tl)
            remap = -np.ones(len(verts), dtype=np.int64)
            remap[used] = np.arange(len(used))
            v = verts[used]
            n = normals[used]
            t = remap[tl]
            uv = U.reshape(-1, 2)[used][t.reshape(-1)]
            col = np.ones((len(v), 4))
            _append(ch, mat, v, t, n, uv, col)


def _fix_winding(verts, tris):
    a, b, c = verts[tris[:, 0]], verts[tris[:, 1]], verts[tris[:, 2]]
    nz = np.cross(b - a, c - a)[:, 2]
    flip = nz < 0
    out = tris.copy()
    out[flip] = out[flip][:, [0, 2, 1]]
    return out


def _append(ch, mat, v, t, n, uv, col):
    if mat in ch.parts:
        V, Tt, Nn, UV, C = ch.parts[mat]
        base = len(V)
        ch.parts[mat] = (np.vstack([V, v]), np.vstack([Tt, t + base]), np.vstack([Nn, n]),
                         np.vstack([UV, uv]), np.vstack([C, col]))
    else:
        ch.parts[mat] = (v, t, n, uv, col)


def build_edge_stripes(T, net, r, width=0.8, lift=0.09, spacing=2.5):
    """Coloured difficulty lines on both piste edges, skipped inside other pistes."""
    L = r.length
    st = np.arange(0.0, L, spacing)
    segs = []
    for side in (-1, 1):
        cur = []
        for s in st:
            k = r.index_at(s)
            if r.surface[k] == routes.SURF_TUNNEL:
                if cur:
                    segs.append(cur)
                    cur = []
                continue
            W = float(r.interp("width", s))
            h = float(r.interp("heading_unwrapped", s))
            rx, ry = math.sin(h), -math.cos(h)
            cx, cy = float(r.interp("x", s)), float(r.interp("y", s))
            d0 = side * (W / 2 - 0.6)
            d1 = side * (W / 2 - 0.6 - width)
            pts = []
            for d in (d0, d1):
                px, py = cx + rx * d, cy + ry * d
                if r.surface[k] == routes.SURF_GROUND:
                    pz = float(T.height(px, py))
                else:
                    pz = float(r.interp("z", s)) + d * math.tan(float(r.interp("bank", s)))
                pts.append((px, py, pz + lift))
            # skip where this edge lies inside another route's piste (junctions)
            ex, ey = cx + rx * side * W / 2, cy + ry * side * W / 2
            inside_other = float(T.piste_dist(ex, ey)) < -1.0
            if r.kind == "alt":
                inside_other = inside_other or float(main_corridor_dist(net, np.array([ex]), np.array([ey]))[0]) < 0
            if inside_other:
                if len(cur) > 1:
                    segs.append(cur)
                cur = []
                continue
            cur.append(pts)
        if len(cur) > 1:
            segs.append(cur)
    verts, tris = [], []
    for seg in segs:
        base = len(verts)
        for a, b in seg:
            verts.append(a)
            verts.append(b)
        for i in range(len(seg) - 1):
            v0 = base + 2 * i
            tris.append((v0, v0 + 2, v0 + 3))
            tris.append((v0, v0 + 3, v0 + 1))
    if not tris:
        return None
    verts = np.asarray(verts)
    tris = _fix_winding(verts, np.asarray(tris, dtype=np.int64))
    return verts, tris
