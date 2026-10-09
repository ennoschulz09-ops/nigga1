--!strict
-- Snowy Valley - builds the invisible collision world from CollisionData.
--
--   strips  : route riding surfaces. Each quad between two rows is split into
--             the triangles (A[c], B[c], B[c+1]) and (A[c], B[c+1], A[c+1]);
--             every triangle becomes two WedgeParts (right-triangle split).
--             The wedges are slabs extruded DOWN from the triangle, so their
--             top faces are exactly the riding surface.
--   patches : start platform, finish plaza and village ground (masked grids).
--   boxes   : boundary walls, bridge parapets, ice-cave walls / ceiling and
--             out-of-bounds catch floors.
--   kickers : WedgeParts matching the visual kicker ramps.
--
-- The visual meshes never collide; this geometry is what SlopeRaycaster and
-- the character physics touch. Every part carries SV_ attributes.

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("SnowyValleyShared")
local Config = require(Shared:WaitForChild("Config"))

local CollisionBuilder = {}

local PREFIX = Config.AttributePrefix

type BuildStats = { wedges: number, boxes: number, kickers: number, models: number }

local function newWedge(): WedgePart
	local w = Instance.new("WedgePart")
	w.Anchored = true
	w.CanCollide = true
	w.CanTouch = false
	w.CanQuery = true
	w.CastShadow = false
	w.Locked = true
	w.Material = Enum.Material.Snow
	w.Transparency = if Config.Collision.Debug then 0.6 else 1
	w.Color = Color3.fromRGB(255, 140, 40)
	w.TopSurface = Enum.SurfaceType.Smooth
	w.BottomSurface = Enum.SurfaceType.Smooth
	return w
end

-- Two wedges for triangle (a, b, c), slab of `thickness` below the surface.
-- Returns the number of wedges created (0 for degenerate triangles).
local function triangle(a: Vector3, b: Vector3, c: Vector3, thickness: number, parent: Instance, kind: string): number
	local ab, ac, bc = b - a, c - a, c - b
	local abd, acd, bcd = ab:Dot(ab), ac:Dot(ac), bc:Dot(bc)
	-- make bc the longest edge
	if abd > acd and abd > bcd then
		c, a = a, c
	elseif acd > bcd and acd > abd then
		a, b = b, a
	end
	ab, ac, bc = b - a, c - a, c - b
	local cross = ac:Cross(ab)
	if cross.Magnitude < 1e-6 then
		return 0
	end
	local right = cross.Unit
	local up = bc:Cross(right).Unit
	local back = bc.Unit
	local height = math.abs(ab:Dot(up))
	if height < 1e-4 then
		return 0
	end
	-- slab below the surface whichever way the triangle is wound
	local down = if right.Y > 0 then -right else right
	local shift = down * (thickness / 2)

	local w1 = newWedge()
	w1.Size = Vector3.new(thickness, height, math.abs(ab:Dot(back)))
	w1.CFrame = CFrame.fromMatrix((a + b) / 2 + shift, right, up, back)
	w1:SetAttribute(PREFIX .. "Kind", kind)
	w1.Parent = parent

	local w2 = newWedge()
	w2.Size = Vector3.new(thickness, height, math.abs(ac:Dot(back)))
	w2.CFrame = CFrame.fromMatrix((a + c) / 2 + shift, -right, up, -back)
	w2:SetAttribute(PREFIX .. "Kind", kind)
	w2.Parent = parent
	return 2
end

CollisionBuilder.Triangle = triangle

local function rowPoint(row: { number }, c: number): Vector3
	local k = (c - 1) * 3
	return Vector3.new(row[k + 1], row[k + 2], row[k + 3])
end

local function quatCFrame(p: { number }, q: { number }): CFrame
	return CFrame.new(p[1], p[2], p[3], q[1], q[2], q[3], q[4])
end

local function newModel(name: string, parent: Instance, streamingMode: string?): Model
	local m = Instance.new("Model")
	m.Name = name
	if streamingMode then
		local ok = pcall(function()
			(m :: any).ModelStreamingMode = (Enum.ModelStreamingMode :: any)[streamingMode]
		end)
		if not ok then
			warn("[SnowyValley] could not set ModelStreamingMode", streamingMode)
		end
	end
	m.Parent = parent
	return m
end

local function maybeYield(counter: { n: number }, every: number)
	counter.n += 1
	if counter.n % every == 0 then
		task.wait()
	end
end

-- Build everything under `root` (a Folder named "Collision").
type BuildOptions = { yieldEvery: number? }

function CollisionBuilder.Build(data: any, root: Instance, options: BuildOptions?): BuildStats
	local opts: BuildOptions = options or {}
	local yieldEvery = opts.yieldEvery or 1500
	local counter = { n = 0 }
	local thickness = Config.Collision.SurfaceThickness
	local mode = Config.Collision.SurfaceStreamingMode
	local stats: BuildStats = { wedges = 0, boxes = 0, kickers = 0, models = 0 }

	-- route surfaces, chunked by accumulated row length
	local surfaces = Instance.new("Folder")
	surfaces.Name = "Surfaces"
	surfaces.Parent = root
	local chunkLen = Config.Collision.ChunkLength
	local chunk: Model? = nil
	local acc = 0
	local chunkIndex: { [string]: number } = {}
	for _, strip in data.strips do
		local rows = strip.rows
		local nPts = #rows[1] // 3
		local kinds: { string } = strip.kinds
		for r = 1, #rows - 1 do
			local A, B = rows[r], rows[r + 1]
			local step = (rowPoint(A, 1) - rowPoint(B, 1)).Magnitude
			if chunk == nil or acc >= chunkLen or chunk:GetAttribute(PREFIX .. "Route") ~= strip.route then
				chunkIndex[strip.route] = (chunkIndex[strip.route] or 0) + 1
				chunk = newModel(string.format("%s_%03d", strip.route, chunkIndex[strip.route]), surfaces, mode)
				local cm = chunk :: Model
				cm:SetAttribute(PREFIX .. "Route", strip.route)
				stats.models += 1
				acc = 0
			end
			acc += step
			local parent = chunk :: Model
			for c = 1, nPts - 1 do
				local a0, b0 = rowPoint(A, c), rowPoint(B, c)
				local b1, a1 = rowPoint(B, c + 1), rowPoint(A, c + 1)
				local kind = kinds[c] or "Piste"
				stats.wedges += triangle(a0, b0, b1, thickness, parent, kind)
				stats.wedges += triangle(a0, b1, a1, thickness, parent, kind)
				maybeYield(counter, yieldEvery)
			end
		end
	end

	-- walkable ground patches
	local patches = newModel("Patches", root, mode)
	stats.models += 1
	for _, patch in data.patches do
		local nx, ny = patch.nx, patch.ny
		local pts: { number } = patch.points
		local function P(i: number, j: number): Vector3
			local k = ((j * nx) + i) * 3
			return Vector3.new(pts[k + 1], pts[k + 2], pts[k + 3])
		end
		local folder = Instance.new("Folder")
		folder.Name = patch.name
		folder.Parent = patches
		for j = 0, ny - 2 do
			for i = 0, nx - 2 do
				if patch.mask[j * (nx - 1) + i + 1] == 1 then
					local p00, p10, p01, p11 = P(i, j), P(i + 1, j), P(i, j + 1), P(i + 1, j + 1)
					stats.wedges += triangle(p00, p10, p11, thickness, folder, "Ground")
					stats.wedges += triangle(p00, p11, p01, thickness, folder, "Ground")
					maybeYield(counter, yieldEvery)
				end
			end
		end
	end

	-- boxes: walls, parapets, cave, catch floors
	local boxesModel = newModel("Boxes", root, mode)
	stats.models += 1
	local catchModel = newModel("CatchFloors", root, "Persistent")
	stats.models += 1
	for _, b in data.boxes do
		local part = Instance.new("Part")
		part.Name = b.kind
		part.Anchored = true
		part.CastShadow = false
		part.Locked = true
		part.Size = Vector3.new(b.size[1], b.size[2], b.size[3])
		part.CFrame = quatCFrame(b.position, b.rotation)
		part.Transparency = if Config.Collision.Debug then 0.7 else 1
		part.Color = Color3.fromRGB(60, 170, 255)
		part.TopSurface = Enum.SurfaceType.Smooth
		part.BottomSurface = Enum.SurfaceType.Smooth
		part:SetAttribute(PREFIX .. "Kind", b.kind)
		if b.kind == "CatchFloor" then
			part.CanCollide = true
			part.CanTouch = true
			part.CanQuery = false
			part.Parent = catchModel
		else
			-- walls are not ground: by default raycasts (SlopeRaycaster) skip them
			part.CanCollide = true
			part.CanTouch = false
			part.CanQuery = Config.Collision.WallsQueryable or b.kind == "CaveCeiling"
			part.Parent = boxesModel
		end
		stats.boxes += 1
		maybeYield(counter, yieldEvery)
	end

	-- kickers: one wedge each, sloped face up the travel direction
	local kickModel = newModel("Kickers", root, mode)
	stats.models += 1
	for i, k in data.kickers do
		local w = newWedge()
		w.Name = string.format("Kicker_%02d", i)
		w.Size = Vector3.new(k.size[1], k.size[2], k.size[3])
		w.CFrame = quatCFrame(k.position, k.rotation)
		w:SetAttribute(PREFIX .. "Kind", "Kicker")
		w.Parent = kickModel
		stats.kickers += 1
	end
	return stats
end

return CollisionBuilder
