"""
run_all.py — One command to simulate any crystal
─────────────────────────────────────────────────

Usage:
  python3 run_all.py PMC-007                              # 300K, defaults, 1 bar NPT
  python3 run_all.py PMC-007 --temps 100 200 300 400      # custom temperatures
  python3 run_all.py PMC-007 --timestep 0.5 --eq-steps 20000 --steps 200000
  python3 run_all.py PMC-007 --pressure 1.0                # NPT external pressure (bar)
  python3 run_all.py PMC-007 --size 3                     # 3x3x3 supercell
  python3 run_all.py all                                  # ALL molecules
  python3 run_all.py --list                               # show molecules

Simulation length is given directly in NUMBER OF STEPS. The timestep only
sets the physics and the time labels:

      simulated time (ps) = steps * timestep_fs / 1000

  e.g.  --steps 200000 --timestep 0.5  ->  100 ps production
        --eq-steps 20000 --timestep 0.5  ->  10 ps equilibration

Pipeline (always runs, in this order, per temperature):
  1. Minimisation        shared, ensemble-independent, T = 0 K
  2. NVT Equilibration    fixed cell, thermalises the system at target T
  3. NVT Production       fixed cell, sampling run at target T
                          (last frame -> feeds into NPT Equilibration)
  4. NPT Equilibration    cell free to move, relaxes density at
                          (target T, --pressure)
                          (last frame -> feeds into NPT Production)
  5. NPT Production       cell free to move, sampling run at
                          (target T, --pressure)

Each stage saves:
  - a PDB trajectory (keeps the unit-cell CRYST1 record)
  - a full thermo log/CSV (step, time, T, E, P, V, a/b/c/alpha/beta/gamma)
  - NVT stages -> Temperature vs Time plot
  - NPT stages -> Volume vs Time plot

Every stage is independently resumable: if its PDB + CSV already exist,
the stage is skipped and its last trajectory frame is reloaded to feed
the next stage, so you can safely re-run a partially finished pipeline.

Output layout (NVT and NPT results never clash):
  md_results/
    minimisation.log                  minimiser log (shared)
    {pmc}_minimised.pdb                minimised structure (shared)
    NVT/{T}K/
      equilibration_{T}K.pdb / .csv / _temp.png
      production_{T}K.pdb   / .csv / _temp.png
    NPT/{T}K/
      equilibration_{T}K.pdb / .csv / _volume.png
      production_{T}K.pdb   / .csv / _volume.png
"""
import json
import csv
import os
import sys
import time
import argparse
import numpy as np
from pathlib import Path
from datetime import datetime
import warnings

warnings.filterwarnings("ignore", message=".*not interpreted for space group.*")
warnings.filterwarnings("ignore", message=".*weights_only.*")
warnings.filterwarnings("ignore", message=".*Pandas requires version.*")
warnings.filterwarnings("ignore", message=".*TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD.*")
warnings.filterwarnings("ignore", category=UserWarning, module="mace")
warnings.filterwarnings("ignore", category=UserWarning, module="pandas")
warnings.filterwarnings("ignore", category=UserWarning, module="e3nn")

# ── Paths ──────────────────────────────────────────
PROJECT_ROOT = Path.home() / "himesh_work"
DATA_DIR = PROJECT_ROOT / "data"
SIM_DIR = PROJECT_ROOT / "simulations"

# ── Defaults (all overridable on the command line) ──
DEFAULT_TIMESTEP_FS = 0.5         # femtoseconds per step
DEFAULT_EQ_STEPS = 20000          # equilibration steps (20000 * 0.5 fs = 10 ps)
DEFAULT_PROD_STEPS = 200000       # production steps  (200000 * 0.5 fs = 100 ps)
DEFAULT_PRESSURE_BAR = 1.0        # external pressure for NPT stages
TRAJECTORY_INTERVAL = 100         # write a trajectory frame every N steps
LOG_INTERVAL = 100                 # write a thermo row every N steps

# ── NPT barostat settings (tune here if needed) ────
NPT_TTIME_FS = 25.0
NPT_PTIME_FS = 75.0
NPT_BULK_MODULUS_GPA = 100.0

BAR_TO_GPA = 1e-4                 # 1 bar = 1e-4 GPa


def find_cif(pmc_id: str) -> Path:
    """Find the CIF file for a given PMC ID."""
    folder = DATA_DIR / pmc_id
    if not folder.exists():
        return None
    cif_files = list(folder.glob("*.cif"))
    return cif_files[0] if cif_files else None


def get_available_molecules() -> list:
    """List all PMC folders that have a CIF file."""
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
                    import json
                    with open(json_f[0]) as f:
                        name = json.load(f).get("molecule_name", "")
                except:
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
    """Generate supercell from CIF."""
    from ase.io import read, write
    from ase.build import make_supercell

    cif_path = find_cif(pmc_id)
    if not cif_path:
        return {"status": "error", "message": f"No CIF file found for {pmc_id}"}

    size_str = f"{size}x{size}x{size}"
    sim_dir = SIM_DIR / pmc_id
    sim_dir.mkdir(parents=True, exist_ok=True)

    output_path = sim_dir / f"{pmc_id}_supercell_{size_str}.cif"

    # Skip if already exists
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


def plot_temp_vs_time(log_data, target_temp, title, out_path):
    """Save a Temperature vs Time figure. Skips cleanly if no matplotlib or no data."""
    if not log_data:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  ℹ matplotlib not installed — skipping temperature plot (CSV still saved).")
        return None

    t_ps = [d["time_fs"] / 1000.0 for d in log_data]
    temp_arr = [d["temperature_K"] for d in log_data]

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


def plot_volume_vs_time(log_data, title, out_path):
    """Save a Volume vs Time figure. Skips cleanly if no matplotlib or no data."""
    if not log_data:
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  ℹ matplotlib not installed — skipping volume plot (CSV still saved).")
        return None

    t_ps = [d["time_fs"] / 1000.0 for d in log_data]
    vol = [d["volume_A3"] for d in log_data]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(t_ps, vol, color="C2", linewidth=0.9)
    ax.set_xlabel("Time (ps)")
    ax.set_ylabel("Volume (Å³)")
    ax.set_title(title)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return out_path


def _make_traj_writer(atoms_ref, path):
    """Return a callback that appends the current frame to a PDB file."""
    from ase.io import write

    def write_frame():
        write(str(path), atoms_ref, format="proteindatabank", append=True)
    return write_frame


def make_logger(atoms_ref, dyn_ref, log_ref, dt_fs, print_interval=5000):
    """Return a callback that appends one thermo row per call."""
    def log_thermo():
        step = dyn_ref.nsteps
        t = atoms_ref.get_temperature()
        ke = atoms_ref.get_kinetic_energy()
        pe = atoms_ref.get_potential_energy()
        vol = atoms_ref.get_volume()
        cell = atoms_ref.get_cell().cellpar()
        try:
            stress = atoms_ref.get_stress(voigt=True)
            p = -(stress[0] + stress[1] + stress[2]) / 3.0 * 160.21766
        except:
            p = 0.0
        log_ref.append({
            "step": step, "time_fs": step * dt_fs,
            "temperature_K": t, "kinetic_eV": ke,
            "potential_eV": pe, "total_eV": ke + pe,
            "pressure_GPa": p, "volume_A3": vol,
            "a_A": cell[0], "b_A": cell[1], "c_A": cell[2],
            "alpha_deg": cell[3], "beta_deg": cell[4], "gamma_deg": cell[5],
        })
        if step % print_interval == 0:
            print(f"      Step {step:6d} | {step*dt_fs/1000:6.1f} ps | "
                  f"T={t:6.1f} K | E={ke+pe:12.2f} eV | "
                  f"V={vol:8.1f} ų | a={cell[0]:.3f} b={cell[1]:.3f} c={cell[2]:.3f}")
    return log_thermo


def save_stage_state(state_path, state_dict):
    """Write stage state JSON atomically."""
    tmp_path = state_path.with_suffix(state_path.suffix + ".tmp")
    with open(tmp_path, "w") as f:
        json.dump(state_dict, f, indent=2)
    tmp_path.replace(state_path)


def load_stage_state(state_path):
    """Load stage state JSON if it exists."""
    if not state_path.exists():
        return None
    with open(state_path, "r") as f:
        return json.load(f)


def append_log_to_csv(csv_path, log_rows, write_header=False):
    """Append thermo rows to CSV."""
    if not log_rows:
        return
    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=log_rows[0].keys())
        if write_header:
            writer.writeheader()
        writer.writerows(log_rows)


# def run_md_stage(atoms_in, calc, steps, timestep_fs, temp, stage_dir, stage_name,
#                   dyn_type="nvt", pressure_GPa=0.0, init_velocities=False,
#                   plot_kind="temp"):
#     """
#     Run one MD stage (NVT or NPT), saving a PDB trajectory + CSV thermo log
#     + a plot (Temperature vs Time for NVT, Volume vs Time for NPT).

#     If this stage's PDB + CSV already exist, it is skipped and the last
#     trajectory frame is reloaded instead — so the pipeline is resumable.

#     Returns (final_atoms, log_data, elapsed_seconds). final_atoms has `calc`
#     attached and is ready to be fed into the next stage.
#     """
#     from ase.io import read, write
#     from ase.md.nvtberendsen import NVTBerendsen
#     from ase.md.npt import NPT
#     from ase.md.velocitydistribution import MaxwellBoltzmannDistribution
#     from ase import units
#     import csv

#     folder_existed = stage_dir.exists()
#     stage_dir.mkdir(parents=True, exist_ok=True)
#     if not folder_existed:
#         print(f"    📁 Created folder: {stage_dir}")

#     traj_path = stage_dir / f"{stage_name}_{temp}K.pdb"
#     csv_path = stage_dir / f"{stage_name}_{temp}K.csv"

#     if csv_path.exists() and traj_path.exists():
#         print(f"    {stage_name.capitalize()} already completed — "
#               f"resuming from {traj_path.name} (delete it to re-run this stage)")
#         final_atoms = read(str(traj_path), index=-1)
#         final_atoms.calc = calc
#         return final_atoms, None, 0.0

#     atoms = atoms_in.copy()
#     atoms.calc = calc

#     if init_velocities:
#         MaxwellBoltzmannDistribution(atoms, temperature_K=temp)

#     if dyn_type == "npt":
#         # ASE NPT requires an upper-triangular cell.
#         cell = atoms.get_cell()
#         if abs(cell[1, 0]) + abs(cell[2, 0]) + abs(cell[2, 1]) > 1e-8:
#             atoms.set_cell(cell.standard_form()[0], scale_atoms=True)
#         ttime = NPT_TTIME_FS * units.fs
#         ptime = NPT_PTIME_FS * units.fs
#         pfactor = ptime ** 2 * NPT_BULK_MODULUS_GPA * units.GPa
#         dyn = NPT(
#             atoms,
#             timestep=timestep_fs * units.fs,
#             temperature_K=temp,
#             externalstress=pressure_GPa * units.GPa,
#             ttime=ttime,
#             pfactor=pfactor,
#         )
#         label = f"NPT @ {pressure_GPa / BAR_TO_GPA:.1f} bar"
#     else:
#         dyn = NVTBerendsen(atoms, timestep=timestep_fs * units.fs,
#                             temperature_K=temp, taut=100 * units.fs)
#         label = "NVT"

#     if traj_path.exists():
#         traj_path.unlink()
#     dyn.attach(_make_traj_writer(atoms, traj_path), interval=TRAJECTORY_INTERVAL)

#     log_data = []
#     dyn.attach(make_logger(atoms, dyn, log_data, timestep_fs), interval=LOG_INTERVAL)

#     ps = steps * timestep_fs / 1000.0
#     print(f"    {stage_name.capitalize()} ({ps:.2f} ps = {steps} steps, {label})...")

#     t0 = time.time()
#     dyn.run(steps)
#     elapsed = time.time() - t0

#     print(f"    💾 Saved trajectory: {traj_path}")

#     with open(csv_path, "w", newline="") as f:
#         writer = csv.DictWriter(f, fieldnames=log_data[0].keys())
#         writer.writeheader()
#         writer.writerows(log_data)
#     print(f"    💾 Saved thermo log (CSV): {csv_path}")

#     if plot_kind == "temp":
#         plot_path = stage_dir / f"{stage_name}_{temp}K_temp.png"
#         saved = plot_temp_vs_time(
#             log_data, temp,
#             f"{stage_name.capitalize()} — Temperature vs Time ({temp} K)",
#             plot_path)
#         if saved:
#             print(f"    💾 Saved plot (Temperature vs Time): {plot_path}")
#     elif plot_kind == "volume":
#         plot_path = stage_dir / f"{stage_name}_{temp}K_volume.png"
#         saved = plot_volume_vs_time(
#             log_data,
#             f"{stage_name.capitalize()} — Volume vs Time "
#             f"({temp} K, {pressure_GPa / BAR_TO_GPA:.1f} bar)",
#             plot_path)
#         if saved:
#             print(f"    💾 Saved plot (Volume vs Time): {plot_path}")

#     print(f"    ✅ {stage_name.capitalize()} done: {elapsed:.0f}s | "
#           f"Final T={atoms.get_temperature():.1f} K | "
#           f"Final V={atoms.get_volume():.1f} ų")

#     return atoms, log_data, elapsed


def run_md_stage(
    atoms_in,
    calc,
    steps,
    timestep_fs,
    temp,
    stage_dir,
    stage_name,
    dyn_type="nvt",
    pressure_GPa=0.0,
    init_velocities=False,
    plot_kind="temp",
    pmc_id=None,
    checkpoint_interval=5000,
):
    """
    Run one MD stage (NVT or NPT) with checkpoint / resume support.

    Files created per stage:
      - {stage_name}_{temp}K.pdb
      - {stage_name}_{temp}K.csv
      - {stage_name}_{temp}K.restart.extxyz
      - {stage_name}_{temp}K.state.json

    Resume logic:
      - If state says completed_steps >= target_steps:
            load restart and return immediately.
      - If state says completed_steps < target_steps:
            resume from restart and continue remaining steps.
      - If no state/restart:
            start fresh from atoms_in.
    """
    from ase.io import read, write
    from ase.md.nvtberendsen import NVTBerendsen
    from ase.md.npt import NPT
    from ase.md.velocitydistribution import MaxwellBoltzmannDistribution
    from ase import units
    import time

    folder_existed = stage_dir.exists()
    stage_dir.mkdir(parents=True, exist_ok=True)
    if not folder_existed:
        print(f"    📁 Created folder: {stage_dir}")

    ensemble_name = "NPT" if dyn_type == "npt" else "NVT"

    traj_path = stage_dir / f"{stage_name}_{temp}K.pdb"
    csv_path = stage_dir / f"{stage_name}_{temp}K.csv"
    restart_path = stage_dir / f"{stage_name}_{temp}K.restart.extxyz"
    state_path = stage_dir / f"{stage_name}_{temp}K.state.json"

    # ---------------------------------------------------------
    # Case 1/2/3: inspect existing state
    # ---------------------------------------------------------
    state = load_stage_state(state_path)

    completed_steps = 0
    fresh_csv = True

    if state is not None and restart_path.exists():
        completed_steps = int(state.get("completed_steps", 0))
        target_steps_old = int(state.get("target_steps", steps))

        # If the new requested target is larger than old target, allow extension.
        # Example: old completed 200000, user now asks for 1000000 total.
        target_steps = max(steps, target_steps_old)

        if completed_steps >= target_steps:
            print(f"    {stage_name.capitalize()} already completed "
                  f"({completed_steps}/{target_steps} steps) — loading restart")
            final_atoms = read(str(restart_path))
            final_atoms.calc = calc
            return final_atoms, None, 0.0

        print(f"    Resuming {stage_name} from checkpoint:")
        print(f"      completed_steps = {completed_steps}")
        print(f"      target_steps    = {target_steps}")
        print(f"      remaining_steps = {target_steps - completed_steps}")

        atoms = read(str(restart_path))
        atoms.calc = calc
        fresh_csv = not csv_path.exists()
    else:
        target_steps = steps
        atoms = atoms_in.copy()
        atoms.calc = calc

        # Fresh stage: if old files exist but no valid checkpoint, archive by overwrite.
        if traj_path.exists():
            traj_path.unlink()
        if csv_path.exists():
            csv_path.unlink()

        if init_velocities:
            MaxwellBoltzmannDistribution(atoms, temperature_K=temp)

        # Initialize state file for fresh run
        state = {
            "pmc_id": pmc_id,
            "ensemble": ensemble_name.lower(),
            "stage": stage_name,
            "temperature_K": temp,
            "pressure_GPa": pressure_GPa if dyn_type == "npt" else None,
            "timestep_fs": timestep_fs,
            "target_steps": target_steps,
            "completed_steps": 0,
            "trajectory_interval": TRAJECTORY_INTERVAL,
            "log_interval": LOG_INTERVAL,
            "checkpoint_interval": checkpoint_interval,
            "trajectory_file": traj_path.name,
            "csv_file": csv_path.name,
            "restart_file": restart_path.name,
            "status": "running",
        }
        save_stage_state(state_path, state)

    remaining_steps = target_steps - completed_steps
    if remaining_steps <= 0:
        final_atoms = read(str(restart_path))
        final_atoms.calc = calc
        return final_atoms, None, 0.0

    # ---------------------------------------------------------
    # Build MD integrator
    # ---------------------------------------------------------
    if dyn_type == "npt":
        # ASE NPT requires upper-triangular cell
        cell = atoms.get_cell()
        if abs(cell[1, 0]) + abs(cell[2, 0]) + abs(cell[2, 1]) > 1e-8:
            atoms.set_cell(cell.standard_form()[0], scale_atoms=True)

        ttime = NPT_TTIME_FS * units.fs
        ptime = NPT_PTIME_FS * units.fs
        pfactor = ptime ** 2 * NPT_BULK_MODULUS_GPA * units.GPa

        dyn = NPT(
            atoms,
            timestep=timestep_fs * units.fs,
            temperature_K=temp,
            externalstress=pressure_GPa * units.GPa,
            ttime=ttime,
            pfactor=pfactor,
        )
        label = f"NPT @ {pressure_GPa / BAR_TO_GPA:.1f} bar"
    else:
        dyn = NVTBerendsen(
            atoms,
            timestep=timestep_fs * units.fs,
            temperature_K=temp,
            taut=100 * units.fs,
        )
        label = "NVT"

    # ---------------------------------------------------------
    # Logging / trajectory / checkpoint callbacks
    # ---------------------------------------------------------
    log_data = []

    # Track global stage step count = completed_steps + dyn.nsteps
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
            "step": step,
            "time_fs": step * timestep_fs,
            "temperature_K": t,
            "kinetic_eV": ke,
            "potential_eV": pe,
            "total_eV": ke + pe,
            "pressure_GPa": p,
            "volume_A3": vol,
            "a_A": cell[0],
            "b_A": cell[1],
            "c_A": cell[2],
            "alpha_deg": cell[3],
            "beta_deg": cell[4],
            "gamma_deg": cell[5],
        }
        log_data.append(row)

        if step % 5000 == 0:
            print(
                f"      Step {step:6d} | {step*timestep_fs/1000:6.1f} ps | "
                f"T={t:6.1f} K | E={ke+pe:12.2f} eV | "
                f"V={vol:8.1f} Å³ | a={cell[0]:.3f} b={cell[1]:.3f} c={cell[2]:.3f}"
            )

    def write_frame():
        # append current frame to trajectory
        write(str(traj_path), atoms, format="proteindatabank", append=True)

    def save_checkpoint():
        # write latest restart structure
        write(str(restart_path), atoms, format="extxyz")

        # append accumulated log rows to CSV
        nonlocal fresh_csv
        if log_data:
            append_log_to_csv(csv_path, log_data, write_header=fresh_csv)
            fresh_csv = False
            log_data.clear()

        # update state
        current_steps = completed_steps + dyn.nsteps
        state["completed_steps"] = current_steps
        state["target_steps"] = target_steps
        state["status"] = "running"
        save_stage_state(state_path, state)

    dyn.attach(write_frame, interval=TRAJECTORY_INTERVAL)
    dyn.attach(log_thermo, interval=LOG_INTERVAL)
    dyn.attach(save_checkpoint, interval=checkpoint_interval)

    ps_remaining = remaining_steps * timestep_fs / 1000.0
    print(
        f"    {stage_name.capitalize()} "
        f"({ps_remaining:.2f} ps = {remaining_steps} steps remaining, {label})..."
    )

    # ---------------------------------------------------------
    # Run
    # ---------------------------------------------------------
    t0 = time.time()
    dyn.run(remaining_steps)
    elapsed = time.time() - t0

    # final checkpoint flush
    save_checkpoint()

    # mark completed
    state["completed_steps"] = target_steps
    state["target_steps"] = target_steps
    state["status"] = "completed"
    save_stage_state(state_path, state)

    # plots
    if plot_kind == "temp":
        plot_path = stage_dir / f"{stage_name}_{temp}K_temp.png"
        # read full CSV back into memory for full-trajectory plot
        import csv as _csv
        full_log = []
        with open(csv_path, "r") as f:
            reader = _csv.DictReader(f)
            for row in reader:
                # convert numeric columns back to float/int where needed
                row["step"] = int(float(row["step"]))
                row["time_fs"] = float(row["time_fs"])
                row["temperature_K"] = float(row["temperature_K"])
                row["volume_A3"] = float(row["volume_A3"])
                full_log.append(row)
        saved = plot_temp_vs_time(
            full_log,
            temp,
            f"{stage_name.capitalize()} — Temperature vs Time ({temp} K)",
            plot_path,
        )
        if saved:
            print(f"    💾 Saved plot (Temperature vs Time): {plot_path}")

    elif plot_kind == "volume":
        plot_path = stage_dir / f"{stage_name}_{temp}K_volume.png"
        import csv as _csv
        full_log = []
        with open(csv_path, "r") as f:
            reader = _csv.DictReader(f)
            for row in reader:
                row["step"] = int(float(row["step"]))
                row["time_fs"] = float(row["time_fs"])
                row["temperature_K"] = float(row["temperature_K"])
                row["volume_A3"] = float(row["volume_A3"])
                full_log.append(row)
        saved = plot_volume_vs_time(
            full_log,
            f"{stage_name.capitalize()} — Volume vs Time "
            f"({temp} K, {pressure_GPa / BAR_TO_GPA:.1f} bar)",
            plot_path,
        )
        if saved:
            print(f"    💾 Saved plot (Volume vs Time): {plot_path}")

    print(f"    💾 Saved trajectory: {traj_path}")
    print(f"    💾 Saved thermo log (CSV): {csv_path}")
    print(f"    💾 Saved restart: {restart_path}")
    print(f"    💾 Saved state:   {state_path}")
    final_T = atoms.get_temperature()
final_ke = atoms.get_kinetic_energy()
final_pe = atoms.get_potential_energy()
final_E = final_ke + final_pe
final_V = atoms.get_volume()
cell = atoms.get_cell().cellpar()

try:
    stress = atoms.get_stress(voigt=True)
    final_P = -(stress[0] + stress[1] + stress[2]) / 3.0 * 160.21766
except Exception:
    final_P = 0.0

print(
    f"    ✅ {stage_name.capitalize()} done: {elapsed:.0f}s\n"
    f"       Final Step = {target_steps}\n"
    f"       T = {final_T:.2f} K | P = {final_P:.4f} GPa | "
    f"E = {final_E:.4f} eV | V = {final_V:.2f} Å³\n"
    f"       a = {cell[0]:.4f} Å | b = {cell[1]:.4f} Å | c = {cell[2]:.4f} Å\n"
    f"       α = {cell[3]:.2f}° | β = {cell[4]:.2f}° | γ = {cell[5]:.2f}°"
)

    return atoms, None, elapsed


def run_simulation(pmc_id: str, temperatures: list, size: int = 2,
                    timestep_fs: float = DEFAULT_TIMESTEP_FS,
                    equilibration_steps: int = DEFAULT_EQ_STEPS,
                    production_steps: int = DEFAULT_PROD_STEPS,
                    npt_equilibration_steps: int = None,
                    npt_production_steps: int = None,
                    pressure_bar: float = DEFAULT_PRESSURE_BAR,
                    mace_model: str = "medium"):
    """Run the full MACE-OFF23 pipeline for one molecule:
    Minimisation -> NVT Eq -> NVT Prod -> NPT Eq -> NPT Prod (per temperature).

    NPT step counts default to the same values as NVT (equilibration_steps /
    production_steps) if npt_equilibration_steps / npt_production_steps are
    not given.
    """
    from ase.io import read, write
    from ase.optimize import LBFGS
    from mace.calculators import mace_off
    import torch

    # NPT stages default to the same step counts as NVT unless overridden
    if npt_equilibration_steps is None:
        npt_equilibration_steps = equilibration_steps
    if npt_production_steps is None:
        npt_production_steps = production_steps

    size_str = f"{size}x{size}x{size}"
    cif_path = SIM_DIR / pmc_id / f"{pmc_id}_supercell_{size_str}.cif"

    if not cif_path.exists():
        print(f"  ❌ Supercell not found: {cif_path}")
        return False

    pressure_GPa = pressure_bar * BAR_TO_GPA

    eq_ps = equilibration_steps * timestep_fs / 1000.0
    prod_ps = production_steps * timestep_fs / 1000.0
    npt_eq_ps = npt_equilibration_steps * timestep_fs / 1000.0
    npt_prod_ps = npt_production_steps * timestep_fs / 1000.0

    # Setup
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"  Device: {device}")
    print(f"  Timestep: {timestep_fs} fs")
    print(f"  NVT Equilibration: {equilibration_steps} steps -> {eq_ps:.2f} ps")
    print(f"  NVT Production:    {production_steps} steps -> {prod_ps:.2f} ps")
    print(f"  NPT Equilibration: {npt_equilibration_steps} steps -> {npt_eq_ps:.2f} ps")
    print(f"  NPT Production:    {npt_production_steps} steps -> {npt_prod_ps:.2f} ps")
    print(f"  NPT pressure:  {pressure_bar} bar")

    atoms = read(str(cif_path))
    print(f"  Loaded: {len(atoms)} atoms")

    calc = mace_off(model=mace_model, device=device, default_dtype="float64")
    atoms.calc = calc

    output_dir = SIM_DIR / pmc_id / "md_results"
    output_existed = output_dir.exists()
    output_dir.mkdir(parents=True, exist_ok=True)
    if not output_existed:
        print(f"  📁 Created folder: {output_dir}")

    # NVT and NPT results are kept in their own folders so they never clash.
    nvt_dir = output_dir / "NVT"
    npt_dir = output_dir / "NPT"
    for d in (nvt_dir, npt_dir):
        existed = d.exists()
        d.mkdir(parents=True, exist_ok=True)
        if not existed:
            print(f"  📁 Created folder: {d}")

    # ── Minimisation (shared, ensemble-independent) ──
    print(f"\n  ── Minimisation ──")
    atoms_min = atoms.copy()
    atoms_min.calc = calc
    min_pdb = output_dir / f"{pmc_id}_minimised.pdb"
    if min_pdb.exists():
        print(f"  Already minimised — loading {min_pdb.name}")
        atoms_min = read(str(min_pdb))
        atoms_min.calc = calc
    else:
        opt = LBFGS(atoms_min, logfile=str(output_dir / "minimisation.log"))
        t0 = time.time()
        opt.run(fmax=0.05, steps=500)
        t_min = time.time() - t0
        e_min = atoms_min.get_potential_energy()
        print(f"  Energy: {e_min:.2f} eV | Steps: {opt.nsteps} | Time: {t_min:.0f}s")
        print(f"  💾 Saved minimiser log: {output_dir / 'minimisation.log'}")
        write(str(min_pdb), atoms_min, format="proteindatabank")
        print(f"  💾 Saved minimised structure: {min_pdb}")

    ref_a, ref_b, ref_c, *_ = atoms_min.get_cell().cellpar()
    print(f"  Reference lattice (minimised): a={ref_a:.4f} b={ref_b:.4f} c={ref_c:.4f} Å")

    # ── Per temperature: NVT Eq -> NVT Prod -> NPT Eq -> NPT Prod ──
    for temp in temperatures:
        print(f"\n  ── {temp} K ──")
        nvt_temp_dir = nvt_dir / f"{temp}K"
        npt_temp_dir = npt_dir / f"{temp}K"

        # Stage 1: NVT Equilibration (fixed cell, thermalise from minimised structure)
        print(f"  [NVT] Equilibration")
        atoms_nvt_eq, log_nvt_eq, _ = run_md_stage(
            atoms_min, calc, equilibration_steps, timestep_fs, temp,
            nvt_temp_dir, "equilibration",
            dyn_type="nvt", init_velocities=True, plot_kind="temp",
            pmc_id=pmc_id,
            )

        # Stage 2: NVT Production (fixed cell, sampling run)
        print(f"  [NVT] Production")
        atoms_nvt_prod, log_nvt_prod, _ = run_md_stage(
            atoms_nvt_eq, calc, production_steps, timestep_fs, temp,
            nvt_temp_dir, "production",
            dyn_type="nvt", init_velocities=False, plot_kind="temp",
            pmc_id=pmc_id,
            )

        # Stage 3: NPT Equilibration (cell free, starts from last NVT production frame)
        print(f"  [NPT] Equilibration ({pressure_bar} bar)")
        atoms_npt_eq, log_npt_eq, _ = run_md_stage(
            atoms_nvt_prod, calc, npt_equilibration_steps, timestep_fs, temp,
            npt_temp_dir, "equilibration",
            dyn_type="npt", pressure_GPa=pressure_GPa,
            init_velocities=False, plot_kind="volume",
            pmc_id=pmc_id,
            )

        # Stage 4: NPT Production (cell free, starts from last NPT equilibration frame)
        print(f"  [NPT] Production ({pressure_bar} bar)")
        atoms_npt_prod, log_npt_prod, _ = run_md_stage(
            atoms_npt_eq, calc, npt_production_steps, timestep_fs, temp,
            npt_temp_dir, "production",
            dyn_type="npt", pressure_GPa=pressure_GPa,
            init_velocities=False, plot_kind="volume",
            pmc_id=pmc_id,
            )

        if log_npt_prod:
            a_arr = [d["a_A"] for d in log_npt_prod]
            b_arr = [d["b_A"] for d in log_npt_prod]
            c_arr = [d["c_A"] for d in log_npt_prod]
            vol_arr = [d["volume_A3"] for d in log_npt_prod]
            print(f"  NPT production lattice avg: "
                  f"a={np.mean(a_arr):.4f} b={np.mean(b_arr):.4f} c={np.mean(c_arr):.4f} Å "
                  f"| V={np.mean(vol_arr):.1f} ų "
                  f"(Δ vs minimised: Δa={np.mean(a_arr)-ref_a:+.4f} "
                  f"Δb={np.mean(b_arr)-ref_b:+.4f} Δc={np.mean(c_arr)-ref_c:+.4f} Å)")

    print(f"\n  ✅ {pmc_id} complete! Results: {output_dir}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Piezo-LLM: Automated MD Simulation")
    parser.add_argument("molecule", nargs="?", help="PMC ID (e.g. PMC-007) or 'all'")
    parser.add_argument("--temps", nargs="+", type=int, default=[300],
                        help="Temperatures in K (default: 300)")
    parser.add_argument("--size", type=int, default=2,
                        help="Supercell size: 2 or 3 (default: 2)")
    parser.add_argument("--timestep", type=float, default=DEFAULT_TIMESTEP_FS,
                        help=f"MD timestep in fs (default: {DEFAULT_TIMESTEP_FS})")
    parser.add_argument("--eq-steps", type=int, default=DEFAULT_EQ_STEPS,
                        help=f"NVT equilibration steps (default: {DEFAULT_EQ_STEPS})")
    parser.add_argument("--steps", type=int, default=DEFAULT_PROD_STEPS,
                        help=f"NVT production steps (default: {DEFAULT_PROD_STEPS})")
    parser.add_argument("--npt-eq-steps", type=int, default=None,
                        help="NPT equilibration steps (default: same as --eq-steps)")
    parser.add_argument("--npt-steps", type=int, default=None,
                        help="NPT production steps (default: same as --steps)")
    parser.add_argument("--pressure", type=float, default=DEFAULT_PRESSURE_BAR,
                        help=f"External pressure for NPT stages, in bar (default: {DEFAULT_PRESSURE_BAR})")
    parser.add_argument("--model", default="medium",
                        choices=["small", "medium", "large"],
                        help="MACE model size (default: medium)")
    parser.add_argument("--list", action="store_true",
                        help="List available molecules")

    args = parser.parse_args()

    # Set environment
    os.environ["TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD"] = "1"

    print("=" * 60)
    print("  Piezo-LLM: Automated MD Pipeline")
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    # List mode
    if args.list:
        molecules = get_available_molecules()
        print(f"\n  Available molecules ({len(molecules)}):\n")
        print(f"  {'PMC ID':<12} {'Has CIF':<10} {'Molecule Name'}")
        print(f"  {'─' * 60}")
        for m in molecules:
            cif_mark = "✅" if m["has_cif"] else "❌"
            print(f"  {m['pmc_id']:<12} {cif_mark:<10} {m['molecule_name']}")
        cif_count = sum(1 for m in molecules if m["has_cif"])
        print(f"\n  {cif_count} molecules with CIF files (ready to simulate)")
        return

    if not args.molecule:
        parser.print_help()
        return

    # Determine which molecules to run
    if args.molecule.lower() == "all":
        molecules = get_available_molecules()
        pmc_ids = [m["pmc_id"] for m in molecules if m["has_cif"]]
        print(f"\n  Running ALL {len(pmc_ids)} molecules")
    else:
        pmc_id = args.molecule.upper()
        if not pmc_id.startswith("PMC-"):
            pmc_id = f"PMC-{pmc_id}"
        pmc_ids = [pmc_id]

    eq_ps = args.eq_steps * args.timestep / 1000.0
    prod_ps = args.steps * args.timestep / 1000.0
    npt_eq_steps = args.npt_eq_steps if args.npt_eq_steps is not None else args.eq_steps
    npt_steps = args.npt_steps if args.npt_steps is not None else args.steps
    npt_eq_ps = npt_eq_steps * args.timestep / 1000.0
    npt_prod_ps = npt_steps * args.timestep / 1000.0

    print(f"  Temperatures: {args.temps} K")
    print(f"  Supercell: {args.size}x{args.size}x{args.size}")
    print(f"  Timestep: {args.timestep} fs")
    print(f"  NVT Equilibration: {args.eq_steps} steps ({eq_ps:.2f} ps)")
    print(f"  NVT Production:    {args.steps} steps ({prod_ps:.2f} ps)")
    print(f"  NPT Equilibration: {npt_eq_steps} steps ({npt_eq_ps:.2f} ps)")
    print(f"  NPT Production:    {npt_steps} steps ({npt_prod_ps:.2f} ps)")
    print(f"  NPT pressure: {args.pressure} bar")
    print(f"  MACE model: {args.model}")
    print(f"  Molecules: {len(pmc_ids)}")

    # Run each molecule
    results = {}
    total_start = time.time()

    for i, pmc_id in enumerate(pmc_ids, 1):
        print(f"\n{'▓' * 60}")
        print(f"  [{i}/{len(pmc_ids)}] {pmc_id}")
        print(f"{'▓' * 60}")

        cif = find_cif(pmc_id)
        if not cif:
            print(f"  ❌ No CIF file found, skipping")
            results[pmc_id] = "no_cif"
            continue

        print(f"\n  Generating supercell...")
        sc = generate_supercell(pmc_id, args.size)
        if sc["status"] == "error":
            print(f"  ❌ {sc['message']}")
            results[pmc_id] = "supercell_failed"
            continue

        try:
            success = run_simulation(
                pmc_id, args.temps, args.size,
                timestep_fs=args.timestep,
                equilibration_steps=args.eq_steps,
                production_steps=args.steps,
                npt_equilibration_steps=args.npt_eq_steps,
                npt_production_steps=args.npt_steps,
                pressure_bar=args.pressure,
                mace_model=args.model,
            )
            results[pmc_id] = "success" if success else "failed"
        except Exception as e:
            print(f"  ❌ Error: {e}")
            results[pmc_id] = f"error: {str(e)}"

    total_time = time.time() - total_start

    print(f"\n\n{'=' * 60}")
    print(f"  Pipeline Complete!")
    print(f"  Total time: {total_time / 60:.1f} minutes")
    print(f"{'=' * 60}")
    print(f"\n  {'PMC ID':<12} {'Status'}")
    print(f"  {'─' * 40}")
    for pmc_id, status in results.items():
        icon = "✅" if status == "success" else "❌"
        print(f"  {pmc_id:<12} {icon} {status}")

    success_count = sum(1 for s in results.values() if s == "success")
    print(f"\n  {success_count}/{len(results)} completed successfully")
    print(f"  Results in: {SIM_DIR}")


if __name__ == "__main__":
    main()