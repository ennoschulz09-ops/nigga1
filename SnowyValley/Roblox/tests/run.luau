--!strict
-- Snowy Valley - standalone logic tests (no Roblox needed):
--     /opt/luau/luau tests/run.luau
-- Fixtures are generated from Metadata/*.json by build_package.py.

local RouteGraph = require("../src/Shared/RouteGraph")
local CheckpointTracker = require("../src/Shared/CheckpointTracker")
local RouteData = require("./fixtures/RouteData")
local Checkpoints = require("./fixtures/Checkpoints")
local specs = require("./specs")

local passed, failed = 0, 0
local t = {
	check = function(cond: boolean, msg: string)
		if cond then
			passed += 1
			print("PASS " .. msg)
		else
			failed += 1
			print("FAIL " .. msg)
		end
	end,
	info = function(msg: string)
		print("info " .. msg)
	end,
}
specs(t, {
	RouteGraph = RouteGraph,
	CheckpointTracker = CheckpointTracker,
	RouteData = RouteData,
	Checkpoints = Checkpoints,
})
print(string.format("%d passed, %d failed", passed, failed))
if failed > 0 then
	error("tests failed")
end
