"""Route network design for SNOWY VALLEY (data only).

Coordinate frame: meters, X = east, Y = north (Blender), Z = up.

The map follows the reference sheet's composition:
    * summit start at the top centre, upper gondola station west of it
    * cliffs / red terrain on the east face, forests on the west face
    * frozen lake, ravine + stone bridge and the canyon in the centre
    * ice cave where the canyon creek breaks through a rock rib
    * open fields lower east, alpine village + valley plaza bottom centre

The MAIN route (blue racing line) is a chain of 8 traverses ("legs") that
sweep across the mountain faces with hairpins at their ends, so the route
repeatedly disappears behind ridges, forests and the canyon walls.
Each section lists centreline waypoints starting at the section start.
Waypoints are interpolated with centripetal Catmull-Rom splines and then
smoothed, so the turning radius is controlled and kink-free.

Alternatives branch from / merge into the main route at (section, fraction)
stations; the builder pins their first and last 20 m onto the main route's
tangent so junctions are smooth "Y" splits.
"""

# Legend colours from the reference sheet (section badges / signage)
LEGEND = {
    "start": (196, 40, 40),
    "green": (52, 190, 84),
    "blue": (40, 120, 228),
    "red": (222, 48, 48),
    "orange": (226, 150, 60),
    "purple": (150, 90, 200),
    "finish": (196, 40, 40),
}

# fmt: off
MAIN_SECTIONS = [
    # ---- leg A: summit -> east ridge -> cliffs -------------------------------
    dict(id=1, name="Summit (Start)", legend="start", character="start",
         width=40, margin=(10, 10), steep=0.30, shape="start",
         pts=[(40, 940), (40, 908), (39, 877), (43, 848)]),
    dict(id=2, name="High Ridge Run", legend="blue", character="blue",
         width=32, margin=(12, 12), steep=1.00, shape="steady",
         pts=[(54, 819), (80, 798), (116, 791), (158, 796), (200, 782), (232, 754)]),
    dict(id=3, name="Cliff Descent", legend="red", character="red",
         width=24, margin=(12, 5), steep=1.85, shape="steepening",
         pts=[(251, 725), (269, 686), (275, 646), (289, 607), (310, 572)],
         fence="right"),
    # ---- leg B: hairpin, long forest traverse to the west ---------------------
    dict(id=4, name="Forest Run", legend="green", character="blue",
         width=28, margin=(10, 10), steep=0.85, shape="steady",
         pts=[(333, 543), (352, 513), (342, 484), (309, 474), (261, 494), (201, 487),
              (141, 472), (80, 461), (19, 451), (-42, 436), (-103, 425), (-163, 408)]),
    # ---- leg C: west hairpin, wide carve + rocky pass to the east -------------
    dict(id=5, name="Wide Carve", legend="blue", character="blue",
         width=52, margin=(12, 12), steep=1.05, shape="rollers",
         pts=[(-217, 390), (-260, 365), (-269, 329), (-242, 301), (-189, 300), (-149, 281),
              (-104, 279), (-63, 259), (-21, 250)]),
    dict(id=6, name="Rocky Pass", legend="red", character="red",
         width=26, margin=(6, 6), steep=0.95, shape="steady",
         pts=[(21, 232), (66, 222), (116, 213), (162, 218), (204, 204), (241, 184)]),
    # ---- leg D: east hairpin, second forest traverse to the west --------------
    dict(id=7, name="Tree Section", legend="green", character="blue",
         width=30, margin=(10, 10), steep=0.90, shape="rollers",
         pts=[(273, 170), (304, 145), (304, 109), (268, 93), (209, 106), (146, 94),
              (85, 83), (25, 73), (-36, 64), (-96, 55), (-157, 40)]),
    # ---- leg E: west hairpin, bridge, frozen lake shore, mountain pass ---------
    dict(id=8, name="Bridge Section", legend="orange", character="blue",
         width=22, margin=(8, 8), steep=0.55, shape="bridge",
         pts=[(-212, 24), (-252, 4), (-261, -33), (-234, -59), (-187, -63),
              (-142, -64), (-89, -65)],
         bridge=(0.56, 0.90)),
    dict(id=9, name="Frozen Lake", legend="blue", character="blue",
         width=34, margin=(10, 10), steep=0.65, shape="steady",
         pts=[(-51, -69), (-5, -82), (40, -91), (85, -96), (123, -109)]),
    dict(id=10, name="Mountain Pass", legend="red", character="red",
         width=30, margin=(8, 8), steep=1.25, shape="steps",
         pts=[(158, -124), (192, -135), (226, -152), (257, -166), (283, -175)]),
    # ---- leg F: east hairpin, down the canyon to the west ----------------------
    dict(id=11, name="Canyon Run", legend="blue", character="blue",
         width=24, margin=(4, 4), steep=1.00, shape="steady",
         pts=[(308, -184), (332, -213), (316, -246), (274, -256), (222, -249), (176, -258),
              (131, -267), (85, -266), (40, -276), (-5, -285), (-51, -293)]),
    # ---- leg G: ice cave through the rock rib, S-curves, steep slopes ---------
    dict(id=12, name="Ice Cave", legend="blue", character="blue",
         width=22, margin=(2, 2), steep=0.85, shape="tunnel",
         pts=[(-89, -304), (-115, -326), (-121, -359), (-105, -390), (-78, -411)],
         tunnel=(0.16, 0.88)),
    dict(id=13, name="S-Curve", legend="purple", character="blue",
         width=40, margin=(12, 12), steep=1.10, shape="rollers",
         pts=[(-51, -422), (-14, -414), (19, -431), (44, -458), (79, -469), (111, -455),
              (140, -457)]),
    dict(id=14, name="Steep Slopes", legend="red", character="red",
         width=36, margin=(10, 10), steep=2.05, shape="steps:0.40",
         pts=[(166, -469), (200, -491), (230, -523), (253, -569), (267, -611)]),
    # ---- leg H: open fields, final slopes, village approach, finish -----------
    dict(id=15, name="Open Fields", legend="green", character="green",
         width=58, margin=(14, 14), steep=0.75, shape="rollers",
         pts=[(268, -648), (251, -680), (215, -697), (169, -703), (131, -718)]),
    dict(id=16, name="Final Slopes", legend="green", character="blue",
         width=40, margin=(12, 12), steep=1.35, shape="steepening",
         pts=[(93, -734), (55, -749), (21, -772), (-9, -804), (-33, -841)]),
    dict(id=17, name="Village Approach", legend="blue", character="blue",
         width=32, margin=(8, 8), steep=0.70, shape="settle",
         pts=[(-51, -873), (-70, -906), (-85, -937)]),
    dict(id=18, name="Finish (Valley Plaza)", legend="finish", character="finish",
         width=60, margin=(10, 10), steep=0.08, shape="finish",
         pts=[(-95, -965), (-102, -998)]),
]
# fmt: on


# Stopping zone after the finish line (not part of the race length).
RUNOUT_PTS = [(-107, -1029), (-112, -1066)]

# Alternatives ----------------------------------------------------------------
ALTERNATIVES = [
    # exit  = (turn_deg, radius) arc right after the branch (+ = left turn)
    # entry = (turn_deg, radius) arc right before the merge
    dict(id="G1", name="Panorama Green", difficulty="green",
         width=36, margin=(12, 12), shape="green",
         branch=(1, 0.74), merge=(4, 0.76), exit=(-105, 58), entry=(-76, 58),
         pts=[(-60, 762), (-130, 756), (-200, 745), (-256, 720), (-306, 695), (-335, 653),
              (-327, 613), (-291, 586), (-231, 584), (-166, 580), (-104, 574), (-54, 563),
              (-21, 540), (-3, 504)],
         description="Wide, gentle family run along the upper west slope next to the "
                     "gondola; bypasses High Ridge Run, Cliff Descent and the east "
                     "half of the Forest Run."),
    dict(id="R1", name="Rocky Couloir", difficulty="red",
         width=18, margin=(5, 5), shape="red",
         branch=(6, 0.50), merge=(7, 0.45), exit=(-77, 30), entry=(-57, 23),
         pts=[(198, 181), (191, 152), (173, 140)], tangent=8.0,
         description="Steep, narrow chute between rock towers; cuts the east hairpin."),
    dict(id="R2", name="Canyon Drop", difficulty="black",
         width=18, margin=(4, 4), shape="red",
         branch=(10, 0.17), merge=(11, 0.46), exit=(-74, 23), entry=(-78, 24.5),
         pts=[(202, -174), (197, -187), (200, -220)], tangent=8.7,
         description="EXPERT (black diamond): steep drop from the Mountain Pass straight "
                     "down into the canyon - the reference sheet's expert line."),
    dict(id="G2", name="Meadow Green", difficulty="green",
         width=42, margin=(12, 12), shape="green",
         branch=(13, 0.87), merge=(16, 0.20), exit=(36, 58), entry=(60, 50),
         pts=[(240, -456), (290, -450), (340, -462), (385, -490), (418, -530), (432, -580),
              (428, -640), (408, -695), (372, -740), (325, -775), (275, -800), (225, -808),
              (180, -790), (150, -768)],
         description="Relaxed loop over the eastern meadows, avoiding the Steep Slopes "
                     "and joining at the foot of the Open Fields."),
]

# Difficulty limits used for validation (gradient as fraction, radius in m)
DIFFICULTY_RULES = {
    "green": dict(max_grad=0.23, avg_grad_max=0.17, min_radius=35.0, min_width=28.0),
    "blue": dict(max_grad=0.38, avg_grad_max=0.22, min_radius=21.0, min_width=20.0),
    "red": dict(max_grad=0.62, avg_grad_min=0.20, min_radius=18.0, min_width=14.0),
    # expert line (reference legend "EXPERT"): short, very steep risk/reward drop
    "black": dict(max_grad=0.75, avg_grad_min=0.25, min_radius=18.0, min_width=14.0),
}
