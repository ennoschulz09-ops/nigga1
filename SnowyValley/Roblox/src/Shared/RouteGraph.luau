--!strict
-- Snowy Valley - route graph built from RouteData.
--
-- Answers, for any position: which route corridor it is on, the station and
-- race progress there, the signed lateral offset and how far outside the
-- rideable corridor (piste + margins) it is. Used for out-of-bounds
-- detection, respawn frames and the progress-based checkpoint fallback.
--
-- Pure Luau on plain numbers (no Roblox types), so the same module runs in
-- Studio and in the standalone `luau` test runner.

local RouteGraph = {}
RouteGraph.__index = RouteGraph

local CELL = 96 -- studs, spatial hash cell size (XZ plane)
local SURF_TUNNEL = 2

type Route = {
	id: string,
	name: string,
	kind: string,
	difficulty: string,
	index: number,
	n: number,
	x: { number },
	y: { number },
	z: { number },
	s: { number }, -- studs along this route
	progress: { number }, -- studs of main-route progress
	halfWidth: { number },
	marginL: { number },
	marginR: { number },
	surface: { number },
	section: { number },
	length: number,
}

export type Hit = {
	route: string,
	routeIndex: number,
	segment: number,
	t: number,
	s: number, -- studs along the hit route
	progress: number, -- studs of main-route progress
	lateral: number, -- signed horizontal offset, + = right of travel
	distance: number, -- horizontal distance to the centreline
	halfWidth: number,
	margin: number, -- margin on the side of the position
	edgeDistance: number, -- > 0: studs outside the rideable corridor
	x: number, -- centreline point
	y: number,
	z: number,
	tx: number, -- horizontal unit travel direction
	tz: number,
	surface: number, -- 0 ground, 1 bridge, 2 tunnel
	section: number,
}

export type Status = "ok" | "outside" | "below" | "roof" | "far"

export type Options = {
	lateralLimit: number?, -- studs outside the corridor before "outside"
	belowLimit: number?, -- studs below the centreline before "below"
	roofLimit: number?, -- studs above a tunnel floor before "roof"
}

export type RouteGraph = typeof(setmetatable(
	{} :: {
		routes: { Route },
		byId: { [string]: Route },
		cellRoute: { [number]: { number } },
		cellSeg: { [number]: { number } },
		studsPerMeter: number,
		raceLength: number,
		lateralLimit: number,
		belowLimit: number,
		roofLimit: number,
	},
	RouteGraph
))

local function cellKey(cx: number, cz: number): number
	return (cx + 32768) * 65536 + (cz + 32768)
end

local function lerp(a: number, b: number, t: number): number
	return a + (b - a) * t
end

function RouteGraph.new(data: any, options: Options?): RouteGraph
	local opts: Options = options or {}
	local K: number = data.units.studs_per_meter
	local self = setmetatable({
		routes = {} :: { Route },
		byId = {} :: { [string]: Route },
		cellRoute = {} :: { [number]: { number } },
		cellSeg = {} :: { [number]: { number } },
		studsPerMeter = K,
		raceLength = (data.main.race_length_m :: number) * K,
		lateralLimit = opts.lateralLimit or 30,
		belowLimit = opts.belowLimit or 60,
		roofLimit = opts.roofLimit or 55,
	}, RouteGraph)

	for ri, def in data.routes do
		local samples = def.samples
		local n = #samples
		local route: Route = {
			id = def.id,
			name = def.name,
			kind = def.kind,
			difficulty = def.difficulty,
			index = ri,
			n = n,
			x = table.create(n),
			y = table.create(n),
			z = table.create(n),
			s = table.create(n),
			progress = table.create(n),
			halfWidth = table.create(n),
			marginL = table.create(n),
			marginR = table.create(n),
			surface = table.create(n),
			section = table.create(n),
			length = (def.length_m :: number) * K,
		}
		for i, smp in samples do
			route.x[i] = smp[1]
			route.y[i] = smp[2]
			route.z[i] = smp[3]
			route.s[i] = smp[4] * K
			route.progress[i] = smp[5] * K
			route.halfWidth[i] = smp[6]
			route.marginL[i] = smp[7]
			route.marginR[i] = smp[8]
			route.surface[i] = smp[9]
			route.section[i] = smp[10]
		end
		self.routes[ri] = route
		self.byId[route.id] = route
		-- register every segment in all cells its corridor (+ lateral limit) touches
		for i = 1, n - 1 do
			local reach = math.max(
				route.halfWidth[i] + math.max(route.marginL[i], route.marginR[i]),
				route.halfWidth[i + 1] + math.max(route.marginL[i + 1], route.marginR[i + 1])
			) + self.lateralLimit + 8
			local x0 = math.floor((math.min(route.x[i], route.x[i + 1]) - reach) / CELL)
			local x1 = math.floor((math.max(route.x[i], route.x[i + 1]) + reach) / CELL)
			local z0 = math.floor((math.min(route.z[i], route.z[i + 1]) - reach) / CELL)
			local z1 = math.floor((math.max(route.z[i], route.z[i + 1]) + reach) / CELL)
			for cx = x0, x1 do
				for cz = z0, z1 do
					local key = cellKey(cx, cz)
					local lr = self.cellRoute[key]
					if not lr then
						lr = {}
						self.cellRoute[key] = lr
						self.cellSeg[key] = {}
					end
					table.insert(lr, ri)
					table.insert(self.cellSeg[key], i)
				end
			end
		end
	end
	return self
end

-- Closest corridor to (px, py, pz). Positions inside a corridor (horizontally)
-- and within 20 studs vertically all score 0 penalty; ties prefer the given
-- route (hysteresis at junctions), then the smaller horizontal distance.
function RouteGraph.Nearest(self: RouteGraph, px: number, py: number, pz: number, prefer: string?): Hit?
	local key = cellKey(math.floor(px / CELL), math.floor(pz / CELL))
	local lr = self.cellRoute[key]
	if not lr then
		return nil
	end
	local ls = self.cellSeg[key]
	local best: Hit? = nil
	local bestScore = math.huge
	for k = 1, #lr do
		local route = self.routes[lr[k]]
		local i = ls[k]
		local ax, az = route.x[i], route.z[i]
		local ex, ez = route.x[i + 1] - ax, route.z[i + 1] - az
		local len2 = ex * ex + ez * ez
		if len2 < 1e-9 then
			continue
		end
		local t = ((px - ax) * ex + (pz - az) * ez) / len2
		if t < 0 then
			t = 0
		elseif t > 1 then
			t = 1
		end
		local cx, cz = ax + ex * t, az + ez * t
		local len = math.sqrt(len2)
		local tx, tz = ex / len, ez / len
		local dx, dz = px - cx, pz - cz
		local lateral = dx * -tz + dz * tx -- right = (-tz, tx)
		local dist = math.sqrt(dx * dx + dz * dz)
		local hw = lerp(route.halfWidth[i], route.halfWidth[i + 1], t)
		local margin = if lateral >= 0
			then lerp(route.marginR[i], route.marginR[i + 1], t)
			else lerp(route.marginL[i], route.marginL[i + 1], t)
		local edge = dist - (hw + margin)
		local cy = lerp(route.y[i], route.y[i + 1], t)
		local dy = math.abs(py - cy)
		local score = math.max(edge, 0) + 0.35 * math.max(dy - 20, 0) + 0.001 * dist
		if prefer and route.id == prefer then
			score -= 2
		end
		if score < bestScore then
			bestScore = score
			local surf = if t < 0.5 then route.surface[i] else route.surface[i + 1]
			local sec = if t < 0.5 then route.section[i] else route.section[i + 1]
			best = {
				route = route.id,
				routeIndex = route.index,
				segment = i,
				t = t,
				s = lerp(route.s[i], route.s[i + 1], t),
				progress = lerp(route.progress[i], route.progress[i + 1], t),
				lateral = lateral,
				distance = dist,
				halfWidth = hw,
				margin = margin,
				edgeDistance = edge,
				x = cx,
				y = cy,
				z = cz,
				tx = tx,
				tz = tz,
				surface = surf,
				section = sec,
			}
		end
	end
	return best
end

-- Classify a position for out-of-bounds handling.
function RouteGraph.Classify(self: RouteGraph, px: number, py: number, pz: number, prefer: string?): (Status, Hit?)
	local hit = self:Nearest(px, py, pz, prefer)
	if not hit then
		return "far", nil
	end
	if hit.edgeDistance > self.lateralLimit then
		return "outside", hit
	end
	if py < hit.y - self.belowLimit then
		return "below", hit
	end
	if hit.surface == SURF_TUNNEL and py > hit.y + self.roofLimit and hit.edgeDistance < 0 then
		return "roof", hit
	end
	return "ok", hit
end

local function locate(route: Route, s: number): (number, number)
	-- binary search: segment i with route.s[i] <= s <= route.s[i + 1]
	local lo, hi = 1, route.n
	if s <= route.s[1] then
		return 1, 0
	end
	if s >= route.s[hi] then
		return hi - 1, 1
	end
	while hi - lo > 1 do
		local mid = (lo + hi) // 2
		if route.s[mid] <= s then
			lo = mid
		else
			hi = mid
		end
	end
	local span = route.s[lo + 1] - route.s[lo]
	return lo, if span > 1e-9 then (s - route.s[lo]) / span else 0
end

-- Centreline point and horizontal travel direction at station s (studs).
function RouteGraph.FrameAt(self: RouteGraph, routeId: string, s: number): (number, number, number, number, number)
	local route = self.byId[routeId]
	assert(route, "unknown route " .. tostring(routeId))
	local i, t = locate(route, s)
	local ex, ez = route.x[i + 1] - route.x[i], route.z[i + 1] - route.z[i]
	local len = math.sqrt(ex * ex + ez * ez)
	if len < 1e-9 then
		ex, ez, len = 0, -1, 1
	end
	return lerp(route.x[i], route.x[i + 1], t),
		lerp(route.y[i], route.y[i + 1], t),
		lerp(route.z[i], route.z[i + 1], t),
		ex / len,
		ez / len
end

-- Main-route progress (studs) at station s of a route.
function RouteGraph.ProgressAt(self: RouteGraph, routeId: string, s: number): number
	local route = self.byId[routeId]
	assert(route, "unknown route " .. tostring(routeId))
	local i, t = locate(route, s)
	return lerp(route.progress[i], route.progress[i + 1], t)
end

-- Respawn frame: `back` studs behind station s on the centreline, `up` studs
-- above it, facing downhill. Returns position + horizontal look direction.
function RouteGraph.RespawnFrame(
	self: RouteGraph,
	routeId: string,
	s: number,
	back: number,
	up: number
): (number, number, number, number, number)
	local x, y, z, tx, tz = self:FrameAt(routeId, math.max(s - back, 0))
	return x, y + up, z, tx, tz
end

function RouteGraph.GetRoute(self: RouteGraph, routeId: string): Route?
	return self.byId[routeId]
end

function RouteGraph.RouteIds(self: RouteGraph): { string }
	local ids = {}
	for _, r in self.routes do
		table.insert(ids, r.id)
	end
	return ids
end

return RouteGraph
