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

Works against either pipeline via --engine (default: mace-ase):

  --engine mace-ase (default, direct-ASE MACE-OFF23 pipeline):
    data/<PMC>/*.cif
    simulations/<PMC>/NVT_results/01_minimisation/last-frame-of-trajectory.pdb
    simulations/<PMC>/NVT_results/03_nvt_production/<T>K/production-trajectory.pdb
    simulations/<PMC>/NPT_results/01_minimisation/last-frame-of-trajectory.pdb
    simulations/<PMC>/NPT_results/04_npt_production/<T>K/trajectory.pdb

  --engine lammps (MACE-LAMMPS pipeline):
    data/<PMC>/*.cif
    MACE-LAMMPS/<PMC>/NVT_results/01_minimisation/*.lammps           (nocoeff data file; type->element
                                                                       recovered from state.json / *.in)
    MACE-LAMMPS/<PMC>/NVT_results/03_nvt_production/<T>K/*.lammpstrj (dump text, with 'element' column)
    MACE-LAMMPS/<PMC>/NPT_results/01_minimisation/*.lammps
    MACE-LAMMPS/<PMC>/NPT_results/03_npt_production/<T>K_<P>GPa/*.lammpstrj
    (NPT on this pipeline also needs --pressure to pick the right <T>K_<P>GPa folder)

Usage:
  python3 rdf_compare.py PMC-001 --temp 300
  python3 rdf_compare.py PMC-001 --temp 300 --skip 80 --nbins 200
  python3 rdf_compare.py PMC-001 --temp 300 --refs cif          # only CIF ref
  python3 rdf_compare.py PMC-001 --temp 300 --refs cif minimised # both (default)
  python3 rdf_compare.py PMC-001 --temp 300 --engine mace-ase --model medium
  python3 rdf_compare.py PMC-001 --temp 300 --engine lammps --ensemble npt --pressure 1.0

Note: --engine mace-ase requires --model {small,medium} — each MACE-OFF23 model
size (SMALL-model/, MEDIUM-model/) has its own local simulations/ folder.
--engine lammps has no model-size variants (single MACE-LAMMPS/ root) and
ignores --model.

Outputs (in <root>/<PMC>/{NVT,NPT}_results/0{3,4}_..._production/<T>K[_<P>GPa]/rdf_compare/):
  rdf_total.png       ONE graph: total g(r) vs r — simulation vs actual (CIF) vs minimised
  rdf_all_pairs.xvg   one xmgrace file: r, then TOTAL + g_sim (+ g_cif / g_min) per pair
  rdf_<A>-<B>.png     one plot per element pair overlaying the available curves
"""

import sys
import json
import argparse
import itertools
from pathlib import Path

import numpy as np
from ase.io import read
from ase.data import atomic_numbers
from ase.geometry.rdf import get_rdf

PROJECT_ROOT = Path.home() / "himesh_work"
DATA_DIR = PROJECT_ROOT / "data"

# lammps: single root, no model-size variants (confirmed: MACE-LAMMPS/{pmc}/...)
# mace-ase: root depends on which MACE-OFF23 model size was used to run the
#           simulation — confirmed each model size has its own local simulations/
#           folder (MACE-off-23/SMALL-model/simulations/, .../MEDIUM-model/simulations/)
MACE_OFF23_DIR = PROJECT_ROOT / "MACE-off-23"
MODEL_DIR_NAMES = {"small": "SMALL-model", "medium": "MEDIUM-model"}


def resolve_sim_root(engine: str, model):
    if engine == "lammps":
        return PROJECT_ROOT / "MACE-LAMMPS"
    # engine == "mace-ase"
    if model is None:
        sys.exit("❌ --model {small,medium} is required for --engine mace-ase "
                  "(each MACE-OFF23 model size has its own simulations/ folder).")
    return MACE_OFF23_DIR / MODEL_DIR_NAMES[model] / "simulations"


def find_cif(pmc_id: str) -> Path:
    folder = DATA_DIR / pmc_id
    if not folder.exists():
        return None
    cifs = list(folder.glob("*.cif"))
    return cifs[0] if cifs else None


def get_lammps_element_order(dir_path: Path):
    """Recover atom-type -> element mapping order for a LAMMPS run folder.

    Preferred source: a *.json state file with an 'element_order' key
    (written by the LAMMPS launcher). Fallback: parse the 'pair_coeff * * ...'
    line out of the corresponding *.in script.
    """
    for sj in sorted(dir_path.glob("*.json")):
        try:
            d = json.loads(sj.read_text())
        except Exception:
            continue
        if isinstance(d, dict) and d.get("element_order"):
            return list(d["element_order"])

    for infile in sorted(dir_path.glob("*.in")):
        for line in infile.read_text().splitlines():
            line = line.strip()
            if not line.startswith("pair_coeff"):
                continue
            parts = line.split()
            star_idx = [i for i, p in enumerate(parts) if p == "*"]
            if len(star_idx) >= 2:
                elems = [p for p in parts[star_idx[1] + 1:] if p.isalpha()]
                if elems:
                    return elems
    return None


def find_one(dir_path: Path, pattern: str, exclude_substrings=()):
    """Find a single file matching a glob pattern in dir_path, excluding
    any whose name contains one of exclude_substrings. Errors out clearly
    if zero or multiple matches remain."""
    candidates = [p for p in sorted(dir_path.glob(pattern))
                  if not any(x in p.name for x in exclude_substrings)]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) == 0:
        sys.exit(f"❌ No file matching {pattern!r} found in {dir_path}")
    sys.exit(f"❌ Multiple files matching {pattern!r} found in {dir_path}: "
              f"{[c.name for c in candidates]} — narrow this down manually.")


def read_lammps_trajectory(traj_path: Path, element_order, skip, stride):
    """Read a LAMMPS dump-text trajectory. The dump includes an explicit
    'element' column (via dump_modify ... element ...), which ASE prioritises
    over atom type, so element_order is only used as a fallback specorder."""
    frames = read(str(traj_path), index=":", format="lammps-dump-text",
                  specorder=element_order, units="metal")
    if not isinstance(frames, list):
        frames = [frames]
    return frames[skip::stride]


def read_lammps_structure(path: Path, element_order):
    """Read a LAMMPS data file (atom_style atomic, written with nocoeff),
    mapping numeric atom types back to elements via element_order."""
    z_of_type = {i + 1: atomic_numbers[el] for i, el in enumerate(element_order)}
    atoms = read(str(path), format="lammps-data", style="atomic",
                 Z_of_type=z_of_type, units="metal")
    return atoms


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
    ap.add_argument("--engine", default="mace-ase", choices=["lammps", "mace-ase"],
                    help="which pipeline's output to analyse (default: mace-ase)")
    ap.add_argument("--model", default=None, choices=["small", "medium"],
                    help="MACE-OFF23 model size — required for --engine mace-ase "
                         "(SMALL-model/ vs MEDIUM-model/, each with its own simulations/)")
    ap.add_argument("--pressure", type=float, default=None,
                    help="pressure in GPa — required for --engine lammps --ensemble npt "
                         "(matches the {T}K_{P}GPa folder written by run_npt_lammps.py)")
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

    SIM_DIR = resolve_sim_root(args.engine, args.model)

    is_lammps = args.engine == "lammps"

    tdir = SIM_DIR / pmc_id / f"{args.ensemble.upper()}_results"
    if args.ensemble == "nvt":
        # Identical folder convention on both pipelines.
        tdir = tdir / "03_nvt_production" / f"{args.temp}K"
        if is_lammps:
            traj_path = find_one(tdir, "*.lammpstrj")
        else:
            traj_path = tdir / "production-trajectory.pdb"
    else:
        if is_lammps:
            if args.pressure is None:
                sys.exit("❌ --pressure is required for --engine lammps --ensemble npt "
                          "(e.g. --pressure 1.0)")
            npt_root = tdir / "03_npt_production"
            exact = npt_root / f"{args.temp}K_{args.pressure}GPa"
            if exact.exists():
                tdir = exact
            else:
                # Formatting of the pressure value in the folder name (e.g. "1.0" vs "1")
                # isn't 100% pinned down yet — fall back to a glob match on temperature.
                candidates = sorted(npt_root.glob(f"{args.temp}K_*GPa")) if npt_root.exists() else []
                if len(candidates) == 1:
                    tdir = candidates[0]
                elif len(candidates) > 1:
                    sys.exit(f"❌ Multiple pressure folders match {args.temp}K_*GPa under "
                              f"{npt_root} — pass the exact --pressure value: "
                              f"{[c.name for c in candidates]}")
                else:
                    sys.exit(f"❌ NPT folder not found: {exact} (no {args.temp}K_*GPa match either)")
            traj_path = find_one(tdir, "*.lammpstrj")
        else:
            tdir = tdir / "04_npt_production" / f"{args.temp}K"
            traj_path = tdir / "trajectory.pdb"
    if not traj_path.exists():
        sys.exit(f"❌ Trajectory not found: {traj_path}")

    cif_path = find_cif(pmc_id)
    min_dir = SIM_DIR / pmc_id / f"{args.ensemble.upper()}_results" / "01_minimisation"
    if is_lammps:
        # Written via `write_data ... nocoeff`; exclude the pre-minimisation
        # starting structure, restart files, and the run log (also *.lammps).
        preferred = min_dir / "minimised_structure.lammps"
        if preferred.exists():
            min_path = preferred
        elif min_dir.exists():
            min_path = find_one(min_dir, "*.lammps",
                                 exclude_substrings=("starting_structure", "log."))
        else:
            min_path = preferred
    else:
        min_path = min_dir / "last-frame-of-trajectory.pdb"

    lammps_elements = None
    if is_lammps:
        lammps_elements = get_lammps_element_order(tdir) or get_lammps_element_order(min_dir)
        if lammps_elements is None:
            sys.exit(f"❌ Could not determine LAMMPS type→element mapping from "
                      f"{tdir} or {min_dir} (no state.json with element_order, "
                      f"no pair_coeff line in a *.in file).")
        print(f"  LAMMPS element order (type 1..N): {lammps_elements}")

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
    if is_lammps:
        frames = read_lammps_trajectory(traj_path, lammps_elements, args.skip, args.stride)
    else:
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
        if is_lammps:
            unit = read_lammps_structure(min_path, lammps_elements)
        else:
            unit = read(str(min_path))
        unit.set_pbc(True)
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