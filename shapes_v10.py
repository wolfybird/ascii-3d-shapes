#!/usr/bin/env python3
"""
shapes_v10.py – ASCII 3D Shape Renderer

v10 (2026-11)
    - Opens in its own window (pygame) on Windows, macOS and Linux:
      drag to rotate, right-drag to spin, wheel to zoom, middle-click to
      reset, resizable, F11 fullscreen, clickable button bar and menus
    - Settings panel with sliders and dropdowns (Tkinter, in its own
      process so it is stable on macOS too); 'P' or the Settings button
    - Menus are overlays drawn over the running shape, in both modes
    - --terminal runs in the terminal as before; it follows terminal
      resizes and turns on ANSI colors on Windows itself
    - Settings are remembered between runs; crashes are written to a log
    - The frame is NumPy arrays of characters and xterm-256 color codes,
      so drawing no longer loops over points in Python

v9.7 (2026-11)
    - Help line lists every key and wraps instead of being cut off
    - ',' and '.' rotate Z like '<' and '>'; the HUD toggle moved to 'h'
    - Audio device list shows each device once (WASAPI on Windows), streams
      open at the device's own sample rate, and a device that fails to open
      says so instead of quietly switching to the default
    - "Rhombus" is now called Octahedron, which is what it is
    - Missing PortAudio (common on Linux) turns audio off instead of crashing

v9.6 (2026-11)
    - Keys work on macOS/Linux: terminal stays in cbreak mode while running
    - FPS adapt judges render time instead of the capped frame rate, so
      density recovers; d/D still work while adapt is on
    - No audio input at startup turns audio off, so auto-switch still runs
    - Points mode z-buffer keeps the nearest point per cell
    - Resolution changes scale FOV instead of resetting it (keeps FOV 65 look)
    - Sphere rings and meridians close
    - Seam fixes: Mobius and Klein 2 twist joins, no doubled cylinder lines;
      Klein 1 is now a true Klein bottle (bottle immersion)
    - HUD scale no longer jitters with the audio punch
"""

import argparse
import json
import math
import os
import random
import shutil
import subprocess
import sys
import time
import threading
import traceback
from collections import deque
from typing import List, Tuple, Callable, Optional

APP_NAME = "ASCII 3D Shapes"
APP_VERSION = "10"

HAS_AUDIO = False
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

if getattr(sys, "frozen", False) and sys.platform.startswith("linux"):
    # sounddevice only asks the system for PortAudio; fall back to the copy
    # bundled with the app when the system has none
    import ctypes.util
    import glob
    _system_find_library = ctypes.util.find_library

    def _find_library(name):
        found = _system_find_library(name)
        if found is None and name == "portaudio":
            bundled = glob.glob(os.path.join(sys._MEIPASS, "libportaudio.so*"))
            found = bundled[0] if bundled else None
        return found

    ctypes.util.find_library = _find_library

try:
    import sounddevice as sd
    if HAS_NUMPY:
        HAS_AUDIO = True
except (ImportError, OSError):  # OSError: PortAudio library not found
    pass

if not HAS_NUMPY:
    print("shapes_v10 requires numpy: pip install numpy")
    sys.exit(1)

COLOR_RESET = "\033[0m"

# xterm-256 color codes
SHAPE_COLORS = [
    45,     # 0 cyan
    214,    # 1 orange
    82,     # 2 green
    201,    # 3 magenta
    189,    # 4 lavender
    160,    # 5 red
    226,    # 6 yellow
    21,     # 7 blue
    255,    # 8 white
    208,    # 9 amber
]

SHAPE_COLOR_NAMES = [
    "cyan", "orange", "green", "magenta", "lavender",
    "red", "yellow", "blue", "white", "amber",
]

# menus, HUD extras and the window button bar
UI_BG = 236
UI_SEL_BG = 24
UI_BAR_BG = 235
UI_BTN_BG = 239
UI_TEXT = 252
UI_DIM = 245
UI_ACCENT = 45

SHIFT_NUM_MAP = {
    '!': 0, '@': 1, '#': 2, '$': 3, '%': 4,
    '^': 5, '&': 6, '*': 7, '(': 8, ')': 9,
}

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
ONSET_MODES = [
    "all",
    "punch+shape",
    "punch+palette",
    "punch only",
    "shape+palette",
    "shape only",
    "palette only",
]

RESOLUTION_PRESETS = [
    ("Auto",   None, None),
    ("Small",  80,   24),
    ("Medium", 120,  40),
    ("Large",  160,  50),
    ("XL",     200,  55),
]

TARGET_FPS = 30
FPS_FLOOR = 15
ARROW_ROT_DELTA = 0.1

WIDTH = 120
HEIGHT = 40


DRAG_ROT = 0.01         # radians per pixel of mouse drag
FOV_REF_GRID = (200, 55)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def terminal_size():
    try:
        # fd 1 maps to the console handle on Windows, even for a console
        # opened later by a windowed build
        size = os.get_terminal_size(1)
    except (OSError, ValueError):
        size = shutil.get_terminal_size(fallback=(120, 40))
    return max(40, size.columns), max(10, size.lines - 1)


def fov_for_size(w, h):
    eff_w = w * 0.8
    eff_h = (h - 3) * 2.2
    return clamp(min(eff_w, eff_h) * 0.35, 2.0, 100.0)


def apply_resolution(frontend):
    global WIDTH, HEIGHT
    old_fit = fov_for_size(WIDTH, HEIGHT)
    WIDTH, HEIGHT = frontend.grid_size(config.resolution_idx)
    fov = config.fov
    fov.value = clamp(fov.value * fov_for_size(WIDTH, HEIGHT) / old_fit,
                      fov.lo, fov.hi)


# ── Colors: xterm-256 codes, as escapes or RGB ──────

def _xterm_rgb(code):
    if code < 16:
        return [
            (0, 0, 0), (205, 0, 0), (0, 205, 0), (205, 205, 0),
            (0, 0, 238), (205, 0, 205), (0, 205, 205), (229, 229, 229),
            (127, 127, 127), (255, 0, 0), (0, 255, 0), (255, 255, 0),
            (92, 92, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255),
        ][code]
    if code < 232:
        levels = (0, 95, 135, 175, 215, 255)
        c = code - 16
        return levels[c // 36], levels[(c // 6) % 6], levels[c % 6]
    gray = 8 + (code - 232) * 10
    return gray, gray, gray


XTERM_RGB = [_xterm_rgb(c) for c in range(256)]

_SGR_CACHE = {}


def _sgr(fg, bg):
    """Escape that sets foreground and background (-1 = terminal default)."""
    key = (fg, bg)
    seq = _SGR_CACHE.get(key)
    if seq is None:
        seq = "\033[0"
        if fg >= 0:
            seq += f";38;5;{fg}"
        if bg >= 0:
            seq += f";48;5;{bg}"
        seq += "m"
        _SGR_CACHE[key] = seq
    return seq


_PALETTE_LUTS = {}


def _get_palette_lut(palette_idx):
    """256-entry array of color codes from near (0) to far (255)."""
    key = palette_idx % len(DEPTH_PALETTES)
    if key not in _PALETTE_LUTS:
        _, palette = DEPTH_PALETTES[key]
        idx = (np.arange(256) / 255 * (len(palette) - 1)).astype(np.int32)
        _PALETTE_LUTS[key] = np.array(palette, dtype=np.int16)[idx]
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
    def __init__(self, auto_fov=65.0):
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
        self.audio_sens = Param("Sens", 1.3, 0.1, 5.0, 1.15, ".1f", "n", "N",
                                multiplicative=True)

        self.shape_index = 0
        self.paused = False
        self.auto_rotate = True
        self.render_mode = "wire"
        self.brightness_enabled = True
        self.brightness_ramp_idx = 1
        self.color_mode_idx = 2
        self.depth_palette_idx = 0
        self.depth_invert = False
        self.shape_color_idx = -1
        self.audio_reactive = True
        self.audio_onset_mode = 0
        self.hud_visible = True
        self.resolution_idx = 0
        self.fps_adapt = False

        self.all_params = [self.scale, self.fov, self.speed_x, self.density,
                           self.auto_switch, self.depth_range, self.audio_sens]

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
    norm = np.clip((z_vals + half) / config.depth_range.value, 0.0, 1.0)
    if config.depth_invert:
        norm = 1.0 - norm
    return norm


# ── Vectorized rotation & projection ─────────────────

def make_rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64)


def make_rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float64)


def make_rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)


def batch_rotate_project(verts_np, ax, ay, az, scale):
    rot = make_rot_z(az) @ make_rot_y(ay) @ make_rot_x(ax)
    rotated = verts_np @ rot.T
    zs = rotated[:, 2]
    denom = zs + 4.0
    denom = np.where(denom == 0, 1e-4, denom)
    f = config.fov.value / denom
    xs = (rotated[:, 0] * f * scale + WIDTH // 2).astype(np.int32)
    ys = (-rotated[:, 1] * f * scale + HEIGHT // 2).astype(np.int32)
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
    """Character grid with xterm-256 foreground and background codes
    (-1 means the default color) and a z-buffer for the shape."""

    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.chars = np.full((h, w), 32, dtype=np.uint8)
        self.fg = np.full((h, w), -1, dtype=np.int16)
        self.bg = np.full((h, w), -1, dtype=np.int16)
        self.zbuf = np.full((h, w), np.inf, dtype=np.float64)

    def clear(self):
        self.chars.fill(32)
        self.fg.fill(-1)
        self.bg.fill(-1)
        self.zbuf.fill(np.inf)

    def put_text(self, x, y, text, fg=-1, bg=-1):
        if not 0 <= y < self.h or x >= self.w:
            return
        if x < 0:
            text = text[-x:]
            x = 0
        text = text[:self.w - x]
        if not text:
            return
        end = x + len(text)
        self.chars[y, x:end] = np.frombuffer(
            text.encode("ascii", errors="replace"), dtype=np.uint8)
        self.fg[y, x:end] = fg
        self.bg[y, x:end] = bg
        self.zbuf[y, x:end] = -np.inf

    def fill_rect(self, x, y, w, h, bg):
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(self.w, x + w), min(self.h, y + h)
        if x0 >= x1 or y0 >= y1:
            return
        self.chars[y0:y1, x0:x1] = 32
        self.fg[y0:y1, x0:x1] = -1
        self.bg[y0:y1, x0:x1] = bg
        self.zbuf[y0:y1, x0:x1] = -np.inf

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

        self.zbuf[w_fy, w_fx] = fz[winners]
        ramp_codes = np.frombuffer(ramp.replace(" ", ".").encode("ascii"),
                                   dtype=np.uint8)
        self.chars[w_fy, w_fx] = ramp_codes[ridx[winners]]
        if color_lut is not None:
            self.fg[w_fy, w_fx] = color_lut[cidx[winners]]
        else:
            self.fg[w_fy, w_fx] = static_color

    def draw_lines(self, x1s, y1s, z1s, x2s, y2s, z2s, ramp, color_lut, static_color):
        if len(x1s) == 0:
            return
        all_x, all_y, all_z = rasterize_lines_flat(x1s, y1s, z1s, x2s, y2s, z2s)
        self.draw_points(all_x, all_y, all_z, ramp, color_lut, static_color)

    def render_ansi(self):
        """The frame as one string of text and color escapes."""
        parts = []
        prev = (-1, -1)
        lit = (self.chars != 32) | (self.bg >= 0)
        for r in range(self.h):
            row = self.chars[r].tobytes().decode("ascii")
            fgs = self.fg[r].tolist()
            bgs = self.bg[r].tolist()
            x = 0
            for c in np.flatnonzero(lit[r]).tolist() + [self.w]:
                if c > x:
                    if prev[1] >= 0:
                        prev = (prev[0], -1)
                        parts.append(_sgr(*prev))
                    parts.append(" " * (c - x))
                if c == self.w:
                    break
                key = (fgs[c], bgs[c])
                if key != prev:
                    parts.append(_sgr(*key))
                    prev = key
                parts.append(row[c])
                x = c + 1
            if r < self.h - 1:
                parts.append("\n")
        if prev != (-1, -1):
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


# ── Edge generation helpers ──────────────────────────

# wrap_v: join column nv-1 back to column 0 (v is periodic)
# seam:   seam[j] is the column of row 0 that row nu-1, column j joins
#         (twisted surfaces like the Mobius strip); None joins column j
def _make_grid_edges(nu, nv, wrap_v=True, seam=None):
    i_vals = np.arange(nu, dtype=np.int32)
    j_vals = np.arange(nv, dtype=np.int32)
    ig, jg = np.meshgrid(i_vals, j_vals, indexing='ij')
    i_flat = ig.ravel()
    j_flat = jg.ravel()

    a = i_flat * nv + j_flat
    b_u = i_flat * nv + (j_flat + 1) % nv
    j_next = j_flat
    if seam is not None:
        j_next = np.where(i_flat == nu - 1, seam[j_flat], j_flat)
    b_v = ((i_flat + 1) % nu) * nv + j_next

    edges_u = np.column_stack([a, b_u])
    if not wrap_v:
        edges_u = edges_u[j_flat < nv - 1]
    edges_v = np.column_stack([a, b_v])
    return np.vstack([edges_u, edges_v]).astype(np.int32)


def _make_grid_edges_open(nu, nv):
    i_vals = np.arange(nu, dtype=np.int32)
    j_vals = np.arange(nv, dtype=np.int32)
    ig, jg = np.meshgrid(i_vals, j_vals, indexing='ij')
    i_flat = ig.ravel()
    j_flat = jg.ravel()
    a = i_flat * nv + j_flat

    h_mask = j_flat < nv - 1
    h_a = a[h_mask]
    h_b = h_a + 1

    v_mask = i_flat < nu - 1
    v_a = a[v_mask]
    v_b = v_a + nv

    edges_h = np.column_stack([h_a, h_b])
    edges_v = np.column_stack([v_a, v_b])
    return np.vstack([edges_h, edges_v]).astype(np.int32)


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


def _gen_octahedron():
    s = 1.0
    h = 1.5
    verts = np.array([
        [0, h, 0], [0, -h, 0],
        [s, 0, 0], [-s, 0, 0], [0, 0, s], [0, 0, -s],
    ], dtype=np.float64)
    edges = np.array([
        [0, 2], [0, 3], [0, 4], [0, 5],
        [1, 2], [1, 3], [1, 4], [1, 5],
        [2, 4], [4, 3], [3, 5], [5, 2],
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


def _gen_cone(n_sides=16):
    r = 1.2
    h = 1.5
    angles = np.linspace(0, 2 * np.pi, n_sides, endpoint=False)
    base_x = r * np.cos(angles)
    base_z = r * np.sin(angles)
    apex = np.array([[0.0, h, 0.0]])
    base = np.column_stack([base_x, np.full(n_sides, -h), base_z])
    verts = np.vstack([apex, base]).astype(np.float64)

    edges = []
    for i in range(n_sides):
        j = (i + 1) % n_sides
        edges.append([1 + i, 1 + j])
        edges.append([0, 1 + i])
    return verts, np.array(edges, dtype=np.int32)


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
        for j in range(0, ncols, lon_step):
            a = i * ncols + j
            b = i * ncols + min(j + lon_step, ncols) % ncols
            edges.append([a, b])
    for j in range(0, ncols, lon_step):
        for i in range(0, detail - 1, lat_step):
            a = i * ncols + j
            b = min(i + lat_step, detail - 1) * ncols + j
            edges.append([a, b])

    edge_arr = np.array(edges, dtype=np.int32) if edges else np.zeros((0, 2), dtype=np.int32)
    return verts, edge_arr


def _gen_icosahedron():
    phi = (1 + math.sqrt(5)) / 2
    raw = np.array([
        [-1, phi, 0], [1, phi, 0], [-1, -phi, 0], [1, -phi, 0],
        [0, -1, phi], [0, 1, phi], [0, -1, -phi], [0, 1, -phi],
        [phi, 0, -1], [phi, 0, 1], [-phi, 0, -1], [-phi, 0, 1],
    ], dtype=np.float64)
    norms = np.linalg.norm(raw, axis=1, keepdims=True)
    verts = raw / norms * 1.3
    edges = np.array([
        [0, 11], [0, 5], [0, 1], [0, 7], [0, 10],
        [3, 9], [3, 4], [3, 2], [3, 6], [3, 8],
        [1, 5], [5, 11], [11, 10], [10, 7], [7, 1],
        [1, 9], [5, 4], [11, 2], [10, 6], [7, 8],
        [9, 4], [4, 2], [2, 6], [6, 8], [8, 9],
        [9, 5], [4, 11], [2, 10], [6, 7], [8, 1],
    ], dtype=np.int32)
    return verts, edges


def _gen_prism(n_sides):
    r = 1.2
    h = 1.0
    angles = np.linspace(0, 2 * np.pi, n_sides, endpoint=False)
    top_x = r * np.cos(angles)
    top_z = r * np.sin(angles)
    top_y = np.full(n_sides, h)
    bot_y = np.full(n_sides, -h)

    top_verts = np.column_stack([top_x, top_y, top_z])
    bot_verts = np.column_stack([top_x, bot_y, top_z])
    verts = np.vstack([top_verts, bot_verts]).astype(np.float64)

    edges = []
    for i in range(n_sides):
        j = (i + 1) % n_sides
        edges.append([i, j])
        edges.append([n_sides + i, n_sides + j])
        edges.append([i, n_sides + i])
    return verts, np.array(edges, dtype=np.int32)


def _gen_hexagon():
    return _gen_prism(6)


def _gen_octagon():
    return _gen_prism(8)


def _gen_star():
    verts = np.array([
        [1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1],
        [-1, -1, -1], [-1, 1, 1], [1, -1, 1], [1, 1, -1],
    ], dtype=np.float64) * 0.9
    edges = np.array([
        [0, 1], [0, 2], [0, 3], [1, 2], [1, 3], [2, 3],
        [4, 5], [4, 6], [4, 7], [5, 6], [5, 7], [6, 7],
    ], dtype=np.int32)
    return verts, edges


def _gen_cylinder(nu, nv):
    r = 1.0
    h = 1.5
    u_vals = np.linspace(0, 2 * np.pi, nu, endpoint=False)
    v_vals = np.linspace(-h, h, nv)
    ug, vg = np.meshgrid(u_vals, v_vals, indexing='ij')
    u_flat = ug.ravel()
    v_flat = vg.ravel()

    x = r * np.cos(u_flat)
    z = r * np.sin(u_flat)
    y = v_flat
    verts = np.column_stack([x, y, z])
    edges = _make_grid_edges(nu, nv, wrap_v=False)
    return verts, edges


def _gen_helix(n_points):
    t = np.linspace(0, 4 * np.pi, n_points)
    r = 1.0
    x = r * np.cos(t)
    z = r * np.sin(t)
    y = np.linspace(-1.5, 1.5, n_points)
    verts = np.column_stack([x, y, z])
    edges = np.column_stack([
        np.arange(n_points - 1, dtype=np.int32),
        np.arange(1, n_points, dtype=np.int32),
    ])
    return verts, edges


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


def _gen_torus_knot(n_points, p=3, q=5):
    R, r = 1.2, 0.4
    t = np.linspace(0, 2 * np.pi, n_points, endpoint=False)
    x = (R + r * np.cos(q * t)) * np.cos(p * t)
    y = (R + r * np.cos(q * t)) * np.sin(p * t)
    z = r * np.sin(q * t)
    verts = np.column_stack([x, y, z])
    edges = np.column_stack([
        np.arange(n_points, dtype=np.int32),
        (np.arange(n_points, dtype=np.int32) + 1) % n_points,
    ])
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
    edges = _make_grid_edges(nu, nv, wrap_v=False, seam=np.arange(nv)[::-1])
    return verts, edges


def _gen_trefoil(n_points):
    return _gen_torus_knot(n_points, p=2, q=3)


# Klein bottle, "bottle" immersion: u in [0, pi) closes onto itself with
# v -> pi - v, so nv must be even for every seam vertex to have a partner
def _gen_klein1(nu, nv):
    nv += nv % 2
    u_vals = np.linspace(0, np.pi, nu, endpoint=False)
    v_vals = np.linspace(0, 2 * np.pi, nv, endpoint=False)
    ug, vg = np.meshgrid(u_vals, v_vals, indexing='ij')
    u_flat = ug.ravel()
    v_flat = vg.ravel()

    cu = np.cos(u_flat)
    su = np.sin(u_flat)
    cv = np.cos(v_flat)
    sv = np.sin(v_flat)

    x = -2 / 15 * cu * (3 * cv - 30 * su + 90 * cu ** 4 * su
                        - 60 * cu ** 6 * su + 5 * cu * cv * su)
    y = -1 / 15 * su * (3 * cv - 3 * cu ** 2 * cv - 48 * cu ** 4 * cv
                        + 48 * cu ** 6 * cv - 60 * su + 5 * cu * cv * su
                        - 5 * cu ** 3 * cv * su - 80 * cu ** 5 * cv * su
                        + 80 * cu ** 7 * cv * su)
    z = 2 / 15 * (3 + 5 * cu * su) * sv
    verts = np.column_stack([x, y, z])
    verts -= (verts.max(axis=0) + verts.min(axis=0)) / 2
    verts *= 1.6 / np.abs(verts).max()
    edges = _make_grid_edges(nu, nv, seam=(nv // 2 - np.arange(nv)) % nv)
    return verts, edges


def _gen_klein2(nu, nv):
    a = 2.5
    u_vals = np.linspace(0, 2 * np.pi, nu, endpoint=False)
    v_vals = np.linspace(0, 2 * np.pi, nv, endpoint=False)
    ug, vg = np.meshgrid(u_vals, v_vals, indexing='ij')
    u_flat = ug.ravel()
    v_flat = vg.ravel()

    cu2 = np.cos(u_flat / 2)
    su2 = np.sin(u_flat / 2)
    sv = np.sin(v_flat)
    s2v = np.sin(2 * v_flat)

    x = (a + cu2 * sv - su2 * s2v) * np.cos(u_flat) * 0.35
    y = (a + cu2 * sv - su2 * s2v) * np.sin(u_flat) * 0.35
    z = (su2 * sv + cu2 * s2v) * 0.35
    verts = np.column_stack([x, y, z])
    edges = _make_grid_edges(nu, nv, seam=(nv - np.arange(nv)) % nv)
    return verts, edges


def _gen_lorenz(n_steps):
    sigma, rho, beta = 10.0, 28.0, 8.0 / 3.0
    dt_step = 0.005

    xs = np.empty(n_steps, dtype=np.float64)
    ys = np.empty(n_steps, dtype=np.float64)
    zs = np.empty(n_steps, dtype=np.float64)
    xs[0], ys[0], zs[0] = 1.0, 1.0, 1.0

    for i in range(1, n_steps):
        x, y, z = xs[i - 1], ys[i - 1], zs[i - 1]
        xs[i] = x + sigma * (y - x) * dt_step
        ys[i] = y + (x * (rho - z) - y) * dt_step
        zs[i] = z + (x * y - beta * z) * dt_step

    verts = np.column_stack([xs, ys, zs])
    center = (verts.max(axis=0) + verts.min(axis=0)) / 2
    verts -= center
    max_ext = np.abs(verts).max()
    if max_ext > 0:
        verts *= 1.5 / max_ext

    edges = np.column_stack([
        np.arange(n_steps - 1, dtype=np.int32),
        np.arange(1, n_steps, dtype=np.int32),
    ])
    return verts, edges


def _gen_mandelbrot(nu, nv, max_iter=50):
    re_vals = np.linspace(-2.0, 0.8, nu)
    im_vals = np.linspace(-1.2, 1.2, nv)
    re_grid, im_grid = np.meshgrid(re_vals, im_vals, indexing='ij')
    c = (re_grid + 1j * im_grid).ravel()

    z = np.zeros(len(c), dtype=np.complex128)
    iterations = np.full(len(c), max_iter, dtype=np.int32)
    active = np.ones(len(c), dtype=bool)

    for i in range(max_iter):
        z[active] = z[active] ** 2 + c[active]
        escaped = active & ((np.abs(z) > 2.0) | ~np.isfinite(np.abs(z)))
        iterations[escaped] = i
        active &= ~escaped
        if not active.any():
            break

    height = iterations.astype(np.float64) / max_iter
    x = re_grid.ravel() * 0.5
    z_coord = im_grid.ravel() * 0.5
    y = height * 1.5 - 0.75
    verts = np.column_stack([x, y, z_coord])
    edges = _make_grid_edges_open(nu, nv)
    return verts, edges


def _gen_julia(nu, nv, max_iter=50):
    c_param = -0.7 + 0.27015j
    re_vals = np.linspace(-1.5, 1.5, nu)
    im_vals = np.linspace(-1.5, 1.5, nv)
    re_grid, im_grid = np.meshgrid(re_vals, im_vals, indexing='ij')
    z = (re_grid + 1j * im_grid).ravel()

    iterations = np.full(len(z), max_iter, dtype=np.int32)
    active = np.ones(len(z), dtype=bool)

    for i in range(max_iter):
        z[active] = z[active] ** 2 + c_param
        escaped = active & ((np.abs(z) > 2.0) | ~np.isfinite(np.abs(z)))
        iterations[escaped] = i
        active &= ~escaped
        if not active.any():
            break

    height = iterations.astype(np.float64) / max_iter
    x = re_grid.ravel() * 0.5
    z_coord = im_grid.ravel() * 0.5
    y = height * 1.5 - 0.75
    verts = np.column_stack([x, y, z_coord])
    edges = _make_grid_edges_open(nu, nv)
    return verts, edges


# ── Shape registry ───────────────────────────────────

SHAPE_DEFS = [
    # key 1
    ("Cube",          lambda: get_cached("cube", _gen_cube)),
    ("Octahedron",    lambda: get_cached("octahedron", _gen_octahedron)),
    # key 2
    ("Pyramid",       lambda: get_cached("pyramid", _gen_pyramid)),
    ("Cone",          lambda: get_cached("cone", _gen_cone)),
    # key 3
    ("Sphere",        lambda: get_cached("sphere", _gen_sphere,
                                         max(6, int(14 * config.density.value)))),
    ("Icosahedron",   lambda: get_cached("icosa", _gen_icosahedron)),
    # key 4
    ("Hexagon",       lambda: get_cached("hexagon", _gen_hexagon)),
    ("Octagon",       lambda: get_cached("octagon", _gen_octagon)),
    ("Star",          lambda: get_cached("star", _gen_star)),
    # key 5
    ("Cylinder",      lambda: get_cached("cylinder", _gen_cylinder,
                                         max(10, int(24 * config.density.value)),
                                         max(4, int(8 * config.density.value)))),
    ("Helix",         lambda: get_cached("helix", _gen_helix,
                                         max(80, int(200 * config.density.value)))),
    # key 6
    ("Torus",         lambda: get_cached("torus", _gen_torus,
                                         max(10, int(24 * config.density.value)),
                                         max(6, int(12 * config.density.value)))),
    ("Torus Knot",    lambda: get_cached("tknot", _gen_torus_knot,
                                         max(100, int(300 * config.density.value)))),
    # key 7
    ("Mobius Strip",  lambda: get_cached("mobius", _gen_mobius,
                                         max(20, int(60 * config.density.value)),
                                         max(4, int(8 * config.density.value)))),
    ("Trefoil Knot",  lambda: get_cached("trefoil", _gen_trefoil,
                                         max(100, int(300 * config.density.value)))),
    # key 8
    ("Klein 1",       lambda: get_cached("klein1", _gen_klein1,
                                         max(20, int(50 * config.density.value)),
                                         max(8, int(16 * config.density.value)))),
    ("Klein 2",       lambda: get_cached("klein2", _gen_klein2,
                                         max(20, int(50 * config.density.value)),
                                         max(8, int(16 * config.density.value)))),
    # key 9
    ("Lorenz",        lambda: get_cached("lorenz", _gen_lorenz,
                                         max(500, int(3000 * config.density.value)))),
    # key 0
    ("Mandelbrot",    lambda: get_cached("mandelbrot", _gen_mandelbrot,
                                         max(15, int(35 * config.density.value)),
                                         max(15, int(35 * config.density.value)))),
    ("Julia",         lambda: get_cached("julia", _gen_julia,
                                         max(15, int(35 * config.density.value)),
                                         max(15, int(35 * config.density.value)))),
]

SHAPE_KEY_GROUPS = {
    '1': [0, 1],
    '2': [2, 3],
    '3': [4, 5],
    '4': [6, 7, 8],
    '5': [9, 10],
    '6': [11, 12],
    '7': [13, 14],
    '8': [15, 16],
    '9': [17],
    '0': [18, 19],
}


def shape_key_for_index(idx):
    for key, group in SHAPE_KEY_GROUPS.items():
        if idx in group:
            return key
    return "?"


def draw_shape(idx, ax, ay, az, scale, scr, frame_count):
    _, get_geo = SHAPE_DEFS[idx]
    verts, edges = get_geo()

    xs, ys, zs = batch_rotate_project(verts, ax, ay, az, scale)

    mode = config.color_mode
    color_lut = None
    static_color = -1

    if mode == "shape":
        if config.shape_color_idx >= 0:
            static_color = SHAPE_COLORS[config.shape_color_idx % len(SHAPE_COLORS)]
        else:
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


# ── Non-blocking input with arrow keys ───────────────

_tty_saved = None


def tty_cbreak_on():
    global _tty_saved
    if os.name == "nt" or not sys.stdin.isatty():
        return
    import termios, tty
    fd = sys.stdin.fileno()
    _tty_saved = termios.tcgetattr(fd)
    tty.setcbreak(fd)


def tty_restore():
    global _tty_saved
    if _tty_saved is None:
        return
    import termios
    termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, _tty_saved)
    _tty_saved = None


def _read_char(fd, timeout):
    import select
    dr, _, _ = select.select([fd], [], [], timeout)
    if not dr:
        return None
    return os.read(fd, 1).decode("ascii", errors="ignore")


def get_key():
    if os.name == "nt":
        try:
            import msvcrt
        except ImportError:
            return None
        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            if ch in ('\x00', '\xe0'):
                ch2 = msvcrt.getwch()
                return {'H': 'UP', 'P': 'DOWN', 'K': 'LEFT', 'M': 'RIGHT'}.get(ch2)
            if ch == '\r':
                return 'ENTER'
            return ch
        return None
    else:
        if not sys.stdin.isatty():
            return None
        fd = sys.stdin.fileno()
        ch = _read_char(fd, 0)
        if ch is None:
            return None
        if ch == '\x1b':
            if _read_char(fd, 0.02) == '[':
                return {'A': 'UP', 'B': 'DOWN',
                        'C': 'RIGHT', 'D': 'LEFT'}.get(_read_char(fd, 0.02))
            return None
        if ch in ('\r', '\n'):
            return 'ENTER'
        return ch


# ── Audio Analyzer ───────────────────────────────────

class AudioAnalyzer:
    def __init__(self, sample_rate=22050, block_size=1024):
        self.sample_rate = sample_rate
        self.block_size = block_size
        self.running = False
        self.device_index = None
        self.device_name = "Default"
        self.last_error = ""
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
            # WASAPI only accepts the device's own rate (often 48000), so use
            # that and keep the block length near block_size at sample_rate
            info = sd.query_devices(self.device_index, kind="input")
            rate = int(info["default_samplerate"]) or self.sample_rate
            block = max(256, round(self.block_size * rate / self.sample_rate))
            self._stream = sd.InputStream(
                device=self.device_index,
                samplerate=rate,
                blocksize=block,
                channels=1,
                dtype="float32",
                callback=self._callback,
            )
            self._stream.start()
            self.running = True
            self.last_error = ""
            return True
        except Exception as e:
            self.running = False
            self.last_error = str(e)
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
        sens = config.audio_sens.value
        threshold = max(self._rms_slow * 3.0, 0.008) / sens
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

# Each host API (MME, DirectSound, WASAPI, WDM-KS on Windows) lists the same
# hardware again, so only list one: WASAPI on Windows (full names, only the
# devices enabled in Sound settings), the default host API elsewhere
def _listed_hostapi(hostapis):
    if os.name == "nt":
        for i, api in enumerate(hostapis):
            if "WASAPI" in api["name"]:
                return i
    return sd.default.hostapi


def list_audio_devices():
    if not HAS_AUDIO:
        return [], []
    try:
        devices = sd.query_devices()
        hostapis = sd.query_hostapis()
    except Exception:
        return [], []
    api_idx = _listed_hostapi(hostapis)
    api = hostapis[api_idx]
    inputs = []
    outputs = []
    for i in api["devices"]:
        dev = devices[i]
        name = dev["name"]
        if dev["max_input_channels"] > 0:
            is_default = (i == api["default_input_device"])
            inputs.append((i, name, is_default))
        if dev["max_output_channels"] > 0:
            is_default = (i == api["default_output_device"])
            outputs.append((i, name, is_default))
    return inputs, outputs


def _switch_audio_device(dev_idx, name):
    """Point audio at a device and restart it if audio is on. Returns a
    notice for the menu when the device can't be opened."""
    was_running = audio.running
    audio.stop()
    audio.device_index = dev_idx
    audio.device_name = name
    if not (was_running or config.audio_reactive):
        return ""
    if audio.start():
        return ""
    notice = f"Couldn't open {name}: {audio.last_error}"
    if dev_idx is not None:
        audio.device_index = None
        audio.device_name = "Default"
        if audio.start():
            return notice + " - using Default instead"
    config.audio_reactive = False
    return notice + " - audio is off"


# ── FPS tracking & adaptive throttle ─────────────────

class FPSTracker:
    def __init__(self, target=TARGET_FPS, window=30, settle=10):
        self.target = target
        self.settle = settle
        self.frame_times = deque(maxlen=window)
        self.work_times = deque(maxlen=window)
        self.effective_density = 1.0

    def tick(self, dt):
        self.frame_times.append(dt)

    def add_work(self, seconds):
        self.work_times.append(seconds)

    @property
    def fps(self):
        if not self.frame_times:
            return 60.0
        avg = sum(self.frame_times) / len(self.frame_times)
        return 1.0 / avg if avg > 0 else 60.0

    @property
    def uncapped_fps(self):
        # frame rate the render work alone allows; the main loop sleeps to
        # TARGET_FPS, so fps itself can never show spare headroom
        if not self.work_times:
            return float(self.target)
        work = sorted(self.work_times)[len(self.work_times) // 2]
        return 1.0 / work if work > 0 else 1000.0

    def adapt(self, base_density):
        if not config.fps_adapt:
            self.effective_density = base_density
            return base_density

        if self.effective_density > base_density:
            self.effective_density = base_density
            self.work_times.clear()
        if len(self.work_times) < self.settle:
            return self.effective_density

        fps = self.uncapped_fps
        old = self.effective_density

        if fps < FPS_FLOOR and old > 0.25:
            self.effective_density = max(0.25, old * 0.8)
        elif fps < self.target * 0.85 and old > 0.25:
            self.effective_density = max(0.25, old * 0.95)
        elif fps > self.target * 1.5 and old < base_density:
            self.effective_density = min(base_density, old * 1.15)

        if self.effective_density != old:
            self.work_times.clear()
        return self.effective_density


fps_tracker = FPSTracker()


# ── HUD ──────────────────────────────────────────────

def build_hud_line1(bpm_str=""):
    si = config.shape_index
    name = SHAPE_DEFS[si][0]
    key = shape_key_for_index(si)
    mode = config.color_mode
    pal = ""
    if mode == "depth":
        pal_name = DEPTH_PALETTES[
            config.depth_palette_idx % len(DEPTH_PALETTES)
        ][0]
        inv_tag = " INV" if config.depth_invert else ""
        pal = f"({pal_name}{inv_tag})"
    elif mode == "shape":
        if config.shape_color_idx >= 0:
            cname = SHAPE_COLOR_NAMES[config.shape_color_idx % len(SHAPE_COLOR_NAMES)]
            pal = f"({cname})"
        else:
            pal = "(auto)"
    res_label = RESOLUTION_PRESETS[config.resolution_idx][0]
    fps_str = f"{fps_tracker.fps:.0f}fps"
    parts = [
        f"[{key}] {name}",
        config.render_mode.upper(),
        f"color:{mode}{pal}",
        f"{WIDTH}x{HEIGHT}({res_label})",
        fps_str,
    ]
    if config.fps_adapt and fps_tracker.effective_density < config.density.value * 0.99:
        parts.append(f"THR:{fps_tracker.effective_density:.1f}")
    if not config.auto_rotate:
        parts.append("NOROT")
    if config.audio_reactive:
        status = bpm_str if bpm_str else "waiting..."
        onset_tag = ONSET_MODES[config.audio_onset_mode]
        parts.append(f"AUDIO:{status}({onset_tag})")
    if config.paused:
        parts.append("PAUSED")
    return "  ".join(p for p in parts if p)


def build_hud_line2():
    parts = [p.display() for p in config.all_params]
    parts.append(f"Brt:{'ON' if config.brightness_enabled else 'OFF'}")
    parts.append(f"Ramp:{config.brightness_ramp_idx}")
    return "  ".join(parts)


HELP_ITEMS = [
    "Spc=pause", "0-9=shape(x2=var)", "Shift+0-9=shpColor", "Arrows=rotXY",
    "<>/,.=rotZ", "r=reset", "o=autorot", "+/-=scl", "f/F=fov", "[/]=spd",
    "d/D=den", "p=points", "b=brt", "B=ramp", "c=color", "C=pal", "i=inv",
    "z/Z=depth", "s/S=auto", "a=audio", "n/N=sens", "g=onset", "A=dev",
    "R=res", "t=adapt", "h=hud", "m=menu", "P=panel", "?=help",
    "q=quit",
]


def build_hud_help(width):
    """Help items wrapped into as many lines as the width needs."""
    lines = [""]
    for item in HELP_ITEMS:
        if lines[-1] and len(lines[-1]) + 1 + len(item) > width:
            lines.append("")
        lines[-1] = f"{lines[-1]} {item}" if lines[-1] else item
    return lines


# ── Settings registry ────────────────────────────────
# One list of settings drives the overlay menu, the settings panel and the
# saved settings file.

class Setting:
    """kind is 'param' (wraps a Param), 'choice' (an index into choices)
    or 'toggle'. For params, set_hook runs after every change."""

    def __init__(self, key, label, kind, get=None, set=None, param=None,
                 choices=None, set_hook=None):
        self.key = key
        self.label = label
        self.kind = kind
        self.param = param
        self._get = get
        self._set = set
        self._choices = choices
        self._hook = set_hook

    def choices(self):
        return self._choices

    def get(self):
        if self.kind == "param":
            return self.param.value
        return self._get()

    def set(self, value):
        if self.kind == "param":
            p = self.param
            p.value = clamp(float(value), p.lo, p.hi)
            if self._hook:
                self._hook(p.value)
        elif self.kind == "toggle":
            self._set(bool(value))
        else:
            self._set(int(value) % len(self._choices))

    def step(self, direction):
        if self.kind == "param":
            if direction > 0:
                self.param.increase()
            else:
                self.param.decrease()
            if self._hook:
                self._hook(self.param.value)
        elif self.kind == "toggle":
            self.set(not self.get())
        else:
            self.set(self.get() + direction)

    def display(self):
        if self.kind == "param":
            return self.param.display().split(":", 1)[1]
        if self.kind == "toggle":
            return "ON" if self.get() else "OFF"
        return self._choices[self.get() % len(self._choices)]


def _set_audio(on):
    config.audio_reactive = on
    if not on:
        audio.stop()
    elif not audio.running and not audio.start():
        config.audio_reactive = False


def _set_adapt(on):
    config.fps_adapt = on
    if on:
        fps_tracker.effective_density = config.density.value


def _follow_speed(v):
    # Y spin keeps its 5:6 ratio to X spin
    sy = config.speed_y
    sy.value = clamp(v * 5 / 6, sy.lo, sy.hi)


def build_settings():
    c = config

    def choice(key, label, attr, choices):
        return Setting(key, label, "choice", choices=choices,
                       get=lambda: getattr(c, attr),
                       set=lambda v: setattr(c, attr, v))

    def toggle(key, label, attr, setter=None):
        return Setting(key, label, "toggle",
                       get=lambda: getattr(c, attr),
                       set=setter or (lambda v: setattr(c, attr, v)))

    def param(key, label, p, hook=None):
        return Setting(key, label, "param", param=p, set_hook=hook)

    shape_names = [f"[{shape_key_for_index(i)}] {name}"
                   for i, (name, _) in enumerate(SHAPE_DEFS)]
    return [
        choice("shape", "Shape", "shape_index", shape_names),
        Setting("render", "Render", "choice", choices=["wire", "points"],
                get=lambda: 0 if c.render_mode == "wire" else 1,
                set=lambda v: setattr(c, "render_mode", ("wire", "points")[v])),
        param("scale", "Scale", c.scale),
        param("fov", "FOV", c.fov),
        param("speed", "Speed", c.speed_x, _follow_speed),
        param("density", "Density", c.density),
        param("auto_switch", "Auto switch", c.auto_switch),
        param("depth_range", "Depth range", c.depth_range),
        param("audio_sens", "Audio sens", c.audio_sens),
        toggle("auto_rotate", "Auto rotate", "auto_rotate"),
        toggle("paused", "Paused", "paused"),
        toggle("brightness", "Brightness", "brightness_enabled"),
        choice("ramp", "Brt ramp", "brightness_ramp_idx",
               [repr(r) for r in BRIGHTNESS_RAMPS]),
        choice("color_mode", "Color mode", "color_mode_idx", COLOR_MODES),
        choice("palette", "Palette", "depth_palette_idx",
               [name for name, _ in DEPTH_PALETTES]),
        toggle("invert", "Depth invert", "depth_invert"),
        Setting("shape_color", "Shape color", "choice",
                choices=["auto (per shape)"] + SHAPE_COLOR_NAMES,
                get=lambda: c.shape_color_idx + 1,
                set=lambda v: setattr(c, "shape_color_idx", v - 1)),
        toggle("audio", "Audio react", "audio_reactive", _set_audio),
        choice("onset", "Onset mode", "audio_onset_mode", ONSET_MODES),
        toggle("adapt", "FPS adapt", "fps_adapt", _set_adapt),
        toggle("hud", "HUD overlay", "hud_visible"),
        choice("resolution", "Resolution", "resolution_idx",
               [label for label, _, _ in RESOLUTION_PRESETS]),
    ]


# ── Saved settings and crash log ─────────────────────

NOT_SAVED = {"paused", "fov"}           # fov is saved relative to the grid
RESTORED_BY_RUN = {"audio", "resolution"}


def settings_dir():
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return os.path.join(base, "ASCII3DShapes")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/ASCII3DShapes")
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "ascii3dshapes")


def load_saved():
    try:
        with open(os.path.join(settings_dir(), "settings.json"),
                  encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def restore_settings(settings, data):
    for s in settings:
        if s.key in data and s.key not in NOT_SAVED | RESTORED_BY_RUN:
            try:
                s.set(data[s.key])
            except (TypeError, ValueError):
                pass


def save_settings(settings, extra):
    data = {s.key: s.get() for s in settings if s.key not in NOT_SAVED}
    data.update(extra)
    path = os.path.join(settings_dir(), "settings.json")
    try:
        os.makedirs(settings_dir(), exist_ok=True)
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
        os.replace(path + ".tmp", path)
    except OSError:
        pass


def write_crash_log(text):
    path = os.path.join(settings_dir(), "crash.log")
    try:
        os.makedirs(settings_dir(), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} "
                    f"v{APP_VERSION} {sys.platform}\n{text}\n")
        return path
    except OSError:
        return None


# ── Menus drawn over the shape ───────────────────────

MENU_ACTIONS = [
    ("Audio device...", "A"),
    ("Resolution...", "R"),
    ("Settings panel...", "P"),
    ("Reset rotation", "r"),
    ("Reset all settings", "RESET_ALL"),
    ("Close menu", "x"),
    ("Quit", "q"),
]

HELP_LINES = [
    "Mouse (window)",
    "  Left-drag rotate   Right-drag spin   Wheel zoom",
    "  Middle-click reset rotation   buttons along the bottom",
    "",
    "Keys",
    "  Space pause          q quit            m menu",
    "  P settings panel     ? or F1 help      h HUD on/off",
    "  F11 or Alt+Enter fullscreen (window)   Esc close / leave",
    "  0-9 shape (again = variant)   Shift+0-9 shape color",
    "  Arrows rotate X/Y   < > or , . rotate Z   r reset   o auto-rotate",
    "  + - scale   f F field of view   [ ] speed   d D density",
    "  p wire/points   b brightness   B ramp   z Z depth range",
    "  c color mode   C palette   i invert depth",
    "  s S auto-switch time   t adaptive density   R resolution",
    "  a audio on/off   A input device   n N sensitivity   g onsets",
]


class Overlay:
    """The open menu: None, 'menu', 'audio', 'resolution' or 'help'."""

    def __init__(self):
        self.mode = None
        self.parent = None
        self.cursor = 0
        self.menu_cursor = 0
        self.notice = ""
        self.inputs = []     # audio devices, listed when the audio menu opens
        self.box = None      # (x, y, w, h) as last drawn
        self.hits = []       # (row y, item index, value x0, value x1)

    def open(self, mode, parent=None):
        if self.mode == "menu":
            self.menu_cursor = self.cursor
        self.mode, self.parent, self.notice = mode, parent, ""
        self.cursor = 0
        if mode == "menu":
            self.cursor = self.menu_cursor
        elif mode == "resolution":
            self.cursor = config.resolution_idx
        elif mode == "audio":
            self.inputs = list_audio_devices()[0]
            for i, (idx, _, is_def) in enumerate(self.inputs):
                if idx == audio.device_index or (
                        audio.device_index is None and is_def):
                    self.cursor = i

    def back(self):
        parent = self.parent
        self.mode, self.parent, self.box = None, None, None
        if parent:
            self.open(parent)

    def close_all(self):
        if self.mode == "menu":
            self.menu_cursor = self.cursor
        self.mode, self.parent, self.box = None, None, None

    def contains(self, col, row):
        if self.box is None:
            return False
        x, y, w, h = self.box
        return x <= col < x + w and y <= row < y + h

    def item_count(self, settings):
        if self.mode == "menu":
            return len(settings) + len(MENU_ACTIONS)
        if self.mode == "audio":
            return len(self.inputs) if HAS_AUDIO else 0
        if self.mode == "resolution":
            return len(RESOLUTION_PRESETS)
        return 0


def overlay_content(ov, settings, frontend):
    """Title, rows and footer of the open menu. Rows are (text, value span,
    selectable); the span marks the '< value >' part of a setting row."""
    rows = []
    if ov.mode == "menu":
        title = f"{APP_NAME} v{APP_VERSION} - Settings"
        for s in settings:
            label = f"{s.label + ':':<14} "
            text = f"{label}< {s.display()} >"
            rows.append((text, (len(label), len(text)), True))
        rows.append(("", None, False))
        rows.extend((label, None, True) for label, _ in MENU_ACTIONS)
        stats = f"FPS {fps_tracker.fps:.0f}"
        if config.fps_adapt:
            stats += f"  eff. density {fps_tracker.effective_density:.2f}"
        footer = [f"{stats}  audio: {audio.device_name}",
                  "Up/Down select  Left/Right change  Enter run  x close"]
    elif ov.mode == "audio":
        title = "Audio input device"
        if not HAS_AUDIO:
            rows.append(("Audio needs the sounddevice package and PortAudio.",
                         None, False))
            if sys.platform.startswith("linux"):
                rows.append(("On Linux: sudo apt install libportaudio2",
                             None, False))
        elif not ov.inputs:
            rows.append(("No input devices found.", None, False))
        for idx, name, is_def in (ov.inputs if HAS_AUDIO else []):
            active = idx == audio.device_index or (
                audio.device_index is None and is_def)
            tags = (" [default]" if is_def else "") + (" *active*" if active else "")
            rows.append((name + tags, None, True))
        running = " (running)" if audio.running else ""
        footer = [f"Selected: {audio.device_name}{running}"]
        if ov.notice:
            footer.append(ov.notice)
        footer.append("Enter use device  d default  x back")
    elif ov.mode == "resolution":
        title = "Resolution"
        for i, (label, _, _) in enumerate(RESOLUTION_PRESETS):
            mark = "*" if i == config.resolution_idx else " "
            rows.append((f"{mark} {label:<8} {frontend.preset_note(i)}", None, True))
        footer = [f"Current: {WIDTH}x{HEIGHT} characters", "Enter use  x back"]
    else:
        title = "Help"
        rows = [(line, None, False) for line in HELP_LINES]
        footer = ["Any key or click closes this"]
    return title, rows, footer


def draw_overlay(scr, ov, settings, frontend):
    title, rows, footer = overlay_content(ov, settings, frontend)
    inner = max([len(title)] + [len(r[0]) for r in rows] + [len(f) for f in footer])
    bw = min(scr.w, inner + 4)
    fixed = 5 + len(footer)            # padding, title, blank lines, footer
    room = max(1, scr.h - fixed)
    selectable = [i for i, r in enumerate(rows) if r[2]]
    ov.cursor = clamp(ov.cursor, 0, max(0, len(selectable) - 1))
    sel_row = selectable[ov.cursor] if selectable else -1
    start = 0
    if len(rows) > room:
        start = clamp(sel_row - room // 2, 0, len(rows) - room)
    visible = rows[start:start + room]
    bh = min(scr.h, fixed + len(visible))
    x = max(0, (scr.w - bw) // 2)
    y = max(0, (scr.h - bh) // 2)
    ov.box = (x, y, bw, bh)
    ov.hits = []
    width = bw - 4

    scr.fill_rect(x, y, bw, bh, UI_BG)
    scr.put_text(x + 2, y + 1, title[:width], fg=UI_ACCENT, bg=UI_BG)
    ry = y + 3
    for i, (text, span, sel) in enumerate(visible, start):
        current = i == sel_row
        bg = UI_SEL_BG if current else UI_BG
        if current:
            scr.fill_rect(x + 1, ry, bw - 2, 1, bg)
        scr.put_text(x + 2, ry, text[:width], fg=255 if current else UI_TEXT, bg=bg)
        if sel:
            v0 = x + 2 + span[0] if span else None
            v1 = x + 2 + span[1] if span else None
            ov.hits.append((ry, selectable.index(i), v0, v1))
        ry += 1
    ry += 1
    for line in footer:
        scr.put_text(x + 2, ry, line[:width], fg=UI_DIM, bg=UI_BG)
        ry += 1


def _menu_activate(ov, settings, how):
    if ov.cursor < len(settings):
        settings[ov.cursor].step(-1 if how == "LEFT" else 1)
        return []
    if how != "ENTER":
        return []
    _, key = MENU_ACTIONS[ov.cursor - len(settings)]
    if key == "A":
        ov.open("audio", parent="menu")
    elif key == "R":
        ov.open("resolution", parent="menu")
    elif key == "x":
        ov.back()
    else:
        return [{"P": "panel", "r": "reset_angles", "RESET_ALL": "reset_all",
                 "q": "quit"}[key]]
    return []


def overlay_key(ov, ch, settings):
    """Handle a key while a menu is open; returns actions for the main loop."""
    if ov.mode == "help":
        ov.back()
        return []
    if ch in ("x", "ESC") or (ch == "m" and ov.mode == "menu"):
        ov.back()
        return []
    if ch == "q":
        return ["quit"]
    if ch == "UP":
        ov.cursor = max(0, ov.cursor - 1)
    elif ch == "DOWN":
        ov.cursor = min(ov.item_count(settings) - 1, ov.cursor + 1)
    elif ov.mode == "menu":
        if ch in ("LEFT", "RIGHT", "ENTER"):
            return _menu_activate(ov, settings, ch)
        if ch == "A":
            ov.open("audio", parent="menu")
        elif ch == "R":
            ov.open("resolution", parent="menu")
        elif ch == "P":
            return ["panel"]
        elif ch == "r":
            return ["reset_angles"]
    elif ov.mode == "audio":
        if ch == "ENTER" and HAS_AUDIO and ov.inputs:
            idx, name, _ = ov.inputs[ov.cursor]
            ov.notice = _switch_audio_device(idx, name)
        elif ch == "d" and HAS_AUDIO:
            ov.notice = _switch_audio_device(None, "Default")
    elif ov.mode == "resolution":
        if ch == "ENTER":
            config.resolution_idx = ov.cursor
    return []


def overlay_click(ov, col, row, button, settings):
    if not ov.contains(col, row):
        ov.close_all()
        return []
    if ov.mode == "help":
        ov.back()
        return []
    for ry, idx, v0, v1 in ov.hits:
        if ry != row:
            continue
        ov.cursor = idx
        if v0 is not None and v0 <= col < v1:
            left = button == 3 or col < (v0 + v1) // 2
            return overlay_key(ov, "LEFT" if left else "RIGHT", settings)
        if ov.mode == "menu" and idx < len(settings) and settings[idx].kind == "param":
            return []              # clicking a slider's name just selects it
        return overlay_key(ov, "ENTER", settings)
    return []


def overlay_wheel(ov, dy, col, row, settings):
    """Wheel over a setting changes it; elsewhere in the menu it scrolls."""
    for ry, idx, v0, _ in ov.hits:
        if ry == row and ov.mode == "menu" and idx < len(settings):
            ov.cursor = idx
            settings[idx].step(1 if dy > 0 else -1)
            return
    ov.cursor = clamp(ov.cursor - dy, 0, max(0, ov.item_count(settings) - 1))


# ── Window button bar ────────────────────────────────

def button_bar_items():
    return [
        ("Menu", "m"),
        ("Settings", "P"),
        ("< Shape", "PREV_SHAPE"),
        ("Shape >", "NEXT_SHAPE"),
        ("Play" if config.paused else "Pause", " "),
        ("Points" if config.render_mode == "wire" else "Wire", "p"),
        (f"Color: {config.color_mode}", "c"),
        ("Palette", "C"),
        ("Audio: on" if config.audio_reactive else "Audio: off", "a"),
        ("Fullscreen", "F11"),
        ("Help", "?"),
        ("Quit", "q"),
    ]


def draw_button_bar(scr, hover):
    """Draw the bar on the bottom row; returns (x0, x1, y, key) hit areas."""
    y = scr.h - 1
    scr.fill_rect(0, y, scr.w, 1, UI_BAR_BG)
    hits = []
    x = 1
    for label, key in button_bar_items():
        text = f" {label} "
        if x + len(text) > scr.w:
            break
        hovered = hover[1] == y and x <= hover[0] < x + len(text)
        scr.put_text(x, y, text, fg=255 if hovered else UI_TEXT,
                     bg=UI_SEL_BG if hovered else UI_BTN_BG)
        hits.append((x, x + len(text), y, key))
        x += len(text) + 1
    return hits


def button_at(hits, col, row):
    for x0, x1, y, key in hits:
        if y == row and x0 <= col < x1:
            return key
    return None


def handle_common_key(ch):
    if config.handle_key(ch):
        return True

    if ch in SHAPE_KEY_GROUPS:
        group = SHAPE_KEY_GROUPS[ch]
        if config.shape_index in group:
            pos = group.index(config.shape_index)
            config.shape_index = group[(pos + 1) % len(group)]
        else:
            config.shape_index = group[0]
        return True
    elif ch in SHIFT_NUM_MAP:
        config.shape_color_idx = SHIFT_NUM_MAP[ch]
        return True
    elif ch == "p":
        config.render_mode = (
            "points" if config.render_mode == "wire" else "wire"
        )
        return True
    elif ch == "o":
        config.auto_rotate = not config.auto_rotate
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
    elif ch == "i":
        config.depth_invert = not config.depth_invert
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
    elif ch == "g":
        config.audio_onset_mode = (
            (config.audio_onset_mode + 1) % len(ONSET_MODES)
        )
        return True
    elif ch == "t":
        config.fps_adapt = not config.fps_adapt
        if config.fps_adapt:
            fps_tracker.effective_density = config.density.value
        return True
    elif ch == "h":
        config.hud_visible = not config.hud_visible
        return True
    return False


# ── Link to the settings panel process ───────────────

class PanelLink:
    """The Tk settings panel runs as its own process, because Tk and SDL
    can't share one on macOS. Settings travel as JSON lines over its
    stdin and stdout."""

    def __init__(self):
        self.proc = None
        self.inbox = deque()
        self.last_state = None
        self.notice = ""

    def alive(self):
        return self.proc is not None and self.proc.poll() is None

    def open(self, meta):
        """Start the panel, or leave the running one alone. Returns an
        error message, or "" on success."""
        if self.alive():
            return ""
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--panel"]
        else:
            cmd = [sys.executable, os.path.abspath(__file__), "--panel"]
        try:
            self.proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                bufsize=1)
        except OSError as e:
            self.proc = None
            return str(e)
        self.last_state = None
        threading.Thread(target=self._read, args=(self.proc,),
                         daemon=True).start()
        self.send(meta)
        return ""

    def _read(self, proc):
        for line in proc.stdout:
            try:
                self.inbox.append(json.loads(line))
            except ValueError:
                pass

    def poll(self):
        msgs = []
        while self.inbox:
            msgs.append(self.inbox.popleft())
        return msgs

    def send(self, obj):
        if not self.alive():
            return
        try:
            self.proc.stdin.write(json.dumps(obj) + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError):
            pass

    def send_state(self, state):
        if state != self.last_state:
            self.send({"state": state})
            self.last_state = state

    def close(self):
        if not self.alive():
            return
        self.send({"quit": True})
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=1.0)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            self.proc.kill()


def panel_meta(settings):
    meta = []
    for s in settings:
        m = {"key": s.key, "label": s.label, "kind": s.kind}
        if s.kind == "param":
            p = s.param
            m.update(lo=p.lo, hi=p.hi, log=p.multiplicative, fmt=p.fmt)
        elif s.kind == "choice":
            m["choices"] = s.choices()
        meta.append(m)
    devices = ["Default"] + [name for _, name, _ in list_audio_devices()[0]]
    return {"meta": meta, "audio_devices": devices}


def panel_state(settings, panel):
    state = {s.key: s.get() for s in settings}
    state["audio_device"] = audio.device_name
    state["notice"] = panel.notice
    return state


def apply_panel_message(msg, by_key, panel):
    """Apply one message from the panel; returns actions for the main loop."""
    if not isinstance(msg, dict):
        return []
    key = msg.get("set")
    if key == "audio_device" and HAS_AUDIO:
        name = msg.get("value")
        idx = None
        for dev_idx, dev_name, _ in list_audio_devices()[0]:
            if dev_name == name:
                idx = dev_idx
        panel.notice = _switch_audio_device(idx, name if idx is not None else "Default")
    elif key in by_key:
        try:
            by_key[key].set(msg.get("value"))
        except (TypeError, ValueError):
            pass
    action = msg.get("do")
    if action in ("reset_angles", "fullscreen", "reset_all"):
        return [action]
    return []


# ── Main loop ─────────────────────────────────────────

class View:
    def __init__(self):
        self.ax = self.ay = self.az = 0.0

    def reset(self):
        self.ax = self.ay = self.az = 0.0


def run(frontend, saved):
    """Render until the user quits. frontend is a TerminalFrontend or a
    WindowFrontend that has already been started."""
    global WIDTH, HEIGHT

    settings = build_settings()
    by_key = {s.key: s for s in settings}
    defaults = {s.key: s.get() for s in settings}
    restore_settings(settings, saved)
    res = saved.get("resolution", 0)
    if isinstance(res, int) and 0 <= res < len(RESOLUTION_PRESETS):
        config.resolution_idx = res
    config.audio_reactive = bool(saved.get("audio", config.audio_reactive))
    dev_name = saved.get("audio_device")
    for idx, name, _ in list_audio_devices()[0]:
        if name == dev_name:
            audio.device_index, audio.device_name = idx, name

    WIDTH, HEIGHT = frontend.grid_size(config.resolution_idx)
    applied_res = config.resolution_idx
    fit = saved.get("fov_fit")
    if not isinstance(fit, (int, float)) and frontend.is_window:
        # FOV 65 was tuned on a ~200x55 terminal; start windows at that look
        fit = 65.0 / fov_for_size(*FOV_REF_GRID)
    if isinstance(fit, (int, float)):
        fov = config.fov
        fov.value = clamp(fit * fov_for_size(WIDTH, HEIGHT), fov.lo, fov.hi)
    fps_tracker.effective_density = config.density.value
    if config.audio_reactive and not audio.start():
        config.audio_reactive = False

    scr = ScreenBuffer(WIDTH, HEIGHT)
    overlay = Overlay()
    panel = PanelLink()
    view = View()
    last_switch = time.time()
    last_frame = time.time()
    last_panel_send = 0.0
    frame_count = 0
    audio_punch = 0.0
    audio_bpm = 120.0
    need_resize = False
    low_fps_frames = 0
    low_fps_hint = ""
    message = ("", 0.0)          # short notice and when it disappears
    bar_hits = []

    def do_action(act):
        nonlocal need_resize, message
        if act == "quit":
            return True
        if act == "reset_angles":
            view.reset()
        elif act == "fullscreen":
            frontend.toggle_fullscreen()
            need_resize = True
        elif act == "panel":
            err = panel.open(panel_meta(settings))
            if err:
                message = (f"Settings panel couldn't open: {err}", time.time() + 5)
        elif act == "reset_all":
            for s in settings:
                if s.key not in ("audio", "resolution"):
                    s.set(defaults[s.key])
            config.fov.value = 65.0
            if frontend.is_window:
                config.fov.value *= fov_for_size(WIDTH, HEIGHT) / fov_for_size(*FOV_REF_GRID)
        return False

    def press(ch):
        if overlay.mode:
            return overlay_key(overlay, ch, settings)
        if ch == " ":
            config.paused = not config.paused
        elif ch == "q":
            return ["quit"]
        elif ch == "UP":
            view.ax -= ARROW_ROT_DELTA
        elif ch == "DOWN":
            view.ax += ARROW_ROT_DELTA
        elif ch == "LEFT":
            view.ay -= ARROW_ROT_DELTA
        elif ch == "RIGHT":
            view.ay += ARROW_ROT_DELTA
        elif ch in ("<", ","):
            view.az -= ARROW_ROT_DELTA
        elif ch in (">", "."):
            view.az += ARROW_ROT_DELTA
        elif ch == "R":
            overlay.open("resolution")
        elif ch == "A":
            overlay.open("audio")
        elif ch == "m":
            overlay.open("menu")
        elif ch == "?":
            overlay.open("help")
        elif ch == "r":
            view.reset()
        elif ch == "P":
            return ["panel"]
        elif ch == "F11":
            return ["fullscreen"]
        elif ch == "ESC":
            if getattr(frontend, "fullscreen", False):
                return ["fullscreen"]
        elif ch == "PREV_SHAPE":
            config.shape_index = (config.shape_index - 1) % len(SHAPE_DEFS)
        elif ch == "NEXT_SHAPE":
            config.shape_index = (config.shape_index + 1) % len(SHAPE_DEFS)
        else:
            handle_common_key(ch)
        return []

    try:
        while True:
            now = time.time()
            dt = now - last_frame
            last_frame = now
            dt_scale = dt / 0.03 if dt > 0 else 1.0

            fps_tracker.tick(dt)

            if not config.fps_adapt and fps_tracker.fps < 6.0:
                low_fps_frames += 1
                if low_fps_frames > 60:
                    low_fps_hint = "  LOW FPS! Press 't' to enable adaptive mode"
            else:
                low_fps_frames = max(0, low_fps_frames - 2)
                if low_fps_frames == 0:
                    low_fps_hint = ""

            shape_before = config.shape_index
            for ev in frontend.events():
                kind = ev[0]
                acts = []
                if kind == "quit":
                    return
                elif kind == "resize":
                    need_resize = True
                elif kind == "key":
                    acts = press(ev[1])
                elif kind == "click":
                    _, col, row, button = ev
                    if overlay.mode:
                        acts = overlay_click(overlay, col, row, button, settings)
                    elif button_at(bar_hits, col, row):
                        acts = press(button_at(bar_hits, col, row))
                    elif button == 2:
                        view.reset()
                elif kind == "wheel":
                    _, dy, col, row = ev
                    if overlay.mode and overlay.contains(col, row):
                        overlay_wheel(overlay, dy, col, row, settings)
                    else:
                        for _ in range(min(abs(dy), 5)):
                            if dy > 0:
                                config.scale.increase()
                            else:
                                config.scale.decrease()
                elif kind == "drag":
                    _, dx, dy, button, col0, row0 = ev
                    if overlay.contains(col0, row0) or button_at(bar_hits, col0, row0):
                        continue
                    if button == 1:
                        view.ay -= dx * DRAG_ROT
                        view.ax -= dy * DRAG_ROT
                    elif button == 3:
                        view.az -= dx * DRAG_ROT
                for act in acts:
                    if do_action(act):
                        return

            for msg in panel.poll():
                if isinstance(msg, dict) and msg.get("error"):
                    message = (f"Settings panel: {msg['error']}", now + 8)
                    continue
                for act in apply_panel_message(msg, by_key, panel):
                    if do_action(act):
                        return

            if config.shape_index != shape_before:
                last_switch = now        # a picked shape stays a while

            if config.resolution_idx != applied_res:
                applied_res = config.resolution_idx
                need_resize = True
            if need_resize:
                need_resize = False
                apply_resolution(frontend)
                scr = ScreenBuffer(WIDTH, HEIGHT)
                frontend.clear()

            if (not (config.audio_reactive and audio.running)
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
                    mode = config.audio_onset_mode
                    do_punch = mode <= 3
                    do_shape = mode in (0, 1, 4, 5)
                    do_palette = mode in (0, 2, 4, 6)

                    if do_punch:
                        audio_punch = 1.0
                    if do_shape:
                        config.shape_index = random.randrange(len(SHAPE_DEFS))
                    if do_palette:
                        config.depth_palette_idx = (
                            (config.depth_palette_idx + 1) % len(DEPTH_PALETTES)
                        )
                    last_switch = now

                audio_punch *= 0.85 ** dt_scale

            elif config.audio_reactive and not audio.running:
                bpm_str = "waiting..."

            draw_scale = config.scale.value
            if config.audio_reactive and audio.running:
                sens = config.audio_sens.value
                draw_scale *= (
                    1.0 + audio_punch * 0.5 * sens + audio_rms * 2.0 * sens
                )

            eff_density = fps_tracker.adapt(config.density.value)
            eff_density = round(eff_density * 20) / 20
            eff_density = max(0.25, eff_density)
            saved_density = config.density.value
            config.density.value = eff_density

            work_start = time.time()
            scr.clear()

            si = config.shape_index
            draw_shape(si, view.ax, view.ay, view.az, draw_scale, scr, frame_count)

            config.density.value = saved_density

            hover = getattr(frontend, "mouse_cell", (-1, -1))
            if config.hud_visible:
                scr.put_text(0, 0, build_hud_line1(bpm_str))
                scr.put_text(0, 1, build_hud_line2())
                if low_fps_hint:
                    scr.put_text(0, 2, low_fps_hint)
                if not frontend.is_window:
                    help_lines = build_hud_help(WIDTH)
                    for i, line in enumerate(help_lines):
                        scr.put_text(0, HEIGHT - len(help_lines) + i, line)
            if message[0] and now < message[1]:
                scr.put_text(0, 3, message[0], fg=0, bg=214)
            bar_hits = []
            if frontend.is_window and (config.hud_visible or hover[1] >= HEIGHT - 2):
                bar_hits = draw_button_bar(scr, hover)
            if overlay.mode:
                draw_overlay(scr, overlay, settings, frontend)

            frontend.present(scr)
            fps_tracker.add_work(time.time() - work_start)

            if panel.alive() and now - last_panel_send > 0.1:
                last_panel_send = now
                panel.send_state(panel_state(settings, panel))

            if (not config.paused and config.auto_rotate
                    and not getattr(frontend, "dragging", False)):
                if config.audio_reactive and audio.running:
                    bps = audio_bpm / 60.0
                    view.ax += bps * 1.0 * dt
                    view.ay += bps * 0.83 * dt
                else:
                    view.ax += config.speed_x.value * dt_scale
                    view.ay += config.speed_y.value * dt_scale

            frame_count += 1

            target_dt = 1.0 / TARGET_FPS
            elapsed = time.time() - now
            sleep_time = target_dt - elapsed
            if sleep_time > 0.001:
                time.sleep(sleep_time)

    finally:
        extra = {"fov_fit": config.fov.value / fov_for_size(WIDTH, HEIGHT),
                 "audio_device": audio.device_name}
        extra.update(frontend.saved_state())
        save_settings(settings, extra)
        panel.close()
        audio.stop()


# ── Terminal front end ───────────────────────────────

def _enable_windows_ansi():
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        handle = k32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if k32.GetConsoleMode(handle, ctypes.byref(mode)):
            k32.SetConsoleMode(handle, mode.value | 0x0004)  # VT processing
    except (AttributeError, OSError):
        pass


class TerminalFrontend:
    is_window = False

    def __init__(self):
        self._size = None
        self._checked = 0.0

    def start(self, saved):
        if os.name == "nt":
            _enable_windows_ansi()
        self._size = terminal_size()
        sys.stdout.write("\033[?25l\033[2J\033[H")
        sys.stdout.flush()
        tty_cbreak_on()

    def stop(self):
        tty_restore()
        sys.stdout.write("\033[?25h" + COLOR_RESET + "\033[2J\033[H")
        sys.stdout.flush()
        print("Goodbye.")

    def grid_size(self, preset_idx):
        tw, th = terminal_size()
        _, pw, ph = RESOLUTION_PRESETS[preset_idx]
        if pw is None:
            return tw, th
        return min(pw, tw), min(ph, th)

    def preset_note(self, preset_idx):
        tw, th = terminal_size()
        _, pw, ph = RESOLUTION_PRESETS[preset_idx]
        if pw is None:
            return f"{tw}x{th} (whole terminal)"
        note = f"{pw}x{ph}"
        if pw > tw or ph > th:
            note += f" -> {min(pw, tw)}x{min(ph, th)} (terminal is smaller)"
        return note

    def events(self):
        evs = []
        now = time.time()
        if now - self._checked > 0.5:
            self._checked = now
            size = terminal_size()
            if size != self._size:
                self._size = size
                evs.append(("resize",))
        for _ in range(32):
            ch = get_key()
            if ch is None:
                break
            evs.append(("key", ch))
        return evs

    def present(self, scr):
        sys.stdout.write("\033[H" + scr.render_ansi())
        sys.stdout.flush()

    def clear(self):
        sys.stdout.write("\033[2J\033[H")

    def toggle_fullscreen(self):
        pass

    def saved_state(self):
        return {}

    def show_error(self, lines):
        print("\n".join(lines))


# ── Window front end (pygame) ────────────────────────

def _windows_dpi_scale():
    """Make the window DPI aware so text stays sharp; returns the scale."""
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()
        return ctypes.windll.user32.GetDpiForSystem() / 96.0
    except (AttributeError, OSError):
        return 1.0


class WindowFrontend:
    """Draws the character grid in its own window with a monospace font."""
    is_window = True
    FONT_NAMES = ("consolas,menlo,dejavusansmono,liberationmono,ubuntumono,"
                  "couriernew,courier")
    BACKGROUND = (12, 12, 16)
    DEFAULT_FG = (204, 204, 204)

    def __init__(self):
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        import pygame
        self.pg = pygame
        self.surface = None
        self.fullscreen = False
        self.windowed_size = (1280, 800)
        self.base_font = 16
        self.font_path = None
        self.fonts = {}
        self.font = None
        self.cell = (9, 19)
        self.offset = (0, 0)
        self.glyphs = {}
        self.mouse_cell = (-1, -1)
        self.dragging = False
        self._press = None        # (button, (x, y)) of the held mouse button
        self._last_pos = (0, 0)

    def start(self, saved):
        pg = self.pg
        scale = _windows_dpi_scale() if os.name == "nt" else 1.0
        pg.display.init()
        pg.font.init()
        pg.display.set_caption(f"{APP_NAME} v{APP_VERSION}")
        pg.key.set_repeat(300, 35)
        self.base_font = max(8, round(16 * scale))
        self.font_path = pg.font.match_font(self.FONT_NAMES)
        dw, dh = pg.display.get_desktop_sizes()[0]
        size = saved.get("window")
        if not (isinstance(size, list) and len(size) == 2
                and all(isinstance(v, int) for v in size)):
            size = [min(1600, int(dw * 0.8)), min(1000, int(dh * 0.8))]
        self.windowed_size = (clamp(size[0], 320, dw), clamp(size[1], 200, dh))
        self.fullscreen = bool(saved.get("fullscreen", False))
        self._set_mode()

    def _set_mode(self):
        pg = self.pg
        if self.fullscreen:
            self.surface = pg.display.set_mode((0, 0), pg.FULLSCREEN)
        else:
            self.surface = pg.display.set_mode(self.windowed_size, pg.RESIZABLE)
        self.glyphs.clear()

    def stop(self):
        self.pg.quit()

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        self._set_mode()

    def saved_state(self):
        return {"window": list(self.windowed_size), "fullscreen": self.fullscreen}

    def _font(self, size):
        font = self.fonts.get(size)
        if font is None:
            font = self.pg.font.Font(self.font_path, size)
            self.fonts[size] = font
        return font

    @staticmethod
    def _cell_of(font):
        return max(1, font.size("M")[0]), max(1, font.get_linesize())

    def _fit_font(self, w, h, cols, rows):
        """Largest font size that fits cols x rows characters in w x h."""
        cw, ch = self._cell_of(self._font(100))
        size = int(clamp(100 * min(w / (cols * cw), h / (rows * ch)), 6, 96))
        while size > 6:
            cw, ch = self._cell_of(self._font(size))
            if cols * cw <= w and rows * ch <= h:
                break
            size -= 1
        return size

    def grid_size(self, preset_idx):
        self.surface = self.pg.display.get_surface()
        w, h = self.surface.get_size()
        _, pw, ph = RESOLUTION_PRESETS[preset_idx]
        size = self.base_font if pw is None else self._fit_font(w, h, pw, ph)
        font = self._font(size)
        cw, ch = self._cell_of(font)
        if pw is None:
            cols, rows = w // cw, h // ch
        else:
            cols, rows = min(pw, w // cw), min(ph, h // ch)
        cols, rows = max(20, cols), max(8, rows)
        if font is not self.font:
            self.font = font
            self.glyphs.clear()
        self.cell = (cw, ch)
        self.offset = (max(0, (w - cols * cw) // 2), max(0, (h - rows * ch) // 2))
        return cols, rows

    def preset_note(self, preset_idx):
        _, pw, ph = RESOLUTION_PRESETS[preset_idx]
        if pw is None:
            return f"fills the window ({self.base_font}px text)"
        return f"{pw}x{ph} characters, text sized to fit"

    def clear(self):
        pass

    def _cell_at(self, pos):
        cw, ch = self.cell
        ox, oy = self.offset
        return (pos[0] - ox) // cw, (pos[1] - oy) // ch

    def _key(self, e):
        pg = self.pg
        if e.key in (pg.K_RETURN, pg.K_KP_ENTER):
            return "F11" if e.mod & pg.KMOD_ALT else "ENTER"
        if e.key == pg.K_f and e.mod & pg.KMOD_META:     # macOS Cmd+F
            return "F11"
        special = {pg.K_UP: "UP", pg.K_DOWN: "DOWN", pg.K_LEFT: "LEFT",
                   pg.K_RIGHT: "RIGHT", pg.K_ESCAPE: "ESC", pg.K_F11: "F11",
                   pg.K_F1: "?"}
        if e.key in special:
            return special[e.key]
        ch = e.unicode
        if len(ch) == 1 and " " <= ch <= "~":
            return ch
        return None

    def events(self):
        pg = self.pg
        out = []
        for e in pg.event.get():
            if e.type == pg.QUIT:
                out.append(("quit",))
            elif e.type == pg.VIDEORESIZE:
                if not self.fullscreen:
                    self.windowed_size = (max(320, e.w), max(200, e.h))
                out.append(("resize",))
            elif e.type == pg.KEYDOWN:
                key = self._key(e)
                if key:
                    out.append(("key", key))
            elif e.type == pg.MOUSEBUTTONDOWN and e.button in (1, 2, 3):
                self._press = (e.button, e.pos)
                self._last_pos = e.pos
            elif e.type == pg.MOUSEMOTION:
                self.mouse_cell = self._cell_at(e.pos)
                if self._press:
                    button, start = self._press
                    if not self.dragging and (abs(e.pos[0] - start[0])
                                              + abs(e.pos[1] - start[1])) > 4:
                        self.dragging = True
                    if self.dragging:
                        col0, row0 = self._cell_at(start)
                        out.append(("drag", e.pos[0] - self._last_pos[0],
                                    e.pos[1] - self._last_pos[1], button,
                                    col0, row0))
                        self._last_pos = e.pos
            elif e.type == pg.MOUSEBUTTONUP and self._press and e.button == self._press[0]:
                if not self.dragging:
                    col, row = self._cell_at(e.pos)
                    out.append(("click", col, row, e.button))
                self._press = None
                self.dragging = False
            elif e.type == pg.MOUSEWHEEL:
                col, row = self.mouse_cell
                out.append(("wheel", e.y, col, row))
        return out

    def _glyph(self, key):
        """Cell-sized surface for a character in a fg/bg color pair."""
        pg = self.pg
        code = key & 0xFF
        fg = ((key >> 8) & 0x1FF) - 1
        bg = (key >> 17) - 1
        fg_rgb = XTERM_RGB[fg] if fg >= 0 else self.DEFAULT_FG
        bg_rgb = XTERM_RGB[bg] if bg >= 0 else self.BACKGROUND
        cell = pg.Surface(self.cell).convert()
        cell.fill(bg_rgb)
        if code != 32:
            cell.blit(self.font.render(chr(code), True, fg_rgb, bg_rgb), (0, 0))
        self.glyphs[key] = cell
        return cell

    def present(self, scr):
        surf = self.surface
        surf.fill(self.BACKGROUND)
        ys, xs = np.nonzero((scr.chars != 32) | (scr.bg >= 0))
        if len(ys):
            keys = (scr.chars[ys, xs].astype(np.int64)
                    | ((scr.fg[ys, xs].astype(np.int64) + 1) << 8)
                    | ((scr.bg[ys, xs].astype(np.int64) + 1) << 17))
            cw, ch = self.cell
            ox, oy = self.offset
            glyphs = self.glyphs
            seq = []
            for key, x, y in zip(keys.tolist(), (xs * cw + ox).tolist(),
                                 (ys * ch + oy).tolist()):
                glyph = glyphs.get(key)
                if glyph is None:
                    glyph = self._glyph(key)
                seq.append((glyph, (x, y)))
            surf.blits(seq, doreturn=False)
        self.pg.display.flip()

    def show_error(self, lines):
        """Show an error in the window until a key, click or close."""
        pg = self.pg
        try:
            font = self._font(self.base_font)
            while True:
                self.surface.fill(self.BACKGROUND)
                for i, line in enumerate(lines + ["", "Press any key to close."]):
                    self.surface.blit(font.render(line, True, (255, 180, 80)),
                                      (20, 20 + i * font.get_linesize()))
                pg.display.flip()
                for e in pg.event.get():
                    if e.type in (pg.QUIT, pg.KEYDOWN, pg.MOUSEBUTTONDOWN):
                        return
                time.sleep(0.05)
        except Exception:
            pass


# ── Settings panel process (Tkinter) ─────────────────

PANEL_GROUPS = [
    ("Shape", ["shape", "render", "auto_switch", "paused"]),
    ("Motion", ["auto_rotate", "speed", "scale", "fov"]),
    ("Audio", ["audio", "audio_device", "audio_sens", "onset"]),
    ("Look", ["color_mode", "palette", "shape_color", "invert", "brightness",
              "ramp", "density", "depth_range"]),
    ("Display", ["resolution", "hud", "adapt"]),
]
PANEL_RIGHT = {"Look", "Display"}


def run_panel():
    """Entry point of the panel process started with --panel."""
    import queue

    def report(error):
        sys.stdout.write(json.dumps({"error": error}) + "\n")
        sys.stdout.flush()

    try:
        import tkinter as tk
        from tkinter import ttk
        root = tk.Tk()
    except ImportError as e:
        hint = " (on Linux: sudo apt install python3-tk)" if sys.platform.startswith("linux") else ""
        report(f"Tkinter is not available: {e}{hint}")
        return
    except Exception as e:                 # tk.TclError: no display
        report(f"the panel window could not open: {e}")
        return

    inbox = queue.Queue()

    def read_stdin():
        for line in sys.stdin:
            try:
                inbox.put(json.loads(line))
            except ValueError:
                pass
        inbox.put({"quit": True})       # the app closed its end

    threading.Thread(target=read_stdin, daemon=True).start()

    root.title(f"{APP_NAME} - Settings")
    root.resizable(False, False)
    if sys.platform.startswith("linux"):
        ttk.Style().theme_use("clam")
    status = tk.StringVar(value="Connecting...")
    ttk.Label(root, textvariable=status, foreground="#b35c00",
              wraplength=520).grid(row=0, column=0, columnspan=2,
                                   padx=10, pady=(8, 0), sticky="w")
    setters = {}       # key -> function that shows a value from the app
    touched = {}       # key -> when the user last changed it here
    updating = [False]

    def send(obj):
        try:
            sys.stdout.write(json.dumps(obj) + "\n")
            sys.stdout.flush()
        except (OSError, ValueError):
            root.destroy()

    def user_set(key, value):
        if updating[0]:
            return
        touched[key] = time.time()
        send({"set": key, "value": value})

    def add_param(parent, r, m):
        key, lo, hi, log, fmt = m["key"], m["lo"], m["hi"], m["log"], m["fmt"]

        def to_pos(v):
            v = clamp(v, lo, hi)
            t = math.log(v / lo) / math.log(hi / lo) if log else (v - lo) / (hi - lo)
            return 1000 * t

        def to_val(pos):
            t = float(pos) / 1000
            return lo * (hi / lo) ** t if log else lo + (hi - lo) * t

        value = ttk.Label(parent, width=7, anchor="e")

        def moved(pos):
            value.config(text=f"{to_val(pos):{fmt}}")
            user_set(key, to_val(pos))

        scale = ttk.Scale(parent, from_=0, to=1000, orient="horizontal",
                          length=190, command=moved)
        scale.grid(row=r, column=1, sticky="we", pady=2)
        value.grid(row=r, column=2, sticky="e", padx=(6, 0))

        def show(v):
            scale.set(to_pos(v))
            value.config(text=f"{v:{fmt}}")
        return show

    def add_choice(parent, r, key, choices, by_name=False):
        var = tk.StringVar()
        box = ttk.Combobox(parent, textvariable=var, values=choices,
                           state="readonly", width=28)
        box.grid(row=r, column=1, columnspan=2, sticky="we", pady=2)
        box.bind("<<ComboboxSelected>>", lambda e: user_set(
            key, var.get() if by_name else box.current()))

        def show(v):
            if by_name:
                var.set(v)
            else:
                box.current(v % len(choices))
        return show

    def add_toggle(parent, r, key):
        var = tk.BooleanVar()
        ttk.Checkbutton(parent, variable=var,
                        command=lambda: user_set(key, var.get())).grid(
            row=r, column=1, sticky="w", pady=2)
        return var.set

    def build(msg):
        meta = {m["key"]: m for m in msg["meta"]}
        columns = [ttk.Frame(root), ttk.Frame(root)]
        for i, col in enumerate(columns):
            col.grid(row=1, column=i, sticky="n", padx=8, pady=6)
        placed = set()
        groups = PANEL_GROUPS + [("Other", [k for k in meta if not any(
            k in keys for _, keys in PANEL_GROUPS)])]
        for title, keys in groups:
            if not keys:
                continue
            frame = ttk.LabelFrame(columns[title in PANEL_RIGHT], text=title,
                                   padding=8)
            frame.pack(fill="x", pady=4)
            for r, key in enumerate(keys):
                if key == "audio_device":
                    ttk.Label(frame, text="Input device").grid(
                        row=r, column=0, sticky="w", padx=(0, 10))
                    setters[key] = add_choice(frame, r, key,
                                              msg["audio_devices"], by_name=True)
                    continue
                m = meta.get(key)
                if m is None:
                    continue
                ttk.Label(frame, text=m["label"]).grid(
                    row=r, column=0, sticky="w", padx=(0, 10))
                if m["kind"] == "param":
                    setters[key] = add_param(frame, r, m)
                elif m["kind"] == "choice":
                    setters[key] = add_choice(frame, r, key, m["choices"])
                else:
                    setters[key] = add_toggle(frame, r, key)
                placed.add(key)
        buttons = ttk.Frame(columns[1])
        buttons.pack(fill="x", pady=8)
        for text, action in (("Reset rotation", "reset_angles"),
                             ("Fullscreen", "fullscreen"),
                             ("Reset all settings", "reset_all")):
            ttk.Button(buttons, text=text,
                       command=lambda a=action: send({"do": a})).pack(
                fill="x", pady=2)
        status.set("")

    def apply_state(state):
        now = time.time()
        updating[0] = True
        try:
            for key, value in state.items():
                show = setters.get(key)
                if show and now - touched.get(key, 0) > 0.5:
                    show(value)
            status.set(state.get("notice", ""))
        finally:
            updating[0] = False

    def pump():
        try:
            while True:
                msg = inbox.get_nowait()
                if msg.get("quit"):
                    root.destroy()
                    return
                if "meta" in msg and not setters:
                    build(msg)
                if "state" in msg and setters:
                    apply_state(msg["state"])
        except queue.Empty:
            pass
        root.after(50, pump)

    root.after(50, pump)
    root.mainloop()


# ── Start-up ──────────────────────────────────────────

def window_unavailable():
    """Why the window can't open here, or "" if it can."""
    try:
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        import pygame  # noqa: F401
    except ImportError:
        return "pygame is not installed (pip install pygame)"
    if sys.platform.startswith("linux") and not (
            os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return "no graphical display was found"
    return ""


def open_console():
    """Windowed Windows builds start without a console; open one so the
    terminal mode has somewhere to draw. Returns False if that fails."""
    try:
        import ctypes
        if not ctypes.windll.kernel32.AllocConsole():
            return False
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
        sys.stderr = sys.stdout
        sys.stdin = open("CONIN$", "r")
        return True
    except (AttributeError, OSError):
        return False


def selftest():
    """Draw every shape offscreen and check the optional parts load; used
    by the build workflow on each OS. Returns the exit code."""
    global WIDTH, HEIGHT
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    fe = WindowFrontend()
    fe.start({"window": [800, 600]})
    WIDTH, HEIGHT = fe.grid_size(0)
    scr = ScreenBuffer(WIDTH, HEIGHT)
    for i in range(len(SHAPE_DEFS)):
        scr.clear()
        draw_shape(i, 0.5, 0.7, 0.1, 1.0, scr, 0)
        fe.present(scr)
    fe.stop()
    scr.render_ansi()
    import tkinter  # noqa: F401
    print(f"selftest ok: {len(SHAPE_DEFS)} shapes drawn at {WIDTH}x{HEIGHT}, "
          f"font {os.path.basename(fe.font_path or 'pygame default')}, "
          f"audio {'yes' if HAS_AUDIO else 'NO'}, tkinter yes")
    return 0 if HAS_AUDIO else 2


def main():
    no_console = sys.stdout is None
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:   # windowed build: print() goes nowhere
            setattr(sys, name, open(os.devnull, "w"))

    parser = argparse.ArgumentParser(description=f"{APP_NAME} v{APP_VERSION}")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--window", action="store_true",
                            help="open in its own window (the default)")
    mode_group.add_argument("--terminal", action="store_true",
                            help="draw in this terminal instead")
    parser.add_argument("--panel", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)
    args, _ = parser.parse_known_args()  # macOS may add -psn_... from Finder

    if args.panel:
        run_panel()
        return
    if args.selftest:
        sys.exit(selftest())
    exe_name = os.path.splitext(os.path.basename(sys.executable))[0].lower()
    if getattr(sys, "frozen", False) and exe_name.endswith("-terminal"):
        args.terminal = not args.window   # the Windows console twin

    saved = load_saved()
    frontend = None
    if not args.terminal:
        reason = window_unavailable()
        if not reason:
            try:
                frontend = WindowFrontend()
                frontend.start(saved)
            except Exception as e:
                reason = f"the window could not open ({e})"
                frontend = None
        if reason:
            write_crash_log(f"Window mode unavailable: {reason}")
            if no_console:
                if os.name == "nt" and open_console():
                    print(f"Window mode unavailable: {reason}")
                    input("Press Enter to close.")
                sys.exit(1)
            if args.window or not sys.stdout.isatty():
                print(f"Window mode unavailable: {reason}")
                sys.exit(1)
            print(f"Window mode unavailable: {reason}. Using the terminal.")
            time.sleep(1.5)
    if frontend is None:
        if no_console and not (os.name == "nt" and open_console()):
            sys.exit(1)
        frontend = TerminalFrontend()
        frontend.start(saved)

    try:
        run(frontend, saved)
    except KeyboardInterrupt:
        pass
    except Exception:
        log = write_crash_log(traceback.format_exc())
        lines = [f"{APP_NAME} hit an error and has to close.",
                 traceback.format_exc().strip().splitlines()[-1]]
        if log:
            lines.append(f"Details were saved to {log}")
        if frontend.is_window:
            frontend.show_error(lines)
            frontend.stop()
        else:
            frontend.stop()          # restore the terminal first
            frontend.show_error(lines)
        sys.exit(1)
    frontend.stop()


if __name__ == "__main__":
    main()
