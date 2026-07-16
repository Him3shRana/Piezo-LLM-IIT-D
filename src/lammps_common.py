#!/usr/bin/env python3
"""
lammps_common.py
================

Shared helpers for LAMMPS + MACE MD workflows.

Key design
----------
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
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from ase import Atoms
from ase.io import read, write
from ase.io.lammpsdata import write_lammps_data

import md_common as mc


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
# Model helpers
# =============================================================================

def _resolve_model_source(model_path: str) -> Path:
    """
    Resolve the user-provided model argument into a source model path.

    Accepted forms:
        medium
        small
        large
        /path/to/model.model
        /path/to/model-mliap_lammps.pt

    Edit alias paths here if your actual model files live elsewhere.
    """
    aliases = {
        "small": Path("MACE-OFF23_small.model"),
        "medium": Path("MACE-OFF23_medium.model"),
        "large": Path("MACE-OFF23_large.model"),
    }

    p = Path(model_path)
    if model_path in aliases:
        p = aliases[model_path]

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
      3) python3 if available
      4) python
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
            raise FileNotFoundError(f"MACE source model file not found: {src}")

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

def resolve_lammps_bin(lammps_bin: Optional[str] = None) -> str:
    """
    Resolve the LAMMPS executable.

    Priority:
      1) explicit --lammps-bin
      2) $LAMMPS_BIN
      3) $LAMMPS_INSTALL/bin/lmp
      4) lmp from PATH
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

    return "lmp"


def _env_flag_true(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return str(val).strip().lower() in {"1", "true", "yes", "y", "on"}


def build_lammps_command(
    input_path: Path,
    log_path: Path,
    lammps_bin: Optional[str] = None,
) -> List[str]:
    """
    Build the LAMMPS command.

    Default behavior:
      - plain CPU LAMMPS command (safe on login nodes / CPU nodes)

    Optional GPU/Kokkos behavior:
      set environment variable:
          export LAMMPS_USE_KOKKOS=1

    Optional GPU count:
          export LAMMPS_GPUS=1

    Example GPU command produced:
      lmp -k on g 1 -sf kk -pk kokkos newton on neigh half -in ... -log ...

    Example CPU command produced:
      lmp -in ... -log ...
    """
    lmp = resolve_lammps_bin(lammps_bin)
    use_kokkos = _env_flag_true("LAMMPS_USE_KOKKOS", default=False)
    ngpu = os.environ.get("LAMMPS_GPUS", "1")

    if use_kokkos:
        return [
            lmp,
            "-k", "on", "g", str(ngpu),
            "-sf", "kk",
            "-pk", "kokkos", "newton", "on", "neigh", "half",
            "-in", str(input_path),
            "-log", str(log_path),
        ]

    return [
        lmp,
        "-in", str(input_path),
        "-log", str(log_path),
    ]


# =============================================================================
# Stage-state helpers
# =============================================================================

def load_stage_state(state_path: Path) -> dict:
    if not state_path.exists():
        return {}
    with open(state_path, "r") as f:
        return json.load(f)


def save_stage_state(state_path: Path, state: dict):
    """
    Use md_common.save_stage_state if present; otherwise local atomic write.
    """
    if hasattr(mc, "save_stage_state"):
        return mc.save_stage_state(state_path, state)

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
        f"restart         {int(restart_every_steps)} {output_restart}.*",
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
        f"restart         {int(restart_every_steps)} {output_restart}.*",
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
    if hasattr(mc, "plot_temp_vs_time"):
        try:
            ok = mc.plot_temp_vs_time(csv_path, temp, title, plot_path)
            if ok:
                return True
        except Exception:
            pass
    return False


def maybe_plot_volume(csv_path: Path, title: str, plot_path: Path, initial_volume: Optional[float] = None):
    if hasattr(mc, "plot_volume_vs_time"):
        try:
            return mc.plot_volume_vs_time(csv_path, title, plot_path, initial_volume=initial_volume)
        except Exception:
            return False
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
    }