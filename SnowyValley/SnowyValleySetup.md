# AVALANCHE RIDERS – Welt 1 „SNOWY VALLEY“: Einrichtung in Roblox Studio

Diese Anleitung beschreibt, wie die generierte Welt in dein bestehendes Spiel kommt.
Die Welt ist als **Erweiterung** gebaut: Sie ändert keine bestehenden Skripte und
keine der anderen vier Welten. Die einzige Datei, die du an dein Spiel anpasst,
ist `SnowyValleyServer/Integration` (Adapter).

> **Ehrlicher Stand:** Alles hier wurde außerhalb von Roblox Studio erzeugt und
> geprüft (Blender-Generator, programmatische Validierung, Luau-Logiktests mit
> der `luau`-CLI, Typprüfung mit `luau-lsp` und den offiziellen Roblox-Typdefinitionen).
> Der **Import in Roblox Studio und das Spielen in Studio wurden nicht durchgeführt** –
> die Punkte unter „In Studio noch zu prüfen“ sind offen.

---

## 1. Inhalt

| Ordner / Datei | Inhalt |
|---|---|
| `Blender/GenerateSnowyValley.py` + `Blender/sv/` | Prozeduraler Generator (Blender 4.2+, getestet mit 5.2.2 LTS) |
| `Blender/SnowyValley.blend` | Generierte Szene (komprimiert) – siehe Abschnitt 9, falls nicht im Repo |
| `Export/**/*.fbx` | 14 FBX-Dateien (Studs, Y-oben), alle Meshes ≤ 20 000 Dreiecke und ≤ 2048 Studs |
| `Export/Textures/SV_TreePalette.png` | Farbpalette der Bäume (auch in den FBX eingebettet) |
| `Metadata/*.json` | AssetManifest, RouteData, Checkpoints, CollisionData, GondolaData, Environment, ValidationReport |
| `Roblox/SnowyValley.rbxmx` | **Installationspaket** für Roblox Studio (alle Luau-Module + Daten) |
| `Roblox/src/**` | Luau-Quellcode des Pakets (lesbar / für Rojo-Nutzer) |
| `Roblox/tests/` | Logiktests (laufen ohne Roblox: `/opt/luau/luau tests/run.luau`) |
| `Previews/*.png` | Kontroll-Renderings (Draufsicht, Luftbild, Gipfel, Wald, Brücke ×2, Eishöhle, Dorf, See, Canyon) + schematische Routenkarte `layout_topdown.png` |
| `Tools/build_package.py` | Erzeugt Daten-Module, Testdaten, `SnowyValley.rbxmx` und `sourcemap.json` |

Koordinatenvertrag: Roblox (X, Y oben, Z) in Studs = Blender (x, z, −y) in Metern × 3,5714
(1 Stud = 0,28 m). Jede Platzierung erfolgt aus dem Manifest (Mittelpunkt der Bounding-Box +
Rotation) – nie aus der Position, an der der Importer ein Mesh ablegt. Damit sind die
früheren Ursprungs-/Versatzprobleme ausgeschlossen.

---

## 2. Paket installieren

1. Roblox Studio öffnen, dein Spiel laden.
2. Im Explorer **Rechtsklick auf `ServerStorage` → „Insert from File…“** → `Roblox/SnowyValley.rbxmx`.
   Es erscheint `ServerStorage.SnowyValleyInstall`.
3. In der Befehlsleiste (View → Command Bar) ausführen:
   ```lua
   require(game.ServerStorage.SnowyValleyInstall.Install)()
   ```
   Das verschiebt die Teile an ihren Platz:

   | Ziel | Inhalt |
   |---|---|
   | `ReplicatedStorage.SnowyValleyShared` | Config, RouteGraph, CheckpointTracker, EnvironmentPreset, GondolaClient, Daten (Route/Checkpoints/Gondel/Umgebung) |
   | `ServerStorage.SnowyValleyServer` | Importer, CollisionBuilder, World, RaceRuntime, **Integration (Adapter)**, Daten (Manifest, Kollision), Tests |
   | `ServerScriptService.SnowyValleyBootstrap` | Start-/Testskript (**deaktiviert** ausgeliefert) |
   | `StarterPlayer.StarterPlayerScripts.SnowyValleyGondola` | Client-Animation der Gondeln |

   Bei einer späteren Neuinstallation bleibt deine angepasste `Integration` erhalten.

---

## 3. FBX-Dateien importieren

1. **File → Import 3D** (bzw. „3D importieren“) und nacheinander alle 14 Dateien aus `Export/`
   importieren (Unterordner Terrain, Pistes, Forest, Rocks, Buildings, Bridges, Environment,
   Gondola, Props).
2. Empfohlene Importer-Einstellungen:
   - **Maßeinheit / Scale Unit: Stud** (die FBX-Koordinaten sind bereits Studs).
     Wird eine andere Einheit gewählt, korrigiert der Weltbauer einen *gleichmäßigen*
     Skalierungsfehler automatisch und meldet ihn.
   - **World Up: +Y (Top)**, **World Forward: −Z (Front)** (Standard).
   - **Merge Meshes: AUS** – jedes Objekt muss ein eigenes MeshPart mit seinem Namen bleiben.
   - Anchored: an. Kollision des Importers ist egal (der Weltbauer setzt alles selbst).
3. Im Explorer in `ServerStorage` einen Ordner **`SnowyValleyImport`** anlegen und alle
   importierten Modelle hineinziehen (die Unterstruktur ist egal, gesucht wird nach Namen).

---

## 4. Welt bauen (einmalig in Studio)

In der Befehlsleiste:
```lua
require(game.ServerStorage.SnowyValleyServer.Importer).Build()
```
Das erzeugt `ServerStorage.SnowyValleyWorld` (ein Model) und schreibt einen Bericht ins
Output-Fenster:

- `meshes found X / Y expected` – fehlende Namen werden aufgelistet (nicht importiert?).
- `scale corrected` – gleichmäßiger Maßstabsfehler wurde korrigiert (unkritisch).
- `AXIS ERRORS` – Achsen vertauscht (falsche Importer-Achsen) → diese Meshes werden
  **nicht** platziert; Datei mit World Up +Y / World Forward −Z neu importieren.
- `ORIENTATION PROBE MISMATCH` – ein asymmetrischer Referenzpunkt pro Datei (über
  EditableMesh gelesen) passt nicht: Datei vermutlich gedreht/gespiegelt importiert.
  Ist die EditableMesh-API nicht verfügbar, steht dort `probes checked: 0` (die
  Größenprüfung läuft trotzdem).
- `BUILD OK` am Ende, wenn nichts fehlt.

Aufbau des Modells `SnowyValleyWorld`:

```
SnowyValleyWorld
├─ Visual/        Terrain_xx_yy (pro Chunk, LevelOfDetail = StreamingMesh), Backdrop (Persistent),
│                 Pistes, Forest_*, Rocks_*, Village_*, Props_*, Gondola_*, Bridges, IceCave …
├─ Collision/     Surfaces/<Route>_<nnn>, Patches, Boxes, CatchFloors, Kickers
├─ Gameplay/      Checkpoints (26 Tore in 18 Gruppen), Spawns (16), Boosts (5)
├─ Lights/        PointLights (Laternen, Eishöhle, Brücke, Dorfplatz)
├─ Signs/         SurfaceGui-Schilder (Abschnitte, Abzweigungen, Start/Ziel, Gondel, Läden)
└─ Gondola/       Seile (Zylinder) – Kabinen animiert jeder Client selbst
```

Visuelle Meshes haben `CanCollide = false`, `CanQuery = false`, `CanTouch = false`.
Nur die Kollisionsgeometrie ist für Raycasts sichtbar (wichtig für SlopeRaycaster).

---

## 5. Sofort testen (ohne dein Rundensystem)

1. `ServerScriptService.SnowyValleyBootstrap` **aktivieren** (Enabled/Disabled umschalten).
2. **Play**. Das Skript lädt die Welt, setzt die Lichtstimmung, stellt Spieler auf das
   Startraster und startet eine Rennsitzung: Checkpoints, Out-of-Bounds-Respawn und
   Zielzeit erscheinen im Output. Ein neuer Charakter startet einen neuen Lauf.
3. Logiktests in Studio (Befehlsleiste):
   ```lua
   require(game.ServerStorage.SnowyValleyServer.Tests.RunTests)()
   ```
4. Danach das Bootstrap-Skript wieder deaktivieren (oder Attribut `TestMode = false`
   setzen), sobald dein RoundManager die Welt lädt.

---

## 6. In dein Spiel einbinden (Adapter `Integration`)

Öffne `ServerStorage.SnowyValleyServer.Integration`. Alle Stellen sind mit
`-- INTEGRATION:` markiert:

| Funktion | Wer ruft sie auf | Was du einträgst |
|---|---|---|
| `Integration.Init()` | einmal beim Serverstart | Registrierung bei Map-Voting / WorldBuilder (`World.GetMapDefinition()` liefert Name, Länge, Gefälle, Abschnitte, Routen) |
| `Integration.LoadWorld(parent)` | WorldBuilder, wenn Snowy Valley gewählt wurde | nichts – klont die Welt nach Workspace und setzt die Umgebung |
| `Integration.UnloadWorld()` | nach der Runde | nichts |
| `Integration.ApplyEnvironment()` | intern | Preset an deinen **WorldEnvironmentController** übergeben (`EnvironmentPreset.Preset`); ohne Controller wird Lighting direkt gesetzt und beim Entladen zurückgesetzt |
| `Integration.GetSpawnCFrames()` | RoundManager | 16 Startplätze hinter der Startlinie |
| `Integration.StartRace(players)` | RaceService nach dem Countdown | nichts – startet die Überwachung |
| `Integration.Hooks.OnCheckpoint` | Laufzeit | an deinen **CheckpointService** weiterreichen (`event.group` 1…18) |
| `Integration.Hooks.OnFinish` | Laufzeit | an deinen **RaceService** (Zielzeit `event.time` in s) |
| `Integration.Hooks.OnOutOfBounds` | Laufzeit | `true` zurückgeben, wenn dein RaceService selbst respawnt; sonst teleportiert die Erweiterung auf die letzte gültige Position |
| `Integration.Hooks.OnBoost` | Boost-Felder | deinen Boost auslösen (Richtung/Stärke als Attribute) |

Beispiel (Namen an dein Projekt anpassen):
```lua
-- in Integration.Init
Services.MapVoting.RegisterMap(def.Id, def.DisplayName, def)
-- in Integration.ApplyEnvironment
controller:ApplyPreset(EnvironmentPreset.Preset)
-- in Integration.Hooks.OnCheckpoint
Services.CheckpointService:CheckpointReached(player, event.group)
-- in Integration.Hooks.OnFinish
Services.RaceService:PlayerFinished(player, event.time)
```

Physik, RaceService, CheckpointService, RoundManager und Map-Voting bleiben unverändert –
die Erweiterung meldet nur Ereignisse.

**Variante B (attributbasiertes CheckpointService):** Jedes Tor-Part in
`Gameplay/Checkpoints` trägt `CheckpointIndex` (1…18) und `IsFinish`. Gleichwertige Tore
auf Varianten teilen sich denselben Index. Wenn dein Service nur ein Part pro Index
erwartet, nutze Variante A (Hooks) – sonst entsteht auf Varianten ein falsches DNF.

---

## 7. Kollision (SlopeRaycaster-kompatibel)

- Die Fahrfläche wird **nicht** aus den sichtbaren Meshes erzeugt, sondern aus
  `CollisionData`: Querschnitte (4, 9 oder 17 Punkte) entlang jeder Route, je Viereck zwei
  Dreiecke, je Dreieck zwei WedgeParts (EgoMoose-Verfahren). Die Keile sind Platten,
  die **unter** die Oberfläche ragen – ihre Oberseite ist exakt die Fahrfläche.
- Jeder Abschnitt wählt Querschnitt und Schrittweite so, dass die Fläche höchstens
  0,10 m (Piste) bzw. 0,35 m (Rand) vom sichtbaren Gelände abweicht – gemessen an
  33 Querpunkten inklusive Viereck-Mitten. Gemessene Werte: siehe `Metadata/ValidationReport.md`.
- Brücke und Eishöhle: analytische Flächen; die Übergänge zum Gelände sind nahtlos (gemessen 0,000 m).
- Begrenzungswände, Brückenbrüstungen, Höhlenwände/-decke: unsichtbare Parts
  (`CanQuery = false`, damit Raycasts sie nicht als Boden sehen; umstellbar in `Config.Collision.WallsQueryable`).
- Start, Zielplatz und Dorf: begehbare Bodenraster (Patches).
- Out-of-Bounds: große Auffangböden 35 m unter dem tiefsten Gelände jedes Chunks +
  Erkennung über den Routengraphen (außerhalb des Korridors, darunter, auf dem Höhlendach).
- Die Kollisionsmodelle sind `ModelStreamingMode = Persistent` (kein Durchfallen beim
  Streaming). Alternativ `Config.Collision.SurfaceStreamingMode = "Atomic"`.

---

## 8. Leistung / Streaming – Empfehlungen

- `Workspace.StreamingEnabled = true`, `StreamingMinRadius ≈ 512`, `StreamingTargetRadius ≈ 2048`.
- Terrain-Chunks und Waldflächen sind einzelne Modelle mit `LevelOfDetail = StreamingMesh`
  (Platzhalter-Mesh in der Ferne); der Bergkranz (`Backdrop`) ist Persistent.
- Keine Mesh überschreitet 20 000 Dreiecke oder 2048 Studs; der dichte Wald ist in 35
  Chunk-Meshes „gebacken“, nur nahe der Pisten stehen einzelne Bäume.
- `Workspace.FallenPartsDestroyHeight`: Der tiefste Auffangboden liegt bei −188 Studs
  (gemessen); der Standardwert −500 liegt sicher darunter, solange du die Welt nicht absenkst.
- Gemessene Mengen (Bericht): 411 Unikat-Meshes, 70 Asset-Vorlagen (319 Mesh-Teile),
  4 725 platzierte Objekte, 35 560 Kollisionskeile + 1 712 Boxen.
  Dreiecke: Terrain 338 k (+ 87 k Bergkranz), Pisten 109 k, Waldflächen 284 k,
  Einzelbäume 1,24 Mio. (≈ 3 000 Instanzen von 6 Baum-Varianten), Felsen 420 k.
  Wiederholte Meshes rendert Roblox instanziert; trotzdem ist das Wald-/Felsbudget der
  größte Hebel, falls Mobilgeräte zu schwach sind (Anzahl in `placement.py` → `cap`).
- Gondelkabinen bewegt nur der Client (BulkMoveTo, keine Physik, kein Netzwerkverkehr),
  nur wenn die Kamera in der Nähe ist. **Personentransport ist nicht umgesetzt** –
  die Gondeln sind animierte Kulisse.

---

## 9. Welt neu generieren (optional)

```bash
blender --background --python Blender/GenerateSnowyValley.py -- --render topdown,aerial,summit,forest,bridge,bridge_side,cave,village,lake,canyon
python3 Tools/build_package.py
```
Optionen: `--quick` (6-m-Raster für schnelle Iteration), `--stages a,b`, `--no-export`,
`--no-save`. Alles ist deterministisch (feste Seeds). Laufzeit ca. 2 Minuten ohne
Renderings, je Rendering ca. 2–4 Minuten (CPU). Falls `SnowyValley.blend` wegen der
GitHub-Dateigrößen nicht im Repository liegt, erzeugt der obige Befehl sie identisch neu.

---

## 10. In Studio noch zu prüfen (nicht durchgeführt)

1. Import aller 14 FBX mit den genannten Einstellungen; Build-Bericht ohne fehlende Meshes.
2. Optik in Studio-Beleuchtung (Materialfarben, Baumtextur, SurfaceGui-Schilder).
3. Fahrt mit dem **echten Board / SlopeRaycaster** über die gesamte Hauptroute und alle
   vier Varianten (Kanten der Keile, Brücke, Höhle, Kicker, Übergänge an Abzweigungen).
4. Checkpoint-Ereignisse mit deinem CheckpointService/RaceService (inkl. Varianten, kein falsches DNF).
5. Out-of-Bounds-Respawn an Klippen, Canyon, Brücke, Höhlendach.
6. Streaming mit vielen Spielern / Mobilgeräten (Speicher, Ladezeit der ca. 37 000 Kollisionsteile, Bildrate im Wald).
7. WorldEnvironmentController-Übergabe und Rückkehr zu den anderen Welten.
8. Gondel-Animation auf dem Client (Kabinen auf dem Seil, Abstand zum Gelände).
