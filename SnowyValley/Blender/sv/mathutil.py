"""Numerical helpers shared by all generator stages (pure numpy).

Contents
--------
* deterministic gradient noise (Perlin) + fBm / ridged variants
* curvature-controlled path integration ("turtle" primitives) with smoothing
* polyline utilities (arc length, resampling, tangents, curvature)
* bilinear / bicubic grid samplers
"""

import math

import numpy as np


# ---------------------------------------------------------------------------
# scalar helpers
# ---------------------------------------------------------------------------

def clamp(v, lo, hi):
    return np.minimum(np.maximum(v, lo), hi)


def lerp(a, b, t):
    return a + (b - a) * t


def smoothstep(e0, e1, x):
    t = clamp((np.asarray(x, dtype=float) - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def smootherstep(e0, e1, x):
    t = clamp((np.asarray(x, dtype=float) - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def wrap_angle(a):
    return (a + math.pi) % (2.0 * math.pi) - math.pi


# ---------------------------------------------------------------------------
# noise
# ---------------------------------------------------------------------------

class Perlin2D:
    """Vectorised 2D gradient noise, output roughly in [-1, 1]."""

    def __init__(self, seed):
        rng = np.random.default_rng(seed)
        p = rng.permutation(256).astype(np.int64)
        self.perm = np.concatenate([p, p])
        ang = rng.uniform(0.0, 2.0 * math.pi, 256)
        self.gx = np.cos(ang)
        self.gy = np.sin(ang)

    def _grad(self, ix, iy, dx, dy):
        h = self.perm[self.perm[ix] + iy]
        return self.gx[h] * dx + self.gy[h] * dy

    def __call__(self, x, y):
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        xf0 = np.floor(x)
        yf0 = np.floor(y)
        xi = xf0.astype(np.int64) & 255
        yi = yf0.astype(np.int64) & 255
        xf = x - xf0
        yf = y - yf0
        xi1 = (xi + 1) & 255
        yi1 = (yi + 1) & 255
        n00 = self._grad(xi, yi, xf, yf)
        n10 = self._grad(xi1, yi, xf - 1.0, yf)
        n01 = self._grad(xi, yi1, xf, yf - 1.0)
        n11 = self._grad(xi1, yi1, xf - 1.0, yf - 1.0)
        u = xf * xf * xf * (xf * (xf * 6.0 - 15.0) + 10.0)
        v = yf * yf * yf * (yf * (yf * 6.0 - 15.0) + 10.0)
        return (lerp(lerp(n00, n10, u), lerp(n01, n11, u), v)) * 1.41421356


class NoiseBank:
    """A set of independent noise generators derived from one seed."""

    def __init__(self, seed):
        self.seed = seed
        self._cache = {}

    def get(self, name):
        if name not in self._cache:
            h = 0
            for ch in name:
                h = (h * 131 + ord(ch)) % 1000003
            self._cache[name] = Perlin2D(self.seed * 7919 + h)
        return self._cache[name]

    def fbm(self, name, x, y, scale, octaves=5, lacunarity=2.0, gain=0.5):
        n = self.get(name)
        amp = 1.0
        freq = 1.0 / scale
        total = np.zeros(np.broadcast(np.asarray(x), np.asarray(y)).shape)
        norm = 0.0
        for o in range(octaves):
            total = total + amp * n(x * freq + o * 17.31, y * freq - o * 9.73)
            norm += amp
            amp *= gain
            freq *= lacunarity
        return total / norm

    def ridged(self, name, x, y, scale, octaves=5, lacunarity=2.05, gain=0.5):
        """Ridged multifractal in [0, 1]; sharp crests like mountain ridges."""
        n = self.get(name)
        amp = 1.0
        freq = 1.0 / scale
        total = np.zeros(np.broadcast(np.asarray(x), np.asarray(y)).shape)
        norm = 0.0
        weight = np.ones_like(total)
        for o in range(octaves):
            v = 1.0 - np.abs(n(x * freq + o * 31.7, y * freq + o * 11.3))
            v = v * v * weight
            weight = clamp(v * 1.6, 0.0, 1.0)
            total = total + amp * v
            norm += amp
            amp *= gain
            freq *= lacunarity
        return total / norm


# ---------------------------------------------------------------------------
# curvature-controlled path integration
# ---------------------------------------------------------------------------

def primitives_to_curvature(prims, ds):
    """Convert turtle primitives into a sampled curvature function.

    Primitives:
        ("S", length)                 straight
        ("A", angle_deg, radius)      circular arc, +angle = left turn
        ("K", length, kappa)          explicit constant curvature
    Returns kappa samples (len n) with spacing ds and the total length.
    """
    kap = []
    for p in prims:
        kind = p[0]
        if kind == "S":
            n = max(1, int(round(p[1] / ds)))
            kap.extend([0.0] * n)
        elif kind == "A":
            ang = math.radians(p[1])
            r = float(p[2])
            length = abs(ang) * r
            n = max(1, int(round(length / ds)))
            k = (ang / length) if length > 0 else 0.0
            kap.extend([k] * n)
        elif kind == "K":
            n = max(1, int(round(p[1] / ds)))
            kap.extend([float(p[2])] * n)
        else:
            raise ValueError("unknown primitive %r" % (p,))
    kap = np.asarray(kap, dtype=float)
    return kap, len(kap) * ds


def gaussian_kernel(sigma_samples):
    if sigma_samples <= 0:
        return np.array([1.0])
    half = int(math.ceil(3.0 * sigma_samples))
    t = np.arange(-half, half + 1, dtype=float)
    k = np.exp(-0.5 * (t / sigma_samples) ** 2)
    return k / k.sum()


def smooth1d(arr, sigma_samples, mode="edge"):
    """Gaussian smoothing that preserves the integral for zero-padded mode."""
    arr = np.asarray(arr, dtype=float)
    k = gaussian_kernel(sigma_samples)
    if len(k) == 1:
        return arr.copy()
    half = len(k) // 2
    if mode == "zero":
        padded = np.concatenate([np.zeros(half), arr, np.zeros(half)])
    else:
        padded = np.pad(arr, half, mode="edge")
    return np.convolve(padded, k, mode="valid")


def integrate_path(kappa, ds, x0, y0, heading0):
    """Integrate curvature samples into a planar path.

    Returns arrays of length n+1: x, y, heading (radians, CCW from +X).
    Heading is integrated with the midpoint rule which keeps the turtle
    exact for constant curvature.
    """
    n = len(kappa)
    heading = np.empty(n + 1)
    heading[0] = heading0
    heading[1:] = heading0 + np.cumsum(kappa) * ds
    mid = 0.5 * (heading[:-1] + heading[1:])
    x = np.empty(n + 1)
    y = np.empty(n + 1)
    x[0] = x0
    y[0] = y0
    x[1:] = x0 + np.cumsum(np.cos(mid)) * ds
    y[1:] = y0 + np.cumsum(np.sin(mid)) * ds
    return x, y, heading


# ---------------------------------------------------------------------------
# polyline helpers
# ---------------------------------------------------------------------------

def cumulative_length(pts):
    d = np.diff(pts, axis=0)
    seg = np.sqrt((d ** 2).sum(axis=1))
    return np.concatenate([[0.0], np.cumsum(seg)])


def resample_polyline(pts, spacing):
    """Resample an (n, k) polyline at (approximately) uniform arc length."""
    s = cumulative_length(pts[:, :2])
    total = s[-1]
    n = max(2, int(math.ceil(total / spacing)) + 1)
    t = np.linspace(0.0, total, n)
    out = np.empty((n, pts.shape[1]))
    for c in range(pts.shape[1]):
        out[:, c] = np.interp(t, s, pts[:, c])
    return out, t


def polyline_tangents(pts):
    t = np.gradient(pts[:, :2], axis=0)
    ln = np.linalg.norm(t, axis=1, keepdims=True)
    ln[ln == 0] = 1.0
    return t / ln


def signed_curvature_from_heading(heading, ds):
    dh = np.diff(np.unwrap(heading)) / ds
    return np.concatenate([dh[:1], dh])


def seg_intersect_2d(p1, p2, q1, q2):
    """True if segment p1p2 strictly intersects q1q2 (2D)."""
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    o1 = orient(p1, p2, q1)
    o2 = orient(p1, p2, q2)
    o3 = orient(q1, q2, p1)
    o4 = orient(q1, q2, p2)
    return (o1 * o2 < 0) and (o3 * o4 < 0)


# ---------------------------------------------------------------------------
# grid samplers
# ---------------------------------------------------------------------------

class Grid2D:
    """Regular grid of values. data[j, i] at (x0 + i*res, y0 + j*res)."""

    def __init__(self, data, x0, y0, res):
        self.data = np.asarray(data, dtype=float)
        self.x0 = float(x0)
        self.y0 = float(y0)
        self.res = float(res)
        self.ny, self.nx = self.data.shape

    @property
    def x1(self):
        return self.x0 + (self.nx - 1) * self.res

    @property
    def y1(self):
        return self.y0 + (self.ny - 1) * self.res

    def coords(self):
        xs = self.x0 + np.arange(self.nx) * self.res
        ys = self.y0 + np.arange(self.ny) * self.res
        return xs, ys

    def bilinear(self, x, y):
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        fx = clamp((x - self.x0) / self.res, 0.0, self.nx - 1.000001)
        fy = clamp((y - self.y0) / self.res, 0.0, self.ny - 1.000001)
        i = np.floor(fx).astype(np.int64)
        j = np.floor(fy).astype(np.int64)
        tx = fx - i
        ty = fy - j
        d = self.data
        a = d[j, i] * (1 - tx) + d[j, i + 1] * tx
        b = d[j + 1, i] * (1 - tx) + d[j + 1, i + 1] * tx
        return a * (1 - ty) + b * ty

    def bicubic(self, x, y):
        """Catmull-Rom bicubic interpolation (C1 continuous)."""
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        fx = clamp((x - self.x0) / self.res, 0.0, self.nx - 1.000001)
        fy = clamp((y - self.y0) / self.res, 0.0, self.ny - 1.000001)
        i = np.floor(fx).astype(np.int64)
        j = np.floor(fy).astype(np.int64)
        tx = fx - i
        ty = fy - j

        def w(t):
            t2 = t * t
            t3 = t2 * t
            return (
                -0.5 * t3 + t2 - 0.5 * t,
                1.5 * t3 - 2.5 * t2 + 1.0,
                -1.5 * t3 + 2.0 * t2 + 0.5 * t,
                0.5 * t3 - 0.5 * t2,
            )

        wx = w(tx)
        wy = w(ty)
        d = self.data
        out = np.zeros_like(tx)
        for m in range(4):
            jj = np.clip(j + m - 1, 0, self.ny - 1)
            row = np.zeros_like(tx)
            for k in range(4):
                ii = np.clip(i + k - 1, 0, self.nx - 1)
                row = row + wx[k] * d[jj, ii]
            out = out + wy[m] * row
        return out

    def gradient(self, x, y, h=None):
        h = h or self.res * 0.5
        gx = (self.bicubic(x + h, y) - self.bicubic(x - h, y)) / (2 * h)
        gy = (self.bicubic(x, y + h) - self.bicubic(x, y - h)) / (2 * h)
        return gx, gy


def upsample_bicubic(grid, new_res, x0=None, y0=None, x1=None, y1=None):
    x0 = grid.x0 if x0 is None else x0
    y0 = grid.y0 if y0 is None else y0
    x1 = grid.x1 if x1 is None else x1
    y1 = grid.y1 if y1 is None else y1
    nx = int(round((x1 - x0) / new_res)) + 1
    ny = int(round((y1 - y0) / new_res)) + 1
    xs = x0 + np.arange(nx) * new_res
    ys = y0 + np.arange(ny) * new_res
    X, Y = np.meshgrid(xs, ys)
    return Grid2D(grid.bicubic(X, Y), x0, y0, new_res)


def box_blur2d(a, radius):
    """Separable box blur with edge padding (radius in cells)."""
    if radius <= 0:
        return a.copy()
    k = 2 * radius + 1
    p = np.pad(a, radius, mode="edge")
    c = np.cumsum(p, axis=0)
    c = np.vstack([np.zeros((1, c.shape[1])), c])
    v = (c[k:, :] - c[:-k, :]) / k
    c2 = np.cumsum(v, axis=1)
    c2 = np.hstack([np.zeros((c2.shape[0], 1)), c2])
    return (c2[:, k:] - c2[:, :-k]) / k


def footprint_xy(bounds, x, y, yaw, scale=1.0, shrink=1.0):
    """World XY samples (corners, edge midpoints, centre) of an asset's
    rotated/scaled bounding-box footprint. bounds = (lo, hi) in local m."""
    lo, hi = bounds
    c, s = math.cos(yaw), math.sin(yaw)
    cx, cy = 0.5 * (lo[0] + hi[0]), 0.5 * (lo[1] + hi[1])
    hx, hy = 0.5 * (hi[0] - lo[0]) * shrink, 0.5 * (hi[1] - lo[1]) * shrink
    pts = []
    for u in (-1.0, 0.0, 1.0):
        for v in (-1.0, 0.0, 1.0):
            px = (cx + u * hx) * scale
            py = (cy + v * hy) * scale
            pts.append((x + c * px - s * py, y + s * px + c * py))
    return np.asarray(pts)
