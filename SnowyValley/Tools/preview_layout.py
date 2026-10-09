"""Top-down preview of the route network (no Blender required).

Usage:  python3 Tools/preview_layout.py [out.png] [--terrain]
"""

import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "Blender"))

from sv import config, routes  # noqa: E402

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def main():
    out = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else \
        os.path.join(config.PREVIEW_DIR, "layout_topdown.png")
    with_terrain = "--terrain" in sys.argv
    net = routes.Network()
    print(routes.summarize(net))

    x0, x1 = config.DETAIL_MIN_X, config.DETAIL_MAX_X
    y0, y1 = config.DETAIL_MIN_Y, config.DETAIL_MAX_Y
    sc = 0.42
    W = int((x1 - x0) * sc)
    H = int((y1 - y0) * sc)

    def P(x, y):
        return ((x - x0) * sc, (y1 - y) * sc)

    if with_terrain:
        from sv import terrain
        T = terrain.build_terrain(net, quick=True)
        xs = np.linspace(x0, x1, W)
        ys = np.linspace(y1, y0, H)
        X, Y = np.meshgrid(xs, ys)
        Z = T.height(X, Y)
        gx, gy = np.gradient(Z, (x1 - x0) / W, (y0 - y1) / H)
        nrm = np.sqrt(1 + gx ** 2 + gy ** 2)
        shade = np.clip(0.62 + 0.55 * (-gx * 0.55 + gy * 0.55 + 0.35) / nrm - 0.2, 0.25, 1.15)
        slope = np.degrees(np.arctan(np.sqrt(gx ** 2 + gy ** 2)))
        snow = np.array([236, 242, 250], dtype=float)
        rock = np.array([118, 116, 122], dtype=float)
        m = np.clip((slope - 34) / 8, 0, 1)[..., None]
        col = snow * (1 - m) + rock * m
        col = col * shade[..., None]
        print("slope stats: p50 %.1f p90 %.1f rock>38deg %.1f%%" % (
            np.percentile(slope, 50), np.percentile(slope, 90), 100 * (slope > 38).mean()))
        img = Image.fromarray(np.clip(col, 0, 255).astype(np.uint8))
        d = ImageDraw.Draw(img)
        # contour lines every 50 m
        for lvl in range(-100, 1400, 100):
            mask = (Z[:-1, :] < lvl) != (Z[1:, :] < lvl)
            yy, xx = np.nonzero(mask)
            for a, b in zip(xx[::1], yy[::1]):
                img.putpixel((int(a), int(b)), (90, 100, 120))
    else:
        img = Image.new("RGB", (W, H), (236, 241, 247))
        d = ImageDraw.Draw(img)
        for gxv in range(int(x0 // 100) * 100, int(x1), 100):
            d.line([P(gxv, y0), P(gxv, y1)], fill=(215, 222, 232))
        for gyv in range(int(y0 // 100) * 100, int(y1), 100):
            d.line([P(x0, gyv), P(x1, gyv)], fill=(215, 222, 232))
    font = ImageFont.truetype(FONT, 13)
    small = ImageFont.truetype(FONT, 10)

    cols = {"blue": (40, 110, 225), "green": (40, 170, 70), "red": (215, 45, 45), "black": (20, 20, 24)}
    for r in net.routes:
        col = cols[r.difficulty]
        step = 3
        # corridor (piste width)
        for i in range(0, len(r.s) - step, step):
            w = max(1, int(r.width[i] * sc))
            d.line([P(r.x[i], r.y[i]), P(r.x[i + step], r.y[i + step])],
                   fill=tuple(int(c * 0.45 + 255 * 0.55) for c in col), width=w)
        for i in range(0, len(r.s) - step, step):
            c = col
            if r.surface[i] == routes.SURF_BRIDGE:
                c = (120, 70, 30)
            elif r.surface[i] == routes.SURF_TUNNEL:
                c = (0, 200, 230)
            d.line([P(r.x[i], r.y[i]), P(r.x[i + step], r.y[i + step])], fill=c, width=2)
        for g in r.gates:
            i = r.index_at(g["s"])
            hx, hy = math.cos(r.heading[i]), math.sin(r.heading[i])
            half = r.width[i] / 2 + 6
            a = (r.x[i] + hy * half, r.y[i] - hx * half)
            b = (r.x[i] - hy * half, r.y[i] + hx * half)
            d.line([P(*a), P(*b)], fill=(0, 0, 0), width=2)
            tag = "%d%s" % (g["group"], "" if r.id == "MAIN" else r.id[0])
            d.text(P(r.x[i] + hy * (half + 8), r.y[i] - hx * (half + 8)), tag, fill=(0, 0, 0), font=small)
    m = net.main
    for sec in m.sections:
        i = m.index_at(sec["s0"] + 0.5 * (sec["s1"] - sec["s0"]))
        px, py = P(m.x[i], m.y[i])
        d.ellipse([px - 9, py - 9, px + 9, py + 9], fill=(255, 255, 255), outline=(20, 20, 20))
        d.text((px - 7 if sec["id"] > 9 else px - 4, py - 7), str(sec["id"]), fill=(0, 0, 0), font=font)
    for r in net.alts:
        i = len(r.s) // 2
        d.text(P(r.x[i] + 15, r.y[i]), r.id, fill=cols[r.difficulty], font=font)
    d.text((10, 10), "Snowy Valley layout  main=%.0f m  drop=%.0f m" % (
        m.race_end_s, m.z[0] - m.interp("z", m.race_end_s)), fill=(0, 0, 0), font=font)
    # scale bar
    d.line([(10, H - 20), (10 + 200 * sc, H - 20)], fill=(0, 0, 0), width=3)
    d.text((10, H - 38), "200 m", fill=(0, 0, 0), font=small)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    img.save(out)
    print("wrote", out)


if __name__ == "__main__":
    main()
