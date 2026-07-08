"""
rdf_compare.py — Simulation vs Experiment(CIF) vs Minimised RDF, per element pair
──────────────────────────────────────────────────────────────────────────────────

For every element pair it computes g(r) from up to THREE structures and overlays
them on one graph:

  simulation   — the MD production trajectory (thermally averaged, 300 K etc.)
  cif          — the experimental crystal from the CIF (perfect lattice, ~0 K)
  minimised    — your MACE-relaxed 0 K structure (the sim's actual starting point)

Why three:
  * CIF is the experimental reference — your real comparison target.
  * The minimised curve is a symmetry-free cross-check: because it comes from a
    PDB with explicit coordinates, it does NOT depend on how the CIF space-group
    setting was expanded. If the CIF and minimised reference curves agree, the
    CIF was read correctly and the experiment comparison is trustworthy.

It finds everything from the PMC id + temperature (matching run_nvt.py /
run_npt.py's actual output layout):
  data/<PMC>/*.cif
  simulations/<PMC>/NVT_results/01_minimisation/last-frame-of-trajectory.pdb
  simulations/<PMC>/NVT_results/03_nvt_production/<T>K/production-trajectory.pdb
  simulations/<PMC>/NPT_results/01_minimisation/last-frame-of-trajectory.pdb
  simulations/<PMC>/NPT_results/04_npt_production/<T>K/trajectory.pdb

Usage:
  python3 rdf_compare.py PMC-001 --temp 300
  python3 rdf_compare.py PMC-001 --temp 300 --skip 80 --nbins 200
  python3 rdf_compare.py PMC-001 --temp 300 --refs cif          # only CIF ref
  python3 rdf_compare.py PMC-001 --temp 300 --refs cif minimised # both (default)

Outputs (in simulations/<PMC>/{NVT,NPT}_results/0{3,4}_..._production/<T>K/rdf_compare/):
  rdf_total.png       ONE graph: total g(r) vs r — simulation vs actual (CIF) vs minimised
  rdf_all_pairs.xvg   one xmgrace file: r, then TOTAL + g_sim (+ g_cif / g_min) per pair
  rdf_<A>-<B>.png     one plot per element pair overlaying the available curves
"""

import sys
import argparse
import itertools
from pathlib import Path

import numpy as np
from ase.io import read
from ase.geometry.rdf import get_rdf

PROJECT_ROOT = Path.home() / "himesh_work"
DATA_DIR = PROJECT_ROOT / "data"
SIM_DIR = PROJECT_ROOT / "simulations"


def find_cif(pmc_id: str) -> Path:
    folder = DATA_DIR / pmc_id
    if not folder.exists():
        return None
    cifs = list(folder.glob("*.cif"))
    return cifs[0] if cifs else None


def rdf_over_frames(frames, rmax, nbins, elements):
    """Average g(r) over frames (single-Atoms calls; works on all ASE 3.28.x)."""
    acc = None
    dists = None
    n = 0
    for atoms in frames:
        g, d = get_rdf(atoms, rmax=rmax, nbins=nbins, elements=elements)
        g = np.asarray(g)
        if acc is None:
            acc = np.zeros_like(g)
            dists = np.asarray(d)
        acc += g
        n += 1
    return acc / max(n, 1), dists


def build_reference_supercell(unit, rmax, margin=1.15):
    """Replicate a structure so each side comfortably exceeds 2*rmax."""
    lengths = unit.get_cell().cellpar()[:3]
    reps = [max(1, int(np.ceil(2.0 * rmax * margin / L))) for L in lengths]
    superc = unit.repeat(tuple(reps))
    superc.set_pbc(True)
    return superc, reps


# curve style/order: key -> (legend, colour, linestyle)
CURVE_STYLE = {
    "sim": ("Simulation", "C0", "-"),
    "cif": ("Experiment (CIF, 0 K)", "C3", "--"),
    "min": ("Minimised (0 K)", "C2", "-."),
}


def write_combined_xvg(path, r, data_by_curve, labels, sim_name, curve_order):
    with open(path, "w") as fh:
        fh.write(f"# RDF comparison, all element pairs\n")
        fh.write(f"# Simulation: {sim_name}\n")
        fh.write(f"# Column 1 = r (Angstrom); then per pair: "
                 f"{', '.join(curve_order)}\n")
        fh.write(f'@    title "RDF comparison - {sim_name}"\n')
        fh.write(f'@    xaxis  label "r (\\cE\\C)"\n')
        fh.write(f'@    yaxis  label "g(r)"\n')
        fh.write(f'@TYPE xy\n@ legend on\n@ legend box on\n')
        s = 0
        for lab in labels:
            for ck in curve_order:
                fh.write(f'@ s{s} legend "{lab} {ck}"\n')
                s += 1
        for j in range(len(r)):
            row = f"{r[j]:10.4f}"
            for lab in labels:
                for ck in curve_order:
                    row += f" {data_by_curve[ck][lab][j]:12.6f}"
            fh.write(row + "\n")


def main():
    ap = argparse.ArgumentParser(description="Simulation vs CIF vs minimised RDF")
    ap.add_argument("molecule", nargs="?", help="PMC ID, e.g. PMC-001")
    ap.add_argument("--temp", type=int, help="temperature in K, e.g. 300")
    ap.add_argument("--ensemble", default="nvt", choices=["nvt", "npt"],
                    help="which ensemble's run to analyse (default: nvt)")
    ap.add_argument("--refs", nargs="+", choices=["cif", "minimised"],
                    default=["cif", "minimised"],
                    help="reference structures to include (default: both)")
    ap.add_argument("--rmax", type=float, default=None,
                    help="max radius in Å (default: ~half shortest trajectory cell)")
    ap.add_argument("--nbins", type=int, default=200, help="radial bins (default: 200)")
    ap.add_argument("--stride", type=int, default=1, help="use every Nth frame")
    ap.add_argument("--skip", type=int, default=0, help="skip first N frames")
    args = ap.parse_args()

    if not args.molecule:
        sys.exit("❌ Give a PMC ID (e.g. PMC-001) with --temp.")
    if args.temp is None:
        sys.exit("❌ Please give --temp (e.g. --temp 300).")

    pmc_id = args.molecule.upper()
    if not pmc_id.startswith("PMC-"):
        pmc_id = f"PMC-{pmc_id}"

    tdir = SIM_DIR / pmc_id / f"{args.ensemble.upper()}_results"
    if args.ensemble == "nvt":
        tdir = tdir / "03_nvt_production" / f"{args.temp}K"
        traj_path = tdir / "production-trajectory.pdb"
    else:
        tdir = tdir / "04_npt_production" / f"{args.temp}K"
        traj_path = tdir / "trajectory.pdb"
    if not traj_path.exists():
        sys.exit(f"❌ Trajectory not found: {traj_path}")

    cif_path = find_cif(pmc_id)
    min_path = (SIM_DIR / pmc_id / f"{args.ensemble.upper()}_results"
                / "01_minimisation" / "last-frame-of-trajectory.pdb")

    # Decide which references are actually available
    want_cif = "cif" in args.refs and cif_path is not None
    want_min = "minimised" in args.refs and min_path.exists()
    if "cif" in args.refs and cif_path is None:
        print(f"  ⚠ No CIF found in {DATA_DIR / pmc_id} — skipping CIF reference")
    if "minimised" in args.refs and not min_path.exists():
        print(f"  ⚠ Minimised structure not found ({min_path.name}) — skipping")
    if not (want_cif or want_min):
        sys.exit("❌ No reference structures available to compare against.")

    print(f"Trajectory : {traj_path}")
    if want_cif:
        print(f"CIF ref    : {cif_path}")
    if want_min:
        print(f"Minimised  : {min_path}")
    print()

    # ── Load trajectory ──
    print("Reading trajectory ...")
    frames = read(str(traj_path), index=":")
    if not isinstance(frames, list):
        frames = [frames]
    frames = frames[args.skip::args.stride]
    if len(frames) == 0:
        sys.exit("❌ No frames left after --skip/--stride.")
    for f in frames:
        f.set_pbc(True)
    sim_cell = frames[0].get_cell()
    if frames[0].get_volume() <= 0 or sim_cell.rank < 3:
        sys.exit("❌ Trajectory has no valid unit cell.")
    sim_lengths = sim_cell.cellpar()[:3]
    print(f"  {len(frames)} frames, {len(frames[0])} atoms, "
          f"cell {sim_lengths[0]:.2f}/{sim_lengths[1]:.2f}/{sim_lengths[2]:.2f} Å")

    mic_sim = 0.5 * float(min(sim_lengths))
    if args.rmax is None:
        rmax = 0.98 * mic_sim
        print(f"  rmax auto-set to {rmax:.2f} Å (sim min-image limit {mic_sim:.2f} Å)")
    else:
        rmax = min(args.rmax, 0.98 * mic_sim)
        print(f"  rmax = {rmax:.2f} Å")

    # ── Load + tile reference structures ──
    refs = {}   # curve-key -> tiled Atoms
    if want_cif:
        unit = read(str(cif_path)); unit.set_pbc(True)
        sc, reps = build_reference_supercell(unit, rmax)
        refs["cif"] = sc
        print(f"  CIF: {len(unit)} atoms -> {reps[0]}x{reps[1]}x{reps[2]} = {len(sc)} atoms")
    if want_min:
        unit = read(str(min_path)); unit.set_pbc(True)
        sc, reps = build_reference_supercell(unit, rmax)
        refs["min"] = sc
        print(f"  Min: {len(unit)} atoms -> {reps[0]}x{reps[1]}x{reps[2]} = {len(sc)} atoms")

    # curve order: sim first, then whichever refs exist
    curve_order = ["sim"] + [k for k in ("cif", "min") if k in refs]

    elements = sorted(set(frames[0].get_chemical_symbols()))
    pairs = list(itertools.combinations_with_replacement(elements, 2))
    print(f"  Elements: {', '.join(elements)}")
    print(f"  Pairs ({len(pairs)}): {', '.join(a+'-'+b for a, b in pairs)}\n")

    out_dir = tdir / "rdf_compare"
    out_dir.mkdir(exist_ok=True)

    have_mpl = True
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        have_mpl = False
        print("ℹ matplotlib not installed — .xvg written, .png graphs skipped.\n")

    r = None
    data = {ck: {} for ck in curve_order}   # curve-key -> {pair/TOTAL: g(r)}

    # ── Total RDF (all elements combined) — the single sim/actual/minimised
    #    overlay, as opposed to the per-pair breakdown below ──
    print("  Computing TOTAL RDF (all elements)...")
    g_sim_total, dists = rdf_over_frames(frames, rmax, args.nbins, None)
    per_curve_total = {"sim": np.asarray(g_sim_total)}
    for ck, struct in refs.items():
        g, _ = get_rdf(struct, rmax=rmax, nbins=args.nbins, elements=None)
        per_curve_total[ck] = np.asarray(g)
    r = np.asarray(dists)
    for ck in curve_order:
        data[ck]["TOTAL"] = per_curve_total[ck]

    if have_mpl:
        plt.figure(figsize=(8, 5.5))
        for ck in curve_order:
            legend, colour, ls = CURVE_STYLE[ck]
            plt.plot(r, per_curve_total[ck], color=colour, linestyle=ls,
                     linewidth=1.8, label=legend)
        plt.axhline(1.0, color="grey", linewidth=0.7, linestyle=":")
        plt.xlabel("r (Å)")
        plt.ylabel("g(r)")
        plt.title(f"Total RDF vs r — {traj_path.stem}")
        plt.legend()
        plt.tight_layout()
        plt.savefig(out_dir / "rdf_total.png", dpi=150)
        plt.close()
        print(f"  ✅ Total RDF plot: rdf_total.png (curves: {', '.join(curve_order)})")

    made = 0
    for a, b in pairs:
        pair = f"{a}-{b}"
        try:
            g_sim, dists = rdf_over_frames(frames, rmax, args.nbins, [a, b])
            per_curve = {"sim": np.asarray(g_sim)}
            for ck, struct in refs.items():
                g, _ = get_rdf(struct, rmax=rmax, nbins=args.nbins, elements=[a, b])
                per_curve[ck] = np.asarray(g)
        except Exception as e:
            print(f"  {pair:6s}  skipped: {e}")
            continue
        if r is None:
            r = np.asarray(dists)
        for ck in curve_order:
            data[ck][pair] = per_curve[ck]

        if have_mpl:
            plt.figure(figsize=(7, 5))
            for ck in curve_order:
                legend, colour, ls = CURVE_STYLE[ck]
                plt.plot(r, per_curve[ck], color=colour, linestyle=ls,
                         linewidth=1.5, label=legend)
            plt.axhline(1.0, color="grey", linewidth=0.7, linestyle=":")
            plt.xlabel("r (Å)")
            plt.ylabel("g(r)")
            plt.title(f"RDF {pair}")
            plt.legend()
            plt.tight_layout()
            plt.savefig(out_dir / f"rdf_{pair}.png", dpi=150)
            plt.close()
        made += 1
        print(f"  {pair:6s}  done")

    if made == 0:
        sys.exit("❌ No pair RDFs were computed.")

    labels = list(data["sim"].keys())
    combined = out_dir / "rdf_all_pairs.xvg"
    write_combined_xvg(combined, r, data, labels, traj_path.stem, curve_order)

    print(f"\n✅ {made} pairs done. Curves per pair: {', '.join(curve_order)}")
    print(f"   Combined data: {combined.name}")
    if have_mpl:
        print(f"   Per-pair graphs: rdf_<pair>.png")
    print(f"   Folder: {out_dir}/")


if __name__ == "__main__":
    main()