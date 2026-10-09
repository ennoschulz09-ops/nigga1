--!strict
-- Snowy Valley - logic tests in Studio (same specs as the CLI runner).
-- Command bar:  require(game.ServerStorage.SnowyValleyServer.Tests.RunTests)()
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Shared = ReplicatedStorage:WaitForChild("SnowyValleyShared")

return function(): (number, number)
	local specs = require(script.Parent:WaitForChild("Specs")) :: any
	local passed, failed = 0, 0
	local t = {
		check = function(cond: boolean, msg: string)
			if cond then
				passed += 1
				print("[SnowyValley test] PASS " .. msg)
			else
				failed += 1
				warn("[SnowyValley test] FAIL " .. msg)
			end
		end,
		info = function(msg: string)
			print("[SnowyValley test] info " .. msg)
		end,
	}
	specs(t, {
		RouteGraph = require(Shared:WaitForChild("RouteGraph")),
		CheckpointTracker = require(Shared:WaitForChild("CheckpointTracker")),
		RouteData = require(Shared.Data:WaitForChild("RouteData")),
		Checkpoints = require(Shared.Data:WaitForChild("Checkpoints")),
	})
	print(string.format("[SnowyValley test] %d passed, %d failed", passed, failed))
	return passed, failed
end
