"""Preview rendering (Cycles CPU) for visual acceptance checks."""

import math
import os

import bpy
import numpy as np
from mathutils import Euler, Vector

from . import config


def setup_world(sun_elev_deg=24.0, sun_azim_deg=222.0):
    scn = bpy.context.scene
    world = bpy.data.worlds.new("SV_World")
    scn.world = world
    world.use_nodes = True
    nt = world.node_tree
    bg = nt.nodes.get("Background")
    sky = nt.nodes.new("ShaderNodeTexSky")
    try:
        sky.sky_type = "MULTIPLE_SCATTERING"
    except Exception:
        sky.sky_type = "HOSEK_WILKIE"
    for attr, val in (("sun_elevation", math.radians(sun_elev_deg)),
                      ("sun_rotation", math.radians(sun_azim_deg)),
                      ("altitude", 1800.0), ("air_density", 1.0), ("aerosol_density", 1.3),
                      ("ozone_density", 1.0), ("sun_disc", True), ("sun_size", math.radians(0.8)),
                      ("sun_intensity", 0.45)):
        if hasattr(sky, attr):
            try:
                setattr(sky, attr, val)
            except Exception:
                pass
    nt.links.new(sky.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 0.30
    # sun lamp (warm late afternoon)
    sun_data = bpy.data.lights.new("SV_Sun", "SUN")
    sun_data.energy = 4.2
    sun_data.angle = math.radians(1.2)
    sun_data.color = (1.0, 0.88, 0.74)
    sun = bpy.data.objects.new("SV_Sun", sun_data)
    scn.collection.objects.link(sun)
    # light travels from the sun towards the scene
    az = math.radians(sun_azim_deg)
    el = math.radians(sun_elev_deg)
    d = Vector((math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)))
    sun.rotation_euler = d.to_track_quat("Z", "Y").to_euler()
    # volumetric-free distance haze via mist pass is costly; use world fog look
    return sun


def setup_render(res=(1280, 720), samples=40):
    scn = bpy.context.scene
    scn.render.engine = "CYCLES"
    scn.cycles.device = "CPU"
    scn.cycles.samples = samples
    scn.cycles.use_denoising = True
    try:
        scn.cycles.denoiser = "OPENIMAGEDENOISE"
    except Exception:
        pass
    scn.cycles.max_bounces = 4
    scn.cycles.diffuse_bounces = 2
    scn.cycles.glossy_bounces = 2
    scn.cycles.transmission_bounces = 2
    scn.cycles.transparent_max_bounces = 4
    scn.render.resolution_x, scn.render.resolution_y = res
    scn.render.resolution_percentage = 100
    scn.render.film_transparent = False
    scn.view_settings.view_transform = "AgX"
    try:
        scn.view_settings.look = "AgX - Medium High Contrast"
    except Exception:
        pass
    scn.view_settings.exposure = -0.45
    scn.render.threads_mode = "AUTO"


def camera(name, loc, target, lens=35.0, ortho_scale=None, clip_end=20000.0):
    cam_data = bpy.data.cameras.new(name)
    cam_data.lens = lens
    cam_data.clip_start = 0.5
    cam_data.clip_end = clip_end
    if ortho_scale:
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = ortho_scale
    cam = bpy.data.objects.new(name, cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = Vector(loc)
    direction = Vector(target) - Vector(loc)
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return cam


def render_to(cam, path):
    scn = bpy.context.scene
    scn.camera = cam
    scn.render.filepath = path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.render.render(write_still=True)
    return path


def add_fog(density=0.00006):
    """Cheap aerial perspective: a huge volume box with low density."""
    scn = bpy.context.scene
    nt = scn.world.node_tree
    vol = nt.nodes.new("ShaderNodeVolumePrincipled")
    vol.inputs["Density"].default_value = density
    vol.inputs["Color"].default_value = (0.75, 0.82, 0.95, 1.0)
    out = nt.nodes.get("World Output")
    nt.links.new(vol.outputs["Volume"], out.inputs["Volume"])
