"""Unique set pieces built from route + terrain data, in WORLD coordinates:
stone arch bridge, ice cave tunnel, frozen lake / waterfall / ponds / creek
ice, plaza paving.  Each returns a MeshBuilder plus metadata (lights,
collision helpers) consumed by the placement / export stages.
"""

import math

import numpy as np

from . import routes
from .mathutil import NoiseBank
from .meshbuild import MeshBuilder


def _frame(r, s):
    p = r.point(s)
    t = r.tangent(s)
    rt = np.array([t[1], -t[0]])
    return p, t, rt


# ---------------------------------------------------------------------------
# stone arch bridge (section 08)
# ---------------------------------------------------------------------------

def build_bridge(T, net):
    m = net.main
    br = T.features["bridge"]
    s0, s1 = br["s0"], br["s1"]
    W = float(m.interp("width", 0.5 * (s0 + s1)))
    half = W / 2 + 1.1                     # deck + parapet footprint
    ext0, ext1 = s0 - 10.0, s1 + 10.0      # abutments reach onto the banks
    ss = np.arange(ext0, ext1 + 0.01, 2.0)
    deck = np.array([float(m.interp("z", s)) for s in ss])
    # ground profile under the bridge axis (min over the deck width)
    ground = []
    for s in ss:
        p, t, rt = _frame(m, s)
        g = min(float(T.height(p[0] + rt[0] * d, p[1] + rt[1] * d)) for d in (-half, 0.0, half))
        ground.append(g)
    ground = np.array(ground)
    # arch layout: central pier at the ravine's lowest point
    ib = int(np.argmin(ground))
    u = ss - ext0
    L = u[-1]
    pier_u = u[ib]
    pier_w = 7.0
    arches = [(6.0, pier_u - pier_w / 2), (pier_u + pier_w / 2, L - 6.0)]
    intrados = np.full(len(u), -1e9)
    arch_info = []
    for ua, ub in arches:
        if ub - ua < 10:
            continue
        um = 0.5 * (ua + ub)
        hs = 0.5 * (ub - ua)
        ia, ib2 = np.searchsorted(u, ua), np.searchsorted(u, ub)
        spring = max(min(ground[max(ia - 1, 0)], ground[min(ib2, len(u) - 1)]) + 1.5,
                     ground[ia:ib2].min() + 2.0 if ib2 > ia else ground[ia])
        crown = float(np.interp(um, u, deck)) - 3.2
        spring = min(spring, crown - 6.0)
        inside = (u > ua) & (u < ub)
        t = (u[inside] - um) / hs
        intrados[inside] = spring + (crown - spring) * np.sqrt(np.clip(1 - t * t, 0, 1))
        arch_info.append(dict(ua=ua, ub=ub, spring=spring, crown=crown))
    top = deck - 0.06
    bottom = np.where(intrados > -1e8, intrados, ground - 4.0)
    bottom = np.minimum(bottom, top - 1.2)

    mb = MeshBuilder()
    # body: for each strip build a quad on both faces + soffit + top cap
    def P(i, d, z):
        p, t, rt = _frame(m, ss[i])
        return (p[0] + rt[0] * d, p[1] + rt[1] * d, z)

    verts, faces = [], []
    for i in range(len(ss)):
        for d in (-half, half):
            verts.append(P(i, d, top[i]))
            verts.append(P(i, d, bottom[i]))
    # vertex index helper: (i, side 0/1, top 0/bottom 1)
    def vi(i, side, tb):
        return i * 4 + side * 2 + tb
    for i in range(len(ss) - 1):
        # faces on both sides
        faces.append((vi(i, 0, 0), vi(i, 0, 1), vi(i + 1, 0, 1), vi(i + 1, 0, 0)))
        faces.append((vi(i, 1, 0), vi(i + 1, 1, 0), vi(i + 1, 1, 1), vi(i, 1, 1)))
        # soffit (underside)
        faces.append((vi(i, 0, 1), vi(i, 1, 1), vi(i + 1, 1, 1), vi(i + 1, 0, 1)))
        # top (under the deck ribbon, hidden but closes the solid)
        faces.append((vi(i, 0, 0), vi(i + 1, 0, 0), vi(i + 1, 1, 0), vi(i, 1, 0)))
    n = len(ss) - 1
    faces.append((vi(0, 0, 0), vi(0, 1, 0), vi(0, 1, 1), vi(0, 0, 1)))
    faces.append((vi(n, 0, 0), vi(n, 0, 1), vi(n, 1, 1), vi(n, 1, 0)))
    mb.add("SV_StoneBlock", verts, faces, closed=True)

    # arch rings (voussoir bands) + icicles + ice glow beneath
    lights, icicles = [], []
    for a in arch_info:
        ring = []
        for k in range(25):
            t = -1 + 2 * k / 24
            uu = 0.5 * (a["ua"] + a["ub"]) + t * 0.5 * (a["ub"] - a["ua"])
            zz = a["spring"] + (a["crown"] - a["spring"]) * math.sqrt(max(0.0, 1 - t * t))
            ring.append((uu, zz))
        for d in (-half - 0.25, half + 0.25):
            pts = []
            for uu, zz in ring:
                s = ext0 + uu
                p, t_, rt = _frame(m, s)
                pts.append((p[0] + rt[0] * d, p[1] + rt[1] * d, zz))
            mb.sweep("SV_Stone", pts, [(-0.5, -0.9), (0.5, -0.9), (0.5, 0.6), (-0.5, 0.6)],
                     closed_profile=True, up=(0, 0, 1))
        cs = ext0 + 0.5 * (a["ua"] + a["ub"])
        p, t_, rt = _frame(m, cs)
        lights.append(dict(pos=(p[0], p[1], a["crown"] - 6.0), color=(120, 200, 255), range=60, brightness=2.2))
        for k in range(-3, 4):
            q = ext0 + 0.5 * (a["ua"] + a["ub"]) + k * 4.0
            pp, _, rr = _frame(m, q)
            for d in (-half * 0.6, half * 0.6):
                zz = float(np.interp(q - ext0, u, bottom))
                icicles.append((pp[0] + rr[0] * d, pp[1] + rr[1] * d, zz))
    # parapets with snow caps and lamp posts
    for side in (-1, 1):
        d0 = side * (W / 2 + 0.55)
        pts = [P(i, d0, top[i] + 0.65) for i in range(len(ss))]
        mb.sweep("SV_Stone", pts, [(-0.55, -0.7), (0.55, -0.7), (0.5, 0.65), (-0.5, 0.65)],
                 closed_profile=True, up=(0, 0, 1))
        pts2 = [(x, y, z + 0.72) for x, y, z in pts]
        mb.sweep("SV_Snow", pts2, [(-0.5, -0.05), (0.5, -0.05), (0.38, 0.16), (-0.38, 0.16)],
                 closed_profile=True, up=(0, 0, 1))
    # icefalls under the arches: glowing frozen cascades in the ravine
    rv = T.features["ravine"]
    for k, a in enumerate(arch_info):
        cs = ext0 + 0.5 * (a["ua"] + a["ub"])
        p, t_, rt = _frame(m, cs)
        ztop = a["spring"] + 6.0
        g = float(T.height(p[0], p[1]))
        _ice_curtain(mb, (p[0], p[1]), t_, g, ztop, width=10.0, seed=50 + k)
    pier_s = ext0 + pier_u
    meta = dict(span=(s0, s1), ext=(ext0, ext1), half_width=half, deck_width=W, arches=arch_info,
                pier_s=pier_s, lights=lights, icicles=icicles,
                parapet_height=1.3)
    return mb, meta


def _ice_curtain(mb, base_xy, tangent, z_bottom, z_top, width, seed):
    """Frozen waterfall: corrugated vertical sheet facing along +/- tangent."""
    rng = np.random.default_rng(seed)
    nu, nv = 14, 8
    t = np.array([tangent[0], tangent[1], 0.0])
    lat = np.array([-tangent[1], tangent[0], 0.0])
    verts, faces, cols = [], [], []
    for j in range(nv + 1):
        z = z_top + (z_bottom - z_top) * j / nv
        for i in range(nu + 1):
            a = -width / 2 + width * i / nu
            bulge = 0.7 * math.sin(i * 1.7 + seed) + 0.4 * rng.uniform(-1, 1) + 1.2 * (j / nv)
            p = np.array([base_xy[0], base_xy[1], z]) + lat * a + t * bulge
            verts.append(tuple(p))
    for j in range(nv):
        for i in range(nu):
            a = j * (nu + 1) + i
            faces.append((a, a + 1, a + nu + 2, a + nu + 1))
    mb.add("SV_IceGlow", verts, faces, smooth=True, double_sided=True)


# ---------------------------------------------------------------------------
# ice cave (section 12)
# ---------------------------------------------------------------------------

def build_ice_cave(T, net, seed=12):
    m = net.main
    tun = T.features["tunnel"]
    t0, t1 = tun["s0"] - 4.0, tun["s1"] + 4.0
    W = float(m.interp("width", 0.5 * (t0 + t1)))
    a_in = W / 2 + 3.0
    h = tun["height"]
    thick = 2.6
    nb = NoiseBank(seed)
    # arch profile (left -> right, inner surface), ordered over the top
    prof = []
    for k in range(0, 3):
        prof.append((-a_in, 3.0 * k / 2))
    for k in range(1, 12):
        ang = math.pi - math.pi * k / 12
        prof.append((a_in * math.cos(ang), 3.0 + (h - 3.0) * math.sin(ang)))
    for k in range(2, -1, -1):
        prof.append((a_in, 3.0 * k / 2))
    prof = np.array(prof)
    ss = np.arange(t0, t1 + 0.01, 3.0)
    mb = MeshBuilder()
    rings_in, rings_out = [], []
    for s in ss:
        p, t, rt = _frame(m, s)
        z0 = float(m.interp("z", s))
        ring_i, ring_o = [], []
        for (d, z) in prof:
            x = p[0] + rt[0] * d
            y = p[1] + rt[1] * d
            zz = z0 + z
            # inward-facing icy displacement (none at the floor line)
            nrm = np.array([-rt[0] * np.sign(d) * (abs(d) / a_in), -rt[1] * np.sign(d) * (abs(d) / a_in),
                            -(z / h)])
            nn = np.linalg.norm(nrm)
            nrm = nrm / nn if nn > 1e-6 else nrm
            amp = 0.9 * min(1.0, z / 2.5)
            disp = amp * float(nb.fbm("cave", x * 0.7 + zz * 0.31, y * 0.7 - zz * 0.27, 4.0, octaves=3))
            ring_i.append((x + nrm[0] * disp, y + nrm[1] * disp, zz + nrm[2] * disp))
            ring_o.append((p[0] + rt[0] * d * (1 + thick / a_in), p[1] + rt[1] * d * (1 + thick / a_in),
                           z0 + (z * (h + thick) / h if z > 0 else z - 0.5)))
        rings_in.append(ring_i)
        rings_out.append(ring_o)
    npf = len(prof)
    # inner surface (faces point inwards) split into glacier / deep ice by noise
    vin = np.array(rings_in).reshape(-1, 3)
    faces_a, faces_b = [], []
    for i in range(len(ss) - 1):
        for j in range(npf - 1):
            a = i * npf + j
            f = (a, a + npf, a + npf + 1, a + 1)
            c = vin[list(f)].mean(axis=0)
            deep = nb.fbm("cavecol", c[0], c[1] + c[2], 9.0, octaves=2) > 0.18
            (faces_b if deep else faces_a).append(f)
    centres = np.array([[m.interp("x", s), m.interp("y", s), m.interp("z", s) + h * 0.45] for s in ss])
    votes = 0.0
    for f in (faces_a + faces_b)[:200]:
        a, b, c = vin[f[0]], vin[f[1]], vin[f[2]]
        nrm = np.cross(b - a, c - a)
        votes += float(np.dot(nrm, centres[f[0] // npf] - (a + b + c) / 3.0))
    if votes < 0:
        faces_a = [tuple(reversed(f)) for f in faces_a]
        faces_b = [tuple(reversed(f)) for f in faces_b]
    _add_subset(mb, "SV_Glacier", vin, faces_a, smooth=True)
    _add_subset(mb, "SV_IceDeep", vin, faces_b, smooth=True)
    # outer rock shell + end rings (portal faces)
    vout = np.array(rings_out).reshape(-1, 3)
    fo = []
    for i in range(len(ss) - 1):
        for j in range(npf - 1):
            a = i * npf + j
            fo.append((a, a + 1, a + npf + 1, a + npf))
    votes = 0.0
    for f in fo[:200]:
        a, b, c = vout[f[0]], vout[f[1]], vout[f[2]]
        nrm = np.cross(b - a, c - a)
        votes += float(np.dot(nrm, (a + b + c) / 3.0 - centres[f[0] // npf]))
    if votes < 0:
        fo = [tuple(reversed(f)) for f in fo]
    mb.add("SV_Rock", vout, fo, smooth=False)
    # floor strips between piste edge and wall (ice)
    for side in (-1, 1):
        fl = []
        for s in ss:
            p, t, rt = _frame(m, s)
            z0 = float(m.interp("z", s)) - 0.08
            for d in (side * (W / 2 - 0.3), side * a_in):
                fl.append((p[0] + rt[0] * d, p[1] + rt[1] * d, z0))
        ff = [(2 * i, 2 * i + 2, 2 * i + 3, 2 * i + 1) if side > 0 else (2 * i, 2 * i + 1, 2 * i + 3, 2 * i + 2)
              for i in range(len(ss) - 1)]
        mb.add("SV_Ice", fl, ff, smooth=False)
    # portal frames: chunky rock arch + snow cap at both ends
    for s in (t0, t1):
        p, t, rt = _frame(m, s)
        z0 = float(m.interp("z", s))
        pts = []
        for (d, z) in prof:
            pts.append((p[0] + rt[0] * d * 1.08, p[1] + rt[1] * d * 1.08, z0 + z * 1.06 + (0.4 if z > 0.5 else -0.5)))
        mb.sweep("SV_RockDark", pts, [(-1.6, -1.2), (1.6, -1.2), (1.4, 1.4), (-1.4, 1.4)],
                 closed_profile=True, up=(t[0], t[1], 0.0))
    # lights, crystals and icicles along the tunnel
    lights, crystals, icicles = [], [], []
    for k, s in enumerate(np.arange(tun["s0"] + 8.0, tun["s1"] - 4.0, 18.0)):
        p, t, rt = _frame(m, s)
        z0 = float(m.interp("z", s))
        lights.append(dict(pos=(p[0], p[1], z0 + h - 2.5), color=(150, 225, 255), range=42, brightness=2.6))
    for k, s in enumerate(np.arange(tun["s0"] + 4.0, tun["s1"] - 2.0, 9.0)):
        p, t, rt = _frame(m, s)
        z0 = float(m.interp("z", s))
        side = 1 if k % 2 == 0 else -1
        crystals.append(dict(pos=(p[0] + rt[0] * side * (a_in - 1.0), p[1] + rt[1] * side * (a_in - 1.0), z0 - 0.3),
                             yaw=math.atan2(t[1], t[0])))
        icicles.append(dict(pos=(p[0] + rt[0] * side * 4.0, p[1] + rt[1] * side * 4.0, z0 + h - 0.6)))
    meta = dict(span=(tun["s0"], tun["s1"]), inner_half_width=a_in, height=h, lights=lights,
                crystals=crystals, icicles=icicles)
    return mb, meta


def _add_subset(mb, mat, verts, faces, smooth):
    if not faces:
        return
    used = sorted({i for f in faces for i in f})
    remap = {o: n for n, o in enumerate(used)}
    mb.add(mat, verts[used], [tuple(remap[i] for i in f) for f in faces], smooth=smooth)


# ---------------------------------------------------------------------------
# frozen lake, ponds, creek ice
# ---------------------------------------------------------------------------

def build_ice_disk(e, z, seed, rim=True):
    rng = np.random.default_rng(seed)
    mb = MeshBuilder()
    na, nr = 40, 6
    ca, sa = math.cos(e["angle"]), math.sin(e["angle"])
    wob = 1.0 + 0.06 * np.sin(np.arange(na) * 3.0 / na * 2 * math.pi + seed) + rng.uniform(-0.03, 0.03, na)
    verts = [(e["x"], e["y"], z)]
    for k in range(1, nr + 1):
        rr = k / nr
        for i in range(na):
            a = 2 * math.pi * i / na
            u, v = e["a"] * 1.02 * rr * wob[i] * math.cos(a), e["b"] * 1.02 * rr * wob[i] * math.sin(a)
            verts.append((e["x"] + u * ca - v * sa, e["y"] + u * sa + v * ca, z))
    faces = []
    for i in range(na):
        faces.append((0, 1 + i, 1 + (i + 1) % na))
    for k in range(1, nr):
        b0 = 1 + (k - 1) * na
        b1 = 1 + k * na
        for i in range(na):
            faces.append((b0 + i, b1 + i, b1 + (i + 1) % na, b0 + (i + 1) % na))
    cols = [(1, 1, 1, 1)] * len(verts)
    mb.add("SV_Ice", verts, faces, cols)
    if rim:
        rv = []
        for i in range(na):
            a = 2 * math.pi * i / na
            for f, dz in ((1.0, 0.04), (1.14, 0.45)):
                u = e["a"] * f * wob[i] * math.cos(a)
                v = e["b"] * f * wob[i] * math.sin(a)
                rv.append((e["x"] + u * ca - v * sa, e["y"] + u * sa + v * ca, z + dz))
        rf = [(2 * i, 2 * ((i + 1) % na), 2 * ((i + 1) % na) + 1, 2 * i + 1) for i in range(na)]
        mb.add("SV_Snow", rv, rf, smooth=True)
    return mb


def ribbon_normals(pts):
    pts = np.asarray(pts, dtype=float)
    tang = np.gradient(pts, axis=0)
    tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
    return np.column_stack([-tang[:, 1], tang[:, 0]])


def build_ice_ribbon(T, pts, width, lift=0.25, mat="SV_Glacier", nrm=None):
    """Level ice strip along pts. Pass nrm (from the full polyline) when a long
    ribbon is built in pieces, so the pieces share identical joint vertices."""
    pts = np.asarray(pts, dtype=float)
    mb = MeshBuilder()
    if nrm is None:
        nrm = ribbon_normals(pts)
    verts = []
    for p, n in zip(pts, nrm):
        for s in (-1, 1):
            q = p + n * s * width / 2
            verts.append((q[0], q[1], float(T.height(q[0], q[1])) + lift))
    # flatten each cross-section to its lowest point (water surface is level)
    for i in range(len(pts)):
        z = min(verts[2 * i][2], verts[2 * i + 1][2])
        verts[2 * i] = (verts[2 * i][0], verts[2 * i][1], z)
        verts[2 * i + 1] = (verts[2 * i + 1][0], verts[2 * i + 1][1], z)
    faces = [(2 * i, 2 * i + 2, 2 * i + 3, 2 * i + 1) for i in range(len(pts) - 1)]
    mb.add(mat, verts, faces, smooth=True)
    return mb


def build_plaza_paving(T, center, radius, z):
    """Cobblestone ring around the finish runout (corridor stays snow). The
    outline is cut along smooth contours (circle + corridor edge)."""
    from .terrain_mesh import _grid_tris, split_by_field
    mb = MeshBuilder()
    step = 2.5
    xs = np.arange(center[0] - radius - step, center[0] + radius + step + 0.1, step)
    ys = np.arange(center[1] - radius - step, center[1] + radius + step + 0.1, step)
    X, Y = np.meshgrid(xs, ys)
    x, y = X.ravel(), Y.ravel()
    verts = np.column_stack([x, y, T.height(x, y) + 0.06])
    r = np.hypot(x - center[0], y - center[1])
    f = np.minimum(radius - r, T.corridor_dist(x, y) - 1.5)
    f = np.where(np.abs(f) < 1e-4, 1e-4, f)
    tris = _grid_tris(len(xs), len(ys))
    tris = tris[np.any(f[tris] > 0, axis=1)]
    normals = np.tile([0.0, 0.0, 1.0], (len(verts), 1))
    v2, _, t2, inside, _src = split_by_field(verts, normals, tris, f)
    faces = t2[inside]
    used = np.unique(faces)
    remap = -np.ones(len(v2), dtype=np.int64)
    remap[used] = np.arange(len(used))
    mb.add("SV_Stone", v2[used], [tuple(int(i) for i in fc) for fc in remap[faces]], smooth=True)
    return mb
