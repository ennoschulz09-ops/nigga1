--!strict
-- Snowy Valley - checkpoint validation with equivalent gates.
--
-- Rule (Checkpoints.json): every racer must pass checkpoint groups 1..18 in
-- order. A group may own several equivalent gates (main route + the
-- alternatives that bypass it); passing ANY gate of the expected group
-- counts. A gate of a later group before the expected one is a skip and is
-- rejected, so shortcuts across the mountain never validate.
--
-- Detection never relies on Touched alone:
--   * Sample(): the movement segment between two position samples is tested
--     against the expected gates' planes (no tunnelling at high speed);
--   * RouteSample(): continuous progress along one route corridor past a
--     gate's station also passes it (covers jumps over a gate). It requires
--     two consecutive in-corridor samples on the same route less than
--     maxRouteStep studs apart, so hopping between hairpin legs cannot pass.
--
-- Pure Luau on numbers; the race runtime feeds it positions.

local Tracker = {}
Tracker.__index = Tracker

type Gate = {
	id: string,
	group: number,
	route: string,
	isFinish: boolean,
	isStart: boolean,
	station: number, -- studs along its own route
	progress: number, -- studs of main progress
	cx: number,
	cy: number,
	cz: number,
	rx: number,
	ry: number,
	rz: number,
	ux: number,
	uy: number,
	uz: number,
	bx: number,
	by: number,
	bz: number,
	hw: number,
	hh: number,
}

type PlayerState = {
	nextGroup: number,
	passedGate: { [number]: string },
	passedTime: { [number]: number },
	startTime: number,
	finishTime: number?,
	finished: boolean,
	skips: number,
	hasLast: boolean,
	lx: number,
	ly: number,
	lz: number,
}

export type Event = {
	kind: string, -- "pass" | "finish" | "skip"
	group: number,
	expected: number,
	gateId: string,
	route: string,
	time: number, -- seconds since Begin
	source: string, -- "sweep" | "route" | "touch"
}

export type Tracker = typeof(setmetatable(
	{} :: {
		groupCount: number,
		finishGroup: number,
		gatesByGroup: { [number]: { Gate } },
		gateById: { [string]: Gate },
		players: { [any]: PlayerState },
		maxRouteStep: number,
		studsPerMeter: number,
	},
	Tracker
))

local function axesFromQuat(q: { number }): (number, number, number, number, number, number, number, number, number)
	local x, y, z, w = q[1], q[2], q[3], q[4]
	-- rotation matrix columns: right (X), up (Y), back (Z)
	local rx, ry, rz = 1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)
	local ux, uy, uz = 2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)
	local bx, by, bz = 2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)
	return rx, ry, rz, ux, uy, uz, bx, by, bz
end

type Options = { maxRouteStep: number?, studsPerMeter: number? }

function Tracker.new(data: any, options: Options?): Tracker
	local opts: Options = options or {}
	local K = opts.studsPerMeter or 1 / 0.28
	local self = setmetatable({
		groupCount = data.group_count :: number,
		finishGroup = data.finish_group :: number,
		gatesByGroup = {} :: { [number]: { Gate } },
		gateById = {} :: { [string]: Gate },
		players = {} :: { [any]: PlayerState },
		maxRouteStep = opts.maxRouteStep or 60,
		studsPerMeter = K,
	}, Tracker)
	for _, grp in data.groups do
		local list: { Gate } = {}
		for _, g in grp.gates do
			local rx, ry, rz, ux, uy, uz, bx, by, bz = axesFromQuat(g.rotation)
			local gate: Gate = {
				id = g.id,
				group = g.group,
				route = g.route,
				isFinish = g.is_finish,
				isStart = g.is_start,
				station = g.station_m * K,
				progress = g.progress_studs,
				cx = g.position[1],
				cy = g.position[2],
				cz = g.position[3],
				rx = rx,
				ry = ry,
				rz = rz,
				ux = ux,
				uy = uy,
				uz = uz,
				bx = bx,
				by = by,
				bz = bz,
				hw = g.size[1] / 2,
				hh = g.size[2] / 2,
			}
			table.insert(list, gate)
			self.gateById[gate.id] = gate
		end
		self.gatesByGroup[grp.group] = list
	end
	return self
end

function Tracker.Begin(self: Tracker, key: any, now: number)
	self.players[key] = {
		nextGroup = 1,
		passedGate = {},
		passedTime = {},
		startTime = now,
		finishTime = nil,
		finished = false,
		skips = 0,
		hasLast = false,
		lx = 0,
		ly = 0,
		lz = 0,
	}
end

function Tracker.Remove(self: Tracker, key: any)
	self.players[key] = nil
end

-- Forget the last sample (call after a teleport / respawn).
function Tracker.ResetSample(self: Tracker, key: any)
	local st = self.players[key]
	if st then
		st.hasLast = false
	end
end

local function accept(self: Tracker, st: PlayerState, gate: Gate, now: number, source: string): Event
	st.passedGate[gate.group] = gate.id
	st.passedTime[gate.group] = now - st.startTime
	local kind = "pass"
	if gate.group >= self.finishGroup then
		st.finished = true
		st.finishTime = now - st.startTime
		kind = "finish"
	end
	st.nextGroup = gate.group + 1
	return {
		kind = kind,
		group = gate.group,
		expected = gate.group,
		gateId = gate.id,
		route = gate.route,
		time = now - st.startTime,
		source = source,
	}
end

-- Segment (x0,y0,z0) -> (x1,y1,z1) crosses the gate plane forwards (travel =
-- -back) inside the gate rectangle?
local function crosses(g: Gate, x0: number, y0: number, z0: number, x1: number, y1: number, z1: number): boolean
	local ax, ay, az = x0 - g.cx, y0 - g.cy, z0 - g.cz
	local bx, by, bz = x1 - g.cx, y1 - g.cy, z1 - g.cz
	local da = ax * g.bx + ay * g.by + az * g.bz
	local db = bx * g.bx + by * g.by + bz * g.bz
	if not (da > 0 and db <= 0) then
		return false
	end
	local f = da / (da - db)
	local px, py, pz = ax + (bx - ax) * f, ay + (by - ay) * f, az + (bz - az) * f
	local lx = px * g.rx + py * g.ry + pz * g.rz
	local ly = px * g.ux + py * g.uy + pz * g.uz
	return math.abs(lx) <= g.hw and math.abs(ly) <= g.hh
end

-- Feed a new position sample. Returns the events it produced (may be empty).
function Tracker.Sample(self: Tracker, key: any, x: number, y: number, z: number, now: number): { Event }
	local st = self.players[key]
	local events: { Event } = {}
	if not st or st.finished then
		return events
	end
	if st.hasLast then
		-- the expected group, then every later group (skip = shortcut attempt;
		-- reported, never counted). ~25 gates: cheap enough for every sample.
		local g0 = st.nextGroup
		for grp = g0, self.groupCount do
			local gates = self.gatesByGroup[grp]
			if not gates then
				continue
			end
			local hit = false
			for _, gate in gates do
				if crosses(gate, st.lx, st.ly, st.lz, x, y, z) then
					hit = true
					if grp == st.nextGroup then
						table.insert(events, accept(self, st, gate, now, "sweep"))
					else
						st.skips += 1
						table.insert(events, {
							kind = "skip",
							group = grp,
							expected = st.nextGroup,
							gateId = gate.id,
							route = gate.route,
							time = now - st.startTime,
							source = "sweep",
						})
					end
					break
				end
			end
			if hit or st.finished then
				break
			end
		end
	end
	st.hasLast = true
	st.lx, st.ly, st.lz = x, y, z
	return events
end

-- Progress fallback: two consecutive in-corridor samples on the same route at
-- stations sPrev -> sCur (studs). Passes the expected group if one of its
-- gates on that route lies in (sPrev, sCur].
function Tracker.RouteSample(self: Tracker, key: any, routeId: string, sPrev: number, sCur: number, now: number): Event?
	local st = self.players[key]
	if not st or st.finished then
		return nil
	end
	if sCur <= sPrev or sCur - sPrev > self.maxRouteStep then
		return nil
	end
	local gates = self.gatesByGroup[st.nextGroup]
	if not gates then
		return nil
	end
	for _, gate in gates do
		if gate.route == routeId and gate.station > sPrev and gate.station <= sCur then
			return accept(self, st, gate, now, "route")
		end
	end
	return nil
end

-- Touch-based input (e.g. from an existing CheckpointService). Only the
-- expected group is accepted; earlier groups are ignored, later ones are skips.
function Tracker.Touch(self: Tracker, key: any, gateId: string, now: number): Event?
	local st = self.players[key]
	local gate = self.gateById[gateId]
	if not st or not gate or st.finished then
		return nil
	end
	if gate.group == st.nextGroup then
		return accept(self, st, gate, now, "touch")
	elseif gate.group > st.nextGroup then
		st.skips += 1
		return {
			kind = "skip",
			group = gate.group,
			expected = st.nextGroup,
			gateId = gate.id,
			route = gate.route,
			time = now - st.startTime,
			source = "touch",
		}
	end
	return nil
end

function Tracker.GetState(self: Tracker, key: any): PlayerState?
	return self.players[key]
end

function Tracker.NextGroup(self: Tracker, key: any): number?
	local st = self.players[key]
	return st and st.nextGroup or nil
end

function Tracker.LastGate(self: Tracker, key: any): string?
	local st = self.players[key]
	if not st then
		return nil
	end
	for grp = st.nextGroup - 1, 1, -1 do
		local id = st.passedGate[grp]
		if id then
			return id
		end
	end
	return nil
end

function Tracker.GetGate(self: Tracker, gateId: string): Gate?
	return self.gateById[gateId]
end

function Tracker.GatesOfGroup(self: Tracker, group: number): { Gate }
	return self.gatesByGroup[group] or {}
end

return Tracker
