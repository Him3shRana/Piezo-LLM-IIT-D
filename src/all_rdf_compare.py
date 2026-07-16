#!/usr/bin/env python3
"""
rdf_compare.py — Simulation vs Experiment (CIF) vs Minimised RDF, per element pair
==================================================================================

Computes g(r) from up to THREE sources and overlays them on one graph per pair:

  simulation  — the MD production trajectory (thermally averaged)
  cif         — the experimental crystal from the CIF (perfect lattice, ~0 K)
  minimised   — the MACE-relaxed 0 K structure (simulation's actual starting point)

Works with the standardised folder structure produced by all_nvt_lammps.py /
all_npt_lammps.py / all_nvt_ase.py / all_npt_ase.py:

    runs/<PMC-ID>/<engine>-<ensemble>/<model>-<version>/<condition>/
        minimization/    equilibration/    production/

Usage:
    # Point at a specific run directory:
    python3 rdf_compare.py --run-dir runs/PMC-001/lammps-nvt/mace-off23-medium/300K_2x2x2

    # Or let it find the directory from structured args:
    python3 rdf_compare.py --pmc PMC-001 --engine lammps --ensemble nvt \
        --model mace-off23 --version medium --temperature 300

    # Options:
    python3 rdf_compare.py --run-dir <path> --rmax 8.0 --nbins 200 --skip 10 --stride 2
    python3 rdf_compare.py --run-dir <path> --refs cif              # CIF only, no minimised
    python3 rdf_compare.py --run-dir <path> --refs cif minimised    # both (default)

Outputs (in <run-dir>/rdf/):
    rdf_total.png       total g(r) overlay — simulation vs CIF vs minimised
    rdf_<A>-<B>.png     one plot per element pair
    rdf_all_pairs.xvg   combined data in xmgrace format
"""

import argparse
import itertools
import json
import os
import sys
from pathlib import Path

import numpy as np
from ase.io import read
from ase.data import atomic_numbers
from ase.geometry.rdf import get_rdf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_cif_for_pmc(cif_dir, pmc_id):
    """Same logic as the simulation scripts: glob for exactly one .cif."""
    folder = Path(cif_dir) / pmc_id
    if not folder.exists():
        return None
    cifs = list(folder.glob("*.cif"))
    return cifs[0] if len(cifs) == 1 else None


def load_type_map(run_dir):
    """Load type_map.json from the run directory (written by simulation scripts)."""
    tm_path = Path(run_dir) / "type_map.json"
    if tm_path.exists():
        with open(tm_path) as f:
            return json.load(f)
    return None


def rdf_over_frames(frames, rmax, nbins, elements):
    """Average g(r) over multiple frames."""
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


# Curve styling: key -> (legend, colour, linestyle)
CURVE_STYLE = {
    "sim": ("Simulation", "#1f77b4", "-"),
    "cif": ("Experiment (CIF)", "#d62728", "--"),
    "min": ("Minimised (0 K)", "#2ca02c", "-."),
}


def write_combined_xvg(path, r, data, labels, title, curve_order):
    """Write all RDF data to a single xmgrace-format file."""
    with open(path, "w") as fh:
        fh.write(f"# RDF comparison: {title}\n")
        fh.write(f"# Column 1 = r (Angstrom); then per pair: "
                 f"{', '.join(curve_order)}\n")
        fh.write(f'@    title "RDF comparison - {title}"\n')
        fh.write(f'@    xaxis  label "r (\\cE\\C)"\n')
        fh.write(f'@    yaxis  label "g(r)"\n')
        fh.write(f"@TYPE xy\n@ legend on\n@ legend box on\n")
        s = 0
        for lab in labels:
            for ck in curve_order:
                fh.write(f'@ s{s} legend "{lab} {ck}"\n')
                s += 1
        for j in range(len(r)):
            row = f"{r[j]:10.4f}"
            for lab in labels:
                for ck in curve_order:
                    row += f" {data[ck][lab][j]:12.6f}"
            fh.write(row + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Simulation vs CIF vs Minimised RDF comparison",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Run directory — either given directly, or constructed from components
    ap.add_argument("--run-dir", type=str, default=None,
                    help="Path to the condition directory (e.g. runs/PMC-001/lammps-nvt/mace-off23-medium/300K_2x2x2)")
    ap.add_argument("--pmc", type=str, default=None, help="PMC ID (e.g. PMC-001)")
    ap.add_argument("--engine", default="lammps", choices=["lammps", "ase"])
    ap.add_argument("--ensemble", default="nvt", choices=["nvt", "npt"])
    ap.add_argument("--model", default="mace-off23")
    ap.add_argument("--version", default="medium", choices=["small", "medium", "large"])
    ap.add_argument("--temperature", type=float, default=None)
    ap.add_argument("--pressure", type=float, default=None)
    ap.add_argument("--supercell-size", type=int, default=2)
    ap.add_argument("--runs-dir", default="runs", help="Root runs directory (default: runs)")

    # CIF location
    ap.add_argument("--cif-dir", default=os.path.expanduser("~/himesh_work/data"),
                    help="Directory containing PMC-ID/compound.cif folders")

    # RDF parameters
    ap.add_argument("--refs", nargs="+", choices=["cif", "minimised"],
                    default=["cif", "minimised"],
                    help="Reference structures to include (default: both)")
    ap.add_argument("--rmax", type=float, default=None,
                    help="Max radius in Å (default: ~half shortest trajectory cell)")
    ap.add_argument("--nbins", type=int, default=200, help="Radial bins (default: 200)")
    ap.add_argument("--stride", type=int, default=1, help="Use every Nth frame")
    ap.add_argument("--skip", type=int, default=0, help="Skip first N frames")
    args = ap.parse_args()

    # ── Resolve run directory ──
    if args.run_dir:
        run_dir = Path(args.run_dir)
    elif args.pmc and args.temperature is not None:
        N = args.supercell_size
        engine_ensemble = f"{args.engine}-{args.ensemble}"
        model_version = f"{args.model}-{args.version}"
        if args.ensemble == "npt":
            pressure = args.pressure if args.pressure is not None else 1.0
            condition = f"{int(args.temperature)}K_{pressure:g}bar_{N}x{N}x{N}"
        else:
            condition = f"{int(args.temperature)}K_{N}x{N}x{N}"
        run_dir = Path(args.runs_dir) / args.pmc / engine_ensemble / model_version / condition
    else:
        sys.exit("ERROR: Provide either --run-dir or (--pmc + --temperature).")

    if not run_dir.exists():
        sys.exit(f"ERROR: Run directory not found: {run_dir}")

    # ── Find required files ──
    traj_path = run_dir / "production" / "traj.extxyz"
    if not traj_path.exists():
        sys.exit(f"ERROR: Production trajectory not found: {traj_path}\n"
                 f"Has the production stage completed?")

    # Minimised structure: prefer structure.pdb, fall back to minimized.lammpstrj
    min_dir = run_dir / "minimization"
    min_path = min_dir / "structure.pdb"
    min_format = "proteindatabank"
    if not min_path.exists():
        alt = min_dir / "minimized.lammpstrj"
        if alt.exists():
            min_path = alt
            min_format = "lammps-dump-text"

    # CIF
    pmc_id = args.pmc
    if pmc_id is None:
        # Try to extract from run_dir path (e.g. runs/PMC-001/lammps-nvt/...)
        for part in run_dir.parts:
            if part.upper().startswith("PMC-"):
                pmc_id = part.upper()
                break
    cif_path = find_cif_for_pmc(args.cif_dir, pmc_id) if pmc_id else None

    # Type map for reading lammpstrj files
    type_map = load_type_map(run_dir)
    specorder = None
    if type_map:
        specorder = [type_map[str(i + 1)] for i in range(len(type_map))]

    # ── Decide which references are available ──
    want_cif = "cif" in args.refs and cif_path is not None
    want_min = "minimised" in args.refs and min_path.exists()

    if "cif" in args.refs and cif_path is None:
        print(f"  WARNING: No CIF found for {pmc_id} in {args.cif_dir} -- skipping CIF reference")
    if "minimised" in args.refs and not min_path.exists():
        print(f"  WARNING: Minimised structure not found at {min_path} -- skipping")

    # ── Print summary ──
    print(f"\n{'=' * 60}")
    print(f"  RDF COMPARISON")
    print(f"{'=' * 60}")
    print(f"  Run directory : {run_dir}")
    print(f"  Trajectory    : {traj_path}")
    if want_cif:
        print(f"  CIF reference : {cif_path}")
    if want_min:
        print(f"  Minimised ref : {min_path}")
    print()

    # ── Load trajectory ──
    print("Reading trajectory...")
    frames = read(str(traj_path), index=":", format="extxyz")
    if not isinstance(frames, list):
        frames = [frames]
    frames = frames[args.skip::args.stride]
    if len(frames) == 0:
        sys.exit("ERROR: No frames left after --skip/--stride.")
    for f in frames:
        f.set_pbc(True)

    sim_cell = frames[0].get_cell()
    sim_lengths = sim_cell.cellpar()[:3]
    print(f"  {len(frames)} frames, {len(frames[0])} atoms, "
          f"cell {sim_lengths[0]:.2f}/{sim_lengths[1]:.2f}/{sim_lengths[2]:.2f} Å")

    mic_sim = 0.5 * float(min(sim_lengths))
    if args.rmax is None:
        rmax = 0.98 * mic_sim
        print(f"  rmax auto-set to {rmax:.2f} Å (min-image limit {mic_sim:.2f} Å)")
    else:
        rmax = min(args.rmax, 0.98 * mic_sim)
        print(f"  rmax = {rmax:.2f} Å")

    # ── Load + tile reference structures ──
    refs = {}
    if want_cif:
        unit = read(str(cif_path))
        unit.set_pbc(True)
        sc, reps = build_reference_supercell(unit, rmax)
        refs["cif"] = sc
        print(f"  CIF: {len(unit)} atoms -> {reps[0]}x{reps[1]}x{reps[2]} = {len(sc)} atoms")
    if want_min:
        read_kwargs = {}
        if min_format == "lammps-dump-text" and specorder:
            read_kwargs["specorder"] = specorder
        unit = read(str(min_path), format=min_format, **read_kwargs)
        unit.set_pbc(True)
        sc, reps = build_reference_supercell(unit, rmax)
        refs["min"] = sc
        print(f"  Min: {len(unit)} atoms -> {reps[0]}x{reps[1]}x{reps[2]} = {len(sc)} atoms")

    curve_order = ["sim"] + [k for k in ("cif", "min") if k in refs]

    elements = sorted(set(frames[0].get_chemical_symbols()))
    pairs = list(itertools.combinations_with_replacement(elements, 2))
    print(f"  Elements: {', '.join(elements)}")
    print(f"  Pairs ({len(pairs)}): {', '.join(a + '-' + b for a, b in pairs)}")
    print()

    # ── Output directory ──
    out_dir = run_dir / "rdf"
    out_dir.mkdir(exist_ok=True)

    # ── Check matplotlib ──
    have_mpl = True
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        have_mpl = False
        print("WARNING: matplotlib not installed -- .xvg written, .png skipped.\n")

    r = None
    data = {ck: {} for ck in curve_order}

    # ── Total RDF ──
    print("  Computing TOTAL RDF...")
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
        plt.title(f"Total RDF — {run_dir.name}")
        plt.legend()
        plt.tight_layout()
        plt.savefig(out_dir / "rdf_total.png", dpi=150)
        plt.close()
        print(f"  -> rdf_total.png")

    # ── Per-pair RDF ──
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
            plt.title(f"RDF {pair} — {run_dir.name}")
            plt.legend()
            plt.tight_layout()
            plt.savefig(out_dir / f"rdf_{pair}.png", dpi=150)
            plt.close()
        made += 1
        print(f"  {pair:6s}  -> rdf_{pair}.png")

    if made == 0:
        sys.exit("ERROR: No pair RDFs were computed.")

    # ── Combined xmgrace file ──
    labels = list(data["sim"].keys())
    combined = out_dir / "rdf_all_pairs.xvg"
    write_combined_xvg(combined, r, data, labels, run_dir.name, curve_order)

    print(f"\n{'=' * 60}")
    print(f"  RDF COMPLETE")
    print(f"{'=' * 60}")
    print(f"  {made} pairs + total RDF")
    print(f"  Curves per plot: {', '.join(CURVE_STYLE[ck][0] for ck in curve_order)}")
    print(f"  Output folder: {out_dir}/")
    print()


if __name__ == "__main__":
    main()