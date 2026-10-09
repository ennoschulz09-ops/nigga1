"""Resort props: gates, signs, fences, poles, lamps, plaza decoration,
snowpark kickers, footbridges and the gondola pylon / cabin.

Conventions: base centre at the origin, front faces +Y. Gondola assets use
+Y as the cable direction; the cabin's origin is the GRIP point on the cable
(the body hangs below) so it can be placed directly on cable positions.
Text (START, FINISH, section names, numbers) is NOT modelled: the Roblox
importer adds crisp SurfaceGui labels on the marked board faces.
"""

import math

import numpy as np

from .meshbuild import MeshBuilder, rot_x, rot_y, rot_z


# ---------------------------------------------------------------------------
# start / finish / checkpoint structures
# ---------------------------------------------------------------------------

def _truss_tower(mb, cx, cy, h, w=1.3, col_a="SV_PaintRed", col_b="SV_PaintWhite"):
    for sx in (-1, 1):
        for sy in (-1, 1):
            mb.cylinder("SV_MetalLight", (cx + sx * w / 2, cy + sy * w / 2, -0.4),
                        (cx + sx * w / 2, cy + sy * w / 2, h), 0.09, seg=6)
    n = int(h / 1.4)
    for k in range(n):
        z0 = k * h / n
        z1 = (k + 1) * h / n
        for (ax, ay, bx, by) in ((-1, -1, 1, -1), (1, 1, -1, 1), (-1, -1, -1, 1), (1, -1, 1, 1)):
            mb.cylinder("SV_MetalLight", (cx + ax * w / 2, cy + ay * w / 2, z0),
                        (cx + bx * w / 2, cy + by * w / 2, z1), 0.05, seg=4)
    # painted cladding panels on the lower half
    mb.box(col_a, (cx, cy, h * 0.25), (w + 0.1, w + 0.1, h * 0.5))
    mb.box(col_b, (cx, cy, h * 0.5 + 0.2), (w + 0.12, w + 0.12, 0.4))


def build_start_gate():
    mb = MeshBuilder()
    span, h = 34.0, 8.0
    for x in (-span / 2, span / 2):
        _truss_tower(mb, x, 0, h)
        mb.box("SV_Snow", (x, 0, h + 0.15), (1.5, 1.5, 0.25))
    # banner beam: front face (+Y) is the text panel
    mb.box("SV_FabricRed", (0, 0, h - 1.2), (span + 1.4, 0.5, 2.4))
    mb.box("SV_PaintWhite", (0, 0.27, h - 1.2), (span - 2.0, 0.05, 1.6))
    mb.box("SV_PaintWhite", (0, -0.27, h - 1.2), (span - 2.0, 0.05, 1.6))
    # top "START" board
    mb.box("SV_SignBoard", (0, 0, h + 1.0), (8.0, 0.4, 1.8))
    mb.box("SV_LightRed", (0, 0.22, h + 1.0), (7.4, 0.04, 0.12))
    # timing posts + start wand housings
    for x in (-span / 2 + 2.5, span / 2 - 2.5):
        mb.box("SV_PaintBlack", (x, 0.3, 0.6), (0.5, 0.5, 1.2))
        mb.box("SV_LightGold", (x, 0.56, 1.05), (0.3, 0.04, 0.12))
    # painted start line on the snow
    mb.box("SV_PaintRed", (0, 1.2, 0.03), (span - 2.0, 0.7, 0.06))
    return mb


def build_finish_arch():
    mb = MeshBuilder()
    span, h = 50.0, 10.0
    # inflatable-style rounded legs and beam
    for x in (-span / 2, span / 2):
        mb.lathe("SV_FabricBlue", [(1.4, -0.3), (1.35, h * 0.5), (1.2, h - 0.8), (0.9, h - 0.2), (0.01, h)],
                 seg=12, center=(x, 0, 0), smooth=True)
    pts = []
    for k in range(25):
        t = k / 24
        pts.append((-span / 2 + span * t, 0.0, h - 0.6 + math.sin(t * math.pi) * 2.2))
    prof = [(math.cos(a) * 1.1, math.sin(a) * 1.1) for a in np.linspace(0, 2 * math.pi, 10, endpoint=False)]
    mb.sweep("SV_FabricBlue", pts, prof, closed_profile=True, up=(0, 1, 0), smooth=True)
    # banner panel (text "FINISH" via SurfaceGui) + clock
    mb.box("SV_PaintWhite", (0, 0.0, h + 1.6), (18.0, 0.3, 3.0))
    mb.box("SV_FabricRed", (0, 0.0, h + 1.6), (18.6, 0.2, 3.4))
    mb.box("SV_PaintBlack", (0, 0.2, h - 1.6), (6.0, 0.6, 1.6))
    mb.box("SV_LightRed", (0, 0.52, h - 1.6), (5.2, 0.04, 0.9))
    # finish line
    mb.box("SV_PaintRed", (0, 0.0, 0.03), (span - 2.0, 1.2, 0.06))
    for k in range(10):
        mb.box("SV_PaintWhite" if k % 2 else "SV_PaintBlack", (-span / 2 + 3 + k * (span - 6) / 9, 0.0, 0.07),
               (1.0, 1.0, 0.03))
    return mb


def build_gate_post():
    """Checkpoint gate post (one per side); banner spans between posts."""
    mb = MeshBuilder()
    mb.cylinder("SV_PaintWhite", (0, 0, -0.5), (0, 0, 7.0), 0.22, seg=8)
    mb.cylinder("SV_PaintRed", (0, 0, 4.4), (0, 0, 7.0), 0.24, seg=8)
    mb.box("SV_PaintBlack", (0, 0, 0.35), (0.9, 0.9, 0.7))
    mb.cone("SV_LightGold", (0, 0, 7.0), (0, 0, 7.6), 0.3, seg=8)
    return mb


# ---------------------------------------------------------------------------
# signs & poles
# ---------------------------------------------------------------------------

def build_section_sign():
    mb = MeshBuilder()
    for x in (-1.5, 1.5):
        mb.cylinder("SV_WoodDark", (x, 0, -0.5), (x, 0, 4.3), 0.13, seg=6)
    mb.box("SV_WoodDark", (0, 0, 3.1), (3.6, 0.2, 2.4))
    mb.box("SV_SignBoard", (0, 0.12, 3.1), (3.3, 0.05, 2.1))     # text face (+Y)
    mb.cylinder("SV_PaintBlue", (-1.05, 0.16, 3.7), (-1.05, 0.2, 3.7), 0.42, seg=12)   # badge
    mb.box("SV_Snow", (0, 0, 4.36), (3.7, 0.36, 0.14))
    for s in (-1, 1):
        mb.box("SV_Shingle", (s * 0.95, 0, 4.55), (2.1, 0.7, 0.1), matrix=rot_y(s * math.radians(-20)))
        mb.box("SV_Snow", (s * 0.95, 0, 4.7), (2.0, 0.6, 0.14), matrix=rot_y(s * math.radians(-20)))
    return mb


def build_junction_sign():
    mb = MeshBuilder()
    mb.cylinder("SV_WoodDark", (0, 0, -0.5), (0, 0, 3.8), 0.12, seg=6)
    cols = ["SV_PaintBlue", "SV_PaintGreen", "SV_PaintRed"]
    for k, c in enumerate(cols):
        z = 3.3 - k * 0.62
        d = 1 if k % 2 == 0 else -1
        mb.box(c, (d * 0.95, 0.1, z), (1.9, 0.08, 0.5))
        mb.add(c, [(d * 1.9, 0.06, z - 0.32), (d * 1.9, 0.06, z + 0.32), (d * 2.45, 0.06, z),
                   (d * 1.9, 0.14, z - 0.32), (d * 1.9, 0.14, z + 0.32), (d * 2.45, 0.14, z)],
               [(0, 1, 2), (5, 4, 3), (0, 3, 4, 1), (1, 4, 5, 2), (2, 5, 3, 0)])
    mb.box("SV_Snow", (0, 0, 3.85), (0.4, 0.4, 0.12))
    return mb


def build_warning_sign():
    mb = MeshBuilder()
    mb.cylinder("SV_MetalLight", (0, 0, -0.4), (0, 0, 2.6), 0.06, seg=6)
    tri = [(-0.75, 0.0), (0.75, 0.0), (0.0, 1.3)]
    for mat, off, sc in (("SV_PaintRed", 0.04, 1.0), ("SV_PaintYellow", 0.07, 0.78)):
        v = [(x * sc, off, 2.2 + z * sc + (1 - sc) * 0.25) for x, z in tri]
        v += [(x * sc, off + 0.03, 2.2 + z * sc + (1 - sc) * 0.25) for x, z in tri]
        mb.add(mat, v, [(0, 1, 2), (5, 4, 3), (0, 3, 4, 1), (1, 4, 5, 2), (2, 5, 3, 0)])
    mb.box("SV_PaintBlack", (0, 0.12, 2.85), (0.12, 0.02, 0.5))
    mb.box("SV_PaintBlack", (0, 0.12, 2.5), (0.12, 0.02, 0.12))
    return mb


def build_difficulty_marker(kind):
    mb = MeshBuilder()
    mb.cylinder("SV_MetalLight", (0, 0, -0.4), (0, 0, 2.4), 0.06, seg=6)
    mb.box("SV_PaintWhite", (0, 0.03, 2.2), (0.9, 0.04, 0.9))
    if kind == "green":
        mb.cylinder("SV_PaintGreen", (0, 0.05, 2.2), (0, 0.09, 2.2), 0.34, seg=14)
    elif kind == "blue":
        mb.box("SV_PaintBlue", (0, 0.07, 2.2), (0.6, 0.04, 0.6))
    elif kind == "black":
        mb.box("SV_PaintBlack", (0, 0.07, 2.2), (0.48, 0.04, 0.48), matrix=rot_y(math.radians(45)))
    else:
        mb.box("SV_PaintRed", (0, 0.07, 2.2), (0.48, 0.04, 0.48), matrix=rot_y(math.radians(45)))
    return mb


def build_piste_pole(mat):
    mb = MeshBuilder()
    mb.cylinder(mat, (0, 0, -0.5), (0, 0, 2.0), 0.045, seg=5)
    mb.cylinder("SV_PaintWhite", (0, 0, 2.0), (0, 0, 2.25), 0.045, seg=5)
    mb.cylinder(mat, (0, 0, 2.25), (0, 0, 2.4), 0.05, seg=5)
    return mb


def build_fence_rail(length=4.0):
    mb = MeshBuilder()
    for x in (-length / 2, length / 2):
        mb.cylinder("SV_WoodDark", (x, 0, -0.5), (x, 0, 1.25), 0.09, seg=6)
        mb.cone("SV_Snow", (x, 0, 1.22), (x, 0, 1.4), 0.12, seg=6)
    for z in (0.55, 1.05):
        mb.cylinder("SV_Wood", (-length / 2 - 0.15, 0, z), (length / 2 + 0.15, 0, z), 0.065, seg=5)
    mb.box("SV_Snow", (0, 0, 1.13), (length, 0.14, 0.06))
    return mb


def build_safety_net(length=6.0):
    mb = MeshBuilder()
    for x in (-length / 2, length / 2):
        mb.cylinder("SV_MetalLight", (x, 0, -0.5), (x, 0, 2.2), 0.05, seg=5)
    mb.box("SV_PaintOrange", (0, 0, 1.2), (length, 0.05, 1.7))
    mb.box("SV_PaintOrange", (0, 0, 2.1), (length, 0.08, 0.12))
    return mb


def build_feather_flag(mat):
    mb = MeshBuilder()
    mb.cylinder("SV_MetalLight", (0, 0, -0.5), (0, 0, 5.0), 0.05, seg=5)
    pts = [(0.0, 0.0, 1.2 + k * 0.48) for k in range(9)]
    prof = [(0.0, 0.02), (1.1, 0.02), (1.1, -0.02), (0.0, -0.02)]
    scales = [0.75 + 0.35 * math.sin(k / 8 * math.pi) for k in range(9)]
    mb.sweep(mat, pts, prof, closed_profile=True, up=(1, 0, 0), scales=scales)
    return mb


def build_lamp():
    mb = MeshBuilder()
    mb.cylinder("SV_Metal", (0, 0, -0.4), (0, 0, 4.2), 0.09, seg=8)
    mb.cylinder("SV_Metal", (0, 0, 0.0), (0, 0, 0.6), 0.2, seg=8)
    mb.cylinder("SV_Metal", (0, 0, 4.2), (0.55, 0, 4.35), 0.05, seg=5)
    mb.box("SV_Metal", (0.6, 0, 4.0), (0.42, 0.42, 0.08))
    mb.box("SV_WindowWarm", (0.6, 0, 3.75), (0.32, 0.32, 0.45))
    mb.cone("SV_Metal", (0.6, 0, 4.0), (0.6, 0, 4.35), 0.3, seg=4, phase=math.pi / 4)
    mb.cone("SV_Snow", (0.6, 0, 4.08), (0.6, 0, 4.4), 0.24, seg=4, phase=math.pi / 4)
    return mb


def build_bench():
    mb = MeshBuilder()
    mb.box("SV_Wood", (0, 0, 0.48), (2.0, 0.5, 0.08))
    mb.box("SV_Wood", (0, -0.22, 0.85), (2.0, 0.06, 0.45))
    for x in (-0.85, 0.85):
        mb.box("SV_Metal", (x, 0, 0.24), (0.08, 0.5, 0.48))
    mb.box("SV_Snow", (0, 0.02, 0.56), (1.9, 0.44, 0.08))
    return mb


def build_xmas_tree():
    mb = MeshBuilder()
    h = 13.0
    rng = np.random.default_rng(77)
    mb.cylinder("SV_Bark", (0, 0, -0.3), (0, 0, 2.0), 0.5, seg=8)
    tiers = 6
    for k in range(tiers):
        zb = 1.6 + k * (h - 2.5) / tiers
        zt = zb + (h - 2.5) / tiers * 2.0
        r = 4.6 * (1 - k / tiers) + 0.5
        mb.cone("SV_Foliage", (0, 0, zb), (0, 0, min(zt, h)), r, seg=10, phase=k * 0.3)
        mb.cone("SV_Snow", (0, 0, zb + (zt - zb) * 0.45), (0, 0, min(zt, h) + 0.05), r * 0.55, seg=10,
                phase=k * 0.3, cap=False)
        for j in range(10 + 3 * (tiers - k)):
            a = rng.uniform(0, 2 * math.pi)
            t = rng.uniform(0.15, 0.95)
            rr = r * (1 - t) * 0.98
            z = zb + (min(zt, h) - zb) * t
            mat = ("SV_LightGold", "SV_LightRed", "SV_LightBlue")[j % 3]
            mb.ico(mat, (rr * math.cos(a), rr * math.sin(a), z), 0.22, subdiv=0)
    # star
    for k in range(5):
        a = k * 2 * math.pi / 5
        mb.cone("SV_LightGold", (0, 0, h + 0.6), (0.9 * math.sin(a), 0, h + 0.6 + 0.9 * math.cos(a)), 0.22, seg=4)
    mb.box("SV_PaintRed", (1.2, 1.0, 0.4), (0.8, 0.8, 0.8))
    mb.box("SV_PaintGreen", (-1.0, 1.3, 0.35), (0.7, 0.7, 0.7))
    mb.box("SV_PaintBlue", (0.2, -1.4, 0.45), (0.9, 0.9, 0.9))
    return mb


def build_market_stall():
    mb = MeshBuilder()
    w, d = 3.6, 2.4
    mb.box("SV_Planks", (0, -d / 2 + 0.1, 1.3), (w, 0.2, 2.6))
    for sx in (-1, 1):
        mb.box("SV_Planks", (sx * (w / 2 - 0.1), 0, 1.3), (0.2, d, 2.6))
    mb.box("SV_Wood", (0, d / 2 - 0.2, 1.0), (w - 0.2, 0.5, 1.0))
    mb.box("SV_WoodLight", (0, d / 2 - 0.1, 1.55), (w, 0.8, 0.08))
    for s in (1, -1):
        R = rot_x(s * math.radians(-28))
        mb.box("SV_Shingle", (0, s * d * 0.28, 3.05), (w + 0.6, d * 0.65, 0.12), matrix=R)
        mb.box("SV_Snow", (0, s * d * 0.28, 3.2), (w + 0.5, d * 0.6, 0.18), matrix=R)
    for i, x in enumerate(np.linspace(-w / 2 + 0.3, w / 2 - 0.3, 6)):
        mb.box("SV_FabricRed" if i % 2 == 0 else "SV_PaintWhite", (x, d / 2 + 0.35, 2.35),
               (w / 6, 0.9, 0.05), matrix=rot_x(math.radians(25)))
    mb.box("SV_WindowWarm", (0, d / 2 - 0.25, 2.1), (w - 0.6, 0.05, 0.12))
    return mb


def build_bleachers():
    mb = MeshBuilder()
    w = 9.0
    for k in range(4):
        mb.box("SV_Wood", (0, -k * 0.9, 0.25 + k * 0.5), (w, 0.9, 0.5 + k * 1.0 if k == 0 else 0.5))
        mb.box("SV_Planks", (0, -k * 0.9 + 0.1, 0.52 + k * 0.5), (w, 0.5, 0.06))
        mb.box("SV_Snow", (0, -k * 0.9 - 0.25, 0.55 + k * 0.5), (w - 0.2, 0.3, 0.06))
    mb.box("SV_Metal", (0, -3.0, 1.2), (w, 0.1, 2.4))
    for x in (-w / 2, w / 2):
        mb.box("SV_Metal", (x, -1.4, 1.3), (0.12, 3.2, 2.6))
    return mb


def build_snowman():
    mb = MeshBuilder()
    for z, r in ((0.7, 0.85), (1.85, 0.62), (2.75, 0.45)):
        mb.ico("SV_Snow", (0, 0, z), r, subdiv=2, smooth=True)
    mb.cone("SV_PaintOrange", (0, 0.42, 2.78), (0, 0.95, 2.76), 0.08, seg=6)
    mb.cylinder("SV_PaintBlack", (0, 0, 3.05), (0, 0, 3.55), 0.3, seg=10)
    mb.cylinder("SV_PaintBlack", (0, 0, 3.05), (0, 0, 3.12), 0.48, seg=10)
    mb.cylinder("SV_FabricRed", (0, 0, 2.3), (0, 0, 2.48), 0.5, seg=10)
    for s in (-1, 1):
        mb.cylinder("SV_Wood", (s * 0.55, 0, 1.95), (s * 1.3, 0, 2.5), 0.04, seg=4)
        mb.ico("SV_PaintBlack", (s * 0.16, 0.4, 2.9), 0.05, subdiv=0)
    return mb


def build_ski_rack():
    mb = MeshBuilder()
    mb.box("SV_Wood", (0, 0, 1.0), (3.2, 0.12, 0.12))
    mb.box("SV_Wood", (0, 0, 0.35), (3.2, 0.4, 0.1))
    for x in (-1.5, 1.5):
        mb.box("SV_WoodDark", (x, 0, 0.6), (0.12, 0.4, 1.2))
    cols = ["SV_PaintRed", "SV_PaintBlue", "SV_PaintYellow", "SV_PaintGreen", "SV_PaintBlack", "SV_PaintOrange"]
    for k, x in enumerate(np.linspace(-1.3, 1.3, 9)):
        mb.box(cols[k % len(cols)], (x, 0.12 if k % 2 else -0.12, 0.95), (0.09, 0.03, 1.75),
               matrix=rot_y(math.radians(8 if k % 2 else -6)))
    return mb


def build_kicker():
    """Snowpark kicker: 10 m long, lip 1.8 m; ramp rises towards +Y."""
    mb = MeshBuilder()
    L, W, lip = 10.0, 8.0, 1.8
    n = 8
    prof = []
    for k in range(n + 1):
        t = k / n
        y = -L / 2 + L * t
        z = lip * t   # straight ramp: matches the Roblox WedgePart collider exactly
        prof.append((y, z))
    verts, faces = [], []
    for y, z in prof:
        verts += [(-W / 2, y, z), (W / 2, y, z), (-W / 2 - 1.5, y, -0.2), (W / 2 + 1.5, y, -0.2)]
    for k in range(n):
        a = 4 * k
        b = a + 4
        faces += [(a, a + 1, b + 1, b), (a + 2, a, b, b + 2), (a + 1, a + 3, b + 3, b + 1)]
    a = 4 * n
    faces.append((a, a + 2, a + 3, a + 1))
    mb.add("SV_PisteGroomed", verts, faces, smooth=True)
    mb.box("SV_PaintBlue", (-W / 2 - 0.2, L / 2 - 0.3, lip * 0.5 + 0.2), (0.2, 0.2, lip + 0.6))
    mb.box("SV_PaintBlue", (W / 2 + 0.2, L / 2 - 0.3, lip * 0.5 + 0.2), (0.2, 0.2, lip + 0.6))
    return mb


def build_snow_cannon():
    mb = MeshBuilder()
    mb.cylinder("SV_MetalLight", (0, 0, -0.4), (0, 0, 6.0), 0.12, seg=6)
    mb.cylinder("SV_PaintYellow", (0, -0.5, 6.0), (0, 1.3, 6.6), 0.55, 0.45, seg=10)
    mb.cylinder("SV_Metal", (0, 1.3, 6.6), (0, 1.5, 6.68), 0.48, seg=10)
    mb.box("SV_PaintYellow", (0, 0, 0.4), (0.8, 0.6, 0.8))
    return mb


def build_footbridge():
    mb = MeshBuilder()
    L, W = 14.0, 3.2
    pts = [(0.0, -L / 2 + L * t, 0.6 + 0.9 * math.sin(t * math.pi)) for t in np.linspace(0, 1, 11)]
    mb.sweep("SV_Planks", pts, [(-W / 2, 0), (W / 2, 0), (W / 2, -0.35), (-W / 2, -0.35)],
             closed_profile=True, up=(0, 0, 1))
    mb.sweep("SV_Snow", [(p[0], p[1], p[2] + 0.06) for p in pts],
             [(-W / 2 + 0.2, 0), (W / 2 - 0.2, 0), (W / 2 - 0.2, -0.05), (-W / 2 + 0.2, -0.05)],
             closed_profile=True, up=(0, 0, 1))
    for s in (-1, 1):
        rail = [(s * W / 2, p[1], p[2] + 1.0) for p in pts]
        mb.sweep("SV_Wood", rail, [(-0.07, -0.07), (0.07, -0.07), (0.07, 0.07), (-0.07, 0.07)],
                 closed_profile=True, up=(0, 0, 1))
        for p in pts[::2]:
            mb.cylinder("SV_WoodDark", (s * W / 2, p[1], p[2] - 0.3), (s * W / 2, p[1], p[2] + 1.05), 0.07, seg=5)
    for y in (-L / 2, L / 2):
        mb.box("SV_Stone", (0, y, 0.0), (W + 1.0, 1.6, 1.6))
    return mb


def build_lookout():
    mb = MeshBuilder()
    w, d = 7.0, 4.5
    mb.box("SV_Planks", (0, 0, 1.2), (w, d, 0.25))
    mb.box("SV_Snow", (0, -0.6, 1.4), (w - 0.6, d * 0.5, 0.1))
    for sx in (-1, 1):
        for sy in (-1, 1):
            mb.cylinder("SV_WoodDark", (sx * (w / 2 - 0.3), sy * (d / 2 - 0.3), -1.5),
                        (sx * (w / 2 - 0.3), sy * (d / 2 - 0.3), 2.4), 0.14, seg=6)
    mb.box("SV_Wood", (0, d / 2 - 0.1, 2.35), (w, 0.14, 0.12))
    mb.box("SV_Snow", (0, d / 2 - 0.1, 2.46), (w - 0.1, 0.16, 0.08))
    for sx in (-1, 1):
        mb.box("SV_Wood", (sx * (w / 2 - 0.1), 0, 2.35), (0.14, d, 0.12))
    for x in np.linspace(-w / 2 + 0.4, w / 2 - 0.4, 9):
        mb.box("SV_WoodLight", (x, d / 2 - 0.1, 1.8), (0.1, 0.06, 1.0))
    # telescope
    mb.cylinder("SV_Metal", (1.8, d / 2 - 0.8, 1.3), (1.8, d / 2 - 0.8, 2.4), 0.07, seg=6)
    mb.cylinder("SV_PaintBlue", (1.8, d / 2 - 1.1, 2.45), (1.8, d / 2 - 0.4, 2.6), 0.15, seg=8)
    return mb


# ---------------------------------------------------------------------------
# gondola pylon & cabin
# ---------------------------------------------------------------------------

GAUGE = 7.0          # distance between the two cable tracks (m)
PYLON_HEIGHTS = {"Pylon14": 14.0, "Pylon20": 20.0, "Pylon26": 26.0, "Pylon32": 32.0}
CABIN_HANG = 3.4     # grip to cabin roof (m)


def build_pylon(h):
    """Tubular gondola pylon. Cable direction = local Y; tracks at x = +-GAUGE/2,
    cable height = h + 0.75 (top of the sheave trains)."""
    mb = MeshBuilder()
    mb.box("SV_StoneBlock", (0, 0, 0.2), (3.2, 3.2, 1.6))
    mb.cylinder("SV_PaintWhite", (0, 0, 0.6), (0, 0, h), 0.85, 0.55, seg=10)
    mb.cylinder("SV_PaintRed", (0, 0, h - 2.5), (0, 0, h - 1.5), 0.6, seg=10)
    # crossarm
    mb.box("SV_Metal", (0, 0, h), (GAUGE + 2.4, 0.7, 0.7))
    mb.box("SV_Metal", (0, -0.9, h + 0.9), (1.6, 1.6, 0.25))   # platform
    for s in (-1, 1):
        x = s * GAUGE / 2
        # sheave train along the cable
        mb.box("SV_Metal", (x, 0, h + 0.35), (0.35, 3.6, 0.35))
        for k in range(4):
            y = -1.35 + k * 0.9
            mb.cylinder("SV_MetalLight", (x - 0.22, y, h + 0.58), (x + 0.22, y, h + 0.58), 0.22, seg=8)
    # ladder
    mb.box("SV_MetalLight", (0, 0.75, h * 0.5 + 0.3), (0.45, 0.08, h - 0.6))
    return mb


def build_cabin():
    """8-seat gondola cabin. Origin = grip on the cable; +Y = travel."""
    mb = MeshBuilder()
    top = -CABIN_HANG
    body_h = 2.3
    # hanger arm and grip
    mb.box("SV_Metal", (0, 0, -0.25), (0.35, 0.9, 0.4))
    mb.cylinder("SV_Metal", (0, 0, -0.3), (0, 0, top + 0.2), 0.09, seg=6)
    mb.cylinder("SV_Metal", (0, 0, top + 0.2), (0, 0.6, top - 0.1), 0.08, seg=6)
    # body: rounded box sections
    mb.rounded_box("SV_PaintRed", (0, 0, top - body_h * 0.72), (2.2, 2.3, body_h * 0.56), 0.35)
    mb.rounded_box("SV_WindowCool", (0, 0, top - body_h * 0.24), (2.15, 2.25, body_h * 0.42), 0.35)
    mb.rounded_box("SV_MetalLight", (0, 0, top - 0.02), (2.1, 2.2, 0.2), 0.35)
    mb.rounded_box("SV_Snow", (0, 0, top + 0.12), (1.8, 1.9, 0.12), 0.3)
    mb.box("SV_PaintWhite", (0, 1.16, top - body_h * 0.7), (1.2, 0.04, 0.3))
    return mb


def all_prop_builders():
    out = {
        "StartGate": ("Start", build_start_gate()),
        "FinishArch": ("Finish", build_finish_arch()),
        "GatePost": ("Props", build_gate_post()),
        "SectionSign": ("Props", build_section_sign()),
        "JunctionSign": ("Props", build_junction_sign()),
        "WarningSign": ("Props", build_warning_sign()),
        "MarkerGreen": ("Props", build_difficulty_marker("green")),
        "MarkerBlue": ("Props", build_difficulty_marker("blue")),
        "MarkerRed": ("Props", build_difficulty_marker("red")),
        "MarkerBlack": ("Props", build_difficulty_marker("black")),
        "PoleBlue": ("Props", build_piste_pole("SV_PaintBlue")),
        "PoleGreen": ("Props", build_piste_pole("SV_PaintGreen")),
        "PoleRed": ("Props", build_piste_pole("SV_PaintRed")),
        "PoleOrange": ("Props", build_piste_pole("SV_PaintOrange")),
        "PoleBlack": ("Props", build_piste_pole("SV_PaintBlack")),
        "FenceRail": ("Props", build_fence_rail()),
        "SafetyNet": ("Props", build_safety_net()),
        "FlagRed": ("Props", build_feather_flag("SV_FabricRed")),
        "FlagBlue": ("Props", build_feather_flag("SV_FabricBlue")),
        "Lamp": ("Props", build_lamp()),
        "Bench": ("Props", build_bench()),
        "XmasTree": ("Finish", build_xmas_tree()),
        "MarketStall": ("Finish", build_market_stall()),
        "Bleachers": ("Finish", build_bleachers()),
        "Snowman": ("Props", build_snowman()),
        "SkiRack": ("Props", build_ski_rack()),
        "Kicker": ("Props", build_kicker()),
        "SnowCannon": ("Props", build_snow_cannon()),
        "FootBridge": ("Bridges", build_footbridge()),
        "Lookout": ("Props", build_lookout()),
        "Cabin": ("Gondola", build_cabin()),
    }
    for k, h in PYLON_HEIGHTS.items():
        out[k] = ("Gondola", build_pylon(h))
    return out
