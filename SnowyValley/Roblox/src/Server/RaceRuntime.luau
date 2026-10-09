--!strict
-- Snowy Valley - server race runtime.
--
-- One session per round. Every Heartbeat it samples each racer's
-- HumanoidRootPart and
--   * sweeps the movement against the expected checkpoint gates,
--   * uses continuous in-corridor progress as a fallback gate detector,
--   * detects out-of-bounds (outside corridor, fallen, on the cave roof) and
--     respawns on the last valid route position after a grace period,
--   * reports boost pad touches.
-- Every outcome is reported through the hooks (Integration.luau), so the
-- existing RaceService / CheckpointService stay in charge of the game rules.

local RunService = game:GetService("RunService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("SnowyValleyShared")
local Config = require(Shared:WaitForChild("Config"))
local World = require(script.Parent:WaitForChild("World"))

export type Hooks = {
	OnCheckpoint: ((player: Player, event: any) -> ())?,
	OnFinish: ((player: Player, event: any) -> ())?,
	OnSkip: ((player: Player, event: any) -> ())?,
	-- return true when the game handled the respawn itself
	OnOutOfBounds: ((player: Player, status: string, respawn: CFrame) -> boolean?)?,
	OnBoost: ((player: Player, boost: BasePart) -> ())?,
}

type Racer = {
	player: Player,
	route: string?,
	s: number?,
	lastRoute: string?,
	lastS: number?,
	outSince: number?,
	finished: boolean,
	finishTime: number?,
	respawns: number,
}

local RaceRuntime = {}
RaceRuntime.__index = RaceRuntime

export type Session = typeof(setmetatable(
	{} :: {
		hooks: Hooks,
		graph: any,
		tracker: any,
		racers: { [Player]: Racer },
		running: boolean,
		startTime: number,
		connections: { RBXScriptConnection },
		boostDebounce: { [Player]: { [BasePart]: number } },
	},
	RaceRuntime
))

function RaceRuntime.new(hooks: Hooks?): Session
	return setmetatable({
		hooks = hooks or {},
		graph = World.GetRouteGraph(),
		tracker = World.NewCheckpointTracker(),
		racers = {},
		running = false,
		startTime = 0,
		connections = {},
		boostDebounce = {},
	}, RaceRuntime)
end

function RaceRuntime.AddRacer(self: Session, player: Player)
	self.racers[player] = {
		player = player,
		route = nil,
		s = nil,
		lastRoute = "MAIN",
		lastS = 0,
		outSince = nil,
		finished = false,
		finishTime = nil,
		respawns = 0,
	}
	if self.running then
		self.tracker:Begin(player, os.clock())
	end
end

function RaceRuntime.RemoveRacer(self: Session, player: Player)
	self.racers[player] = nil
	self.tracker:Remove(player)
	self.boostDebounce[player] = nil
end

local function rootOf(player: Player): BasePart?
	local char = player.Character
	local root = char and char:FindFirstChild("HumanoidRootPart")
	return if root and root:IsA("BasePart") then root else nil
end

function RaceRuntime.RespawnFrame(self: Session, player: Player): CFrame
	local r = self.racers[player]
	local route = r and r.lastRoute or "MAIN"
	local s = r and r.lastS or 0
	local x, y, z, tx, tz = self.graph:RespawnFrame(route, s, Config.Race.RespawnBackStuds, Config.Race.RespawnHeightStuds)
	local pos = Vector3.new(x, y, z)
	return CFrame.lookAt(pos, pos + Vector3.new(tx, 0, tz))
end

function RaceRuntime.Respawn(self: Session, player: Player, status: string)
	local r = self.racers[player]
	if not r then
		return
	end
	local frame = self:RespawnFrame(player)
	r.respawns += 1
	r.outSince = nil
	r.s = nil
	self.tracker:ResetSample(player)
	local handled = false
	if self.hooks.OnOutOfBounds then
		handled = self.hooks.OnOutOfBounds(player, status, frame) == true
	end
	if not handled then
		local root = rootOf(player)
		if root then
			root.AssemblyLinearVelocity = Vector3.zero
			root.AssemblyAngularVelocity = Vector3.zero
			root.CFrame = frame
		end
	end
end

local function dispatch(self: Session, player: Player, ev: any)
	if ev.kind == "pass" or ev.kind == "finish" then
		if self.hooks.OnCheckpoint then
			self.hooks.OnCheckpoint(player, ev)
		end
		if ev.kind == "finish" then
			local r = self.racers[player]
			if r then
				r.finished = true
				r.finishTime = ev.time
			end
			if self.hooks.OnFinish then
				self.hooks.OnFinish(player, ev)
			end
		end
	elseif ev.kind == "skip" and self.hooks.OnSkip then
		self.hooks.OnSkip(player, ev)
	end
end

function RaceRuntime.Step(self: Session, now: number)
	local graph, tracker = self.graph, self.tracker
	for player, r in self.racers do
		if r.finished then
			continue
		end
		local root = rootOf(player)
		if not root then
			continue
		end
		local p = root.Position
		for _, ev in tracker:Sample(player, p.X, p.Y, p.Z, now) do
			dispatch(self, player, ev)
		end
		local status, hit = graph:Classify(p.X, p.Y, p.Z, r.route)
		if status == "ok" and hit and hit.edgeDistance <= 0 then
			if r.route == hit.route and r.s then
				local ev = tracker:RouteSample(player, hit.route, r.s, hit.s, now)
				if ev then
					dispatch(self, player, ev)
				end
			end
			r.route, r.s = hit.route, hit.s
			r.lastRoute, r.lastS = hit.route, hit.s
			r.outSince = nil
		elseif status == "ok" then
			-- beside the corridor but within the tolerance: no progress credit
			r.s = nil
			r.outSince = nil
		else
			r.s = nil
			r.outSince = r.outSince or now
			if now - (r.outSince :: number) >= Config.Race.OutOfBoundsGraceSeconds then
				self:Respawn(player, status)
			end
		end
	end
end

function RaceRuntime.Start(self: Session)
	if self.running then
		return
	end
	self.running = true
	local now = os.clock()
	self.startTime = now
	for player in self.racers do
		self.tracker:Begin(player, now)
	end
	table.insert(
		self.connections,
		RunService.Heartbeat:Connect(function()
			self:Step(os.clock())
		end)
	)
	for _, boost in World.GetBoostParts() do
		table.insert(
			self.connections,
			boost.Touched:Connect(function(hit: BasePart)
				local char = hit:FindFirstAncestorOfClass("Model")
				local player = char and game:GetService("Players"):GetPlayerFromCharacter(char)
				if not player or not self.racers[player] then
					return
				end
				local deb = self.boostDebounce[player] or {}
				self.boostDebounce[player] = deb
				local t = os.clock()
				if (deb[boost] or 0) > t then
					return
				end
				deb[boost] = t + 2
				if self.hooks.OnBoost then
					self.hooks.OnBoost(player, boost)
				end
			end)
		)
	end
end

function RaceRuntime.Stop(self: Session)
	self.running = false
	for _, c in self.connections do
		c:Disconnect()
	end
	table.clear(self.connections)
end

-- Finished racers sorted by time, then the others by progress.
function RaceRuntime.GetStandings(self: Session): { { player: Player, finished: boolean, time: number?, nextGroup: number } }
	local out = {}
	for player, r in self.racers do
		table.insert(out, {
			player = player,
			finished = r.finished,
			time = r.finishTime,
			nextGroup = self.tracker:NextGroup(player) or 1,
		})
	end
	table.sort(out, function(a, b)
		if a.finished ~= b.finished then
			return a.finished
		end
		if a.finished then
			return (a.time :: number) < (b.time :: number)
		end
		return a.nextGroup > b.nextGroup
	end)
	return out
end

return RaceRuntime
