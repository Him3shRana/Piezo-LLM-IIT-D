#!/usr/bin/env python3
"""
run_nvt_lammps_polar.py
========================

LAMMPS + PolarMACE version of the NVT workflow, using skaiser29's
dev-fork build of MACE + LAMMPS (single-GPU PolarMACE support — not
merged upstream; see ACEsuit/mace#1409/#1403). Mirrors run_nvt_lammps.py
exactly in structure and CLI conventions, adding the PolarMACE runtime
context (--charge / --spin / --external-field) carried over from
run_nvt_polar.py (the ASE-based pipeline).

===============================================================================
⚠️  The pair_style/context wiring in lammps_common_polar.py is a PLACEHOLDER
    until a real working Polar .in file from the GPU build is available.
    Everything else here (CLI, restart continuity, checkpointing, RDF hook,
    output layout) is complete and matches run_nvt_lammps.py.
===============================================================================

Workflow per temperature:
    1) Minimisation
    2) NVT equilibration
    3) NVT production
    4) Optional RDF analysis

Usage:
    python3 run_nvt_lammps_polar.py --pmc PMC-001 --model medium \\
        --temps 300 --charge 0.0 --spin 1.0
"""

from __future__ import annotations

import argparse
import shutil
import time
from pathlib import Path
from typing import List, Optional, Tuple

from ase import Atoms
from ase.io import read, write

import md_common as mc
import lammps_common as lc
import lammps_common_polar as lcp


# =============================================================================
# Helpers (identical to run_nvt_lammps.py)
# =============================================================================

def _format_temp_dir(temp: float) -> str:
    if abs(temp - round(temp)) < 1e-9:
        return f"{int(round(temp))}K"
    return f"{temp:g}K"


def _steps_from_ps(duration_ps: float, timestep_fs: float) -> int:
    timestep_ps = timestep_fs / 1000.0
    return int(round(duration_ps / timestep_ps))


def load_or_build_supercell(pmc_id: str, supercell_size: int, work_dir: Path) -> Atoms:
    result = mc.generate_supercell(pmc_id, size=supercell_size)

    if not isinstance(result, dict):
        raise RuntimeError(
            f"md_common.generate_supercell({pmc_id}, size={supercell_size}) "
            f"returned unexpected value: {result}"
        )

    status = result.get("status")
    cif_path = result.get("path")

    if status not in {"success", "exists"} or not cif_path:
        raise RuntimeError(f"Failed to generate/load supercell for {pmc_id}. Result: {result}")

    cif_path = Path(cif_path)
    if not cif_path.exists():
        raise FileNotFoundError(f"Supercell CIF reported by md_common does not exist: {cif_path}")

    print(f"  📦 Using supercell CIF: {cif_path}")
    atoms = read(str(cif_path))

    cache_path = work_dir / f"{pmc_id}_supercell_{supercell_size}x{supercell_size}x{supercell_size}.pdb"
    try:
        write(str(cache_path), atoms)
    except Exception:
        pass

    return atoms


def _wipe_stage_outputs(stage_dir: Path):
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


def maybe_run_rdf(*, production_dir: Path, rdf_bins: int, rdf_rmax: Optional[float]):
    """Run rdf_analysis.py on the production trajectory if available. Optional, non-fatal."""
    traj_path = production_dir / lc.PROD_TRAJ_PDB
    if not traj_path.exists():
        print(f"  ⚠️ RDF skipped: production trajectory not found: {traj_path}")
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
# One-temperature workflow
# =============================================================================

def run_single_temperature(
    *,
    pmc_id: str,
    temp_K: float,
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
    resume_policy: str,
    charge: float,
    spin: float,
    external_field: Tuple[float, float, float],
):
    temp_dir_name = _format_temp_dir(temp_K)

    min_dir = results_root / "01_minimisation"
    eq_dir = results_root / "02_nvt_equilibration" / temp_dir_name
    prod_dir = results_root / "03_nvt_production" / temp_dir_name

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
    print_stage_header(f"{pmc_id} | Preparing starting structure (Polar)")
    starting_atoms = load_or_build_supercell(pmc_id, supercell_size, results_root)
    print(f"  🧱 Supercell atoms: {len(starting_atoms)}")
    print(f"  📦 Cell volume: {starting_atoms.get_volume():.3f} Å³")
    print(f"  ⚡ Polar context: charge={charge:g} spin={spin:g} field={external_field}")

    # -------------------------------------------------------------------------
    # 1) Minimisation
    # -------------------------------------------------------------------------
    if skip_minimisation:
        print_stage_header(f"{pmc_id} | Minimisation skipped")
        min_restart = min_dir / "minimisation.restart"
        min_last = min_dir / lc.LAST_FRAME_PDB
        if not min_restart.exists():
            raise FileNotFoundError(
                f"--skip-minimisation given but no existing restart at {min_restart}"
            )
        print(f"  ↪ Using existing minimisation restart: {min_restart}")
        min_result = {"restart_path": min_restart}
    else:
        print_stage_header(f"{pmc_id} | Stage 1/3: Minimisation (Polar)")
        min_result = lcp.run_minimisation_polar_stage(
            atoms=starting_atoms,
            stage_dir=min_dir,
            model_path=model,
            charge=charge,
            spin=spin,
            external_field=external_field,
            lammps_bin=lammps_bin,
            timestep_fs=timestep_fs,
            save_pdb=save_pdb,
        )

    # -------------------------------------------------------------------------
    # 2) NVT equilibration
    # -------------------------------------------------------------------------
    eq_steps = _steps_from_ps(eq_ps, timestep_fs)
    print_stage_header(
        f"{pmc_id} | Stage 2/3: NVT Equilibration (Polar) @ {temp_K:g} K "
        f"({eq_ps:g} ps = {eq_steps} steps)"
    )
    eq_result = lcp.run_nvt_polar_stage(
        stage_dir=eq_dir,
        model_path=model,
        temp_K=temp_K,
        nsteps=eq_steps,
        stage_label="NVT Equilibration",
        init_velocities=True,
        traj_name=lc.TRAJ_PDB,
        view_log_name=lc.EQ_VIEW_LOG,
        charge=charge,
        spin=spin,
        external_field=external_field,
        timestep_fs=timestep_fs,
        lammps_bin=lammps_bin,
        read_restart_path=min_result["restart_path"],
        save_pdb=save_pdb,
        restart_every_steps=restart_every_steps,
        resume_mode=("overwrite" if resume_policy == "overwrite" else "reuse"),
    )

    # -------------------------------------------------------------------------
    # 3) NVT production
    # -------------------------------------------------------------------------
    prod_steps = _steps_from_ps(prod_ps, timestep_fs)
    print_stage_header(
        f"{pmc_id} | Stage 3/3: NVT Production (Polar) @ {temp_K:g} K "
        f"({prod_ps:g} ps = {prod_steps} steps)"
    )
    prod_result = lcp.run_nvt_polar_stage(
        stage_dir=prod_dir,
        model_path=model,
        temp_K=temp_K,
        nsteps=prod_steps,
        stage_label="NVT Production",
        init_velocities=False,
        traj_name=lc.PROD_TRAJ_PDB,
        view_log_name=lc.PROD_VIEW_LOG,
        charge=charge,
        spin=spin,
        external_field=external_field,
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
        print_stage_header(f"{pmc_id} | RDF analysis @ {temp_K:g} K")
        maybe_run_rdf(production_dir=prod_dir, rdf_bins=rdf_bins, rdf_rmax=rdf_rmax)

    print_stage_header(f"{pmc_id} | Finished {temp_K:g} K (Polar)")
    print(f"  Final production structure volume: {prod_result['final_volume_A3']:.3f} Å³")
    print(f"  Production trajectory: {prod_result['traj_path']}")


# =============================================================================
# CLI
# =============================================================================

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run NVT MD using LAMMPS + PolarMACE (skaiser29 dev-fork build) for a PMC crystal."
    )

    p.add_argument("--pmc", required=True, help="PMC ID, e.g. PMC-001")
    p.add_argument("--temps", required=True, nargs="+", type=float,
                    help="Temperature(s) in K, e.g. --temps 300 350 400")
    p.add_argument("--model", choices=["small", "medium", "large"], default="medium",
                    help="PolarMACE variant (default: medium)")
    p.add_argument("--model-path", default=None,
                    help="Explicit path to a Polar .model/.pt checkpoint, overrides --model alias lookup")
    p.add_argument("--supercell", type=int, default=2, help="Supercell size N for NxNxN (default: 2)")
    p.add_argument("--outdir", type=str, default=None,
                    help="Root directory for results as <outdir>/<PMC_ID>/<model_tag>/NVT_results "
                         "(default: current working directory)")

    # PolarMACE runtime context — carried over from run_nvt_polar.py
    p.add_argument("--charge", type=float, default=0.0, help="Total system charge (PolarMACE context)")
    p.add_argument("--spin", type=float, default=1.0, help="Total system spin multiplicity (PolarMACE context)")
    p.add_argument("--external-field", type=float, nargs=3, default=[0.0, 0.0, 0.0],
                    metavar=("EX", "EY", "EZ"), help="External electric field (PolarMACE context)")

    # MD durations
    p.add_argument("--eq-ps", type=float, default=10.0, help="NVT equilibration duration in ps (default: 10)")
    p.add_argument("--prod-ps", type=float, default=1000.0, help="NVT production duration in ps (default: 1000)")
    p.add_argument("--timestep-fs", type=float, default=0.5, help="LAMMPS timestep in fs (default: 0.5)")

    # Execution
    p.add_argument("--lammps-bin", default=None,
                    help="Path to your skaiser29-fork lmp executable. If omitted, uses "
                         "LAMMPS_BIN / LAMMPS_INSTALL / PATH — make sure that resolves to the "
                         "Polar-capable build, not the mainline one.")

    # Workflow switches
    p.add_argument("--skip-minimisation", action="store_true",
                    help="Skip minimisation and start from an existing minimisation.restart")
    p.add_argument("--run-rdf", action="store_true",
                    help="Run RDF analysis after production if rdf_analysis.py is callable.")
    p.add_argument("--save-pdb", action="store_true",
                    help="Also write trajectory.pdb / last-frame-of-trajectory.pdb for every stage.")
    p.add_argument("--restart-every", type=int, default=100,
                    help="Steps between intermediate LAMMPS restart checkpoints (default: 100)")
    p.add_argument("--resume-policy", choices=["reuse", "overwrite"], default="reuse",
                    help="'reuse' keeps/extends existing completed stages; "
                         "'overwrite' reruns equilibration/production from scratch")

    # RDF knobs
    p.add_argument("--rdf-bins", type=int, default=300, help="RDF bins (default: 300)")
    p.add_argument("--rdf-rmax", type=float, default=None, help="Optional RDF rmax in Å")

    return p


def main():
    args = build_parser().parse_args()

    pmc_id = args.pmc
    temps: List[float] = list(args.temps)
    external_field = tuple(args.external_field)

    outdir_base = Path(args.outdir).resolve() if args.outdir else Path.cwd()

    model_arg = str(args.model_path) if args.model_path else str(args.model)
    model_tag = "polar-" + (Path(model_arg).stem if any(sep in model_arg for sep in ("/", "\\")) else model_arg)
    model_tag = model_tag.replace(" ", "_")

    results_root = outdir_base / pmc_id / model_tag / "NVT_results"
    results_root.mkdir(parents=True, exist_ok=True)

    print()
    print("══════════════════════════════════════════════════════════════════════════════")
    print("  LAMMPS + PolarMACE NVT workflow (skaiser29 dev-fork build)")
    print("══════════════════════════════════════════════════════════════════════════════")
    print(f"  PMC ID        : {pmc_id}")
    print(f"  Temperatures  : {temps}")
    print(f"  Model         : {model_arg}")
    print(f"  Charge/Spin   : {args.charge} / {args.spin}")
    print(f"  Ext. field    : {external_field}")
    print(f"  Supercell     : {args.supercell}x{args.supercell}x{args.supercell}")
    print(f"  Eq duration   : {args.eq_ps} ps")
    print(f"  Prod duration : {args.prod_ps} ps")
    print(f"  Timestep      : {args.timestep_fs} fs")
    print(f"  Restart every : {args.restart_every} steps")
    print(f"  Resume policy : {args.resume_policy}")
    print(f"  Save PDB      : {args.save_pdb}")
    print(f"  Results dir   : {results_root}")
    print()
    print("  ⚠️  Polar pair_style/context wiring in lammps_common_polar.py is a")
    print("      PLACEHOLDER until confirmed against a real working .in file.")
    print()

    t0 = time.time()

    for temp in temps:
        run_single_temperature(
            pmc_id=pmc_id,
            temp_K=temp,
            results_root=results_root,
            model=(args.model_path or args.model),
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
            charge=args.charge,
            spin=args.spin,
            external_field=external_field,
        )

    elapsed = time.time() - t0
    print()
    print("══════════════════════════════════════════════════════════════════════════════")
    print(f"  All requested temperatures finished in {elapsed/60:.1f} min")
    print("══════════════════════════════════════════════════════════════════════════════")


if __name__ == "__main__":
    main()