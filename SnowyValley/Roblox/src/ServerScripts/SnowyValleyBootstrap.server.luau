--!strict
-- Snowy Valley - bootstrap + standalone test mode (ServerScriptService).
--
-- Shipped DISABLED. Enable it to test the course without the round system:
-- it loads the world, applies the light preset, puts every player on the
-- spawn grid and runs a race session (checkpoints, out-of-bounds respawn,
-- finish time in the output window). A respawned character starts a new run.
--
-- In the real game set the attribute TestMode = false (or delete this
-- script) and call Integration.Init / LoadWorld / StartRace from the
-- existing RoundManager instead.

local ServerStorage = game:GetService("ServerStorage")
local Players = game:GetService("Players")

local Integration = require(ServerStorage:WaitForChild("SnowyValleyServer"):WaitForChild("Integration"))

Integration.Init()

local testMode = script:GetAttribute("TestMode")
if testMode == false then
	return
end

Integration.LoadWorld(workspace)
local spawns = Integration.GetSpawnCFrames()
local session = Integration.StartRace({})
local nextSlot = 0

local function onCharacter(player: Player, character: Model)
	character:WaitForChild("HumanoidRootPart")
	nextSlot = nextSlot % #spawns + 1
	task.wait()
	character:PivotTo(spawns[nextSlot] + Vector3.new(0, 3, 0))
	-- fresh run for this player
	session:RemoveRacer(player)
	session:AddRacer(player)
end

local function onPlayer(player: Player)
	player.CharacterAdded:Connect(function(character)
		onCharacter(player, character)
	end)
	if player.Character then
		onCharacter(player, player.Character)
	end
end

Players.PlayerAdded:Connect(onPlayer)
for _, p in Players:GetPlayers() do
	onPlayer(p)
end
Players.PlayerRemoving:Connect(function(player)
	session:RemoveRacer(player)
end)
