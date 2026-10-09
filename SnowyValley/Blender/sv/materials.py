"""Material library: one table drives Blender preview shading AND the
Roblox Material / Color / Reflectance / Transparency written to the manifest.

Roblox only supports one material per MeshPart, so every exported object
carries exactly one of these materials.  Roblox's built-in materials are
used (no texture uploads needed) except for the palette-textured trees.
"""

# name: (roblox_material, (r, g, b) sRGB 0-255, extra dict)
MATERIALS = {
    # snow & ground
    "SV_Snow":         ("Snow", (242, 247, 255), dict(rough=0.8)),
    "SV_SnowSoft":     ("Snow", (232, 240, 252), dict(rough=0.85)),
    "SV_PisteGroomed": ("Snow", (226, 236, 251), dict(rough=0.55)),
    "SV_Powder":       ("Snow", (248, 251, 255), dict(rough=0.9)),
    "SV_SnowPlaza":    ("Snow", (236, 238, 244), dict(rough=0.7)),
    "SV_Rock":         ("Rock", (104, 106, 116), dict(rough=0.9)),
    "SV_RockDark":     ("Slate", (74, 78, 90), dict(rough=0.9)),
    "SV_RockWarm":     ("Rock", (126, 116, 108), dict(rough=0.9)),
    # ice
    "SV_Ice":          ("Ice", (172, 218, 244), dict(rough=0.08, reflectance=0.18)),
    "SV_Glacier":      ("Glacier", (150, 206, 238), dict(rough=0.2)),
    "SV_IceDeep":      ("Glacier", (92, 168, 222), dict(rough=0.15)),
    "SV_IceGlow":      ("Neon", (120, 210, 255), dict(emit=2.5)),
    # wood / stone / building
    "SV_Wood":         ("Wood", (128, 86, 54), dict(rough=0.75)),
    "SV_WoodDark":     ("Wood", (82, 54, 36), dict(rough=0.8)),
    "SV_WoodLight":    ("WoodPlanks", (176, 128, 84), dict(rough=0.75)),
    "SV_Planks":       ("WoodPlanks", (150, 100, 64), dict(rough=0.75)),
    "SV_Shingle":      ("WoodPlanks", (96, 64, 46), dict(rough=0.85)),
    "SV_Stone":        ("Cobblestone", (152, 150, 148), dict(rough=0.9)),
    "SV_StoneBlock":   ("Slate", (140, 136, 132), dict(rough=0.85)),
    "SV_Plaster":      ("SmoothPlastic", (238, 230, 214), dict(rough=0.7)),
    "SV_WindowWarm":   ("Neon", (255, 188, 112), dict(emit=1.6)),
    "SV_WindowCool":   ("Glass", (150, 186, 214), dict(rough=0.05, transparency=0.25)),
    "SV_Metal":        ("Metal", (70, 74, 82), dict(rough=0.4, metal=1.0)),
    "SV_MetalLight":   ("Metal", (168, 172, 180), dict(rough=0.35, metal=1.0)),
    "SV_Cable":        ("Metal", (36, 36, 40), dict(rough=0.5, metal=1.0)),
    # paints / fabrics / signage
    "SV_PaintRed":     ("SmoothPlastic", (200, 38, 38), dict(rough=0.4)),
    "SV_PaintBlue":    ("SmoothPlastic", (36, 108, 214), dict(rough=0.4)),
    "SV_PaintGreen":   ("SmoothPlastic", (44, 168, 76), dict(rough=0.4)),
    "SV_PaintYellow":  ("SmoothPlastic", (246, 196, 44), dict(rough=0.4)),
    "SV_PaintOrange":  ("SmoothPlastic", (240, 120, 30), dict(rough=0.4)),
    "SV_PaintWhite":   ("SmoothPlastic", (244, 244, 246), dict(rough=0.4)),
    "SV_PaintBlack":   ("SmoothPlastic", (30, 32, 36), dict(rough=0.4)),
    "SV_PaintPurple":  ("SmoothPlastic", (146, 84, 196), dict(rough=0.4)),
    "SV_FabricRed":    ("Fabric", (190, 36, 40), dict(rough=0.9)),
    "SV_FabricBlue":   ("Fabric", (34, 92, 190), dict(rough=0.9)),
    "SV_SignBoard":    ("SmoothPlastic", (24, 44, 78), dict(rough=0.5)),
    "SV_LightGold":    ("Neon", (255, 210, 120), dict(emit=3.0)),
    "SV_LightRed":     ("Neon", (255, 70, 60), dict(emit=3.0)),
    "SV_LightBlue":    ("Neon", (90, 170, 255), dict(emit=3.0)),
    # vegetation (palette textured)
    "SV_TreeAtlas":    ("SmoothPlastic", (255, 255, 255), dict(rough=0.85, texture="SV_TreePalette.png")),
    "SV_Foliage":      ("Grass", (40, 86, 58), dict(rough=0.9)),
    "SV_Bark":         ("Wood", (92, 62, 44), dict(rough=0.9)),
}

DIFFICULTY_PAINT = {"green": "SV_PaintGreen", "blue": "SV_PaintBlue", "red": "SV_PaintRed",
                    "black": "SV_PaintBlack", "purple": "SV_PaintPurple", "orange": "SV_PaintOrange"}


def roblox_info(name):
    rbx, col, extra = MATERIALS[name]
    info = {"Material": rbx, "Color": list(col)}
    if "reflectance" in extra:
        info["Reflectance"] = extra["reflectance"]
    if "transparency" in extra:
        info["Transparency"] = extra["transparency"]
    if "texture" in extra:
        info["Texture"] = extra["texture"]
    return info


def srgb_to_linear(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


# Tree palette texture: swatch name -> (u, v) centre in a 4x4 grid
TREE_PALETTE = {
    "trunk": (0, 0, (96, 64, 44)),
    "trunk_dark": (1, 0, (70, 46, 32)),
    "needle_dark": (2, 0, (26, 62, 46)),
    "needle_mid": (3, 0, (40, 92, 62)),
    "needle_light": (0, 1, (58, 116, 74)),
    "needle_blue": (1, 1, (30, 72, 66)),
    "snow": (2, 1, (246, 250, 255)),
    "snow_shadow": (3, 1, (206, 222, 242)),
    "snow_warm": (0, 2, (255, 248, 240)),
    "dead": (1, 2, (110, 96, 84)),
}
PALETTE_GRID = 4


def palette_uv(key):
    i, j, _ = TREE_PALETTE[key]
    return ((i + 0.5) / PALETTE_GRID, 1.0 - (j + 0.5) / PALETTE_GRID)


def save_png(path, rgb):
    """Save an (H, W, 3) uint8 array as PNG (Pillow if present, else bpy)."""
    import numpy as np
    rgb = np.asarray(rgb, dtype=np.uint8)
    try:
        from PIL import Image
        Image.fromarray(rgb).save(path)
        return path
    except ImportError:
        pass
    import bpy
    h, w, _ = rgb.shape
    img = bpy.data.images.new("tmp_png", width=w, height=h, alpha=True)
    rgba = np.concatenate([rgb, np.full((h, w, 1), 255, np.uint8)], axis=2)
    # Blender images are stored bottom-up
    img.pixels.foreach_set((rgba[::-1].astype(np.float32) / 255.0).ravel())
    img.filepath_raw = path
    img.file_format = "PNG"
    img.save()
    bpy.data.images.remove(img)
    return path


def write_palette_png(path, size=256):
    import numpy as np
    rgb = np.zeros((size, size, 3), dtype=np.uint8)
    rgb[:] = (255, 0, 255)
    cell = size // PALETTE_GRID
    for key, (i, j, col) in TREE_PALETTE.items():
        rgb[j * cell:(j + 1) * cell, i * cell:(i + 1) * cell] = col
    return save_png(path, rgb)
