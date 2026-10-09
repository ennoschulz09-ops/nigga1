"""Gondola cableways: station placement, automatic pylon placement with
cable clearance, cable loop paths (for Roblox animation) and cabin layout.

Line A: summit (upper station, west of the start) -> mid station -> valley
        station on the WEST edge of the village (deliberately not at the
        finish plaza).
Line B: east flank top station -> east valley station.
"""

import math

import numpy as np

from . import bl, config
from .assets_props import CABIN_HANG, GAUGE, PYLON_HEIGHTS
from .assets_buildings import STATION_VARIANTS

CLEARANCE = 12.0     # min cable height above ground (m)
MAX_SPAN = 340.0
SAG_RATIO = 0.018
CABIN_SPACING = 72.0  # m along the loop
SPEED = 5.0           # m/s

LINES = [
    dict(id="A", name="Snowy Valley Gondola", stations=[
        ("StationValley", (-440.0, -1050.0)),
        ("StationMid", (-440.0, 318.0)),
        ("StationTop", (-52.0, 930.0)),
    ]),
    dict(id="B", name="East Ridge Gondola", stations=[
        ("StationValley", (488.0, -985.0)),
        ("StationTop", (612.0, 410.0)),
    ]),
]


def _station_cable_z(T, kind, xy):
    return float(T.height(xy[0], xy[1])) + 1.5 + STATION_VARIANTS[kind]["cable_z"]


def plan_line(T, a_xy, a_z, b_xy, b_z, log=None):
    """Return list of support dicts (pylons) between two stations."""
    a = np.asarray(a_xy, dtype=float)
    b = np.asarray(b_xy, dtype=float)
    L = float(np.linalg.norm(b - a))
    d = (b - a) / L
    us = np.arange(0.0, L + 0.01, 4.0)
    pts = a[None, :] + us[:, None] * d[None, :]
    g = T.height(pts[:, 0], pts[:, 1])
    # both cable tracks (+- gauge/2) and the cabin width must clear the ground
    right = np.array([d[1], -d[0]])
    half = GAUGE / 2 + 1.5
    g_cab = np.maximum(g, np.maximum(T.height(pts[:, 0] + right[0] * half, pts[:, 1] + right[1] * half),
                                     T.height(pts[:, 0] - right[0] * half, pts[:, 1] - right[1] * half)))
    ce = np.array([float(T.corridor_dist(p[0], p[1])) if T.inside_detail(p[0], p[1]) else 1e3 for p in pts])
    # cable must also clear pistes by an extra margin
    req = g_cab + CLEARANCE + np.where(ce < 3.0, 3.0, 0.0)
    supports = [(0.0, a_z)]
    pylons = []
    heights = sorted(PYLON_HEIGHTS.items(), key=lambda kv: kv[1])

    def span_ok(u0, z0, u1, z1):
        sel = (us > u0) & (us < u1)
        if not np.any(sel):
            return True
        t = (us[sel] - u0) / (u1 - u0)
        sag = SAG_RATIO * (u1 - u0)
        zc = z0 + (z1 - z0) * t - 4 * sag * t * (1 - t)
        return bool(np.all(zc >= req[sel]))

    guard = 0
    while guard < 60:
        guard += 1
        u0, z0 = supports[-1]
        if L - u0 <= MAX_SPAN and span_ok(u0, z0, L, b_z):
            break
        best = None
        for i in range(len(us) - 1, -1, -1):
            u1 = us[i]
            if u1 <= u0 + 40.0 or u1 - u0 > MAX_SPAN or u1 > L - 30.0:
                continue
            if ce[i] < 7.0:
                continue
            for name, h in heights:
                z1 = g[i] + h + 0.75
                if span_ok(u0, z0, u1, z1):
                    best = (u1, z1, name, h, i)
                    break
            if best:
                break
        if best is None:
            # fall back: tallest pylon at the furthest legal spot
            for i in range(len(us) - 1, -1, -1):
                u1 = us[i]
                if u0 + 40.0 < u1 <= u0 + MAX_SPAN and ce[i] >= 7.0:
                    name, h = heights[-1]
                    best = (u1, g[i] + h + 0.75, name, h, i)
                    break
        if best is None:
            break
        u1, z1, name, h, i = best
        supports.append((u1, z1))
        pylons.append(dict(asset=name, u=float(u1), pos=(float(pts[i][0]), float(pts[i][1]), float(g[i])),
                           cable_z=float(z1), dir=(float(d[0]), float(d[1]))))
    supports.append((L, b_z))
    return pylons, supports, d, L


def build_lines(ctx, P):
    T = ctx.T
    lines_meta = []
    for line in LINES:
        st = []
        for kind, xy in line["stations"]:
            st.append(dict(asset=kind, xy=xy, cable_z=_station_cable_z(T, kind, xy),
                           ground=float(T.height(xy[0], xy[1]))))
        segs = []
        for k in range(len(st) - 1):
            pylons, supports, d, L = plan_line(T, st[k]["xy"], st[k]["cable_z"], st[k + 1]["xy"],
                                               st[k + 1]["cable_z"])
            segs.append(dict(pylons=pylons, supports=supports, dir=d, length=L, a=st[k], b=st[k + 1]))
        # stations: open end (+Y) faces along the line
        for k, s in enumerate(st):
            if k == 0:
                d = segs[0]["dir"]
            elif k == len(st) - 1:
                d = -segs[-1]["dir"]
            else:
                d = segs[k]["dir"]   # mid station faces uphill segment
            yaw = math.atan2(d[1], d[0]) - math.pi / 2
            P.place(s["asset"], s["xy"][0], s["xy"][1], z=s["ground"] - 0.6, yaw=yaw, occupy_r=16.0,
                    collide="Box", tag={"gondola": line["id"]})
            s["yaw"] = yaw
        for sg in segs:
            for py in sg["pylons"]:
                yaw = math.atan2(py["dir"][1], py["dir"][0]) - math.pi / 2
                P.place(py["asset"], py["pos"][0], py["pos"][1], z=py["pos"][2] - 0.5, yaw=yaw,
                        occupy_r=3.0, collide="Box", tag={"gondola": line["id"]})
        loop = _loop_path(st, segs)
        cabins = _cabins_on_loop(loop)
        for c in cabins:
            P.place("Cabin", c["pos"][0], c["pos"][1], z=c["pos"][2], yaw=c["yaw"], category="Gondola",
                    collide="None", tag={"animated": True, "gondola": line["id"]})
        lines_meta.append(dict(id=line["id"], name=line["name"], stations=st,
                               pylons=[py for sg in segs for py in sg["pylons"]],
                               loop=loop, cabins=len(cabins), spacing=CABIN_SPACING, speed=SPEED,
                               hang=CABIN_HANG, gauge=GAUGE))
        ctx.log("gondola %s: %d stations, %d pylons, loop %.0f m, %d cabins" % (
            line["id"], len(st), sum(len(sg["pylons"]) for sg in segs), loop["length"], len(cabins)))
    ctx.markers["gondolas"] = lines_meta
    _cable_meshes(ctx, lines_meta)


def _track_points(sg, side):
    """Sampled cable points for one track (side=+1 right of travel a->b)."""
    d = sg["dir"]
    right = np.array([d[1], -d[0]])
    a = np.asarray(sg["a"]["xy"], dtype=float)
    out = []
    sup = sg["supports"]
    for k in range(len(sup) - 1):
        u0, z0 = sup[k]
        u1, z1 = sup[k + 1]
        span = u1 - u0
        n = max(4, int(span / 12.0))
        for j in range(n + (1 if k == len(sup) - 2 else 0)):
            t = j / n
            u = u0 + span * t
            z = z0 + (z1 - z0) * t - 4 * SAG_RATIO * span * t * (1 - t)
            p = a + d * u + right * side * GAUGE / 2
            out.append((float(p[0]), float(p[1]), float(z)))
    return out


def _bullwheel(center, z, d_out, side_in, steps=8):
    """Semicircle around a station bullwheel, from track side_in to -side_in."""
    right = np.array([d_out[1], -d_out[0]])
    pts = []
    for j in range(1, steps):
        a = math.pi * j / steps
        # start at right*side_in, sweep through the back of the station
        v = right * side_in * math.cos(a) - np.asarray(d_out) * math.sin(a)
        p = np.asarray(center) + v * GAUGE / 2
        pts.append((float(p[0]), float(p[1]), float(z)))
    return pts


def _loop_path(st, segs):
    up = []
    for sg in segs:
        pts = _track_points(sg, +1)
        up += pts if not up else pts[1:]
    down = []
    for sg in reversed(segs):
        rev = dict(sg)
        rev["dir"] = -sg["dir"]
        rev["a"], rev["b"] = sg["b"], sg["a"]
        L = sg["length"]
        rev["supports"] = [(L - u, z) for (u, z) in reversed(sg["supports"])]
        pts = _track_points(rev, +1)
        down += pts if not down else pts[1:]
    top = st[-1]
    bot = st[0]
    pts = up + _bullwheel(top["xy"], top["cable_z"], -segs[-1]["dir"], -1) + down + \
        _bullwheel(bot["xy"], bot["cable_z"], segs[0]["dir"], -1)
    arr = np.asarray(pts)
    seg = np.linalg.norm(np.diff(np.vstack([arr, arr[:1]]), axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(seg)])
    return dict(points=[tuple(p) for p in arr], cum=cum[:-1].tolist(), length=float(cum[-1]))


def _cabins_on_loop(loop):
    pts = np.asarray(loop["points"])
    cum = np.asarray(loop["cum"])
    L = loop["length"]
    out = []
    for s in np.arange(0.0, L, CABIN_SPACING):
        i = int(np.searchsorted(cum, s, side="right") - 1)
        j = (i + 1) % len(pts)
        seg_len = max(1e-6, (cum[j] if j > i else L) - cum[i])
        t = (s - cum[i]) / seg_len
        p = pts[i] + (pts[j] - pts[i]) * t
        dvec = pts[j] - pts[i]
        yaw = math.atan2(dvec[1], dvec[0]) - math.pi / 2
        out.append(dict(pos=(float(p[0]), float(p[1]), float(p[2])), yaw=yaw, s=float(s)))
    return out


def _cable_meshes(ctx, lines_meta):
    """Thin cable tubes for Blender previews (Roblox builds cables from data)."""
    from .meshbuild import MeshBuilder
    for ln in lines_meta:
        mb = MeshBuilder()
        pts = list(ln["loop"]["points"]) + [ln["loop"]["points"][0]]
        prof = [(math.cos(a) * 0.09, math.sin(a) * 0.09) for a in np.linspace(0, 2 * math.pi, 5, endpoint=False)]
        mb.sweep("SV_Cable", pts, prof, closed_profile=True, up=(0, 0, 1))
        lo, hi = mb.bounds()
        bl.builder_objects(mb, "SVP_Cable_%s" % ln["id"], bl.coll("GONDOLA"), origin=tuple(0.5 * (lo + hi)),
                           tag={"sv_kind": "preview_only"})
