#!/usr/bin/env python3
"""Render preview PNGs of the riser (assembly, exploded, side view, plates)."""
import json
import math
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from macbook_riser import BED, Riser, to_tm

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "preview")
os.makedirs(OUT, exist_ok=True)

PETG = np.array([0.20, 0.42, 0.62])
TPU = np.array([0.12, 0.12, 0.13])
LAP = np.array([0.72, 0.73, 0.76])

# Render the same shape as the last `macbook_riser.py` run (it saves its
# parameters to stl/riser_dims.json), so --preset / --set carry through.
DIMS = os.path.join(HERE, "stl", "riser_dims.json")
try:
    with open(DIMS) as f:
        params = json.load(f)["params"]
except (OSError, KeyError, ValueError):
    params = {}
r = Riser(**params)
asm = r.assembly()
p = r.p

# 3D renders (PyVista, offscreen) ------------------------------------------
import pyvista as pv
pv.OFF_SCREEN = True

C_PETG = "#2f6690"
C_CB = "#28597d"
C_TPU = "#1c1c1e"
C_LAP = "#9a9ca3"


def pvmesh(m):
    tm = to_tm(m)
    f = np.hstack([np.full((len(tm.faces), 1), 3), tm.faces]).ravel()
    return pv.PolyData(tm.vertices.copy(), f)


def render(path, items, eye, focal, size=(1400, 1050), floor_z=None, zoom=1.0):
    pl = pv.Plotter(off_screen=True, window_size=size)
    pl.set_background("white")
    for m, col, op in items:
        pl.add_mesh(pvmesh(m), color=col, opacity=op, smooth_shading=True,
                    split_sharp_edges=True, specular=0.25, specular_power=20,
                    ambient=0.18, diffuse=0.85)
    if floor_z is not None:
        fl = pv.Plane(center=(focal[0], focal[1], floor_z - 0.05), direction=(0, 0, 1),
                      i_size=1400, j_size=1400)
        pl.add_mesh(fl, color="#eceef1", ambient=0.6, diffuse=0.4)
    pl.enable_depth_peeling(10)
    pl.enable_anti_aliasing("ssaa")
    bb = np.array([m.bounding_box() for m, _, _ in items])
    bounds = (bb[:, 0].min(), bb[:, 3].max(), bb[:, 1].min(), bb[:, 4].max(),
              bb[:, 2].min(), bb[:, 5].max())
    ctr = ((bounds[0] + bounds[1]) / 2, (bounds[2] + bounds[3]) / 2, (bounds[4] + bounds[5]) / 2)
    d = np.asarray(eye, float) - np.asarray(focal, float)
    pl.camera_position = [tuple(np.asarray(ctr) + d), ctr, (0, 0, 1)]
    pl.reset_camera(bounds=bounds)
    pl.camera.zoom(zoom)
    pl.screenshot(path)
    pl.close()


lift = p["pad_t"] - p["pocket_depth"]
stand = [(f, C_PETG, 1.0) for f in asm["frames"]] + [(c, C_CB, 1.0) for c in asm["crossbars"]]
stand += [(pd, C_TPU, 1.0) for pd in asm["pads"]]
focal = (0, 115, 120)

render(f"{OUT}/assembly_with_macbook.png", stand + [(asm["laptop"], C_LAP, 0.45)],
       eye=(-620, -560, 420), focal=(0, 120, 180), floor_z=-lift, zoom=1.25)
render(f"{OUT}/stand_front.png", stand, eye=(-430, -420, 300), focal=focal,
       floor_z=-lift, zoom=1.3)
render(f"{OUT}/stand_rear.png", stand, eye=(430, 620, 330), focal=focal,
       floor_z=-lift, zoom=1.3)
fl, fr = asm["frames"]
exp = [(fl.translate((-80, 0, 0)), C_PETG, 1.0), (fr.translate((80, 0, 0)), C_PETG, 1.0)]
exp += [(c.translate((0, 0, 70)), C_CB, 1.0) for c in asm["crossbars"]]
for pd in asm["pads"]:
    b = pd.bounding_box()
    x = (b[0] + b[3]) / 2
    dz = 22 if b[5] > 10 else -18
    exp.append((pd.translate((-80 if x < 0 else 80, 0, dz)), C_TPU, 1.0))
render(f"{OUT}/exploded.png", exp, eye=(-480, -470, 380), focal=(0, 115, 90), zoom=1.25)

# 4. side view (2D) with dimensions ----------------------------------------
fig, ax = plt.subplots(figsize=(12, 7.5), dpi=110)
prof = r.profile()
x, y = prof.exterior.xy
ax.fill(x, y, color=PETG, alpha=0.9, lw=0)
for ring in prof.interiors:
    xi, yi = ring.xy
    ax.fill(xi, yi, color="white", lw=0)
lift = p["pad_t"] - p["pocket_depth"]
# pads
for s0, s1 in r.rail_pads:
    q = [r.P0 + s0 * r.u - p["pocket_depth"] * r.n, r.P0 + s1 * r.u - p["pocket_depth"] * r.n,
         r.P0 + s1 * r.u + lift * r.n, r.P0 + s0 * r.u + lift * r.n]
    ax.add_patch(plt.Polygon(q, color=TPU))
for y0, y1 in r.foot_pads:
    ax.add_patch(plt.Rectangle((y0, -lift), y1 - y0, p["pad_t"], color=TPU))
for yc in r.sockets:
    ax.add_patch(plt.Rectangle((yc - p["cb_depth"] / 2, p["sock_floor"]), p["cb_depth"],
                               p["base_h"] - p["sock_floor"], fill=False, ec="white", lw=1.2, ls="--"))
# laptop silhouette
D, tb, lt = p["laptop_d"], p["laptop_base_t"], p["laptop_t"] - p["laptop_base_t"]
o = r.P0 + 0.5 * r.u + lift * r.n
base = [o, o + D * r.u, o + D * r.u + tb * r.n, o + tb * r.n]
ax.add_patch(plt.Polygon(base, color=LAP, alpha=0.55))
hinge = o + (D - 2) * r.u + tb * r.n
# lid direction: rotate the deck's forward direction (-u) clockwise by 115 deg
fwd = -r.u
a = math.radians(-115)
lid_v = np.array([fwd[0] * math.cos(a) - fwd[1] * math.sin(a), fwd[0] * math.sin(a) + fwd[1] * math.cos(a)])
lid_n = np.array([lid_v[1], -lid_v[0]])
L = D - 8
lid = [hinge, hinge + L * lid_v, hinge + L * lid_v - lt * lid_n, hinge - lt * lid_n]
ax.add_patch(plt.Polygon(lid, color=LAP, alpha=0.55))
ax.axhline(-lift, color="#555", lw=1)
# annotations
def dim(x0, y0, x1, y1, text, off=(0, 0), **kw):
    ax.annotate("", (x1, y1), (x0, y0), arrowprops=dict(arrowstyle="<->", color="#333", lw=0.9))
    ax.text((x0 + x1) / 2 + off[0], (y0 + y1) / 2 + off[1], text, ha="center", va="center",
            fontsize=9, color="#222", bbox=dict(fc="white", ec="none", pad=1), **kw)
dim(r.yf - 14, -lift, r.yf - 14, o[1], f"{o[1] + lift:.0f}", off=(-10, 0))
dim(r.yb + 14, -lift, r.yb + 14, r.R1[1] + lift, f"{r.R1[1] + 2 * lift:.0f}", off=(12, 0))
dim(r.yf, -lift - 14, r.yb, -lift - 14, f"{r.yb - r.yf:.0f} mm deep", off=(0, -6))
top = (hinge + L * lid_v)[1]
ax.text(hinge[0] + 30, top - 8, f"screen top ≈ {top + lift:.0f} mm\n(lid at 115°)", fontsize=9)
ax.text(60, 115, f"{p['tilt_deg']:.0f}°", fontsize=12, color="#222")
ax.text(r.yf, -lift - 40,
        "PETG frame    ■ TPU 90A pads    dashed = crossbar position    grey = MacBook Pro 14\" proxy",
        fontsize=8.5, color="#444")
ax.set_aspect("equal")
ax.set_xlim(r.yf - 45, max(r.yb, (hinge + L * lid_v)[0]) + 45)
ax.set_ylim(-lift - 50, top + 25)
ax.axis("off")
fig.savefig(f"{OUT}/side_view.png", facecolor="white", bbox_inches="tight")
plt.close(fig)

# 5. print plates (top-down) ------------------------------------------------
fig, axs = plt.subplots(1, 3, figsize=(15, 5.4), dpi=110)
fp = r.frame_print()
frb = r.frame_right_print()
cb = r.crossbar()
pad = r.pad()


def outline2d(m):
    tm = to_tm(m)
    pts = tm.vertices[:, :2]
    return pts


def plate(ax, title, placed):
    ax.add_patch(plt.Rectangle((0, 0), BED, BED, fc="#2b2b2e", ec="#666"))
    for m, col in placed:
        tm = to_tm(m)
        tri = tm.vertices[tm.faces][:, :, :2]
        up = tm.face_normals[:, 2] > 0.5
        from matplotlib.collections import PolyCollection
        ax.add_collection(PolyCollection(tri[up], facecolors=[col], edgecolors=[col],
                                         linewidths=0.3, antialiased=False))
    ax.set_xlim(-5, BED + 5)
    ax.set_ylim(-5, BED + 5)
    ax.set_aspect("equal")
    ax.set_title(title, fontsize=10)
    ax.axis("off")


def place(m, x, y, rot=0):
    if rot:
        m = m.rotate((0, 0, rot))
    b = m.bounding_box()
    return m.translate((x - b[0], y - b[1], -b[2]))


fb = fp.bounding_box()
fw, fh = fb[3] - fb[0], fb[4] - fb[1]
x0 = (BED - fw) / 2
cbb = cb.bounding_box()
cw = cbb[3] - cbb[0]
plate(axs[0], "Plate 1 — PETG: left frame + crossbar",
      [(place(fp, x0, 12), PETG), (place(cb, (BED - cw) / 2, BED - 32), PETG * 0.85)])
plate(axs[1], "Plate 2 — PETG: right frame + crossbar",
      [(place(frb, x0, 12), PETG), (place(cb, (BED - cw) / 2, BED - 32), PETG * 0.85)])
pads = []
for i in range(8):
    pads.append((place(pad, 70 + (i % 2) * 70, 60 + (i // 2) * 35), (0.35, 0.35, 0.37)))
plate(axs[2], "Plate 3 — TPU 90A: 8 pads (external spool)", pads)
fig.tight_layout()
fig.savefig(f"{OUT}/print_plates.png", facecolor="white")
plt.close(fig)
print("ok")
