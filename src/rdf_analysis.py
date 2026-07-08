"""
rdf_analysis.py — Radial Distribution Function for all element pairs (ASE only)
────────────────────────────────────────────────────────────────────────────────

Computes the partial RDF g(r) for every unique element-element pair
(C-C, C-H, C-N, C-O, H-H, ...) from an MD production trajectory, averaged
over all frames, using the periodic box stored in the file.

Usage:
  python3 rdf_analysis.py production_300K.pdb
  python3 rdf_analysis.py production_300K.pdb --rmax 8 --nbins 200
  python3 rdf_analysis.py production_300K.pdb --stride 5        # every 5th frame
  python3 rdf_analysis.py production_300K.pdb --skip 400        # drop first 400 frames

Outputs (next to the trajectory):
  rdf_<name>.xvg    combined xmgrace file: column 1 = r, then one g(r)
                    column per element pair, with a proper Grace @ header
  rdf_<name>.png    plot of every pair (only if matplotlib is installed)

Notes:
  * rmax is automatically capped at just under half the shortest cell length
    (the minimum-image limit) so the periodic RDF is well-defined.
  * --skip lets you discard the un-equilibrated start of production.
"""

import sys
import argparse
import itertools
from pathlib import Path

import numpy as np
from ase.io import read
from ase.geometry.rdf import get_rdf


def main():
    ap = argparse.ArgumentParser(description="All-pair RDF (ASE only)")
    ap.add_argument("trajectory", help="trajectory file (e.g. production_300K.pdb)")
    ap.add_argument("--rmax", type=float, default=None,
                    help="max radius in Å (default: ~half shortest cell length)")
    ap.add_argument("--nbins", type=int, default=200,
                    help="number of radial bins (default: 200)")
    ap.add_argument("--stride", type=int, default=1,
                    help="use every Nth frame (default: 1 = all)")
    ap.add_argument("--skip", type=int, default=0,
                    help="skip the first N frames before analysing (default: 0)")
    args = ap.parse_args()

    traj_path = Path(args.trajectory)
    if not traj_path.exists():
        sys.exit(f"❌ File not found: {traj_path}")

    print(f"Reading {traj_path.name} ...")
    frames = read(str(traj_path), index=":")
    if isinstance(frames, list) is False:
        frames = [frames]
    print(f"  {len(frames)} frames, {len(frames[0])} atoms")

    # Apply skip + stride
    frames = frames[args.skip::args.stride]
    if len(frames) == 0:
        sys.exit("❌ No frames left after --skip/--stride.")
    print(f"  Using {len(frames)} frames (skip={args.skip}, stride={args.stride})")

    # Make sure the periodic box is active (PDB CRYST1 -> cell)
    cell = frames[0].get_cell()
    vol = frames[0].get_volume()
    if vol <= 0 or cell.rank < 3:
        sys.exit("❌ Trajectory has no valid unit cell — cannot compute a periodic RDF.")
    for f in frames:
        f.set_pbc(True)

    lengths = cell.cellpar()[:3]
    print(f"  Cell lengths: a={lengths[0]:.2f} b={lengths[1]:.2f} c={lengths[2]:.2f} Å")

    # rmax capped at the minimum-image limit (half the shortest cell length)
    mic_limit = 0.5 * float(min(lengths))
    if args.rmax is None:
        rmax = 0.98 * mic_limit
        print(f"  rmax auto-set to {rmax:.2f} Å (min-image limit {mic_limit:.2f} Å)")
    else:
        rmax = args.rmax
        if rmax >= mic_limit:
            rmax = 0.98 * mic_limit
            print(f"  ⚠ requested rmax too large; capped to {rmax:.2f} Å")
        else:
            print(f"  rmax = {rmax:.2f} Å")

    # Elements present, sorted for stable ordering
    elements = sorted(set(frames[0].get_chemical_symbols()))
    print(f"  Elements: {', '.join(elements)}")

    pairs = list(itertools.combinations_with_replacement(elements, 2))
    print(f"  Pairs to compute ({len(pairs)}): "
          f"{', '.join(a + '-' + b for a, b in pairs)}\n")

    r = None
    gr_by_pair = {}
    for a, b in pairs:
        label = f"{a}-{b}"
        try:
            # get_rdf averages over the whole list of frames internally
            g, dists = get_rdf(frames, rmax=rmax, nbins=args.nbins,
                               elements=[a, b])
            if r is None:
                r = np.asarray(dists)
            gr_by_pair[label] = np.asarray(g)
            peak = r[np.argmax(g)]
            print(f"  {label:6s}  done   (main peak near {peak:.2f} Å)")
        except Exception as e:
            print(f"  {label:6s}  skipped: {e}")

    if not gr_by_pair:
        sys.exit("❌ No pair RDFs were computed.")

    # ── Write combined .xvg (xmgrace-ready, Grace @ header) ──
    stem = traj_path.stem
    out_xvg = traj_path.parent / f"rdf_{stem}.xvg"
    labels = list(gr_by_pair.keys())

    with open(out_xvg, "w") as fh:
        # comment block
        fh.write(f"# Radial distribution functions (ASE), all element pairs\n")
        fh.write(f"# Trajectory : {traj_path.name}\n")
        fh.write(f"# Frames used: {len(frames)}  (skip={args.skip}, stride={args.stride})\n")
        fh.write(f"# rmax={rmax:.4f} A   nbins={args.nbins}\n")
        fh.write(f"# Column 1 = r (Angstrom); columns 2.. = g(r) per pair\n")
        # Grace formatting header
        fh.write(f'@    title "Radial Distribution Functions - {stem}"\n')
        fh.write(f'@    xaxis  label "r (\\cE\\C)"\n')   # \cE\C = Angstrom symbol in Grace
        fh.write(f'@    yaxis  label "g(r)"\n')
        fh.write(f'@TYPE xy\n')
        fh.write(f'@ view 0.15, 0.15, 0.85, 0.85\n')
        fh.write(f'@ legend on\n')
        fh.write(f'@ legend box on\n')
        for i, lab in enumerate(labels):
            fh.write(f'@ s{i} legend "{lab}"\n')
        # data rows: r  g0 g1 g2 ...
        for j in range(len(r)):
            row = f"{r[j]:10.4f}" + "".join(
                f" {gr_by_pair[lab][j]:12.6f}" for lab in labels)
            fh.write(row + "\n")

    print(f"\n✅ XVG saved: {out_xvg.name}")
    print(f"   Open with:  xmgrace {out_xvg.name}")

    # ── Plot (optional; skipped cleanly if matplotlib absent) ──
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        plt.figure(figsize=(9, 6))
        for lab in labels:
            plt.plot(r, gr_by_pair[lab], label=lab, linewidth=1.3)
        plt.axhline(1.0, color="grey", linestyle="--", linewidth=0.8)
        plt.xlabel("r (Å)")
        plt.ylabel("g(r)")
        plt.title(f"Radial Distribution Functions — {stem}")
        plt.legend(ncol=2, fontsize=9)
        plt.tight_layout()
        out_png = traj_path.parent / f"rdf_{stem}.png"
        plt.savefig(out_png, dpi=150)
        print(f"✅ Plot saved: {out_png.name}")
    except ImportError:
        print("ℹ matplotlib not installed — XVG written, plot skipped.")
        print("  (plot with xmgrace, or from the .xvg columns anywhere)")


if __name__ == "__main__":
    main()