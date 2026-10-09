--!strict
-- Snowy Valley - runtime world API.
--
-- The existing WorldBuilder / RoundManager talk to Snowy Valley only through
-- this module (via Integration.luau):
--   World.GetMapDefinition()  -> data for map voting / UI
--   World.Load(parent?)       -> clones ServerStorage.SnowyValleyWorld into Workspace
--   World.Unload()
--   World.GetSpawnCFrames(), World.GetCheckpointParts(), World.GetRouteGraph() ...

local ServerStorage = game:GetService("ServerStorage")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("SnowyValleyShared")
local Config = require(Shared:WaitForChild("Config"))
local RouteGraph = require(Shared:WaitForChild("RouteGraph"))
local CheckpointTracker = require(Shared:WaitForChild("CheckpointTracker"))
local SharedData = Shared:WaitForChild("Data")
local RouteData = require(SharedData:WaitForChild("RouteData")) :: any
local Checkpoints = require(SharedData:WaitForChild("Checkpoints")) :: any

local PREFIX = Config.AttributePrefix

local World = {}
World.Id = Config.WorldId
World.DisplayName = Config.DisplayName

local loaded: Model? = nil
local graph: any = nil

export type MapDefinition = {
	Id: string,
	DisplayName: string,
	WorldNumber: number,
	LengthMeters: number,
	LengthStuds: number,
	DropMeters: number,
	DropStuds: number,
	CheckpointGroups: number,
	FinishGroup: number,
	Sections: { { Id: number, Name: string, Legend: string, StartMeters: number, EndMeters: number } },
	Routes: { { Id: string, Name: string, Difficulty: string, Kind: string, LengthMeters: number } },
	SpawnCount: number,
}

function World.GetMapDefinition(): MapDefinition
	local K = Config.StudsPerMeter
	local sections = {}
	for _, s in RouteData.sections do
		table.insert(sections, { Id = s.id, Name = s.name, Legend = s.legend, StartMeters = s.start_m, EndMeters = s.end_m })
	end
	local routes = {}
	for _, r in RouteData.routes do
		table.insert(routes, {
			Id = r.id,
			Name = r.name,
			Difficulty = r.difficulty,
			Kind = r.kind,
			LengthMeters = if r.race_length_m then r.race_length_m else r.length_m,
		})
	end
	return {
		Id = Config.WorldId,
		DisplayName = Config.DisplayName,
		WorldNumber = Config.WorldNumber,
		LengthMeters = RouteData.main.race_length_m,
		LengthStuds = RouteData.main.race_length_m * K,
		DropMeters = RouteData.main.drop_m,
		DropStuds = RouteData.main.drop_m * K,
		CheckpointGroups = Checkpoints.group_count,
		FinishGroup = Checkpoints.finish_group,
		Sections = sections,
		Routes = routes,
		SpawnCount = #Checkpoints.spawns,
	}
end

function World.IsBuilt(): boolean
	return ServerStorage:FindFirstChild(Config.BuiltWorldName) ~= nil
end

-- Clone the built world into `parent` (default Workspace). Returns the model.
function World.Load(parent: Instance?): Model
	if loaded and loaded.Parent then
		return loaded
	end
	local source = ServerStorage:FindFirstChild(Config.BuiltWorldName)
	if not source then
		error(
			"[SnowyValley] ServerStorage."
				.. Config.BuiltWorldName
				.. " missing - run Importer.Build() in Studio (see SnowyValleySetup.md)"
		)
	end
	local m = (source :: Model):Clone()
	m.Name = Config.WorldId
	m:SetAttribute(PREFIX .. "Loaded", true)
	m.Parent = parent or workspace
	loaded = m
	return m
end

function World.Unload()
	if loaded then
		loaded:Destroy()
		loaded = nil
	end
end

function World.GetLoaded(): Model?
	return if loaded and loaded.Parent then loaded else nil
end

local function cf(p: { number }, q: { number }): CFrame
	return CFrame.new(p[1], p[2], p[3], q[1], q[2], q[3], q[4])
end

-- Spawn frames behind the start line (16, grid 4 x 4), from data.
function World.GetSpawnCFrames(): { CFrame }
	local out = {}
	for _, s in Checkpoints.spawns do
		table.insert(out, cf(s.position, s.rotation))
	end
	return out
end

-- group -> gate parts of the loaded world (main gate first).
function World.GetCheckpointParts(): { [number]: { BasePart } }
	local out: { [number]: { BasePart } } = {}
	local m = World.GetLoaded()
	if not m then
		return out
	end
	local folder = m:FindFirstChild("Gameplay") and (m :: any).Gameplay:FindFirstChild("Checkpoints")
	if not folder then
		return out
	end
	for _, p in folder:GetChildren() do
		if p:IsA("BasePart") then
			local g = p:GetAttribute(PREFIX .. "Group") :: number
			out[g] = out[g] or {}
			if p:GetAttribute(PREFIX .. "Route") == "MAIN" then
				table.insert(out[g], 1, p)
			else
				table.insert(out[g], p)
			end
		end
	end
	return out
end

function World.GetBoostParts(): { BasePart }
	local out = {}
	local m = World.GetLoaded()
	local folder = m and m:FindFirstChild("Gameplay") and (m :: any).Gameplay:FindFirstChild("Boosts")
	if folder then
		for _, p in folder:GetChildren() do
			if p:IsA("BasePart") then
				table.insert(out, p)
			end
		end
	end
	return out
end

function World.GetRouteGraph(): any
	if not graph then
		graph = RouteGraph.new(RouteData, {
			lateralLimit = Config.Race.OutOfBoundsLateralStuds,
			belowLimit = Config.Race.OutOfBoundsBelowStuds,
			roofLimit = Config.Race.TunnelRoofStuds,
		})
	end
	return graph
end

function World.NewCheckpointTracker(): any
	return CheckpointTracker.new(Checkpoints, { studsPerMeter = Config.StudsPerMeter })
end

return World
