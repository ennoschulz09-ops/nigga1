# AVALANCHE RIDERS – Welt 1: SNOWY VALLEY

Prozedural generierte Ski-/Snowboard-Welt für Roblox, nach dem Referenz-Kartenblatt
„Snowy Valley – Map Overview“: Gipfelstart, Klippen, Waldpassagen, Steinbrücke über eine
gefrorene Schlucht, zugefrorener See, Canyon, Eishöhle, S-Kurven, Steilhang, offene Felder
und ein Alpendorf mit Zielplatz.

| | Wert (gemessen) |
|---|---|
| Hauptroute (Rennlänge) | siehe `SnowyValley/Metadata/ValidationReport.md` (≈ 4,83 km) |
| Höhenunterschied | 720 m |
| Abschnitte / Checkpoint-Gruppen | 18 / 18 |
| Varianten | G1 Panorama Green, R1 Rocky Couloir, R2 Canyon Drop (Experte), G2 Meadow Green |

**Einrichtung in Roblox Studio:** [`SnowyValley/SnowyValleySetup.md`](SnowyValley/SnowyValleySetup.md)

Struktur:

```
SnowyValley/
  Blender/GenerateSnowyValley.py   Generator (Blender, headless)
  Blender/sv/                      Module: Routen, Gelände, Meshes, Assets, Kollision, Export, Validierung
  Blender/SnowyValley.blend        generierte Szene
  Export/                          FBX-Dateien für den Roblox 3D-Importer
  Metadata/                        JSON-Metadaten + ValidationReport
  Roblox/SnowyValley.rbxmx         Installationspaket (Luau)
  Roblox/src/                      Luau-Quellen; Roblox/tests/ Logiktests
  Previews/                        Kontroll-Renderings
  Tools/                           Paket-Generator, Layout-Vorschau
```

Neu generieren:

```bash
blender --background --python SnowyValley/Blender/GenerateSnowyValley.py -- --render topdown,aerial
python3 SnowyValley/Tools/build_package.py
/opt/luau/luau SnowyValley/Roblox/tests/run.luau    # Logiktests (luau-CLI)
```
