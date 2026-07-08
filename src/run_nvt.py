"""
run_nvt.py — NVT-only MD pipeline for Piezoelectric Molecular Crystals
────────────────────────────────────────────────────────────────────
Pipeline (always in this order, per temperature):
  1. Minimisation        shared across temperatures, T = 0 K
  2. NVT Equilibration   fixed cell, thermalises the system at target T
  3. NVT Production      fixed cell, sampling run at target T
                          + RDF vs R (simulation / actual / minimised)

Everything lives under its own NVT_results/ tree — this script never
touches NPT output, and run_npt.py never touches this one.

Usage:
  python3 run_nvt.py PMC-007
  python3 run_nvt.py PMC-007 --temps 100 200 300 400
  python3 run_nvt.py PMC-007 --timestep 0.5 --eq-steps 20000 --steps 200000
  python3 run_nvt.py PMC-007 --size 3
  python3 run_nvt.py all
  python3 run_nvt.py --list
  python3 run_nvt.py PMC-007 --status            # progress trace, no simulation
  python3 run_nvt.py PMC-007 --slice-steps 50000  # run only 50k steps this call,
                                                    # rerun later to continue

Output layout:
  simulations/{pmc}/NVT_results/
    01_minimisation/
      trajectory.pdb                  every LBFGS step
      last-frame-of-trajectory.pdb
      minimisation.log
      state.json / minimisation.restart.extxyz     (checkpoint)
    02_nvt_equilibration/{T}K/
      trajectory.pdb
      last-frame-of-trajectory.pdb
      nvt-equilibration.log
      nvt_equilibration_temp.png
      state.json / restart.extxyz                  (checkpoint)
    03_nvt_production/{T}K/
      production-trajectory.pdb
      last-frame-of-trajectory.pdb
      nvt-production.log
      rdf_vs_r.png                    simulation vs actual vs minimised
      rdf_all_pairs.xvg               every element-pair g(r), GROMACS-style
      state.json / restart.extxyz                  (checkpoint)

Every stage is independently checkpointed and resumable, and every
stage additionally honours --slice-steps: pass e.g. --slice-steps 20000
to cap the number of MD/optimiser steps executed in *this* process
invocation (across whichever stage is currently in progress). Rerun
the exact same command to pick up where it left off — this is how you
run a very large simulation as a series of smaller slices.
"""
import os
import sys
import time
import argparse
import warnings
from pathlib import Path
from datetime import datetime

warnings.filterwarnings("ignore", message=".*not interpreted for space group.*")
warnings.filterwarnings("ignore", message=".*weights_only.*")
warnings.filterwarnings("ignore", message=".*Pandas requires version.*")
warnings.filterwarnings("ignore", message=".*TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD.*")
warnings.filterwarnings("ignore", category=UserWarning, module="mace")
warnings.filterwarnings("ignore", category=UserWarning, module="pandas")
warnings.filterwarnings("ignore", category=UserWarning, module="e3nn")

sys.path.insert(0, str(Path(__file__).resolve().parent))
import md_common as mc


def run_nvt_pipeline(pmc_id: str, temperatures: list, size: int,
                      timestep_fs: float, eq_steps: int, prod_steps: int,
                      mace_model: str, budget: "mc.StepBudget"):
    from ase.io import read, write
    import torch

    size_str = f"{size}x{size}x{size}"
    cif_path = mc.SIM_DIR / pmc_id / f"{pmc_id}_supercell_{size_str}.cif"
    if not cif_path.exists():
        print(f"  ❌ Supercell not found: {cif_path}")
        return False

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"  Device: {device}")
    print(f"  Timestep: {timestep_fs} fs")
    print(f"  NVT Equilibration: {eq_steps} steps -> {eq_steps*timestep_fs/1000:.2f} ps")
    print(f"  NVT Production:    {prod_steps} steps -> {prod_steps*timestep_fs/1000:.2f} ps")

    atoms_raw = read(str(cif_path))
    print(f"  Loaded: {len(atoms_raw)} atoms")

    from mace.calculators import mace_off
    calc = mace_off(model=mace_model, device=device, default_dtype="float64")
    atoms_raw.calc = calc

    results_dir = mc.SIM_DIR / pmc_id / "NVT_results"
    results_dir.mkdir(parents=True, exist_ok=True)

    # ── Stage 1: Minimisation (shared across all temperatures) ──
    print(f"\n  ── Minimisation ──")
    min_dir = results_dir / "01_minimisation"
    atoms_min, _, min_finished = mc.run_minimisation(atoms_raw, calc, min_dir, budget=budget)
    if not min_finished:
        print("\n  ⏸  Slice budget exhausted during minimisation — "
              "rerun this command to continue.")
        return True

    ref_a, ref_b, ref_c, *_ = atoms_min.get_cell().cellpar()
    print(f"  Reference lattice (minimised): a={ref_a:.4f} b={ref_b:.4f} c={ref_c:.4f} Å")

    # ── Reference RDFs used in every production plot ──
    # "actual"    = the as-loaded supercell geometry straight from the CIF
    # "minimised" = the geometry after LBFGS minimisation
    elements = sorted(set(atoms_min.get_chemical_symbols()))
    print(f"  Computing reference RDFs (actual + minimised)...")
    r_grid, actual_total, actual_pairs = mc.compute_rdf_single(atoms_raw, elements=elements)
    _, min_total, min_pairs = mc.compute_rdf_single(atoms_min, elements=elements)

    # ── Per temperature: NVT Equilibration -> NVT Production ──
    for temp in temperatures:
        print(f"\n  ── {temp} K ──")
        eq_dir = results_dir / "02_nvt_equilibration" / f"{temp}K"
        prod_dir = results_dir / "03_nvt_production" / f"{temp}K"

        print(f"  [NVT] Equilibration")
        atoms_eq, _, eq_finished = mc.run_md_stage(
            atoms_min, calc, eq_steps, timestep_fs, temp, eq_dir,
            dyn_type="nvt",
            init_velocities=True,
            plot_kind="temp",
            traj_name="trajectory.pdb",
            stage_label="NVT Equilibration",
            budget=budget,
            log_name="thermo.csv",
            view_log_name="nvt-equilibration.log",
            )
        if not eq_finished:
            print("\n  ⏸  Slice budget exhausted — rerun this command to continue.")
            return True

        print(f"  [NVT] Production")
        atoms_prod, _, prod_finished = mc.run_md_stage(
            atoms_eq, calc, prod_steps, timestep_fs, temp, prod_dir,
            dyn_type="nvt",
            init_velocities=False,
            plot_kind=None,
            traj_name="production-trajectory.pdb",
            stage_label="NVT Production",
            budget=budget,
            log_name="thermo.csv",
            view_log_name="nvt-production.log",
            )
        if not prod_finished:
            print("\n  ⏸  Slice budget exhausted — rerun this command to continue.")
            return True

        # ── RDF: simulation (averaged over production trajectory) vs
        #    actual vs minimised ──
        prod_traj = prod_dir / "production-trajectory.pdb"
        print(f"  [NVT] Computing simulation RDF from {prod_traj.name} ...")
        _, sim_total, sim_pairs = mc.compute_rdf_trajectory(prod_traj, elements=elements)

        rdf_plot_path = prod_dir / "rdf_vs_r.png"
        mc.plot_rdf_comparison(
            r_grid,
            {
                f"simulation ({temp} K, production)": (sim_total, "C0"),
                "actual (as-loaded CIF)": (actual_total, "C1"),
                "minimised": (min_total, "C2"),
            },
            rdf_plot_path,
            f"RDF vs R — {pmc_id} @ {temp} K (NVT production)",
        )
        print(f"    💾 Saved plot (RDF vs R): {rdf_plot_path}")

        xvg_path = prod_dir / "rdf_all_pairs.xvg"
        # Combine all three states' pair RDFs into one xvg for full traceability.
        combined_pairs = {}
        for k in sim_pairs:
            combined_pairs[f"sim_{k}"] = sim_pairs[k]
        for k in actual_pairs:
            combined_pairs[f"actual_{k}"] = actual_pairs[k]
        for k in min_pairs:
            combined_pairs[f"min_{k}"] = min_pairs[k]
        mc.save_rdf_xvg(xvg_path, r_grid, sim_total, combined_pairs,
                         f"RDF all pairs — {pmc_id} @ {temp} K (NVT production)")
        print(f"    💾 Saved RDF xvg (all pairs): {xvg_path}")

    print(f"\n  ✅ {pmc_id} NVT pipeline complete! Results: {results_dir}")
    return True


def main():
    parser = argparse.ArgumentParser(description="NVT-only MD pipeline (Piezo-LLM)")
    parser.add_argument("molecule", nargs="?", help="PMC ID (e.g. PMC-007) or 'all'")
    parser.add_argument("--temps", nargs="+", type=int, default=[300])
    parser.add_argument("--size", type=int, default=2)
    parser.add_argument("--timestep", type=float, default=mc.DEFAULT_TIMESTEP_FS)
    parser.add_argument("--eq-steps", type=int, default=mc.DEFAULT_EQ_STEPS)
    parser.add_argument("--steps", type=int, default=mc.DEFAULT_PROD_STEPS,
                         help="NVT production steps")
    parser.add_argument("--model", default="medium", choices=["small", "medium", "large"])
    parser.add_argument("--slice-steps", type=int, default=None,
                         help="Cap on MD/optimiser steps run in this invocation "
                              "(run the same command again to continue).")
    parser.add_argument("--status", action="store_true",
                         help="Print checkpoint progress and exit (no simulation run).")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    os.environ["TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD"] = "1"

    print("=" * 60)
    print("  Piezo-LLM: NVT MD Pipeline")
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    if args.list:
        molecules = mc.get_available_molecules()
        print(f"\n  Available molecules ({len(molecules)}):\n")
        print(f"  {'PMC ID':<12} {'Has CIF':<10} {'Molecule Name'}")
        print(f"  {'─'*60}")
        for m in molecules:
            mark = "✅" if m["has_cif"] else "❌"
            print(f"  {m['pmc_id']:<12} {mark:<10} {m['molecule_name']}")
        return

    if not args.molecule:
        parser.print_help()
        return

    if args.molecule.lower() == "all":
        molecules = mc.get_available_molecules()
        pmc_ids = [m["pmc_id"] for m in molecules if m["has_cif"]]
    else:
        pmc_id = args.molecule.upper()
        if not pmc_id.startswith("PMC-"):
            pmc_id = f"PMC-{pmc_id}"
        pmc_ids = [pmc_id]

    if args.status:
        for pmc_id in pmc_ids:
            mc.print_progress_table(mc.SIM_DIR / pmc_id / "NVT_results", f"{pmc_id} — NVT")
        return

    print(f"  Temperatures: {args.temps} K")
    print(f"  Supercell: {args.size}x{args.size}x{args.size}")
    print(f"  Timestep: {args.timestep} fs")
    print(f"  NVT Equilibration: {args.eq_steps} steps")
    print(f"  NVT Production:    {args.steps} steps")
    print(f"  MACE model: {args.model}")
    if args.slice_steps:
        print(f"  Slice budget: {args.slice_steps} steps this invocation")
    print(f"  Molecules: {len(pmc_ids)}")

    results = {}
    total_start = time.time()
    for i, pmc_id in enumerate(pmc_ids, 1):
        print(f"\n{'▓'*60}\n  [{i}/{len(pmc_ids)}] {pmc_id}\n{'▓'*60}")

        cif = mc.find_cif(pmc_id)
        if not cif:
            print("  ❌ No CIF file found, skipping")
            results[pmc_id] = "no_cif"
            continue

        print("\n  Generating supercell...")
        sc = mc.generate_supercell(pmc_id, args.size)
        if sc["status"] == "error":
            print(f"  ❌ {sc['message']}")
            results[pmc_id] = "supercell_failed"
            continue

        budget = mc.StepBudget(args.slice_steps)
        try:
            success = run_nvt_pipeline(
                pmc_id, args.temps, args.size, args.timestep,
                args.eq_steps, args.steps, args.model, budget,
            )
            results[pmc_id] = "success" if success else "failed"
        except Exception as e:
            print(f"  ❌ Error: {e}")
            results[pmc_id] = f"error: {str(e)}"

    total_time = time.time() - total_start
    print(f"\n\n{'='*60}\n  NVT Pipeline Complete!\n  Total time: {total_time/60:.1f} minutes\n{'='*60}")
    print(f"\n  {'PMC ID':<12} {'Status'}\n  {'─'*40}")
    for pmc_id, status in results.items():
        icon = "✅" if status == "success" else "❌"
        print(f"  {pmc_id:<12} {icon} {status}")
    ok = sum(1 for s in results.values() if s == "success")
    print(f"\n  {ok}/{len(results)} completed successfully")
    print(f"  Results in: {mc.SIM_DIR}")


if __name__ == "__main__":
    main()