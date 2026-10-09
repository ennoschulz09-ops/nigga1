--!strict
-- Snowy Valley - edit-time world builder.
--
-- 1. Import the FBX files from SnowyValley/Export with the Studio 3D Importer
--    and move the resulting models into ServerStorage.SnowyValleyImport.
-- 2. Run in the command bar:
--        require(game.ServerStorage.SnowyValleyServer.Importer).Build()
--
-- Builds ServerStorage.SnowyValleyWorld (a Model) from the generated
-- metadata. Every mesh is positioned from the manifest (bounding-box centre +
-- orientation), never from where the importer dropped it, and every mesh's
-- imported Size is verified against the manifest: a uniform scale error is
-- corrected, swapped axes are reported (wrong import settings) and that mesh
-- is skipped. Collision, checkpoints, spawns, lights, signs and gondola
-- cables are created from data. Nothing outside ServerStorage is modified.

local ServerStorage = game:GetService("ServerStorage")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("SnowyValleyShared")
local Config = require(Shared:WaitForChild("Config"))
local Server = script.Parent
local CollisionBuilder = require(Server:WaitForChild("CollisionBuilder"))

local PREFIX = Config.AttributePrefix

local Importer = {}

export type BuildOptions = {
	importRoot: Instance?, -- default ServerStorage.SnowyValleyImport
	parent: Instance?, -- default ServerStorage
	visuals: boolean?, -- default true
	collision: boolean?, -- default true
	yieldEvery: number?, -- task.wait() every N created parts (keeps Studio responsive)
}

export type Report = {
	ok: boolean,
	meshesFound: number,
	meshesExpected: number,
	missing: { string },
	scaleFixed: { string },
	axisErrors: { string },
	rotated: { string },
	probesChecked: number,
	sizeMismatch: { string },
	duplicates: { string },
	uniquePlaced: number,
	instancesPlaced: number,
	partsPlaced: number,
	collision: any,
	gates: number,
	spawns: number,
	lights: number,
	signs: number,
	cableSegments: number,
	seconds: number,
}

local function vec(t: { number }): Vector3
	return Vector3.new(t[1], t[2], t[3])
end

local function quatCFrame(p: { number }, q: { number }): CFrame
	return CFrame.new(p[1], p[2], p[3], q[1], q[2], q[3], q[4])
end

local function setPluginProperty(part: Instance, prop: string, value: any)
	-- RenderFidelity / CollisionFidelity can only be set with plugin security
	-- (command bar); ignore failures elsewhere.
	pcall(function()
		(part :: any)[prop] = value
	end)
end

-- Compare an imported mesh size with the manifest size.
-- Returns "ok" | "scale" | "axes" | "mismatch".
local function classifySize(actual: Vector3, expected: Vector3, tol: number): string
	local a = { actual.X, actual.Y, actual.Z }
	local e = { expected.X, expected.Y, expected.Z }
	local okAll = true
	for i = 1, 3 do
		if math.abs(a[i] - e[i]) > math.max(tol * e[i], 0.05) then
			okAll = false
		end
	end
	if okAll then
		return "ok"
	end
	-- uniform scale: ratios of the significant axes agree
	local ratios = {}
	for i = 1, 3 do
		if e[i] > 1 then
			table.insert(ratios, a[i] / e[i])
		end
	end
	if #ratios > 0 then
		local r0 = ratios[1]
		local uniform = r0 > 0
		for _, r in ratios do
			if math.abs(r - r0) > tol * r0 then
				uniform = false
			end
		end
		if uniform then
			return "scale"
		end
	end
	-- same extents in another axis order -> rotated on import
	local sa, se = table.clone(a), table.clone(e)
	table.sort(sa)
	table.sort(se)
	local perm = true
	for i = 1, 3 do
		if math.abs(sa[i] - se[i]) > math.max(tol * se[i], 0.05) then
			perm = false
		end
	end
	return if perm then "axes" else "mismatch"
end

-- Orientation probe: the manifest stores, per mesh, the vertex maximising
-- x + 2.13 y + 3.71 z (relative to the bounding-box centre, studs). Reading
-- the imported mesh with EditableMesh and finding the same landmark detects
-- meshes the importer rotated or mirrored (sizes alone cannot show a 180
-- degree turn). Returns "ok" | "rotated" | "skipped".
local AssetService = game:GetService("AssetService")

local function probeOrientation(mp: MeshPart, probe: { number }?, size: Vector3): string
	if not probe then
		return "skipped"
	end
	local ok, result = pcall(function(): any
		local em = (AssetService :: any):CreateEditableMeshAsync((mp :: any).MeshContent)
		local best, bestP = -math.huge, Vector3.zero
		local mn = Vector3.new(math.huge, math.huge, math.huge)
		local mx = -mn
		for _, vid in em:GetVertices() do
			local p: Vector3 = em:GetPosition(vid)
			mn = mn:Min(p)
			mx = mx:Max(p)
			local v = p.X + 2.13 * p.Y + 3.71 * p.Z
			if v > best then
				best, bestP = v, p
			end
		end
		em:Destroy()
		return { mn, mx, bestP }
	end)
	if not ok or type(result) ~= "table" then
		return "skipped"
	end
	local mn: Vector3, mx: Vector3, bestP: Vector3 = result[1], result[2], result[3]
	local ext = mx - mn
	local function ratio(e: number, want: number): number
		return if e > 1e-6 then want / e else 0
	end
	local scale = Vector3.new(ratio(ext.X, size.X), ratio(ext.Y, size.Y), ratio(ext.Z, size.Z))
	local q = (bestP - (mn + mx) / 2) * scale
	local err = (q - Vector3.new(probe[1], probe[2], probe[3])).Magnitude
	return if err <= 0.05 * math.max(size.X, size.Y, size.Z) + 0.25 then "ok" else "rotated"
end

local function applyLook(part: BasePart, look: any)
	local hasTexture = false
	if part:IsA("MeshPart") then
		hasTexture = (part :: MeshPart).TextureID ~= "" or part:FindFirstChildOfClass("SurfaceAppearance") ~= nil
	end
	local ok, mat = pcall(function()
		return (Enum.Material :: any)[look.Material]
	end)
	if ok and mat then
		part.Material = mat
	end
	if not hasTexture then
		part.Color = Color3.fromRGB(look.Color[1], look.Color[2], look.Color[3])
	end
	if look.Reflectance then
		part.Reflectance = look.Reflectance
	end
	if look.Transparency then
		part.Transparency = look.Transparency
	end
end

local function makeVisual(part: BasePart, castShadow: boolean)
	part.Anchored = true
	part.CanCollide = false
	part.CanTouch = false
	part.CanQuery = false -- raycasts (SlopeRaycaster) only see collision geometry
	part.CastShadow = castShadow
	part.Locked = true
	setPluginProperty(part, "CollisionFidelity", Enum.CollisionFidelity.Box)
end

local function folder(name: string, parent: Instance): Folder
	local f = Instance.new("Folder")
	f.Name = name
	f.Parent = parent
	return f
end

local function model(name: string, parent: Instance): Model
	local m = Instance.new("Model")
	m.Name = name
	m.Parent = parent
	return m
end

-- Collect imported MeshParts by name.
local function collectMeshes(root: Instance, report: Report): { [string]: MeshPart }
	local meshes: { [string]: MeshPart } = {}
	for _, d in root:GetDescendants() do
		if d:IsA("MeshPart") then
			if meshes[d.Name] then
				table.insert(report.duplicates, d.Name)
			else
				meshes[d.Name] = d
			end
		end
	end
	return meshes
end

local SHADOWLESS = { Pistes = true, Environment = true, IceCave = true }

function Importer.Build(options: BuildOptions?): Report
	local t0 = os.clock()
	local opts: BuildOptions = options or {}
	local Manifest = require(Server:WaitForChild("Data"):WaitForChild("AssetManifest")) :: any
	local CollisionData = require(Server.Data:WaitForChild("CollisionData")) :: any
	local Checkpoints = require(Shared:WaitForChild("Data"):WaitForChild("Checkpoints")) :: any
	local GondolaData = require(Shared.Data:WaitForChild("GondolaData")) :: any

	local report: Report = {
		ok = false,
		meshesFound = 0,
		meshesExpected = 0,
		missing = {},
		scaleFixed = {},
		axisErrors = {},
		rotated = {},
		probesChecked = 0,
		sizeMismatch = {},
		duplicates = {},
		uniquePlaced = 0,
		instancesPlaced = 0,
		partsPlaced = 0,
		collision = nil,
		gates = 0,
		spawns = 0,
		lights = 0,
		signs = 0,
		cableSegments = 0,
		seconds = 0,
	}
	local yieldEvery = opts.yieldEvery or 1500
	local created = 0
	local function tick()
		created += 1
		if created % yieldEvery == 0 then
			task.wait()
		end
	end

	local parent = opts.parent or ServerStorage
	local old = parent:FindFirstChild(Config.BuiltWorldName)
	if old then
		old:Destroy()
	end
	local world = Instance.new("Model")
	world.Name = Config.BuiltWorldName
	world:SetAttribute(PREFIX .. "WorldId", Config.WorldId)
	world:SetAttribute(PREFIX .. "GeneratorVersion", Manifest.version)

	-- 1) visual meshes ---------------------------------------------------
	if opts.visuals ~= false then
		local importRoot = opts.importRoot or ServerStorage:FindFirstChild(Config.ImportFolderName)
		if not importRoot then
			error(
				string.format(
					"[SnowyValley] ServerStorage.%s not found - import the FBX files first (see SnowyValleySetup.md)",
					Config.ImportFolderName
				)
			)
		end
		local meshes = collectMeshes(importRoot :: Instance, report)
		local tol = Config.SizeTolerance
		-- verdict per mesh name: false = unusable, number = scale fix needed (1 = ok)
		local verdict: { [string]: boolean } = {}
		local probedFiles: { [string]: string } = {}
		local function check(name: string, expected: Vector3, probe: { number }?, file: string?): boolean
			local v = verdict[name]
			if v ~= nil then
				return v
			end
			report.meshesExpected += 1
			local src = meshes[name]
			if not src then
				table.insert(report.missing, name)
				verdict[name] = false
				return false
			end
			report.meshesFound += 1
			local cls = classifySize(src.Size, expected, tol)
			if cls == "scale" then
				table.insert(report.scaleFixed, name)
			elseif cls == "axes" then
				table.insert(report.axisErrors, name)
				verdict[name] = false
				return false
			elseif cls == "mismatch" then
				table.insert(report.sizeMismatch, string.format("%s (got %s, expected %s)", name, tostring(src.Size), tostring(expected)))
				verdict[name] = false
				return false
			end
			-- one orientation probe per FBX file (import settings are per file)
			if file and probedFiles[file] == nil then
				local res = probeOrientation(src, probe, expected)
				probedFiles[file] = res
				if res ~= "skipped" then
					report.probesChecked += 1
				end
				if res == "rotated" then
					table.insert(report.rotated, file .. " (" .. name .. ")")
				end
			end
			verdict[name] = true
			return true
		end

		local visual = folder("Visual", world)
		local groups: { [string]: Model } = {}
		local function groupModel(name: string): Model
			local existing = groups[name]
			if existing then
				return existing
			end
			local m = model(name, visual)
			groups[name] = m
			if name == "Backdrop" then
				-- the far mountain ring stays visible everywhere
				setPluginProperty(m, "ModelStreamingMode", Enum.ModelStreamingMode.Persistent)
			elseif string.sub(name, 1, 8) == "Terrain_" or string.sub(name, 1, 7) == "Canopy_" then
				-- one model per terrain / canopy chunk: shows a low-detail
				-- imposter while streamed out (StreamingEnabled)
				setPluginProperty(m, "LevelOfDetail", Enum.ModelLevelOfDetail.StreamingMesh)
			end
			return m
		end
		-- terrain + canopy chunks get their own models (SV_TER_03_05_Snow -> Terrain_03_05)
		local function uniqueGroup(u: any): string
			local i, j = string.match(u.mesh, "^SV_TER_(%d+)_(%d+)")
			if i and j then
				return "Terrain_" .. i .. "_" .. j
			end
			if u.category == "ForestCanopy" then
				return "Canopy_" .. u.mesh
			end
			return u.group
		end

		-- unique meshes: terrain, pistes, canopy, bridge, ice cave, lakes ...
		for _, u in Manifest.unique do
			local size = vec(u.size)
			if not check(u.mesh, size, u.probe, u.file) then
				continue
			end
			local p = (meshes[u.mesh] :: MeshPart):Clone()
			p.Size = size
			p.CFrame = CFrame.new(vec(u.position))
			makeVisual(p, not SHADOWLESS[u.category])
			applyLook(p, u.roblox)
			if u.category == "TerrainFar" then
				setPluginProperty(p, "RenderFidelity", Enum.RenderFidelity.Performance)
			end
			p:SetAttribute(PREFIX .. "Category", u.category)
			p.Parent = groupModel(uniqueGroup(u))
			report.uniquePlaced += 1
			tick()
		end

		-- instanced assets: trees, rocks, buildings, props, stations ...
		local cellSize = 2048
		for _, inst in Manifest.instances do
			local assetName = Manifest.assets[(inst[1] :: number) + 1]
			local tpl = Manifest.templates[assetName]
			if not tpl then
				continue
			end
			local cf = CFrame.new(inst[2], inst[3], inst[4], inst[5], inst[6], inst[7], inst[8])
			local scale: number = inst[9]
			local collide: string = inst[10]
			local group: string = inst[11]
			local cx = math.floor((inst[2] :: number) / cellSize)
			local cz = math.floor((inst[4] :: number) / cellSize)
			local holder = groupModel(group .. "_" .. cx .. "_" .. cz)
			local placedAny = false
			for _, part in tpl.parts do
				local size = vec(part.size)
				if not check(part.mesh, size, part.probe, tpl.file) then
					continue
				end
				local p = (meshes[part.mesh] :: MeshPart):Clone()
				p.Size = size * scale
				p.CFrame = cf * CFrame.new(vec(part.offset) * scale)
				makeVisual(p, true)
				applyLook(p, part.roblox)
				if collide == "Box" or collide == "Hull" then
					p.CanCollide = true
					p.CanQuery = true
					setPluginProperty(
						p,
						"CollisionFidelity",
						if collide == "Box" then Enum.CollisionFidelity.Box else Enum.CollisionFidelity.Hull
					)
				end
				p:SetAttribute(PREFIX .. "Asset", assetName)
				p.Parent = holder
				report.partsPlaced += 1
				placedAny = true
				tick()
			end
			if placedAny then
				report.instancesPlaced += 1
			end
		end

		-- gondola cabin template for the client animation
		local cabinTpl = Manifest.templates.Cabin
		if cabinTpl then
			local assets = Shared:FindFirstChild("Assets") or folder("Assets", Shared)
			local oldCabin = (assets :: Instance):FindFirstChild("GondolaCabin")
			if oldCabin then
				oldCabin:Destroy()
			end
			local cabin = model("GondolaCabin", assets :: Instance)
			local grip = Instance.new("Part")
			grip.Name = "Grip"
			grip.Size = Vector3.new(0.4, 0.4, 0.4)
			grip.Transparency = 1
			grip.CFrame = CFrame.new()
			makeVisual(grip, false)
			grip.Parent = cabin
			cabin.PrimaryPart = grip
			for _, part in cabinTpl.parts do
				if check(part.mesh, vec(part.size), part.probe, cabinTpl.file) then
					local p = (meshes[part.mesh] :: MeshPart):Clone()
					p.Size = vec(part.size)
					p.CFrame = CFrame.new(vec(part.offset))
					makeVisual(p, true)
					applyLook(p, part.roblox)
					p.Parent = cabin
				end
			end
		end
	end

	-- 2) collision -------------------------------------------------------
	if opts.collision ~= false then
		local col = folder("Collision", world)
		report.collision = CollisionBuilder.Build(CollisionData, col, { yieldEvery = yieldEvery })
	end

	-- 3) gameplay: checkpoints, spawns, boosts ---------------------------
	local gameplay = folder("Gameplay", world)
	local cps = folder("Checkpoints", gameplay)
	for _, grp in Checkpoints.groups do
		for _, g in grp.gates do
			local p = Instance.new("Part")
			p.Name = g.id
			p.Size = vec(g.size)
			p.CFrame = quatCFrame(g.position, g.rotation)
			p.Anchored = true
			p.CanCollide = false
			p.CanQuery = false
			p.CanTouch = true
			p.Transparency = 1
			p.CastShadow = false
			p.Locked = true
			p:SetAttribute(PREFIX .. "Group", g.group)
			p:SetAttribute(PREFIX .. "GateId", g.id)
			p:SetAttribute(PREFIX .. "Route", g.route)
			p:SetAttribute(PREFIX .. "Section", g.section)
			p:SetAttribute(PREFIX .. "ProgressStuds", g.progress_studs)
			p:SetAttribute(PREFIX .. "IsStart", g.is_start)
			p:SetAttribute(PREFIX .. "IsFinish", g.is_finish)
			-- generic names for attribute-based checkpoint systems
			p:SetAttribute("CheckpointIndex", g.group)
			p:SetAttribute("IsFinish", g.is_finish)
			p.Parent = cps
			report.gates += 1
		end
	end
	local spawns = folder("Spawns", gameplay)
	for i, s in Checkpoints.spawns do
		local p = Instance.new("Part")
		p.Name = string.format("Spawn%02d", i)
		p.Size = Vector3.new(4, 1, 4)
		p.CFrame = quatCFrame(s.position, s.rotation)
		p.Anchored = true
		p.CanCollide = false
		p.CanQuery = false
		p.CanTouch = false
		p.Transparency = 1
		p.Locked = true
		p:SetAttribute(PREFIX .. "SpawnIndex", i)
		p.Parent = spawns
		report.spawns += 1
	end
	local boosts = folder("Boosts", gameplay)
	for _, b in Checkpoints.boosts do
		local p = Instance.new("Part")
		p.Name = b.id
		p.Size = vec(b.size)
		p.CFrame = quatCFrame(b.position, b.rotation)
		p.Anchored = true
		p.CanCollide = false
		p.CanQuery = false
		p.CanTouch = true
		p.Transparency = 1
		p.Locked = true
		p:SetAttribute(PREFIX .. "BoostDirection", vec(b.direction))
		p:SetAttribute(PREFIX .. "BoostStrength", b.strength)
		p.Parent = boosts
	end

	-- 4) lights + signs ----------------------------------------------------
	local lights = folder("Lights", world)
	for i, l in Manifest.lights do
		local holder = Instance.new("Part")
		holder.Name = string.format("%s_%03d", l.kind, i)
		holder.Size = Vector3.new(0.4, 0.4, 0.4)
		holder.CFrame = CFrame.new(vec(l.position))
		makeVisual(holder, false)
		holder.Transparency = 1
		local pl = Instance.new("PointLight")
		pl.Color = Color3.fromRGB(l.color[1], l.color[2], l.color[3])
		pl.Range = math.min(l.range, 60)
		pl.Brightness = l.brightness
		pl.Shadows = l.shadows
		pl.Parent = holder
		holder.Parent = lights
		report.lights += 1
	end
	local signs = folder("Signs", world)
	for i, t in Manifest.texts do
		local board = Instance.new("Part")
		board.Name = string.format("%s_%02d", t.kind, i)
		board.Size = Vector3.new(t.size[1], t.size[2], 0.05)
		board.CFrame = quatCFrame(t.position, t.rotation)
		makeVisual(board, false)
		board.Transparency = 1
		local gui = Instance.new("SurfaceGui")
		gui.Face = Enum.NormalId.Front
		gui.SizingMode = Enum.SurfaceGuiSizingMode.PixelsPerStud
		gui.PixelsPerStud = 24
		gui.LightInfluence = 0.35
		gui.MaxDistance = 650
		gui.Parent = board
		local badge = Color3.fromRGB(t.badge[1], t.badge[2], t.badge[3])
		local bg = Instance.new("Frame")
		bg.Size = UDim2.fromScale(1, 1)
		bg.BorderSizePixel = 0
		bg.BackgroundColor3 = if t.kind == "Section" then Color3.fromRGB(246, 248, 252) else badge
		bg.Parent = gui
		local n = #t.lines
		for li, line in t.lines do
			local lbl = Instance.new("TextLabel")
			lbl.BackgroundTransparency = 1
			lbl.TextScaled = true
			lbl.Font = Enum.Font.GothamBlack
			lbl.Text = line
			if t.kind == "Section" and li == 1 then
				-- number badge on the left
				lbl.BackgroundTransparency = 0
				lbl.BackgroundColor3 = badge
				lbl.TextColor3 = Color3.new(1, 1, 1)
				lbl.Position = UDim2.fromScale(0.03, 0.12)
				lbl.Size = UDim2.fromScale(0.26, 0.76)
			elseif t.kind == "Section" then
				lbl.TextColor3 = Color3.fromRGB(28, 36, 52)
				lbl.Position = UDim2.fromScale(0.33, 0.18)
				lbl.Size = UDim2.fromScale(0.64, 0.64)
			else
				lbl.TextColor3 = Color3.new(1, 1, 1)
				lbl.Position = UDim2.fromScale(0.04, 0.08 + 0.84 * (li - 1) / n)
				lbl.Size = UDim2.fromScale(0.92, 0.84 / n)
			end
			lbl.Parent = bg
		end
		board.Parent = signs
		report.signs += 1
	end

	-- 5) gondola cables (cabins are animated on the clients) --------------
	local gondola = folder("Gondola", world)
	for _, line in GondolaData.lines do
		local cables = model("Cables_" .. line.id, gondola)
		local pts: { number } = line.path
		local count = #pts // 3
		for i = 1, count do
			local j = (i % count) + 1
			local a = Vector3.new(pts[(i - 1) * 3 + 1], pts[(i - 1) * 3 + 2], pts[(i - 1) * 3 + 3])
			local b = Vector3.new(pts[(j - 1) * 3 + 1], pts[(j - 1) * 3 + 2], pts[(j - 1) * 3 + 3])
			local len = (b - a).Magnitude
			if len < 0.05 then
				continue
			end
			local seg = Instance.new("Part")
			seg.Name = "Cable"
			seg.Shape = Enum.PartType.Cylinder
			seg.Size = Vector3.new(len + 0.1, 0.32, 0.32)
			seg.CFrame = CFrame.lookAt((a + b) / 2, b) * CFrame.Angles(0, math.pi / 2, 0)
			seg.Material = Enum.Material.Metal
			seg.Color = Color3.fromRGB(46, 48, 54)
			makeVisual(seg, false)
			seg.Parent = cables
			report.cableSegments += 1
			tick()
		end
		cables:SetAttribute(PREFIX .. "GondolaLine", line.id)
	end

	world:SetAttribute(PREFIX .. "BuiltAt", os.date("!%Y-%m-%dT%H:%M:%SZ"))
	world.Parent = parent
	report.seconds = os.clock() - t0
	report.ok = #report.missing == 0 and #report.axisErrors == 0 and #report.sizeMismatch == 0 and #report.rotated == 0
	Importer.PrintReport(report)
	return report
end

function Importer.PrintReport(r: Report)
	print("[SnowyValley] ===== build report =====")
	print(string.format("[SnowyValley] meshes found %d / %d expected", r.meshesFound, r.meshesExpected))
	print(string.format("[SnowyValley] unique meshes placed %d, asset instances %d (%d mesh parts)", r.uniquePlaced, r.instancesPlaced, r.partsPlaced))
	if r.collision then
		print(string.format("[SnowyValley] collision: %d wedges, %d boxes, %d kickers, %d models", r.collision.wedges, r.collision.boxes, r.collision.kickers, r.collision.models))
	end
	print(string.format("[SnowyValley] gates %d, spawns %d, lights %d, signs %d, cable segments %d", r.gates, r.spawns, r.lights, r.signs, r.cableSegments))
	local function list(title: string, t: { string })
		if #t > 0 then
			warn(string.format("[SnowyValley] %s (%d): %s", title, #t, table.concat(t, ", ", 1, math.min(#t, 25))))
		end
	end
	list("MISSING meshes (not imported?)", r.missing)
	list("scale corrected (check the importer's file dimensions)", r.scaleFixed)
	list("AXIS ERRORS - re-import with World Up = +Y / World Forward = -Z", r.axisErrors)
	list("ORIENTATION PROBE MISMATCH - meshes of these files look rotated/mirrored; verify visually and re-import with World Up +Y / World Forward -Z", r.rotated)
	print(string.format("[SnowyValley] orientation probes checked: %d (EditableMesh; 0 = API unavailable, sizes still verified)", r.probesChecked))
	list("size mismatch (wrong file?)", r.sizeMismatch)
	list("duplicate mesh names (first one used)", r.duplicates)
	print(string.format("[SnowyValley] %s in %.1f s", if r.ok then "BUILD OK" else "BUILD FINISHED WITH ISSUES", r.seconds))
end

return Importer
