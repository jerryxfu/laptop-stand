# laptop-stand

A parametric, 3D-printable riser for the **MacBook Pro 14" with PROLED XDR display (2026)**, sliced for a **Bambu Lab X1C**. Everything is generated from Python; nothing is hand-modelled in CAD.

## Owner's setup
- Printer: Bambu Lab X1 Carbon, 0.4 mm nozzle, with an AMS, and a textured PEI plate.
- Filament on hand (all Bambu): TPU 90A, PETG, PLA Basic, PLA Matte. TPU 90A can't go through the AMS, so it has to come from the external spool.
- Laptop: MacBook Pro 14" PROLED, **310.8 × 216.3 × 15.0 mm**, about 1.36–1.41 kg, with a touchscreen. These dimensions come from MacRumors (2026-10-28), because Apple's spec page for the PROLED model wasn't found.
- Status as of 2026-11-08: the laptop is still shipping and **nothing has been printed yet**.

## Layout
| Path | Kind |
|---|---|
| `macbook_riser.py` | **Source of truth.** Holds the parameters (`PARAMS`, `PRESETS`), the geometry (class `Riser`), STL export and the fit checks |
| `render_preview.py` | Renders `preview/*.png`, using the parameters saved by the last `macbook_riser.py` run |
| `tools/slice_bambu.py` | Bambu Studio CLI wrapper that writes `bambu/*.3mf` from `stl/` |
| `stl/`, `preview/`, `bambu/` | **Generated.** Regenerate them; never hand-edit. Commit them together with the source change that produced them |
| `stl/riser_dims.json` | Check results plus the full parameter set of the last build |

## Commands
```bash
make setup                       # .venv + requirements.txt
make all                         # stl -> preview -> slice
make stl ARGS="--preset tall"    # or ARGS="--set tilt_deg=15 front_height=90"
make preview
make slice                       # needs /Applications/BambuStudio.app (tested 02.08.02.61)
```

## Verifying a change
1. Run `make stl`. It prints the checks, plus a `WARNING:` line if any fail. All of these must hold: `frame_pieces == 1`, `frame_fits_bed`, `crossbar_interference_mm3 == 0`, `laptop_interference_mm3 == 0`, `pad_vs_frame_interference_mm3 == 0`, `drop_in_path_clear`, `shuffle_path_clear`, and a positive `laptop_pad_overlap...` (the laptop touches the pads).
2. Run `make preview`, then open `preview/side_view.png` and `preview/stand_front.png` to check the shape by eye.
3. Run `make slice`. Every project must slice with no supports. Update the README's time and weight table from its output.

## Coordinates
- **Frame profile (2D, and the print plane):** x runs front to rear with x = 0 at the lip root, and y is height above the desk. The frame is extruded along z, which is its thickness; z = 0 is the outer face (on the build plate) and z = `frame_t` is the inner face (sockets are cut from it).
- **Assembly (use orientation):** X is lateral (centred), Y runs front to rear, Z is up. `Riser.frame_to_use` maps print to use. The right frame is the mirror image of the left.
- `u` is the unit vector up the slope and `n` is the rail surface normal. `P0` is the lip root and `R1` is the rail's rear end.

## Design decisions (and why)
- **Two side frames plus two crossbars.** The laptop's footprint is bigger than the 256 mm bed, so the stand can't print in one piece. The frames print **flat with the outer face down**, so layers run in the plane of the frame (strong) and the visible face gets the PEI texture. The crossbars print upright as modelled.
- **The joint is a drop-in dovetail.** The flanks are 23° (8 mm neck widening to 14 mm, 7 mm deep). Sockets are cut down into each base bar from inside the window above it, so gravity and the laptop keep the crossbars seated. The crossbar floats `sock_floor` = 3 mm above the bottom of the frame. To assemble, push one crossbar end through a frame window, swing the other end into the opposite window, then drop both ends. The checks simulate this path.
- **PETG for structure.** The underside of the laptop gets warm and PLA creeps at about 50–55 °C. PLA Matte would probably be OK, since the pads keep the aluminium 1.2 mm off the frame.
- **TPU 90A pads**, 8 identical 40 × 12 × 2.4 mm pads press-fit into 1.2 mm pockets: 4 on the rails and 4 under the base.
- **The rails sit `rail_inset` = 40 mm inboard** of the laptop's side edges. That keeps the side intake slots, the rubber feet and the side ports clear. Nothing sits behind the hinge, so the rear exhaust is open.
- **`rear_ext` = 45 mm rear feet**, so a tap on the touchscreen doesn't tip the stand backward.
- **`front_height` must be at least ~55 mm.** The crossbar has to fit in the window above the base bar (`drop_in_path_clear` fails below that).

## Gotchas
- **manifold3d:** a union of solids that only *touch* can stay as separate shells. `chamfer_extrude` overlaps its stepped slabs by 0.02 mm for this reason. Always check `frame_pieces == 1` after geometry changes.
- **shapely:** the opening radius `outer_r` must stay below `lip_t / 2`, or the lip gets eaten.
- **Bambu Studio CLI:** see the docstring in `tools/slice_bambu.py`. In short, use an absolute `--outputdir` with a bare `--export-3mf` file name; set `curr_bed_type`; 100 % sparse infill is rejected, so use shells instead; pass paths as an argv list, not through a shell.
- **zsh doesn't word-split `$var`.** Pass `--set k=v k2=v2` as separate argv items.

## Open work
1. **Seat the laptop on its own rubber feet instead of the TPU rail pads** (the owner's idea). This is waiting for the laptop to arrive so the feet can be measured: the distance from each side edge to the foot centres, the distances from the front and rear edges to the foot centres, the foot diameter, and how far the feet protrude. Planned approach:
   - Move the rails outward under the feet.
   - Cut a foot cup into the rail about 0.8 mm deep, roughly 1.5 mm oversize and slightly elongated along the slope.
   - Drop the rail about 5 mm below the laptop between the cups, to keep the intake vents open and the aluminium off the PETG.
   - Keep the lip as a backup.
   - Keep the 4 TPU desk pads, because bare PETG slides on a desk.
   - Add a quick cup-fit test print.
2. **Raise the crossbar off the desk** (requested). Plan: `base_h` 20 → about 28 and `sock_floor` 3 → about 11, so the crossbar stays 17 mm tall and sits about 11–12 mm up. Re-check the drop-in path and the `low` preset. The owner hasn't confirmed a height yet; they may want room for a cable.
3. **Choose a license.** The repo is public with no license. The options offered were MIT for the code plus CC BY for the models, CC BY-NC, or leave it.
4. **Print the fit test first** (`bambu/fit_test_PETG.3mf` plus one pad), then tune `fit_side` (default 0.15 mm per flank: 0.2 if the joint is tight, 0.1 if it's loose) and `pocket_clear` before printing the full set.
