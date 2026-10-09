--!strict
-- Snowy Valley - starts the client-side gondola animation.
-- Lives in StarterPlayer.StarterPlayerScripts.

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Shared = ReplicatedStorage:WaitForChild("SnowyValleyShared")
require(Shared:WaitForChild("GondolaClient")).Start()
