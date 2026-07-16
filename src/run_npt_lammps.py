#!/usr/bin/env python3
"""
run_npt_lammps.py
=================

LAMMPS + MACE version of the NPT workflow.

Workflow per (temperature, pressure):
    1) Minimisation
    2) NPT equilibration   (cell free to move, thermalises + relaxes density)
    3) NPT production      (cell free to move, sampling run)
    4) Optional RDF analysis

Mirrors run_nvt_lammps.py's restart-based continuity:
    minimisation.restart -> npt_equilibration.restart -> production

Output layout:

  <outdir>/<PMC_ID>/<model_tag>/NPT_results/
    01_minimisation/
    02_npt_equilibration/{T}K_{P}GPa/
    03_npt_production/{T}K_{P}GPa/
      production-trajectory.pdb   (only written if --save-pdb is passed)
"""

from __future__ import annotations

import argparse
import time
import shutil
from pathlib import Path
from typing import List, Optional

from ase import Atoms
from ase.io import read, write

import md_common as mc
import lammps_common as lc


# =============================================================================
# Helpers
# =============================================================================

def _format_temp_pressure_dir(temp_K: float, pressure_GPa: float) -> str:
    """300, 1.0 -> '300K_1GPa' ; 300.5, 0.5 -> '300.5K_0.5GPa'"""
    if abs(temp_K - round(temp_K)) < 1e-9:
        t = f"{int(round(temp_K))}"
    else:
        t = f"{temp_K:g}"

    if abs(pressure_GPa - round(pressure_GPa)) < 1e-9:
        p = f"{int(round(pressure_GPa))}"
    else:
        p = f"{pressure_GPa:g}"

    return f"{t}K_{p}GPa"


def _steps_from_ps(duration_ps: float, timestep_fs: float) -> int:
    """Convert duration in ps to number of MD steps."""
    timestep_ps = timestep_fs / 1000.0
    return int(round(duration_ps / timestep_ps))


def load_or_build_supercell(
    pmc_id: str,
    supercell_size: int,
    work_dir: Path,
) -> Atoms:
    """
    Build/read the starting supercell using md_common.generate_supercell(),
    then load the resulting CIF as ASE Atoms.
    """
    result = mc.generate_supercell(pmc_id, size=supercell_size)

    if not isinstance(result, dict):
        raise RuntimeError(
            f"md_common.generate_supercell({pmc_id}, size={supercell_size}) "
            f"returned unexpected value: {result}"
        )

    status = result.get("status")
    cif_path = result.get("path")

    if status not in {"success", "exists"} or not cif_path:
        raise RuntimeError(
            f"Failed to generate/load supercell for {pmc_id}. Result: {result}"
        )

    cif_path = Path(cif_path)
    if not cif_path.exists():
        raise FileNotFoundError(
            f"Supercell CIF reported by md_common does not exist: {cif_path}"
        )

    print(f"  📦 Using supercell CIF: {cif_path}")
    atoms = read(str(cif_path))

    # Optional cache copy for traceability only
    cache_path = (
        work_dir / f"{pmc_id}_supercell_{supercell_size}x{supercell_size}x{supercell_size}.pdb"
    )
    try:
        write(str(cache_path), atoms)
    except Exception:
        pass

    return atoms


def _wipe_stage_outputs(stage_dir: Path):
    """
    Remove files inside a stage directory so the stage can be rerun cleanly.
    Keeps the directory itself.
    """
    if not stage_dir.exists():
        return

    for p in stage_dir.iterdir():
        try:
            if p.is_file() or p.is_symlink():
                p.unlink()
            elif p.is_dir():
                shutil.rmtree(p)
        except Exception as e:
            print(f"    ⚠️ Could not remove {p}: {e}")


def print_stage_header(title: str):
    print()
    print("═" * 78)
    print(f"  {title}")
    print("═" * 78)


def maybe_run_rdf(
    *,
    production_dir: Path,
    rdf_bins: int,
    rdf_rmax: Optional[float],
):
    """Run rdf_analysis.py on the production trajectory if available. Optional/non-fatal."""
    traj_path = production_dir / lc.PROD_TRAJ_PDB
    if not traj_path.exists():
        print(f"  ⚠️ RDF skipped: production trajectory not found: {traj_path}")
        print("     (did you forget --save-pdb? production-trajectory.pdb is only "
              "written when that flag is passed)")
        return

    try:
        import rdf_analysis as ra

        for fn_name in ["run_rdf_analysis", "main_rdf", "analyze_rdf", "compute_rdf"]:
            if hasattr(ra, fn_name):
                fn = getattr(ra, fn_name)
                try:
                    print(f"  📈 Running RDF analysis via rdf_analysis.{fn_name}()")
                    fn(
                        trajectory=str(traj_path),
                        output_dir=str(production_dir / "rdf"),
                        bins=rdf_bins,
                        rmax=rdf_rmax,
                    )
                    return
                except TypeError:
                    try:
                        fn(str(traj_path), str(production_dir / "rdf"))
                        return
                    except Exception:
                        pass
                except Exception as e:
                    print(f"  ⚠️ RDF function call failed: {e}")
                    return
    except Exception:
        pass

    print("  ℹ️ RDF auto-run not wired to rdf_analysis.py API yet.")
    print(f"     Production trajectory: {traj_path}")


# =============================================================================
# One-(temperature, pressure)-point workflow
# =============================================================================

def run_single_point(
    *,
    pmc_id: str,
    temp_K: float,
    pressure_GPa: float,
    results_root: Path,
    model: str,
    supercell_size: int,
    eq_ps: float,
    prod_ps: float,
    timestep_fs: float,
    lammps_bin: Optional[str],
    skip_minimisation: bool,
    run_rdf_after: bool,
    rdf_bins: int,
    rdf_rmax: Optional[float],
    save_pdb: bool,
    restart_every_steps: int,
    resume_policy: str = "extend",
):
    """
    Full workflow for one (temperature, pressure) point:
        1) minimisation
        2) NPT equilibration
        3) NPT production
        4) optional RDF
    """
    point_dir_name = _format_temp_pressure_dir(temp_K, pressure_GPa)

    min_dir = results_root / "01_minimisation"
    eq_dir = results_root / "02_npt_equilibration" / point_dir_name
    prod_dir = results_root / "03_npt_production" / point_dir_name

    # If overwrite is requested, wipe NPT stage outputs so they rerun cleanly.
    # Minimisation is left alone unless you explicitly skip/remove it.
    if resume_policy == "overwrite":
        if eq_dir.exists():
            print(f"  🗑 Overwrite policy: clearing equilibration stage at {eq_dir}")
            _wipe_stage_outputs(eq_dir)
        if prod_dir.exists():
            print(f"  🗑 Overwrite policy: clearing production stage at {prod_dir}")
            _wipe_stage_outputs(prod_dir)

    # -------------------------------------------------------------------------
    # Starting structure
    # -------------------------------------------------------------------------
    print_stage_header(f"{pmc_id} | Preparing starting structure")
    starting_atoms = load_or_build_supercell(pmc_id, supercell_size, results_root)
    print(f"  🧱 Supercell atoms: {len(starting_atoms)}")
    print(f"  📦 Cell volume: {starting_atoms.get_volume():.3f} Å³")

    # -------------------------------------------------------------------------
    # 1) Minimisation
    # -------------------------------------------------------------------------
    if skip_minimisation:
        print_stage_header(f"{pmc_id} | Minimisation skipped")
        min_restart = min_dir / "minimisation.restart"
        min_last = min_dir / lc.LAST_FRAME_PDB

        if min_restart.exists():
            print(f"  ↪ Using existing minimisation restart: {min_restart}")
            if min_last.exists():
                atoms_after_min = read(str(min_last))
            else:
                atoms_after_min = starting_atoms
            min_result = {
                "atoms": atoms_after_min,
                "restart_path": min_restart,
                "last_frame_path": min_last,
            }
        else:
            raise FileNotFoundError(
                "skip-minimisation was requested but no minimisation restart exists at "
                f"{min_restart}"
            )
    else:
        print_stage_header(f"{pmc_id} | Stage 1/3: Minimisation")
        min_result = lc.run_minimisation_stage(
            atoms=starting_atoms,
            stage_dir=min_dir,
            model_path=model,
            lammps_bin=lammps_bin,
            timestep_fs=timestep_fs,
            save_pdb=save_pdb,
        )

    # -------------------------------------------------------------------------
    # 2) NPT equilibration
    # -------------------------------------------------------------------------
    eq_steps = _steps_from_ps(eq_ps, timestep_fs)
    print_stage_header(
        f"{pmc_id} | Stage 2/3: NPT Equilibration @ {temp_K:g} K, {pressure_GPa:g} GPa "
        f"({eq_ps:g} ps = {eq_steps} steps)"
    )

    eq_result = lc.run_npt_stage(
        stage_dir=eq_dir,
        model_path=model,
        temp_K=temp_K,
        pressure_GPa=pressure_GPa,
        nsteps=eq_steps,
        stage_label="NPT Equilibration",
        init_velocities=True,   # only when starting from minimisation
        traj_name=lc.TRAJ_PDB,
        view_log_name=lc.EQ_VIEW_LOG,
        timestep_fs=timestep_fs,
        lammps_bin=lammps_bin,
        read_restart_path=min_result["restart_path"],
        save_pdb=save_pdb,
        restart_every_steps=restart_every_steps,
        resume_mode=("overwrite" if resume_policy == "overwrite" else "reuse"),
    )

    # -------------------------------------------------------------------------
    # 3) NPT production
    # -------------------------------------------------------------------------
    prod_steps = _steps_from_ps(prod_ps, timestep_fs)
    print_stage_header(
        f"{pmc_id} | Stage 3/3: NPT Production @ {temp_K:g} K, {pressure_GPa:g} GPa "
        f"({prod_ps:g} ps = {prod_steps} steps)"
    )

    prod_result = lc.run_npt_stage(
        stage_dir=prod_dir,
        model_path=model,
        temp_K=temp_K,
        pressure_GPa=pressure_GPa,
        nsteps=prod_steps,
        stage_label="NPT Production",
        init_velocities=False,  # preserve eq velocities via restart
        traj_name=lc.PROD_TRAJ_PDB,
        view_log_name=lc.PROD_VIEW_LOG,
        timestep_fs=timestep_fs,
        lammps_bin=lammps_bin,
        read_restart_path=eq_result["restart_path"],
        save_pdb=save_pdb,
        restart_every_steps=restart_every_steps,
        resume_mode=("overwrite" if resume_policy == "overwrite" else "reuse"),
    )

    # -------------------------------------------------------------------------
    # 4) RDF
    # -------------------------------------------------------------------------
    if run_rdf_after:
        print_stage_header(f"{pmc_id} | RDF analysis @ {temp_K:g} K, {pressure_GPa:g} GPa")
        maybe_run_rdf(
            production_dir=prod_dir,
            rdf_bins=rdf_bins,
            rdf_rmax=rdf_rmax,
        )

    print_stage_header(f"{pmc_id} | Finished {temp_K:g} K, {pressure_GPa:g} GPa")
    print(f"  Final production structure volume: {prod_result['final_volume_A3']:.3f} Å³")
    print(f"  Production trajectory dir: {prod_dir}")


# =============================================================================
# CLI
# =============================================================================

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run NPT MD using LAMMPS + MACE for a PMC crystal."
    )

    p.add_argument("--pmc", required=True, help="PMC ID, e.g. PMC-001")
    p.add_argument(
        "--temps",
        required=True,
        nargs="+",
        type=float,
        help="Temperature(s) in K, e.g. --temps 300 350 400",
    )
    p.add_argument(
        "--pressure",
        required=True,
        type=float,
        help="Pressure in GPa, e.g. --pressure 1.0",
    )
    p.add_argument(
        "--model",
        default="medium",
        help=(
            "MACE model source or alias. Examples:\n"
            "  medium\n"
            "  /path/to/MACE-OFF23_medium.model\n"
            "  /path/to/MACE-OFF23_medium.model-mliap_lammps.pt"
        ),
    )
    p.add_argument(
        "--supercell",
        type=int,
        default=2,
        help="Supercell size N for NxNxN supercell (default: 2)",
    )
    p.add_argument(
        "--outdir",
        type=str,
        default=None,
        help=(
            "Root directory under which results are written, as "
            "<outdir>/<PMC_ID>/<MODEL>/NPT_results. Defaults to the current "
            "working directory. Pass a path to override, e.g. --outdir /scratch/runs"
        ),
    )

    p.add_argument(
        "--eq-ps",
        type=float,
        default=10.0,
        help="NPT equilibration duration in ps (default: 10)",
    )
    p.add_argument(
        "--prod-ps",
        type=float,
        default=1000.0,
        help="NPT production duration in ps (default: 1000 = 1 ns)",
    )
    p.add_argument(
        "--timestep-fs",
        type=float,
        default=0.5,
        help="LAMMPS timestep in fs (default: 0.5)",
    )

    p.add_argument(
        "--lammps-bin",
        default=None,
        help="Path to lmp executable. If omitted, uses LAMMPS_BIN / LAMMPS_INSTALL / PATH.",
    )

    p.add_argument(
        "--skip-minimisation",
        action="store_true",
        help="Skip minimisation and start from an existing minimisation.restart",
    )
    p.add_argument(
        "--run-rdf",
        action="store_true",
        help="Run RDF analysis after production if rdf_analysis.py is callable.",
    )
    p.add_argument(
        "--save-pdb",
        action="store_true",
        help=(
            "Also write trajectory.pdb / last-frame-of-trajectory.pdb / "
            "production-trajectory.pdb for every stage. Off by default. "
            "REQUIRED if you plan to run rdf_compare.py on this output — "
            "it needs production-trajectory.pdb."
        ),
    )
    p.add_argument(
        "--restart-every",
        type=int,
        default=100,
        help=(
            "Steps between intermediate LAMMPS restart checkpoints written during "
            "each NPT stage (the 'restart N file.*' command), separate from the "
            "single write_restart at the end of the stage. Default: 100."
        ),
    )
    p.add_argument(
        "--resume-policy",
        choices=["reuse", "extend", "overwrite"],
        default="extend",
        help=(
            "How to handle existing stage outputs for the same PMC/model/temperature/pressure. "
            "'reuse' = keep completed stages as-is and skip them; "
            "'extend' = continue shorter equilibration/production runs up to the requested length; "
            "'overwrite' = rerun stages from scratch and replace existing outputs."
        ),
    )

    p.add_argument("--rdf-bins", type=int, default=300, help="RDF bins (default: 300)")
    p.add_argument("--rdf-rmax", type=float, default=None, help="Optional RDF rmax in Å")

    return p


def main():
    args = build_parser().parse_args()

    pmc_id = args.pmc
    temps: List[float] = list(args.temps)
    pressure = args.pressure

    # Make result directories model-specific so small/medium/large runs do not collide.
    outdir_base = Path(args.outdir).resolve() if args.outdir else Path.cwd()
    model_arg = str(args.model)
    model_tag = Path(model_arg).stem if any(sep in model_arg for sep in ("/", "\\")) else model_arg
    model_tag = model_tag.replace(" ", "_")

    results_root = outdir_base / pmc_id / model_tag / "NPT_results"
    results_root.mkdir(parents=True, exist_ok=True)

    print()
    print("══════════════════════════════════════════════════════════════════════════════")
    print("  LAMMPS + MACE NPT workflow")
    print("══════════════════════════════════════════════════════════════════════════════")
    print(f"  PMC ID        : {pmc_id}")
    print(f"  Temperatures  : {temps}")
    print(f"  Pressure      : {pressure} GPa")
    print(f"  Model         : {args.model}")
    print(f"  Supercell     : {args.supercell}x{args.supercell}x{args.supercell}")
    print(f"  Eq duration   : {args.eq_ps} ps")
    print(f"  Prod duration : {args.prod_ps} ps")
    print(f"  Timestep      : {args.timestep_fs} fs")
    print(f"  Restart every : {args.restart_every} steps")
    print(f"  Resume policy : {args.resume_policy}")
    print(f"  Save PDB      : {args.save_pdb}")
    if not args.save_pdb:
        print("  ⚠️  --save-pdb not set: production-trajectory.pdb will NOT be written "
              "(rdf_compare.py needs it)")
    print(f"  Results dir   : {results_root}")
    print()

    t0 = time.time()

    for temp in temps:
        run_single_point(
            pmc_id=pmc_id,
            temp_K=temp,
            pressure_GPa=pressure,
            results_root=results_root,
            model=args.model,
            supercell_size=args.supercell,
            eq_ps=args.eq_ps,
            prod_ps=args.prod_ps,
            timestep_fs=args.timestep_fs,
            lammps_bin=args.lammps_bin,
            skip_minimisation=args.skip_minimisation,
            run_rdf_after=args.run_rdf,
            rdf_bins=args.rdf_bins,
            rdf_rmax=args.rdf_rmax,
            save_pdb=args.save_pdb,
            restart_every_steps=args.restart_every,
            resume_policy=args.resume_policy,
        )

    elapsed = time.time() - t0
    print()
    print("══════════════════════════════════════════════════════════════════════════════")
    print(f"  All requested temperatures finished in {elapsed/60:.1f} min")
    print("══════════════════════════════════════════════════════════════════════════════")


if __name__ == "__main__":
    main()