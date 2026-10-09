"""Alpine architecture: parametric chalets, lodges, shops, huts and the
gondola stations.

Convention: footprint centred on the origin, ground at z = 0, the main
(gable / entrance) facade faces +Y. Ridge runs along Y for chalets.
"""

import math

import numpy as np

from .meshbuild import MeshBuilder, rot_y, rot_z

BASE_DEPTH = 2.0   # m of stone base below the floor level (origin)

FLOOR_H = 3.0


def _box(mb, mat, cx, cy, cz, sx, sy, sz, M=None):
    mb.box(mat, (cx, cy, cz), (sx, sy, sz), matrix=M)


class Chalet:
    def __init__(self, p):
        self.p = p
        self.mb = MeshBuilder()
        self.W, self.D = p["w"], p["d"]
        self.F = p["floors"]
        self.base_h = p.get("base_h", 1.1)
        self.base_depth = p.get("base_depth", BASE_DEPTH)
        self.wall_top = self.base_h + self.F * FLOOR_H - 0.3
        self.pitch = math.radians(p.get("pitch", 28.0))
        self.ov = p.get("overhang", 1.1)
        self.gov = p.get("gable_overhang", 1.0)
        self.ridge = self.wall_top + (self.W / 2) * math.tan(self.pitch)
        self.wall_mat = p.get("wall", "SV_Planks")

    def build(self):
        p = self.p
        self.base()
        self.walls()
        self.gables()
        self.roof()
        self.beams()
        self.windows()
        self.door()
        if p.get("balcony", True) and self.F >= 2:
            self.balcony(self.base_h + FLOOR_H)
        if p.get("balcony2") and self.F >= 3:
            self.balcony(self.base_h + 2 * FLOOR_H, width_frac=0.7)
        if p.get("chimney", True):
            self.chimney()
        if p.get("woodpile", False):
            self.woodpile()
        for extra in p.get("extras", []):
            getattr(self, extra)()
        return self.mb

    # --- structure -----------------------------------------------------
    def base(self):
        W, D = self.W, self.D
        # stone base reaches BASE_DEPTH below the floor so it meets sloping ground
        bd = self.base_depth
        _box(self.mb, "SV_Stone", 0, 0, (self.base_h - bd) / 2, W + 0.3, D + 0.3, self.base_h + bd)

    def walls(self):
        W, D = self.W, self.D
        top, b = self.wall_top, self.base_h
        if self.p.get("plaster_ground"):
            _box(self.mb, self.p.get("plaster", "SV_Plaster"), 0, 0, (b + b + FLOOR_H) / 2, W + 0.06, D + 0.06, FLOOR_H)
            _box(self.mb, self.wall_mat, 0, 0, (b + FLOOR_H + top) / 2, W, D, top - b - FLOOR_H)
        else:
            _box(self.mb, self.wall_mat, 0, 0, (b + top) / 2, W, D, top - b)

    def gables(self):
        W, D = self.W, self.D
        tri = [(-W / 2, 0.0), (W / 2, 0.0), (0.0, self.ridge - self.wall_top)]
        for sgn in (1, -1):
            # triangle in XZ extruded along Y
            v = []
            for y in (sgn * (D / 2 - 0.35), sgn * (D / 2)):
                for x, z in tri:
                    v.append((x, y, self.wall_top + z))
            f = [(0, 1, 2), (5, 4, 3), (0, 3, 4, 1), (1, 4, 5, 2), (2, 5, 3, 0)]
            self.mb.add(self.p.get("gable_mat", "SV_Planks"), v, f)

    def roof(self):
        W, D, ov, gov = self.W, self.D, self.ov, self.gov
        th = 0.32
        snow_th = self.p.get("snow", 0.55)
        L = D + 2 * gov
        half = W / 2 + ov
        slope_len = half / math.cos(self.pitch)
        t = math.tan(self.pitch)
        for s in (1, -1):
            R = rot_y(s * self.pitch)
            n = np.array([s * math.sin(self.pitch), 0.0, math.cos(self.pitch)])
            xm = s * half / 2
            zm = self.ridge - (half / 2) * t
            c = np.array([xm, 0.0, zm]) + n * (th / 2 + 0.02)
            self.mb.box("SV_Shingle", c, (slope_len, L, th), matrix=R)
            # snow layer + soft eave roll + ridge cap
            cs = np.array([xm * 0.97, 0.0, self.ridge - (half * 0.97 / 2) * t]) + n * (th + snow_th / 2)
            self.mb.box("SV_Snow", cs, (slope_len * 0.95, L - 0.25, snow_th), matrix=R)
            eave = np.array([s * half * 0.95, 0.0, self.ridge - half * 0.95 * t]) + n * (th + snow_th * 0.45)
            self.mb.cylinder("SV_Snow", eave - np.array([0, L / 2 - 0.2, 0]), eave + np.array([0, L / 2 - 0.2, 0]),
                             snow_th * 0.55, seg=6)
            # fascia boards along the rakes (front and back)
            for g in (1, -1):
                fc = np.array([xm, g * (L / 2 + 0.05), zm]) + n * (th / 2)
                self.mb.box(self.p.get("trim", "SV_WoodDark"), fc, (slope_len + 0.1, 0.12, th + 0.18), matrix=R)
        rc = np.array([0.0, 0.0, self.ridge + th + snow_th * 0.6])
        self.mb.cylinder("SV_Snow", rc - np.array([0, L / 2 - 0.2, 0]), rc + np.array([0, L / 2 - 0.2, 0]),
                         snow_th * 0.75, seg=6)

    def beams(self):
        W, D = self.W, self.D
        b, top = self.base_h, self.wall_top
        dark = self.p.get("beam", "SV_WoodDark")
        for sx in (-1, 1):
            for sy in (-1, 1):
                _box(self.mb, dark, sx * (W / 2), sy * (D / 2), (b + top) / 2, 0.34, 0.34, top - b)
        for k in range(1, self.F + 1):
            z = b + k * FLOOR_H - 0.3 if k < self.F else top
            for sy in (-1, 1):
                _box(self.mb, dark, 0, sy * (D / 2 + 0.04), z, W + 0.1, 0.12, 0.24)
            for sx in (-1, 1):
                _box(self.mb, dark, sx * (W / 2 + 0.04), 0, z, 0.12, D + 0.1, 0.24)

    # --- openings ----------------------------------------------------------
    def _window(self, cx, cy, cz, face, w=1.15, h=1.35, shutters=True):
        """face: 'front'(+Y), 'back'(-Y), 'left'(-X), 'right'(+X)."""
        mb = self.mb
        if face in ("front", "back"):
            sg = 1 if face == "front" else -1
            M = None
            off = lambda dx, dn, dz: (cx + dx, cy + sg * dn, cz + dz)  # noqa: E731
            size = lambda a, b, c: (a, b, c)  # noqa: E731
        else:
            sg = 1 if face == "right" else -1
            off = lambda dx, dn, dz: (cx + sg * dn, cy + dx, cz + dz)  # noqa: E731
            size = lambda a, b, c: (b, a, c)  # noqa: E731
        trim = self.p.get("trim", "SV_WoodDark")
        mb.box(trim, off(0, 0.06, 0), size(w + 0.24, 0.14, h + 0.24))
        mb.box("SV_WindowWarm", off(0, 0.14, 0), size(w, 0.04, h))
        # mullion cross
        mb.box(trim, off(0, 0.17, 0), size(0.08, 0.04, h))
        mb.box(trim, off(0, 0.17, 0.1), size(w, 0.04, 0.08))
        mb.box(trim, off(0, 0.2, -h / 2 - 0.12), size(w + 0.45, 0.32, 0.1))
        mb.box("SV_Snow", off(0, 0.22, -h / 2 - 0.02), size(w + 0.4, 0.28, 0.1))
        sh = self.p.get("shutters")
        if shutters and sh:
            for dx in (-(w / 2 + 0.33), w / 2 + 0.33):
                mb.box(sh, off(dx, 0.1, 0), size(0.52, 0.07, h + 0.1))

    def windows(self):
        W, D, b = self.W, self.D, self.base_h
        p = self.p
        for k in range(self.F):
            zc = b + k * FLOOR_H + 1.45
            n_front = p.get("front_windows", 2)
            for i in range(n_front):
                if k == 0 and n_front % 2 == 1 and i == n_front // 2:
                    continue
                x = (i - (n_front - 1) / 2) * (W / max(n_front, 1))
                if k == 0 and abs(x) < 1.0:
                    continue
                self._window(x, D / 2, zc, "front")
            n_side = p.get("side_windows", max(2, int(D / 3.5)))
            for i in range(n_side):
                y = (i - (n_side - 1) / 2) * (D / n_side)
                self._window(W / 2, y, zc, "right")
                self._window(-W / 2, y, zc, "left")
            for i in range(p.get("back_windows", 1)):
                x = (i - (p.get("back_windows", 1) - 1) / 2) * (W / 2.5)
                self._window(x, -D / 2, zc, "back", shutters=False)
        # attic window in the front gable
        if self.ridge - self.wall_top > 2.4:
            self._window(0, self.D / 2, self.wall_top + 1.2, "front", w=0.9, h=1.0, shutters=False)

    def door(self):
        D, b = self.D, self.base_h
        mb = self.mb
        trim = self.p.get("trim", "SV_WoodDark")
        mb.box(trim, (0, D / 2 + 0.07, b + 1.15 - 0.6), (1.7, 0.16, 2.6))
        mb.box("SV_Wood", (0, D / 2 + 0.14, b + 1.05 - 0.6), (1.25, 0.06, 2.25))
        mb.box("SV_LightGold", (0.42, D / 2 + 0.19, b + 0.4), (0.08, 0.05, 0.08))
        # steps
        mb.box("SV_Stone", (0, D / 2 + 0.75, (b - 0.6) / 2 - 0.2), (2.2, 1.3, b - 0.2))
        # canopy
        cz = b + 2.25
        for s in (1, -1):
            R = rot_y(s * math.radians(30))
            mb.box("SV_Shingle", (s * 0.62, D / 2 + 0.75, cz), (1.5, 1.6, 0.12), matrix=R)
            mb.box("SV_Snow", (s * 0.6, D / 2 + 0.75, cz + 0.18), (1.4, 1.5, 0.18), matrix=R)

    def balcony(self, z, width_frac=0.92):
        W, D = self.W, self.D
        mb = self.mb
        bw = W * width_frac
        depth = 1.5
        y0 = D / 2
        mb.box("SV_Wood", (0, y0 + depth / 2, z - 0.1), (bw, depth, 0.22))
        # brackets
        for x in np.linspace(-bw / 2 + 0.4, bw / 2 - 0.4, 3):
            mb.cylinder("SV_WoodDark", (x, y0, z - 1.1), (x, y0 + depth - 0.2, z - 0.2), 0.09, seg=5)
        rail = self.p.get("rail", "SV_WoodLight")
        h = 1.05
        # front rail + side rails
        mb.box(rail, (0, y0 + depth - 0.06, z + h), (bw, 0.14, 0.12))
        mb.box("SV_Snow", (0, y0 + depth - 0.06, z + h + 0.11), (bw - 0.1, 0.16, 0.1))
        for sx in (-1, 1):
            mb.box(rail, (sx * (bw / 2 - 0.06), y0 + depth / 2, z + h), (0.14, depth, 0.12))
        n_sl = int(bw / 0.32)
        for i in range(n_sl + 1):
            x = -bw / 2 + 0.1 + i * (bw - 0.2) / max(n_sl, 1)
            mb.box(rail, (x, y0 + depth - 0.06, z + h / 2), (0.14, 0.05, h - 0.1))
        for sx in (-1, 1):
            for j in range(4):
                y = y0 + 0.2 + j * (depth - 0.3) / 3
                mb.box(rail, (sx * (bw / 2 - 0.06), y, z + h / 2), (0.05, 0.14, h - 0.1))
        # balcony door
        mb.box(self.p.get("trim", "SV_WoodDark"), (0, y0 + 0.07, z + 1.15), (1.4, 0.14, 2.3))
        mb.box("SV_WindowWarm", (0, y0 + 0.12, z + 1.2), (1.1, 0.04, 1.9))

    def chimney(self):
        W, D = self.W, self.D
        x, y = W * 0.22, -D * 0.18
        z_roof = self.ridge - abs(x) * math.tan(self.pitch)
        top = self.ridge + 1.3
        self.mb.box("SV_Stone", (x, y, (z_roof - 1.0 + top) / 2), (0.9, 0.9, top - z_roof + 1.0))
        self.mb.box("SV_StoneBlock", (x, y, top + 0.1), (1.15, 1.15, 0.2))
        self.mb.box("SV_Snow", (x, y, top + 0.28), (1.05, 1.05, 0.2))

    def woodpile(self):
        W, D = self.W, self.D
        x = -W / 2 - 0.6
        for k in range(3):
            self.mb.cylinder("SV_Wood", (x, -D / 4 + k * 0.0 - 1.4, 0.3 + k * 0.45),
                             (x, -D / 4 + 1.4, 0.3 + k * 0.45), 0.22, seg=6)
        self.mb.box("SV_Snow", (x, -D / 4, 1.42), (0.55, 3.0, 0.16))

    def sign_board(self):
        """Board above the door for lodge / restaurant / shop names."""
        D = self.D
        self.mb.box("SV_SignBoard", (0, D / 2 + 0.12, self.base_h + 2.85), (min(self.W - 1.0, 5.0), 0.12, 0.8))

    def terrace(self):
        W, D = self.W, self.D
        mb = self.mb
        mb.box("SV_Wood", (0, D / 2 + 3.5, 0.35), (W + 2, 7.0, 0.3))
        mb.box("SV_Snow", (0, D / 2 + 5.8, 0.55), (W + 1.6, 2.2, 0.12))
        for x in np.linspace(-W / 2 + 1.5, W / 2 - 1.5, 4):
            mb.cylinder("SV_WoodDark", (x, D / 2 + 3.0, 0.5), (x, D / 2 + 3.0, 1.25), 0.45, seg=8)
            mb.cylinder("SV_FabricRed", (x, D / 2 + 3.0, 1.25), (x, D / 2 + 3.0, 2.9), 0.06, seg=5)
            mb.cone("SV_FabricRed", (x, D / 2 + 3.0, 2.3), (x, D / 2 + 3.0, 3.2), 0.35, seg=8)

    def awning(self):
        W, D = self.W, self.D
        R = rot_x_deg(-25)
        for i, x in enumerate(np.linspace(-W / 2 + 0.6, W / 2 - 0.6, 6)):
            mat = "SV_FabricRed" if i % 2 == 0 else "SV_PaintWhite"
            self.mb.box(mat, (x, D / 2 + 0.9, self.base_h + 2.7), ((W - 1.2) / 6 + 0.02, 1.8, 0.06), matrix=R)
        self.mb.box("SV_WindowWarm", (0, D / 2 + 0.05, self.base_h + 1.2), (W - 2.5, 0.06, 1.8))

    def garage(self):
        W, D = self.W, self.D
        for x in (-W / 4, W / 4):
            self.mb.box("SV_MetalLight", (x, D / 2 + 0.06, self.base_h + 1.1 - 0.6), (3.2, 0.1, 2.9))
        for k in range(6):
            self.mb.box("SV_PaintRed", (-W / 2 + 0.8 + k * 0.35, D / 2 + 0.7, 1.0), (0.08, 0.06, 1.8))


def rot_x_deg(a):
    a = math.radians(a)
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=float)


BUILDING_VARIANTS = {
    "ChaletA": dict(w=10.0, d=9.0, floors=2, pitch=27, wall="SV_Planks", shutters="SV_PaintGreen",
                    front_windows=2, woodpile=True),
    "ChaletB": dict(w=12.0, d=11.0, floors=3, pitch=25, wall="SV_Planks", plaster_ground=True,
                    shutters="SV_PaintRed", front_windows=3, balcony2=True),
    "Cabin": dict(w=7.0, d=6.0, floors=1, pitch=36, wall="SV_Wood", shutters="SV_PaintRed",
                  front_windows=2, balcony=False, woodpile=True, snow=0.7),
    "Lodge": dict(w=18.0, d=12.0, floors=2, pitch=24, wall="SV_Planks", plaster_ground=True,
                  shutters="SV_PaintGreen", front_windows=4, side_windows=4, extras=["sign_board"]),
    "Restaurant": dict(w=16.0, d=12.0, floors=2, pitch=22, wall="SV_WoodLight", front_windows=4, base_depth=8.0,
                       shutters=None, extras=["terrace", "sign_board"]),
    "SkiService": dict(w=14.0, d=9.0, floors=1, pitch=20, wall="SV_Planks", front_windows=1,
                       balcony=False, shutters=None, extras=["garage", "sign_board"], chimney=False),
    "Shop": dict(w=9.0, d=8.0, floors=2, pitch=30, wall="SV_Planks", plaster_ground=True,
                 plaster="SV_Plaster", shutters="SV_PaintBlue", front_windows=1, balcony=False,
                 extras=["awning", "sign_board"]),
    "Hut": dict(w=5.0, d=4.5, floors=1, pitch=40, wall="SV_Wood", shutters="SV_PaintGreen",
                front_windows=1, side_windows=1, balcony=False, snow=0.75, base_h=0.7),
    "Townhouse": dict(w=8.0, d=10.0, floors=3, pitch=32, wall="SV_Planks", plaster_ground=True,
                      plaster="SV_PaintRed", shutters="SV_PaintWhite", front_windows=2, balcony2=False),
}


def build_building(name):
    return Chalet(BUILDING_VARIANTS[name]).build()


# ---------------------------------------------------------------------------
# gondola stations (open terminal hall with bullwheel)
# ---------------------------------------------------------------------------

STATION_VARIANTS = {
    "StationTop": dict(w=26.0, d=15.0, h=10.0, cable_z=8.0),
    "StationMid": dict(w=20.0, d=12.0, h=9.0, cable_z=7.0),
    "StationValley": dict(w=28.0, d=16.0, h=10.0, cable_z=8.0),
}


def build_station(name):
    """Terminal hall; cables leave through the open +Y end. Bullwheel axis
    vertical at the -Y end. Track gauge (cable separation) = 2 * gauge/2."""
    p = STATION_VARIANTS[name]
    W, D, Hh = p["w"], p["d"], p["h"]
    mb = MeshBuilder()
    # concrete/stone plinth + platform
    mb.box("SV_StoneBlock", (0, 0, 0.5), (W + 1.0, D + 1.0, 2.0))
    # back wall and side walls (open front +Y)
    mb.box("SV_Planks", (0, -D / 2 + 0.3, 1.5 + Hh / 2), (W, 0.6, Hh))
    for s in (-1, 1):
        mb.box("SV_Planks", (s * (W / 2 - 0.3), -D * 0.1, 1.5 + Hh / 2), (0.6, D * 0.8, Hh))
        # big panoramic windows on the sides
        for k in range(3):
            y = -D / 2 + 2.5 + k * (D * 0.8 - 3) / 2.5
            mb.box("SV_WindowCool", (s * (W / 2 + 0.02), y, 1.5 + Hh * 0.55), (0.08, 2.4, Hh * 0.45))
    # steel portal frames
    for y in np.linspace(-D / 2 + 1, D / 2 - 0.5, 4):
        for s in (-1, 1):
            mb.box("SV_Metal", (s * (W / 2 - 0.2), y, 1.5 + Hh / 2), (0.5, 0.5, Hh))
        mb.box("SV_Metal", (0, y, 1.5 + Hh), (W, 0.5, 0.6))
    # roof (shallow gable along Y) with snow
    pitch = math.radians(14)
    half = W / 2 + 1.6
    t = math.tan(pitch)
    for s in (1, -1):
        R = rot_y(s * pitch)
        n = np.array([s * math.sin(pitch), 0, math.cos(pitch)])
        c = np.array([s * half / 2, 0.0, 1.5 + Hh + 0.6 + half / 2 * t * 0 + (W / 2 - half / 2) * t]) + n * 0.25
        mb.box("SV_Shingle", c, (half / math.cos(pitch), D + 3.0, 0.4), matrix=R)
        mb.box("SV_Snow", c + n * 0.5, (half / math.cos(pitch) * 0.96, D + 2.6, 0.6), matrix=R)
    # bullwheel + drive house
    cz = p["cable_z"]
    mb.cylinder("SV_MetalLight", (0, -D * 0.2, cz - 0.4), (0, -D * 0.2, cz + 0.4), W * 0.18, seg=20)
    mb.cylinder("SV_PaintRed", (0, -D * 0.2, cz + 0.4), (0, -D * 0.2, cz + 1.4), 0.9, seg=10)
    # cabin guide rail loop (visual)
    mb.box("SV_Metal", (0, D * 0.15, cz + 1.6), (W * 0.42, D * 0.6, 0.25))
    # platform deck and railing
    mb.box("SV_Wood", (0, D / 2 + 1.5, 1.4), (W * 0.8, 3.0, 0.3))
    # station name board
    mb.box("SV_SignBoard", (0, -D / 2 - 0.05 + D, 1.5 + Hh + 0.2), (W * 0.5, 0.2, 1.4))
    return mb


def all_building_builders():
    out = {}
    for k in BUILDING_VARIANTS:
        out[k] = ("Buildings", build_building(k))
    for k in STATION_VARIANTS:
        out[k] = ("Gondola", build_station(k))
    return out
