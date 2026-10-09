--!strict
-- Snowy Valley - logic tests shared by the CLI runner (tests/run.luau) and the
-- Studio runner (ServerStorage.SnowyValleyServer.Tests.RunTests).
-- deps = { RouteGraph, CheckpointTracker, RouteData, Checkpoints }

type T = {
	check: (cond: boolean, msg: string) -> (),
	info: (msg: string) -> (),
}

local function samplesOf(route: any): { { number } }
	return route.samples
end

local function findRoute(data: any, id: string): any
	for _, r in data.routes do
		if r.id == id then
			return r
		end
	end
	error("route " .. id)
end

-- positions (x, y + lift, z) along a polyline of samples, densified to <= 6 studs
local function ridePath(samples: { { number } }, lift: number): { { number } }
	local out = {}
	for i = 1, #samples - 1 do
		local a, b = samples[i], samples[i + 1]
		local dx, dy, dz = b[1] - a[1], b[2] - a[2], b[3] - a[3]
		local len = math.sqrt(dx * dx + dy * dy + dz * dz)
		local n = math.max(1, math.ceil(len / 6))
		for k = 0, n - 1 do
			local t = k / n
			table.insert(out, { a[1] + dx * t, a[2] + dy * t + lift, a[3] + dz * t })
		end
	end
	local last = samples[#samples]
	table.insert(out, { last[1], last[2] + lift, last[3] })
	return out
end

-- MAIN up to the branch, the alternative, MAIN after the merge
local function altPath(data: any, altId: string): { { number } }
	local main = findRoute(data, "MAIN")
	local alt = findRoute(data, altId)
	local before, after = {}, {}
	for _, s in samplesOf(main) do
		if s[4] < alt.branch_main_m then
			table.insert(before, s)
		elseif s[4] > alt.merge_main_m then
			table.insert(after, s)
		end
	end
	local seq = {}
	for _, s in before do
		table.insert(seq, s)
	end
	for _, s in samplesOf(alt) do
		table.insert(seq, s)
	end
	for _, s in after do
		table.insert(seq, s)
	end
	return seq
end

local function ride(deps: any, path: { { number } }, key: string): (any, { any })
	local tracker = deps.CheckpointTracker.new(deps.Checkpoints, {})
	tracker:Begin(key, 0)
	local events = {}
	local now = 0
	for _, p in path do
		now += 0.05
		for _, ev in tracker:Sample(key, p[1], p[2], p[3], now) do
			table.insert(events, ev)
		end
	end
	return tracker, events
end

local function groupsPassed(events: { any }): ({ number }, number)
	local groups, skips = {}, 0
	for _, ev in events do
		if ev.kind == "pass" or ev.kind == "finish" then
			table.insert(groups, ev.group)
		elseif ev.kind == "skip" then
			skips += 1
		end
	end
	return groups, skips
end

local function inOrder(groups: { number }, n: number): boolean
	if #groups ~= n then
		return false
	end
	for i = 1, n do
		if groups[i] ~= i then
			return false
		end
	end
	return true
end

return function(t: T, deps: any)
	local RouteData, Checkpoints = deps.RouteData, deps.Checkpoints
	local G = deps.RouteGraph.new(RouteData, { lateralLimit = 30, belowLimit = 60, roofLimit = 55 })
	local K = RouteData.units.studs_per_meter
	local nGroups = Checkpoints.group_count

	-- RouteGraph ------------------------------------------------------------
	for _, r in RouteData.routes do
		local bad, worstEdge = 0, -math.huge
		for i, s in r.samples do
			if i % 3 ~= 1 then
				continue
			end
			local status, hit = G:Classify(s[1], s[2] + 3, s[3], r.id)
			if status ~= "ok" or not hit or hit.edgeDistance > 0 then
				bad += 1
			end
			if hit then
				worstEdge = math.max(worstEdge, hit.edgeDistance)
			end
		end
		t.check(bad == 0, string.format("RouteGraph: every %s centreline sample is in bounds (bad %d)", r.id, bad))
	end
	do
		local main = findRoute(RouteData, "MAIN")
		local mono = true
		local samples = main.samples
		for i = 2, #samples do
			if samples[i][5] < samples[i - 1][5] then
				mono = false
			end
		end
		t.check(mono, "RouteGraph: MAIN progress increases monotonically")
		-- lateral escape: walk sideways from mid-course until "outside"
		local s = samples[math.floor(#samples / 2)]
		local nx, nz = samples[math.floor(#samples / 2) + 1][1] - s[1], samples[math.floor(#samples / 2) + 1][3] - s[3]
		local len = math.sqrt(nx * nx + nz * nz)
		local rx, rz = -nz / len, nx / len
		local half = s[6] + s[8]
		local st1 = G:Classify(s[1] + rx * (half - 2), s[2] + 2, s[3] + rz * (half - 2), "MAIN")
		local st2 = G:Classify(s[1] + rx * (half + 45), s[2] + 2, s[3] + rz * (half + 45), "MAIN")
		t.check(st1 == "ok", "RouteGraph: inside the right margin is in bounds")
		t.check(st2 == "outside" or st2 == "far", "RouteGraph: 45 studs beyond the corridor is out of bounds (" .. st2 .. ")")
		local st3 = G:Classify(s[1], s[2] - 90, s[3], "MAIN")
		t.check(st3 == "below", "RouteGraph: 90 studs below the surface is 'below' (" .. st3 .. ")")
		-- a sample in the middle of the ice-cave tunnel (portals are ambiguous)
		local tunnel = {}
		for _, smp in samples do
			if smp[9] == 2 then
				table.insert(tunnel, smp)
			end
		end
		local tunnelSample = tunnel[math.max(1, #tunnel // 2)]
		t.check(tunnelSample ~= nil, "RouteData: MAIN contains the ice-cave tunnel")
		if tunnelSample then
			local st4 = G:Classify(tunnelSample[1], tunnelSample[2] + 70, tunnelSample[3], "MAIN")
			t.check(st4 == "roof", "RouteGraph: 70 studs above the tunnel floor is 'roof' (" .. st4 .. ")")
		end
		local x, y, z = G:FrameAt("MAIN", 0)
		t.check(math.abs(x - samples[1][1]) < 0.01 and math.abs(z - samples[1][3]) < 0.01, "RouteGraph: FrameAt(0) is the start")
		local rx2, ry2, rz2 = G:RespawnFrame("MAIN", 1000, 40, 5)
		local _, cy = G:FrameAt("MAIN", 960)
		t.check(math.abs(ry2 - (cy + 5)) < 0.01, "RouteGraph: respawn 40 studs back, 5 studs above the centreline")
		local L = main.race_length_m * K
		t.info(string.format("MAIN race length %.0f studs (%.1f m), %d samples", L, main.race_length_m, #samples))
		local _ = rx2 + rz2 + y
	end

	-- CheckpointTracker -------------------------------------------------------
	do
		local main = findRoute(RouteData, "MAIN")
		local _, events = ride(deps, ridePath(main.samples, 3), "main")
		local groups, skips = groupsPassed(events)
		t.check(inOrder(groups, nGroups) and skips == 0,
			string.format("Tracker: riding MAIN passes groups 1..%d in order (%d passed, %d skips)", nGroups, #groups, skips))
		t.check(events[#events] and events[#events].kind == "finish", "Tracker: the last event on MAIN is the finish")
	end
	for _, r in RouteData.routes do
		if r.kind ~= "alt" then
			continue
		end
		local _, events = ride(deps, ridePath(altPath(RouteData, r.id), 3), r.id)
		local groups, skips = groupsPassed(events)
		local viaAlt = 0
		for _, ev in events do
			if ev.route == r.id then
				viaAlt += 1
			end
		end
		t.check(inOrder(groups, nGroups) and skips == 0,
			string.format("Tracker: MAIN -> %s -> MAIN finishes with all %d groups (passed %d, skips %d, %d on %s) - no false DNF",
				r.id, nGroups, #groups, skips, viaAlt, r.id))
		t.check(viaAlt > 0, "Tracker: " .. r.id .. " gates are equivalent gates (credited on " .. r.id .. ")")
	end
	do
		-- shortcut: ride MAIN to group 5, then appear just before a group-9 gate
		local main = findRoute(RouteData, "MAIN")
		local path = ridePath(main.samples, 3)
		local tracker = deps.CheckpointTracker.new(Checkpoints, {})
		tracker:Begin("cheat", 0)
		local now = 0
		local target = nil
		for _, grp in Checkpoints.groups do
			if grp.group == 9 then
				target = grp.gates[1]
			end
		end
		local nineStation = target.station_m * K
		local events = {}
		for _, p in path do
			now += 0.05
			for _, ev in tracker:Sample("cheat", p[1], p[2], p[3], now) do
				table.insert(events, ev)
			end
			if tracker:NextGroup("cheat") == 6 then
				break
			end
		end
		-- jump (no ResetSample) to 30 studs before gate 9 and ride through it
		local before = nil
		for _, s in main.samples do
			if s[4] * K >= nineStation - 30 and not before then
				before = s
			end
		end
		local after = nil
		for _, s in main.samples do
			if s[4] * K >= nineStation + 30 and not after then
				after = s
			end
		end
		tracker:ResetSample("cheat")
		for _, s in { before, after } do
			now += 0.05
			for _, ev in tracker:Sample("cheat", s[1], s[2] + 3, s[3], now) do
				table.insert(events, ev)
			end
		end
		local _, skips = groupsPassed(events)
		t.check(skips >= 1 and tracker:NextGroup("cheat") == 6,
			string.format("Tracker: shortcut to group 9 is rejected (skips %d, next expected %s)", skips, tostring(tracker:NextGroup("cheat"))))
		local ev = tracker:RouteSample("cheat", "MAIN", nineStation - 20, nineStation + 20, now)
		t.check(ev == nil, "Tracker: route progress past a later group's station does not pass it")
	end
	do
		-- jump over a gate: positions 60 studs above the course -> sweep misses,
		-- continuous route progress passes the gate
		local main = findRoute(RouteData, "MAIN")
		local tracker = deps.CheckpointTracker.new(Checkpoints, {})
		tracker:Begin("air", 0)
		local cp2 = Checkpoints.groups[2].gates[1]
		local st = cp2.station_m * K
		local passedBySweep = false
		local prevS = nil
		for _, s in main.samples do
			local sS = s[4] * K
			if sS > st + 200 then
				break
			end
			for _, ev in tracker:Sample("air", s[1], s[2] + 60, s[3], 1) do
				if ev.group == 2 then
					passedBySweep = true
				end
			end
			if prevS then
				tracker:RouteSample("air", "MAIN", prevS, sS, 1)
			end
			prevS = sS
		end
		t.check(not passedBySweep and (tracker:NextGroup("air") or 0) >= 3,
			"Tracker: a jump high over gate 2 still passes it via continuous route progress")
		-- hairpin hop: a station jump larger than maxRouteStep never passes
		local tr2 = deps.CheckpointTracker.new(Checkpoints, {})
		tr2:Begin("hop", 0)
		local cp1 = Checkpoints.groups[1].gates[1].station_m * K
		local r1 = tr2:RouteSample("hop", "MAIN", cp1 - 200, cp1 + 200, 1)
		t.check(r1 == nil, "Tracker: a 400-stud station jump (hairpin hop) passes nothing")
	end
	do
		-- touch API: order enforced
		local tr = deps.CheckpointTracker.new(Checkpoints, {})
		tr:Begin("touch", 0)
		local g1 = Checkpoints.groups[1].gates[1].id
		local g3 = Checkpoints.groups[3].gates[1].id
		local a = tr:Touch("touch", g3, 1)
		local b = tr:Touch("touch", g1, 2)
		t.check(a ~= nil and a.kind == "skip" and b ~= nil and b.kind == "pass", "Tracker: Touch() rejects out-of-order gates and accepts the expected one")
	end
end
