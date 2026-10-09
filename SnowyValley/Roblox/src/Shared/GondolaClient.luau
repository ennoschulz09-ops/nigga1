--!strict
-- Snowy Valley - client-side gondola animation.
--
-- The server builds the cables only; every client animates its own cabins
-- along the closed loop paths from GondolaData at constant speed (no
-- network traffic, no physics). Cabins are animated only while the Snowy
-- Valley world is loaded and the local camera is near a line.
-- Passenger transport is NOT implemented (cabins are scenery).

local RunService = game:GetService("RunService")

local Shared = script.Parent
local Config = require(Shared:WaitForChild("Config"))

local GondolaClient = {}

type Line = {
	id: string,
	n: number,
	px: { number },
	py: { number },
	pz: { number },
	cum: { number },
	length: number,
	speed: number,
	cabins: { { model: Model, offset: number, parts: { BasePart }, rel: { CFrame } } },
	minX: number,
	maxX: number,
	minZ: number,
	maxZ: number,
}

local lines: { Line } = {}
local folder: Folder? = nil
local clock = 0
local active = false

local function buildLine(def: any): Line
	local pts: { number } = def.path
	local n = #pts // 3
	local line: Line = {
		id = def.id,
		n = n,
		px = table.create(n),
		py = table.create(n),
		pz = table.create(n),
		cum = table.create(n + 1),
		length = 0,
		speed = def.speed_studs,
		cabins = {},
		minX = math.huge,
		maxX = -math.huge,
		minZ = math.huge,
		maxZ = -math.huge,
	}
	for i = 1, n do
		line.px[i], line.py[i], line.pz[i] = pts[(i - 1) * 3 + 1], pts[(i - 1) * 3 + 2], pts[(i - 1) * 3 + 3]
		line.minX = math.min(line.minX, line.px[i])
		line.maxX = math.max(line.maxX, line.px[i])
		line.minZ = math.min(line.minZ, line.pz[i])
		line.maxZ = math.max(line.maxZ, line.pz[i])
	end
	line.cum[1] = 0
	for i = 1, n do
		local j = i % n + 1
		local dx, dy, dz = line.px[j] - line.px[i], line.py[j] - line.py[i], line.pz[j] - line.pz[i]
		line.cum[i + 1] = line.cum[i] + math.sqrt(dx * dx + dy * dy + dz * dz)
	end
	line.length = line.cum[n + 1]
	return line
end

-- Position + horizontal direction at loop distance d.
local function sample(line: Line, d: number): (Vector3, Vector3)
	d = d % line.length
	local lo, hi = 1, line.n + 1
	while hi - lo > 1 do
		local mid = (lo + hi) // 2
		if line.cum[mid] <= d then
			lo = mid
		else
			hi = mid
		end
	end
	local i = lo
	local j = i % line.n + 1
	local seg = line.cum[i + 1] - line.cum[i]
	local t = if seg > 1e-6 then (d - line.cum[i]) / seg else 0
	local p = Vector3.new(
		line.px[i] + (line.px[j] - line.px[i]) * t,
		line.py[i] + (line.py[j] - line.py[i]) * t,
		line.pz[i] + (line.pz[j] - line.pz[i]) * t
	)
	local dir = Vector3.new(line.px[j] - line.px[i], 0, line.pz[j] - line.pz[i])
	if dir.Magnitude < 1e-6 then
		dir = Vector3.new(0, 0, -1)
	end
	return p, dir.Unit
end

local function spawnCabins(template: Model, def: any, line: Line, budget: number): number
	local count = math.min(math.floor(line.length / def.spacing_studs), budget)
	for k = 0, count - 1 do
		local m = template:Clone()
		local pivot = m:GetPivot()
		local parts, rel = {}, {}
		for _, d in m:GetDescendants() do
			if d:IsA("BasePart") then
				d.Anchored = true
				d.CanCollide = false
				d.CanQuery = false
				d.CanTouch = false
				table.insert(parts, d)
				table.insert(rel, pivot:ToObjectSpace(d.CFrame))
			end
		end
		m.Parent = folder
		table.insert(line.cabins, { model = m, offset = k * line.length / count, parts = parts, rel = rel })
	end
	return count
end

local function nearAnyLine(pos: Vector3): boolean
	local r = Config.Gondola.ActivationDistance
	for _, line in lines do
		if pos.X > line.minX - r and pos.X < line.maxX + r and pos.Z > line.minZ - r and pos.Z < line.maxZ + r then
			return true
		end
	end
	return false
end

local function step(dt: number)
	clock += dt
	local parts: { BasePart } = {}
	local cfs: { CFrame } = {}
	for _, line in lines do
		for _, cab in line.cabins do
			local p, dir = sample(line, cab.offset + clock * line.speed)
			local cf = CFrame.lookAt(p, p + dir)
			for i, part in cab.parts do
				table.insert(parts, part)
				table.insert(cfs, cf * cab.rel[i])
			end
		end
	end
	workspace:BulkMoveTo(parts, cfs, Enum.BulkMoveMode.FireCFrameChanged)
end

local function setActive(on: boolean)
	if on == active then
		return
	end
	active = on
	if folder then
		folder.Parent = if on then workspace else nil
	end
end

function GondolaClient.Start()
	local data = require(Shared:WaitForChild("Data"):WaitForChild("GondolaData")) :: any
	local assets = Shared:WaitForChild("Assets", 30)
	local template = assets and assets:WaitForChild("GondolaCabin", 30)
	if not template or not template:IsA("Model") then
		warn("[SnowyValley] GondolaCabin template missing - run Importer.Build() (cabins disabled)")
		return
	end
	local f = Instance.new("Folder")
	f.Name = "SnowyValley_GondolaCabins"
	folder = f
	local budget = Config.Gondola.MaxCabins
	for _, def in data.lines do
		local line = buildLine(def)
		budget -= spawnCabins(template, def, line, budget)
		table.insert(lines, line)
	end
	-- activate only while the world is loaded and the camera is near a line
	task.spawn(function()
		while true do
			local cam = workspace.CurrentCamera
			local loaded = workspace:FindFirstChild(Config.WorldId) ~= nil
			setActive(loaded and cam ~= nil and nearAnyLine(cam.CFrame.Position))
			task.wait(1)
		end
	end)
	RunService.Heartbeat:Connect(function(dt)
		if active then
			step(dt)
		end
	end)
end

return GondolaClient
