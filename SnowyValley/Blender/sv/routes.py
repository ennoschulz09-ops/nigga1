"""Build dense route samples from the layout description (pure numpy).

A Route holds arrays sampled every DS meters along its centreline:
    s, x, y, z, heading, kappa, width, margin_l, margin_r, bank,
    surface (0 ground, 1 bridge, 2 tunnel), section, grad
Main route stations are the reference for race progress; alternatives
store the main stations at which they branch and merge.
"""

import math

import numpy as np

from . import config, layout
from .mathutil import cumulative_length, smooth1d, wrap_angle

DS = 1.0
POS_SIGMA_M = 6.0
GRAD_SIGMA_M = 14.0
WIDTH_SIGMA_M = 14.0
SURF_GROUND, SURF_BRIDGE, SURF_TUNNEL = 0, 1, 2


class Route:
    def __init__(self, rid, name, difficulty, kind):
        self.id = rid
        self.name = name
        self.difficulty = difficulty
        self.kind = kind
        self.sections = []       # list of dicts with s0, s1, id, name, ...
        self.branch_s = None     # main station of branch (alternatives)
        self.merge_s = None      # main station of merge (alternatives)
        self.gates = []          # checkpoint gates on this route
        self.race_end_s = None   # finish line station (main only)

    # -- sampling helpers -----------------------------------------------------
    @property
    def length(self):
        return float(self.s[-1])

    def index_at(self, s):
        return int(np.clip(round(s / DS), 0, len(self.s) - 1))

    def interp(self, name, s):
        return np.interp(s, self.s, getattr(self, name))

    def pose(self, s):
        i = self.index_at(s)
        return float(self.x[i]), float(self.y[i]), float(self.heading[i])

    def point(self, s):
        return np.array([self.interp("x", s), self.interp("y", s), self.interp("z", s)])

    def tangent(self, s):
        h = self.interp("heading_unwrapped", s)
        return np.array([math.cos(h), math.sin(h)])

    def right(self, s):
        t = self.tangent(s)
        return np.array([t[1], -t[0]])


# ---------------------------------------------------------------------------
# gradient shapes
# ---------------------------------------------------------------------------

def _shape(name, u, length):
    """Relative gradient weights along a section (u in [0, 1]).
    "name:amp" overrides the undulation amplitude of rollers / steps."""
    amp = None
    if ":" in name:
        name, a = name.split(":")
        amp = float(a)
    if name == "start":
        return np.where(u < 0.45, 0.25, 0.25 + 2.6 * (u - 0.45))
    if name == "steady":
        return np.ones_like(u)
    if name == "steepening":
        return 0.55 + 0.9 * u
    if name == "rollers":
        n = max(2, int(round(length / 48.0)))
        return np.maximum(0.3, 1.0 + (0.42 if amp is None else amp) * np.sin(2 * math.pi * n * u))
    if name == "steps":
        n = max(2, int(round(length / 75.0)))
        return np.maximum(0.25, 1.0 + (0.62 if amp is None else amp) * np.sin(2 * math.pi * n * u - 0.6))
    if name == "bridge":
        f = np.where(u < 0.40, 1.9, 0.35)
        return np.where(u > 0.90, 1.0, f)
    if name == "tunnel":
        return np.ones_like(u)
    if name == "settle":
        return 1.4 - 0.9 * u
    if name == "finish":
        return np.ones_like(u)
    if name == "green":
        n = max(2, int(round(length / 90.0)))
        return np.maximum(0.5, 1.0 + 0.22 * np.sin(2 * math.pi * n * u))
    if name == "red":
        n = max(2, int(round(length / 60.0)))
        return np.maximum(0.45, 1.0 + 0.5 * np.sin(2 * math.pi * n * u + 0.4))
    raise ValueError(name)


def _profile_from_drops(seg_lengths, seg_drops, seg_shapes, total_drop, min_grad,
                        sigma_m=GRAD_SIGMA_M, n_total=None):
    """Return gradient samples g (positive = downhill) for concatenated segments."""
    g_parts = []
    for L, d, sh in zip(seg_lengths, seg_drops, seg_shapes):
        n = max(1, int(round(L / DS)))
        u = (np.arange(n) + 0.5) / n
        w = _shape(sh, u, L)
        g = w / (w.sum() * DS) * d if d > 0 else np.zeros(n)
        g_parts.append(g)
    g = np.concatenate(g_parts)
    if n_total is not None:
        if len(g) > n_total:
            g = g[:n_total]
        elif len(g) < n_total:
            g = np.concatenate([g, np.full(n_total - len(g), g[-1])])
    g = smooth1d(g, sigma_m / DS, mode="edge")
    g = np.maximum(g, min_grad)
    g *= total_drop / (g.sum() * DS)
    return g


def _bank_from_kappa(kappa, max_bank_deg):
    """Bank angle (rad): left turn (kappa>0) -> right side higher (positive)."""
    b = np.clip(kappa * 420.0, -max_bank_deg, max_bank_deg)
    return np.radians(smooth1d(b, 10.0 / DS))


# ---------------------------------------------------------------------------
# main route
# ---------------------------------------------------------------------------

def catmull_rom_chain(pts, samples_per_m=2.0, alpha=0.5):
    """Centripetal Catmull-Rom spline through all points (Barry-Goldman form)."""
    P = np.asarray(pts, dtype=float)
    n = len(P)
    ext = np.vstack([2 * P[0] - P[1], P, 2 * P[-1] - P[-2]])
    out = [P[0:1]]
    for i in range(n - 1):
        p0, p1, p2, p3 = ext[i], ext[i + 1], ext[i + 2], ext[i + 3]
        t0 = 0.0
        t1 = t0 + max(np.linalg.norm(p1 - p0), 1e-6) ** alpha
        t2 = t1 + max(np.linalg.norm(p2 - p1), 1e-6) ** alpha
        t3 = t2 + max(np.linalg.norm(p3 - p2), 1e-6) ** alpha
        m = max(4, int(np.linalg.norm(p2 - p1) * samples_per_m))
        t = np.linspace(t1, t2, m + 1)[1:][:, None]
        a1 = (t1 - t) / (t1 - t0) * p0 + (t - t0) / (t1 - t0) * p1
        a2 = (t2 - t) / (t2 - t1) * p1 + (t - t1) / (t2 - t1) * p2
        a3 = (t3 - t) / (t3 - t2) * p2 + (t - t2) / (t3 - t2) * p3
        b1 = (t2 - t) / (t2 - t0) * a1 + (t - t0) / (t2 - t0) * a2
        b2 = (t3 - t) / (t3 - t1) * a2 + (t - t1) / (t3 - t1) * a3
        out.append((t2 - t) / (t2 - t1) * b1 + (t - t1) / (t2 - t1) * b2)
    return np.vstack(out)


def _resample(pts):
    s = cumulative_length(pts)
    n = int(np.floor(s[-1] / DS)) + 1
    t = np.arange(n) * DS
    return np.column_stack([np.interp(t, s, pts[:, 0]), np.interp(t, s, pts[:, 1])])


def smooth_path(pts, sigma_m=POS_SIGMA_M, pin_start=0.0, pin_end=0.0):
    """Uniformly resample and Gaussian-smooth a planar path.

    The first/last pin_* meters are blended back to the unsmoothed curve so
    that junction tangents stay exactly on the main route.
    """
    p = _resample(catmull_rom_chain(pts))
    sm = np.column_stack([smooth1d(p[:, 0], sigma_m / DS), smooth1d(p[:, 1], sigma_m / DS)])
    n = len(p)
    s = np.arange(n) * DS
    w = np.ones(n)
    if pin_start > 0:
        w = np.minimum(w, np.clip(s / pin_start, 0, 1))
    if pin_end > 0:
        w = np.minimum(w, np.clip((s[-1] - s) / pin_end, 0, 1))
    w = w * w * (3 - 2 * w)
    mixed = p * (1 - w[:, None]) + sm * w[:, None]
    return _resample(mixed)


def _frames(r, pts):
    r.x, r.y = pts[:, 0].copy(), pts[:, 1].copy()
    n = len(pts)
    r.s = np.arange(n) * DS
    d = np.gradient(pts, axis=0)
    h = np.unwrap(np.arctan2(d[:, 1], d[:, 0]))
    r.heading_unwrapped = h
    r.heading = np.array([wrap_angle(a) for a in h])
    k = np.gradient(h) / DS
    r.kappa = smooth1d(k, 2.0)


def _limit_width_by_radius(r):
    """Keep the inner piste edge and inner margin outside the turn centre."""
    radius = 1.0 / np.maximum(np.abs(r.kappa), 1e-6)
    radius = -smooth1d(-np.minimum(radius, 400.0), 6.0)  # conservative
    wmax = 2.0 * np.maximum(radius - 7.0, 6.0)
    r.width = np.minimum(r.width, smooth1d(np.minimum(r.width, wmax), 8.0))
    inner_room = np.maximum(radius - 0.5 * r.width - 4.0, 1.0)
    left_turn = r.kappa > 0
    r.margin_l = np.where(left_turn, np.minimum(r.margin_l, inner_room), r.margin_l)
    r.margin_r = np.where(~left_turn, np.minimum(r.margin_r, inner_room), r.margin_r)


def build_main():
    r = Route("MAIN", "Snowy Valley Main Line", "blue", "main")
    all_pts, starts = [], []
    for sec in layout.MAIN_SECTIONS:
        starts.append(len(all_pts))
        all_pts.extend(sec["pts"])
    all_pts.extend(layout.RUNOUT_PTS)
    pts = smooth_path(all_pts, pin_start=25.0, pin_end=10.0)
    _frames(r, pts)
    n = len(pts)

    # section boundaries: closest centreline sample to each section's first
    # waypoint, searched monotonically along the route.
    bidx = []
    lo = 0
    for k in starts:
        wx, wy = all_pts[k]
        hi = min(n, lo + 900)
        d2 = (r.x[lo:hi] - wx) ** 2 + (r.y[lo:hi] - wy) ** 2
        i = lo + int(np.argmin(d2))
        bidx.append(i)
        lo = i + 1
    # finish line = closest sample to the last section's last waypoint
    fx, fy = layout.MAIN_SECTIONS[-1]["pts"][-1]
    d2 = (r.x[lo:] - fx) ** 2 + (r.y[lo:] - fy) ** 2
    i_finish = lo + int(np.argmin(d2))
    bidx.append(i_finish)
    sec_lengths = [(bidx[i + 1] - bidx[i]) * DS for i in range(len(starts))]

    # sections
    for k, sec in enumerate(layout.MAIN_SECTIONS):
        d = dict(sec)
        d["s0"], d["s1"] = bidx[k] * DS, bidx[k + 1] * DS
        r.sections.append(d)
    race_len = bidx[-1] * DS
    r.race_end_s = race_len

    # elevation profile: race part then flat runout
    n_race = int(round(race_len / DS))
    weights = [L * sec["steep"] for L, sec in zip(sec_lengths, layout.MAIN_SECTIONS)]
    drops = [config.TARGET_ELEVATION_DROP_M * w / sum(weights) for w in weights]
    g = _profile_from_drops(sec_lengths, drops,
                            [sec["shape"] for sec in layout.MAIN_SECTIONS],
                            config.TARGET_ELEVATION_DROP_M, 0.012, n_total=n_race)
    # ease the last 30 m into the plaza (finish line on a gentle 1% slope)
    z = np.empty(n)
    z[0] = config.START_Z
    z[1:n_race + 1] = config.START_Z - np.cumsum(g) * DS
    z[n_race + 1:] = z[n_race]
    # runout: gently levels out (flat stopping zone)
    r.z = z
    r.grad = np.concatenate([g, np.zeros(n - n_race)])

    # widths & margins
    width = np.zeros(n)
    ml = np.zeros(n)
    mr = np.zeros(n)
    sect = np.zeros(n, dtype=np.int32)
    surface = np.zeros(n, dtype=np.int32)
    for d in r.sections:
        i0, i1 = r.index_at(d["s0"]), r.index_at(d["s1"])
        width[i0:i1 + 1] = d["width"]
        ml[i0:i1 + 1] = d["margin"][0]
        mr[i0:i1 + 1] = d["margin"][1]
        sect[i0:i1 + 1] = d["id"]
        L = d["s1"] - d["s0"]
        if "bridge" in d:
            a, b = d["bridge"]
            surface[r.index_at(d["s0"] + a * L):r.index_at(d["s0"] + b * L) + 1] = SURF_BRIDGE
            d["bridge_s"] = (d["s0"] + a * L, d["s0"] + b * L)
        if "tunnel" in d:
            a, b = d["tunnel"]
            surface[r.index_at(d["s0"] + a * L):r.index_at(d["s0"] + b * L) + 1] = SURF_TUNNEL
            d["tunnel_s"] = (d["s0"] + a * L, d["s0"] + b * L)
    i_end = r.index_at(race_len)
    width[i_end:] = layout.MAIN_SECTIONS[-1]["width"]
    ml[i_end:] = 10
    mr[i_end:] = 10
    sect[i_end:] = 18
    r.width = smooth1d(width, WIDTH_SIGMA_M / DS)
    r.margin_l = smooth1d(ml, WIDTH_SIGMA_M / DS)
    r.margin_r = smooth1d(mr, WIDTH_SIGMA_M / DS)
    _limit_width_by_radius(r)
    # bridges and tunnels keep their exact width (no smoothing inside)
    exact = surface != SURF_GROUND
    r.width[exact] = width[exact]
    r.margin_l[exact] = ml[exact]
    r.margin_r[exact] = mr[exact]
    r.section = sect
    r.surface = surface

    bank = _bank_from_kappa(r.kappa, 11.0)
    no_bank = surface != SURF_GROUND
    no_bank[: r.index_at(60)] = True
    no_bank[r.index_at(race_len - 80):] = True
    # grow the flat zones by 3 sigma before smoothing, so the bank has faded
    # out completely where a bridge deck / tunnel floor begins (no step)
    sigma = 10.0
    grow = int(round(3.0 * sigma / DS))
    grown = np.convolve(no_bank.astype(float), np.ones(2 * grow + 1), mode="same") > 0.5
    fade = 1.0 - np.clip(smooth1d(grown.astype(float), sigma / DS), 0, 1)
    fade[no_bank] = 0.0
    r.bank = bank * fade
    return r


# ---------------------------------------------------------------------------
# alternatives
# ---------------------------------------------------------------------------

def junction_arc(p0, heading, turn_deg, radius, forward=True, step=10.0):
    """Points of a circular arc attached to pose (p0, heading).

    forward=True : the arc starts at p0 with the given heading and turns by
                   turn_deg (+ = left) -> used right after a branch.
    forward=False: the arc ENDS at p0 with the given heading, having turned
                   by turn_deg on the way in -> used right before a merge.
    p0 itself is not included.
    """
    p0 = np.asarray(p0, dtype=float)
    ang = math.radians(turn_deg)
    n = max(2, int(abs(ang) * radius / step))
    sgn = 1.0 if ang >= 0 else -1.0
    pts = []
    if forward:
        left = np.array([-math.sin(heading), math.cos(heading)])
        c = p0 + sgn * radius * left
        for k in range(1, n + 1):
            h = heading + ang * k / n
            lft = np.array([-math.sin(h), math.cos(h)])
            pts.append(tuple(c - sgn * radius * lft))
    else:
        h_start = heading - ang
        left = np.array([-math.sin(heading), math.cos(heading)])
        c = p0 + sgn * radius * left
        for k in range(0, n):
            h = h_start + ang * k / n
            lft = np.array([-math.sin(h), math.cos(h)])
            pts.append(tuple(c - sgn * radius * lft))
    return pts


def adjacent_to_span(r, s):
    """True if station s touches a bridge / tunnel sample: ground rows there
    use the analytic surface so they meet the span rows exactly."""
    k = r.index_at(s)
    lo, hi = max(k - 1, 0), min(k + 2, len(r.surface))
    return bool(np.any(r.surface[lo:hi] != SURF_GROUND))


def _main_station(main, sec_id, frac):
    d = next(sec for sec in main.sections if sec["id"] == sec_id)
    return d["s0"] + frac * (d["s1"] - d["s0"])


def build_alternative(alt, main):
    sb = _main_station(main, *alt["branch"])
    sm = _main_station(main, *alt["merge"])
    pb = main.point(sb)[:2]
    pm = main.point(sm)[:2]
    tb = main.tangent(sb)
    tm = main.tangent(sm)
    hb = main.interp("heading_unwrapped", sb)
    hm = main.interp("heading_unwrapped", sm)
    tg = alt.get("tangent", 18.0)
    exit_pts = junction_arc(pb + tg * tb, hb, *alt["exit"], forward=True)
    entry_pts = junction_arc(pm - tg * tm, hm, *alt["entry"], forward=False)
    pts = [tuple(pb), tuple(pb + tg * tb)] + exit_pts + [tuple(p) for p in alt["pts"]] + \
        entry_pts + [tuple(pm - tg * tm), tuple(pm)]
    path = smooth_path(pts, sigma_m=3.0, pin_start=tg, pin_end=tg)
    r = Route(alt["id"], alt["name"], alt["difficulty"], "alt")
    r.alt = alt
    _frames(r, path)
    n = len(path)
    r.branch_s, r.merge_s = sb, sm
    r.join_error = float(np.hypot(r.x[-1] - pm[0], r.y[-1] - pm[1]))
    zb = main.interp("z", sb)
    zm = main.interp("z", sm)
    L = r.length
    g = _profile_from_drops([L], [zb - zm], [alt["shape"]], zb - zm,
                            0.03 if alt["difficulty"] == "green" else 0.06,
                            sigma_m=10.0, n_total=n - 1)
    # blend the first/last 30 m of gradient into the main route gradient
    gb = main.interp("grad", sb)
    gm = main.interp("grad", sm)
    k = np.arange(n - 1) * DS
    wb = np.clip(1.0 - k / 30.0, 0, 1)
    wm = np.clip(1.0 - (L - k) / 30.0, 0, 1)
    g = g * (1 - wb) * (1 - wm) + gb * wb + gm * wm
    g *= (zb - zm) / (g.sum() * DS)
    r.z = np.concatenate([[zb], zb - np.cumsum(g) * DS])
    r.grad = np.concatenate([g, g[-1:]])
    # width: start/end at main width, blend to alt width
    wmain_b = main.interp("width", sb)
    wmain_m = main.interp("width", sm)
    t = smooth1d(np.clip(np.minimum(r.s, L - r.s) / 45.0, 0, 1), 6.0)
    r.width = alt["width"] * t + (1 - t) * np.where(r.s < L / 2, wmain_b, wmain_m)
    r.margin_l = np.full(n, float(alt["margin"][0]))
    r.margin_r = np.full(n, float(alt["margin"][1]))
    _limit_width_by_radius(r)
    r.section = np.zeros(n, dtype=np.int32)
    r.surface = np.zeros(n, dtype=np.int32)
    bank = _bank_from_kappa(r.kappa, 8.0 if alt["difficulty"] == "green" else 12.0)  # red/black: 12
    fade = np.clip(np.minimum(r.s, L - r.s) / 50.0, 0, 1)
    r.bank = bank * fade
    return r


# ---------------------------------------------------------------------------
# network
# ---------------------------------------------------------------------------

def _nearest_on(route, px, py, step=2):
    """Exact projection of points onto a route centreline.
    Returns continuous station and signed lateral offset (+ = right)."""
    px = np.asarray(px, dtype=float)
    py = np.asarray(py, dtype=float)
    idx = np.arange(0, len(route.s), step)
    rx, ry = route.x[idx], route.y[idx]
    out_s = np.empty(len(px))
    out_d = np.empty(len(px))
    n = len(route.s)
    for k in range(0, len(px), 1024):
        qx = px[k:k + 1024]
        qy = py[k:k + 1024]
        d2 = (qx[:, None] - rx[None, :]) ** 2 + (qy[:, None] - ry[None, :]) ** 2
        j = idx[np.argmin(d2, axis=1)]
        best_s = np.zeros(len(qx))
        best_d = np.full(len(qx), np.inf)
        best_lat = np.zeros(len(qx))
        for off in range(-step - 1, step + 1):
            a = np.clip(j + off, 0, n - 2)
            ax, ay = route.x[a], route.y[a]
            bx, by = route.x[a + 1], route.y[a + 1]
            dx, dy = bx - ax, by - ay
            L2 = dx * dx + dy * dy
            t = np.clip(((qx - ax) * dx + (qy - ay) * dy) / L2, 0.0, 1.0)
            cx, cy = ax + t * dx, ay + t * dy
            dist = np.hypot(qx - cx, qy - cy)
            L = np.sqrt(L2)
            lat = ((qx - cx) * dy - (qy - cy) * dx) / L
            better = dist < best_d
            best_d = np.where(better, dist, best_d)
            best_s = np.where(better, route.s[a] + t * L, best_s)
            best_lat = np.where(better, lat, best_lat)
        out_s[k:k + 1024] = best_s
        out_d[k:k + 1024] = best_lat
    return out_s, out_d


# Junction design: two diverging pistes may only differ in height as fast as
# the ground between their piste edges can slope (no ledges inside pistes).
SEP_SLOPE = math.tan(math.radians(30.0))
SEP_GAP0 = 3.0          # m of gap before the heights may start to differ
JUNCTION_WINDOW = 420.0  # m along the main route around the branch / merge


def _project_box_sum(g, lo, hi, total):
    """Euclidean projection of g onto {lo <= g <= hi, sum(g) = total}."""
    a = float(np.min(g - hi)) - 1.0
    b = float(np.max(g - lo)) + 1.0
    for _ in range(64):
        lam = 0.5 * (a + b)
        if np.clip(g - lam, lo, hi).sum() > total:
            a = lam
        else:
            b = lam
    return np.clip(g - 0.5 * (a + b), lo, hi)


def solve_profile(z_init, lo, hi, gmin, gmax, smooth_m=6.0):
    """Height profile closest to z_init (same end heights) that stays inside
    the envelope [lo, hi] with gradients in [gmin, gmax]: alternating
    projections, then light smoothing passes. Returns z, max violation (m)."""
    z0, z1 = float(z_init[0]), float(z_init[-1])
    total = (z0 - z1) / DS
    g = -np.diff(z_init) / DS
    gmin = np.broadcast_to(gmin, g.shape)
    gmax = np.broadcast_to(gmax, g.shape)
    z = z_init
    for outer in range(4):
        if outer:
            g = smooth1d(g, smooth_m / DS, mode="edge")
        for _ in range(400):
            g = _project_box_sum(g, gmin, gmax, total)
            z = np.concatenate([[z0], z0 - np.cumsum(g) * DS])
            zc = np.clip(z, lo, hi)
            if np.max(np.abs(zc - z)) < 0.005:
                break
            g = -np.diff(zc) / DS
    viol = float(np.max(np.maximum(lo - z, 0.0) + np.maximum(z - hi, 0.0)))
    return z, viol


def conform_alt_to_main(alt, main):
    """Junction surfaces: while the alternative's piste overlaps the main
    piste it lies exactly in the main plane; as the pistes separate its height
    may diverge by at most SEP_SLOPE x (gap - SEP_GAP0). The rest of its
    profile is re-solved inside that envelope with bounded gradients."""
    s_near, d_near = _nearest_on(main, alt.x, alt.y)
    bm = np.interp(s_near, main.s, main.bank)
    z_main = np.interp(s_near, main.s, main.z) + d_near * np.tan(bm)
    gap = np.abs(d_near) - alt.width / 2 - np.interp(s_near, main.s, main.width) / 2
    in_win = (np.abs(s_near - alt.branch_s) < JUNCTION_WINDOW) | (np.abs(s_near - alt.merge_s) < JUNCTION_WINDOW)
    # only a main piste lying BESIDE the alternative constrains its height;
    # where the main lies ahead / behind (end-on approach) the ground in
    # between is the alternative's own surface
    vx = np.interp(s_near, main.s, main.x) - alt.x
    vy = np.interp(s_near, main.s, main.y) - alt.y
    vn = np.hypot(vx, vy)
    lat = np.abs(vx * np.sin(alt.heading_unwrapped) - vy * np.cos(alt.heading_unwrapped)) / np.maximum(vn, 1e-6)
    lat = np.where(vn < 1.0, 1.0, lat)
    beside = smoothstep_np(0.45, 0.75, lat)
    dev = SEP_SLOPE * np.maximum(gap - SEP_GAP0, 0.0) + 60.0 * (1.0 - beside)
    dev = np.where(in_win, dev, 1e4)
    dev[0] = dev[-1] = 0.0
    rule = layout.DIFFICULTY_RULES[alt.difficulty]
    gmax = 0.97 * rule["max_grad"]
    z, viol = solve_profile(alt.z, z_main - dev, z_main + dev, 0.0, gmax)
    alt.z = z
    gg = -np.diff(alt.z) / DS
    alt.grad = np.concatenate([gg, gg[-1:]])
    alt.envelope_violation = viol
    alt.sep_dev = dev
    # junction weight: 1 where the alternative is held in the main plane
    w = smooth1d(np.clip(1.0 - dev / 2.0, 0.0, 1.0), 6.0 / DS, mode="edge")
    # in the main plane the cross-section follows the main surface gradient
    # (downhill grade along the main tangent + main bank) on its lateral axis
    hm = np.interp(s_near, main.s, main.heading_unwrapped)
    gm = np.interp(s_near, main.s, main.grad)
    dh = alt.heading_unwrapped - hm
    bank_eff = np.arctan(-gm * np.sin(dh) + np.tan(bm) * np.cos(dh))
    alt.bank = alt.bank * (1.0 - w) + bank_eff * w
    alt.junction_weight = w
    held = np.where(w > 0.5)[0]
    first = held[held < len(w) // 2]
    last = held[held >= len(w) // 2]
    alt.junction_s = (float(alt.s[first[-1]]) if len(first) else 0.0,
                      float(alt.s[last[0]]) if len(last) else float(alt.length))


def smoothstep_np(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def limit_margins_by_clearance(r, others, step=3):
    """Trim margins where another part of the network (same route around a
    hairpin, or a different route outside junction zones) is closer than the
    lateral offset -> no ambiguous / stepped surfaces inside the corridor."""
    idx = np.arange(0, len(r.s), step)
    for side, attr in ((-1, "margin_l"), (1, "margin_r")):
        margin = getattr(r, attr)
        lim = margin.copy()
        for i in idx:
            W = r.width[i]
            h = r.heading_unwrapped[i]
            rx, ry = math.sin(h), -math.cos(h)
            ds = np.arange(W / 2 + 1.0, W / 2 + margin[i] + 8.0, 1.0)
            px = r.x[i] + rx * side * ds
            py = r.y[i] + ry * side * ds
            # same route: nearest station must stay local
            sn, dn = _nearest_on(r, px, py, step=2)
            bad = np.abs(sn - r.s[i]) > 8.0 + 0.2 * ds
            for o in others:
                so, do = _nearest_on(o, px, py, step=3)
                ow = np.interp(so, o.s, o.width) / 2
                jw = np.interp(so, o.s, getattr(o, "junction_weight", np.zeros(len(o.s))))
                near_other = (np.abs(do) < ow + 6.0) & (jw < 0.5)
                bad |= near_other
            if np.any(bad):
                first = ds[np.argmax(bad)]
                lim[max(0, i - step):i + step + 1] = np.minimum(lim[max(0, i - step):i + step + 1],
                                                                 max(0.0, first - W / 2 - 6.0))
        # conservative smoothing: a sliding minimum (erosion) over 3 sigma, then
        # the Gaussian blur, so the smoothed margin never exceeds the hard limit
        sig = 4.0
        w = int(3 * sig)
        pad = np.pad(lim, w, mode="edge")
        ero = np.min(np.stack([pad[k:k + len(lim)] for k in range(2 * w + 1)]), axis=0)
        lim = np.minimum(smooth1d(ero, sig), lim)
        lim = np.minimum(lim, margin)
        setattr(r, attr, np.maximum(lim, 0.0))


class Network:
    def __init__(self):
        self.main = build_main()
        self.alts = [build_alternative(a, self.main) for a in layout.ALTERNATIVES]
        self.routes = [self.main] + self.alts
        for a in self.alts:
            conform_alt_to_main(a, self.main)
        for r in self.routes:
            others = [o for o in self.routes if o is not r and o.kind == "alt" and r.kind == "alt"]
            limit_margins_by_clearance(r, others)
        self._assign_alt_sections()
        self._place_gates()

    def route(self, rid):
        return next(r for r in self.routes if r.id == rid)

    def _assign_alt_sections(self):
        """Alternatives inherit the main section their progress maps to."""
        m = self.main
        for r in self.alts:
            prog = r.branch_s + (r.s / r.length) * (r.merge_s - r.branch_s)
            r.progress = prog
            r.section = np.interp(prog, m.s, m.section).round().astype(np.int32)
        m.progress = m.s.copy()

    def _straightest(self, route, s_lo, s_hi, avoid=()):
        best, best_s = 1e9, 0.5 * (s_lo + s_hi)
        for s in np.arange(max(5.0, s_lo), min(route.length - 5.0, s_hi), 2.0):
            i = route.index_at(s)
            if route.surface[i] != SURF_GROUND:
                continue
            cost = abs(route.kappa[i]) * 1000.0 + abs(s - 0.5 * (s_lo + s_hi)) * 0.05
            for a in avoid:
                if abs(s - a) < 45.0:
                    cost += 50.0
            if cost < best:
                best, best_s = cost, s
        return best_s

    def _place_gates(self):
        m = self.main
        junction_s = []
        for r in self.alts:
            junction_s += [r.branch_s, r.merge_s]
        gates = []
        for d in m.sections:
            k = d["id"]
            if k == 1:
                s = 8.0
            elif k == 18:
                s = m.race_end_s
            else:
                s = self._straightest(m, d["s0"] - 25.0, d["s0"] + 55.0, junction_s)
            gates.append(dict(group=k, route="MAIN", s=float(s), progress=float(s)))
        m.gates = gates
        # equivalent gates on alternatives
        for r in self.alts:
            r.gates = []
            for g in gates:
                if r.branch_s < g["s"] < r.merge_s:
                    t = (g["s"] - r.branch_s) / (r.merge_s - r.branch_s)
                    s_alt = t * r.length
                    s_alt = self._straightest(r, s_alt - 30.0, s_alt + 30.0, (0.0, r.length))
                    s_alt = float(np.clip(s_alt, 50.0, r.length - 50.0))
                    r.gates.append(dict(group=g["group"], route=r.id, s=s_alt,
                                        progress=g["progress"]))


def summarize(net):
    m = net.main
    lines = []
    lines.append("MAIN race length %.1f m (target %.0f), drop %.1f m" % (
        m.race_end_s, config.TARGET_MAIN_LENGTH_M, m.z[0] - m.interp("z", m.race_end_s)))
    for d in m.sections:
        z0 = m.interp("z", d["s0"])
        z1 = m.interp("z", d["s1"])
        L = d["s1"] - d["s0"]
        lines.append("  %02d %-22s s=%6.0f..%6.0f L=%5.0f z %5.1f->%5.1f drop %5.1f avg %4.1f%%" % (
            d["id"], d["name"], d["s0"], d["s1"], L, z0, z1, z0 - z1, 100 * (z0 - z1) / L))
    for r in net.alts:
        rad = 1.0 / np.maximum(np.abs(r.kappa), 1e-6)
        lines.append("ALT %s %-16s L=%6.1f drop %5.1f avg %4.1f%% max %4.1f%% minR %5.1f join_err %.2f" % (
            r.id, r.name, r.length, r.z[0] - r.z[-1], 100 * (r.z[0] - r.z[-1]) / r.length,
            100 * r.grad.max(), rad.min(), r.join_error))
    return "\n".join(lines)
