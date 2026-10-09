"""SNOWY VALLEY - procedural world generator for AVALANCHE RIDERS (World 1).

Run headless (Blender 4.2+ / tested with Blender 5.2.2 LTS):

    blender --background --python GenerateSnowyValley.py -- [options]

Options
    --quick            coarse heightfield (6 m) for fast iteration
    --stages a,b,c     run only these stages (default: all)
    --render a,b       render preview cameras (topdown, aerial, summit, forest,
                       bridge, bridge_side, cave, village, lake, canyon) into Previews/
    --no-export        skip FBX / metadata export
    --no-save          do not save SnowyValley.blend

Everything is deterministic (fixed seeds). All modelling units are meters;
the export stage converts to Roblox studs (1 stud = 0.28 m) and Y-up axes.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import importlib  # noqa: E402

import sv  # noqa: E402
from sv import pipeline  # noqa: E402


def parse_args(argv):
    args = argv[argv.index("--") + 1:] if "--" in argv else []
    opts = dict(quick=False, stages=None, render=[], export=True, save=True)
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--quick":
            opts["quick"] = True
        elif a == "--stages":
            opts["stages"] = args[i + 1].split(",")
            i += 1
        elif a == "--render":
            opts["render"] = args[i + 1].split(",")
            i += 1
        elif a == "--no-export":
            opts["export"] = False
        elif a == "--no-save":
            opts["save"] = False
        i += 1
    return opts


def main():
    opts = parse_args(sys.argv)
    ctx = pipeline.Context(quick=opts["quick"])
    ctx.log("Snowy Valley generator %s" % sv.GENERATOR_VERSION)
    pipeline.run(ctx, opts)


if __name__ == "__main__":
    main()
