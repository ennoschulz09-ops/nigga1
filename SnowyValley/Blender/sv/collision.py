"""Roblox collision geometry (pure numpy).

The visual meshes are NOT used as colliders. Instead the riding surfaces
are rebuilt in Roblox from compact data:

* route strips: rows of lateral surface points at adaptive stations; each
  quad between two rows = 2 triangles = 4 WedgeParts in Roblox. Every
  point samples the same carved heightfield as the visual ribbon. Rows
  have 4, 9 or 17 points; each interval picks the layout + step with the
  fewest parts that keeps the strip within tolerance of the true surface
  (checked at 33 lateral probe points, i.e. including quad centres).
* patches: regular grids (start platform, finish plaza) with a quad mask.
* boxes: invisible boundary walls, bridge parapets, ice-cave walls and
  ceiling, out-of-bounds catch floors.
* kickers: WedgeParts matching the visual straight ramps.

All coordinates here are Blender meters; export converts to Roblox studs.
"""

import math

import numpy as np

from . import config, routes

PISTE_TOL = config.COLLISION_TOLERANCE_M          # m, groomed piste
MARGIN_TOL = config.COLLISION_MARGIN_TOLERANCE_M  # m, off-piste margins
MAX_STEP = config.COLLISION_MAX_ROW_SPACING_M
MIN_STEP = 1.0
MAX_TURN = math.radians(7.0)

# Ground cross-sections are subsets of a 33-point "truth" layout: margins in
# eighths, piste in sixteenths. Level 0 = 4 points (planar margins + piste),
# level 1 = 9 points, level 2 = 17 points; the truth layout only probes.
TRUTH_N = 33
LEVEL_IDX = {0: [0, 8, 24, 32], 1: list(range(0, 33, 4)), 2: list(range(0, 33, 2))}
MAX_LEVEL = 2


def truth_offsets(W, ml, mr):
    left = -(W / 2 + ml * (1.0 - np.arange(8) / 8.0))
    piste = -W / 2 + W * np.arange(17) / 16.0
    right = W / 2 + mr * np.arange(1, 9) / 8.0
    return np.concatenate([left, piste, right])


def lateral_layout(W, ml, mr, surface, cave_half=None, level=0):
    """Lateral offsets (m, + = right) and the kind of each quad column."""
    if surface == routes.SURF_BRIDGE:
        return np.array([-W / 2, W / 2]), ["Bridge"]
    if surface == routes.SURF_TUNNEL:
        a = cave_half if cave_half else W / 2 + 3.0
        return np.array([-a, -W / 2, W / 2, a]), ["Tunnel"] * 3
    offs = truth_offsets(W, ml, mr)
    idx = LEVEL_IDX[level] if level in LEVEL_IDX else list(range(TRUTH_N))
    offs = offs[idx]
    pis = (np.asarray(idx) >= 8) & (np.asarray(idx) <= 24)
    kinds = ["Piste" if pis[c] and pis[c + 1] else "OffPiste" for c in range(len(idx) - 1)]
    return offs, kinds


def sub_index(level_lo, level_hi):
    """Positions of the level_lo points inside the level_hi layout."""
    hi = LEVEL_IDX[level_hi]
    return [hi.index(i) for i in LEVEL_IDX[level_lo]]


class CollisionBuilder:
    def __init__(self, T, net, markers):
        self.T = T
        self.net = net
        self.markers = markers
        cave = markers.get("cave", {})
        self.cave_half = cave.get("inner_half_width")
        self._lv_cache = {}

    # ------------------------------------------------------------------
    def row(self, r, s, force_surface=None, level=0):
        """Cross-section at station s. level 3 = 33-point truth probe."""
        k = r.index_at(s)
        surf = int(r.surface[k]) if force_surface is None else force_surface
        W = float(r.interp("width", s))
        ml = float(r.interp("margin_l", s))
        mr = float(r.interp("margin_r", s))
        offs, kinds = lateral_layout(W, ml, mr, surf, self.cave_half, level)
        p = r.point(s)
        h = float(r.interp("heading_unwrapped", s))
        rx, ry = math.sin(h), -math.cos(h)
        x = p[0] + rx * offs
        y = p[1] + ry * offs
        if surf == routes.SURF_GROUND and not routes.adjacent_to_span(r, s):
            z = self.T.height(x, y)
        else:
            z = float(r.interp("z", s)) + offs * math.tan(float(r.interp("bank", s)))
        return dict(s=float(s), surface=surf, pts=np.column_stack([x, y, z]), kinds=kinds,
                    level=int(level) if surf == routes.SURF_GROUND else 0, offs=offs,
                    piste=np.abs(offs) <= W / 2 + 1e-6)

    def level_at(self, r, s):
        """Coarsest lateral level whose piecewise-linear cross-section matches
        the true surface within tolerance (piste / margin separately)."""
        key = (r.id, round(s, 3))
        if key in self._lv_cache:
            return self._lv_cache[key]
        k = r.index_at(s)
        lv = 0
        if int(r.surface[k]) == routes.SURF_GROUND:
            tr = self.row(r, s, level=3)
            o, z = tr["offs"], tr["pts"][:, 2]
            lv = MAX_LEVEL
            for cand in range(MAX_LEVEL + 1):
                idx = LEVEL_IDX[cand]
                err = np.abs(np.interp(o, o[idx], z[idx]) - z)
                if err[tr["piste"]].max() <= PISTE_TOL and err[~tr["piste"]].max() <= MARGIN_TOL:
                    lv = cand
                    break
        self._lv_cache[key] = lv
        return lv

    def _interp_error(self, ra, rb, rm):
        """Max |z| error of the triangulated strip (ra, rb) at the points of the
        probe row rm (true surface heights), separately for piste and off-piste
        points. The probe uses the 33-point layout, so quad centres (twist,
        creases between lateral points) are measured too."""
        A, B = ra["pts"], rb["pts"]
        n = len(A)
        err_p, err_o = 0.0, 0.0
        zt = rm["pts"][:, 2]
        for j, q in enumerate(rm["pts"]):
            zi = None
            for c in range(n - 1):
                tri1 = (A[c], B[c], B[c + 1])
                tri2 = (A[c], B[c + 1], A[c + 1])
                for tri in (tri1, tri2):
                    zz = _bary_z(tri, q)
                    if zz is not None:
                        zi = zz
                        break
                if zi is not None:
                    break
            if zi is None:
                continue
            e = abs(zi - zt[j])
            if rm["piste"][j] or rm["surface"] != routes.SURF_GROUND:
                err_p = max(err_p, e)
            else:
                err_o = max(err_o, e)
        return err_p, err_o

    def _max_step(self, r, s, b, lv):
        """Longest step (halving from MAX_STEP) whose strip at lateral level lv
        stays within tolerance. Returns (step, passed)."""
        step = min(MAX_STEP, b - s)
        while True:
            s2 = s + step
            dh = abs(float(r.interp("heading_unwrapped", s2)) - float(r.interp("heading_unwrapped", s)))
            db = abs(float(r.interp("bank", s2)) - float(r.interp("bank", s)))
            ok = dh <= MAX_TURN and db <= math.radians(1.5)
            sf = int(r.surface[r.index_at(s)])
            if ok and sf == routes.SURF_GROUND:
                ok = self.level_at(r, s2) <= lv or int(r.surface[r.index_at(s2)]) != routes.SURF_GROUND
                if ok:
                    ra = self.row(r, s, level=lv)
                    rb = self.row(r, s2, force_surface=sf, level=lv)
                    rm = self.row(r, s + step / 2, level=3)
                    if rm["surface"] == sf:
                        ep, eo = self._interp_error(ra, rb, rm)
                        ok = ep <= PISTE_TOL and eo <= MARGIN_TOL
            if ok:
                return step, True
            if step <= MIN_STEP + 1e-9:
                return step, False
            step = max(MIN_STEP, step * 0.5)

    def route_strips(self, r):
        """Adaptive intervals -> strips. Every interval picks the lateral level
        and step with the fewest WedgeParts per meter that keeps the strip
        within tolerance of the true surface (probed at 33 lateral points)."""
        surf = r.surface
        breaks = [0.0]
        for i in range(1, len(surf)):
            if surf[i] != surf[i - 1]:
                breaks.append(float(r.s[i]))
        breaks.append(r.length)
        ivals = []   # (s0, s1, surface, level)
        for a, b in zip(breaks[:-1], breaks[1:]):
            s = a
            while s < b - 1e-6:
                sf = int(surf[r.index_at(s)])
                if sf != routes.SURF_GROUND:
                    step, _ = self._max_step(r, s, b, 0)
                    ivals.append((s, min(s + step, b), sf, 0))
                    s = min(s + step, b)
                    continue
                best = None
                for lv in range(self.level_at(r, s), MAX_LEVEL + 1):
                    step, passed = self._max_step(r, s, b, lv)
                    quads = len(LEVEL_IDX[lv]) - 1
                    cost = quads / step + (0.0 if passed else 1e3)
                    if best is None or cost < best[0]:
                        best = (cost, step, lv)
                    if passed and lv < MAX_LEVEL and step >= MAX_STEP - 1e-6:
                        break    # cannot get cheaper with more lateral points
                _, step, lv = best
                ivals.append((s, min(s + step, b), sf, lv))
                s = min(s + step, b)
        # runs of equal (surface, level); rows at the shared stations
        runs = []
        for (s0, s1, sf, lv) in ivals:
            if runs and runs[-1][0] == (sf, lv) and abs(runs[-1][1][-1] - s0) < 1e-6:
                runs[-1][1].append(s1)
            else:
                runs.append(((sf, lv), [s0, s1]))
        strips = []
        for ri, ((sf, lv), sts) in enumerate(runs):
            rows = [self.row(r, s, force_surface=sf, level=lv) for s in sts]
            if sf == routes.SURF_GROUND and lv > 0:
                # linearise boundary rows against coarser ground neighbours so
                # shared edges carry no T-junction cracks (the shared station's
                # own cross-section is within tolerance at the coarser level)
                for idx, j in ((0, ri - 1), (len(rows) - 1, ri + 1)):
                    if 0 <= j < len(runs) and runs[j][0][0] == routes.SURF_GROUND and runs[j][0][1] < lv:
                        rw = rows[idx]
                        sub = sub_index(runs[j][0][1], lv)
                        o = rw["offs"]
                        rw["pts"][:, 2] = np.interp(o, o[sub], rw["pts"][sub, 2])
            strips.append(rows)
        return strips

    # ------------------------------------------------------------------
    def walls(self, strips_by_route):
        T = self.T
        boxes = []
        br = self.markers["bridge"]
        cave = self.markers["cave"]
        pads = [T.features["start_pad"], T.features["plaza"]]
        m = self.net.main
        for r in self.net.routes:
            end = r.length
            for side in (-1, 1):
                s = 4.0
                while s < end - 4.0:
                    k = r.index_at(s)
                    surf = int(r.surface[k])
                    seg = 8.0
                    if surf != routes.SURF_GROUND:
                        s += seg
                        continue
                    if r.kind == "main" and s > m.sections[17]["s0"] - 20.0:
                        break                      # finish straight opens into the plaza
                    W = float(r.interp("width", s))
                    mg = float(r.interp("margin_r" if side > 0 else "margin_l", s))
                    p = r.point(s)
                    h = float(r.interp("heading_unwrapped", s))
                    rx, ry = math.sin(h), -math.cos(h)
                    d = side * (W / 2 + mg + 0.6)
                    ex, ey = p[0] + rx * d, p[1] + ry * d
                    probe = (ex + rx * side * 2.5, ey + ry * side * 2.5)
                    skip = float(T.corridor_dist(*probe)) < -0.5
                    for pd in pads:
                        if math.hypot(ex - pd["x"], ey - pd["y"]) < pd["r0"] + 25.0:
                            skip = True
                    if not skip:
                        ez = float(T.height(ex, ey))
                        g = float(r.interp("grad", s))
                        boxes.append(dict(kind="Wall", center=(ex, ey, ez + 1.0),
                                          size=(1.2, 5.5, seg + 0.8), yaw=h, pitch=-math.atan(g)))
                    s += seg
        # bridge parapets (visible stone + invisible extension)
        s0, s1 = br["ext"]
        for side in (-1, 1):
            s = s0
            while s < s1:
                sm = min(s + 6.0, s1)
                c = 0.5 * (s + sm)
                p = m.point(c)
                h = float(m.interp("heading_unwrapped", c))
                d = side * (br["deck_width"] / 2 + 0.55)
                x, y = p[0] + math.sin(h) * d, p[1] - math.cos(h) * d
                z = float(m.interp("z", c))
                g = float(m.interp("grad", c))
                boxes.append(dict(kind="Parapet", center=(x, y, z + 2.0), size=(1.1, 5.0, sm - s + 0.6),
                                  yaw=h, pitch=-math.atan(g)))
                s = sm
        # ice cave walls + ceiling
        t0, t1 = cave["span"]
        a = cave["inner_half_width"]
        hgt = cave["height"]
        s = t0 - 2.0
        while s < t1 + 2.0:
            sm = min(s + 6.0, t1 + 2.0)
            c = 0.5 * (s + sm)
            p = m.point(c)
            h = float(m.interp("heading_unwrapped", c))
            z = float(m.interp("z", c))
            g = float(m.interp("grad", c))
            for side in (-1, 1):
                d = side * (a + 0.6)
                x, y = p[0] + math.sin(h) * d, p[1] - math.cos(h) * d
                boxes.append(dict(kind="CaveWall", center=(x, y, z + hgt / 2), size=(1.2, hgt + 2.0, sm - s + 0.6),
                                  yaw=h, pitch=-math.atan(g)))
            boxes.append(dict(kind="CaveCeiling", center=(p[0], p[1], z + hgt + 0.6),
                              size=(2 * a + 2.4, 1.2, sm - s + 0.6), yaw=h, pitch=-math.atan(g)))
            s = sm
        return boxes

    def patches(self):
        """Walkable ground outside the race corridors as masked grids: start
        platform, finish plaza and the village ring around it (players walk
        there after finishing; the visual terrain itself has no collision)."""
        T = self.T
        out = []
        pz = T.features["plaza"]
        specs = (("start_pad", T.features["start_pad"], 0.0, 44.0, 9.0, False),
                 ("plaza", pz, 0.0, 82.0, 10.0, False),
                 ("village", pz, 72.0, 250.0, 15.0, True))
        for key, f, rad0, rad, step, skip_corridors in specs:
            xs = np.arange(f["x"] - rad, f["x"] + rad + 0.01, step)
            ys = np.arange(f["y"] - rad, f["y"] + rad + 0.01, step)
            X, Y = np.meshgrid(xs, ys)
            Z = T.height(X, Y)
            nx, ny = len(xs), len(ys)
            CX, CY = np.meshgrid(xs[:-1] + step / 2, ys[:-1] + step / 2)
            rr = np.hypot(CX - f["x"], CY - f["y"])
            mask = (rr <= rad) & (rr >= rad0)
            if skip_corridors:
                # route strips own the corridors; keep cells that reach past
                # a corridor edge so there is no gap next to the strips
                mask &= T.corridor_dist(CX, CY) > -step / 2
                mask &= T.inside_detail(CX, CY)
            out.append(dict(name=key, x0=float(xs[0]), y0=float(ys[0]), step=step, nx=nx, ny=ny,
                            z=Z.tolist(), mask=mask.astype(int).tolist()))
        return out

    def catch_floors(self):
        T = self.T
        size = config.CHUNK_SIZE_M
        out = []
        for x0 in np.arange(T.x0, T.x1 - 1e-6, size):
            for y0 in np.arange(T.y0, T.y1 - 1e-6, size):
                x1, y1 = min(x0 + size, T.x1), min(y0 + size, T.y1)
                xs = np.linspace(x0, x1, 12)
                ys = np.linspace(y0, y1, 12)
                X, Y = np.meshgrid(xs, ys)
                zmin = float(T.height(X, Y).min())
                out.append(dict(kind="CatchFloor", center=(0.5 * (x0 + x1), 0.5 * (y0 + y1), zmin - 35.0),
                                size=(x1 - x0 + 4.0, 8.0, y1 - y0 + 4.0), yaw=0.0, pitch=0.0))
        return out

    def kicker_wedges(self):
        out = []
        for kk in self.markers.get("kickers", []):
            x, y, z = kk["pos"]
            t = np.array([kk["dir"][0], kk["dir"][1], -math.tan(kk["pitch"])])
            t /= np.linalg.norm(t)
            lat = np.array([t[1], -t[0], 0.0])
            lat /= np.linalg.norm(lat)
            up = np.cross(lat, t)
            if up[2] < 0:
                up = -up
            lip, L, W = kk["lip"], kk["length"], kk["width"]
            c = np.array([x, y, z]) + up * (lip / 2)
            out.append(dict(kind="Kicker", center=tuple(c), size=(W, lip, L), right=tuple(np.cross(t, up)),
                            up=tuple(up), back=tuple(t)))
        return out

    # ------------------------------------------------------------------
    def build(self):
        strips = {}
        for r in self.net.routes:
            strips[r.id] = self.route_strips(r)
        boxes = self.walls(strips)
        return dict(strips=strips, boxes=boxes, patches=self.patches(), catch=self.catch_floors(),
                    kickers=self.kicker_wedges())


def _bary_z(tri, q):
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = tri
    det = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(det) < 1e-9:
        return None
    l1 = ((by - cy) * (q[0] - cx) + (cx - bx) * (q[1] - cy)) / det
    l2 = ((cy - ay) * (q[0] - cx) + (ax - cx) * (q[1] - cy)) / det
    l3 = 1.0 - l1 - l2
    if l1 < -1e-6 or l2 < -1e-6 or l3 < -1e-6:
        return None
    return l1 * az + l2 * bz + l3 * cz


def strip_triangles(rows):
    """Triangles (Blender meters) of a strip, with their surface kind."""
    tris = []
    for a in range(len(rows) - 1):
        A, B = rows[a]["pts"], rows[a + 1]["pts"]
        kinds = rows[a]["kinds"]
        for c in range(len(A) - 1):
            tris.append((A[c], B[c], B[c + 1], kinds[c]))
            tris.append((A[c], B[c + 1], A[c + 1], kinds[c]))
    return tris


def wedge_count(col):
    n = 0
    for rid, strips in col["strips"].items():
        for rows in strips:
            n += 4 * (len(rows) - 1) * (len(rows[0]["pts"]) - 1)
    for p in col["patches"]:
        n += 4 * int(np.sum(p["mask"]))
    return n
