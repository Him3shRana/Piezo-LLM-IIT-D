#!/usr/bin/env python3
"""
run_nvt_polar.py
=================

Standalone NVT MD workflow using MACE-Polar (PolarMACE) foundation models,
run directly through ASE (no LAMMPS involved).

Why ASE and not LAMMPS: PolarMACE requires per-structure electrostatic
context (charge / spin / external_field) that the LAMMPS ML-IAP interface
has no mechanism to supply, and currently crashes with a
KeyError('fermi level') when attempted (see ACEsuit/mace issue #1409).
ASE's calculator interface handles this correctly.

Only two PolarMACE checkpoints are locally confirmed so far ("medium", which
you have, at ~/.cache/mace/MACEPOLAR1Mmodel). A "small" variant (polar-1-s)
and "large" variant (polar-1-l) also exist upstream but aren't confirmed on
disk yet — see LOCAL_MODEL_PATHS below to point at them once downloaded.

Note: PolarMACE requires building MACE from source (main branch) plus the
separate `graph_electrostatics` package — not the PyPI mace-torch release.
This script auto-detects if it's not running in an env with that build and
re-launches itself under a conda env named "mace-polar-env" (override the
name with MACE_POLAR_CONDA_ENV=..., or skip entirely with
MACE_POLAR_SKIP_ENV_SWITCH=1). So you can just run it from any env —
no need to `conda activate` first.

Workflow per temperature:
    1) Minimisation            -> 01_minimisation/
    2) NVT equilibration       -> 02_nvt_equilibration/<T>K/
    3) NVT production          -> 03_nvt_production/<T>K/
    4) RDF comparison plot     -> 03_nvt_production/<T>K/rdf/
       Three curves per element pair, on one graph:
         - "cif"       : the pristine input structure (supercell-replicated,
                          never touched by minimisation or MD)
         - "minimised"  : the structure after energy minimisation
         - "simulated"  : averaged over the NVT production trajectory

Output layout (mirrors the LAMMPS pipeline's naming as closely as possible):

    <outdir>/<PMC_ID>/<model_tag>/NVT_results/
        01_minimisation/
            minimised_structure.xyz
            minimisation.csv
            minimisation.log
            state.json
        02_nvt_equilibration/<T>K/
            equilibration.traj
            equilibration.csv
            equilibration_temp.png
            state.json
        03_nvt_production/<T>K/
            production.traj
            production.csv
            production_temp.png
            state.json
            rdf/
                rdf_<EL1>-<EL2>.png
                rdf_<EL1>-<EL2>.csv

Usage:
    python3 run_nvt_polar.py --pmc PMC-001 --cif data/PMC-001/PMC-001.cif \
        --model medium --temps 300 --supercell 2

Requirements:
    pip install mace-torch ase numpy matplotlib
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple


# =============================================================================
# Auto-switch to the conda env that actually has PolarMACE installed
# =============================================================================
#
# PolarMACE requires MACE built from source (main branch) + the separate
# graph_electrostatics package — not the plain pip mace-torch release. If
# you're not already in that env, this re-launches the script under it
# automatically instead of failing with ImportError.
#
# Override the env name with: export MACE_POLAR_CONDA_ENV=your-env-name
# Skip this entirely with:    export MACE_POLAR_SKIP_ENV_SWITCH=1

def _mace_polar_importable() -> bool:
    try:
        import mace.calculators as _mc
        return hasattr(_mc, "mace_polar")
    except ImportError:
        return False


def _find_conda_env_python(env_name: str) -> Optional[Path]:
    conda_exe = os.environ.get("CONDA_EXE") or shutil.which("conda")
    if not conda_exe:
        return None
    try:
        result = subprocess.run([conda_exe, "env", "list", "--json"],
                                 capture_output=True, text=True, check=True, timeout=30)
        envs = json.loads(result.stdout).get("envs", [])
    except Exception:
        return None
    for env_path in envs:
        if Path(env_path).name == env_name:
            for candidate in ("python3", "python"):
                py = Path(env_path) / "bin" / candidate
                if py.exists():
                    return py
    return None


def _find_venv_python(env_name: str) -> Optional[Path]:
    """Look for a plain venv/virtualenv (not conda-managed) named env_name
    in common locations. An explicit MACE_POLAR_ENV_PATH always wins."""
    explicit = os.environ.get("MACE_POLAR_ENV_PATH")
    candidate_dirs = []
    if explicit:
        candidate_dirs.append(Path(explicit))

    home = Path.home()
    candidate_dirs += [
        home / "home" / "software" / env_name,  # confirmed layout on this cluster
        home / "software" / env_name,
        home / ".venvs" / env_name,
        home / "venvs" / env_name,
        home / env_name,
    ]

    for d in candidate_dirs:
        for candidate in ("python3", "python"):
            py = d / "bin" / candidate
            if py.exists():
                return py
    return None


def _ensure_polar_env():
    if os.environ.get("MACE_POLAR_SKIP_ENV_SWITCH"):
        return
    if _mace_polar_importable():
        return

    env_name = os.environ.get("MACE_POLAR_CONDA_ENV", "mace-polar-env")
    print(f"  🔁 'mace_polar' not importable in the current environment "
          f"({sys.executable}); looking for env '{env_name}' ...")

    python_bin = _find_venv_python(env_name) or _find_conda_env_python(env_name)
    if python_bin is None:
        sys.exit(
            f"❌ Could not import mace_polar here, and couldn't auto-locate an env "
            f"named '{env_name}' (checked plain venv locations and conda envs).\n"
            f"   Fix by either:\n"
            f"     conda activate {env_name}   (if it's a conda env; then re-run), or\n"
            f"     source /path/to/{env_name}/bin/activate   (if it's a venv; then re-run), or\n"
            f"     export MACE_POLAR_ENV_PATH=/exact/path/to/{env_name}   (points straight at it), or\n"
            f"     export MACE_POLAR_CONDA_ENV=<your-actual-env-name>   (if it's named differently)"
        )

    print(f"  🔁 Re-launching under {python_bin} ...\n")
    clean_env = dict(os.environ)
    clean_env.pop("PYTHONPATH", None)
    clean_env.pop("PYTHONHOME", None)
    os.execve(str(python_bin), [str(python_bin), str(Path(__file__).resolve())] + sys.argv[1:], clean_env)


_ensure_polar_env()


# =============================================================================
# Main imports (only reached once we're in an env that has mace_polar)
# =============================================================================

import numpy as np

from ase import Atoms
from ase.data import atomic_numbers
from ase.io import read, write
from ase.io.trajectory import Trajectory
from ase.geometry.rdf import get_rdf
from ase.md.velocitydistribution import MaxwellBoltzmannDistribution
from ase.md.langevin import Langevin
from ase.optimize import FIRE
from ase import units

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# =============================================================================
# PolarMACE model resolution
# =============================================================================

# Official upstream aliases (mace.calculators.mace_polar will auto-download
# to ~/.cache/mace if a local path isn't found/given).
POLAR_ALIASES = {
    "small": "polar-1-s",
    "medium": "polar-1-m",
    "large": "polar-1-l",
}

# Fill in / adjust these if your local checkpoint filenames differ.
# --model-path on the command line always overrides this.
# Defaults to the current directory (wherever you run this script from,
# e.g. ~/himesh_work/MACE-polar/) — override per-run with --models-dir.
# Download checkpoints there with:
#   MACE-POLAR-1-S.model : https://github.com/ACEsuit/mace-foundations/releases/download/mace_polar_1/MACE-POLAR-1-S.model
#   MACE-POLAR-1-M.model : https://github.com/ACEsuit/mace-foundations/releases/download/mace_polar_1/MACE-POLAR-1-M.model
#   MACE-POLAR-1-L.model : https://github.com/ACEsuit/mace-foundations/releases/download/mace_polar_1/MACE-POLAR-1-L.model
DEFAULT_MODELS_DIR = Path(".")

# Fallback data directory. Used two ways:
#   1) As the default value of --data-dir if you don't pass one at all.
#   2) As a last-resort fallback in find_cif() if whatever --data-dir *was*
#      given (explicitly or via its own default) doesn't contain the PMC
#      folder — e.g. a relative "data" that doesn't exist from wherever you
#      happened to launch the script from.
# Override with MACE_POLAR_DEFAULT_DATA_DIR=... if this ever moves.
DEFAULT_DATA_DIR = Path(os.environ.get(
    "MACE_POLAR_DEFAULT_DATA_DIR",
    str(Path.home() / "himesh_work" / "data"),
)).expanduser()


def resolve_model(model_choice: str, model_path_override: Optional[str],
                   models_dir: Path) -> str:
    if model_path_override:
        p = Path(model_path_override)
        if not p.exists():
            sys.exit(f"❌ --model-path given but not found: {p}")
        return str(p)

    filename = {"small": "MACE-POLAR-1-S.model",
                "medium": "MACE-POLAR-1-M.model",
                "large": "MACE-POLAR-1-L.model"}[model_choice]
    local = models_dir / filename
    if local.exists():
        return str(local)

    alias = POLAR_ALIASES[model_choice]
    print(f"  ⚠️ No local checkpoint at {local}; "
          f"falling back to alias '{alias}' (mace_polar will try to locate/download it).")
    return alias


def setup_polar_calculator(model_choice: str, model_path_override: Optional[str],
                            models_dir: Path, device: str, dtype: str):
    from mace.calculators import mace_polar

    model_arg = resolve_model(model_choice, model_path_override, models_dir)
    print(f"\nLoading MACE-Polar ({model_choice}) from '{model_arg}' on {device} ...")
    try:
        calc = mace_polar(model=model_arg, device=device, default_dtype=dtype)
    except Exception as e:
        if device == "cuda":
            print(f"  ⚠️ CUDA load failed ({e}); retrying on CPU ...")
            calc = mace_polar(model=model_arg, device="cpu", default_dtype=dtype)
        else:
            raise
    print("  ✅ MACE-Polar calculator ready")
    return calc


def attach_polar_context(atoms: Atoms, charge: float, spin: float,
                          external_field: Tuple[float, float, float]):
    """PolarMACE reads these from atoms.info at every energy/force call."""
    atoms.info["charge"] = charge
    atoms.info["spin"] = spin
    atoms.info["external_field"] = list(external_field)


# =============================================================================
# Structure loading
# =============================================================================

def find_cif(pmc_id: str, data_dir: Path) -> Path:
    """Auto-locate the pristine unit-cell CIF for a PMC ID under data_dir/<PMC>/.
    Only matches plain .cif files — supercell files (containing '_supercell_')
    are excluded so we don't accidentally pick up a pre-built simulation cell.

    If <data_dir>/<PMC> doesn't exist, falls back to DEFAULT_DATA_DIR/<PMC>
    (e.g. ~/himesh_work/data) before giving up, so a missing/wrong --data-dir
    doesn't hard-fail as long as the data lives in the usual place."""
    pmc_dir = data_dir / pmc_id
    if not pmc_dir.exists():
        fallback_dir = DEFAULT_DATA_DIR / pmc_id
        if fallback_dir.exists() and fallback_dir.resolve() != pmc_dir.resolve():
            print(f"  ⚠️ {pmc_dir} not found; falling back to default data dir "
                  f"{DEFAULT_DATA_DIR} ...")
            pmc_dir = fallback_dir
        else:
            sys.exit(f"❌ No such folder: {pmc_dir}\n"
                      f"   Also checked fallback: {fallback_dir}\n"
                      f"   Pass --cif /path/to/file.cif explicitly if your CIF lives elsewhere.")

    candidates = [p for p in sorted(pmc_dir.glob("*.cif")) if "_supercell_" not in p.name]
    if len(candidates) == 1:
        print(f"  📄 Auto-detected CIF: {candidates[0]}")
        return candidates[0]
    if len(candidates) == 0:
        sys.exit(f"❌ No .cif file found in {pmc_dir}\n"
                  f"   Pass --cif /path/to/file.cif explicitly.")
    sys.exit(f"❌ Multiple .cif files found in {pmc_dir}: {[c.name for c in candidates]}\n"
              f"   Pass --cif /path/to/the-right-one.cif explicitly.")


def load_supercell(cif_path: Path, supercell: int) -> Atoms:
    atoms = read(str(cif_path))
    atoms.set_pbc(True)
    if supercell != 1:
        atoms = atoms.repeat((supercell, supercell, supercell))
    return atoms


# =============================================================================
# Stage state helper
# =============================================================================

def save_state(state_path: Path, state: dict):
    tmp = state_path.with_suffix(state_path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    tmp.replace(state_path)


def load_state(state_path: Path) -> Optional[dict]:
    if not state_path.exists():
        return None
    try:
        with open(state_path) as f:
            return json.load(f)
    except Exception:
        return None


def load_csv_rows(csv_path: Path) -> list:
    """Read back previously-written CSV rows (numeric fields converted from
    str), used to continue a CSV across a resume instead of clobbering it."""
    if not csv_path.exists():
        return []
    rows = []
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            converted = {}
            for k, v in row.items():
                if k == "step":
                    converted[k] = int(v)
                else:
                    try:
                        converted[k] = float(v)
                    except (TypeError, ValueError):
                        converted[k] = v
            rows.append(converted)
    return rows


def load_last_traj_atoms(traj_path: Path) -> Optional[Atoms]:
    """Load the last frame (positions + momenta + cell) written to an ASE
    Trajectory, used as the checkpoint state for resuming MD. Returns None
    if the file is missing/empty/unreadable."""
    if not traj_path.exists():
        return None
    try:
        traj = Trajectory(str(traj_path), "r")
        if len(traj) == 0:
            traj.close()
            return None
        last_atoms = traj[-1]
        traj.close()
        return last_atoms
    except Exception as e:
        print(f"  ⚠️ Could not read checkpoint frame from {traj_path}: {e}")
        return None


def console_print_interval(total_steps: int, snap_to: int = 1,
                            target_lines: int = 25) -> int:
    """Pick a step interval for *console* progress printing so we get
    roughly `target_lines` lines total, regardless of how many steps the
    run has (2000 steps or 2,000,000 steps both print a manageable amount).
    Rounded to a 'nice' 1/2/5 x 10^n number, then rounded up to the nearest
    multiple of `snap_to` (e.g. the CSV log_interval) so console prints
    always land on a step that's actually being logged."""
    if total_steps <= 0:
        return max(snap_to, 1)
    raw = max(total_steps // target_lines, 1)
    magnitude = 10 ** (len(str(raw)) - 1)
    nice = raw
    for candidate_mult in (1, 2, 5, 10):
        candidate = candidate_mult * magnitude
        if candidate >= raw:
            nice = candidate
            break
    else:
        nice = 10 * magnitude
    # Round up to the nearest multiple of snap_to
    snap_to = max(snap_to, 1)
    return max(((nice + snap_to - 1) // snap_to) * snap_to, snap_to)


def sync_to_remote(local_path: Path, remote_target: str,
                    ssh_key: Optional[str] = None, timeout_s: int = 600) -> bool:
    """Push local_path to remote_target (an rsync destination, e.g.
    'user@host:/path/to/dest') over rsync+ssh. Never raises — a sync
    failure (unreachable host, no rsync installed, etc.) just prints a
    warning and lets the simulation keep going; it does not abort the run.
    Safe to call repeatedly: rsync only transfers what changed."""
    rsync_bin = shutil.which("rsync")
    if not rsync_bin:
        print("  ⚠️ 'rsync' not found on this machine — skipping sync. "
              "(Install rsync, or copy results manually afterwards.)")
        return False

    ssh_cmd = "ssh -o ConnectTimeout=10 -o BatchMode=yes"
    if ssh_key:
        ssh_cmd += f" -i {ssh_key}"

    cmd = [rsync_bin, "-avz", "--partial", "-e", ssh_cmd, str(local_path), remote_target]
    print(f"  🔄 Syncing {local_path} -> {remote_target} ...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        print(f"  ⚠️ Sync timed out after {timeout_s}s — continuing without blocking the run.")
        return False
    except Exception as e:
        print(f"  ⚠️ Sync error: {e} — continuing without blocking the run.")
        return False

    if result.returncode == 0:
        print("  ✅ Sync complete.")
        return True

    print(f"  ⚠️ Sync failed (rsync exit code {result.returncode}). "
          f"Last output: {result.stderr.strip()[-500:] or result.stdout.strip()[-500:]}\n"
          f"     (BatchMode=yes means this requires passwordless SSH key auth to the "
          f"target — if that's not set up yet, sync will keep failing silently like "
          f"this on every attempt without blocking the run.)")
    return False


# =============================================================================
# Stage 1: minimisation
# =============================================================================

def run_minimisation(atoms: Atoms, calc, out_dir: Path, fmax: float, max_steps: int,
                      charge: float, spin: float, field: Tuple[float, float, float]) -> Atoms:
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / "state.json"
    xyz_path = out_dir / "minimised_structure.xyz"
    csv_path = out_dir / "minimisation.csv"

    prev_state = load_state(state_path)
    if prev_state and prev_state.get("status") == "completed" and xyz_path.exists():
        fmax_prev = prev_state.get("final_fmax_eV_per_A")
        fmax_str = f"{fmax_prev:.4f}" if isinstance(fmax_prev, (int, float)) else "?"
        print(f"    ⏩ Minimisation already completed "
              f"({prev_state.get('completed_steps', '?')} steps, final fmax={fmax_str} eV/Å) "
              f"— loading {xyz_path.name} and skipping.")
        resumed_atoms = read(str(xyz_path))
        resumed_atoms.set_pbc(True)
        resumed_atoms.calc = calc
        attach_polar_context(resumed_atoms, charge, spin, field)
        return resumed_atoms

    # NOTE: minimisation has no mid-run resume. FIRE's internal optimizer
    # state (velocities/adaptive timestep) isn't checkpointed, so if this
    # stage gets killed partway through, the next run just restarts
    # minimisation from step 0 (cheap relative to the NVT stages).
    atoms = atoms.copy()
    atoms.calc = calc
    attach_polar_context(atoms, charge, spin, field)

    rows = []
    t_start = time.time()
    print_interval = console_print_interval(max_steps, snap_to=1)

    def log_step():
        e = atoms.get_potential_energy()
        f = atoms.get_forces()
        fmax_now = float(np.sqrt((f ** 2).sum(axis=1).max()))
        step = len(rows)
        rows.append({"step": step, "energy_eV": e, "fmax_eV_per_A": fmax_now})
        if step % print_interval == 0:
            elapsed_now = time.time() - t_start
            print(f"    [Minimisation] step {step:>5d}/{max_steps} | "
                  f"E={e:12.4f} eV | fmax={fmax_now:8.4f} eV/Å | "
                  f"{elapsed_now:6.1f}s elapsed", flush=True)

    opt = FIRE(atoms, logfile=str(out_dir / "minimisation.log"))
    opt.attach(log_step, interval=1)

    t0 = time.time()
    opt.run(fmax=fmax, steps=max_steps)
    elapsed = time.time() - t0

    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["step", "energy_eV", "fmax_eV_per_A"])
        w.writeheader()
        w.writerows(rows)

    write(str(xyz_path), atoms)

    save_state(state_path, {
        "stage": "Minimisation",
        "status": "completed",
        "elapsed_seconds": elapsed,
        "completed_steps": len(rows),
        "final_energy_eV": rows[-1]["energy_eV"] if rows else None,
        "final_fmax_eV_per_A": rows[-1]["fmax_eV_per_A"] if rows else None,
        "structure_file": xyz_path.name,
        "csv_file": csv_path.name,
    })

    print(f"    ✅ Minimisation done: {elapsed:.0f}s | {len(rows)} steps | "
          f"final fmax={rows[-1]['fmax_eV_per_A']:.4f} eV/Å" if rows else "no steps")

    return atoms


# =============================================================================
# Stage 2 & 3: NVT (equilibration / production, shared implementation)
# =============================================================================

def run_nvt_stage(atoms: Atoms, calc, out_dir: Path, temp_K: float, nsteps: int,
                   timestep_fs: float, friction: float, log_interval: int,
                   traj_interval: int, init_velocities: bool, stage_label: str,
                   traj_name: str, charge: float, spin: float,
                   field: Tuple[float, float, float]) -> Atoms:
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / "state.json"
    traj_path = out_dir / traj_name
    csv_path = out_dir / f"{stage_label.lower().replace(' ', '_')}.csv"

    prev_state = load_state(state_path)

    # --- Case 1: stage already fully completed -> skip entirely ---------
    if prev_state and prev_state.get("status") == "completed":
        final_atoms = load_last_traj_atoms(traj_path)
        if final_atoms is not None:
            prev_T = prev_state.get("final_temperature_K")
            prev_T_str = f"{prev_T:.1f}" if isinstance(prev_T, (int, float)) else "?"
            print(f"    ⏩ {stage_label} already completed "
                  f"({prev_state.get('completed_steps', '?')}/{nsteps} steps, "
                  f"final T={prev_T_str} K) "
                  f"— loading {traj_path.name} and skipping.")
            final_atoms.calc = calc
            attach_polar_context(final_atoms, charge, spin, field)
            return final_atoms
        print(f"    ⚠️ {stage_label} state.json says completed but {traj_path.name} "
              f"is missing/unreadable — re-running the stage.")

    # --- Case 2: stage was interrupted partway through -> resume --------
    resume_step = 0
    rows: list = []
    resuming = False
    if prev_state and prev_state.get("status") == "running":
        resume_step = int(prev_state.get("completed_steps", 0) or 0)
        checkpoint_atoms = load_last_traj_atoms(traj_path)
        if checkpoint_atoms is not None and 0 < resume_step < nsteps:
            print(f"    🔄 Resuming {stage_label} from step {resume_step}/{nsteps} "
                  f"(checkpoint found in {traj_path.name}) ...")
            atoms = checkpoint_atoms
            rows = load_csv_rows(csv_path)
            resuming = True
        else:
            print(f"    ⚠️ {stage_label} had a partial state.json but no usable "
                  f"checkpoint frame — restarting the stage from step 0.")

    if not resuming:
        atoms = atoms.copy()
        if init_velocities:
            MaxwellBoltzmannDistribution(atoms, temperature_K=temp_K)

    atoms.calc = calc
    attach_polar_context(atoms, charge, spin, field)

    dyn = Langevin(atoms, timestep=timestep_fs * units.fs,
                    temperature_K=temp_K, friction=friction)
    if resuming:
        dyn.nsteps = resume_step  # realign the step counter so intervals stay in sync

    traj = Trajectory(str(traj_path), "a" if resuming else "w", atoms)
    dyn.attach(traj.write, interval=traj_interval)

    t_start = time.time()
    print_interval = console_print_interval(nsteps, snap_to=log_interval)

    def flush_checkpoint(status: str):
        with open(csv_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["step", "time_ps", "temperature_K",
                                               "potential_energy_eV", "kinetic_energy_eV",
                                               "total_energy_eV", "volume_A3"])
            w.writeheader()
            w.writerows(rows)
        save_state(state_path, {
            "stage": stage_label,
            "temperature_K": temp_K,
            "status": status,
            "completed_steps": dyn.get_number_of_steps(),
            "target_steps": nsteps,
            "final_temperature_K": rows[-1]["temperature_K"] if rows else None,
            "final_volume_A3": rows[-1]["volume_A3"] if rows else None,
            "trajectory_file": traj_path.name,
            "csv_file": csv_path.name,
        })

    def log_step():
        step = dyn.get_number_of_steps()
        e_pot = atoms.get_potential_energy()
        e_kin = atoms.get_kinetic_energy()
        temp_now = atoms.get_temperature()
        vol = atoms.get_volume()
        rows.append({
            "step": step,
            "time_ps": step * timestep_fs / 1000.0,
            "temperature_K": temp_now,
            "potential_energy_eV": e_pot,
            "kinetic_energy_eV": e_kin,
            "total_energy_eV": e_pot + e_kin,
            "volume_A3": vol,
        })

        if step % print_interval == 0:
            elapsed_now = time.time() - t_start
            pct = 100.0 * step / nsteps if nsteps else 100.0
            steps_this_session = max(step - resume_step, 0)
            rate = steps_this_session / elapsed_now if elapsed_now > 0 else 0.0
            eta_s = (nsteps - step) / rate if rate > 0 else float("nan")
            print(f"    [{stage_label}] step {step:>7d}/{nsteps} ({pct:5.1f}%) | "
                  f"t={step * timestep_fs / 1000.0:8.3f} ps | T={temp_now:7.2f} K | "
                  f"E_pot={e_pot:12.4f} eV | E_tot={e_pot + e_kin:12.4f} eV | "
                  f"{elapsed_now:6.1f}s elapsed | ETA {eta_s:6.1f}s", flush=True)

    dyn.attach(log_step, interval=log_interval)
    # Checkpoint (state.json + CSV) every time a trajectory frame is written,
    # since that frame is what a restart would resume from.
    dyn.attach(lambda: flush_checkpoint("running"), interval=traj_interval)

    t0 = time.time()
    remaining_steps = max(nsteps - resume_step, 0)
    dyn.run(remaining_steps)
    elapsed = time.time() - t0

    # Guarantee the exact final state is on disk, even if nsteps isn't an
    # exact multiple of traj_interval, so a future skip/resume is accurate.
    traj.write()
    traj.close()

    final_T = rows[-1]["temperature_K"] if rows else None
    final_V = rows[-1]["volume_A3"] if rows else atoms.get_volume()

    plot_path = out_dir / f"{stage_label.lower().replace(' ', '_')}_temp.png"
    if rows:
        times = [r["time_ps"] for r in rows]
        temps = [r["temperature_K"] for r in rows]
        plt.figure(figsize=(6, 4))
        plt.plot(times, temps, lw=1)
        plt.axhline(temp_K, color="gray", ls="--", lw=1, label=f"target {temp_K:g} K")
        plt.xlabel("Time (ps)")
        plt.ylabel("Temperature (K)")
        plt.title(f"{stage_label} — Temperature vs Time ({temp_K:g} K)")
        plt.legend()
        plt.tight_layout()
        plt.savefig(plot_path, dpi=150)
        plt.close()

    flush_checkpoint("completed")

    print(f"    ✅ {stage_label} done: {elapsed:.0f}s | "
          f"final T={final_T if final_T is not None else float('nan'):.1f} K | "
          f"final V={final_V:.1f} Å³")

    return atoms


# =============================================================================
# RDF comparison (3 curves: cif / minimised / simulated)
# =============================================================================

def average_rdf_over_trajectory(traj_path: Path, rmax: float, nbins: int,
                                 elements: Tuple[int, int],
                                 skip: int, stride: int) -> np.ndarray:
    traj = Trajectory(str(traj_path), "r")
    frames = list(traj)[skip::stride]
    if not frames:
        raise RuntimeError(f"No frames found in {traj_path} after skip/stride")

    total = None
    for atoms in frames:
        rdf, dists = get_rdf(atoms, rmax, nbins, elements=elements)
        total = rdf if total is None else total + rdf
    return total / len(frames), dists


def compute_single_rdf(atoms: Atoms, rmax: float, nbins: int,
                        elements: Tuple[int, int]) -> Tuple[np.ndarray, np.ndarray]:
    rdf, dists = get_rdf(atoms, rmax, nbins, elements=elements)
    return rdf, dists


def plot_rdf_comparison(out_dir: Path, symbol_pair: Tuple[str, str], dists: np.ndarray,
                         cif_rdf: np.ndarray, min_rdf: np.ndarray, sim_rdf: np.ndarray,
                         temp_K: float):
    out_dir.mkdir(parents=True, exist_ok=True)
    el1, el2 = symbol_pair

    plt.figure(figsize=(6, 4))
    plt.plot(dists, cif_rdf, label="CIF (pristine)", lw=1.5, ls="--")
    plt.plot(dists, min_rdf, label="Minimised", lw=1.5, ls=":")
    plt.plot(dists, sim_rdf, label=f"Simulated ({temp_K:g} K, avg)", lw=1.5)
    plt.xlabel("r (Å)")
    plt.ylabel("g(r)")
    plt.title(f"RDF: {el1}–{el2}")
    plt.legend()
    plt.tight_layout()
    png_path = out_dir / f"rdf_{el1}-{el2}.png"
    plt.savefig(png_path, dpi=150)
    plt.close()

    csv_path = out_dir / f"rdf_{el1}-{el2}.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["r_A", "g_cif", "g_minimised", "g_simulated"])
        for r, gc, gm, gs in zip(dists, cif_rdf, min_rdf, sim_rdf):
            w.writerow([r, gc, gm, gs])


def run_rdf_comparison(cif_atoms: Atoms, min_atoms: Atoms, prod_traj_path: Path,
                        out_dir: Path, temp_K: float, rmax: float, nbins: int,
                        skip: int, stride: int):
    elements_present = sorted(set(cif_atoms.get_chemical_symbols()))
    pairs = list(itertools.combinations_with_replacement(elements_present, 2))

    print(f"    📊 RDF for {len(pairs)} element pairs: {pairs}")

    done, todo = [], []
    for el1, el2 in pairs:
        png_path = out_dir / f"rdf_{el1}-{el2}.png"
        csv_path = out_dir / f"rdf_{el1}-{el2}.csv"
        if png_path.exists() and csv_path.exists():
            done.append((el1, el2))
        else:
            todo.append((el1, el2))

    if done and not todo:
        print(f"    ⏩ All {len(done)} RDF pairs already computed in {out_dir} — skipping.")
        return
    if done:
        print(f"    ⏩ Skipping {len(done)} already-computed pair(s): {done}")

    for el1, el2 in todo:
        z_pair = (atomic_numbers[el1], atomic_numbers[el2])

        cif_rdf, dists = compute_single_rdf(cif_atoms, rmax, nbins, z_pair)
        min_rdf, _ = compute_single_rdf(min_atoms, rmax, nbins, z_pair)
        sim_rdf, _ = average_rdf_over_trajectory(prod_traj_path, rmax, nbins, z_pair,
                                                  skip, stride)

        plot_rdf_comparison(out_dir, (el1, el2), dists, cif_rdf, min_rdf, sim_rdf, temp_K)
        print(f"    💾 RDF saved for {el1}-{el2}")

    print(f"    💾 RDF plots saved to {out_dir}")


# =============================================================================
# One-temperature workflow
# =============================================================================

def run_single_temperature(*, cif_atoms: Atoms, min_atoms_cache: dict, calc,
                            results_root: Path, temp_K: float, eq_steps: int,
                            prod_steps: int, timestep_fs: float, friction: float,
                            log_interval: int, traj_interval: int,
                            min_fmax: float, min_max_steps: int,
                            charge: float, spin: float, field: Tuple[float, float, float],
                            rdf_bins: int, rdf_rmax: Optional[float],
                            rdf_skip: int, rdf_stride: int,
                            sync_to: Optional[str] = None, sync_key: Optional[str] = None,
                            sync_after_temp: bool = False):
    temp_dir = f"{temp_K:g}K"
    min_dir = results_root / "01_minimisation"
    eq_dir = results_root / "02_nvt_equilibration" / temp_dir
    prod_dir = results_root / "03_nvt_production" / temp_dir

    print("\n" + "=" * 78)
    print(f"  Stage 1/3: Minimisation")
    print("=" * 78)
    if "atoms" not in min_atoms_cache:
        min_atoms_cache["atoms"] = run_minimisation(
            cif_atoms, calc, min_dir, min_fmax, min_max_steps, charge, spin, field
        )
    min_atoms = min_atoms_cache["atoms"]

    eq_ps = eq_steps * timestep_fs / 1000.0
    print("\n" + "=" * 78)
    print(f"  Stage 2/3: NVT Equilibration @ {temp_K:g} K ({eq_steps} steps = {eq_ps:g} ps)")
    print("=" * 78)
    eq_atoms = run_nvt_stage(
        min_atoms, calc, eq_dir, temp_K, eq_steps, timestep_fs, friction,
        log_interval, traj_interval, init_velocities=True,
        stage_label="NVT Equilibration", traj_name="equilibration.traj",
        charge=charge, spin=spin, field=field,
    )

    prod_ps = prod_steps * timestep_fs / 1000.0
    print("\n" + "=" * 78)
    print(f"  Stage 3/3: NVT Production @ {temp_K:g} K ({prod_steps} steps = {prod_ps:g} ps)")
    print("=" * 78)
    run_nvt_stage(
        eq_atoms, calc, prod_dir, temp_K, prod_steps, timestep_fs, friction,
        log_interval, traj_interval, init_velocities=False,
        stage_label="NVT Production", traj_name="production.traj",
        charge=charge, spin=spin, field=field,
    )

    print("\n" + "=" * 78)
    print(f"  RDF comparison @ {temp_K:g} K")
    print("=" * 78)
    rmax = rdf_rmax if rdf_rmax else min(cif_atoms.get_cell().lengths()) / 2.0 - 0.1
    run_rdf_comparison(
        cif_atoms, min_atoms, prod_dir / "production.traj",
        prod_dir / "rdf", temp_K, rmax, rdf_bins, rdf_skip, rdf_stride,
    )

    print(f"\n  Finished {temp_K:g} K")

    if sync_to and sync_after_temp:
        print("\n" + "=" * 78)
        print(f"  Syncing results after {temp_K:g} K")
        print("=" * 78)
        sync_to_remote(results_root, sync_to, sync_key)


# =============================================================================
# CLI
# =============================================================================

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run NVT MD using MACE-Polar (ASE-based) for a PMC crystal, "
                     "then produce 3-curve (CIF/minimised/simulated) RDF plots."
    )
    p.add_argument("--pmc", required=True, help="PMC ID, e.g. PMC-001")
    p.add_argument("--cif", default=None,
                    help="Path to the unit-cell CIF. If omitted, auto-detected from "
                         "<data-dir>/<PMC>/*.cif")
    p.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR),
                    help=f"Root folder to auto-search for the CIF "
                         f"(default: {DEFAULT_DATA_DIR}). If the PMC folder "
                         f"isn't found here, {DEFAULT_DATA_DIR} is also tried "
                         f"as a fallback.")
    p.add_argument("--supercell", type=int, default=2, help="Supercell size N for NxNxN (default: 2)")

    p.add_argument("--model", choices=["small", "medium", "large"], default="medium",
                    help="PolarMACE variant")
    p.add_argument("--model-path", default=None,
                    help="Explicit path to a .model checkpoint, overrides --models-dir lookup")
    p.add_argument("--models-dir", default=str(DEFAULT_MODELS_DIR),
                    help="Folder to look for MACE-POLAR-1-{S,M,L}.model in (default: current directory)")
    p.add_argument("--device", choices=["cuda", "cpu"], default="cuda")
    p.add_argument("--dtype", choices=["float32", "float64"], default="float64")

    p.add_argument("--charge", type=float, default=0.0, help="Total system charge (PolarMACE context)")
    p.add_argument("--spin", type=float, default=1.0, help="Total system spin multiplicity (PolarMACE context)")
    p.add_argument("--external-field", type=float, nargs=3, default=[0.0, 0.0, 0.0],
                    metavar=("EX", "EY", "EZ"), help="External electric field (PolarMACE context)")

    p.add_argument("--temps", required=True, nargs="+", type=float,
                    help="Temperature(s) in K, e.g. --temps 300 350 400")
    p.add_argument("--eq-ps", type=float, default=10.0,
                    help="NVT equilibration duration in ps (default: 10). "
                         "Ignored if --eq-steps is given.")
    p.add_argument("--prod-ps", type=float, default=1000.0,
                    help="NVT production duration in ps (default: 1000). "
                         "Ignored if --prod-steps is given.")
    p.add_argument("--eq-steps", type=int, default=None,
                    help="NVT equilibration duration in raw MD steps. "
                         "Overrides --eq-ps if given, e.g. --eq-steps 2000")
    p.add_argument("--prod-steps", type=int, default=None,
                    help="NVT production duration in raw MD steps. "
                         "Overrides --prod-ps if given, e.g. --prod-steps 100000")
    p.add_argument("--timestep-fs", type=float, default=0.5, help="MD timestep in fs (default: 0.5)")
    p.add_argument("--friction", type=float, default=0.01, help="Langevin friction coefficient (default: 0.01)")

    p.add_argument("--min-fmax", type=float, default=0.05, help="Minimisation force convergence eV/Å (default: 0.05)")
    p.add_argument("--min-max-steps", type=int, default=500, help="Max minimisation steps (default: 500)")

    p.add_argument("--log-interval", type=int, default=10, help="Steps between CSV log rows (default: 10)")
    p.add_argument("--traj-interval", type=int, default=50, help="Steps between trajectory frames (default: 50)")

    p.add_argument("--rdf-bins", type=int, default=300, help="RDF bins (default: 300)")
    p.add_argument("--rdf-rmax", type=float, default=None,
                    help="RDF rmax in Å (default: half the shortest cell length)")
    p.add_argument("--rdf-skip", type=int, default=0, help="Skip this many production frames before averaging RDF")
    p.add_argument("--rdf-stride", type=int, default=1, help="Use every Nth production frame for RDF averaging")

    p.add_argument("--outdir", type=str, default=".",
                    help="Root output directory (default: current directory)")

    p.add_argument("--sync-to", default=None,
                    help="rsync destination to push results to as they're produced, "
                         "e.g. 'pravega2@my-laptop:/home/pravega2/Documents/Piezo-LLM/"
                         "simulations/MACE-Polar'. Requires passwordless SSH (key auth) "
                         "from this machine to the target, and the target to be reachable "
                         "over the network (a laptop behind NAT/a home router usually "
                         "isn't reachable this way — see Tailscale as a fix). "
                         "Sync failures are logged as warnings and never abort the run.")
    p.add_argument("--sync-key", default=None,
                    help="Path to the SSH private key to use for --sync-to (default: "
                         "whatever ssh-agent/default key is already configured)")
    p.add_argument("--sync-after-temp", action="store_true",
                    help="Sync after every temperature finishes, not just once at the "
                         "very end (useful for long multi-temperature runs so results "
                         "start arriving on your laptop early)")

    return p


def main():
    args = build_parser().parse_args()

    if args.cif:
        cif_path = Path(args.cif)
        if not cif_path.exists():
            sys.exit(f"❌ CIF not found: {cif_path}")
    else:
        cif_path = find_cif(args.pmc, Path(args.data_dir))

    outdir_base = Path(args.outdir).resolve()
    model_tag = f"polar-{args.model}"
    results_root = outdir_base / args.pmc / model_tag / "NVT_results"
    results_root.mkdir(parents=True, exist_ok=True)

    # Resolve eq/prod duration as raw step counts, however it was specified.
    # --eq-steps/--prod-steps (if given) win over --eq-ps/--prod-ps.
    if args.eq_steps is not None:
        eq_steps = args.eq_steps
        eq_source = f"{eq_steps} steps (explicit)"
    else:
        eq_steps = int(round(args.eq_ps * 1000.0 / args.timestep_fs))
        eq_source = f"{args.eq_ps:g} ps -> {eq_steps} steps"

    if args.prod_steps is not None:
        prod_steps = args.prod_steps
        prod_source = f"{prod_steps} steps (explicit)"
    else:
        prod_steps = int(round(args.prod_ps * 1000.0 / args.timestep_fs))
        prod_source = f"{args.prod_ps:g} ps -> {prod_steps} steps"

    print("=" * 78)
    print("  MACE-Polar NVT workflow (ASE-based)")
    print("=" * 78)
    print(f"  PMC ID        : {args.pmc}")
    print(f"  CIF           : {cif_path}")
    print(f"  Supercell     : {args.supercell}x{args.supercell}x{args.supercell}")
    print(f"  Model         : {args.model}")
    print(f"  Temperatures  : {args.temps}")
    print(f"  Eq duration   : {eq_source}")
    print(f"  Prod duration : {prod_source}")
    print(f"  Timestep      : {args.timestep_fs} fs")
    print(f"  Charge/Spin   : {args.charge} / {args.spin}")
    print(f"  Ext. field    : {args.external_field}")
    print(f"  Results dir   : {results_root}")
    print()

    cif_atoms = load_supercell(cif_path, args.supercell)
    print(f"  🧱 Supercell atoms: {len(cif_atoms)}")
    print(f"  📦 Cell volume: {cif_atoms.get_volume():.3f} Å³")

    calc = setup_polar_calculator(args.model, args.model_path, Path(args.models_dir),
                                   args.device, args.dtype)

    min_atoms_cache: dict = {}  # minimisation is shared across all requested temperatures

    t0 = time.time()
    for temp in args.temps:
        run_single_temperature(
            cif_atoms=cif_atoms,
            min_atoms_cache=min_atoms_cache,
            calc=calc,
            results_root=results_root,
            temp_K=temp,
            eq_steps=eq_steps,
            prod_steps=prod_steps,
            timestep_fs=args.timestep_fs,
            friction=args.friction,
            log_interval=args.log_interval,
            traj_interval=args.traj_interval,
            min_fmax=args.min_fmax,
            min_max_steps=args.min_max_steps,
            charge=args.charge,
            spin=args.spin,
            field=tuple(args.external_field),
            rdf_bins=args.rdf_bins,
            rdf_rmax=args.rdf_rmax,
            rdf_skip=args.rdf_skip,
            rdf_stride=args.rdf_stride,
            sync_to=args.sync_to,
            sync_key=args.sync_key,
            sync_after_temp=args.sync_after_temp,
        )

    elapsed = time.time() - t0
    print("\n" + "=" * 78)
    print(f"  All requested temperatures finished in {elapsed / 60:.1f} min")
    print("=" * 78)

    if args.sync_to:
        print("\n" + "=" * 78)
        print("  Final sync")
        print("=" * 78)
        sync_to_remote(results_root, args.sync_to, args.sync_key)


if __name__ == "__main__":
    main()