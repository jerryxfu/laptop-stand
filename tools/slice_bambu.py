#!/usr/bin/env python3
"""Slice the STLs in stl/ into ready-to-print Bambu Studio projects in bambu/.

Uses the Bambu Studio command line with the stock "BBL" system presets for the
X1 Carbon (0.4 mm nozzle). The presets are flattened (their `inherits` chains
resolved) and lightly overridden, then the CLI arranges, slices and saves each
project as a .3mf with the G-code inside.

    python3 tools/slice_bambu.py                 # all three projects
    python3 tools/slice_bambu.py --only fit      # just the fit test
    python3 tools/slice_bambu.py --petg basic    # PETG Basic instead of PETG HF

Bambu Studio CLI quirks this works around (found the hard way):
  * --export-3mf only works with an ABSOLUTE --outputdir and a BARE file name.
  * The bed type must be set (curr_bed_type), or validation fails on Cool Plate.
  * sparse_infill_density=100% is rejected with the default pattern, so the TPU
    pads are made solid with 6 top + 6 bottom shell layers instead.
  * Passing paths through a shell breaks on spaces; we use argv lists.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STL = ROOT / "stl"

MACHINE = "Bambu Lab X1 Carbon 0.4 nozzle"
PROCESS = "0.20mm Standard @BBL X1C"
PETG = {"hf": "Bambu PETG HF @BBL X1C", "basic": "Bambu PETG Basic @BBL X1C"}
TPU = "Bambu TPU 90A @BBL X1C"

COMMON = {"curr_bed_type": "Textured PEI Plate", "enable_support": "0", "brim_type": "no_brim"}
PETG_PROCESS = {**COMMON, "wall_loops": "4", "sparse_infill_density": "15%",
                "sparse_infill_pattern": "gyroid", "top_shell_layers": "5",
                "bottom_shell_layers": "4"}
TPU_PROCESS = {**COMMON, "wall_loops": "3", "top_shell_layers": "6", "bottom_shell_layers": "6"}

# name -> (output file, filament key, process overrides, STL files)
JOBS = {
    "petg": ("riser_PETG_frames_crossbars.3mf", "petg", PETG_PROCESS,
             ["frame_left.stl", "crossbar_x2.stl", "frame_right.stl", "crossbar_x2.stl"]),
    "tpu": ("riser_TPU90A_pads_x8.3mf", "tpu", TPU_PROCESS, ["tpu_pad_x8.stl"] * 8),
    "fit": ("fit_test_PETG.3mf", "petg", PETG_PROCESS,
            ["fit_test_socket.stl", "fit_test_tenon.stl"]),
}


def find_app(arg):
    cand = arg or os.environ.get("BAMBU_STUDIO") or "/Applications/BambuStudio.app"
    p = Path(cand)
    if p.suffix == ".app":
        return p / "Contents/MacOS/BambuStudio", p / "Contents/Resources/profiles/BBL"
    # a bare executable: profiles usually live in ../Resources/profiles/BBL
    return p, p.parent.parent / "Resources/profiles/BBL"


def load_preset(profiles, name):
    for sub in ("machine", "process", "filament"):
        f = profiles / sub / f"{name}.json"
        if f.exists():
            d = json.loads(f.read_text())
            parent = d.get("inherits")
            if parent:
                base = load_preset(profiles, parent)
                base.update(d)
                d = base
            d.pop("inherits", None)
            return d
    sys.exit(f"Preset not found in {profiles}: {name!r}")


def write_preset(profiles, name, out, overrides=None):
    d = load_preset(profiles, name)
    d.update(overrides or {})
    out.write_text(json.dumps(d, indent=1))
    return out


def summarize(gcode_dir):
    rows = []
    for g in sorted(gcode_dir.glob("plate_*.gcode")):
        head = g.read_text(errors="ignore")[:20000]
        t = re.search(r"total estimated time: ([^\n;]+)", head)
        w = re.search(r"total filament weight \[g\] : ([\d.]+)", head)
        rows.append((g.stem, t.group(1).strip() if t else "?", w.group(1) if w else "?"))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", choices=list(JOBS), action="append")
    ap.add_argument("--petg", choices=list(PETG), default="hf")
    ap.add_argument("--bambu", help="path to BambuStudio.app or its executable "
                                    "(default: $BAMBU_STUDIO or /Applications/BambuStudio.app)")
    ap.add_argument("--out", default=str(ROOT / "bambu"))
    a = ap.parse_args()

    exe, profiles = find_app(a.bambu)
    if not exe.exists():
        sys.exit(f"Bambu Studio not found at {exe}. Install it or pass --bambu.")
    out_dir = Path(a.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        machine = write_preset(profiles, MACHINE, td / "machine.json")
        fil = {"petg": write_preset(profiles, PETG[a.petg], td / "petg.json"),
               "tpu": write_preset(profiles, TPU, td / "tpu.json")}
        ok = True
        for job in a.only or list(JOBS):
            name, fkey, proc_over, stls = JOBS[job]
            missing = [s for s in stls if not (STL / s).exists()]
            if missing:
                sys.exit(f"Missing {missing} in stl/. Run macbook_riser.py first.")
            proc = write_preset(profiles, PROCESS, td / f"process_{job}.json", proc_over)
            jd = td / job
            jd.mkdir()
            cmd = [str(exe), "--debug", "1", "--arrange", "1", "--orient", "0", "--slice", "0",
                   "--load-settings", f"{machine};{proc}", "--load-filaments", str(fil[fkey]),
                   "--outputdir", str(jd), "--export-3mf", name,
                   *[str(STL / s) for s in stls]]
            r = subprocess.run(cmd, capture_output=True, text=True)
            res = jd / "result.json"
            info = json.loads(res.read_text()) if res.exists() else {}
            if r.returncode != 0 or info.get("return_code", -1) != 0 or not (jd / name).exists():
                ok = False
                errs = [l for l in (r.stdout + r.stderr).splitlines() if "[error]" in l]
                print(f"FAILED {name}: {info.get('error_string', '')}")
                print("\n".join(errs[-5:]))
                continue
            shutil.move(str(jd / name), out_dir / name)
            print(f"{name}")
            for plate, t, w in summarize(jd):
                print(f"  {plate}: {t}, {w} g")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
