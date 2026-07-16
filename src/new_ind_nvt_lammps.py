#!/usr/bin/env python3
"""
run_nvt_lammps.py
=================

LAMMPS + MACE version of the NVT workflow — SINGLE-FILE EDITION.

This is a merge of the original run_nvt_lammps.py driver script and its
lammps_common.py helper module into one self-contained file. All logic is
identical to the two-file version; only the module boundary was removed
(no more `import lammps_common as lc`, everything lives here) so future
feature changes only need to touch one file.

Workflow per temperature:
    1) Minimisation
    2) NVT equilibration
    3) NVT production
    4) Optional RDF analysis

This version uses restart-based continuity:
    minimisation.restart -> equilibration -> nvt_equilibration.restart -> production

So production continues from the equilibrated state without losing velocities
or reconstructing the cell from a PDB roundtrip.

Key design (from the former lammps_common.py)
-----------------------------------------------
This version uses LAMMPS restart files for stage-to-stage continuity:

    Minimisation:
        read_data      starting_structure.lammps
        ...
        write_restart  minimisation.restart

    NVT equilibration:
        read_restart   minimisation.restart
        velocity create ...
        ...
        write_restart  nvt_equilibration.restart

    NVT production:
        read_restart   nvt_equilibration.restart
        (NO velocity create)
        ...
        write_restart  nvt_production.restart

This preserves:
    - velocities / thermostat state continuity
    - exact triclinic box continuity
    - stage-to-stage MD continuity without PDB/data roundtrip reinitialisation

PDB trajectories are still exported for downstream RDF / comparison tooling,
but are not used as the continuation mechanism.

Also included: run_npt_stage() / build_npt_input() for NPT runs, kept here
so this single file stays a drop-in replacement for both former modules.

This edition also merges in md_common.py (supercell generation, plotting,
RDF tools, and the ASE-native checkpointed MD engine), so the script now
has ZERO dependency on any other local project module -- only third-party
packages (ase, numpy, optionally matplotlib) and the LAMMPS binary itself.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from ase import Atoms
from ase.io import read, write
from ase.io.lammpsdata import write_lammps_data


# =============================================================================
# md_common.py content (merged in) — supercell generation, plotting, RDF,
# and the ASE-native checkpointed minimisation/MD engine (run_minimisation /
# run_md_stage) kept here for parity with the original module, even though
# the LAMMPS pipeline above uses its own LAMMPS-based stage runners instead.
# =============================================================================

# ── Paths (shared by both pipelines; each pipeline picks its own
#    results subfolder so NVT and NPT outputs never mix) ──────────
# Baked-in default data location. Override with env vars if this ever moves
# or if you run the script from a different machine/account:
#   export HIMESH_PROJECT_ROOT=/some/other/himesh_work
#   export HIMESH_DATA_DIR=/some/other/data/dir
PROJECT_ROOT = Path(os.environ.get(
    "HIMESH_PROJECT_ROOT", "/home/chemistry/phd/cyz218376/himesh_work"
))
DATA_DIR = Path(os.environ.get("HIMESH_DATA_DIR", str(PROJECT_ROOT / "data")))
SIM_DIR = Path(os.environ.get("HIMESH_SIM_DIR", str(PROJECT_ROOT / "simulations")))

# ── Defaults (overridable on the command line in each script) ─────
DEFAULT_TIMESTEP_FS = 0.5
DEFAULT_EQ_STEPS = 20000          # NVT equilibration steps
DEFAULT_PROD_STEPS = 200000       # production steps
DEFAULT_PRESSURE_BAR = 1.0
TRAJECTORY_INTERVAL = 100         # write a trajectory frame every N steps
LOG_INTERVAL = 100                # write a thermo row every N steps
CHECKPOINT_INTERVAL = 5000        # flush restart+state every N steps
MIN_CHECKPOINT_INTERVAL = 50      # flush minimiser restart every N opt steps

NPT_TTIME_FS = 25.0
NPT_PTIME_FS = 75.0
NPT_BULK_MODULUS_GPA = 100.0

RDF_R_MAX = 10.0                  # Angstrom
RDF_N_BINS = 200


# ═══════════════════════════════════════════════════════════════════
#  Molecule / supercell helpers
def find_cif(pmc_id: str) -> Path:
    folder = DATA_DIR / pmc_id
    if not folder.exists():
        return None
    cif_files = list(folder.glob("*.cif"))
    return cif_files[0] if cif_files else None


def get_available_molecules() -> list:
    molecules = []
    if not DATA_DIR.exists():
        return molecules
    for folder in sorted(DATA_DIR.iterdir()):
        if folder.is_dir() and folder.name.startswith("PMC-"):
            cif = list(folder.glob("*.cif"))
            json_f = list(folder.glob("*.json"))
            name = ""
            if json_f:
                try:
                    with open(json_f[0]) as f:
                        name = json.load(f).get("molecule_name", "")
                except Exception:
                    pass
            molecules.append({
                "pmc_id": folder.name,
                "has_cif": bool(cif),
                "has_json": bool(json_f),
                "molecule_name": name,
                "cif_file": cif[0].name if cif else "MISSING",
            })
    return molecules


def resolve_pmc_id(query: str) -> Tuple[str, str]:
    """
    Accept EITHER a PMC ID (e.g. 'PMC-001', case-insensitive, matched
    directly against the folder name under DATA_DIR) OR a molecule name
    (e.g. 'Glycine', matched against the 'molecule_name' field in each
    PMC folder's .json metadata), and resolve it to (pmc_id, molecule_name).

    Matching order:
        1) exact folder-name match (case-insensitive)
        2) exact molecule-name match (case-insensitive)
        3) unique substring molecule-name match
    Raises if nothing matches, or if a substring match is ambiguous.
    """
    query_norm = query.strip()
    molecules = get_available_molecules()

    # 1) direct PMC folder match
    for m in molecules:
        if m["pmc_id"].lower() == query_norm.lower():
            return m["pmc_id"], m["molecule_name"]

    # 2) exact molecule-name match
    for m in molecules:
        if m["molecule_name"] and m["molecule_name"].strip().lower() == query_norm.lower():
            return m["pmc_id"], m["molecule_name"]

    # 3) unique substring molecule-name match
    substr_matches = [
        m for m in molecules
        if m["molecule_name"] and query_norm.lower() in m["molecule_name"].lower()
    ]
    if len(substr_matches) == 1:
        m = substr_matches[0]
        return m["pmc_id"], m["molecule_name"]
    if len(substr_matches) > 1:
        options = ", ".join(f"{m['pmc_id']} ({m['molecule_name']})" for m in substr_matches)
        raise ValueError(
            f"'{query}' matches multiple molecules — be more specific: {options}"
        )

    available = ", ".join(f"{m['pmc_id']} ({m['molecule_name'] or 'no name in json'})" for m in molecules)
    raise FileNotFoundError(
        f"Could not resolve '{query}' to a PMC ID or a known molecule name under {DATA_DIR}.\n"
        f"Available entries: {available if available else '(none found — check DATA_DIR)'}"
    )


def generate_supercell(pmc_id: str, size: int = 2) -> dict:
    from ase.io import read, write
    from ase.build import make_supercell

    cif_path = find_cif(pmc_id)
    if not cif_path:
        return {"status": "error", "message": f"No CIF file found for {pmc_id}"}

    size_str = f"{size}x{size}x{size}"
    sim_dir = SIM_DIR / pmc_id
    sim_dir.mkdir(parents=True, exist_ok=True)
    output_path = sim_dir / f"{pmc_id}_supercell_{size_str}.cif"

    if output_path.exists():
        atoms = read(str(output_path))
        print(f"  Supercell already exists: {len(atoms)} atoms")
        return {"status": "exists", "atoms": len(atoms), "path": str(output_path)}

    print(f"  Reading CIF: {cif_path.name}")
    atoms = read(str(cif_path))
    print(f"  Unit cell: {len(atoms)} atoms")

    P = np.diag([size, size, size])
    supercell = make_supercell(atoms, P)
    print(f"  Supercell: {len(supercell)} atoms ({size_str})")

    write(str(output_path), supercell, format="cif")
    print(f"  Saved: {output_path.name}")
    return {"status": "success", "atoms": len(supercell), "path": str(output_path)}


# ═══════════════════════════════════════════════════════════════════
#  Checkpoint state helpers
def ase_save_stage_state(state_path: Path, state: dict):
    """Write stage state JSON atomically (tmp file + rename)."""
    tmp_path = state_path.with_suffix(state_path.suffix + ".tmp")
    with open(tmp_path, "w") as f:
        json.dump(state, f, indent=2)
    tmp_path.replace(state_path)


def ase_load_stage_state(state_path: Path):
    if not state_path.exists():
        return None
    with open(state_path, "r") as f:
        return json.load(f)


def append_log_to_csv(csv_path: Path, log_rows: list, write_header: bool = False):
    if not log_rows:
        return
    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=log_rows[0].keys())
        if write_header:
            writer.writeheader()
        writer.writerows(log_rows)

def append_log_to_viewlog(csv_path: Path, log_rows: list, write_header: bool = False):
    """Append thermo rows to a human-readable .log file."""
    if not log_rows:
        return

    with open(csv_path, "a") as f:
        if write_header:
            f.write(
                f"{'step':>8} {'time_fs':>12} {'T(K)':>10} {'KE(eV)':>14} "
                f"{'PE(eV)':>14} {'E_tot(eV)':>14} {'P(GPa)':>12} "
                f"{'V(A^3)':>12} {'a':>10} {'b':>10} {'c':>10} "
                f"{'alpha':>10} {'beta':>10} {'gamma':>10}\n"
            )
            f.write("-" * 170 + "\n")

        for row in log_rows:
            f.write(
                f"{row['step']:8d} "
                f"{row['time_fs']:12.1f} "
                f"{row['temperature_K']:10.2f} "
                f"{row['kinetic_eV']:14.6f} "
                f"{row['potential_eV']:14.6f} "
                f"{row['total_eV']:14.6f} "
                f"{row['pressure_GPa']:12.6f} "
                f"{row['volume_A3']:12.3f} "
                f"{row['a_A']:10.4f} "
                f"{row['b_A']:10.4f} "
                f"{row['c_A']:10.4f} "
                f"{row['alpha_deg']:10.4f} "
                f"{row['beta_deg']:10.4f} "
                f"{row['gamma_deg']:10.4f}\n"
            )

def append_log_to_text(csv_path: Path, log_rows: list, write_header: bool = False):
    """Append thermo rows to a plain-text .log file."""
    if not log_rows:
        return

    with open(csv_path, "a") as f:
        if write_header:
            f.write("# Thermodynamic log\n")
            f.write("# Columns:\n")
            f.write("# step time_fs temperature_K kinetic_eV potential_eV total_eV pressure_GPa volume_A3 a_A b_A c_A alpha_deg beta_deg gamma_deg\n")

        for row in log_rows:
            f.write(
                f"{row['step']:8d} "
                f"{row['time_fs']:12.3f} "
                f"{row['temperature_K']:12.3f} "
                f"{row['kinetic_eV']:14.6f} "
                f"{row['potential_eV']:14.6f} "
                f"{row['total_eV']:14.6f} "
                f"{row['pressure_GPa']:12.6f} "
                f"{row['volume_A3']:12.3f} "
                f"{row['a_A']:10.4f} "
                f"{row['b_A']:10.4f} "
                f"{row['c_A']:10.4f} "
                f"{row['alpha_deg']:10.4f} "
                f"{row['beta_deg']:10.4f} "
                f"{row['gamma_deg']:10.4f}\n"
            )
class StepBudget:
    """Caps how many MD/optimiser steps a single process invocation may
    run, so a huge simulation can be executed as many short slices
    (e.g. one per queued HPC job) while remaining fully checkpointed.

    remaining=None means "no cap" (run until each stage's own target
    is reached).
    """
    def __init__(self, remaining=None):
        self.remaining = remaining  # None or int

    def take(self, want: int) -> int:
        """Return how many steps may be run right now for a request of
        `want` steps, and debit the budget."""
        if self.remaining is None:
            return want
        take = max(0, min(want, self.remaining))
        self.remaining -= take
        return take

    @property
    def exhausted(self) -> bool:
        return self.remaining is not None and self.remaining <= 0


# ═══════════════════════════════════════════════════════════════════
#  Plotting
def _load_csv_numeric(csv_path: Path, columns):
    """Read a thermo CSV back into a list of dicts with the requested
    columns cast to float/int."""
    rows = []
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out = {}
            for c in columns:
                v = row[c]
                out[c] = int(float(v)) if c == "step" else float(v)
            rows.append(out)
    return rows


def plot_temp_vs_time(csv_path: Path, target_temp: float, title: str, out_path: Path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  ℹ matplotlib not installed — skipping temperature plot (CSV still saved).")
        return None

    rows = _load_csv_numeric(csv_path, ["step", "time_fs", "temperature_K"])
    if not rows:
        return None
    t_ps = [r["time_fs"] / 1000.0 for r in rows]
    temp_arr = [r["temperature_K"] for r in rows]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(t_ps, temp_arr, color="C3", linewidth=0.9, label="Instantaneous T")
    ax.axhline(target_temp, color="grey", linestyle="--", linewidth=0.8,
               label=f"target {target_temp} K")
    ax.set_xlabel("Time (ps)")
    ax.set_ylabel("Temperature (K)")
    ax.set_title(title)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def plot_volume_vs_time(csv_path: Path, title: str, out_path: Path, initial_volume=None):
    """Volume vs Time. If initial_volume is given (Å³), it is drawn as
    a horizontal reference line (e.g. the minimised/reference cell
    volume) so drift can be judged visually."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  ℹ matplotlib not installed — skipping volume plot (CSV still saved).")
        return None

    rows = _load_csv_numeric(csv_path, ["step", "time_fs", "volume_A3"])
    if not rows:
        return None
    t_ps = [r["time_fs"] / 1000.0 for r in rows]
    vol = [r["volume_A3"] for r in rows]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(t_ps, vol, color="C2", linewidth=0.9, label="Instantaneous V")
    if initial_volume is not None:
        ax.axhline(initial_volume, color="grey", linestyle="--", linewidth=0.9,
                    label=f"initial V = {initial_volume:.1f} Å³")
    ax.set_xlabel("Time (ps)")
    ax.set_ylabel("Volume (Å³)")
    ax.set_title(title)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


# ═══════════════════════════════════════════════════════════════════
#  RDF
def compute_rdf_single(atoms, r_max=RDF_R_MAX, n_bins=RDF_N_BINS, elements=None):
    """Total + per-element-pair g(r) for a single ASE Atoms frame,
    using the minimum-image convention (PBC-aware neighbor list).

    Normalisation uses the global number density (N_atoms / V) for
    every pair channel. This is the standard convention for a total
    g(r) computed from a full (double-counted) neighbor list; it is
    convenient here because it puts every partial curve on the same
    footing for visual comparison, at the cost of not matching a
    strict per-species partial-RDF integral. Fine for the purpose of
    this pipeline (comparing simulation vs actual vs minimised).
    """
    from ase.neighborlist import neighbor_list

    symbols = np.array(atoms.get_chemical_symbols())
    if elements is None:
        elements = sorted(set(symbols))

    bin_edges = np.linspace(0.0, r_max, n_bins + 1)
    r_centers = 0.5 * (bin_edges[1:] + bin_edges[:-1])
    dr = bin_edges[1] - bin_edges[0]
    shell_vol = 4.0 * np.pi * r_centers ** 2 * dr

    n_atoms = len(atoms)
    volume = atoms.get_volume()
    rho = n_atoms / volume

    if n_atoms < 2 or volume <= 0:
        zeros = np.zeros(n_bins)
        return r_centers, zeros, {f"{a}-{b}": zeros.copy()
                                   for i, a in enumerate(elements)
                                   for b in elements[i:]}

    i_idx, j_idx, d = neighbor_list("ijd", atoms, r_max)

    def hist_to_gr(dist_arr):
        counts, _ = np.histogram(dist_arr, bins=bin_edges)
        with np.errstate(divide="ignore", invalid="ignore"):
            gr = counts / (rho * shell_vol * n_atoms)
        return np.nan_to_num(gr)

    total_gr = hist_to_gr(d)

    sym_i = symbols[i_idx]
    sym_j = symbols[j_idx]
    pair_gr = {}
    for a_pos, a in enumerate(elements):
        for b in elements[a_pos:]:
            mask = ((sym_i == a) & (sym_j == b)) | ((sym_i == b) & (sym_j == a))
            pair_gr[f"{a}-{b}"] = hist_to_gr(d[mask])

    return r_centers, total_gr, pair_gr


def compute_rdf_trajectory(traj_path: Path, r_max=RDF_R_MAX, n_bins=RDF_N_BINS,
                            elements=None, stride: int = 1):
    """Average g(r) over every `stride`-th frame of a PDB trajectory."""
    from ase.io import read

    frames = read(str(traj_path), index=f"::{stride}")
    if not isinstance(frames, list):
        frames = [frames]
    if not frames:
        return None, None, None

    if elements is None:
        symbols = frames[0].get_chemical_symbols()
        elements = sorted(set(symbols))

    r_centers = total_sum = None
    pair_sum = {}
    n_frames = 0
    for atoms in frames:
        r_centers, total_gr, pair_gr = compute_rdf_single(atoms, r_max, n_bins, elements)
        if total_sum is None:
            total_sum = np.zeros_like(total_gr)
            pair_sum = {k: np.zeros_like(v) for k, v in pair_gr.items()}
        total_sum += total_gr
        for k, v in pair_gr.items():
            pair_sum[k] += v
        n_frames += 1

    total_avg = total_sum / n_frames
    pair_avg = {k: v / n_frames for k, v in pair_sum.items()}
    return r_centers, total_avg, pair_avg


def save_rdf_xvg(path: Path, r_centers, total_gr, pair_gr: dict, title: str):
    """GROMACS-style .xvg file with the total RDF + every element-pair
    RDF as separate columns/legend entries."""
    cols = ["g_total"] + list(pair_gr.keys())
    with open(path, "w") as f:
        f.write(f'# RDF written by md_common.save_rdf_xvg\n')
        f.write(f'@    title "{title}"\n')
        f.write('@    xaxis label "r (\\cE\\C)"\n')
        f.write('@    yaxis label "g(r)"\n')
        f.write('@TYPE xy\n')
        f.write(f'@ legend on\n')
        f.write('@ legend box on\n')
        for idx, name in enumerate(cols):
            f.write(f'@ s{idx} legend "{name}"\n')
        for k in range(len(r_centers)):
            row = [f"{r_centers[k]:.4f}", f"{total_gr[k]:.6f}"]
            row += [f"{pair_gr[p][k]:.6f}" for p in pair_gr]
            f.write(" ".join(row) + "\n")


def plot_rdf_comparison(r_centers, curves: dict, out_path: Path, title: str):
    """curves: {label: (g_r_array, color_or_None)}"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  ℹ matplotlib not installed — skipping RDF plot (xvg still saved).")
        return None

    fig, ax = plt.subplots(figsize=(8, 4.5))
    for label, (gr, color) in curves.items():
        if gr is None:
            continue
        ax.plot(r_centers, gr, linewidth=1.1, label=label, color=color)
    ax.set_xlabel("r (Å)")
    ax.set_ylabel("g(r)")
    ax.set_title(title)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


# ═══════════════════════════════════════════════════════════════════
#  Checkpointed minimisation
def run_minimisation(atoms_in, calc, stage_dir: Path, fmax=0.05, max_steps=500,
                      checkpoint_interval=MIN_CHECKPOINT_INTERVAL,
                      traj_name="trajectory.pdb",
                      last_frame_name="last-frame-of-trajectory.pdb",
                      log_name="minimisation.log",
                      budget: StepBudget = None):
    """LBFGS minimisation with checkpoint/resume + slice-budget support.

    Files written to stage_dir:
      trajectory.pdb              every accepted geometry step (PBC-aware)
      last-frame-of-trajectory.pdb  final (or latest, if paused) geometry
      minimisation.log            ASE optimiser log
      state.json / restart.extxyz checkpoint

    NOTE ON RESUMING: LBFGS keeps an internal curvature history that is
    not saved. Resuming re-initialises LBFGS from the last checkpointed
    geometry — this is a correct restart of the minimisation (forces
    are re-evaluated and it will still converge to the same minimum),
    it's just not bit-identical to an uninterrupted run.
    """
    from ase.io import read, write
    from ase.optimize import LBFGS

    stage_dir.mkdir(parents=True, exist_ok=True)
    traj_path = stage_dir / traj_name
    last_frame_path = stage_dir / last_frame_name
    log_path = stage_dir / log_name
    restart_path = stage_dir / "minimisation.restart.extxyz"
    state_path = stage_dir / "minimisation.state.json"

    state = ase_load_stage_state(state_path)
    if state is not None and state.get("status") == "completed" and last_frame_path.exists():
        print(f"    Minimisation already completed — loading {last_frame_path.name}")
        final_atoms = read(str(last_frame_path))
        final_atoms.calc = calc
        return final_atoms, 0.0, True

    if state is not None and restart_path.exists():
        completed_steps = int(state.get("completed_steps", 0))
        print(f"    Resuming minimisation from checkpoint: "
              f"completed_steps={completed_steps}, target_steps={max_steps}")
        atoms = read(str(restart_path))
        atoms.calc = calc
    else:
        completed_steps = 0
        atoms = atoms_in.copy()
        atoms.calc = calc
        if traj_path.exists():
            traj_path.unlink()
        state = {
            "stage": "minimisation", "fmax": fmax, "target_steps": max_steps,
            "completed_steps": 0, "checkpoint_interval": checkpoint_interval,
            "trajectory_file": traj_name, "restart_file": restart_path.name,
            "status": "running",
        }
        ase_save_stage_state(state_path, state)

    def write_frame():
        write(str(traj_path), atoms, format="proteindatabank", append=True)

    def checkpoint():
        write(str(restart_path), atoms, format="extxyz")
        write(str(last_frame_path), atoms, format="proteindatabank")
        state["completed_steps"] = completed_steps + opt.nsteps
        state["status"] = "running"
        ase_save_stage_state(state_path, state)

    t0 = time.time()
    # ASE's Optimizer always opens logfile in append mode, so resuming a
    # minimisation naturally appends to the existing minimisation.log.
    opt = LBFGS(atoms, logfile=str(log_path), trajectory=str(traj_path), maxstep=0.2)
    opt.attach(write_frame, interval=1)
    opt.attach(checkpoint, interval=checkpoint_interval)

    remaining_target = max_steps - completed_steps
    if remaining_target <= 0:
        remaining_target = 0

    if budget is None:
        run_steps = remaining_target
    else:
        run_steps = budget.take(remaining_target)

    converged = False
    if run_steps > 0:
        opt.run(fmax=fmax, steps=run_steps)
        converged = opt.converged()

    elapsed = time.time() - t0
    new_completed = completed_steps + opt.nsteps

    write(str(restart_path), atoms, format="extxyz")
    write(str(last_frame_path), atoms, format="proteindatabank")

    finished = converged or new_completed >= max_steps
    state["completed_steps"] = new_completed
    state["status"] = "completed" if finished else "paused (slice budget reached)"
    ase_save_stage_state(state_path, state)

    e = atoms.get_potential_energy()
    print(f"    💾 Saved trajectory: {traj_path}")
    print(f"    💾 Saved last frame: {last_frame_path}")
    print(f"    💾 Saved log:        {log_path}")
    if finished:
        print(f"    ✅ Minimisation done: {elapsed:.0f}s | "
              f"Steps={new_completed} | Energy={e:.2f} eV | converged={converged}")
    else:
        print(f"    ⏸  Minimisation paused (slice budget): "
              f"{new_completed}/{max_steps} steps done, {elapsed:.0f}s this slice")

    return atoms, elapsed, finished


# ═══════════════════════════════════════════════════════════════════
#  Checkpointed MD stage (NVT or NPT)
def run_md_stage(atoms_in, calc, target_steps, timestep_fs, temp, stage_dir: Path,
                  dyn_type="nvt", pressure_GPa=0.0, init_velocities=False,
                  plot_kind=None, traj_name="trajectory.pdb",
                  last_frame_name="last-frame-of-trajectory.pdb",
                  log_name="thermo.csv", stage_label="stage",
                  view_log_name="thermo.log",
                  checkpoint_interval=CHECKPOINT_INTERVAL,
                  budget: StepBudget = None, initial_volume=None):
    """Run one MD stage (NVT or NPT) with checkpoint/resume + slice-budget
    support.

    Files written to stage_dir:
      {traj_name}            PDB trajectory (CRYST1 kept)
      {last_frame_name}      last written frame, refreshed at every checkpoint
      {log_name}             thermo CSV (step, time, T, E, P, V, a/b/c/...)
      {view_log_name}        human-readable thermo log
      {stage}_temp.png / {stage}_volume.png   depending on plot_kind
      state.json / restart.extxyz             checkpoint

    Returns (final_atoms, elapsed_seconds, finished: bool).
    `finished=False` means the slice budget ran out before target_steps
    was reached — rerun the same script/stage to continue.
    """
    from ase.io import read, write
    from ase.md.nvtberendsen import NVTBerendsen
    from ase.md.npt import NPT
    from ase.md.velocitydistribution import MaxwellBoltzmannDistribution
    from ase import units

    stage_dir.mkdir(parents=True, exist_ok=True)
    ensemble_name = "NPT" if dyn_type == "npt" else "NVT"

    traj_path = stage_dir / traj_name
    last_frame_path = stage_dir / last_frame_name
    csv_path = stage_dir / log_name
    view_log_path = stage_dir / view_log_name  
    restart_path = stage_dir / "restart.extxyz"
    state_path = stage_dir / "state.json"

    state = ase_load_stage_state(state_path)
    completed_steps = 0
    fresh_csv = True

    if state is not None and restart_path.exists():
        completed_steps = int(state.get("completed_steps", 0))
        target_steps_old = int(state.get("target_steps", target_steps))
        target_steps = max(target_steps, target_steps_old)

        if completed_steps >= target_steps:
            print(f"    {stage_label} already completed "
                  f"({completed_steps}/{target_steps} steps) — loading restart")
            final_atoms = read(str(restart_path))
            final_atoms.calc = calc
            return final_atoms, 0.0, True

        print(f"    Resuming {stage_label} from checkpoint: "
              f"completed={completed_steps}, target={target_steps}, "
              f"remaining={target_steps - completed_steps}")
        atoms = read(str(restart_path))
        atoms.calc = calc
        fresh_csv = not csv_path.exists()
    else:
        atoms = atoms_in.copy()
        atoms.calc = calc
        if init_velocities:
            MaxwellBoltzmannDistribution(atoms, temperature_K=temp)
        if traj_path.exists():
            traj_path.unlink()
        if csv_path.exists():
            csv_path.unlink()
        if view_log_path.exists():
            view_log_path.unlink()
        state = {
            "ensemble": ensemble_name.lower(), "stage": stage_label,
            "temperature_K": temp,
            "pressure_GPa": pressure_GPa if dyn_type == "npt" else None,
            "timestep_fs": timestep_fs, "target_steps": target_steps,
            "completed_steps": 0, "checkpoint_interval": checkpoint_interval,
            "trajectory_file": traj_name, "csv_file": log_name,
            "restart_file": restart_path.name, "status": "running",
        }
        ase_save_stage_state(state_path, state)

    remaining_total = target_steps - completed_steps
    if remaining_total <= 0:
        final_atoms = read(str(restart_path)) if restart_path.exists() else atoms
        final_atoms.calc = calc
        return final_atoms, 0.0, True

    if dyn_type == "npt":
        cell = atoms.get_cell()
        if abs(cell[1, 0]) + abs(cell[2, 0]) + abs(cell[2, 1]) > 1e-8:
            atoms.set_cell(cell.standard_form()[0], scale_atoms=True)
        ttime = NPT_TTIME_FS * units.fs
        ptime = NPT_PTIME_FS * units.fs
        pfactor = ptime ** 2 * NPT_BULK_MODULUS_GPA * units.GPa
        dyn = NPT(atoms, timestep=timestep_fs * units.fs, temperature_K=temp,
                  externalstress=pressure_GPa * units.GPa, ttime=ttime, pfactor=pfactor)
        label = f"NPT @ {pressure_GPa / BAR_TO_GPA:.1f} bar"
    else:
        dyn = NVTBerendsen(atoms, timestep=timestep_fs * units.fs,
                            temperature_K=temp, taut=100 * units.fs)
        label = "NVT"

    log_data = []

    def log_thermo():
        step = completed_steps + dyn.nsteps
        t = atoms.get_temperature()
        ke = atoms.get_kinetic_energy()
        pe = atoms.get_potential_energy()
        vol = atoms.get_volume()
        cell = atoms.get_cell().cellpar()
        try:
            stress = atoms.get_stress(voigt=True)
            p = -(stress[0] + stress[1] + stress[2]) / 3.0 * 160.21766
        except Exception:
            p = 0.0
        row = {
            "step": step, "time_fs": step * timestep_fs, "temperature_K": t,
            "kinetic_eV": ke, "potential_eV": pe, "total_eV": ke + pe,
            "pressure_GPa": p, "volume_A3": vol,
            "a_A": cell[0], "b_A": cell[1], "c_A": cell[2],
            "alpha_deg": cell[3], "beta_deg": cell[4], "gamma_deg": cell[5],
        }
        log_data.append(row)
        if step % 5000 == 0:
            print(f"      Step {step:6d} | {step*timestep_fs/1000:6.1f} ps | "
                  f"T={t:6.1f} K | E={ke+pe:12.2f} eV | V={vol:8.1f} Å³ | "
                  f"a={cell[0]:.3f} b={cell[1]:.3f} c={cell[2]:.3f}")

    def write_frame():
        write(str(traj_path), atoms, format="proteindatabank", append=True)

    def flush_checkpoint():
        nonlocal fresh_csv
        write(str(restart_path), atoms, format="extxyz")
        write(str(last_frame_path), atoms, format="proteindatabank")
        if log_data:
            append_log_to_csv(csv_path, log_data, write_header=fresh_csv)
            append_log_to_viewlog(view_log_path, log_data, write_header=fresh_csv)
            fresh_csv = False
            log_data.clear()
        current_steps = completed_steps + dyn.nsteps
        state["completed_steps"] = current_steps
        state["target_steps"] = target_steps
        state["status"] = "running"
        ase_save_stage_state(state_path, state)

    dyn.attach(write_frame, interval=TRAJECTORY_INTERVAL)
    dyn.attach(log_thermo, interval=LOG_INTERVAL)
    dyn.attach(flush_checkpoint, interval=checkpoint_interval)

    steps_to_run = budget.take(remaining_total) if budget is not None else remaining_total
    ps_run = steps_to_run * timestep_fs / 1000.0
    print(f"    {stage_label} ({ps_run:.2f} ps = {steps_to_run} of "
          f"{remaining_total} remaining steps, {label})...")

    t0 = time.time()
    if steps_to_run > 0:
        dyn.run(steps_to_run)
    elapsed = time.time() - t0

    flush_checkpoint()

    finished = (completed_steps + dyn.nsteps) >= target_steps
    state["status"] = "completed" if finished else "paused (slice budget reached)"
    ase_save_stage_state(state_path, state)

    # plots use the full CSV on disk (all slices concatenated)
    if plot_kind == "temp" and csv_path.exists():
        plot_path = stage_dir / f"{stage_label.replace(' ', '_').lower()}_temp.png"
        saved = plot_temp_vs_time(csv_path, temp,
                                   f"{stage_label} — Temperature vs Time ({temp} K)", plot_path)
        if saved:
            print(f"    💾 Saved plot (Temperature vs Time): {plot_path}")
    elif plot_kind == "volume" and csv_path.exists():
        plot_path = stage_dir / f"{stage_label.replace(' ', '_').lower()}_volume.png"
        saved = plot_volume_vs_time(
            csv_path,
            f"{stage_label} — Volume vs Time ({temp} K, {pressure_GPa / BAR_TO_GPA:.1f} bar)",
            plot_path, initial_volume=initial_volume)
        if saved:
            print(f"    💾 Saved plot (Volume vs Time): {plot_path}")

    print(f"    💾 Saved trajectory: {traj_path}")
    print(f"    💾 Saved last frame: {last_frame_path}")
    print(f"    💾 Saved log:        {csv_path}")
    print(f"    💾 Saved view log:   {view_log_path}")

    final_T = atoms.get_temperature()
    final_V = atoms.get_volume()
    if finished:
        print(f"    ✅ {stage_label} done: {elapsed:.0f}s this slice | "
              f"Final T={final_T:.1f} K | Final V={final_V:.1f} Å³")
    else:
        done = completed_steps + dyn.nsteps
        print(f"    ⏸  {stage_label} paused (slice budget): "
              f"{done}/{target_steps} steps done, {elapsed:.0f}s this slice — "
              f"rerun the script to continue")

    return atoms, elapsed, finished


# ═══════════════════════════════════════════════════════════════════
#  Progress reporting (the "trace" the user asked for)
def collect_progress(results_dir: Path):
    """Walk every state.json under results_dir and return a flat list
    of {path, stage, completed_steps, target_steps, status}."""
    rows = []
    if not results_dir.exists():
        return rows
    for state_path in sorted(results_dir.rglob("state.json")) + \
                       sorted(results_dir.rglob("minimisation.state.json")):
        try:
            state = load_stage_state(state_path)
        except Exception:
            continue
        if not state:
            continue
        rows.append({
            "path": str(state_path.relative_to(results_dir)),
            "stage": state.get("stage", "?"),
            "temperature_K": state.get("temperature_K"),
            "completed_steps": state.get("completed_steps", 0),
            "target_steps": state.get("target_steps", 0),
            "status": state.get("status", "?"),
        })
    return rows


def print_progress_table(results_dir: Path, label: str):
    rows = collect_progress(results_dir)
    print(f"\n  Progress trace — {label}")
    print(f"  {results_dir}")
    print(f"  {'─'*90}")
    if not rows:
        print("  (no stages started yet)")
        return
    print(f"  {'Stage':<28}{'T (K)':<8}{'Completed':<12}{'Target':<12}{'%':<7}{'Status'}")
    print(f"  {'─'*90}")
    for r in rows:
        pct = (100.0 * r["completed_steps"] / r["target_steps"]) if r["target_steps"] else 0.0
        temp_str = f"{r['temperature_K']}" if r["temperature_K"] is not None else "-"
        print(f"  {r['stage']:<28}{temp_str:<8}{r['completed_steps']:<12}"
              f"{r['target_steps']:<12}{pct:<6.1f}%{r['status']}")

# =============================================================================
# Constants / filenames
# =============================================================================

BAR_TO_GPA = 1.0e-4   # 1 bar = 1e-4 GPa

TRAJ_PDB = "trajectory.pdb"
PROD_TRAJ_PDB = "production-trajectory.pdb"
LAST_FRAME_PDB = "last-frame-of-trajectory.pdb"

MIN_VIEW_LOG = "minimisation.view.log"
EQ_VIEW_LOG = "equilibration.view.log"
PROD_VIEW_LOG = "production.view.log"
NPT_VIEW_LOG = "npt.view.log"


# =============================================================================
# Environment auto-detection
# =============================================================================
#
# Goal: the person running this script should NOT need to manually
# `export MACE_PYTHON=...` / `export LAMMPS_BIN=...` every session. If those
# env vars aren't already set, we search a short list of conventional
# locations under the home directory before falling back to PATH.
#
# Override at any time with --mace-env / --mace-python / --lammps-bin, or
# by exporting MACE_PYTHON / LAMMPS_BIN / LAMMPS_INSTALL as before.

_KNOWN_MACE_CONDA_ENVS = [
    # This exact env has been used successfully on this system before.
    "/home/chemistry/phd/cyz218376/.conda/envs/py311/bin/python",
]


def _conda_envs_root_candidates() -> List[Path]:
    home = Path.home()
    roots = []
    for conda_dir in (".conda", "miniconda3", "anaconda3", "miniforge3"):
        envs_dir = home / conda_dir / "envs"
        if envs_dir.exists():
            roots.append(envs_dir)
    return roots


def _conda_env_python(env_name: str) -> Optional[Path]:
    """Resolve a conda env NAME (not a full path) to its python executable."""
    for envs_dir in _conda_envs_root_candidates():
        candidate = envs_dir / env_name / "bin" / "python"
        if candidate.exists():
            return candidate
    return None


def _python_env_has_package(python_path: Path, package: str) -> bool:
    """
    Cheap filesystem check for whether an interpreter's env has `package`
    installed, without paying the cost of actually launching that python.
    """
    for site_pkgs in python_path.parent.parent.glob("lib/python*/site-packages"):
        if (site_pkgs / package).exists():
            return True
    return False


def auto_detect_mace_python() -> Optional[str]:
    """
    Search known/conventional conda envs for one that has `mace` installed.
    Returns a python executable path, or None if nothing was found.
    """
    for path_str in _KNOWN_MACE_CONDA_ENVS:
        p = Path(path_str)
        if p.exists() and _python_env_has_package(p, "mace"):
            return str(p)

    for envs_dir in _conda_envs_root_candidates():
        for env_dir in sorted(envs_dir.iterdir()):
            py = env_dir / "bin" / "python"
            if py.exists() and _python_env_has_package(py, "mace"):
                return str(py)

    return None


def auto_detect_lammps_bin() -> Optional[str]:
    """
    Search a short list of conventional build locations under the home
    directory for a LAMMPS `lmp` executable.
    """
    home = Path.home()
    patterns = [
        "lammps*/build/lmp",
        "lammps*/build/lmp_*",
        "*/lammps*/build/lmp",
        "software/lammps*/build/lmp",
        ".local/bin/lmp",
    ]
    for pat in patterns:
        for p in home.glob(pat):
            if p.is_file() and os.access(p, os.X_OK):
                return str(p)
    return None


# =============================================================================
# Model helpers
# =============================================================================

# Baked-in default folder for the small/medium/large MACE-OFF23 model
# aliases. Override with --model-dir on the command line, or by exporting
# MACE_MODEL_DIR yourself. If a plain path/filename is passed to --model
# instead of an alias, it is used as-is (absolute, or relative to CWD).
_DEFAULT_MODEL_DIR = "/home/chemistry/phd/cyz218376/himesh_work/mace_models"


def _get_model_dir() -> Path:
    return Path(os.environ.get("MACE_MODEL_DIR", _DEFAULT_MODEL_DIR))


_MODEL_ALIASES = {
    "small": "MACE-OFF23_small.model",
    "medium": "MACE-OFF23_medium.model",
    "large": "MACE-OFF23_large.model",
}


def _resolve_model_source(model_path: str) -> Path:
    """
    Resolve the user-provided model argument into a source model path.

    Accepted forms:
        small / medium / large        -> looked up under _get_model_dir()
        /path/to/model.model          -> used as-is
        /path/to/model-mliap_lammps.pt -> used as-is

    Default model dir is the baked-in path above; override via --model-dir
    or the MACE_MODEL_DIR env var.
    """
    if model_path in _MODEL_ALIASES:
        p = _get_model_dir() / _MODEL_ALIASES[model_path]
    else:
        p = Path(model_path)

    if p.exists():
        return p.resolve()

    return p


def _pick_python_for_mace() -> str:
    """
    Pick the Python executable used to run:
        python -m mace.cli.create_lammps_model ...

    Priority:
      1) $MACE_PYTHON if set
      2) current interpreter if it can import mace
      3) auto-detected conda env with mace installed (known envs, then a
         scan of ~/.conda/envs, ~/miniconda3/envs, etc.)
      4) python3 if available
      5) python
    """
    env_python = os.environ.get("MACE_PYTHON")
    if env_python:
        return env_python

    # If the current interpreter can import mace, use it.
    try:
        import mace  # noqa: F401
        return sys.executable
    except Exception:
        pass

    auto = auto_detect_mace_python()
    if auto:
        print(f"  🔎 Auto-detected MACE-capable Python env: {auto}")
        os.environ["MACE_PYTHON"] = auto
        return auto

    for candidate in ("python3", "python"):
        path = shutil.which(candidate)
        if path:
            return candidate

    return sys.executable


def _run_mace_lammps_conversion(src: Path):
    """
    Run mace.cli.create_lammps_model in a subprocess, with a couple of
    compatibility fallbacks for newer PyTorch defaults.
    """
    pyexe = _pick_python_for_mace()

    # PyTorch >=2.6 changed torch.load default weights_only=True.
    # Some e3nn/MACE stacks still expect the old behavior for constants.pt.
    # Setting this env var restores the old behavior for the subprocess.
    env = os.environ.copy()
    env.setdefault("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")

    cmd = [
        pyexe,
        "-m",
        "mace.cli.create_lammps_model",
        str(src),
        "--format=mliap",
    ]

    try:
        subprocess.run(cmd, check=True, env=env)
        return
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            "Failed to convert the MACE model into a LAMMPS MLIAP model.\n\n"
            f"Tried command:\n  {' '.join(cmd)}\n\n"
            "Likely cause on your system:\n"
            "  the current Python/MACE/e3nn/torch stack is incompatible with\n"
            "  mace.cli.create_lammps_model (for example the torch>=2.6\n"
            "  weights_only behavior with older e3nn/MACE builds).\n\n"
            "Recommended fix:\n"
            "  run the workflow from a dedicated py311 MACE environment and/or set\n"
            "  MACE_PYTHON to that interpreter, e.g.\n"
            "    export MACE_PYTHON=/home/chemistry/phd/cyz218376/.conda/envs/py311/bin/python\n"
            "\n"
            f"Original subprocess exit code: {e.returncode}"
        ) from e


def ensure_mliap_model(model_path: str) -> Path:
    """
    Ensure we have a LAMMPS-ready MLIAP .pt model.

    Cases:
    - input already ends with .pt -> return it
    - input is a .model -> convert using mace.cli.create_lammps_model
    """
    src = _resolve_model_source(model_path)

    if src.suffix == ".pt":
        if not src.exists():
            raise FileNotFoundError(f"MLIAP model file not found: {src}")
        return src.resolve()

    if src.suffix == ".model":
        if not src.exists():
            hint = (
                f" (looked in MODEL_DIR={_get_model_dir()} for alias '{model_path}')"
                if model_path in _MODEL_ALIASES else ""
            )
            raise FileNotFoundError(
                f"MACE source model file not found: {src}{hint}\n"
                "Fix: pass --model-dir /path/to/models, export MACE_MODEL_DIR=..., "
                "or pass a full path directly via --model."
            )

        out = src.with_name(src.name + "-mliap_lammps.pt")
        if out.exists():
            return out.resolve()

        print(f"  🔄 Converting MACE model for LAMMPS:\n     {src}\n     -> {out}")
        _run_mace_lammps_conversion(src)

        if not out.exists():
            raise FileNotFoundError(
                f"Expected converted MLIAP model not found after conversion: {out}"
            )
        return out.resolve()

    raise FileNotFoundError(
        f"Could not resolve model path '{model_path}'. "
        f"Provide either a .model or a .pt file."
    )


# =============================================================================
# LAMMPS executable helpers
# =============================================================================

# Baked-in default location of the shell script that sets up the LAMMPS +
# MACE runtime (this is the same script your PBS jobs `source` before
# calling `lmp` -- it sets $LAMMPS_INSTALL, activates the matching MACE
# conda env, and fixes up LD_LIBRARY_PATH/PYTHONPATH so the `mliap unified`
# <-> MACE Python bridge is consistent). With this baked in, you no longer
# need to run `source env.sh` yourself before calling this script -- every
# LAMMPS subprocess launched here sources it automatically.
#
# Override at any time with --env-script, or by exporting LAMMPS_ENV_SCRIPT.
# Disable entirely with --no-env-script / export LAMMPS_NO_ENV_SCRIPT=1
# (e.g. if you really do want the bare `lmp`/$LAMMPS_INSTALL resolution
# from the current shell instead).
_DEFAULT_LAMMPS_ENV_SCRIPT = (
    "/home/chemistry/phd/cyz218376/home/software/mace-lammps-plumed/env.sh"
)


def _env_flag_true(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}


def resolve_env_script(env_script: Optional[str] = None) -> Optional[Path]:
    """
    Resolve the shell script to `source` before launching `lmp`.

    Priority:
      1) explicit env_script argument (--env-script)
      2) $LAMMPS_ENV_SCRIPT
      3) baked-in default (_DEFAULT_LAMMPS_ENV_SCRIPT), if it exists
      4) None (no env.sh will be sourced) -- forced by
         --no-env-script / $LAMMPS_NO_ENV_SCRIPT=1
    """
    if _env_flag_true("LAMMPS_NO_ENV_SCRIPT", default=False):
        return None

    if env_script:
        p = Path(env_script).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"--env-script not found: {p}")
        return p

    env_var = os.environ.get("LAMMPS_ENV_SCRIPT")
    if env_var:
        p = Path(env_var).expanduser()
        if not p.exists():
            raise FileNotFoundError(f"$LAMMPS_ENV_SCRIPT not found: {p}")
        return p

    default = Path(_DEFAULT_LAMMPS_ENV_SCRIPT)
    return default if default.exists() else None


def resolve_lammps_bin(lammps_bin: Optional[str] = None) -> str:
    """
    Resolve the LAMMPS executable using ONLY the current process's
    environment (no env.sh sourcing here).

    Priority:
      1) explicit --lammps-bin
      2) $LAMMPS_BIN
      3) $LAMMPS_INSTALL/bin/lmp
      4) auto-detected build under the home directory
      5) lmp from PATH (last resort, may fail if not on PATH)

    NOTE: build_lammps_command() below is normally what actually launches
    LAMMPS, and it sources env.sh (see resolve_env_script) *before*
    resolving the binary, so a fresh $LAMMPS_INSTALL from env.sh is
    honoured even though this function's own os.environ lookups can't see
    it yet. This function remains as a fallback for when no env.sh is
    available/enabled, and for display/logging purposes.
    """
    if lammps_bin:
        return lammps_bin

    env_bin = os.environ.get("LAMMPS_BIN")
    if env_bin:
        return env_bin

    install = os.environ.get("LAMMPS_INSTALL")
    if install:
        candidate = Path(install) / "bin" / "lmp"
        if candidate.exists():
            return str(candidate)

    auto = auto_detect_lammps_bin()
    if auto:
        print(f"  🔎 Auto-detected LAMMPS binary: {auto}")
        return auto

    return "lmp"


def build_lammps_command(
    input_path: Path,
    log_path: Path,
    lammps_bin: Optional[str] = None,
    env_script: Optional[str] = None,
) -> List[str]:
    """
    Build the LAMMPS command.

    By default this wraps the run so that env.sh is `source`d first (see
    resolve_env_script) -- so you never need to `source env.sh` yourself
    before running this script. The LAMMPS binary is then resolved *inside*
    that same sourced shell, so a fresh $LAMMPS_INSTALL from env.sh is
    honoured. Explicit --lammps-bin / $LAMMPS_BIN still take precedence
    over anything env.sh sets.

    If no env.sh is found/enabled, falls back to plain resolution via
    resolve_lammps_bin() against the current process environment only.

    Optional GPU/Kokkos behavior (independent of env.sh):
      export LAMMPS_USE_KOKKOS=1
      export LAMMPS_GPUS=1   (defaults to 1)

    Example GPU command produced (no env.sh):
      lmp -k on g 1 -sf kk -pk kokkos newton on neigh half -in ... -log ...

    Example CPU command produced (no env.sh):
      lmp -in ... -log ...

    Example command produced (with env.sh):
      bash -c 'source /path/env.sh && LMP_BIN=... && exec "$LMP_BIN" -in ... -log ...'
    """
    use_kokkos = _env_flag_true("LAMMPS_USE_KOKKOS", default=False)
    ngpu = os.environ.get("LAMMPS_GPUS", "1")

    lmp_args = ["-in", str(input_path), "-log", str(log_path)]
    if use_kokkos:
        lmp_args = [
            "-k", "on", "g", str(ngpu),
            "-sf", "kk",
            "-pk", "kokkos", "newton", "on", "neigh", "half",
        ] + lmp_args

    resolved_env_script = resolve_env_script(env_script)

    if not resolved_env_script:
        # No env.sh available/enabled -- resolve purely from this
        # process's own environment, exactly as before.
        lmp = resolve_lammps_bin(lammps_bin)
        return [lmp] + lmp_args

    print(f"  🔎 Sourcing LAMMPS/MACE environment script: {resolved_env_script}")

    # Explicit --lammps-bin / $LAMMPS_BIN win over anything env.sh sets.
    explicit_bin = lammps_bin or os.environ.get("LAMMPS_BIN")
    if explicit_bin:
        bin_resolve = f"LMP_BIN={shlex.quote(explicit_bin)}"
    else:
        auto = auto_detect_lammps_bin()
        auto_fallback = shlex.quote(auto) if auto else "lmp"
        # Resolved AFTER sourcing env.sh, so this sees the $LAMMPS_INSTALL
        # that env.sh just set, not whatever (or nothing) was set before.
        bin_resolve = (
            'if [ -n "$LAMMPS_INSTALL" ] && [ -x "$LAMMPS_INSTALL/bin/lmp" ]; then '
            'LMP_BIN="$LAMMPS_INSTALL/bin/lmp"; '
            f"else LMP_BIN={auto_fallback}; fi"
        )

    quoted_args = " ".join(shlex.quote(a) for a in lmp_args)
    shell_cmd = (
        f"source {shlex.quote(str(resolved_env_script))} && "
        f"{bin_resolve} && "
        f'echo "  🔎 Using LAMMPS binary: $LMP_BIN" 1>&2 && '
        f'exec "$LMP_BIN" {quoted_args}'
    )

    return ["bash", "-c", shell_cmd]


# =============================================================================
# Stage-state helpers
# =============================================================================

def load_stage_state(state_path: Path) -> dict:
    if not state_path.exists():
        return {}
    with open(state_path, "r") as f:
        return json.load(f)


def save_stage_state(state_path: Path, state: dict):
    """Write stage state JSON atomically (tmp file + rename)."""
    tmp_path = state_path.with_suffix(state_path.suffix + ".tmp")
    with open(tmp_path, "w") as f:
        json.dump(state, f, indent=2)
    tmp_path.replace(state_path)


# =============================================================================
# Atom typing / LAMMPS data writing
# =============================================================================

def unique_elements_in_order(atoms: Atoms) -> List[str]:
    """
    Return unique chemical symbols in first-occurrence order.
    Example: [H, C, N, O]
    """
    seen = set()
    ordered = []
    for sym in atoms.get_chemical_symbols():
        if sym not in seen:
            seen.add(sym)
            ordered.append(sym)
    return ordered


def build_symbol_type_mapping(atoms: Atoms) -> Tuple[List[str], Dict[str, int]]:
    """
    Returns:
        element_order: ['H','C','N','O']
        type_map: {'H':1, 'C':2, 'N':3, 'O':4}
    """
    element_order = unique_elements_in_order(atoms)
    type_map = {sym: i + 1 for i, sym in enumerate(element_order)}
    return element_order, type_map


def write_lammps_structure(
    atoms: Atoms,
    data_path: Path,
) -> Tuple[List[str], Dict[str, int]]:
    """
    Write ASE Atoms to a LAMMPS data file.

    Returns:
        element_order, type_map
    """
    element_order, type_map = build_symbol_type_mapping(atoms)

    write_lammps_data(
        str(data_path),
        atoms,
        atom_style="atomic",
        specorder=element_order,
    )

    return element_order, type_map


# =============================================================================
# LAMMPS input builders
# =============================================================================

ATOMIC_MASSES = {
    "H": 1.008,
    "He": 4.002602,
    "Li": 6.94,
    "Be": 9.0121831,
    "B": 10.81,
    "C": 12.011,
    "N": 14.007,
    "O": 15.999,
    "F": 18.998403163,
    "Ne": 20.1797,
    "Na": 22.98976928,
    "Mg": 24.305,
    "Al": 26.9815385,
    "Si": 28.085,
    "P": 30.973761998,
    "S": 32.06,
    "Cl": 35.45,
    "Ar": 39.948,
    "K": 39.0983,
    "Ca": 40.078,
    "Br": 79.904,
    "I": 126.90447,
}


def build_mass_lines(elements: Sequence[str]) -> List[str]:
    lines = []
    for i, elem in enumerate(elements, start=1):
        if elem not in ATOMIC_MASSES:
            raise ValueError(
                f"No atomic mass defined for element '{elem}'. "
                "Add it to ATOMIC_MASSES in lammps_common.py"
            )
        lines.append(f"mass            {i} {ATOMIC_MASSES[elem]}")
    return lines


def _header_lines(
    *,
    model_pt: Path,
    element_order: Sequence[str],
    timestep_fs: float,
    read_data_file: Optional[str] = None,
    read_restart_file: Optional[str] = None,
) -> List[str]:
    """
    Common header for all LAMMPS stages.

    Exactly one of read_data_file / read_restart_file should be provided.
    """
    if (read_data_file is None) == (read_restart_file is None):
        raise ValueError("Provide exactly one of read_data_file or read_restart_file")

    timestep_ps = timestep_fs / 1000.0
    element_list = list(element_order)

    lines = [
        "# Auto-generated by lammps_common.py",
        "units           metal",
        "atom_style      atomic",
        "newton          on",
        "",
    ]

    if read_data_file is not None:
        lines.append(f"read_data       {read_data_file}")
    else:
        lines.append(f"read_restart    {read_restart_file}")

    mass_lines = build_mass_lines(element_list)

    lines += [
        "",
        f"pair_style      mliap unified {model_pt} 0",
        f"pair_coeff      * * {' '.join(element_list)}",
        "",
    ]
    lines += mass_lines
    lines += [
        "",
        "neighbor        2.0 bin",
        "neigh_modify    every 1 delay 0 check yes",
        "",
        "thermo          100",
        "thermo_style    custom step temp pe ke etotal press vol",
        f"timestep        {timestep_ps:.6f}",
        "",
    ]
    return lines


def build_minimisation_input(
    *,
    data_filename: str,
    model_pt: Path,
    element_order: Sequence[str],
    output_dump: str,
    output_data: str,
    output_restart: str,
    timestep_fs: float,
) -> str:
    elems = " ".join(element_order)
    lines = _header_lines(
        model_pt=model_pt,
        element_order=element_order,
        timestep_fs=timestep_fs,
        read_data_file=data_filename,
    )
    lines += [
        'print "===== STAGE: ENERGY MINIMISATION ====="',
        "reset_timestep  0",
        f"dump            min_dump all custom 100 {output_dump} id type element x y z",
        f"dump_modify     min_dump element {elems}",
        "dump_modify     min_dump sort id",
        "min_style       cg",
        "minimize        1.0e-6 1.0e-8 10000 100000",
        "undump          min_dump",
        f"write_data      {output_data} nocoeff",
        f"write_restart   {output_restart}",
        "",
    ]
    return "\n".join(lines) + "\n"


def build_nvt_input(
    *,
    model_pt: Path,
    element_order: Sequence[str],
    temp_K: float,
    nsteps: int,
    stage_label: str,
    output_dump: str,
    output_data: str,
    output_restart: str,
    timestep_fs: float,
    init_velocities: bool,
    random_seed: int = 42,
    read_data_file: Optional[str] = None,
    read_restart_file: Optional[str] = None,
    restart_every_steps: int = 10000,
) -> str:
    elems = " ".join(element_order)
    lines = _header_lines(
        model_pt=model_pt,
        element_order=element_order,
        timestep_fs=timestep_fs,
        read_data_file=read_data_file,
        read_restart_file=read_restart_file,
    )
    lines += [
        f'print "===== STAGE: {stage_label.upper()} ====="',
        "reset_timestep  0",
    ]

    if init_velocities:
        lines += [
            f"velocity        all create {temp_K:.6f} {random_seed} dist gaussian mom yes rot yes"
        ]

    lines += [
        f"fix             md all nvt temp {temp_K:.6f} {temp_K:.6f} 0.1",
        f"dump            traj all custom 100 {output_dump} id type element x y z",
        f"dump_modify     traj element {elems}",
        "dump_modify     traj sort id",
        f"restart         {int(restart_every_steps)} {output_restart}.a {output_restart}.b",
        f"run             {nsteps}",
        "unfix           md",
        "undump          traj",
        f"write_data      {output_data} nocoeff",
        f"write_restart   {output_restart}",
        "",
    ]
    return "\n".join(lines) + "\n"


def build_npt_input(
    *,
    model_pt: Path,
    element_order: Sequence[str],
    temp_K: float,
    pressure_GPa: float,
    nsteps: int,
    stage_label: str,
    output_dump: str,
    output_data: str,
    output_restart: str,
    timestep_fs: float,
    init_velocities: bool,
    random_seed: int = 42,
    read_data_file: Optional[str] = None,
    read_restart_file: Optional[str] = None,
    restart_every_steps: int = 10000,
) -> str:
    elems = " ".join(element_order)
    pressure_bar = pressure_GPa / BAR_TO_GPA

    lines = _header_lines(
        model_pt=model_pt,
        element_order=element_order,
        timestep_fs=timestep_fs,
        read_data_file=read_data_file,
        read_restart_file=read_restart_file,
    )
    lines += [
        f'print "===== STAGE: {stage_label.upper()} ====="',
        "reset_timestep  0",
    ]

    if init_velocities:
        lines += [
            f"velocity        all create {temp_K:.6f} {random_seed} dist gaussian mom yes rot yes"
        ]

    lines += [
        f"fix             md all npt temp {temp_K:.6f} {temp_K:.6f} 0.1 iso {pressure_bar:.6f} {pressure_bar:.6f} 1.0",
        f"dump            traj all custom 100 {output_dump} id type element x y z",
        f"dump_modify     traj element {elems}",
        "dump_modify     traj sort id",
        f"restart         {int(restart_every_steps)} {output_restart}.a {output_restart}.b",
        f"run             {nsteps}",
        "unfix           md",
        "undump          traj",
        f"write_data      {output_data} nocoeff",
        f"write_restart   {output_restart}",
        "",
    ]
    return "\n".join(lines) + "\n"


# =============================================================================
# Log parsing
# =============================================================================

def parse_lammps_log(log_path: Path) -> List[dict]:
    """
    Parse thermo rows from a LAMMPS log containing lines like:

    Step Temp PotEng KinEng TotEng Press Volume
    0    300  ...    ...    ...    ...   ...
    """
    if not log_path.exists():
        return []

    rows: List[dict] = []
    header_re = re.compile(r"^\s*Step\s+Temp\s+")
    numeric_re = re.compile(r"^\s*[-+0-9.eE]+\s+")

    in_table = False

    with open(log_path, "r", errors="replace") as f:
        for line in f:
            stripped = line.strip()

            if header_re.match(stripped):
                in_table = True
                continue

            if in_table:
                if not stripped:
                    in_table = False
                    continue
                if stripped.startswith("Loop time of"):
                    in_table = False
                    continue
                if not numeric_re.match(stripped):
                    continue

                parts = stripped.split()
                if len(parts) < 7:
                    continue

                try:
                    step = int(float(parts[0]))
                    temp = float(parts[1])
                    pe = float(parts[2])
                    ke = float(parts[3])
                    etot = float(parts[4])
                    press_bar = float(parts[5])
                    vol = float(parts[6])
                except Exception:
                    continue

                rows.append({
                    "step": step,
                    "temperature_K": temp,
                    "potential_energy_eV": pe,
                    "kinetic_energy_eV": ke,
                    "total_energy_eV": etot,
                    "pressure_bar": press_bar,
                    "pressure_GPa": press_bar * BAR_TO_GPA,
                    "volume_A3": vol,
                })

    return rows


def write_stage_csv(rows: List[dict], csv_path: Path):
    if not rows:
        return

    fieldnames = [
        "step",
        "temperature_K",
        "potential_energy_eV",
        "kinetic_energy_eV",
        "total_energy_eV",
        "pressure_bar",
        "pressure_GPa",
        "volume_A3",
        "time_ps",
    ]

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_view_log(rows: List[dict], view_log_path: Path):
    if not rows:
        return

    with open(view_log_path, "w") as f:
        f.write("# step time_ps temperature_K potential_energy_eV kinetic_energy_eV total_energy_eV pressure_bar pressure_GPa volume_A3\n")
        for r in rows:
            f.write(
                f"{r['step']:>10d} "
                f"{r.get('time_ps', float('nan')):>12.6f} "
                f"{r['temperature_K']:>12.6f} "
                f"{r['potential_energy_eV']:>16.8f} "
                f"{r['kinetic_energy_eV']:>16.8f} "
                f"{r['total_energy_eV']:>16.8f} "
                f"{r['pressure_bar']:>14.6f} "
                f"{r['pressure_GPa']:>14.6f} "
                f"{r['volume_A3']:>14.6f}\n"
            )


def final_thermo_values(rows: List[dict]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if not rows:
        return None, None, None
    last = rows[-1]
    return (
        last.get("temperature_K"),
        last.get("pressure_GPa"),
        last.get("volume_A3"),
    )


# =============================================================================
# Dump reading / optional PDB conversion
# =============================================================================

def read_lammps_dump_frames(dump_path: Path) -> List[Atoms]:
    """
    Read all frames from a LAMMPS custom dump using ASE.
    The dump is expected to contain:
        id type element x y z
    """
    if not dump_path.exists():
        return []

    try:
        frames = read(str(dump_path), index=":", format="lammps-dump-text")
    except Exception as e:
        raise RuntimeError(f"Failed to read LAMMPS dump {dump_path}: {e}")

    if isinstance(frames, Atoms):
        frames = [frames]

    return list(frames)


def convert_dump_to_pdb(
    dump_path: Path,
    traj_pdb_path: Path,
    last_frame_path: Path,
) -> Atoms:
    """
    Convert LAMMPS dump -> multi-frame PDB + last-frame PDB.
    Returns the final frame.
    """
    frames = read_lammps_dump_frames(dump_path)
    if not frames:
        raise RuntimeError(f"No frames found in dump file: {dump_path}")

    write(str(traj_pdb_path), frames)
    write(str(last_frame_path), frames[-1])
    return frames[-1]


# =============================================================================
# Plot helpers (optional, delegated to md_common if available)
# =============================================================================

def maybe_plot_temp(csv_path: Path, temp: float, title: str, plot_path: Path):
    try:
        ok = plot_temp_vs_time(csv_path, temp, title, plot_path)
        return bool(ok)
    except Exception:
        return False


def maybe_plot_volume(csv_path: Path, title: str, plot_path: Path, initial_volume: Optional[float] = None):
    try:
        ok = plot_volume_vs_time(csv_path, title, plot_path, initial_volume=initial_volume)
        return bool(ok)
    except Exception:
        return False


# =============================================================================
# Core stage runner
# =============================================================================

def _run_lammps_stage(
    *,
    input_text: str,
    stage_dir: Path,
    input_filename: str,
    log_filename: str,
    dump_filename: str,
    traj_name: str,
    last_frame_name: str,
    csv_name: str,
    view_log_name: str,
    state_name: str,
    lammps_bin: Optional[str],
    timestep_fs: float = 0.5,
    save_trajectory_pdb: bool = False,
) -> Tuple[Atoms, float, List[dict], Path]:
    """
    Internal generic stage runner.
    Returns:
        atoms_out, elapsed_seconds, thermo_rows, dump_path

    By default, only the raw LAMMPS dump (.lammpstrj), the thermo CSV, and the
    plain-text view log are kept. The multi-frame trajectory.pdb and
    last-frame-of-trajectory.pdb files are NOT written unless
    save_trajectory_pdb=True is passed.
    """
    stage_dir.mkdir(parents=True, exist_ok=True)

    input_path = stage_dir / input_filename
    log_path = stage_dir / log_filename
    dump_path = stage_dir / dump_filename
    traj_path = stage_dir / traj_name
    last_frame_path = stage_dir / last_frame_name
    csv_path = stage_dir / csv_name
    view_log_path = stage_dir / view_log_name
    state_path = stage_dir / state_name

    with open(input_path, "w") as f:
        f.write(input_text)

    state = load_stage_state(state_path)
    state["status"] = "running"
    save_stage_state(state_path, state)

    cmd = build_lammps_command(input_path, log_path, lammps_bin=lammps_bin)

    print(f"    ▶ Running LAMMPS in {stage_dir}")
    print(f"    Command: {' '.join(cmd)}")

    t0 = time.time()
    subprocess.run(cmd, cwd=str(stage_dir), check=True)
    elapsed = time.time() - t0

    rows = parse_lammps_log(log_path)
    timestep_ps = timestep_fs / 1000.0
    for r in rows:
        r["time_ps"] = r["step"] * timestep_ps
    write_stage_csv(rows, csv_path)
    write_view_log(rows, view_log_path)

    frames = read_lammps_dump_frames(dump_path)
    if not frames:
        raise RuntimeError(f"No frames found in dump file: {dump_path}")
    atoms_out = frames[-1]

    if save_trajectory_pdb:
        write(str(traj_path), frames)
        write(str(last_frame_path), atoms_out)
        print(f"    💾 Saved trajectory: {traj_path}")
        print(f"    💾 Saved last frame: {last_frame_path}")

    print(f"    💾 Saved log CSV:    {csv_path}")
    print(f"    💾 Saved view log:   {view_log_path}")

    return atoms_out, elapsed, rows, dump_path


# =============================================================================
# Public stage runners
# =============================================================================

def _read_last_frame_for_resume(last_frame_path: Path, dump_path: Path) -> Atoms:
    """
    Get the final-frame Atoms for a stage that's already marked completed.
    Prefers last_frame_path (if it was saved with save_pdb=True), otherwise
    falls back to reading the last frame straight out of the raw .lammpstrj
    dump.
    """
    if last_frame_path.exists():
        return read(str(last_frame_path))

    frames = read_lammps_dump_frames(dump_path)
    if not frames:
        raise FileNotFoundError(
            f"Cannot resume completed stage: neither {last_frame_path} "
            f"nor dump {dump_path} contain any frames."
        )
    return frames[-1]


def _read_reference_atoms_for_continuation(read_restart_path: Path) -> Atoms:
    """
    Get an Atoms object (with the correct cell) for the final frame of the
    stage that wrote read_restart_path. Used where more than just the
    element order is needed.
    """
    stage_dir = read_restart_path.parent
    last_frame_path = stage_dir / LAST_FRAME_PDB
    if last_frame_path.exists():
        return read(str(last_frame_path))

    for candidate in ("state.json", "minimisation.state.json"):
        state_file = stage_dir / candidate
        if state_file.exists():
            state = load_stage_state(state_file)
            dump_file = state.get("dump_file")
            if dump_file:
                frames = read_lammps_dump_frames(stage_dir / dump_file)
                if frames:
                    return frames[-1]

    raise FileNotFoundError(
        f"Could not find a reference structure (last-frame pdb or dump) "
        f"next to {read_restart_path} to continue from."
    )


def _infer_element_order_from_prior_stage(read_restart_path: Path) -> List[str]:
    """
    Look up the element order saved in a prior stage's state.json (or
    minimisation.state.json), so we don't need to read a last-frame pdb
    just to know the element ordering for pair_coeff/dump_modify.
    """
    stage_dir = read_restart_path.parent
    for candidate in ("state.json", "minimisation.state.json"):
        state_file = stage_dir / candidate
        if state_file.exists():
            state = load_stage_state(state_file)
            elems = state.get("element_order")
            if elems:
                return list(elems)

    prev_last_frame = stage_dir / LAST_FRAME_PDB
    if prev_last_frame.exists():
        ref_atoms = read(str(prev_last_frame))
        element_order, _ = build_symbol_type_mapping(ref_atoms)
        return element_order

    raise FileNotFoundError(
        f"Could not infer element order for restart-based stage: no "
        f"state.json with 'element_order' (and no last-frame pdb) found "
        f"next to {read_restart_path}"
    )


def run_minimisation_stage(
    *,
    atoms: Atoms,
    stage_dir: Path,
    model_path: str,
    lammps_bin: Optional[str] = None,
    timestep_fs: float = 0.5,
    save_pdb: bool = False,
) -> dict:
    """
    Run minimisation stage.

    Starts from:
        read_data starting_structure.lammps

    By default trajectory.pdb / last-frame-of-trajectory.pdb are NOT written
    (pass save_pdb=True to keep them). The raw minimisation.lammpstrj dump,
    minimisation.csv, and minimisation.view.log are always written.
    """
    stage_dir.mkdir(parents=True, exist_ok=True)

    state_path = stage_dir / "minimisation.state.json"
    restart_path = stage_dir / "minimisation.restart"
    dump_path = stage_dir / "minimisation.lammpstrj"
    traj_path = stage_dir / TRAJ_PDB
    last_frame_path = stage_dir / LAST_FRAME_PDB
    csv_path = stage_dir / "minimisation.csv"
    view_log_path = stage_dir / MIN_VIEW_LOG

    state = load_stage_state(state_path)
    if state.get("status") == "completed" and restart_path.exists():
        print(f"    ↪ Minimisation already completed; loading from {stage_dir}")
        atoms_out = _read_last_frame_for_resume(last_frame_path, dump_path)
        return {
            "atoms": atoms_out,
            "elapsed_s": state.get("elapsed_seconds", 0.0),
            "restart_path": restart_path,
            "traj_path": traj_path,
            "last_frame_path": last_frame_path,
            "csv_path": csv_path,
            "view_log_path": view_log_path,
            "state_path": state_path,
            "final_temperature_K": state.get("final_temperature_K"),
            "final_pressure_GPa": state.get("final_pressure_GPa"),
            "final_volume_A3": state.get("final_volume_A3"),
        }

    model_pt = ensure_mliap_model(model_path)

    data_path = stage_dir / "starting_structure.lammps"
    element_order, _ = write_lammps_structure(atoms, data_path)

    input_text = build_minimisation_input(
        data_filename=data_path.name,
        model_pt=model_pt,
        element_order=element_order,
        output_dump="minimisation.lammpstrj",
        output_data="minimised_structure.lammps",
        output_restart=restart_path.name,
        timestep_fs=timestep_fs,
    )

    atoms_out, elapsed, rows, _ = _run_lammps_stage(
        input_text=input_text,
        stage_dir=stage_dir,
        input_filename="minimisation.in",
        log_filename="log.lammps",
        dump_filename="minimisation.lammpstrj",
        traj_name=TRAJ_PDB,
        last_frame_name=LAST_FRAME_PDB,
        csv_name="minimisation.csv",
        view_log_name=MIN_VIEW_LOG,
        state_name="minimisation.state.json",
        lammps_bin=lammps_bin,
        timestep_fs=timestep_fs,
        save_trajectory_pdb=save_pdb,
    )

    final_T, final_P, final_V = final_thermo_values(rows)
    if final_V is None:
        final_V = atoms_out.get_volume()

    state.update({
        "stage": "Minimisation",
        "status": "completed",
        "elapsed_seconds": elapsed,
        "completed_steps": 1,
        "target_steps": 1,
        "final_temperature_K": final_T,
        "final_pressure_GPa": final_P,
        "final_volume_A3": final_V,
        "restart_file": restart_path.name,
        "trajectory_file": traj_path.name,
        "last_frame_file": last_frame_path.name,
        "csv_file": csv_path.name,
        "view_log_file": view_log_path.name,
        "dump_file": "minimisation.lammpstrj",
        "element_order": list(element_order),
    })
    save_stage_state(state_path, state)

    print(f"    ✅ Minimisation done: {elapsed:.0f}s | Final V={final_V:.1f} Å³")

    return {
        "atoms": atoms_out,
        "elapsed_s": elapsed,
        "restart_path": restart_path,
        "traj_path": traj_path,
        "last_frame_path": last_frame_path,
        "csv_path": csv_path,
        "view_log_path": view_log_path,
        "state_path": state_path,
        "final_temperature_K": final_T,
        "final_pressure_GPa": final_P,
        "final_volume_A3": final_V,
    }


def run_nvt_stage(
    *,
    stage_dir: Path,
    model_path: str,
    temp_K: float,
    nsteps: int,
    stage_label: str,
    init_velocities: bool,
    traj_name: str,
    view_log_name: str,
    timestep_fs: float = 0.5,
    lammps_bin: Optional[str] = None,
    input_atoms: Optional[Atoms] = None,
    read_restart_path: Optional[Path] = None,
    save_pdb: bool = False,
    restart_every_steps: int = 100,
    resume_mode: str = "reuse",
) -> dict:
    """
    Run an NVT stage.

    Start mode:
      A) from input_atoms -> writes starting_structure.lammps + read_data
      B) from read_restart_path -> uses read_restart
      C) if this stage already completed and is shorter than requested,
         continue from this stage's own restart file
    """
    stage_dir.mkdir(parents=True, exist_ok=True)

    state_path = stage_dir / "state.json"
    traj_path = stage_dir / traj_name
    last_frame_path = stage_dir / LAST_FRAME_PDB
    label_lower = stage_label.lower().replace(" ", "_")
    csv_path = stage_dir / f"{label_lower}.csv"
    restart_path = stage_dir / f"{label_lower}.restart"
    dump_path = stage_dir / f"{label_lower}.lammpstrj"
    view_log_path = stage_dir / view_log_name

    state = load_stage_state(state_path)

    # Reuse completed stage if it already satisfies the request
    if (
        resume_mode == "reuse"
        and state.get("status") == "completed"
        and restart_path.exists()
        and int(state.get("completed_steps", 0)) >= int(nsteps)
    ):
        print(f"    ↪ {stage_label} already completed; loading from {stage_dir}")
        atoms_out = _read_last_frame_for_resume(last_frame_path, dump_path)
        return {
            "atoms": atoms_out,
            "elapsed_s": state.get("elapsed_seconds", 0.0),
            "restart_path": restart_path,
            "traj_path": traj_path,
            "last_frame_path": last_frame_path,
            "csv_path": csv_path,
            "view_log_path": view_log_path,
            "state_path": state_path,
            "final_temperature_K": state.get("final_temperature_K"),
            "final_pressure_GPa": state.get("final_pressure_GPa"),
            "final_volume_A3": state.get("final_volume_A3"),
        }

    if (input_atoms is None) == (read_restart_path is None):
        raise ValueError("Provide exactly one of input_atoms or read_restart_path to run_nvt_stage()")

    model_pt = ensure_mliap_model(model_path)

    read_data_file = None
    read_restart_file = None

    if input_atoms is not None:
        data_path = stage_dir / "starting_structure.lammps"
        element_order, _ = write_lammps_structure(input_atoms, data_path)
        read_data_file = data_path.name
    else:
        if not read_restart_path.exists():
            raise FileNotFoundError(f"Restart file not found: {read_restart_path}")
        element_order = _infer_element_order_from_prior_stage(read_restart_path)
        read_restart_file = str(read_restart_path.resolve())

    input_text = build_nvt_input(
        model_pt=model_pt,
        element_order=element_order,
        temp_K=temp_K,
        nsteps=nsteps,
        stage_label=stage_label,
        output_dump=f"{label_lower}.lammpstrj",
        output_data=f"{label_lower}.lammps",
        output_restart=restart_path.name,
        timestep_fs=timestep_fs,
        init_velocities=init_velocities,
        read_data_file=read_data_file,
        read_restart_file=read_restart_file,
        restart_every_steps=restart_every_steps,
    )

    atoms_out, elapsed, rows, _ = _run_lammps_stage(
        input_text=input_text,
        stage_dir=stage_dir,
        input_filename=f"{label_lower}.in",
        log_filename="log.lammps",
        dump_filename=f"{label_lower}.lammpstrj",
        traj_name=traj_name,
        last_frame_name=LAST_FRAME_PDB,
        csv_name=f"{label_lower}.csv",
        view_log_name=view_log_name,
        state_name="state.json",
        lammps_bin=lammps_bin,
        timestep_fs=timestep_fs,
        save_trajectory_pdb=save_pdb,
    )

    final_T, final_P, final_V = final_thermo_values(rows)
    if final_V is None:
        final_V = atoms_out.get_volume()

    state.update({
        "stage": stage_label,
        "temperature_K": temp_K,
        "status": "completed",
        "elapsed_seconds": elapsed,
        "completed_steps": nsteps,
        "target_steps": nsteps,
        "final_temperature_K": final_T,
        "final_pressure_GPa": final_P,
        "final_volume_A3": final_V,
        "restart_file": restart_path.name,
        "trajectory_file": traj_path.name,
        "last_frame_file": last_frame_path.name,
        "csv_file": csv_path.name,
        "view_log_file": view_log_path.name,
        "dump_file": f"{label_lower}.lammpstrj",
        "element_order": list(element_order),
    })
    save_stage_state(state_path, state)

    print(
        f"    ✅ {stage_label} done: {elapsed:.0f}s | "
        f"Final T={(final_T if final_T is not None else float('nan')):.1f} K | "
        f"Final V={final_V:.1f} Å³"
    )

    if csv_path.exists():
        plot_path = stage_dir / f"{label_lower}_temp.png"
        saved = maybe_plot_temp(
            csv_path,
            temp_K,
            f"{stage_label} — Temperature vs Time ({temp_K:g} K)",
            plot_path,
        )
        if saved:
            print(f"    💾 Saved plot: {plot_path}")

    return {
        "atoms": atoms_out,
        "elapsed_s": elapsed,
        "restart_path": restart_path,
        "traj_path": traj_path,
        "last_frame_path": last_frame_path,
        "csv_path": csv_path,
        "view_log_path": view_log_path,
        "state_path": state_path,
        "final_temperature_K": final_T,
        "final_pressure_GPa": final_P,
        "final_volume_A3": final_V,
    }


def run_npt_stage(
    *,
    stage_dir: Path,
    model_path: str,
    temp_K: float,
    pressure_GPa: float,
    nsteps: int,
    stage_label: str,
    init_velocities: bool,
    traj_name: str,
    view_log_name: str,
    timestep_fs: float = 0.5,
    lammps_bin: Optional[str] = None,
    input_atoms: Optional[Atoms] = None,
    read_restart_path: Optional[Path] = None,
    save_pdb: bool = False,
    restart_every_steps: int = 100,
    resume_mode: str = "reuse",
) -> dict:
    """
    Run an NPT stage.

    Start mode:
      A) from input_atoms -> writes starting_structure.lammps + read_data
      B) from read_restart_path -> uses read_restart
    """
    stage_dir.mkdir(parents=True, exist_ok=True)

    state_path = stage_dir / "state.json"
    traj_path = stage_dir / traj_name
    last_frame_path = stage_dir / LAST_FRAME_PDB
    label_lower = stage_label.lower().replace(" ", "_")
    csv_path = stage_dir / f"{label_lower}.csv"
    restart_path = stage_dir / f"{label_lower}.restart"
    dump_path = stage_dir / f"{label_lower}.lammpstrj"
    view_log_path = stage_dir / view_log_name

    state = load_stage_state(state_path)

    if (
        resume_mode == "reuse"
        and state.get("status") == "completed"
        and restart_path.exists()
        and int(state.get("completed_steps", 0)) >= int(nsteps)
    ):
        print(f"    ↪ {stage_label} already completed; loading from {stage_dir}")
        atoms_out = _read_last_frame_for_resume(last_frame_path, dump_path)
        return {
            "atoms": atoms_out,
            "elapsed_s": state.get("elapsed_seconds", 0.0),
            "restart_path": restart_path,
            "traj_path": traj_path,
            "last_frame_path": last_frame_path,
            "csv_path": csv_path,
            "view_log_path": view_log_path,
            "state_path": state_path,
            "final_temperature_K": state.get("final_temperature_K"),
            "final_pressure_GPa": state.get("final_pressure_GPa"),
            "final_volume_A3": state.get("final_volume_A3"),
        }

    if (input_atoms is None) == (read_restart_path is None):
        raise ValueError("Provide exactly one of input_atoms or read_restart_path to run_npt_stage()")

    model_pt = ensure_mliap_model(model_path)

    read_data_file = None
    read_restart_file = None
    initial_volume = None

    if input_atoms is not None:
        data_path = stage_dir / "starting_structure.lammps"
        initial_volume = input_atoms.get_volume()
        element_order, _ = write_lammps_structure(input_atoms, data_path)
        read_data_file = data_path.name
    else:
        if not read_restart_path.exists():
            raise FileNotFoundError(f"Restart file not found: {read_restart_path}")
        ref_atoms = _read_reference_atoms_for_continuation(read_restart_path)
        initial_volume = ref_atoms.get_volume()
        element_order = _infer_element_order_from_prior_stage(read_restart_path)
        read_restart_file = str(read_restart_path.resolve())

    input_text = build_npt_input(
        model_pt=model_pt,
        element_order=element_order,
        temp_K=temp_K,
        pressure_GPa=pressure_GPa,
        nsteps=nsteps,
        stage_label=stage_label,
        output_dump=f"{label_lower}.lammpstrj",
        output_data=f"{label_lower}.lammps",
        output_restart=restart_path.name,
        timestep_fs=timestep_fs,
        init_velocities=init_velocities,
        read_data_file=read_data_file,
        read_restart_file=read_restart_file,
        restart_every_steps=restart_every_steps,
    )

    atoms_out, elapsed, rows, _ = _run_lammps_stage(
        input_text=input_text,
        stage_dir=stage_dir,
        input_filename=f"{label_lower}.in",
        log_filename="log.lammps",
        dump_filename=f"{label_lower}.lammpstrj",
        traj_name=traj_name,
        last_frame_name=LAST_FRAME_PDB,
        csv_name=f"{label_lower}.csv",
        view_log_name=view_log_name,
        state_name="state.json",
        lammps_bin=lammps_bin,
        timestep_fs=timestep_fs,
        save_trajectory_pdb=save_pdb,
    )

    final_T, final_P, final_V = final_thermo_values(rows)
    if final_V is None:
        final_V = atoms_out.get_volume()

    state.update({
        "stage": stage_label,
        "temperature_K": temp_K,
        "pressure_GPa": pressure_GPa,
        "status": "completed",
        "elapsed_seconds": elapsed,
        "completed_steps": nsteps,
        "target_steps": nsteps,
        "final_temperature_K": final_T,
        "final_pressure_GPa": final_P,
        "final_volume_A3": final_V,
        "restart_file": restart_path.name,
        "trajectory_file": traj_path.name,
        "last_frame_file": last_frame_path.name,
        "csv_file": csv_path.name,
        "view_log_file": view_log_path.name,
        "dump_file": f"{label_lower}.lammpstrj",
        "element_order": list(element_order),
    })
    save_stage_state(state_path, state)

    print(
        f"    ✅ {stage_label} done: {elapsed:.0f}s | "
        f"Final T={(final_T if final_T is not None else float('nan')):.1f} K | "
        f"Final V={final_V:.1f} Å³"
    )

    if csv_path.exists():
        plot_path = stage_dir / f"{label_lower}_volume.png"
        saved = maybe_plot_volume(
            csv_path,
            f"{stage_label} — Volume vs Time ({temp_K:g} K, {pressure_GPa / BAR_TO_GPA:.1f} bar)",
            plot_path,
            initial_volume=initial_volume,
        )
        if saved:
            print(f"    💾 Saved plot: {plot_path}")

    return {
        "atoms": atoms_out,
        "elapsed_s": elapsed,
        "restart_path": restart_path,
        "traj_path": traj_path,
        "last_frame_path": last_frame_path,
        "csv_path": csv_path,
        "view_log_path": view_log_path,
        "state_path": state_path,
        "final_temperature_K": final_T,
        "final_pressure_GPa": final_P,
        "final_volume_A3": final_V,
    }# =============================================================================
# Helpers
# =============================================================================

def _format_temp_dir(temp: float) -> str:
    """300 -> 300K ; 300.5 -> 300.5K"""
    if abs(temp - round(temp)) < 1e-9:
        return f"{int(round(temp))}K"
    return f"{temp:g}K"


def _slugify(name: str) -> str:
    """'Glycine Anhydrous' -> 'glycine-anhydrous' (safe for folder names)."""
    out = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip()).strip("-").lower()
    return out or "molecule"


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
    result = generate_supercell(pmc_id, size=supercell_size)

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
    """
    Run rdf_analysis.py on the production trajectory if available.
    This is optional and non-fatal.
    """
    traj_path = production_dir / PROD_TRAJ_PDB
    if not traj_path.exists():
        print(f"  ⚠️ RDF skipped: production trajectory not found: {traj_path}")
        return

    try:
        import rdf_analysis as ra

        # Try a few possible API names
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
    eq_steps: int,
    prod_steps: int,
    timestep_fs: float,
    lammps_bin: Optional[str],
    skip_minimisation: bool,
    run_rdf_after: bool,
    rdf_bins: int,
    rdf_rmax: Optional[float],
    save_pdb: bool,
    restart_every_steps: int,
    resume_policy: str,
):
    """
    Full workflow for one temperature:
        1) minimisation
        2) NVT equilibration
        3) NVT production
        4) optional RDF
    """
    temp_dir_name = _format_temp_dir(temp_K)

    # Match ASE-style results layout
    min_dir = results_root / "01_minimisation"
    eq_dir = results_root / "02_nvt_equilibration" / temp_dir_name
    prod_dir = results_root / "03_nvt_production" / temp_dir_name

    # If overwrite is requested, wipe NVT stage outputs so they rerun cleanly.
    # Minimisation is left alone here unless you explicitly remove it or use
    # --skip-minimisation logic differently.
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
        min_last = min_dir / LAST_FRAME_PDB

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
        min_result = run_minimisation_stage(
            atoms=starting_atoms,
            stage_dir=min_dir,
            model_path=model,
            lammps_bin=lammps_bin,
            timestep_fs=timestep_fs,
            save_pdb=save_pdb,
        )

    # -------------------------------------------------------------------------
    # 2) NVT equilibration
    # -------------------------------------------------------------------------
    eq_ps = eq_steps * timestep_fs / 1000.0
    print_stage_header(
        f"{pmc_id} | Stage 2/3: NVT Equilibration @ {temp_K:g} K "
        f"({eq_steps} steps = {eq_ps:g} ps)"
    )

    eq_result = run_nvt_stage(
        stage_dir=eq_dir,
        model_path=model,
        temp_K=temp_K,
        nsteps=eq_steps,
        stage_label="NVT Equilibration",
        init_velocities=True,
        traj_name=TRAJ_PDB,
        view_log_name=EQ_VIEW_LOG,
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
    prod_ps = prod_steps * timestep_fs / 1000.0
    print_stage_header(
        f"{pmc_id} | Stage 3/3: NVT Production @ {temp_K:g} K "
        f"({prod_steps} steps = {prod_ps:g} ps)"
    )

    prod_result = run_nvt_stage(
        stage_dir=prod_dir,
        model_path=model,
        temp_K=temp_K,
        nsteps=prod_steps,
        stage_label="NVT Production",
        init_velocities=False,
        traj_name=PROD_TRAJ_PDB,
        view_log_name=PROD_VIEW_LOG,
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
        maybe_run_rdf(
            production_dir=prod_dir,
            rdf_bins=rdf_bins,
            rdf_rmax=rdf_rmax,
        )

    print_stage_header(f"{pmc_id} | Finished {temp_K:g} K")
    print(f"  Final production structure volume: {prod_result['final_volume_A3']:.3f} Å³")
    print(f"  Production trajectory: {prod_result['traj_path']}")


# =============================================================================
# CLI
# =============================================================================

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run NVT MD using LAMMPS + MACE for a PMC crystal."
    )

    # Core system settings
    p.add_argument(
        "--pmc",
        required=True,
        help=(
            "PMC ID (e.g. PMC-001) OR a molecule name (e.g. 'Glycine') matched "
            f"against the .json metadata under {DATA_DIR}. Either works."
        ),
    )
    p.add_argument(
        "--temps",
        required=True,
        nargs="+",
        type=float,
        help="Temperature(s) in K, e.g. --temps 300 350 400",
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
            "<outdir>/NVT_MACE_runs/<PMC_ID[_molecule]>/<MODEL>/NVT_results. "
            "Defaults to the CURRENT WORKING DIRECTORY (i.e. wherever you run "
            "this script from). Pass a path to override, e.g. --outdir /scratch/runs"
        ),
    )

    # MD durations — give EITHER ps OR raw step count, per stage.
    # Steps take precedence if both happen to be given for the same stage.
    eq_group = p.add_mutually_exclusive_group()
    eq_group.add_argument(
        "--eq-ps",
        type=float,
        default=None,
        help="NVT equilibration duration in ps (default: 10 ps, if --eq-steps not given)",
    )
    eq_group.add_argument(
        "--eq-steps",
        type=int,
        default=None,
        help=(
            "NVT equilibration duration as a raw step count instead of ps "
            "(useful for quick/diverse test runs, independent of --timestep-fs). "
            "Overrides --eq-ps."
        ),
    )
    prod_group = p.add_mutually_exclusive_group()
    prod_group.add_argument(
        "--prod-ps",
        type=float,
        default=None,
        help="NVT production duration in ps (default: 1000 ps = 1 ns, if --prod-steps not given)",
    )
    prod_group.add_argument(
        "--prod-steps",
        type=int,
        default=None,
        help=(
            "NVT production duration as a raw step count instead of ps "
            "(useful for quick/diverse test runs, independent of --timestep-fs). "
            "Overrides --prod-ps."
        ),
    )
    p.add_argument(
        "--timestep-fs",
        type=float,
        default=0.5,
        help="LAMMPS timestep in fs (default: 0.5)",
    )

    # Execution / environment
    p.add_argument(
        "--lammps-bin",
        default=None,
        help=(
            "Path to lmp executable. If omitted, resolved (after sourcing "
            "env.sh -- see --env-script) via $LAMMPS_BIN, "
            "$LAMMPS_INSTALL/bin/lmp, an auto-detected build under $HOME, "
            "then finally 'lmp' on PATH."
        ),
    )
    p.add_argument(
        "--env-script",
        default=None,
        help=(
            "Shell script to `source` before every LAMMPS invocation (sets "
            "$LAMMPS_INSTALL, activates the matching MACE conda env, fixes "
            "up LD_LIBRARY_PATH/PYTHONPATH, etc.) -- the same script your "
            "PBS jobs source before calling lmp. You no longer need to "
            f"source this yourself. Default: {_DEFAULT_LAMMPS_ENV_SCRIPT} "
            "(used automatically if it exists). Equivalent to exporting "
            "LAMMPS_ENV_SCRIPT yourself."
        ),
    )
    p.add_argument(
        "--no-env-script",
        action="store_true",
        help=(
            "Disable automatic env.sh sourcing entirely and resolve the "
            "LAMMPS binary purely from the current shell's environment "
            "(old behavior). Equivalent to exporting LAMMPS_NO_ENV_SCRIPT=1."
        ),
    )
    p.add_argument(
        "--gpus",
        type=int,
        default=None,
        help=(
            "Number of GPUs for Kokkos LAMMPS (the '-k on g N' flag). "
            "Default: 1. Kokkos/GPU mode is ON by default -- see --no-kokkos "
            "to disable it. Equivalent to exporting LAMMPS_GPUS yourself."
        ),
    )
    p.add_argument(
        "--no-kokkos",
        action="store_true",
        help=(
            "Run plain CPU LAMMPS (no '-k on -sf kk -pk kokkos ...' flags) "
            "instead of the default Kokkos/GPU mode. Use this when running "
            "on a login node or a node with no GPU allocated -- note that "
            "MACE's message-passing LAMMPS coupling (forward_exchange) "
            "currently REQUIRES the Kokkos build, so plain CPU mode will "
            "fail for MACE models that use LAMMPS_MP. Equivalent to "
            "exporting LAMMPS_USE_KOKKOS=0."
        ),
    )
    p.add_argument(
        "--mace-env",
        default=None,
        help=(
            "Name of a conda env (under ~/.conda/envs, ~/miniconda3/envs, etc.) "
            "to use as the Python interpreter for MACE model conversion, e.g. "
            "--mace-env py311. Equivalent to exporting MACE_PYTHON yourself. "
            "If omitted, the script auto-detects a MACE-capable conda env."
        ),
    )
    p.add_argument(
        "--model-dir",
        default=None,
        help=(
            "Folder where small/medium/large MACE-OFF23 .model aliases live, "
            f"e.g. --model-dir ~/himesh_work/mace_models. Default: {_DEFAULT_MODEL_DIR}. "
            "Not needed if you pass --model as a full path instead of an alias. "
            "Equivalent to exporting MACE_MODEL_DIR yourself."
        ),
    )

    # Workflow switches
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
            "Also write trajectory.pdb / last-frame-of-trajectory.pdb for every "
            "stage (minimisation, equilibration, production). Off by default: "
            "the raw .lammpstrj dump, .csv, and view log are always written and "
            "are enough for restart continuity and Time-vs-Temperature plots, "
            "so these pdb files are usually unnecessary extra output."
        ),
    )
    p.add_argument(
        "--restart-every",
        type=int,
        default=100,
        help=(
            "Steps between intermediate LAMMPS restart checkpoints written during "
            "each NVT/NPT stage (the 'restart N file.a file.b' command), separate "
            "from the single write_restart at the end of the stage. These "
            "checkpoints alternate between two fixed filenames (file.a / file.b) "
            "so disk usage stays constant -- LAMMPS does NOT create a new "
            "numbered file every interval. Default: 100. Use e.g. 50 for more "
            "frequent checkpoints, or a larger value to write less often."
        ),
    )
    p.add_argument(
        "--resume-policy",
        choices=["reuse", "overwrite"],
        default="reuse",
        help=(
            "How to handle existing stage outputs for the same PMC/model/temperature. "
            "'reuse' = keep completed stages as-is if they already match the requested length, "
            "or continue shorter completed equilibration/production runs up to the requested length; "
            "'overwrite' = rerun equilibration/production stages from scratch and replace existing outputs."
        ),
    )

    # RDF knobs
    p.add_argument("--rdf-bins", type=int, default=300, help="RDF bins (default: 300)")
    p.add_argument("--rdf-rmax", type=float, default=None, help="Optional RDF rmax in Å")

    return p


def main():
    args = build_parser().parse_args()

    # ---- Environment setup (before anything touches MACE/LAMMPS) ----------
    if args.model_dir:
        os.environ["MACE_MODEL_DIR"] = str(Path(args.model_dir).expanduser().resolve())

    if args.mace_env:
        resolved = _conda_env_python(args.mace_env)
        if not resolved:
            searched = ", ".join(str(d) for d in _conda_envs_root_candidates()) or "(no conda envs dirs found)"
            raise FileNotFoundError(
                f"--mace-env '{args.mace_env}' not found. Searched: {searched}"
            )
        os.environ["MACE_PYTHON"] = str(resolved)

    if args.no_env_script:
        os.environ["LAMMPS_NO_ENV_SCRIPT"] = "1"
    elif args.env_script:
        os.environ["LAMMPS_ENV_SCRIPT"] = str(Path(args.env_script).expanduser().resolve())

    # Kokkos/GPU mode is ON by default (matches the PBS-job style invocation:
    # -k on g N -sf kk -pk kokkos newton on neigh half). This is required by
    # MACE's LAMMPS_MP message-passing coupling (forward_exchange), which is
    # only implemented in the Kokkos build of ML-IAP. --no-kokkos or an
    # existing $LAMMPS_USE_KOKKOS in the shell both take precedence, so you
    # can still opt out (e.g. on a login/CPU-only node).
    if args.no_kokkos:
        os.environ["LAMMPS_USE_KOKKOS"] = "0"
    elif "LAMMPS_USE_KOKKOS" not in os.environ:
        os.environ["LAMMPS_USE_KOKKOS"] = "1"

    if args.gpus is not None:
        os.environ["LAMMPS_GPUS"] = str(args.gpus)
    elif "LAMMPS_GPUS" not in os.environ:
        os.environ["LAMMPS_GPUS"] = "1"

    # Resolved once up front purely so it can be printed for the user; the
    # actual per-run sourcing happens fresh inside build_lammps_command()
    # for every LAMMPS subprocess.
    env_script_resolved = resolve_env_script(args.env_script)

    # ---- Resolve --pmc (accepts a PMC ID OR a molecule name) --------------
    pmc_id, molecule_name = resolve_pmc_id(args.pmc)
    temps: List[float] = list(args.temps)

    # ---- Resolve MD durations: steps take precedence over ps if given -----
    if args.eq_steps is not None:
        eq_steps = int(args.eq_steps)
    else:
        eq_steps = _steps_from_ps(args.eq_ps if args.eq_ps is not None else 10.0, args.timestep_fs)

    if args.prod_steps is not None:
        prod_steps = int(args.prod_steps)
    else:
        prod_steps = _steps_from_ps(args.prod_ps if args.prod_ps is not None else 1000.0, args.timestep_fs)

    # ---- Output directory: clean, composed, understandable -----------------
    # <outdir or CWD>/NVT_MACE_runs/<PMC_ID[_molecule-slug]>/<model_tag>/NVT_results/...
    outdir_base = Path(args.outdir).resolve() if args.outdir else Path.cwd()

    molecule_folder = pmc_id if not molecule_name else f"{pmc_id}_{_slugify(molecule_name)}"

    # Make result directories model-specific so small/medium/large runs do not collide.
    # If --model is a path, use the file stem as the folder tag.
    model_arg = str(args.model)
    model_tag = Path(model_arg).stem if any(sep in model_arg for sep in ("/", "\\")) else model_arg
    model_tag = model_tag.replace(" ", "_")

    results_root = outdir_base / "NVT_MACE_runs" / molecule_folder / model_tag / "NVT_results"
    results_root.mkdir(parents=True, exist_ok=True)

    # ---- Resolve execution environment up front (so it's visible/auditable) ----
    if env_script_resolved and not args.lammps_bin and not os.environ.get("LAMMPS_BIN"):
        lammps_bin_display = (
            f"(resolved at run-time after sourcing {env_script_resolved}, "
            f"via $LAMMPS_INSTALL/bin/lmp)"
        )
    else:
        lammps_bin_display = resolve_lammps_bin(args.lammps_bin)
    mace_python_resolved = _pick_python_for_mace()

    eq_ps_display = eq_steps * args.timestep_fs / 1000.0
    prod_ps_display = prod_steps * args.timestep_fs / 1000.0

    print()
    print("══════════════════════════════════════════════════════════════════════════════")
    print("  LAMMPS + MACE NVT workflow")
    print("══════════════════════════════════════════════════════════════════════════════")
    print(f"  PMC ID        : {pmc_id}" + (f"  (resolved from '{args.pmc}')" if args.pmc != pmc_id else ""))
    print(f"  Molecule name : {molecule_name or '(none in json)'}")
    print(f"  Data dir      : {DATA_DIR}")
    print(f"  Temperatures  : {temps}")
    print(f"  Model         : {args.model}")
    print(f"  Supercell     : {args.supercell}x{args.supercell}x{args.supercell}")
    print(f"  Eq duration   : {eq_steps} steps ({eq_ps_display:g} ps)")
    print(f"  Prod duration : {prod_steps} steps ({prod_ps_display:g} ps)")
    print(f"  Timestep      : {args.timestep_fs} fs")
    print(f"  Restart every : {args.restart_every} steps")
    print(f"  Resume policy : {args.resume_policy}")
    print(f"  Save PDB      : {args.save_pdb}")
    kokkos_on = _env_flag_true("LAMMPS_USE_KOKKOS", default=False)
    kokkos_display = (
        f"ON  (-k on g {os.environ.get('LAMMPS_GPUS', '1')} -sf kk -pk kokkos ...)"
        if kokkos_on else "OFF (plain CPU lmp)"
    )
    print(f"  Env script    : {env_script_resolved if env_script_resolved else '(none -- disabled or not found)'}")
    print(f"  Kokkos/GPU    : {kokkos_display}")
    print(f"  LAMMPS binary : {lammps_bin_display}")
    print(f"  MACE python   : {mace_python_resolved}")
    print(f"  Model dir     : {_get_model_dir()}  (only used for small/medium/large aliases)")
    print(f"  Results dir   : {results_root}")
    print()

    t0 = time.time()

    for temp in temps:
        run_single_temperature(
            pmc_id=pmc_id,
            temp_K=temp,
            results_root=results_root,
            model=args.model,
            supercell_size=args.supercell,
            eq_steps=eq_steps,
            prod_steps=prod_steps,
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
    print(f"  Results: {results_root}")
    print("══════════════════════════════════════════════════════════════════════════════")


if __name__ == "__main__":
    main()