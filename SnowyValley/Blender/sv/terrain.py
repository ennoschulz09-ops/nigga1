"""Terrain heightfield for SNOWY VALLEY (pure numpy).

The final carved heightfield H (2 m grid over the detailed area) is the
single source of truth for every ground surface:
    * visual terrain chunks sample H (lowered under rideable corridors)
    * visual piste / corridor ribbons sample H exactly
    * Roblox collision triangles sample H exactly
so visual and collision geometry can never drift apart.

Pipeline
    1. macro prior   - designed landscape (valley, massif, ranges) + noise
    2. residual Laplace solve - bends the prior so all route centrelines
                       sit exactly on their designed elevation profile
    3. landform features - summit pyramid, canyon walls + rock rib,
                       ravine, lake basin, creek, ponds, cliff terraces
    4. corridor carve - piste planes (banked), berms, rideable margins and
                       cut/fill blending; bridge spans are left open and
                       tunnel spans get rock cover
"""

import math

import numpy as np

from . import config, routes
from .mathutil import Grid2D, NoiseBank, clamp, smoothstep, upsample_bicubic

# ---------------------------------------------------------------------------
# macro landscape
# ---------------------------------------------------------------------------

# elevation of the massif crest along its north-south axis (y -> z)
AXIS_PROFILE = [(-3300, -120), (-1700, -40), (-1180, -8), (-1000, 6), (-900, 30),
                (-500, 165), (-100, 330), (300, 480), (700, 625), (1000, 800),
                (1180, 700), (1500, 880), (2100, 1250), (2800, 1600), (3700, 1850)]

# (x, y, height, radius) of surrounding peaks -> dramatic panorama
PEAKS = [
    (-1550, 760, 1180, 1500), (-1250, -260, 760, 1050), (1600, 560, 1260, 1550),
    (1350, -360, 820, 1100), (-950, 2050, 1580, 1700), (950, 2350, 1760, 1800),
    (2350, 1450, 1500, 1500), (-2450, 1350, 1420, 1600), (180, 3050, 1950, 1900),
    (-1650, -2450, 1320, 1500), (350, -2750, 1520, 1700), (1950, -2250, 1260, 1500),
    (-2900, -1450, 1040, 1300), (2900, -1150, 1120, 1300), (-3000, 300, 1150, 1400),
    (3100, 250, 1250, 1400),
]

SUMMIT_PEAK = (58.0, 1012.0, 806.0)   # pyramid peak just behind the start


def _smax(a, b, k):
    """Polynomial smooth maximum; k may be an array (blend width)."""
    k = np.maximum(k, 1e-6)
    h = np.maximum(k - np.abs(a - b), 0.0) / k
    return np.maximum(a, b) + h * h * k * 0.25


_AXIS_TABLE = None


def _axis_table():
    """Dense, Gaussian-smoothed massif crest profile (no creases)."""
    global _AXIS_TABLE
    if _AXIS_TABLE is None:
        from .mathutil import smooth1d
        ys = np.arange(-3400.0, 3800.0, 10.0)
        zs = np.interp(ys, [p[0] for p in AXIS_PROFILE], [p[1] for p in AXIS_PROFILE])
        _AXIS_TABLE = (ys, smooth1d(zs, 9.0))
    return _AXIS_TABLE


def macro_prior(x, y, nb):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ty, tz = _axis_table()
    zaxis = np.interp(y, ty, tz)
    # massif (north of the valley): crest along a gently wandering axis,
    # flanks decay into side valleys at ~45 % of the crest height
    xa = 30.0 + 70.0 * np.sin((y - 250.0) / 820.0)
    half = 600.0 + 0.12 * np.clip(1000.0 - y, 0.0, 3000.0) + 0.15 * np.clip(y - 1000.0, 0, 3000)
    u = (x - xa) / half
    g = np.exp(-u * u)
    north = zaxis * (0.45 + 0.55 * g)
    # E-W valley with the village and the southern range
    yv = -1120.0 + 55.0 * np.sin(x / 640.0)
    zv = -6.0 - 0.018 * np.maximum(-x - 650.0, 0.0) - 0.010 * np.maximum(x - 900.0, 0.0)
    dv = yv - y
    dvs = np.maximum(dv - 320.0, 0.0)      # broad flat valley floor for the village
    south = zv + 0.012 * np.maximum(dv, 0.0) + 0.11 * dvs + 0.00007 * dvs ** 2
    north = np.maximum(north, zv)
    wn = smoothstep(-90.0, 60.0, y - yv)
    h = south * (1.0 - wn) + north * wn

    rid = nb.ridged("peaks", x, y, 900.0, octaves=6)
    # surrounding peaks never spill into the village valley floor
    vmask = smoothstep(220.0, 620.0, np.abs(y - yv))
    for (px, py, ph, pr) in PEAKS:
        r = np.hypot(x - px, y - py)
        warp = 1.0 + 0.22 * (nb.fbm("pw%d" % int(px), x, y, 700.0, octaves=3))
        prad = max(pr, 1.32 * ph)
        t = np.clip(1.0 - r * warp / prad, 0.0, 1.0)
        peak = ph * t ** 1.1 * (0.74 + 0.36 * rid) * vmask
        # blend width shrinks with the peak's own height so an absent peak
        # (peak ~ 0) never inflates the landscape
        k = np.minimum(160.0, 0.5 * peak)
        h = np.where(peak > 0.5, _smax(h, peak, k), h)

    # mountain texture growing with altitude; calmer on the playable massif
    alt = np.clip((h - 40.0) / 900.0, 0.0, 1.4)
    tex = nb.ridged("macro", x, y, 760.0, octaves=6) - 0.45
    massif_zone = np.exp(-(((x - 40.0) / 900.0) ** 2) - ((np.maximum(y - 1150.0, 0) + np.maximum(-1450.0 - y, 0)) / 400.0) ** 2)
    amp = (14.0 + 95.0 * alt) * (1.0 - 0.75 * massif_zone)
    return h + tex * amp


# ---------------------------------------------------------------------------
# solvers / field helpers
# ---------------------------------------------------------------------------

def _laplace_rb(values, fixed, iters, omega=1.88):
    """Red-black SOR for the Laplace equation with Dirichlet cells."""
    v = values.copy()
    ny, nx = v.shape
    jj, ii = np.mgrid[0:ny, 0:nx]
    red = ((ii + jj) % 2 == 0) & ~fixed
    black = ((ii + jj) % 2 == 1) & ~fixed
    for _ in range(iters):
        for mask in (red, black):
            p = np.pad(v, 1, mode="edge")
            avg = 0.25 * (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:])
            v[mask] = v[mask] + omega * (avg[mask] - v[mask])
    return v


def solve_residual(grid_x0, grid_y0, res, nx, ny, cons_x, cons_y, cons_v):
    """Membrane interpolation of scattered residual constraints (0 at border)."""
    def rasterize(r, gx0, gy0, mx, my):
        acc = np.zeros((my, mx))
        cnt = np.zeros((my, mx))
        i = np.clip(np.round((cons_x - gx0) / r).astype(int), 0, mx - 1)
        j = np.clip(np.round((cons_y - gy0) / r).astype(int), 0, my - 1)
        np.add.at(acc, (j, i), cons_v)
        np.add.at(cnt, (j, i), 1.0)
        fixed = cnt > 0
        val = np.where(fixed, acc / np.maximum(cnt, 1), 0.0)
        fixed[0, :] = fixed[-1, :] = True
        fixed[:, 0] = fixed[:, -1] = True
        border = np.zeros_like(fixed)
        border[0, :] = border[-1, :] = border[:, 0] = border[:, -1] = True
        val[border & (cnt == 0)] = 0.0
        return val, fixed

    # coarse-to-fine: 4x, 2x, 1x resolution
    guess = None
    for f in (4, 2, 1):
        r = res * f
        mx = int(round((nx - 1) / f)) + 1
        my = int(round((ny - 1) / f)) + 1
        val, fixed = rasterize(r, grid_x0, grid_y0, mx, my)
        if guess is not None:
            g = Grid2D(guess, grid_x0, grid_y0, res * f * 2)
            xs = grid_x0 + np.arange(mx) * r
            ys = grid_y0 + np.arange(my) * r
            X, Y = np.meshgrid(xs, ys)
            init = g.bilinear(X, Y)
            val = np.where(fixed, val, init)
        guess = _laplace_rb(val, fixed, {4: 900, 2: 500, 1: 350}[f])
    return guess


def chamfer_distance(mask, res, max_cells=200):
    """Approximate Euclidean distance (m) to the True cells of mask."""
    inf = 1e9
    d = np.where(mask, 0.0, inf)
    diag = math.sqrt(2.0)
    for _ in range(max_cells):
        p = np.pad(d, 1, mode="edge")
        nd = np.minimum.reduce([
            d,
            p[:-2, 1:-1] + 1, p[2:, 1:-1] + 1, p[1:-1, :-2] + 1, p[1:-1, 2:] + 1,
            p[:-2, :-2] + diag, p[:-2, 2:] + diag, p[2:, :-2] + diag, p[2:, 2:] + diag,
        ])
        if np.array_equal(nd, d):
            break
        d = nd
    return d * res


def polyline_distance(px, py, X, Y):
    """Distance from grid points to a polyline + station along it."""
    best = np.full(X.shape, np.inf)
    sta = np.zeros(X.shape)
    s0 = 0.0
    for k in range(len(px) - 1):
        ax, ay, bx, by = px[k], py[k], px[k + 1], py[k + 1]
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        L = math.sqrt(L2)
        t = np.clip(((X - ax) * dx + (Y - ay) * dy) / max(L2, 1e-9), 0, 1)
        d = np.hypot(X - (ax + t * dx), Y - (ay + t * dy))
        better = d < best
        best = np.where(better, d, best)
        sta = np.where(better, s0 + t * L, sta)
        s0 += L
    return best, sta


# ---------------------------------------------------------------------------
# section-specific carve parameters
# ---------------------------------------------------------------------------

SECTION_BLEND = {1: 26, 2: 22, 3: 12, 4: 18, 5: 30, 6: 9, 7: 18, 8: 14, 9: 16, 10: 10,
                 11: 4, 12: 4, 13: 24, 14: 22, 15: 40, 16: 26, 17: 22, 18: 30}
ALT_BLEND = {"green": 26, "red": 10, "black": 10}
# softness (m) of the nearest-corridor priority in the carve blend
PRIORITY_TAU = 3.0


class Terrain:
    """Builds and stores all height data. Use height(x, y) for sampling."""

    def __init__(self, net, quick=False):
        self.net = net
        self.nb = NoiseBank(config.SEED)
        self.quick = quick
        self.res = 6.0 if quick else config.FINE_GRID_RES
        self.x0, self.x1 = config.DETAIL_MIN_X, config.DETAIL_MAX_X
        self.y0, self.y1 = config.DETAIL_MIN_Y, config.DETAIL_MAX_Y
        self.nx = int(round((self.x1 - self.x0) / self.res)) + 1
        self.ny = int(round((self.y1 - self.y0) / self.res)) + 1
        xs = self.x0 + np.arange(self.nx) * self.res
        ys = self.y0 + np.arange(self.ny) * self.res
        self.X, self.Y = np.meshgrid(xs, ys)
        self.features = {}
        self._define_features()
        self._build_base()
        self._apply_landforms()
        self.base = self.H.copy()
        self._carve()
        self._post()
        self.grid = Grid2D(self.H, self.x0, self.y0, self.res)
        self.base_grid = Grid2D(self.base, self.x0, self.y0, self.res)
        self._derived()
        self._build_outer()
        del self.X, self.Y

    # ------------------------------------------------------------------
    def _define_features(self):
        net = self.net
        m = net.main
        f = self.features
        sx, sy = m.x[0], m.y[0]
        f["start_pad"] = dict(x=sx - 6.0, y=sy + 4.0, z=m.z[0], r0=34.0, r1=62.0)
        fe = m.index_at(m.length)
        f["plaza"] = dict(x=float(m.x[fe]) - 4.0, y=float(m.y[fe]) - 30.0, z=0.0, r0=58.0, r1=140.0)
        # bridge + ravine
        sec8 = m.sections[7]
        b0, b1 = sec8["bridge_s"]
        bm = 0.5 * (b0 + b1)
        bx, by = float(m.interp("x", bm)), float(m.interp("y", bm))
        deck_z = float(m.interp("z", bm))
        f["bridge"] = dict(s0=b0, s1=b1, x=bx, y=by, deck_z=deck_z)
        rav = np.array([(bx - 8, by + 92), (bx - 1, by + 40), (bx, by), (bx + 4, by - 60),
                        (bx + 10, by - 120), (bx + 30, by - 175), (bx + 55, by - 225)])
        canyon_end = m.sections[10]["s1"]
        cz = float(m.interp("z", canyon_end))
        f["ravine"] = dict(pts=rav, floor=[deck_z - 6, deck_z - 26, deck_z - 46, deck_z - 64,
                                            deck_z - 82, deck_z - 104, cz + 1.5],
                           width=[6, 14, 26, 26, 22, 18, 14])
        # lake (south of the Frozen Lake section)
        sec9 = m.sections[8]
        s9 = np.linspace(sec9["s0"], sec9["s1"], 50)
        z9min = float(m.interp("z", sec9["s1"]))
        f["lake"] = dict(x=40.0, y=-163.0, a=88.0, b=30.0, angle=-0.13, z=z9min - 9.0, depth=4.0)
        # canyon (section 11) and the rock rib that the ice cave pierces
        sec11, sec12 = m.sections[10], m.sections[11]
        f["canyon"] = dict(s0=sec11["s0"] + 70.0, s1=sec11["s1"] + 12.0)
        t0, t1 = sec12["tunnel_s"]
        f["tunnel"] = dict(s0=t0, s1=t1, height=11.0, cover=7.0)
        # creek from cave exit to village pond, and two ponds
        cx, cy = float(m.interp("x", t1)), float(m.interp("y", t1))
        base = np.array([(cx - 30, cy + 5), (cx - 60, cy - 60), (cx - 95, cy - 160),
                         (cx - 130, cy - 300), (cx - 175, cy - 430),
                         (cx - 215, cy - 560), (cx - 238, cy - 640)])
        from .routes import catmull_rom_chain
        dense = catmull_rom_chain(base, samples_per_m=0.2)
        seg = np.diff(dense, axis=0)
        L = np.concatenate([[0], np.cumsum(np.hypot(seg[:, 0], seg[:, 1]))])
        tang = np.gradient(dense, axis=0)
        tang /= np.linalg.norm(tang, axis=1, keepdims=True)
        nrm = np.column_stack([-tang[:, 1], tang[:, 0]])
        amp = 14.0 * np.sin(L / 47.0) + 6.0 * np.sin(L / 19.0 + 1.3)
        amp *= np.clip(L / 40.0, 0, 1) * np.clip((L[-1] - L) / 40.0, 0, 1)
        f["creek"] = dict(pts=dense + nrm * amp[:, None], width=5.0, depth=2.6)
        f["pond_w"] = dict(x=cx - 250, y=cy - 670, a=58, b=38, angle=0.3, z=None, depth=3.0)
        f["pond_e"] = dict(x=330.0, y=-1015.0, a=52, b=34, angle=-0.4, z=None, depth=3.0)
        f["summit"] = dict(x=SUMMIT_PEAK[0], y=SUMMIT_PEAK[1], z=SUMMIT_PEAK[2])

    # ------------------------------------------------------------------
    def _build_base(self):
        nb = self.nb
        prior = macro_prior(self.X, self.Y, nb)
        # residual constraints along every route centreline (every 6 m)
        cx, cy, cv = [], [], []
        coarse_res = 10.0
        cnx = int(round((self.x1 - self.x0) / coarse_res)) + 1
        cny = int(round((self.y1 - self.y0) / coarse_res)) + 1
        for r in self.net.routes:
            idx = np.arange(0, len(r.s), 6)
            keep = r.surface[idx] == routes.SURF_GROUND
            idx = idx[keep]
            px, py, pz = r.x[idx], r.y[idx], r.z[idx]
            pr = macro_prior(px, py, nb)
            cx.append(px)
            cy.append(py)
            cv.append(pz - pr)
        # pads
        for key in ("start_pad", "plaza"):
            p = self.features[key]
            ang = np.linspace(0, 2 * math.pi, 24, endpoint=False)
            for rr in (0.0, p["r0"] * 0.5, p["r0"]):
                px = p["x"] + rr * np.cos(ang)
                py = p["y"] + rr * np.sin(ang)
                cx.append(px)
                cy.append(py)
                cv.append(np.full(len(px), p["z"]) - macro_prior(px, py, nb))
        cx = np.concatenate(cx)
        cy = np.concatenate(cy)
        cv = np.concatenate(cv)
        resid = solve_residual(self.x0, self.y0, coarse_res, cnx, cny, cx, cy, cv)
        rg = Grid2D(resid, self.x0, self.y0, coarse_res)
        self.H = prior + rg.bicubic(self.X, self.Y)

        # distance to nearest route centreline (coarse) for noise modulation
        mask = np.zeros((cny, cnx), dtype=bool)
        for r in self.net.routes:
            i = np.clip(np.round((r.x - self.x0) / coarse_res).astype(int), 0, cnx - 1)
            j = np.clip(np.round((r.y - self.y0) / coarse_res).astype(int), 0, cny - 1)
            mask[j, i] = True
        dist = chamfer_distance(mask, coarse_res, max_cells=80)
        self.route_dist_coarse = Grid2D(dist, self.x0, self.y0, coarse_res)
        self.route_dist = self.route_dist_coarse.bilinear(self.X, self.Y)

    # ------------------------------------------------------------------
    def _apply_landforms(self):
        X, Y, H, nb = self.X, self.Y, self.H, self.nb
        f = self.features
        far = smoothstep(26.0, 110.0, self.route_dist)
        # all detail noise fades out at the detail-area border so the terrain
        # meets the outer (macro) ring without a seam
        border = np.minimum.reduce([X - self.x0, self.x1 - X, Y - self.y0, self.y1 - Y])
        self.edge_fade = smoothstep(20.0, 200.0, border)
        # the village valley floor stays calm (no knobs / ribs / rugged relief)
        yv = -1120.0 + 55.0 * np.sin(X / 640.0)
        self.valley_calm = 1.0 - smoothstep(230.0, 560.0, np.abs(Y - yv))
        far = far * self.edge_fade * (1.0 - 0.92 * self.valley_calm)

        # 1) surface detail: soft rolling noise near routes, rugged far away
        rolling = nb.fbm("roll", X, Y, 140.0, octaves=4) * (2.5 + 7.0 * far) * self.edge_fade * \
            (1.0 - 0.7 * self.valley_calm)
        rugged = (nb.ridged("rug", X, Y, 300.0, octaves=5) - 0.45) * 26.0 * far
        H += rolling + rugged
        # gentle river-plain undulation on the valley floor
        H += self.valley_calm * (nb.fbm("plain", X, Y, 380.0, octaves=3) * 4.5 +
                                 np.maximum(nb.fbm("hillock", X, Y, 150.0, octaves=2) - 0.25, 0) * 14.0)
        # fall-line ribs and gullies (massif faces mostly south)
        ribs = (nb.ridged("ribs", X / 0.35, Y, 520.0, octaves=2, gain=0.35) - 0.55) * 18.0 * far
        # rock knobs / outcrops
        knob = np.maximum(nb.fbm("knob", X, Y, 110.0, octaves=3) - 0.22, 0.0) * 30.0 * far
        H += ribs + knob

        # 2) summit pyramid with four ridges
        sx, sy, sz = f["summit"]["x"], f["summit"]["y"], f["summit"]["z"]
        dx, dy = X - sx, Y - sy
        r = np.hypot(dx, dy)
        ang = np.arctan2(dy, dx)
        ridge = 0.80 + 0.20 * np.abs(np.cos(2.0 * (ang - 0.35)))
        pyr = sz - r * 0.95 / ridge + nb.ridged("pyr", X, Y, 60.0, octaves=4) * 10.0
        H[:] = np.maximum(H, np.where(r < 420, pyr, -1e4))

        # 3) cliff terraces on steep, remote ground (rock bands)
        gy, gx = np.gradient(H, self.res)
        slope = np.degrees(np.arctan(np.hypot(gx, gy)))
        phase = nb.fbm("tphase", X, Y, 300.0, octaves=2) * 9.0
        step = 15.0 + 9.0 * nb.fbm("tstep", X, Y, 260.0, octaves=3)
        t = (H + phase) / step
        fl = np.floor(t)
        terr = (fl + smoothstep(0.55, 0.92, t - fl)) * step - phase
        wcl = smoothstep(27.0, 38.0, slope) * smoothstep(45.0, 110.0, self.route_dist)
        wcl *= smoothstep(0.05, 0.35, nb.fbm("tmask", X, Y, 240.0, octaves=3))
        H += (terr - H) * 0.55 * wcl * self.edge_fade * (1.0 - self.valley_calm)

        # 4) canyon walls: north rock wall, peaked rib on the south side
        m = self.net.main
        cs0, cs1 = f["canyon"]["s0"], f["canyon"]["s1"]
        ss = np.arange(cs0, cs1, 3.0)
        cpx, cpy = m.interp("x", ss), m.interp("y", ss)
        win = (X > cpx.min() - 170) & (X < cpx.max() + 170) & (Y > cpy.min() - 170) & (Y < cpy.max() + 170)
        Xw, Yw = X[win], Y[win]
        dist, sta = polyline_distance(cpx, cpy, Xw, Yw)
        zf = np.interp(cs0 + sta, m.s, m.z)
        idx = np.clip((sta / 3.0).astype(int), 0, len(ss) - 2)
        tx = cpx[idx + 1] - cpx[idx]
        ty = cpy[idx + 1] - cpy[idx]
        side = np.sign((Xw - cpx[idx]) * ty - (Yw - cpy[idx]) * tx)   # + = right/south
        rn = nb.ridged("cwall", Xw, Yw, 38.0, octaves=3)
        north = 24.0 * smoothstep(12.0, 21.0, dist) + (dist - 21.0).clip(0) * 0.55
        rib_h = 40.0 + 13.0 * np.sin(sta / 37.0) + 7.0 * np.sin(sta / 13.0 + 1.0) + 10.0 * (rn - 0.5)
        south = rib_h * smoothstep(12.0, 25.0, dist) * (1.0 - smoothstep(30.0, 95.0, dist)) ** 0.9
        prof = np.where(side > 0, south, north) + rn * 5.0 * smoothstep(16.0, 28.0, dist)
        fade = smoothstep(0.0, 45.0, sta) * (1 - smoothstep(sta.max() - 10, sta.max() + 1, sta))
        wv = (1 - smoothstep(100.0, 150.0, dist)) * fade
        H[win] = H[win] + (np.maximum(H[win], zf + prof) - H[win]) * wv

        # 5) rock rib over the ice cave tunnel
        t0, t1 = f["tunnel"]["s0"], f["tunnel"]["s1"]
        st = np.arange(t0 - 30, t1 + 20, 3.0)
        tpx, tpy = m.interp("x", st), m.interp("y", st)
        win = (X > tpx.min() - 140) & (X < tpx.max() + 140) & (Y > tpy.min() - 140) & (Y < tpy.max() + 140)
        Xw, Yw = X[win], Y[win]
        dist, sta = polyline_distance(tpx, tpy, Xw, Yw)
        zt = np.interp(t0 - 30 + sta, m.s, m.z)
        ribz = zt + 34.0 - 0.75 * np.maximum(dist - 24.0, 0) + nb.ridged("rib", Xw, Yw, 40.0) * 7.0
        wv = 1 - smoothstep(95.0, 135.0, dist)
        H[win] = H[win] + (np.maximum(H[win], ribz) - H[win]) * wv

        # 6) ravine below the bridge
        rv = f["ravine"]
        pts = rv["pts"]
        L = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(pts, axis=0).T))])
        win = (X > pts[:, 0].min() - 90) & (X < pts[:, 0].max() + 90) & (Y > pts[:, 1].min() - 90) & (Y < pts[:, 1].max() + 90)
        Xw, Yw = X[win], Y[win]
        dist, sta = polyline_distance(pts[:, 0], pts[:, 1], Xw, Yw)
        floor = np.interp(sta, L, rv["floor"])
        width = np.interp(sta, L, rv["width"])
        prof = floor + np.maximum(dist - width * 0.5, 0) * 1.9 + (np.maximum(dist - width * 0.5, 0) ** 2) * 0.004
        # fade out beyond the polyline ends and far from the axis
        endfade = smoothstep(-25.0, 0.0, sta - 0.0) * (1 - smoothstep(L[-1] - 1.0, L[-1] + 30.0, sta))
        wv = (1 - smoothstep(55.0, 80.0, dist)) * np.where(sta >= L[-1] - 1.0, endfade, 1.0)
        H[win] = H[win] + (np.minimum(H[win], prof) - H[win]) * wv

        # 6b) village floor: calm, nearly flat valley around the plaza
        pz = f["plaza"]
        rr = np.hypot(X - pz["x"], (Y - pz["y"]) * 1.2)
        from .mathutil import box_blur2d
        rad = max(1, int(70.0 / self.res))
        calm = box_blur2d(box_blur2d(H, rad), rad)
        calm = calm - float(Grid2D(calm, self.x0, self.y0, self.res).bilinear(pz["x"], pz["y"])) + pz["z"]
        calm += nb.fbm("vil", X, Y, 120.0, octaves=3) * 1.0
        wv = 1 - smoothstep(180.0, 330.0, rr)
        H += (calm - H) * wv * 0.9

        # 7) lake basin
        lk = f["lake"]
        self._carve_ellipse(lk, lk["z"])

        # 8) creek + ponds
        ck = f["creek"]
        pts = ck["pts"]
        win = (X > pts[:, 0].min() - 40) & (X < pts[:, 0].max() + 40) & (Y > pts[:, 1].min() - 40) & (Y < pts[:, 1].max() + 40)
        Xw, Yw = X[win], Y[win]
        dist, _ = polyline_distance(pts[:, 0], pts[:, 1], Xw, Yw)
        dist = np.maximum(dist, 0.0)
        dip = ck["depth"] * (1 - smoothstep(ck["width"] * 0.5, ck["width"] * 2.2, dist))
        H[win] = H[win] - dip
        for key in ("pond_w", "pond_e"):
            p = f[key]
            zc = float(Grid2D(H, self.x0, self.y0, self.res).bilinear(p["x"], p["y"]))
            p["z"] = zc - 1.2
            self._carve_ellipse(p, p["z"])

    def _carve_ellipse(self, e, zsurf):
        X, Y, H = self.X, self.Y, self.H
        ca, sa = math.cos(e["angle"]), math.sin(e["angle"])
        u = ((X - e["x"]) * ca + (Y - e["y"]) * sa) / e["a"]
        v = (-(X - e["x"]) * sa + (Y - e["y"]) * ca) / e["b"]
        rr = np.sqrt(u * u + v * v)
        bed = zsurf - e["depth"] * (1 - smoothstep(0.0, 1.0, rr))
        shore = zsurf + 0.35 + np.maximum(rr - 1.0, 0.0) * e["b"] * 0.55
        target = np.where(rr < 1.0, bed, shore)
        w = 1.0 - smoothstep(1.0, 2.4, rr)
        w = np.where(rr < 1.0, 1.0, w)
        H[:] = H + (np.minimum(H, target) - H) * w

    # ------------------------------------------------------------------
    def _route_fields(self, r, rmax, step=3.0):
        """Station s and signed lateral d (+ = right) of every grid cell in the
        route's swept-frame parametrisation x = p(s) + d * n(s) - the same
        mapping the ribbons and collision rows use, so planar cross-sections
        stay exactly planar inside turns (a chord projection drifts by
        ~d * dphi / 2 in s at large lateral offsets)."""
        res = self.res
        best = np.full((self.ny, self.nx), np.inf, dtype=np.float32)
        S = np.zeros((self.ny, self.nx), dtype=np.float32)
        D = np.zeros((self.ny, self.nx), dtype=np.float32)
        idx = np.arange(0, len(r.s), int(step / routes.DS))
        if idx[-1] != len(r.s) - 1:
            idx = np.append(idx, len(r.s) - 1)
        nx_all = np.sin(r.heading_unwrapped)
        ny_all = -np.cos(r.heading_unwrapped)
        for a, b in zip(idx[:-1], idx[1:]):
            ax, ay, bx, by = r.x[a], r.y[a], r.x[b], r.y[b]
            lo_x, hi_x = min(ax, bx) - rmax, max(ax, bx) + rmax
            lo_y, hi_y = min(ay, by) - rmax, max(ay, by) + rmax
            i0 = max(0, int((lo_x - self.x0) / res))
            i1 = min(self.nx, int((hi_x - self.x0) / res) + 2)
            j0 = max(0, int((lo_y - self.y0) / res))
            j1 = min(self.ny, int((hi_y - self.y0) / res) + 2)
            if i0 >= i1 or j0 >= j1:
                continue
            Xw = self.x0 + np.arange(i0, i1) * res
            Yw = self.y0 + np.arange(j0, j1) * res
            Xw, Yw = np.meshgrid(Xw, Yw)
            ex, ey = bx - ax, by - ay
            nax, nay = nx_all[a], ny_all[a]
            dnx, dny = nx_all[b] - nax, ny_all[b] - nay
            wx, wy = Xw - ax, Yw - ay
            # (w - t e) x (n_a + t dn) = 0  ->  c2 t^2 + c1 t + c0 = 0
            c0 = wx * nay - wy * nax
            c1 = (wx * dny - wy * dnx) - (ex * nay - ey * nax)
            c2 = -(ex * dny - ey * dnx)
            c1s = np.where(np.abs(c1) < 1e-9, 1e-9, c1)
            t = -c0 / c1s
            f = c2 * t * t + c1 * t + c0
            fp = 2.0 * c2 * t + c1
            t = t - f / np.where(np.abs(fp) < 1e-9, 1e-9, fp)
            t = np.clip(t, 0.0, 1.0)
            qx = wx - t * ex
            qy = wy - t * ey
            dist = np.hypot(qx, qy)
            # side from the interpolated frame normal
            sign = np.where(qx * (nax + t * dnx) + qy * (nay + t * dny) >= 0, 1.0, -1.0)
            bw = best[j0:j1, i0:i1]
            better = dist < bw
            bw[better] = dist[better]
            S[j0:j1, i0:i1][better] = (r.s[a] + t * (r.s[b] - r.s[a]))[better]
            D[j0:j1, i0:i1][better] = (sign * dist)[better]
        return best, S, D

    def _carve(self):
        X, Y, H = self.X, self.Y, self.H
        Hb = H.copy()
        # coverage = how much the natural terrain is replaced (max over routes);
        # the target height is a priority blend in which the corridor whose
        # piste is nearest dominates, so a neighbouring corridor at another
        # height never tilts this piste (it leaves a ledge in between instead)
        cover_w = np.zeros_like(H)
        sump = np.zeros_like(H)
        sumpz = np.zeros_like(H)
        self.corridor_e = np.full(H.shape, 1e3, dtype=np.float32)   # dist beyond rideable edge
        self.piste_e = np.full(H.shape, 1e3, dtype=np.float32)      # dist beyond piste edge
        self.near_route = np.full(H.shape, -1, dtype=np.int8)
        # 1 where the nearest corridor is covered by its ribbon (0 in the round
        # caps beyond a route's first / last station): the visual terrain is
        # only pushed down where a ribbon lies on top
        self.ribbon_cover = np.zeros(H.shape, dtype=np.float32)
        self.near_s = np.zeros(H.shape, dtype=np.float32)
        self.near_d = np.zeros(H.shape, dtype=np.float32)
        tun = self.features["tunnel"]
        br = self.features["bridge"]
        cover = np.full(H.shape, -1e4)
        under = np.full(H.shape, 1e5)     # terrain cap under the bridge deck
        for ri, r in enumerate(self.net.routes):
            if r.kind == "main":
                blend = np.zeros(len(r.s))
                for d in r.sections:
                    blend[r.index_at(d["s0"]):r.index_at(d["s1"]) + 1] = SECTION_BLEND[d["id"]]
                blend[r.index_at(r.race_end_s):] = SECTION_BLEND[18]
                blend = np.convolve(np.pad(blend, 15, mode="edge"), np.ones(31) / 31, mode="valid")
            else:
                blend = np.full(len(r.s), float(ALT_BLEND[r.difficulty]))
            rmax = float((r.width / 2 + np.maximum(r.margin_l, r.margin_r) + blend).max()) + 4.0
            dist, S, D = self._route_fields(r, rmax)
            sel = np.isfinite(dist) & (dist < rmax)
            if r.kind != "main":
                # cells beyond an alternative's end stations project onto the
                # endpoint (a round cap) - they belong to the main corridor
                sel &= (S > 1e-3) & (S < r.s[-1] - 1e-3)
            s = S[sel].astype(float)
            d = D[sel].astype(float)
            zc = np.interp(s, r.s, r.z)
            bank = np.interp(s, r.s, r.bank)
            W = np.interp(s, r.s, r.width)
            ml = np.interp(s, r.s, r.margin_l)
            mr = np.interp(s, r.s, r.margin_r)
            bl = np.interp(s, r.s, blend)
            kap = np.interp(s, r.s, r.kappa)
            surf = np.interp(s, r.s, r.surface.astype(float))
            margin = np.where(d < 0, ml, mr)
            e = np.abs(d) - W / 2
            zplane = zc + d * np.tan(bank)
            hb = Hb[sel]
            # rideable margins are a planar extension of the banked piste (exact
            # 4-point collision cross-sections); cut/fill happens beyond them
            alpha = 0.0 * e
            # planar zone continues ~4 m past the rideable edge (under the
            # boundary wall) so the edge cells of the height grid are exact
            w = 1.0 - smoothstep(margin + 4.0, margin + 4.0 + bl, e)
            # berm on the outside of tighter turns
            radius = 1.0 / np.maximum(np.abs(kap), 1e-4)
            bh = np.clip(1.5 - radius / 60.0, 0.0, 1.3)
            outer = np.sign(d) == np.sign(kap)
            # (berms disabled: the collision cross-section must reproduce the
            # riding surface exactly, banking already shapes the turns)
            berm = 0.0 * bh
            zr = zplane + (hb - zplane) * alpha + berm
            # bridges stay open, tunnels are not carved from above. The carve
            # reaches `pad` into each span so the bilinear height samples at
            # the span boundary rows (ribbon + collision) only see carved cells.
            if r.kind == "main":
                pad = max(2.0, 1.5 * self.res + 0.5)
                in_bridge = (s > br["s0"] + pad) & (s < br["s1"] - pad)
                in_tunnel = (s > tun["s0"] + pad) & (s < tun["s1"] - pad)
                w = np.where(in_bridge | in_tunnel, 0.0, w)
                cov = zc + tun["height"] + tun["cover"]
                tsel = in_tunnel & (np.abs(d) < W / 2 + 7.0)
                cv = cover[sel]
                cv[tsel] = np.maximum(cv[tsel], cov[tsel])
                cover[sel] = cv
                # the hillside must never poke through the deck near the
                # abutments: keep the ground 1.5 m below it under the footprint
                bsel = in_bridge & (np.abs(d) < W / 2 + 3.0)
                ud = under[sel]
                ud[bsel] = np.minimum(ud[bsel], zplane[bsel] - 1.5)
                under[sel] = ud
            cw = cover_w[sel]
            cover_w[sel] = np.maximum(cw, w)
            pw = w * np.exp(-np.maximum(e, 0.0) / PRIORITY_TAU)
            sump[sel] += pw
            sumpz[sel] += pw * zr
            ce = self.corridor_e[sel]
            pe = self.piste_e[sel]
            e_corr = e - margin
            closer = e_corr < ce
            ce = np.where(closer, e_corr, ce)
            self.corridor_e[sel] = ce
            self.piste_e[sel] = np.minimum(pe, e)
            nr = self.near_route[sel]
            ns = self.near_s[sel]
            ndd = self.near_d[sel]
            nr[closer] = ri
            ns[closer] = s[closer]
            ndd[closer] = d[closer]
            rc = self.ribbon_cover[sel]
            # (the transition sits 4 m inside the ribbon so it never shows)
            rc[closer] = ((s > 4.0) & (s < r.s[-1] - 4.0))[closer]
            self.ribbon_cover[sel] = rc
            self.near_route[sel] = nr
            self.near_s[sel] = ns
            self.near_d[sel] = ndd
        # pads (start platform, finish plaza)
        for key in ("start_pad", "plaza"):
            p = self.features[key]
            rr = np.hypot(X - p["x"], Y - p["y"])
            w = 1.0 - smoothstep(p["r0"], p["r1"], rr)
            cover_w = np.maximum(cover_w, w)
            sump += w
            sumpz += w * p["z"]
        a = cover_w
        zavg = np.where(sump > 1e-9, sumpz / np.maximum(sump, 1e-9), Hb)
        self.H = Hb * (1 - a) + zavg * a
        self.H = np.maximum(self.H, cover)
        self.H = np.minimum(self.H, under)
        self.tunnel_cover = cover

    def _post(self):
        # keep lake bed below the ice after carving (corridors never touch it)
        lk = self.features["lake"]
        ca, sa = math.cos(lk["angle"]), math.sin(lk["angle"])
        u = ((self.X - lk["x"]) * ca + (self.Y - lk["y"]) * sa) / lk["a"]
        v = (-(self.X - lk["x"]) * sa + (self.Y - lk["y"]) * ca) / lk["b"]
        inside = np.sqrt(u * u + v * v) < 1.0
        self.H[inside] = np.minimum(self.H[inside], lk["z"] - 0.6)

    def _derived(self):
        from .mathutil import box_blur2d
        gy, gx = np.gradient(self.H, self.res)
        self.slope_deg = np.degrees(np.arctan(np.hypot(gx, gy))).astype(np.float32)
        rad = max(1, int(6.0 / self.res))
        sl = box_blur2d(box_blur2d(self.slope_deg.astype(float), rad), rad)
        thr = 40.0 + 5.0 * self.nb.fbm("rockthr", self.X, self.Y, 70.0, octaves=3)
        rock = smoothstep(thr - 3.0, thr + 3.0, sl)
        rock = box_blur2d(rock, max(1, int(4.0 / self.res)))
        rock = np.where(self.corridor_e < 3.0, 0.0, rock)      # corridors stay snow
        self.rockiness = Grid2D(rock.astype(np.float32), self.x0, self.y0, self.res)
        self.normal_x = (-gx / np.sqrt(1 + gx * gx + gy * gy)).astype(np.float32)
        self.normal_y = (-gy / np.sqrt(1 + gx * gx + gy * gy)).astype(np.float32)
        self.corridor_grid = Grid2D(self.corridor_e, self.x0, self.y0, self.res)
        self.ribbon_grid = Grid2D(self.ribbon_cover, self.x0, self.y0, self.res)
        self.piste_grid = Grid2D(self.piste_e, self.x0, self.y0, self.res)
        self.slope_grid = Grid2D(self.slope_deg, self.x0, self.y0, self.res)

    def _build_outer(self):
        r = 40.0 if self.quick else config.OUTER_GRID_RES
        xs = np.arange(config.OUTER_MIN_X, config.OUTER_MAX_X + 1e-6, r)
        ys = np.arange(config.OUTER_MIN_Y, config.OUTER_MAX_Y + 1e-6, r)
        Xo, Yo = np.meshgrid(xs, ys)
        Ho = macro_prior(Xo, Yo, self.nb)
        self.outer = Grid2D(Ho, xs[0], ys[0], r)
        from .mathutil import box_blur2d
        gy, gx = np.gradient(Ho, r)
        sl = box_blur2d(np.degrees(np.arctan(np.hypot(gx, gy))), 1)
        # surrounding peaks: snow except on the steepest faces (snowy look)
        thr = 52.0 + 5.0 * self.nb.fbm("rockthr_o", Xo, Yo, 300.0, octaves=2)
        self.outer_rock = Grid2D(smoothstep(thr - 2.0, thr + 2.0, sl), xs[0], ys[0], r)

    # ------------------------------------------------------------------
    # sampling API
    # ------------------------------------------------------------------
    def inside_detail(self, x, y):
        return (x >= self.x0) & (x <= self.x1) & (y >= self.y0) & (y <= self.y1)

    def height(self, x, y):
        """Final carved height (detail area), macro prior outside."""
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        hin = self.grid.bilinear(x, y)
        if np.all(self.inside_detail(x, y)):
            return hin
        hout = self.outer.bicubic(x, y)
        return np.where(self.inside_detail(x, y), hin, hout)

    def rock(self, x, y):
        """0..1 rockiness used to split snow / rock terrain parts."""
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        rin = self.rockiness.bilinear(x, y)
        if np.all(self.inside_detail(x, y)):
            return rin
        return np.where(self.inside_detail(x, y), rin, self.outer_rock.bilinear(x, y))

    def slope(self, x, y):
        return self.slope_grid.bilinear(x, y)

    def corridor_dist(self, x, y):
        """< 0 inside a rideable corridor (piste + margins)."""
        return self.corridor_grid.bilinear(x, y)

    def piste_dist(self, x, y):
        return self.piste_grid.bilinear(x, y)


def build_terrain(net, quick=False):
    return Terrain(net, quick=quick)
