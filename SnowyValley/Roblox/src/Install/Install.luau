--!strict
-- Snowy Valley - one-step installer.
-- After inserting SnowyValley.rbxmx into ServerStorage, run in the command bar:
--     require(game.ServerStorage.SnowyValleyInstall.Install)()
-- Moves each package folder into its service. An existing Integration module
-- (your adapter edits) is kept; everything else is replaced by the new version.

local StarterPlayer = game:GetService("StarterPlayer")

local function serviceFor(name: string): Instance
	if name == "StarterPlayerScripts" then
		return StarterPlayer:WaitForChild("StarterPlayerScripts")
	end
	return game:GetService(name)
end

return function()
	local root = script.Parent
	for _, holder in root:GetChildren() do
		if not holder:IsA("Folder") then
			continue
		end
		local service = serviceFor(holder.Name)
		for _, child in holder:GetChildren() do
			local existing = service:FindFirstChild(child.Name)
			if existing then
				-- keep the user's adapter
				local oldIntegration = existing:FindFirstChild("Integration")
				local newIntegration = child:FindFirstChild("Integration")
				if oldIntegration and newIntegration then
					newIntegration:Destroy()
					oldIntegration.Parent = child
					print("[SnowyValley] kept your existing Integration module")
				end
				-- keep generated assets (e.g. the gondola cabin built by the importer)
				local oldAssets = existing:FindFirstChild("Assets")
				if oldAssets and not child:FindFirstChild("Assets") then
					oldAssets.Parent = child
				end
				existing:Destroy()
			end
			child.Parent = service
			print(string.format("[SnowyValley] installed %s -> %s", child.Name, service:GetFullName()))
		end
	end
	root:Destroy()
	print("[SnowyValley] install complete. Next: import the FBX files, then run")
	print("    require(game.ServerStorage.SnowyValleyServer.Importer).Build()")
end
