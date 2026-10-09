"""Programmatic validation of the generated world. Reports MEASURED values.

Every check returns (name, passed, details). The report is written to
Metadata/ValidationReport.json and .md.
"""

import json
import math
import os

import numpy as np

from . import collision as colmod
from . import config, layout, routes
from .mathutil import footprint_xy

# same footprint shrink as placement.FOOTPRINT_SHRINK (placement needs bpy)
FOOTPRINT_SHRINK = {"Rocks": 0.8, "Buildings": 1.0}


class Report:
    def __init__(self):
        self.checks = []
        self.metrics = {}

    def check(self, name, ok, **details):
        self.checks.append(dict(name=name, passed=bool(ok), details=details))
        return ok

    def metric(self, key, value):
        self.metrics[key] = value

    @property
    def passed(self):
        return sum(1 for c in self.checks if c["passed"])


def _round(x, n=2):
    if isinstance(x, (float, np.floating)):
        return round(float(x), n)
    if isinstance(x, (list, tuple)):
        return [_round(v, n) for v in x]
    if isinstance(x, dict):
        return {k: _round(v, n) for k, v in x.items()}
    if isinstance(x, (np.integer,)):
        return int(x)
    return x


def meaningful_bends(r, min_turn_deg=30.0, s0=0.0, s1=None):
    """Count turns: maximal runs of same-sign curvature whose total heading
    change exceeds min_turn_deg."""
    s1 = r.length if s1 is None else s1
    i0, i1 = r.index_at(s0), r.index_at(s1)
    k = r.kappa[i0:i1]
    sign = np.sign(np.where(np.abs(k) < 1.0 / 2000.0, 0.0, k))
    bends = []
    cur_sign, acc, start = 0, 0.0, 0
    for i, sg in enumerate(sign):
        if sg != 0 and sg == cur_sign:
            acc += k[i] * routes.DS
        else:
            if cur_sign != 0 and abs(math.degrees(acc)) >= min_turn_deg:
                bends.append((float(r.s[i0 + start]), round(math.degrees(acc), 1)))
            cur_sign = sg
            acc = k[i] * routes.DS if sg != 0 else 0.0
            start = i
    if cur_sign != 0 and abs(math.degrees(acc)) >= min_turn_deg:
        bends.append((float(r.s[i0 + start]), round(math.degrees(acc), 1)))
    return bends


def run(ctx, col=None, manifest=None, checkpoints=None):
    T, net = ctx.T, ctx.net
    m = net.main
    R = Report()

    # --- main route -------------------------------------------------------
    L = m.race_end_s
    drop = float(m.z[0] - m.interp("z", L))
    R.metric("main_length_m", round(L, 1))
    R.metric("main_length_studs", round(L * config.STUDS_PER_METER, 0))
    R.metric("elevation_drop_m", round(drop, 2))
    R.metric("elevation_drop_studs", round(drop * config.STUDS_PER_METER, 0))
    R.check("Main route length within 3% of 4.8 km", abs(L - config.TARGET_MAIN_LENGTH_M) / config.TARGET_MAIN_LENGTH_M < 0.03,
            measured_m=round(L, 1), target_m=config.TARGET_MAIN_LENGTH_M)
    R.check("Elevation drop = 720 m (+-1 m)", abs(drop - config.TARGET_ELEVATION_DROP_M) <= 1.0, measured_m=round(drop, 2))
    R.check("18 course sections in order", [d["id"] for d in m.sections] == list(range(1, 19)),
            sections=len(m.sections))
    bends = meaningful_bends(m, 30.0, 0.0, L)
    R.metric("main_meaningful_bends", len(bends))
    R.check("15-25+ meaningful bends (>=30 deg heading change)", len(bends) >= 15, count=len(bends),
            largest=sorted([abs(b[1]) for b in bends])[-5:])
    uphill = float(np.min(m.grad[: m.index_at(L)]))
    R.check("Main route always downhill before the finish line", uphill >= 0.0, min_gradient=round(uphill, 4))
    sec_rows = []
    for d in m.sections:
        i0, i1 = m.index_at(d["s0"]), m.index_at(d["s1"])
        rad = 1.0 / np.maximum(np.abs(m.kappa[i0:i1]), 1e-6)
        sec_rows.append(dict(id=d["id"], name=d["name"], length_m=round(d["s1"] - d["s0"], 1),
                             drop_m=round(float(m.interp("z", d["s0"]) - m.interp("z", d["s1"])), 1),
                             avg_grad_pct=round(100 * float(m.interp("z", d["s0"]) - m.interp("z", d["s1"])) / (d["s1"] - d["s0"]), 1),
                             max_grad_pct=round(100 * float(m.grad[i0:i1].max()), 1),
                             min_radius_m=round(float(rad.min()), 1), width_m=d["width"],
                             bends=len(meaningful_bends(m, 30.0, d["s0"], d["s1"]))))
    R.metric("sections", sec_rows)

    # --- difficulty rules ---------------------------------------------------
    route_rows = []
    for r in net.routes:
        rule = layout.DIFFICULTY_RULES[r.difficulty]
        end = r.index_at(r.race_end_s if r.kind == "main" else r.length)
        rad = 1.0 / np.maximum(np.abs(r.kappa[:end]), 1e-6)
        avg = float((r.z[0] - r.z[end]) / max(r.s[end], 1))
        row = dict(id=r.id, difficulty=r.difficulty, length_m=round(r.s[end], 1), avg_grad_pct=round(100 * avg, 1),
                   max_grad_pct=round(100 * float(r.grad[:end].max()), 1), min_radius_m=round(float(rad.min()), 1),
                   min_width_m=round(float(r.width[:end].min()), 1))
        route_rows.append(row)
        ok = row["max_grad_pct"] <= rule["max_grad"] * 100 + 0.05 and row["min_radius_m"] >= rule["min_radius"] - 0.05
        if "avg_grad_max" in rule:
            ok &= avg <= rule["avg_grad_max"] + 1e-6
        if "avg_grad_min" in rule:
            ok &= avg >= rule["avg_grad_min"] - 1e-6
        R.check("%s (%s) meets difficulty rules" % (r.id, r.difficulty), ok, **row, rule=rule)
    R.metric("routes", route_rows)

    # --- branches -----------------------------------------------------------
    for a in net.alts:
        pb = m.point(a.branch_s)[:2]
        pm = m.point(a.merge_s)[:2]
        e0 = float(np.hypot(a.x[0] - pb[0], a.y[0] - pb[1]))
        e1 = float(np.hypot(a.x[-1] - pm[0], a.y[-1] - pm[1]))
        h0 = abs(math.degrees(routes.wrap_angle(a.heading_unwrapped[0] - m.interp("heading_unwrapped", a.branch_s))))
        h1 = abs(math.degrees(routes.wrap_angle(a.heading_unwrapped[-1] - m.interp("heading_unwrapped", a.merge_s))))
        z0 = abs(float(a.z[0] - m.interp("z", a.branch_s)))
        z1 = abs(float(a.z[-1] - m.interp("z", a.merge_s)))
        ok = e0 < 2.0 and e1 < 2.0 and h0 < 4.0 and h1 < 4.0 and z0 < 0.3 and z1 < 0.3 and a.branch_s < a.merge_s
        R.check("%s branches and reconnects tangentially" % a.id, ok, branch_main_m=round(a.branch_s, 1),
                merge_main_m=round(a.merge_s, 1), pos_err_m=[round(e0, 2), round(e1, 2)],
                heading_err_deg=[round(h0, 2), round(h1, 2)], z_err_m=[round(z0, 3), round(z1, 3)])

    # --- checkpoints ----------------------------------------------------------
    gs = [g["s"] for g in m.gates]
    R.check("Main gates strictly ordered 1..18", [g["group"] for g in m.gates] == list(range(1, 19))
            and all(b > a for a, b in zip(gs, gs[1:])), stations=[round(s, 1) for s in gs])
    for a in net.alts:
        need = [g["group"] for g in m.gates if a.branch_s < g["s"] < a.merge_s]
        have = [g["group"] for g in a.gates]
        orderd = all(y > x for x, y in zip([g["s"] for g in a.gates], [g["s"] for g in a.gates][1:]))
        sep = []
        for g in a.gates:
            p = a.point(g["s"])
            sn, dn = routes._nearest_on(m, np.array([p[0]]), np.array([p[1]]))
            sep.append(round(float(abs(dn[0]) - m.interp("width", sn[0]) / 2), 1))
        R.check("%s carries equivalent gates for every bypassed group" % a.id, need == have and orderd,
                bypassed=need, equivalent=have, clearance_from_main_piste_m=sep)

    # --- corridor surface / collision accuracy -----------------------------
    if col is not None:
        rng = np.random.default_rng(5)
        errs_p, errs_o = [], []
        for rid, strips in col["strips"].items():
            for rows in strips:
                for a in range(len(rows) - 1):
                    A, B = rows[a]["pts"], rows[a + 1]["pts"]
                    for c in range(len(A) - 1):
                        for _ in range(2):
                            u, v = rng.uniform(), rng.uniform()
                            if u + v > 1:
                                u, v = 1 - u, 1 - v
                            tri = (A[c], B[c], B[c + 1]) if rng.uniform() < 0.5 else (A[c], B[c + 1], A[c + 1])
                            p = tri[0] + u * (tri[1] - tri[0]) + v * (tri[2] - tri[0])
                            if rows[a]["surface"] == routes.SURF_GROUND:
                                zt = float(T.height(p[0], p[1]))
                            else:
                                continue
                            e = abs(zt - p[2])
                            (errs_p if rows[a]["kinds"][c] == "Piste" else errs_o).append(e)
        ep = np.array(errs_p)
        eo = np.array(errs_o)
        R.metric("collision_vs_surface_piste_m", dict(mean=round(float(ep.mean()), 3), p99=round(float(np.percentile(ep, 99)), 3),
                                                      max=round(float(ep.max()), 3), samples=len(ep)))
        R.metric("collision_vs_surface_offpiste_m", dict(mean=round(float(eo.mean()), 3), p99=round(float(np.percentile(eo, 99)), 3),
                                                         max=round(float(eo.max()), 3), samples=len(eo)))
        R.check("Collision matches the visual piste surface (p99 <= 0.12 m)", np.percentile(ep, 99) <= 0.12,
                p99_m=round(float(np.percentile(ep, 99)), 3), max_m=round(float(ep.max()), 3))
        # continuity: consecutive strips share their boundary station; every
        # lateral position present in both layouts must coincide (layouts
        # differ between ground / bridge / tunnel and simple / detailed rows)
        gaps = []
        for rid, strips in col["strips"].items():
            for s1, s2 in zip(strips, strips[1:]):
                ra, rb = s1[-1], s2[0]
                if abs(ra["s"] - rb["s"]) > 1e-3:
                    gaps.append(9.9)
                    continue
                oa, ob = np.asarray(ra["offs"]), np.asarray(rb["offs"])
                for i, o in enumerate(oa):
                    j = np.where(np.abs(ob - o) < 1e-4)[0]
                    if len(j):
                        gaps.append(float(np.linalg.norm(ra["pts"][i] - rb["pts"][j[0]])))
        R.check("Collision strips are continuous (no seams > 2 cm)", (max(gaps) if gaps else 0.0) <= 0.02,
                max_seam_m=round(max(gaps) if gaps else 0.0, 4), seams_checked=len(gaps))
        R.metric("collision_wedges", colmod.wedge_count(col))
        R.metric("collision_boxes", len(col["boxes"]) + len(col["catch"]))
        # catch floors must sit above Roblox's default FallenPartsDestroyHeight
        lowest = min(c["center"][2] - c["size"][1] / 2 for c in col["catch"])
        lowest_studs = lowest * config.STUDS_PER_METER
        R.metric("lowest_catch_floor_studs", round(lowest_studs, 1))
        R.check("Catch floors above FallenPartsDestroyHeight (-500 studs)", lowest_studs > -480.0,
                lowest_catch_floor_studs=round(lowest_studs, 1))

    # --- bridge -------------------------------------------------------------
    bm = ctx.markers.get("bridge")
    if bm:
        s0, s1 = bm["span"]
        ends = []
        for s in (s0 - 1.0, s1 + 1.0):
            p = m.point(s)
            ends.append(abs(float(T.height(p[0], p[1]) - m.interp("z", s))))
        mids = []
        for s in np.linspace(s0 + 5, s1 - 5, 9):
            p = m.point(s)
            mids.append(float(m.interp("z", s) - T.height(p[0], p[1])))
        R.check("Bridge deck meets both abutments (gap < 0.25 m)", max(ends) < 0.25, abutment_gap_m=_round(ends, 3))
        R.check("Bridge spans a real ravine (clearance > 15 m)", max(mids) > 15.0,
                max_clearance_m=round(max(mids), 1), deck_width_m=bm["deck_width"],
                span_m=round(s1 - s0, 1), arches=len(bm["arches"]))
    # --- ice cave -----------------------------------------------------------
    cm = ctx.markers.get("cave")
    if cm:
        t0, t1 = cm["span"]
        cover = []
        for s in np.linspace(t0 + 8, t1 - 8, 12):
            p = m.point(s)
            cover.append(float(T.height(p[0], p[1]) - (m.interp("z", s) + cm["height"])))
        width = 2 * cm["inner_half_width"]
        R.check("Ice cave: rock cover above the ceiling everywhere", min(cover) > 0.5,
                min_cover_m=round(min(cover), 2), tunnel_length_m=round(t1 - t0, 1))
        R.check("Ice cave clearance (height >= 10 m, width >= piste + 4 m)",
                cm["height"] >= 10.0 and width >= float(m.interp("width", t0)) + 4.0,
                height_m=cm["height"], inner_width_m=round(width, 1), lights=len(cm["lights"]))

    # --- placements -----------------------------------------------------------
    inst = ctx.instances
    floating = []
    in_corr = []
    for rec in inst:
        x, y, z = rec["loc"]
        if not T.inside_detail(x, y):
            continue
        cat = rec["category"]
        if cat == "Forest":
            ce = float(T.corridor_dist(x, y))          # trunk position
        elif cat in ("Rocks", "Buildings"):
            fp = footprint_xy(ctx.template_info[rec["asset"]]["bounds"], x, y, rec["yaw"], rec["scale"],
                              FOOTPRINT_SHRINK[cat])
            ce = float(np.min(T.corridor_dist(fp[:, 0], fp[:, 1])))
        else:
            ce = 1e3
        if ce < 0.0:
            in_corr.append((rec["asset"], round(ce, 2)))
        if cat in ("Forest", "Rocks", "Buildings", "Gondola") and not rec.get("animated"):
            g = float(T.height(x, y))
            # a building stands on its stone base (template bottom), which may be
            # raised on a terrace; everything else stands on its origin
            zb = z + ctx.template_info[rec["asset"]]["bounds"][0][2] if cat == "Buildings" else z
            if zb - g > 0.35:
                floating.append((rec["asset"], round(zb - g, 2)))
    R.check("No trees / rocks / buildings inside rideable corridors (rock + building footprints checked)",
            len(in_corr) == 0, violations=len(in_corr), examples=sorted(in_corr, key=lambda v: v[1])[:10])
    R.check("No floating objects (base above ground > 0.35 m)", len(floating) == 0,
            violations=len(floating), examples=floating[:8])
    b_issues = []
    for rec in inst:
        if rec["category"] != "Buildings":
            continue
        lo, hi = ctx.template_info[rec["asset"]]["bounds"]
        x, y, z = rec["loc"]
        c, s = math.cos(rec["yaw"]), math.sin(rec["yaw"])
        corners = []
        for px in (lo[0], hi[0]):
            for py in (lo[1], hi[1]):
                corners.append((x + c * px - s * py, y + s * px + c * py))
        gz = [float(T.height(a, b)) for a, b in corners]
        # the stone base reaches down to the template's lowest point (lo[2]);
        # its bottom must not hover above the lowest footprint corner
        b_issues.append((round(max(0.0, (z + lo[2]) - min(gz)), 2), rec["asset"]))
    worst_b = max(b_issues) if b_issues else (0.0, "-")
    R.check("Buildings sit on the ground (stone base reaches the lowest footprint corner)", worst_b[0] <= 0.05,
            worst_base_gap_m=worst_b[0], worst_building=worst_b[1], buildings=len(b_issues))
    # kickers
    for kk in ctx.markers.get("kickers", []):
        r = net.route(kk["route"])
        s = kk["s"]
        before = float(r.interp("grad", s - 10))
        after = float(r.interp("grad", s + 25))
        clear = float(r.interp("width", s + 25)) > 20
        R.check("Kicker at %s s=%.0f has a landing (gradient after >= before - 2%%, corridor clear)" % (kk["route"], s),
                after >= before - 0.02 and clear, grad_before_pct=round(100 * before, 1), grad_landing_pct=round(100 * after, 1))
    # gondola clearance
    for ln in ctx.markers.get("gondolas", []):
        pts = np.asarray(ln["loop"]["points"])
        gz = T.height(pts[:, 0], pts[:, 1])
        clearance = pts[:, 2] - gz
        # ignore points inside stations (cable runs into the building)
        st = np.asarray([s["xy"] for s in ln["stations"]])
        dist = np.min(np.hypot(pts[:, 0:1] - st[None, :, 0], pts[:, 1:2] - st[None, :, 1]), axis=1)
        clr = clearance[dist > 30.0]
        R.check("Gondola %s cable clearance >= 10 m between stations" % ln["id"], float(clr.min()) >= 10.0,
                min_clearance_m=round(float(clr.min()), 1), pylons=len(ln["pylons"]), cabins=ln["cabins"],
                loop_m=round(ln["loop"]["length"], 0))

    # --- Roblox limits -----------------------------------------------------
    if manifest is not None:
        worst_tris, worst_size = 0, 0.0
        over = []
        for u in manifest["unique"]:
            worst_tris = max(worst_tris, u["tris"])
            worst_size = max(worst_size, max(u["size"]))
            if u["tris"] > config.ROBLOX_MAX_TRIS or max(u["size"]) > config.ROBLOX_MAX_PART_STUDS:
                over.append(u["mesh"])
        for name, t in manifest["templates"].items():
            for p in t["parts"]:
                worst_tris = max(worst_tris, p["tris"])
                worst_size = max(worst_size, max(p["size"]))
                if p["tris"] > config.ROBLOX_MAX_TRIS or max(p["size"]) > config.ROBLOX_MAX_PART_STUDS:
                    over.append(p["mesh"])
        R.check("Every mesh within Roblox limits (<= 20k tris, <= 2048 studs per axis)", not over,
                worst_tris=worst_tris, worst_extent_studs=round(worst_size, 1), violations=over[:10])
        missing = [i for i in manifest["instances"] if manifest["assets"][i[0]] not in manifest["templates"]]
        R.check("Every placement references an exported template", not missing, instances=len(manifest["instances"]))
        R.metric("mesh_counts", dict(templates=len(manifest["templates"]),
                                     template_parts=sum(len(t["parts"]) for t in manifest["templates"].values()),
                                     unique_meshes=len(manifest["unique"]), instances=len(manifest["instances"])))
        tri_by_cat = {}
        for u in manifest["unique"]:
            tri_by_cat[u["category"]] = tri_by_cat.get(u["category"], 0) + u["tris"]
        inst_tris = {}
        for i in manifest["instances"]:
            name = manifest["assets"][i[0]]
            cat = manifest["templates"][name]["category"]
            inst_tris[cat] = inst_tris.get(cat, 0) + manifest["templates"][name]["tris"]
        R.metric("triangles_unique_by_category", tri_by_cat)
        R.metric("triangles_instanced_by_category", inst_tris)
    if checkpoints is not None:
        R.metric("checkpoint_groups", checkpoints["group_count"])
        R.metric("checkpoint_gates", sum(len(g["gates"]) for g in checkpoints["groups"]))
        R.check("18 checkpoint groups, group 18 = finish", checkpoints["group_count"] == 18 and any(
            g["is_finish"] for g in checkpoints["groups"][-1]["gates"]), groups=checkpoints["group_count"])
        R.check("16 spawn points behind the start line", len(checkpoints["spawns"]) == 16, spawns=len(checkpoints["spawns"]))
    return R


def write(R, ctx):
    data = dict(passed=R.passed, total=len(R.checks), metrics=_round(R.metrics, 3), checks=_round(R.checks, 3))
    os.makedirs(config.METADATA_DIR, exist_ok=True)
    with open(os.path.join(config.METADATA_DIR, "ValidationReport.json"), "w") as f:
        json.dump(data, f, indent=1)
    lines = ["# Snowy Valley - Validation Report", "",
             "Generated by GenerateSnowyValley.py (measured values, not targets).", "",
             "**%d / %d checks passed**" % (R.passed, len(R.checks)), "",
             "## Key measurements", ""]
    mt = R.metrics
    for k in ("main_length_m", "main_length_studs", "elevation_drop_m", "elevation_drop_studs",
              "main_meaningful_bends", "collision_wedges", "collision_boxes", "lowest_catch_floor_studs",
              "checkpoint_groups", "checkpoint_gates"):
        if k in mt:
            lines.append("- **%s**: %s" % (k, mt[k]))
    for k in ("collision_vs_surface_piste_m", "collision_vs_surface_offpiste_m", "mesh_counts",
              "triangles_unique_by_category", "triangles_instanced_by_category"):
        if k in mt:
            lines.append("- **%s**: `%s`" % (k, json.dumps(mt[k])))
    lines += ["", "## Sections (main route)", "",
              "| # | Section | Length m | Drop m | Avg % | Max % | Min radius m | Width m | Bends |",
              "|---|---|---|---|---|---|---|---|---|"]
    for s in mt.get("sections", []):
        lines.append("| %02d | %s | %.0f | %.1f | %.1f | %.1f | %.1f | %s | %d |" % (
            s["id"], s["name"], s["length_m"], s["drop_m"], s["avg_grad_pct"], s["max_grad_pct"],
            s["min_radius_m"], s["width_m"], s["bends"]))
    lines += ["", "## Routes", "", "| Route | Difficulty | Length m | Avg % | Max % | Min radius m | Min width m |",
              "|---|---|---|---|---|---|---|"]
    for r in mt.get("routes", []):
        lines.append("| %s | %s | %.0f | %.1f | %.1f | %.1f | %.1f |" % (
            r["id"], r["difficulty"], r["length_m"], r["avg_grad_pct"], r["max_grad_pct"], r["min_radius_m"], r["min_width_m"]))
    lines += ["", "## Checks", ""]
    for c in R.checks:
        lines.append("- %s **%s** - `%s`" % ("PASS" if c["passed"] else "FAIL", c["name"],
                                             json.dumps(_round(c["details"], 3))[:400]))
    with open(os.path.join(config.METADATA_DIR, "ValidationReport.md"), "w") as f:
        f.write("\n".join(lines) + "\n")
    ctx.log("validation: %d / %d checks passed" % (R.passed, len(R.checks)))
    for c in R.checks:
        if not c["passed"]:
            ctx.log("  FAIL %s %s" % (c["name"], json.dumps(_round(c["details"], 3))[:300]))
