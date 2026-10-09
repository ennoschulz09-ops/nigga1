--!strict
-- Snowy Valley - environment preset (late-afternoon alpine light).
--
-- The game's WorldEnvironmentController owns Lighting. Pass `Preset` to it
-- from Integration.ApplyEnvironment. ApplyDirect() exists only for the
-- standalone test mode / places without a controller: it writes Lighting and
-- its own SV_* effect instances and returns a function that restores every
-- value it changed.

local Lighting = game:GetService("Lighting")

local Data = require(script.Parent:WaitForChild("Data"):WaitForChild("Environment")) :: any

local EnvironmentPreset = {}

local function rgb(t: { number }): Color3
	return Color3.fromRGB(t[1], t[2], t[3])
end

-- Plain, controller-friendly description (Roblox value types).
EnvironmentPreset.Preset = {
	Name = Data.name,
	Lighting = {
		ClockTime = Data.lighting.ClockTime,
		GeographicLatitude = Data.lighting.GeographicLatitude,
		Brightness = Data.lighting.Brightness,
		ExposureCompensation = Data.lighting.ExposureCompensation,
		EnvironmentDiffuseScale = Data.lighting.EnvironmentDiffuseScale,
		EnvironmentSpecularScale = Data.lighting.EnvironmentSpecularScale,
		Ambient = rgb(Data.lighting.Ambient),
		OutdoorAmbient = rgb(Data.lighting.OutdoorAmbient),
		ColorShift_Top = rgb(Data.lighting.ColorShift_Top),
		ColorShift_Bottom = rgb(Data.lighting.ColorShift_Bottom),
		ShadowSoftness = Data.lighting.ShadowSoftness,
		GlobalShadows = Data.lighting.GlobalShadows,
		FogColor = rgb(Data.lighting.FogColor),
		FogStart = Data.lighting.FogStart,
		FogEnd = Data.lighting.FogEnd,
	},
	Atmosphere = {
		Density = Data.atmosphere.Density,
		Offset = Data.atmosphere.Offset,
		Color = rgb(Data.atmosphere.Color),
		Decay = rgb(Data.atmosphere.Decay),
		Glare = Data.atmosphere.Glare,
		Haze = Data.atmosphere.Haze,
	},
	Sky = {
		SunAngularSize = Data.sky.SunAngularSize,
		MoonAngularSize = Data.sky.MoonAngularSize,
		StarCount = Data.sky.StarCount,
		CelestialBodiesShown = Data.sky.CelestialBodiesShown,
	},
	Clouds = {
		Cover = Data.clouds.Cover,
		Density = Data.clouds.Density,
		Color = rgb(Data.clouds.Color),
	},
	Bloom = { Intensity = Data.bloom.Intensity, Size = Data.bloom.Size, Threshold = Data.bloom.Threshold },
	ColorCorrection = {
		Brightness = Data.color_correction.Brightness,
		Contrast = Data.color_correction.Contrast,
		Saturation = Data.color_correction.Saturation,
		TintColor = rgb(Data.color_correction.TintColor),
	},
	SunRays = { Intensity = Data.sun_rays.Intensity, Spread = Data.sun_rays.Spread },
}

local function ensure(className: string, name: string, parent: Instance): (Instance, boolean)
	local existing = parent:FindFirstChild(name)
	if existing and existing.ClassName == className then
		return existing, false
	end
	local inst = Instance.new(className)
	inst.Name = name
	inst.Parent = parent
	return inst, true
end

-- Apply the preset straight to Lighting. Returns restore().
function EnvironmentPreset.ApplyDirect(): () -> ()
	local P = EnvironmentPreset.Preset
	local saved: { [string]: any } = {}
	local L = Lighting :: any
	for prop: string, value in P.Lighting :: { [string]: any } do
		saved[prop] = L[prop]
		L[prop] = value
	end
	local created: { Instance } = {}
	local function effect(className: string, name: string, props: { [string]: any }, parent: Instance)
		local inst, isNew = ensure(className, name, parent)
		if isNew then
			table.insert(created, inst)
		end
		local target = inst :: any
		for k, v in props do
			target[k] = v
		end
	end
	-- an Atmosphere / Sky of the game is left untouched if it already exists
	if not Lighting:FindFirstChildOfClass("Atmosphere") then
		effect("Atmosphere", "SV_Atmosphere", P.Atmosphere, Lighting)
	end
	if not Lighting:FindFirstChildOfClass("Sky") then
		effect("Sky", "SV_Sky", P.Sky, Lighting)
	end
	effect("BloomEffect", "SV_Bloom", P.Bloom, Lighting)
	effect("ColorCorrectionEffect", "SV_ColorCorrection", P.ColorCorrection, Lighting)
	effect("SunRaysEffect", "SV_SunRays", P.SunRays, Lighting)
	if not workspace.Terrain:FindFirstChildOfClass("Clouds") then
		effect("Clouds", "SV_Clouds", P.Clouds, workspace.Terrain)
	end
	return function()
		for prop, value in saved do
			L[prop] = value
		end
		for _, inst in created do
			inst:Destroy()
		end
	end
end

return EnvironmentPreset
