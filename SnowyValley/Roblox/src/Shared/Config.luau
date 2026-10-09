--!strict
-- Snowy Valley (World 1) - shared configuration.
-- Values here are read by the server builder, the race runtime and the client.

local Config = {
	WorldId = "SnowyValley",
	DisplayName = "Snowy Valley",
	WorldNumber = 1,

	StudsPerMeter = 1 / 0.28,

	-- Edit-time build (Importer.Build, run from the Studio command bar)
	ImportFolderName = "SnowyValleyImport", -- ServerStorage folder holding the models from the 3D Importer
	BuiltWorldName = "SnowyValleyWorld", -- Model written to ServerStorage by Importer.Build
	-- Imported mesh sizes may differ from the manifest by this relative amount
	-- before a part is reported (uniform scale errors are corrected).
	SizeTolerance = 0.02,

	Collision = {
		-- Slab thickness of every surface wedge, extruded below the riding surface.
		SurfaceThickness = 2.5,
		-- Route length (studs) per collision model; also the streaming unit.
		ChunkLength = 600,
		-- ModelStreamingMode of collision models. Persistent keeps the riding
		-- surface loaded on every client (no fall-through while streaming).
		SurfaceStreamingMode = "Persistent",
		-- Raycasts hit boundary walls / parapets / cave walls (false = only
		-- riding surfaces, kickers and the cave ceiling are queryable).
		WallsQueryable = false,
		-- Show the collision in edit mode (transparent orange) for inspection.
		Debug = false,
	},

	Race = {
		GroupCount = 18,
		FinishGroup = 18,
		-- Out of bounds: seconds outside before a respawn is requested.
		OutOfBoundsGraceSeconds = 1.25,
		-- Studs beyond the rideable corridor edge (piste + margin) that count as out.
		OutOfBoundsLateralStuds = 30,
		-- Studs below the route surface that count as fallen.
		OutOfBoundsBelowStuds = 60,
		-- Studs above a tunnel floor that count as "on the cave roof".
		TunnelRoofStuds = 55,
		-- Respawn: studs behind the last valid position, height above the surface.
		RespawnBackStuds = 40,
		RespawnHeightStuds = 5,
		-- Gate sweep: minimum movement (studs) between two samples to test crossings.
		SweepMinMove = 0.05,
	},

	Gondola = {
		-- Cabins are animated only for players within this distance of a line (studs).
		ActivationDistance = 3000,
		-- Hard cap of animated cabins per client (performance).
		MaxCabins = 110,
	},

	AttributePrefix = "SV_",

	-- Print checkpoint / skip events in the output window.
	Verbose = true,
	-- Without a WorldEnvironmentController, apply the light preset directly
	-- (restored on unload). Set false to never touch Lighting.
	StandaloneEnvironment = true,
}

return Config
