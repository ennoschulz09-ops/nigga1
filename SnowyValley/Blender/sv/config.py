"""Global configuration for the Snowy Valley generator.

All modelling happens in METERS in Blender (X = east, Y = north, Z = up).
Roblox conversion: 1 stud = 0.28 m, Roblox axes (X, Y up, Z) = (x, z, -y).
"""

import os

SEED = 20261009

# --- Units -----------------------------------------------------------------
METERS_PER_STUD = 0.28
STUDS_PER_METER = 1.0 / METERS_PER_STUD  # 3.5714...

# --- Design targets from the reference sheet -------------------------------
TARGET_MAIN_LENGTH_M = 4800.0
TARGET_ELEVATION_DROP_M = 720.0
TARGET_SECTIONS = 18

# Elevation of the finish plaza (Blender Z). Summit start = 720 m above it.
FINISH_Z = 0.0
START_Z = FINISH_Z + TARGET_ELEVATION_DROP_M

# --- Terrain domain --------------------------------------------------------
# Detailed (playable) terrain area in meters.
DETAIL_MIN_X, DETAIL_MAX_X = -1260.0, 1260.0
DETAIL_MIN_Y, DETAIL_MAX_Y = -1500.0, 1360.0
# Surrounding mid-distance mountains (low resolution ring).
OUTER_MIN_X, OUTER_MAX_X = -2700.0, 2780.0
OUTER_MIN_Y, OUTER_MAX_Y = -2620.0, 2860.0

# Height grid resolutions (meters per cell)
BASE_GRID_RES = 10.0      # coarse diffusion solve
FINE_GRID_RES = 2.0       # final carved heightfield (detail area)
OUTER_GRID_RES = 30.0     # outer ring heightfield

# Roblox limits: MeshPart max 2048 studs per axis, 20k triangles per mesh.
ROBLOX_MAX_PART_STUDS = 2048.0
ROBLOX_MAX_TRIS = 20000
CHUNK_SIZE_M = 420.0      # 1500 studs - safe below 2048 incl. height
TERRAIN_RES_NEAR = 6.0    # chunk vertex spacing near playable corridors
TERRAIN_RES_FAR = 10.0    # chunk vertex spacing elsewhere in detail area
OUTER_CHUNK_SIZE_M = 560.0
OUTER_RES = 28.0

# --- Corridor / collision ----------------------------------------------------
CORRIDOR_LOWER_TERRAIN_M = 0.9   # visual terrain is pushed under ribbons
RIBBON_SKIRT_M = 3.0             # ribbon skirt reaches past corridor edge
RIBBON_SKIRT_DEPTH_M = 1.4
COLLISION_MAX_ROW_SPACING_M = 14.0
COLLISION_TOLERANCE_M = 0.10         # max deviation collision <-> surface on the piste
COLLISION_MARGIN_TOLERANCE_M = 0.35  # ... on the rideable off-piste margins

# --- Paths -----------------------------------------------------------------
BLENDER_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DIR = os.path.dirname(BLENDER_DIR)
EXPORT_DIR = os.path.join(ROOT_DIR, "Export")
METADATA_DIR = os.path.join(ROOT_DIR, "Metadata")
ROBLOX_DIR = os.path.join(ROOT_DIR, "Roblox")
PREVIEW_DIR = os.path.join(ROOT_DIR, "Previews")
BLEND_PATH = os.path.join(BLENDER_DIR, "SnowyValley.blend")

# --- Difficulty colours (sRGB 0-255) ----------------------------------------
COLOR_GREEN = (52, 190, 84)
COLOR_BLUE = (40, 120, 228)
COLOR_RED = (222, 48, 48)
COLOR_BLACK = (30, 30, 34)
DIFFICULTY_COLORS = {"green": COLOR_GREEN, "blue": COLOR_BLUE, "red": COLOR_RED}
