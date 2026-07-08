"""
md_common.py — Shared engine for run_nvt.py and run_npt.py
────────────────────────────────────────────────────────────
This module is imported by both pipelines. It does NOT decide folder
layout (that's each script's job) — it only provides the building
blocks: supercell generation, checkpointed minimisation, checkpointed
MD stages, plotting, and RDF calculation.

Every long-running stage (minimisation, NVT, NPT) is checkpointed:
  - a restart file (ASE extxyz) with the latest atomic positions/velocities
  - a state.json with {completed_steps, target_steps, status, ...}
This lets you:
  1. Kill/resume a run at any time (crash, walltime limit, etc.)
  2. Deliberately cap a single invocation with --slice-steps so a very
     long simulation is executed as many short slices (e.g. one per
     HPC job submission) instead of one huge run.
"""
import json
import csv
import time
import numpy as np
from pathlib import Path

# ── Paths (shared by both pipelines; each pipeline picks its own
#    results subfolder so NVT and NPT outputs never mix) ──────────
PROJECT_ROOT = Path.home() / "himesh_work"
DATA_DIR = PROJECT_ROOT / "data"
SIM_DIR = PROJECT_ROOT / "simulations"

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
BAR_TO_GPA = 1e-4

RDF_R_MAX = 10.0                  # Angstrom
RDF_N_BINS = 200


# ═══════════════════════════════════════════════════════════════════
#  Molecule / supercell helpers
# ═══════════════════════════════════════════════════════════════════
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
# ═══════════════════════════════════════════════════════════════════
def save_stage_state(state_path: Path, state: dict):
    """Write stage state JSON atomically (tmp file + rename)."""
    tmp_path = state_path.with_suffix(state_path.suffix + ".tmp")
    with open(tmp_path, "w") as f:
        json.dump(state, f, indent=2)
    tmp_path.replace(state_path)


def load_stage_state(state_path: Path):
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
# ═══════════════════════════════════════════════════════════════════
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
# ═══════════════════════════════════════════════════════════════════
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
# ═══════════════════════════════════════════════════════════════════
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

    state = load_stage_state(state_path)
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
        save_stage_state(state_path, state)

    def write_frame():
        write(str(traj_path), atoms, format="proteindatabank", append=True)

    def checkpoint():
        write(str(restart_path), atoms, format="extxyz")
        write(str(last_frame_path), atoms, format="proteindatabank")
        state["completed_steps"] = completed_steps + opt.nsteps
        state["status"] = "running"
        save_stage_state(state_path, state)

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
    save_stage_state(state_path, state)

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
# ═══════════════════════════════════════════════════════════════════
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

    state = load_stage_state(state_path)
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
        save_stage_state(state_path, state)

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
        save_stage_state(state_path, state)

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
    save_stage_state(state_path, state)

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
# ═══════════════════════════════════════════════════════════════════
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