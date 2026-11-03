#!/usr/bin/env python3
"""
shapes_v9.py – ASCII 3D Shape Renderer

v9.1 (2026-07)
    - NumPy-vectorized rotation, projection, line rasterization
    - Pixel deduplication: only closest-z pixel per screen position is written
    - Vectorized edge generation (no Python loops for torus/mobius/klein edges)
    - Stable sub-menus (ANSI cursor positioning, no cls flicker)
    - Resolution picker sub-menu
    - Depth range parameter (z/Z keys) for color contrast control
    - 14 depth palettes
    - FPS target with adaptive density throttling
    - All v8 features preserved
"""

import math
import os
import random
import shutil
import sys
import time
import threading
from collections import deque
from typing import List, Tuple, Callable, Optional

HAS_AUDIO = False
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import sounddevice as sd
    if HAS_NUMPY:
        HAS_AUDIO = True
except ImportError:
    pass

if not HAS_NUMPY:
    print("shapes_v9 requires numpy: pip install numpy")
    sys.exit(1)

CLEAR_CMD = "cls" if os.name == "nt" else "clear"
COLOR_RESET = "\033[0m"

SHAPE_COLORS = [
    "\033[38;5;45m",
    "\033[38;5;214m",
    "\033[38;5;82m",
    "\033[38;5;201m",
    "\033[38;5;189m",
    "\033[38;5;160m",
]

DEPTH_PALETTES = [
    ("warm-cool",  [196, 202, 208, 214, 220, 226, 154, 82, 46, 49, 51, 45, 39, 33, 27, 21]),
    ("fire",       [16, 52, 88, 124, 160, 196, 202, 208, 214, 220, 226, 228]),
    ("ocean",      [16, 17, 18, 19, 20, 21, 27, 33, 39, 45, 51, 87, 123, 159]),
    ("neon",       [21, 57, 93, 129, 165, 201, 200, 199, 198, 197, 196]),
    ("matrix",     [16, 22, 28, 34, 40, 46, 82, 118, 154, 190, 226]),
    ("sunset",     [17, 18, 54, 90, 126, 162, 198, 204, 210, 216, 222, 228]),
    ("ice",        [16, 17, 18, 24, 30, 36, 37, 44, 45, 51, 123, 159, 195, 231]),
    ("lava",       [16, 52, 88, 124, 160, 196, 202, 208, 214, 220, 226, 231]),
    ("candy",      [201, 200, 199, 198, 197, 196, 202, 208, 214, 220, 226, 46, 47, 48, 49]),
    ("aurora",     [16, 17, 18, 19, 25, 31, 37, 43, 49, 48, 84, 120, 156, 192, 228]),
    ("synthwave",  [16, 17, 18, 54, 90, 126, 162, 198, 199, 205, 211, 217]),
    ("grayscale",  [232, 234, 236, 238, 240, 242, 244, 246, 248, 250, 252, 254, 255]),
    ("rainbow",    [196, 202, 208, 214, 226, 154, 82, 46, 49, 51, 45, 39, 33, 27, 21, 57, 93, 129, 165, 201]),
    ("toxic",      [16, 22, 28, 34, 40, 46, 47, 48, 49, 50, 51, 87, 123, 159, 195]),
]

BRIGHTNESS_RAMPS = [
    " .:-=+*#%@",
    " .oO@",
    " .:+*#",
]

COLOR_MODES = ["off", "shape", "depth", "rotate"]

RESOLUTION_PRESETS = [
    ("Auto",   None, None),
    ("Small",  80,   24),
    ("Medium", 120,  40),
    ("Large",  160,  50),
    ("XL",     200,  55),
]

TARGET_FPS = 30
FPS_FLOOR = 15

WIDTH = 120
HEIGHT = 40


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def terminal_size():
    size = shutil.get_terminal_size(fallback=(120, 40))
    return max(40, size.columns), max(10, size.lines - 1)


def fov_for_size(w, h):
    eff_w = w * 0.8
    eff_h = (h - 3) * 2.2
    return clamp(min(eff_w, eff_h) * 0.35, 2.0, 100.0)


def apply_resolution(preset_idx):
    global WIDTH, HEIGHT
    term_w, term_h = terminal_size()
    label, pw, ph = RESOLUTION_PRESETS[preset_idx]
    if pw is None:
        WIDTH, HEIGHT = term_w, term_h
    else:
        WIDTH = min(pw, term_w)
        HEIGHT = min(ph, term_h)
    config.fov.value = fov_for_size(WIDTH, HEIGHT)


# ── Pre-built escape code lookup ────────────────────

_COLOR_ESCAPE_CACHE = {}


def _color_escape(code):
    if code not in _COLOR_ESCAPE_CACHE:
        _COLOR_ESCAPE_CACHE[code] = f"\033[38;5;{code}m"
    return _COLOR_ESCAPE_CACHE[code]


def _build_palette_lut(palette, n=256):
    lut = []
    plen = len(palette)
    for i in range(n):
        z_norm = i / (n - 1)
        idx = int(z_norm * (plen - 1))
        lut.append(_color_escape(palette[idx]))
    return lut


_PALETTE_LUTS = {}


def _get_palette_lut(palette_idx):
    key = palette_idx % len(DEPTH_PALETTES)
    if key not in _PALETTE_LUTS:
        _, palette = DEPTH_PALETTES[key]
        _PALETTE_LUTS[key] = _build_palette_lut(palette)
    return _PALETTE_LUTS[key]


# ── Param system ──────────────────────────────────────

class Param:
    def __init__(self, name, value, lo, hi, step, fmt=".2f",
                 key_down=None, key_up=None, multiplicative=False):
        self.name = name
        self.value = value
        self.lo = lo
        self.hi = hi
        self.step = step
        self.fmt = fmt
        self.key_down = key_down
        self.key_up = key_up
        self.multiplicative = multiplicative

    def increase(self):
        if self.multiplicative:
            self.value = min(self.hi, self.value * self.step)
        else:
            self.value = min(self.hi, self.value + self.step)

    def decrease(self):
        if self.multiplicative:
            self.value = max(self.lo, self.value / self.step)
        else:
            self.value = max(self.lo, self.value - self.step)

    @property
    def at_min(self):
        if self.multiplicative:
            return self.value <= self.lo * 1.001
        return self.value <= self.lo + abs(self.step) * 0.01

    @property
    def at_max(self):
        if self.multiplicative:
            return self.value >= self.hi * 0.999
        return self.value >= self.hi - abs(self.step) * 0.01

    def display(self):
        if self.value == 0 and self.lo == 0:
            return f"{self.name}:OFF"
        val_str = f"{self.value:{self.fmt}}"
        tag = ""
        if self.at_min:
            tag = "[MIN]"
        elif self.at_max:
            tag = "[MAX]"
        return f"{self.name}:{val_str}{tag}"


class Config:
    def __init__(self, auto_fov=4.0):
        self.scale = Param("Scl", 1.0, 0.05, 5.0, 1.1, ".2f", "-", "+",
                           multiplicative=True)
        self.fov = Param("FOV", auto_fov, 0.5, 100.0, 0.5, ".1f", "f", "F")
        self.speed_x = Param("Spd", 0.06, 0.001, 0.5, 1.15, ".3f", "[", "]",
                             multiplicative=True)
        self.speed_y = Param("SpdY", 0.05, 0.001, 0.5, 1.15, ".3f", None, None,
                             multiplicative=True)
        self.density = Param("Den", 1.0, 0.25, 4.0, 1.2, ".2f", "d", "D",
                             multiplicative=True)
        self.auto_switch = Param("Auto", 6.0, 0.0, 60.0, 1.0, ".0f", "s", "S")
        self.depth_range = Param("DRng", 6.0, 1.0, 20.0, 0.5, ".1f", "z", "Z")

        self.shape_index = 0
        self.paused = False
        self.render_mode = "wire"
        self.brightness_enabled = True
        self.brightness_ramp_idx = 0
        self.color_mode_idx = 1
        self.depth_palette_idx = 0
        self.audio_reactive = False
        self.hud_visible = True
        self.resolution_idx = 0
        self.fps_adapt = True

        self.all_params = [self.scale, self.fov, self.speed_x, self.density,
                           self.auto_switch, self.depth_range]

    @property
    def color_mode(self):
        return COLOR_MODES[self.color_mode_idx % len(COLOR_MODES)]

    def handle_key(self, ch):
        for p in self.all_params:
            if p.key_up and ch == p.key_up:
                p.increase()
                if p is self.speed_x:
                    self.speed_y.increase()
                return True
            if p.key_down and ch == p.key_down:
                p.decrease()
                if p is self.speed_x:
                    self.speed_y.decrease()
                return True
        return False


config = Config()


# ── Z normalization ──────────────────────────────────

def z_normalize(z_vals):
    half = config.depth_range.value / 2.0
    return np.clip((z_vals + half) / config.depth_range.value, 0.0, 1.0)


def z_normalize_scalar(z):
    half = config.depth_range.value / 2.0
    return clamp((z + half) / config.depth_range.value, 0.0, 1.0)


# ── Vectorized rotation & projection ─────────────────

def make_rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64)


def make_rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float64)


def batch_rotate_project(verts_np, ax, ay):
    rot = make_rot_y(ay) @ make_rot_x(ax)
    rotated = verts_np @ rot.T
    zs = rotated[:, 2]
    denom = zs + 4.0
    denom = np.where(denom == 0, 1e-4, denom)
    f = config.fov.value / denom
    sc = config.scale.value
    xs = (rotated[:, 0] * f * sc + WIDTH // 2).astype(np.int32)
    ys = (-rotated[:, 1] * f * sc + HEIGHT // 2).astype(np.int32)
    return xs, ys, zs


# ── Flat vectorized line rasterization ───────────────

def rasterize_lines_flat(x1s, y1s, z1s, x2s, y2s, z2s):
    dx = np.abs(x2s - x1s)
    dy = np.abs(y2s - y1s)
    steps = np.maximum(dx, dy).astype(np.int64)
    steps = np.maximum(steps, 1)

    counts = steps + 1
    total = int(counts.sum())
    if total == 0:
        return np.empty(0, np.int32), np.empty(0, np.int32), np.empty(0, np.float64)

    offsets = np.empty(len(counts) + 1, dtype=np.int64)
    offsets[0] = 0
    np.cumsum(counts, out=offsets[1:])
    starts = offsets[:-1]

    rep_x1 = np.repeat(x1s.astype(np.float64), counts)
    rep_y1 = np.repeat(y1s.astype(np.float64), counts)
    rep_z1 = np.repeat(z1s, counts)
    rep_dx = np.repeat((x2s - x1s).astype(np.float64), counts)
    rep_dy = np.repeat((y2s - y1s).astype(np.float64), counts)
    rep_dz = np.repeat(z2s - z1s, counts)
    rep_steps = np.repeat(steps.astype(np.float64), counts)

    pixel_pos = np.arange(total, dtype=np.float64)
    group_offsets = np.repeat(starts.astype(np.float64), counts)
    within_group = pixel_pos - group_offsets
    t = within_group / rep_steps

    out_x = (rep_x1 + rep_dx * t).astype(np.int32)
    out_y = (rep_y1 + rep_dy * t).astype(np.int32)
    out_z = rep_z1 + rep_dz * t

    return out_x, out_y, out_z


# ── Screen buffer with z-buffer ──────────────────────

class ScreenBuffer:
    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.chars = [[" "] * w for _ in range(h)]
        self.colors = [[""] * w for _ in range(h)]
        self.zbuf = np.full((h, w), np.inf, dtype=np.float64)

    def clear(self):
        for r in range(self.h):
            cr = self.chars[r]
            co = self.colors[r]
            for c in range(self.w):
                cr[c] = " "
                co[c] = ""
        self.zbuf[:] = np.inf

    def put_text(self, x, y, text):
        for i, ch in enumerate(text):
            xi = x + i
            if 0 <= xi < self.w and 0 <= y < self.h:
                self.chars[y][xi] = ch
                self.colors[y][xi] = ""
                self.zbuf[y, xi] = -np.inf

    def draw_points(self, xs, ys, zs, ramp, color_lut, static_color):
        valid = (xs >= 0) & (xs < self.w) & (ys >= 0) & (ys < self.h)
        fx = xs[valid]
        fy = ys[valid]
        fz = zs[valid]
        if len(fx) == 0:
            return

        z_norm = z_normalize(fz)
        ramp_len = len(ramp)

        if config.brightness_enabled:
            ridx = ((1.0 - z_norm) * (ramp_len - 1)).astype(np.int32)
        else:
            ridx = np.full(len(fz), ramp_len - 1, dtype=np.int32)

        if color_lut is not None:
            cidx = (z_norm * 255).astype(np.int32)

        existing_z = self.zbuf[fy, fx]
        z_pass = fz <= existing_z
        idx = np.where(z_pass)[0]

        for i in idx:
            x, y, z = int(fx[i]), int(fy[i]), float(fz[i])
            ch = ramp[ridx[i]]
            if ch == " ":
                ch = "."
            self.chars[y][x] = ch
            if color_lut is not None:
                self.colors[y][x] = color_lut[cidx[i]]
            elif static_color:
                self.colors[y][x] = static_color
            else:
                self.colors[y][x] = ""
            self.zbuf[y, x] = z

    def draw_lines(self, x1s, y1s, z1s, x2s, y2s, z2s, ramp, color_lut, static_color):
        if len(x1s) == 0:
            return

        all_x, all_y, all_z = rasterize_lines_flat(x1s, y1s, z1s, x2s, y2s, z2s)
        if len(all_x) == 0:
            return

        valid = (all_x >= 0) & (all_x < self.w) & (all_y >= 0) & (all_y < self.h)
        fx = all_x[valid]
        fy = all_y[valid]
        fz = all_z[valid]
        if len(fx) == 0:
            return

        z_norm = z_normalize(fz)
        ramp_len = len(ramp)

        if config.brightness_enabled:
            ridx = ((1.0 - z_norm) * (ramp_len - 1)).astype(np.int32)
        else:
            ridx = np.full(len(fz), ramp_len - 1, dtype=np.int32)

        if color_lut is not None:
            cidx = (z_norm * 255).astype(np.int32)

        ramp_chars = list(ramp)

        lin = fy.astype(np.int64) * self.w + fx.astype(np.int64)

        sort_order = np.lexsort((fz, lin))
        sorted_lin = lin[sort_order]

        unique_mask = np.empty(len(sorted_lin), dtype=bool)
        unique_mask[0] = True
        unique_mask[1:] = sorted_lin[1:] != sorted_lin[:-1]
        deduped = sort_order[unique_mask]

        d_fx = fx[deduped]
        d_fy = fy[deduped]
        d_fz = fz[deduped]

        existing_z = self.zbuf[d_fy, d_fx]
        z_pass = d_fz <= existing_z
        winners = deduped[z_pass]

        w_fx = fx[winners]
        w_fy = fy[winners]
        w_fz = fz[winners]
        w_ridx = ridx[winners]

        self.zbuf[w_fy, w_fx] = w_fz

        if color_lut is not None:
            w_cidx = cidx[winners]
            for i in range(len(winners)):
                x, y = int(w_fx[i]), int(w_fy[i])
                ch = ramp_chars[w_ridx[i]]
                if ch == " ":
                    ch = "."
                self.chars[y][x] = ch
                self.colors[y][x] = color_lut[w_cidx[i]]
        elif static_color:
            for i in range(len(winners)):
                x, y = int(w_fx[i]), int(w_fy[i])
                ch = ramp_chars[w_ridx[i]]
                if ch == " ":
                    ch = "."
                self.chars[y][x] = ch
                self.colors[y][x] = static_color
        else:
            for i in range(len(winners)):
                x, y = int(w_fx[i]), int(w_fy[i])
                ch = ramp_chars[w_ridx[i]]
                if ch == " ":
                    ch = "."
                self.chars[y][x] = ch
                self.colors[y][x] = ""

    def render(self):
        parts = []
        prev_color = ""
        for r in range(self.h):
            row_chars = self.chars[r]
            row_colors = self.colors[r]
            for c in range(self.w):
                col = row_colors[c]
                if col != prev_color:
                    parts.append(col if col else COLOR_RESET)
                    prev_color = col
                parts.append(row_chars[c])
            if r < self.h - 1:
                parts.append("\n")
        if prev_color:
            parts.append(COLOR_RESET)
        return "".join(parts)


# ── Geometry cache ───────────────────────────────────

_geo_cache = {}
_geo_cache_density = -1.0


def get_cached(name, gen_fn, *args):
    global _geo_cache, _geo_cache_density
    d = config.density.value
    if d != _geo_cache_density:
        _geo_cache.clear()
        _geo_cache_density = d
    if name not in _geo_cache:
        _geo_cache[name] = gen_fn(*args)
    return _geo_cache[name]


# ── Vectorized edge generation helper ────────────────

def _make_grid_edges(nu, nv):
    i_vals = np.arange(nu, dtype=np.int32)
    j_vals = np.arange(nv, dtype=np.int32)
    ig, jg = np.meshgrid(i_vals, j_vals, indexing='ij')
    i_flat = ig.ravel()
    j_flat = jg.ravel()

    a = i_flat * nv + j_flat
    b_u = i_flat * nv + (j_flat + 1) % nv
    b_v = ((i_flat + 1) % nu) * nv + j_flat

    edges_u = np.column_stack([a, b_u])
    edges_v = np.column_stack([a, b_v])
    return np.vstack([edges_u, edges_v]).astype(np.int32)


# ── Shapes ───────────────────────────────────────────

def _gen_cube():
    s = 1.0
    verts = np.array([
        [-s, -s, -s], [s, -s, -s], [s, s, -s], [-s, s, -s],
        [-s, -s, s],  [s, -s, s],  [s, s, s],  [-s, s, s],
    ], dtype=np.float64)
    edges = np.array([
        [0, 1], [1, 2], [2, 3], [3, 0],
        [4, 5], [5, 6], [6, 7], [7, 4],
        [0, 4], [1, 5], [2, 6], [3, 7],
    ], dtype=np.int32)
    return verts, edges


def _gen_pyramid():
    s = 1.3
    verts = np.array([
        [0, s, 0],
        [-s, -s, s], [s, -s, s], [s, -s, -s], [-s, -s, -s],
    ], dtype=np.float64)
    edges = np.array([
        [1, 2], [2, 3], [3, 4], [4, 1],
        [0, 1], [0, 2], [0, 3], [0, 4],
    ], dtype=np.int32)
    return verts, edges


def _gen_sphere(detail):
    r = 1.3
    ncols = detail * 2
    i_vals = np.arange(detail)
    j_vals = np.arange(ncols)
    ig, jg = np.meshgrid(i_vals, j_vals, indexing='ij')
    i_flat = ig.ravel().astype(np.float64)
    j_flat = jg.ravel().astype(np.float64)

    theta = np.pi * (i_flat / max(detail - 1, 1))
    phi = 2 * np.pi * (j_flat / ncols)
    st = np.sin(theta)
    x = r * st * np.cos(phi)
    y = r * st * np.sin(phi)
    z = r * np.cos(theta)
    verts = np.column_stack([x, y, z])

    lat_step = max(1, detail // 8)
    lon_step = max(1, ncols // 12)

    edges = []
    for i in range(0, detail, lat_step):
        for j in range(0, ncols - lon_step, lon_step):
            a = i * ncols + j
            b = i * ncols + j + lon_step
            if b < len(verts):
                edges.append([a, b])
    for j in range(0, ncols, lon_step):
        for i in range(0, detail - lat_step, lat_step):
            a = i * ncols + j
            b = (i + lat_step) * ncols + j
            if b < len(verts):
                edges.append([a, b])

    edge_arr = np.array(edges, dtype=np.int32) if edges else np.zeros((0, 2), dtype=np.int32)
    return verts, edge_arr


def _gen_torus(nu, nv):
    R, r = 1.5, 0.6
    u_vals = np.linspace(0, 2 * np.pi, nu, endpoint=False)
    v_vals = np.linspace(0, 2 * np.pi, nv, endpoint=False)
    ug, vg = np.meshgrid(u_vals, v_vals, indexing='ij')
    u_flat = ug.ravel()
    v_flat = vg.ravel()

    x = (R + r * np.cos(v_flat)) * np.cos(u_flat)
    y = (R + r * np.cos(v_flat)) * np.sin(u_flat)
    z = r * np.sin(v_flat)
    verts = np.column_stack([x, y, z])
    edges = _make_grid_edges(nu, nv)
    return verts, edges


def _gen_mobius(nu, nv):
    R, wmax = 1.7, 0.5
    u_vals = np.linspace(0, 2 * np.pi, nu, endpoint=False)
    w_vals = np.linspace(-wmax, wmax, nv)
    ug, wg = np.meshgrid(u_vals, w_vals, indexing='ij')
    u_flat = ug.ravel()
    w_flat = wg.ravel()

    half_u = u_flat / 2
    x = (R + w_flat * np.cos(half_u)) * np.cos(u_flat)
    y = (R + w_flat * np.cos(half_u)) * np.sin(u_flat)
    z = w_flat * np.sin(half_u)
    verts = np.column_stack([x, y, z])
    edges = _make_grid_edges(nu, nv)
    return verts, edges


def _gen_klein(nu, nv):
    u_vals = np.linspace(0, 2 * np.pi, nu, endpoint=False)
    v_vals = np.linspace(0, 2 * np.pi, nv, endpoint=False)
    ug, vg = np.meshgrid(u_vals, v_vals, indexing='ij')
    u_flat = ug.ravel()
    v_flat = vg.ravel()

    cu = np.cos(u_flat)
    su = np.sin(u_flat)
    base = 2.5 - 1.5 * cu

    lower_half = u_flat >= np.pi
    v_eff = np.where(lower_half, v_flat + np.pi, v_flat)

    x = base * np.cos(v_eff) * 0.4
    y = -1.5 * su * 0.4
    z = base * np.sin(v_eff) * 0.4
    verts = np.column_stack([x, y, z])
    edges = _make_grid_edges(nu, nv)
    return verts, edges


SHAPE_DEFS = [
    ("Cube",         lambda: get_cached("cube", _gen_cube)),
    ("Pyramid",      lambda: get_cached("pyramid", _gen_pyramid)),
    ("Sphere",       lambda: get_cached("sphere", _gen_sphere,
                                        max(6, int(14 * config.density.value)))),
    ("Torus",        lambda: get_cached("torus", _gen_torus,
                                        max(10, int(24 * config.density.value)),
                                        max(6, int(12 * config.density.value)))),
    ("Mobius Strip",  lambda: get_cached("mobius", _gen_mobius,
                                         max(20, int(60 * config.density.value)),
                                         max(4, int(8 * config.density.value)))),
    ("Klein Bottle",  lambda: get_cached("klein", _gen_klein,
                                         max(20, int(50 * config.density.value)),
                                         max(8, int(16 * config.density.value)))),
]


def draw_shape(idx, ax, ay, scr, frame_count):
    _, get_geo = SHAPE_DEFS[idx]
    verts, edges = get_geo()

    xs, ys, zs = batch_rotate_project(verts, ax, ay)

    mode = config.color_mode
    color_lut = None
    static_color = ""

    if mode == "shape":
        static_color = SHAPE_COLORS[idx % len(SHAPE_COLORS)]
    elif mode == "depth":
        color_lut = _get_palette_lut(config.depth_palette_idx)
    elif mode == "rotate":
        cidx = (idx + frame_count // 10) % len(SHAPE_COLORS)
        static_color = SHAPE_COLORS[cidx]

    ramp = BRIGHTNESS_RAMPS[config.brightness_ramp_idx % len(BRIGHTNESS_RAMPS)]

    if config.render_mode == "points":
        scr.draw_points(xs, ys, zs, ramp, color_lut, static_color)
    else:
        if len(edges) == 0:
            return
        e0 = edges[:, 0]
        e1 = edges[:, 1]
        scr.draw_lines(
            xs[e0], ys[e0], zs[e0],
            xs[e1], ys[e1], zs[e1],
            ramp, color_lut, static_color,
        )


# ── Non-blocking input ───────────────────────────────

def get_key():
    if os.name == "nt":
        try:
            import msvcrt
        except ImportError:
            return None
        if msvcrt.kbhit():
            return msvcrt.getwch()
        return None
    else:
        import select, termios, tty
        if not sys.stdin.isatty():
            return None
        fd = sys.stdin.fileno()
        dr, _, _ = select.select([sys.stdin], [], [], 0)
        if not dr:
            return None
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            return sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


# ── Audio Analyzer ───────────────────────────────────

class AudioAnalyzer:
    def __init__(self, sample_rate=22050, block_size=1024):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.running = False
        self.device_index = None
        self.device_name = "Default"
        self._stream = None
        self._lock = threading.Lock()
        self._rms = 0.0
        self._onset = False
        self._bpm = 120.0
        self._rms_slow = 0.0
        self._last_onset = 0.0
        self._onset_times: deque = deque(maxlen=32)
        self._cooldown = 0.12

    def start(self, device=None):
        if not HAS_AUDIO:
            return False
        self.stop()
        if device is not None:
            self.device_index = device
        try:
            self._stream = sd.InputStream(
                device=self.device_index,
                samplerate=self.sample_rate,
                blocksize=self.block_size,
                channels=1,
                dtype="float32",
                callback=self._callback,
            )
            self._stream.start()
            self.running = True
            return True
        except Exception:
            self.running = False
            return False

    def stop(self):
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
        self.running = False
        self._stream = None
        self._rms_slow = 0.0
        self._onset_times.clear()

    def _callback(self, indata, frames, time_info, status):
        rms = float(np.sqrt(np.mean(indata ** 2)))
        self._rms_slow = self._rms_slow * 0.93 + rms * 0.07

        now = time.time()
        onset = False
        threshold = max(self._rms_slow * 3.0, 0.008)
        if rms > threshold and (now - self._last_onset) > self._cooldown:
            onset = True
            self._last_onset = now
            self._onset_times.append(now)

        bpm = self._bpm
        if len(self._onset_times) >= 3:
            times = list(self._onset_times)
            intervals = [
                times[i] - times[i - 1]
                for i in range(1, len(times))
                if 0.25 < times[i] - times[i - 1] < 2.0
            ]
            if len(intervals) >= 2:
                bpm = clamp(
                    60.0 / sorted(intervals)[len(intervals) // 2], 60, 240
                )

        with self._lock:
            self._rms = rms
            if onset:
                self._onset = True
            self._bpm = bpm

    def get_features(self):
        with self._lock:
            rms = self._rms
            onset = self._onset
            bpm = self._bpm
            self._onset = False
            return rms, onset, bpm


audio = AudioAnalyzer()


# ── Audio device listing ─────────────────────────────

def list_audio_devices():
    if not HAS_AUDIO:
        return [], []
    try:
        devices = sd.query_devices()
    except Exception:
        return [], []
    inputs = []
    outputs = []
    default_in, default_out = sd.default.device
    for i, dev in enumerate(devices):
        name = dev["name"]
        if dev["max_input_channels"] > 0:
            is_default = (i == default_in)
            inputs.append((i, name, is_default))
        if dev["max_output_channels"] > 0:
            is_default = (i == default_out)
            outputs.append((i, name, is_default))
    return inputs, outputs


# ── Stable sub-menu renderer ────────────────────────

def _menu_write(lines, max_lines=50):
    tw, _ = terminal_size()
    tw = max(tw, 60)
    out = ["\033[H"]
    for i, line in enumerate(lines):
        if i >= max_lines:
            break
        padded = line[:tw].ljust(tw)
        out.append(padded)
        if i < max_lines - 1:
            out.append("\n")
    out.append("\033[J")
    sys.stdout.write("".join(out))
    sys.stdout.flush()


def run_audio_menu():
    while True:
        lines = []
        lines.append("Audio Device Setup")
        lines.append("=" * 50)
        lines.append("")

        if not HAS_AUDIO:
            lines.append("  Audio libraries not installed.")
            lines.append("  Run: pip install sounddevice numpy")
            lines.append("")
            lines.append("  x = back")
            _menu_write(lines)
            ch = get_key()
            if ch is None:
                time.sleep(0.1)
                continue
            if ch == "x":
                return
            continue

        inputs, outputs = list_audio_devices()

        lines.append("  INPUT DEVICES:")
        if not inputs:
            lines.append("    (none detected)")
        for list_idx, (dev_idx, name, is_def) in enumerate(inputs):
            sel = ">" if dev_idx == audio.device_index else " "
            if audio.device_index is None and is_def:
                sel = ">"
            def_tag = " [DEFAULT]" if is_def else ""
            lines.append(f"  {sel} {list_idx}: {name}{def_tag}")

        lines.append("")
        lines.append("  OUTPUT DEVICES (reference):")
        if not outputs:
            lines.append("    (none detected)")
        for list_idx, (dev_idx, name, is_def) in enumerate(outputs):
            def_tag = " [DEFAULT]" if is_def else ""
            lines.append(f"    {list_idx}: {name}{def_tag}")

        lines.append("")
        cur = audio.device_name
        if audio.running:
            cur += " (active)"
        lines.append(f"  Selected input: {cur}")
        lines.append("")
        lines.append("  0-9 = select input device")
        lines.append("  d   = reset to default")
        lines.append("  x   = back")

        _menu_write(lines)

        ch = get_key()
        if ch is None:
            time.sleep(0.1)
            continue
        if ch == "x":
            return
        elif ch == "d":
            was_running = audio.running
            audio.stop()
            audio.device_index = None
            audio.device_name = "Default"
            if was_running or config.audio_reactive:
                audio.start()
        elif ch in "0123456789":
            pick = int(ch)
            if pick < len(inputs):
                dev_idx, name, _ = inputs[pick]
                was_running = audio.running
                audio.stop()
                audio.device_index = dev_idx
                audio.device_name = name
                if was_running or config.audio_reactive:
                    if not audio.start():
                        audio.device_index = None
                        audio.device_name = "Default"
                        audio.start()


def run_resolution_menu():
    while True:
        tw, th = terminal_size()
        lines = []
        lines.append("Resolution Setup")
        lines.append("=" * 50)
        lines.append("")
        lines.append(f"  Terminal size: {tw}x{th + 1}")
        lines.append(f"  Current render: {WIDTH}x{HEIGHT}")
        lines.append("")

        for i, (label, pw, ph) in enumerate(RESOLUTION_PRESETS):
            sel = ">" if i == config.resolution_idx else " "
            if pw is None:
                dim_str = f"{tw}x{th} (terminal)"
            else:
                actual_w = min(pw, tw)
                actual_h = min(ph, th)
                dim_str = f"{pw}x{ph}"
                if actual_w != pw or actual_h != ph:
                    dim_str += f" -> {actual_w}x{actual_h} (clamped)"
            lines.append(f"  {sel} {i}: {label:<8} {dim_str}")

        lines.append("")
        lines.append("  0-4 = select preset")
        lines.append("  x   = back")

        _menu_write(lines)

        ch = get_key()
        if ch is None:
            time.sleep(0.1)
            continue
        if ch == "x":
            return
        elif ch in "01234":
            pick = int(ch)
            if pick < len(RESOLUTION_PRESETS):
                config.resolution_idx = pick
                apply_resolution(config.resolution_idx)


# ── FPS tracking & adaptive throttle ─────────────────

class FPSTracker:
    def __init__(self, target=TARGET_FPS, window=30):
        self.target = target
        self.frame_times = deque(maxlen=window)
        self.effective_density = 1.0

    def tick(self, dt):
        self.frame_times.append(dt)

    @property
    def fps(self):
        if not self.frame_times:
            return 60.0
        avg = sum(self.frame_times) / len(self.frame_times)
        return 1.0 / avg if avg > 0 else 60.0

    def adapt(self, base_density):
        if not config.fps_adapt:
            self.effective_density = base_density
            return base_density

        fps = self.fps

        if fps < FPS_FLOOR and self.effective_density > 0.25:
            self.effective_density = max(0.25, self.effective_density * 0.8)
        elif fps < self.target * 0.85 and self.effective_density > 0.25:
            self.effective_density = max(0.25, self.effective_density * 0.95)
        elif fps > self.target * 1.1 and self.effective_density < base_density:
            self.effective_density = min(base_density, self.effective_density * 1.15)

        return self.effective_density


fps_tracker = FPSTracker()


# ── HUD ──────────────────────────────────────────────

def build_hud_line1(bpm_str=""):
    si = config.shape_index
    name = SHAPE_DEFS[si][0]
    mode = config.color_mode
    pal = ""
    if mode == "depth":
        pal_name = DEPTH_PALETTES[
            config.depth_palette_idx % len(DEPTH_PALETTES)
        ][0]
        pal = f"({pal_name})"
    res_label = RESOLUTION_PRESETS[config.resolution_idx][0]
    fps_str = f"{fps_tracker.fps:.0f}fps"
    parts = [
        f"[{si + 1}] {name}",
        config.render_mode.upper(),
        f"color:{mode}{pal}",
        f"{WIDTH}x{HEIGHT}({res_label})",
        fps_str,
    ]
    if config.fps_adapt and fps_tracker.effective_density < config.density.value * 0.99:
        parts.append(f"THR:{fps_tracker.effective_density:.1f}")
    if config.audio_reactive:
        status = bpm_str if bpm_str else "waiting..."
        parts.append(f"AUDIO:{status}")
    if config.paused:
        parts.append("PAUSED")
    return "  ".join(p for p in parts if p)


def build_hud_line2():
    parts = [p.display() for p in config.all_params]
    parts.append(f"Brt:{'ON' if config.brightness_enabled else 'OFF'}")
    parts.append(f"Ramp:{config.brightness_ramp_idx}")
    return "  ".join(parts)


def build_hud_line3():
    return (
        "Spc=pause 1-6=shape p=wire/pts +/-=scl f/F=fov "
        "[/]=spd d/D=den z/Z=drng b=brt B=ramp c=color C=palette "
        "a=audio A=dev R=res s/S=auto t=adapt .=hud r=reset m=menu q=quit"
    )


# ── Menu ──────────────────────────────────────────────

def menu_screen():
    pal_name = DEPTH_PALETTES[
        config.depth_palette_idx % len(DEPTH_PALETTES)
    ][0]
    res_label = RESOLUTION_PRESETS[config.resolution_idx][0]
    lines = []
    lines.append("ASCII 3D Shapes v9 - Menu")
    lines.append("=" * 50)
    lines.append(f"  Shape:         {config.shape_index + 1}"
                 f" - {SHAPE_DEFS[config.shape_index][0]}")
    lines.append(f"  Render:        {config.render_mode}")
    for p in config.all_params:
        tag = ""
        if p.value == 0 and p.lo == 0:
            tag = "  (disabled)"
        elif p.at_min:
            tag = "  << MIN"
        elif p.at_max:
            tag = "  >> MAX"
        fmt_lo = f"{p.lo:{p.fmt}}" if p.lo != 0 else "OFF"
        lines.append(f"  {p.name + ':':<14} {p.display().split(':')[1]}{tag}"
                     f"  ({fmt_lo} .. {p.hi:{p.fmt}})")
    lines.append(f"  SpeedY:        {config.speed_y.value:{config.speed_y.fmt}}"
                 f"  (linked to Speed)")
    lines.append(f"  Brightness:    {'ON' if config.brightness_enabled else 'OFF'}")
    ramp_str = repr(
        BRIGHTNESS_RAMPS[config.brightness_ramp_idx % len(BRIGHTNESS_RAMPS)]
    )
    lines.append(f"  Ramp:          {config.brightness_ramp_idx} - {ramp_str}")
    lines.append(f"  Color mode:    {config.color_mode}")
    lines.append(f"  Depth palette: {config.depth_palette_idx + 1}/{len(DEPTH_PALETTES)}"
                 f" - {pal_name}")
    lines.append(f"  Resolution:    {WIDTH}x{HEIGHT} ({res_label})")
    lines.append(f"  HUD overlay:   {'ON' if config.hud_visible else 'OFF'}")
    lines.append(f"  FPS target:    {TARGET_FPS}  adapt:{'ON' if config.fps_adapt else 'OFF'}")
    lines.append(f"  Current FPS:   {fps_tracker.fps:.1f}")
    if config.fps_adapt:
        lines.append(f"  Eff. density:  {fps_tracker.effective_density:.2f}")
    audio_str = "OFF"
    if config.audio_reactive:
        audio_str = "ON" if audio.running else "ON (no signal)"
    if not HAS_AUDIO:
        audio_str = "N/A (pip install sounddevice numpy)"
    lines.append(f"  Audio react:   {audio_str}")
    lines.append(f"  Audio device:  {audio.device_name}")
    lines.append(f"  Terminal:      {terminal_size()[0]}x{terminal_size()[1] + 1}")
    lines.append("")
    lines.append("  Same hotkeys as render view, plus:")
    lines.append("  A = audio device setup   R = resolution setup")
    lines.append("  x = exit menu   q = quit   r = reset angles")
    lines.append("")
    lines.append("  Press keys; changes apply immediately.")
    _menu_write(lines)


def run_menu():
    while True:
        menu_screen()
        ch = get_key()
        if ch is None:
            time.sleep(0.1)
            continue
        if ch == "x":
            return "continue"
        if ch == "q":
            return "quit"
        if ch == "r":
            return "reset_angles"
        if ch == "A":
            run_audio_menu()
            continue
        if ch == "R":
            run_resolution_menu()
            return "resolution_changed"
        handle_common_key(ch)


def handle_common_key(ch):
    if config.handle_key(ch):
        return True

    if ch in "123456":
        idx = int(ch) - 1
        if 0 <= idx < len(SHAPE_DEFS):
            config.shape_index = idx
        return True
    elif ch == "p":
        config.render_mode = (
            "points" if config.render_mode == "wire" else "wire"
        )
        return True
    elif ch == "b":
        config.brightness_enabled = not config.brightness_enabled
        return True
    elif ch == "B":
        config.brightness_ramp_idx = (
            (config.brightness_ramp_idx + 1) % len(BRIGHTNESS_RAMPS)
        )
        return True
    elif ch == "c":
        config.color_mode_idx = (
            (config.color_mode_idx + 1) % len(COLOR_MODES)
        )
        return True
    elif ch == "C":
        config.depth_palette_idx = (
            (config.depth_palette_idx + 1) % len(DEPTH_PALETTES)
        )
        return True
    elif ch == "a":
        config.audio_reactive = not config.audio_reactive
        if config.audio_reactive:
            if not audio.running:
                if not audio.start():
                    config.audio_reactive = False
        else:
            audio.stop()
        return True
    elif ch == "t":
        config.fps_adapt = not config.fps_adapt
        if config.fps_adapt:
            fps_tracker.effective_density = config.density.value
        return True
    elif ch == ".":
        config.hud_visible = not config.hud_visible
        return True
    return False


# ── Main loop ─────────────────────────────────────────

def main():
    global WIDTH, HEIGHT, config

    tw, th = terminal_size()
    WIDTH, HEIGHT = tw, th
    config = Config(auto_fov=fov_for_size(WIDTH, HEIGHT))
    fps_tracker.effective_density = config.density.value

    scr = ScreenBuffer(WIDTH, HEIGHT)
    angle_x = 0.0
    angle_y = 0.0
    last_switch = time.time()
    last_frame = time.time()
    frame_count = 0
    audio_punch = 0.0
    audio_bpm = 120.0
    need_resize = False

    sys.stdout.write("\033[?25l")
    sys.stdout.flush()
    os.system(CLEAR_CMD)

    try:
        while True:
            now = time.time()
            dt = now - last_frame
            last_frame = now
            dt_scale = dt / 0.03 if dt > 0 else 1.0

            fps_tracker.tick(dt)

            if need_resize:
                scr = ScreenBuffer(WIDTH, HEIGHT)
                os.system(CLEAR_CMD)
                need_resize = False

            ch = get_key()
            if ch:
                if ch == " ":
                    config.paused = not config.paused
                elif ch == "q":
                    return
                elif ch == "R":
                    sys.stdout.write("\033[?25h")
                    sys.stdout.flush()
                    run_resolution_menu()
                    sys.stdout.write("\033[?25l")
                    sys.stdout.flush()
                    need_resize = True
                    last_frame = time.time()
                elif ch == "A":
                    sys.stdout.write("\033[?25h")
                    sys.stdout.flush()
                    run_audio_menu()
                    sys.stdout.write("\033[?25l")
                    sys.stdout.flush()
                    os.system(CLEAR_CMD)
                    last_frame = time.time()
                elif ch == "m":
                    sys.stdout.write("\033[?25h")
                    sys.stdout.flush()
                    result = run_menu()
                    sys.stdout.write("\033[?25l")
                    sys.stdout.flush()
                    os.system(CLEAR_CMD)
                    last_frame = time.time()
                    if result == "quit":
                        return
                    elif result == "reset_angles":
                        angle_x = angle_y = 0.0
                    elif result == "resolution_changed":
                        need_resize = True
                elif ch == "r":
                    angle_x = angle_y = 0.0
                else:
                    handle_common_key(ch)

            if (not config.audio_reactive
                    and config.auto_switch.value > 0
                    and now - last_switch > config.auto_switch.value):
                config.shape_index = random.randrange(len(SHAPE_DEFS))
                last_switch = now

            audio_rms = 0.0
            bpm_str = ""
            if config.audio_reactive and audio.running:
                rms, onset, bpm = audio.get_features()
                audio_rms = rms
                audio_bpm = bpm
                bpm_str = f"{bpm:.0f}bpm"

                if onset:
                    audio_punch = 1.0
                    config.shape_index = random.randrange(len(SHAPE_DEFS))
                    config.depth_palette_idx = (
                        (config.depth_palette_idx + 1) % len(DEPTH_PALETTES)
                    )
                    last_switch = now

                audio_punch *= 0.85 ** dt_scale

            elif config.audio_reactive and not audio.running:
                bpm_str = "waiting..."

            saved_scale = config.scale.value
            if config.audio_reactive and audio.running:
                config.scale.value *= (
                    1.0 + audio_punch * 0.5 + audio_rms * 2.0
                )

            eff_density = fps_tracker.adapt(config.density.value)
            eff_density = round(eff_density * 20) / 20
            eff_density = max(0.25, eff_density)
            saved_density = config.density.value
            config.density.value = eff_density

            scr.clear()

            si = config.shape_index
            draw_shape(si, angle_x, angle_y, scr, frame_count)

            config.density.value = saved_density

            if config.hud_visible:
                scr.put_text(0, 0, build_hud_line1(bpm_str)[:WIDTH])
                scr.put_text(0, 1, build_hud_line2()[:WIDTH])
                scr.put_text(0, HEIGHT - 1, build_hud_line3()[:WIDTH])

            sys.stdout.write("\033[H")
            sys.stdout.write(scr.render())
            sys.stdout.flush()

            config.scale.value = saved_scale

            if not config.paused:
                if config.audio_reactive and audio.running:
                    bps = audio_bpm / 60.0
                    angle_x += bps * 1.0 * dt
                    angle_y += bps * 0.83 * dt
                else:
                    angle_x += config.speed_x.value * dt_scale
                    angle_y += config.speed_y.value * dt_scale

            frame_count += 1

            target_dt = 1.0 / TARGET_FPS
            elapsed = time.time() - now
            sleep_time = target_dt - elapsed
            if sleep_time > 0.001:
                time.sleep(sleep_time)

    finally:
        audio.stop()
        sys.stdout.write("\033[?25h")
        sys.stdout.write(COLOR_RESET)
        sys.stdout.flush()
        os.system(CLEAR_CMD)
        print("Goodbye.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        audio.stop()
        sys.stdout.write("\033[?25h")
        sys.stdout.write(COLOR_RESET)
        sys.stdout.flush()
        os.system(CLEAR_CMD)
        print("Interrupted.")
