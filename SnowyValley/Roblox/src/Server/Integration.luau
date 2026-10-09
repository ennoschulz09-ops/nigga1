--!strict
-- ============================================================================
-- Snowy Valley  <->  existing AVALANCHE RIDERS systems (ADAPTER)
-- ============================================================================
-- This is the ONLY Snowy Valley file that knows the game's existing services
-- (WorldBuilder, RaceService, CheckpointService, RoundManager, map voting,
-- WorldEnvironmentController). Every place to connect is marked
--     -- INTEGRATION:
-- The defaults below work without any existing service (standalone test
-- mode) and never touch the other four worlds. The installer keeps an
-- existing copy of this file when the package is updated.
-- ============================================================================

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerScriptService = game:GetService("ServerScriptService")

local Shared = ReplicatedStorage:WaitForChild("SnowyValleyShared")
local Config = require(Shared:WaitForChild("Config"))
local EnvironmentPreset = require(Shared:WaitForChild("EnvironmentPreset"))
local World = require(script.Parent:WaitForChild("World"))
local RaceRuntime = require(script.Parent:WaitForChild("RaceRuntime"))

local Integration = {}

Integration.World = World
Integration.Config = Config
Integration.EnvironmentPreset = EnvironmentPreset

-- Optional references to the existing services (fill in Integration.Init).
local Services: { [string]: any } = {}

-- Find a ModuleScript by name anywhere below ServerScriptService and require
-- it (returns nil if it does not exist). Adjust names/paths to your project.
local function tryRequire(name: string): any
	local m = ServerScriptService:FindFirstChild(name, true)
	if m and m:IsA("ModuleScript") then
		local ok, result = pcall(require, m)
		if ok then
			return result
		end
		warn("[SnowyValley] could not require", name, result)
	end
	return nil
end

Integration.TryRequire = tryRequire

-- ---------------------------------------------------------------------------
-- 1) Startup: register Snowy Valley as World 1
-- ---------------------------------------------------------------------------
function Integration.Init()
	-- INTEGRATION: reference your existing modules here. Nothing is required
	-- automatically (requiring a module early could start it twice), e.g.:
	--   Services.WorldBuilder = tryRequire("WorldBuilder")
	--   Services.RaceService = tryRequire("RaceService")
	--   Services.CheckpointService = tryRequire("CheckpointService")
	--   Services.RoundManager = tryRequire("RoundManager")
	--   Services.MapVoting = tryRequire("MapVoting")
	--   Services.WorldEnvironmentController = tryRequire("WorldEnvironmentController")
	-- (tryRequire finds a ModuleScript by name anywhere below ServerScriptService.)

	if not World.IsBuilt() then
		warn("[SnowyValley] ServerStorage." .. Config.BuiltWorldName .. " not built yet - run Importer.Build() in Studio")
	end

	local def = World.GetMapDefinition()
	-- INTEGRATION: register the map with map voting / the world list, e.g.
	--   Services.MapVoting.RegisterMap(def.Id, def.DisplayName, def)
	--   Services.WorldBuilder:RegisterWorld(def.Id, {
	--       Load = Integration.LoadWorld, Unload = Integration.UnloadWorld })
	print(string.format("[SnowyValley] ready: %s, %.0f m / %.0f m drop, %d checkpoint groups",
		def.DisplayName, def.LengthMeters, def.DropMeters, def.CheckpointGroups))
	return def
end

-- ---------------------------------------------------------------------------
-- 2) World loading (called by WorldBuilder when Snowy Valley wins the vote)
-- ---------------------------------------------------------------------------
function Integration.LoadWorld(parent: Instance?): Model
	local model = World.Load(parent)
	Integration.ApplyEnvironment()
	return model
end

function Integration.UnloadWorld()
	Integration.StopRace()
	World.Unload()
	Integration.RevertEnvironment()
end

-- ---------------------------------------------------------------------------
-- 3) Environment (Lighting stays owned by WorldEnvironmentController)
-- ---------------------------------------------------------------------------
local restoreLighting: (() -> ())? = nil

function Integration.ApplyEnvironment()
	local controller = Services.WorldEnvironmentController
	if controller then
		-- INTEGRATION: hand the preset to your controller, e.g.
		--   controller:ApplyPreset(EnvironmentPreset.Preset)
		-- (EnvironmentPreset.Preset holds Lighting / Atmosphere / Sky / Clouds /
		-- Bloom / ColorCorrection / SunRays values as Roblox types.)
		return
	end
	-- standalone fallback only: writes Lighting directly, restorable
	if Config.StandaloneEnvironment ~= false and not restoreLighting then
		restoreLighting = EnvironmentPreset.ApplyDirect()
	end
end

function Integration.RevertEnvironment()
	if restoreLighting then
		restoreLighting()
		restoreLighting = nil
	end
end

-- ---------------------------------------------------------------------------
-- 4) Race wiring (RaceService / CheckpointService / RoundManager)
-- ---------------------------------------------------------------------------
-- The race runtime detects gates (sweep + route progress, equivalent gates on
-- the alternatives), out-of-bounds and boosts, and reports through these
-- hooks. Forward them to the existing services here.
Integration.Hooks = {
	OnCheckpoint = function(player: Player, event: any)
		-- INTEGRATION: e.g. Services.CheckpointService:CheckpointReached(player, event.group)
		-- event = {kind, group, gateId, route, time (s since start), source}
		if Config.Verbose then
			print(string.format("[SnowyValley] %s passed group %d (%s, %s) at %.2f s",
				player.Name, event.group, event.gateId, event.source, event.time))
		end
	end,
	OnFinish = function(player: Player, event: any)
		-- INTEGRATION: e.g. Services.RaceService:PlayerFinished(player, event.time)
		print(string.format("[SnowyValley] %s finished in %.2f s", player.Name, event.time))
	end,
	OnSkip = function(player: Player, event: any)
		-- A later group was crossed before the expected one (shortcut attempt).
		-- It is NOT counted; the player can still finish by riding the course.
		if Config.Verbose then
			warn(string.format("[SnowyValley] %s skipped to group %d (expected %d) - not counted",
				player.Name, event.group, event.expected))
		end
	end,
	OnOutOfBounds = function(player: Player, status: string, respawn: CFrame): boolean?
		-- INTEGRATION: return true if your RaceService handles the respawn
		-- itself (e.g. Services.RaceService:Respawn(player, respawn)).
		-- Returning nil/false teleports the character to `respawn`.
		return nil
	end,
	OnBoost = function(player: Player, boost: BasePart)
		-- INTEGRATION: apply your game's boost (speed is owned by the board
		-- physics); boost:GetAttribute("SV_BoostDirection"/"SV_BoostStrength").
	end,
}

local session: RaceRuntime.Session? = nil

-- Called by RoundManager / RaceService when the countdown ends.
function Integration.StartRace(players: { Player }): RaceRuntime.Session
	Integration.StopRace()
	local s = RaceRuntime.new(Integration.Hooks)
	for _, p in players do
		s:AddRacer(p)
	end
	s:Start()
	session = s
	return s
end

function Integration.StopRace()
	if session then
		session:Stop()
		session = nil
	end
end

function Integration.GetSession(): RaceRuntime.Session?
	return session
end

-- Spawn frames for RoundManager (16 slots behind the start line).
function Integration.GetSpawnCFrames(): { CFrame }
	return World.GetSpawnCFrames()
end

return Integration
