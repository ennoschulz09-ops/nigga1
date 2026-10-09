"""Snowy Valley procedural world generator for AVALANCHE RIDERS.

The package is split into pure-numpy modules (layout, routes, terrain,
validation, metadata) that also run outside Blender, and bpy modules
(meshes, assets, placement, export, render) that need Blender.
"""

GENERATOR_VERSION = "1.0.0"
