--!strict
-- Snowy Valley - types of the generated metadata (see Metadata/*.json).
-- Positions are Roblox studs (X, Y up, Z); rotations are quaternions {x, y, z, w}.

export type Vec = { number } -- {x, y, z}
export type Quat = { number } -- {x, y, z, w}

-- RouteData ---------------------------------------------------------------
-- sample = {x, y, z, s_m, progress_m, halfwidth, margin_l, margin_r, surface, section}
-- (x, y, z, halfwidth and margins in studs; s and progress in meters)
export type RouteDef = {
	id: string,
	name: string,
	difficulty: string,
	kind: string, -- "main" | "alt"
	length_m: number,
	race_length_m: number?,
	branch_main_m: number?,
	merge_main_m: number?,
	samples: { { number } },
}

export type SectionDef = {
	id: number,
	name: string,
	legend: string,
	character: string,
	start_m: number,
	end_m: number,
	width_m: number,
	drop_m: number,
}

export type RouteData = {
	units: { studs_per_meter: number },
	routes: { RouteDef },
	sections: { SectionDef },
	main: { race_length_m: number, drop_m: number },
}

-- Checkpoints -------------------------------------------------------------
export type GateDef = {
	id: string,
	group: number,
	route: string,
	station_m: number,
	progress_m: number,
	progress_studs: number,
	position: Vec,
	rotation: Quat,
	size: Vec,
	is_finish: boolean,
	is_start: boolean,
	section: string,
}

export type GroupDef = { group: number, name: string, gates: { GateDef } }
export type SpawnDef = { position: Vec, rotation: Quat }
export type BoostDef = {
	id: string,
	station_m: number,
	position: Vec,
	rotation: Quat,
	size: Vec,
	direction: Vec,
	strength: number,
}

export type CheckpointData = {
	groups: { GroupDef },
	spawns: { SpawnDef },
	boosts: { BoostDef },
	group_count: number,
	finish_group: number,
	rule: string,
}

-- Collision ---------------------------------------------------------------
export type StripDef = {
	route: string,
	surface: number,
	kinds: { string },
	rows: { { number } }, -- each row: x1, y1, z1, x2, y2, z2, ... left -> right
}

export type BoxDef = { kind: string, position: Vec, rotation: Quat, size: Vec }
export type PatchDef = { name: string, nx: number, ny: number, points: { number }, mask: { number } }
export type KickerDef = { position: Vec, rotation: Quat, size: Vec }

export type CollisionData = {
	units: { studs_per_meter: number },
	strips: { StripDef },
	boxes: { BoxDef },
	patches: { PatchDef },
	kickers: { KickerDef },
}

-- Asset manifest ----------------------------------------------------------
export type RobloxLook = {
	Material: string,
	Color: { number },
	Reflectance: number?,
	Transparency: number?,
	Texture: string?,
}

export type TemplatePart = {
	mesh: string,
	material: string,
	roblox: RobloxLook,
	offset: Vec,
	size: Vec,
	tris: number,
}

export type TemplateDef = { category: string, file: string, parts: { TemplatePart }, tris: number }

export type UniqueDef = {
	mesh: string,
	category: string,
	file: string,
	material: string,
	roblox: RobloxLook,
	position: Vec,
	size: Vec,
	tris: number,
	collide: string,
	group: string,
}

export type LightDef = {
	kind: string,
	position: Vec,
	color: { number },
	range: number,
	brightness: number,
	shadows: boolean,
}

export type TextDef = {
	kind: string,
	position: Vec,
	rotation: Quat,
	size: { number },
	lines: { string },
	badge: { number },
}

-- instance = {assetIndex(0-based), px, py, pz, qx, qy, qz, qw, scale, collide, group}
export type AssetManifest = {
	version: string,
	units: { studs_per_meter: number },
	assets: { string },
	templates: { [string]: TemplateDef },
	instances: { { any } },
	unique: { UniqueDef },
	lights: { LightDef },
	texts: { TextDef },
	counts: { [string]: number },
}

-- Gondola -----------------------------------------------------------------
export type GondolaLine = {
	id: string,
	name: string,
	speed_studs: number,
	spacing_studs: number,
	cabin_template: string,
	hang_studs: number,
	gauge_studs: number,
	loop_length_studs: number,
	path: { number }, -- x, y, z, x, y, z, ... (closed loop)
	stations: { { asset: string, position: Vec, cable_y: number } },
	pylons: { { asset: string, position: Vec, cable_y: number } },
	passenger_transport: boolean,
	note: string,
}

export type GondolaData = { lines: { GondolaLine } }

return {}
