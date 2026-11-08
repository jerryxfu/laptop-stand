#!/usr/bin/env python3
"""
Parametric MacBook riser for the 14" MacBook Pro with PROLED XDR display (2026).

Design
------
* Two side frames (left + right, mirror images) printed flat, outer face on the
  textured plate. Layers run in the plane of the frame, so every load path is
  carried by continuous perimeters.
* Two crossbars with dovetail tenons that drop into dovetail sockets in the
  frames' base bars. Gravity + the laptop keep them seated; the flare stops the
  frames from spreading.
* TPU 90A pads press-fit into pockets: 4 on the rails (laptop contact) and
  4 under the base (desk grip). Same pad for all 8 pockets.
* Rails sit `rail_inset` mm inboard of the laptop's side edges so the side
  intake slots, rubber feet and side ports stay clear; nothing sits behind the
  hinge, so the rear exhaust is open.

Run:  python3 macbook_riser.py           -> writes stl/ and riser_dims.json
Edit the PARAMS block (or pass --preset) to change height/angle.
"""
import argparse
import json
import math
import os

import numpy as np
import trimesh
from manifold3d import CrossSection, Manifold, OpType
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

# ----------------------------------------------------------------------------
# Parameters (mm / degrees)
# ----------------------------------------------------------------------------
PARAMS = dict(
    # MacBook Pro 14" PROLED XDR (2026) - published size
    laptop_w=310.8,
    laptop_d=216.3,
    laptop_t=15.0,
    laptop_base_t=10.0,     # approx. thickness of the bottom half (preview only)

    # Ergonomics
    tilt_deg=18.0,          # slope of the laptop
    front_height=80.0,      # rail surface height at the front lip (desk = 0)
    rail_len=200.0,         # supported length along the slope (laptop is 216)
    rail_inset=40.0,        # laptop side edge -> frame outer face

    # Frame structure
    frame_t=18.0,           # frame thickness (= rail width)
    lip_h=8.0,              # lip height above rail surface (6.8 above pads)
    lip_t=6.0,
    rail_depth=14.0,
    base_h=20.0,
    post_w=16.0,
    brace_w=16.0,
    strut_w=12.0,
    strut_at=0.55,          # strut position as fraction of rail_len
    rear_ext=45.0,          # rear foot reach behind the rail end (anti-tip)
    outer_r=2.5,            # convex corner rounding of outline
    window_r=8.0,           # fillet radius inside the windows
    chamfer=0.6,            # edge chamfer on both flat faces

    # Pads (TPU 90A)
    pad_l=40.0,
    pad_w=12.0,
    pad_t=2.4,
    pocket_depth=1.2,       # -> pads stand 1.2 mm proud
    pocket_clear=0.10,      # per side

    # Crossbar + dovetail
    cb_depth=16.0,          # crossbar front-to-back thickness
    sock_floor=3.0,         # socket floor thickness (crossbar floats this high)
    dt_neck=8.0,            # dovetail width at the frame's inner face
    dt_base=14.0,           # dovetail width at full depth
    dt_depth=7.0,           # how far the tenon goes into the frame
    fit_side=0.15,          # clearance per flank (Y)
    fit_end=0.30,           # clearance at tenon tip
    fit_shoulder=0.10,      # clearance between crossbar shoulder and frame
)

PRESETS = {
    "default": {},
    # Lower and flatter (~55 mm min. front height: the crossbar joints need
    # room above the base bar, so a near-flat typing wedge needs another layout)
    "low": dict(tilt_deg=12.0, front_height=55.0, rear_ext=35.0),
    # Taller: screen top closer to eye level (external keyboard)
    "tall": dict(tilt_deg=20.0, front_height=110.0, rail_len=190.0, rear_ext=50.0),
}

BED = 256.0  # Bambu Lab X1C build plate
RES = 12     # shapely quad segments per 90 deg


# ----------------------------------------------------------------------------
# 2D helpers
# ----------------------------------------------------------------------------
def v(x, y):
    return np.array([x, y], dtype=float)


def halfplane(point, normal, size=2000.0):
    """Region {x : (x - point) . normal >= 0} as a big polygon."""
    n = np.asarray(normal, float)
    n = n / np.linalg.norm(n)
    t = v(-n[1], n[0])
    p = np.asarray(point, float)
    return Polygon([p + t * size, p - t * size,
                    p - t * size + n * size, p + t * size + n * size])


def opening(poly, r):
    return poly.buffer(-r, quad_segs=RES).buffer(r, quad_segs=RES)


def closing(poly, r):
    return poly.buffer(r, quad_segs=RES).buffer(-r, quad_segs=RES)


def to_cs(geom):
    polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
    contours = []
    for pg in polys:
        pg = orient(pg, 1.0)
        contours.append(np.array(pg.exterior.coords)[:-1])
        for ring in pg.interiors:
            contours.append(np.array(ring.coords)[:-1])
    return CrossSection(contours)


def union(parts):
    return Manifold.batch_boolean(parts, OpType.Add)


def chamfer_extrude(cs, h, c_bot=0.0, c_top=0.0, step=0.2):
    """Extrude with stepped (layer-aligned) chamfers on bottom/top edges."""
    # slabs overlap by `eps` so the union fuses them (touching faces would
    # otherwise stay separate shells)
    eps = 0.02
    parts = []
    z0, z1 = c_bot, h - c_top
    parts.append(Manifold.extrude(cs, z1 - z0).translate((0, 0, z0)))
    for c, at_top in ((c_bot, False), (c_top, True)):
        n = int(round(c / step))
        for k in range(n):
            inset = c - k * step
            sl = cs.offset(-inset)
            if sl.is_empty():
                continue
            if at_top:
                z = h - (k + 1) * step - eps
            else:
                z = k * step
            parts.append(Manifold.extrude(sl, step + eps).translate((0, 0, z)))
    return union(parts)


# ----------------------------------------------------------------------------
# Geometry
# ----------------------------------------------------------------------------
class Riser:
    def __init__(self, **over):
        self.p = dict(PARAMS)
        self.p.update(over)
        p = self.p
        th = math.radians(p["tilt_deg"])
        self.u = v(math.cos(th), math.sin(th))      # up the slope, toward rear
        self.n = v(-math.sin(th), math.cos(th))     # rail surface normal
        self.P0 = v(0.0, p["front_height"])          # lip root
        self.R1 = self.P0 + p["rail_len"] * self.u   # rail rear end
        L1 = self.P0 + p["lip_h"] * self.n
        F1 = L1 - p["lip_t"] * self.u
        self.yf = F1[0]
        self.yb = self.R1[0] + p["rear_ext"]
        self.raw_outline = Polygon([v(self.yf, 0), v(self.yb, 0), self.R1,
                                    self.P0, L1, F1])
        self.W_out = p["laptop_w"] - 2 * p["rail_inset"]
        self.G = self.W_out - 2 * p["frame_t"]       # gap between inner faces
        self.ta = (p["dt_base"] - p["dt_neck"]) / 2 / p["dt_depth"]  # flank slope
        self._layout_features()

    # -- positions of pockets / sockets along the frame (profile coords) -----
    def _layout_features(self):
        p = self.p
        L = p["rail_len"]
        self.rail_pads = [(6.0, 6.0 + p["pad_l"]), (L - 6.0 - p["pad_l"], L - 6.0)]
        self.foot_pads = [(self.yf + 6.0, self.yf + 6.0 + p["pad_l"]),
                          (self.yb - 9.0 - p["pad_l"], self.yb - 9.0)]
        s_strut = p["strut_at"] * L
        self.Ps = self.P0 + s_strut * self.u
        # strut meets base top at:
        k = (self.Ps[1] - p["base_h"]) / self.n[1]
        strut_base = self.Ps - k * self.n
        # front socket: just behind the front foot pad
        y_front = self.foot_pads[0][1] + 4 + p["cb_depth"] / 2
        # rear socket: centred in the clear base span of the rear window
        win = self.windows()[1]
        xs = [x for x, y in win.exterior.coords if y < p["base_h"] + 0.5]
        y_rear = (min(xs) + max(xs)) / 2 if xs else (strut_base[0] + self.yb) / 2
        self.sockets = [y_front, y_rear]

    def windows(self):
        p = self.p
        o = self.raw_outline
        base = halfplane(v(0, p["base_h"]), v(0, 1))
        post = halfplane(v(self.yf + p["post_w"], 0), v(1, 0))
        rail = halfplane(self.P0 - p["rail_depth"] * self.n, -self.n)
        e = self.R1 - v(self.yb, 0)
        nl = v(-e[1], e[0])
        nl /= np.linalg.norm(nl)
        brace = halfplane(v(self.yb, 0) + p["brace_w"] * nl, nl)
        Ps = self.P0 + p["strut_at"] * p["rail_len"] * self.u
        sf = halfplane(Ps - p["strut_w"] / 2 * self.u, -self.u)
        sr = halfplane(Ps + p["strut_w"] / 2 * self.u, self.u)
        front = o.intersection(base).intersection(post).intersection(rail).intersection(sf)
        rear = o.intersection(base).intersection(rail).intersection(sr).intersection(brace)
        return [opening(front, p["window_r"]), opening(rear, p["window_r"])]

    def profile(self):
        p = self.p
        o = opening(closing(self.raw_outline, 0.8), p["outer_r"])
        for w in self.windows():
            o = o.difference(w)
        return o

    # -- frame in PRINT orientation: profile on XY (bed), thickness along Z --
    # X = front->rear (lip at X~0), Y = height in use, Z = 0 outer face, t inner
    def frame_print(self):
        p = self.p
        t = p["frame_t"]
        prof = to_cs(self.profile())
        body = chamfer_extrude(prof, t, p["chamfer"], p["chamfer"])

        cuts = []
        c = p["pocket_clear"]
        z_a = (t - p["pad_w"]) / 2 - c
        z_b = (t + p["pad_w"]) / 2 + c
        u, n = self.u, self.n
        for s0, s1 in self.rail_pads:
            a, b = s0 - c, s1 + c
            quad = Polygon([self.P0 + a * u - p["pocket_depth"] * n,
                            self.P0 + b * u - p["pocket_depth"] * n,
                            self.P0 + b * u + 3 * n,
                            self.P0 + a * u + 3 * n])
            cuts.append(Manifold.extrude(to_cs(quad), z_b - z_a).translate((0, 0, z_a)))
        for y0, y1 in self.foot_pads:
            rect = Polygon([(y0 - c, -3), (y1 + c, -3),
                            (y1 + c, p["pocket_depth"]), (y0 - c, p["pocket_depth"])])
            cuts.append(Manifold.extrude(to_cs(rect), z_b - z_a).translate((0, 0, z_a)))
        # dovetail sockets: wide at depth (z = t - dt_depth), neck at inner face
        over = 1.0
        hw_bot = p["dt_base"] / 2
        hw_top = p["dt_neck"] / 2 - over * self.ta
        q0, q1 = p["sock_floor"], p["base_h"] + 8.0
        rect = CrossSection([np.array([(-hw_bot, q0), (hw_bot, q0),
                                       (hw_bot, q1), (-hw_bot, q1)])])
        for yc in self.sockets:
            sock = Manifold.extrude(rect, p["dt_depth"] + over,
                                    scale_top=(hw_top / hw_bot, 1.0))
            cuts.append(sock.translate((yc, 0, t - p["dt_depth"])))
        return body - union(cuts)

    def frame_right_print(self):
        m = self.frame_print().mirror((0, 1, 0))
        return m.translate((0, -m.bounding_box()[1], 0))

    # -- crossbar in PRINT orientation (= use orientation, sitting on Z=0) ---
    # X = left-right (centred), Y = front-back (centred), Z = up
    def crossbar(self):
        p = self.p
        G = self.G
        hb = G / 2 - p["fit_shoulder"]
        d = p["cb_depth"] / 2
        shapes = [Polygon([(-hb, -d), (hb, -d), (hb, d), (-hb, d)])]
        x0, x1 = -p["fit_shoulder"] - 0.5, p["dt_depth"] - p["fit_end"]
        hw = lambda x: p["dt_neck"] / 2 - p["fit_side"] + x * self.ta
        for sgn in (1, -1):
            pts = [(G / 2 + x0, -hw(x0)), (G / 2 + x1, -hw(x1)),
                   (G / 2 + x1, hw(x1)), (G / 2 + x0, hw(x0))]
            shapes.append(Polygon([(sgn * x, y) for x, y in pts]))
        outline = unary_union(shapes)
        h = p["base_h"] - p["sock_floor"]
        return chamfer_extrude(to_cs(outline), h, 0.4, 0.6)

    def pad(self):
        p = self.p
        r = Polygon([(0, 0), (p["pad_l"], 0), (p["pad_l"], p["pad_w"]), (0, p["pad_w"])])
        r = opening(r, 1.0)
        return chamfer_extrude(to_cs(r), p["pad_t"], 0.0, 0.4)

    # -- fit-test coupon: a 50 mm slice of base bar with one socket + pocket --
    def fit_test(self):
        p = self.p
        t = p["frame_t"]
        Lc = p["pad_l"] + 12
        blk = Polygon([(0, 0), (Lc, 0), (Lc, p["base_h"]), (0, p["base_h"])])
        body = chamfer_extrude(to_cs(opening(blk, 1.5)), t, p["chamfer"], p["chamfer"])
        c = p["pocket_clear"]
        z_a = (t - p["pad_w"]) / 2 - c
        z_b = (t + p["pad_w"]) / 2 + c
        rect = Polygon([(6 - c, -3), (6 + p["pad_l"] + c, -3),
                        (6 + p["pad_l"] + c, p["pocket_depth"]),
                        (6 - c, p["pocket_depth"])])
        cuts = [Manifold.extrude(to_cs(rect), z_b - z_a).translate((0, 0, z_a))]
        over = 1.0
        hw_bot = p["dt_base"] / 2
        hw_top = p["dt_neck"] / 2 - over * self.ta
        q0, q1 = p["sock_floor"], p["base_h"] + 8.0
        sq = CrossSection([np.array([(-hw_bot, q0), (hw_bot, q0), (hw_bot, q1), (-hw_bot, q1)])])
        sock = Manifold.extrude(sq, p["dt_depth"] + over, scale_top=(hw_top / hw_bot, 1.0))
        cuts.append(sock.translate((Lc / 2, 0, t - p["dt_depth"])))
        return body - union(cuts)

    def fit_test_tenon(self):
        """Short crossbar stub with one tenon (same tolerances as crossbar)."""
        cb = self.crossbar()
        G = self.G
        keep = Manifold.cube((40, 40, 40)).translate((G / 2 - 22, -20, -1))
        stub = cb ^ keep
        return stub.translate((-(G / 2 - 22), 0, 0))

    # -- assembly (use orientation): X lateral, Y front->rear, Z up ---------
    def frame_to_use(self, m, side):
        # print (x=profile Y, y=height, z=thickness) -> use (X, Y, Z)
        half = self.W_out / 2
        M = [[0, 0, 1, -half], [1, 0, 0, 0], [0, 1, 0, 0]]
        m = m.transform(M)
        return m if side == "L" else m.mirror((1, 0, 0))

    def assembly(self):
        p = self.p
        fl = self.frame_to_use(self.frame_print(), "L")
        fr = self.frame_to_use(self.frame_print(), "R")
        cbs = [self.crossbar().translate((0, yc, p["sock_floor"])) for yc in self.sockets]
        pads = []
        pad = self.pad()
        c = p["pocket_clear"]
        for side in (-1, 1):
            xc = side * (self.W_out / 2 - p["frame_t"] / 2)
            for s0, s1 in self.rail_pads:
                # pad local: X along length, Y across, Z thickness
                o = self.P0 + s0 * self.u - p["pocket_depth"] * self.n
                ang = math.degrees(math.atan2(self.u[1], self.u[0]))
                m = pad.translate((0, -p["pad_w"] / 2, 0)).rotate((0, 0, 90)) \
                       .rotate((ang, 0, 0)).translate((xc, o[0], o[1]))
                pads.append(m)
            for y0, y1 in self.foot_pads:
                m = pad.translate((0, -p["pad_w"] / 2, 0)).mirror((0, 0, 1)) \
                       .rotate((0, 0, 90)).translate((xc, y0, p["pocket_depth"]))
                pads.append(m)
        return dict(frames=[fl, fr], crossbars=cbs, pads=pads, laptop=self.laptop())

    def laptop(self, lid_open_deg=115.0):
        """Simple proxy: base slab + lid, resting on the pads against the lip."""
        p = self.p
        W, D, tb = p["laptop_w"], p["laptop_d"], p["laptop_base_t"]
        lift = p["pad_t"] - p["pocket_depth"]
        ang = p["tilt_deg"]
        rr = Polygon([(-W / 2, 0), (W / 2, 0), (W / 2, D), (-W / 2, D)])
        rr = opening(rr, 9.0)
        base = Manifold.extrude(to_cs(rr), tb)
        lid_t = p["laptop_t"] - tb
        lid_len = D - 8
        lid = Manifold.extrude(to_cs(Polygon([(-W / 2, 0), (W / 2, 0),
                                              (W / 2, lid_t), (-W / 2, lid_t)])), lid_len)
        # lid: extruded along Z, thickness along Y -> rotate so it hinges at rear
        lid = lid.translate((0, -lid_t, 0)).rotate((-(lid_open_deg - 90), 0, 0)) \
                 .translate((0, D - 2, tb))
        lap = base + lid
        o = self.P0 + 0.5 * self.u + lift * self.n
        return lap.rotate((ang, 0, 0)).translate((0, o[0], o[1]))


# ----------------------------------------------------------------------------
# Export + checks
# ----------------------------------------------------------------------------
def to_tm(m):
    mesh = m.to_mesh()
    return trimesh.Trimesh(vertices=np.asarray(mesh.vert_properties)[:, :3],
                           faces=np.asarray(mesh.tri_verts), process=False)


def bbox_size(m):
    b = m.bounding_box()
    return (b[3] - b[0], b[4] - b[1], b[5] - b[2])


def run_checks(r):
    p = r.p
    out = {}
    fp = r.frame_print()
    out["frame_bbox_mm"] = [round(x, 1) for x in bbox_size(fp)]
    out["frame_fits_bed"] = all(x <= BED - 6 for x in bbox_size(fp)[:2])
    out["frame_genus"] = fp.genus()
    out["frame_pieces"] = len(fp.decompose())
    cb = r.crossbar()
    out["crossbar_bbox_mm"] = [round(x, 1) for x in bbox_size(cb)]
    asm = r.assembly()
    fl, fr = asm["frames"]
    frames = fl + fr
    # interference: crossbars / laptop vs frames
    out["crossbar_interference_mm3"] = round(sum((c ^ frames).volume() for c in asm["crossbars"]), 3)
    out["laptop_interference_mm3"] = round((asm["laptop"] ^ frames).volume(), 3)
    pads = union(asm["pads"])
    out["pad_vs_frame_interference_mm3"] = round((pads ^ frames).volume(), 3)
    # the laptop must actually touch the pads (not float, not crash)
    out["laptop_pad_overlap_mm3_with_0.05_drop"] = round(
        (asm["laptop"].translate((0, 0, -0.05)) ^ pads).volume(), 2)
    # insertion path: lift crossbar out of sockets, then shuffle sideways
    lift_ok = True
    for c in asm["crossbars"]:
        for dz in (2, 6, 10, 14, p["base_h"] - p["sock_floor"] + 0.5):
            if (c.translate((0, 0, dz)) ^ frames).volume() > 1e-3:
                lift_ok = False
    out["drop_in_path_clear"] = lift_ok
    dz = p["base_h"] - p["sock_floor"] + 0.5
    shuffle_ok = all((c.translate((-(p["dt_depth"] + 0.5), 0, dz)) ^ frames).volume() < 1e-3
                     for c in asm["crossbars"])
    out["shuffle_path_clear"] = shuffle_ok
    # dovetail flank play -> sideways play of the frames
    out["dovetail_flank_angle_deg"] = round(math.degrees(math.atan(r.ta)), 1)
    out["frame_spread_play_mm_per_joint"] = round(p["fit_side"] / r.ta + p["fit_end"] * 0, 2)
    # geometry summary
    out["stand_outer_width_mm"] = round(r.W_out, 1)
    out["stand_depth_mm"] = round(r.yb - r.yf, 1)
    out["rail_rear_height_mm"] = round(r.R1[1], 1)
    # pads stick out under the base, so the desk is at z = -(pad_t - pocket_depth)
    lift = p["pad_t"] - p["pocket_depth"]
    out["screen_top_height_mm_lid115"] = round(asm["laptop"].bounding_box()[5] + lift, 0)
    out["laptop_front_bottom_height_mm"] = round(r.P0[1] + 2 * lift, 1)
    out["sockets_at_mm"] = [round(s, 1) for s in r.sockets]
    vols = dict(frame=fp.volume(), crossbar=cb.volume(), pad=r.pad().volume())
    out["solid_volume_cm3"] = {k: round(x / 1000, 1) for k, x in vols.items()}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="default", choices=list(PRESETS))
    ap.add_argument("--out", default="stl")
    ap.add_argument("--set", nargs="*", default=[], help="override, e.g. tilt_deg=15")
    a = ap.parse_args()
    over = dict(PRESETS[a.preset])
    for kv in a.set:
        k, val = kv.split("=")
        over[k] = float(val)
    r = Riser(**over)
    os.makedirs(a.out, exist_ok=True)
    parts = {
        "frame_left.stl": r.frame_print(),
        "frame_right.stl": r.frame_right_print(),
        "crossbar_x2.stl": r.crossbar(),
        "tpu_pad_x8.stl": r.pad(),
        "fit_test_socket.stl": r.fit_test(),
        "fit_test_tenon.stl": r.fit_test_tenon(),
    }
    for name, m in parts.items():
        tm = to_tm(m)
        assert tm.is_watertight, name
        tm.export(os.path.join(a.out, name))
    checks = run_checks(r)
    checks["params"] = r.p
    with open(os.path.join(a.out, "riser_dims.json"), "w") as f:
        json.dump(checks, f, indent=2)
    print(json.dumps({k: v for k, v in checks.items() if k != "params"}, indent=2))
    bad = [k for k in ("frame_fits_bed", "drop_in_path_clear", "shuffle_path_clear") if not checks[k]]
    bad += [k for k in ("crossbar_interference_mm3", "laptop_interference_mm3") if checks[k] > 0.01]
    if checks["frame_pieces"] != 1:
        bad.append("frame_pieces")
    if bad:
        print("\nWARNING: these parameters fail checks:", ", ".join(bad))
    return r


if __name__ == "__main__":
    main()
