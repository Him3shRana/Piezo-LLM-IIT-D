#!/usr/bin/env python3
"""
lammps_common_polar.py
=======================

PolarMACE extension of lammps_common.py, for use with skaiser29's
dev-fork build of MACE + LAMMPS (single-GPU PolarMACE support,
not merged upstream — see ACEsuit/mace#1409 and #1403).

Everything here is a Polar-flavoured sibling of the equivalent function
in lammps_common.py: same restart-based continuity, same checkpointing,
same CSV/state.json/plot conventions. The ONLY new ingredient is the
PolarMACE runtime context (charge / spin / external_field), which needs
to reach LAMMPS somehow so the fork's pair_style can pass it through as
`fermi_level`/electrostatic context on every force evaluation.

===============================================================================
  ⚠️  PLACEHOLDER — NEEDS YOUR REAL SYNTAX FROM THE GPU MACHINE  ⚠️
===============================================================================
The three .in files you showed me (minimisation.in, nvt_equilibration.in,
nvt_production.in) were from the *regular* MACE-OFF23 pipeline — plain
`pair_style mliap unified <model>.pt 0`, no charge/spin/field anywhere.
That tells me nothing about how skaiser29's fork actually accepts Polar
context, so I can't respsonsibly guess it.

Everything below `build_polar_context_lines()` and the `pair_style` line
in `_polar_header_lines()` is a PLACEHOLDER. Once you paste a working
.in file from the GPU box (or the fork's create_lammps_model-equivalent
--help output), the fix is a single-function edit — nothing else in this
file or in run_nvt_lammps_polar.py needs to change.

Likely shapes this ends up taking, based on how MACE's ASE PolarMACE
calculator exposes the same three inputs (atoms.info["charge"],
atoms.info["spin"], atoms.info["external_field"]):
    (a) extra pair_style args:
            pair_style   mliap unified <model>.pt 0 charge <Q> spin <S>
    (b) a companion fix/compute that injects context per-step:
            fix          polar_ctx all property/atom ...
    (c) a set command applied to atoms after read_data/read_restart:
            set          atom * charge ...
Don't trust this list — it's informed guessing, not confirmed. Replace
with what your fork's .in file actually shows.
===============================================================================
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from ase import Atoms

import lammps_common as lc


# =============================================================================
# Model resolution — PolarMACE checkpoints (mirrors lc._resolve_model_source)
# =============================================================================

# EDIT these paths to wherever your MACE-POLAR-1-{S,M,L}.model files (and
# their fork-converted .pt siblings) actually live on the GPU machine.
POLAR_MODEL_ALIASES = {
    "small": Path("MACE-POLAR-1-S.model"),
    "medium": Path("MACE-POLAR-1-M.model"),
    "large": Path("MACE-POLAR-1-L.model"),
}


def resolve_polar_model_source(model_path: str) -> Path:
    p = Path(model_path)
    if model_path in POLAR_MODEL_ALIASES:
        p = POLAR_MODEL_ALIASES[model_path]
    if p.exists():
        return p.resolve()
    return p


def ensure_polar_mliap_model(model_path: str) -> Path:
    """
    Ensure we have a LAMMPS-ready Polar .pt model, converted with whatever
    script skaiser29's fork uses (this may NOT be the stock
    `mace.cli.create_lammps_model` — confirm on your build).
    """
    src = resolve_polar_model_source(model_path)

    if src.suffix == ".pt" and src.exists():
        return src

    if src.suffix == ".model":
        out = src.with_name(src.name + "-mliap_lammps_polar.pt")
        if out.exists():
            return out
        raise FileNotFoundError(
            f"No converted Polar LAMMPS model found at {out}.\n"
            f"  PLACEHOLDER: this repo doesn't know the exact conversion "
            f"command your fork uses for Polar models. Run whatever "
            f"conversion script came with skaiser29's fork on {src} first, "
            f"or point --model-path straight at an already-converted .pt."
        )

    raise FileNotFoundError(
        f"Could not resolve Polar model path '{model_path}'. "
        f"Provide either a .model or a converted .pt file."
    )


# =============================================================================
# PLACEHOLDER: Polar context -> LAMMPS input lines
# =============================================================================

def build_polar_context_lines(
    *,
    model_pt: Path,
    element_order: Sequence[str],
    charge: float,
    spin: float,
    external_field: Tuple[float, float, float],
) -> Tuple[List[str], List[str]]:
    """
    PLACEHOLDER — replace once you have the real .in file.

    Returns (pair_style_lines, extra_lines):
      pair_style_lines : replaces the standard
                          `pair_style mliap unified <model> 0` /
                          `pair_coeff * * <elements>` pair in _polar_header_lines()
      extra_lines       : anything else the fork needs (fix/compute/set
                          commands), inserted right after read_data/read_restart

    Currently just mirrors the non-Polar pair_style and drops a loud
    reminder into the generated .in file so a mistaken real run is
    impossible to miss in the LAMMPS log.
    """
    elems = " ".join(element_order)
    pair_style_lines = [
        f"# !!! PLACEHOLDER PAIR_STYLE — NOT YET CONFIRMED FOR POLAR !!!",
        f"# TODO(Himesh): replace with skaiser29 fork's real Polar syntax.",
        f"# Known context to pass through: charge={charge:g} spin={spin:g} "
        f"field={external_field}",
        f"pair_style      mliap unified {model_pt} 0",
        f"pair_coeff      * * {elems}",
    ]
    extra_lines = [
        f'print "!!! PLACEHOLDER RUN — polar context (Q={charge:g}, '
        f'S={spin:g}, E={external_field}) NOT actually wired into LAMMPS yet !!!"',
    ]
    return pair_style_lines, extra_lines


# =============================================================================
# Header builder (Polar sibling of lc._header_lines)
# =============================================================================

def _polar_header_lines(
    *,
    model_pt: Path,
    element_order: Sequence[str],
    timestep_fs: float,
    charge: float,
    spin: float,
    external_field: Tuple[float, float, float],
    read_data_file: Optional[str] = None,
    read_restart_file: Optional[str] = None,
) -> List[str]:
    if (read_data_file is None) == (read_restart_file is None):
        raise ValueError("Provide exactly one of read_data_file or read_restart_file")

    timestep_ps = timestep_fs / 1000.0
    element_list = list(element_order)

    lines = [
        "# Auto-generated by lammps_common_polar.py",
        "units           metal",
        "atom_style      atomic",
        "newton          on",
        "",
    ]

    if read_data_file is not None:
        lines.append(f"read_data       {read_data_file}")
    else:
        lines.append(f"read_restart    {read_restart_file}")

    pair_style_lines, extra_lines = build_polar_context_lines(
        model_pt=model_pt,
        element_order=element_list,
        charge=charge,
        spin=spin,
        external_field=external_field,
    )

    lines.append("")
    lines += extra_lines
    lines.append("")
    lines += pair_style_lines
    lines.append("")

    mass_lines = lc.build_mass_lines(element_list)
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


# =============================================================================
# Input builders (Polar siblings of build_minimisation_input / build_nvt_input)
# =============================================================================

def build_minimisation_polar_input(
    *,
    data_filename: str,
    model_pt: Path,
    element_order: Sequence[str],
    output_dump: str,
    output_data: str,
    output_restart: str,
    timestep_fs: float,
    charge: float,
    spin: float,
    external_field: Tuple[float, float, float],
) -> str:
    elems = " ".join(element_order)
    lines = _polar_header_lines(
        model_pt=model_pt,
        element_order=element_order,
        timestep_fs=timestep_fs,
        charge=charge,
        spin=spin,
        external_field=external_field,
        read_data_file=data_filename,
    )
    lines += [
        'print "===== STAGE: ENERGY MINIMISATION (POLAR) ====="',
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


def build_nvt_polar_input(
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
    charge: float,
    spin: float,
    external_field: Tuple[float, float, float],
    random_seed: int = 42,
    read_data_file: Optional[str] = None,
    read_restart_file: Optional[str] = None,
    restart_every_steps: int = 100,
) -> str:
    elems = " ".join(element_order)
    lines = _polar_header_lines(
        model_pt=model_pt,
        element_order=element_order,
        timestep_fs=timestep_fs,
        charge=charge,
        spin=spin,
        external_field=external_field,
        read_data_file=read_data_file,
        read_restart_file=read_restart_file,
    )
    lines += [
        f'print "===== STAGE: {stage_label.upper()} (POLAR) ====="',
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
        f"restart         {restart_every_steps} {output_restart}.*",
        f"run             {nsteps}",
        "unfix           md",
        "undump          traj",
        f"write_data      {output_data} nocoeff",
        f"write_restart   {output_restart}",
        "",
    ]
    return "\n".join(lines) + "\n"


# =============================================================================
# Stage runners (Polar siblings of run_minimisation_stage / run_nvt_stage)
# =============================================================================
#
# These reuse lc._run_lammps_stage(), lc.write_lammps_structure(),
# lc.load_stage_state()/save_stage_state(), lc._read_last_frame_for_resume(),
# lc._infer_element_order_from_prior_stage() etc. unchanged — only the input
# text generation and model resolution differ from the non-Polar versions.

def run_minimisation_polar_stage(
    *,
    atoms: Atoms,
    stage_dir: Path,
    model_path: str,
    charge: float,
    spin: float,
    external_field: Tuple[float, float, float],
    lammps_bin: Optional[str] = None,
    timestep_fs: float = 0.5,
    save_pdb: bool = False,
) -> dict:
    stage_dir.mkdir(parents=True, exist_ok=True)

    state_path = stage_dir / "minimisation.state.json"
    restart_path = stage_dir / "minimisation.restart"
    dump_path = stage_dir / "minimisation.lammpstrj"
    traj_path = stage_dir / lc.TRAJ_PDB
    last_frame_path = stage_dir / lc.LAST_FRAME_PDB
    csv_path = stage_dir / "minimisation.csv"
    view_log_path = stage_dir / lc.MIN_VIEW_LOG

    state = lc.load_stage_state(state_path)
    if state.get("status") == "completed" and restart_path.exists():
        print(f"    ↪ Minimisation (Polar) already completed; loading from {stage_dir}")
        atoms_out = lc._read_last_frame_for_resume(last_frame_path, dump_path)
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

    model_pt = ensure_polar_mliap_model(model_path)

    data_path = stage_dir / "starting_structure.lammps"
    element_order, _ = lc.write_lammps_structure(atoms, data_path)

    input_text = build_minimisation_polar_input(
        data_filename=data_path.name,
        model_pt=model_pt,
        element_order=element_order,
        output_dump="minimisation.lammpstrj",
        output_data="minimised_structure.lammps",
        output_restart=restart_path.name,
        timestep_fs=timestep_fs,
        charge=charge,
        spin=spin,
        external_field=external_field,
    )

    atoms_out, elapsed, rows, _ = lc._run_lammps_stage(
        input_text=input_text,
        stage_dir=stage_dir,
        input_filename="minimisation.in",
        log_filename="log.lammps",
        dump_filename="minimisation.lammpstrj",
        traj_name=lc.TRAJ_PDB,
        last_frame_name=lc.LAST_FRAME_PDB,
        csv_name="minimisation.csv",
        view_log_name=lc.MIN_VIEW_LOG,
        state_name="minimisation.state.json",
        lammps_bin=lammps_bin,
        timestep_fs=timestep_fs,
        save_trajectory_pdb=save_pdb,
    )

    final_T, final_P, final_V = lc.final_thermo_values(rows)
    if final_V is None:
        final_V = atoms_out.get_volume()

    state.update({
        "stage": "Minimisation (Polar)",
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
        "polar_context": {"charge": charge, "spin": spin, "external_field": list(external_field)},
    })
    lc.save_stage_state(state_path, state)

    print(f"    ✅ Minimisation (Polar) done: {elapsed:.0f}s | Final V={final_V:.1f} Å³")

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


def run_nvt_polar_stage(
    *,
    stage_dir: Path,
    model_path: str,
    temp_K: float,
    nsteps: int,
    stage_label: str,
    init_velocities: bool,
    traj_name: str,
    view_log_name: str,
    charge: float,
    spin: float,
    external_field: Tuple[float, float, float],
    timestep_fs: float = 0.5,
    lammps_bin: Optional[str] = None,
    input_atoms: Optional[Atoms] = None,
    read_restart_path: Optional[Path] = None,
    save_pdb: bool = False,
    restart_every_steps: int = 100,
    resume_mode: str = "reuse",
) -> dict:
    """
    Polar sibling of lc.run_nvt_stage(). Same resume/extend/overwrite
    semantics; only input-text generation and model resolution differ.
    """
    stage_dir.mkdir(parents=True, exist_ok=True)

    state_path = stage_dir / "state.json"
    traj_path = stage_dir / traj_name
    last_frame_path = stage_dir / lc.LAST_FRAME_PDB
    label_lower = stage_label.lower().replace(" ", "_")
    dump_path = stage_dir / f"{label_lower}.lammpstrj"
    csv_path = stage_dir / f"{label_lower}.csv"
    restart_path = stage_dir / f"{label_lower}.restart"
    view_log_path = stage_dir / view_log_name

    state = lc.load_stage_state(state_path)

    resume_from_existing_stage = False
    effective_init_velocities = init_velocities
    old_steps = int(state.get("completed_steps", 0)) if state else 0

    if state.get("status") == "completed" and restart_path.exists():
        if old_steps == nsteps:
            print(f"    ↪ {stage_label} (Polar) already completed for requested length; loading from {stage_dir}")
            atoms_out = lc._read_last_frame_for_resume(last_frame_path, dump_path)
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

        if old_steps > nsteps:
            if resume_mode == "overwrite":
                print(f"    ↻ {stage_label} (Polar): existing run has {old_steps} steps, "
                      f"but requested {nsteps}; overwrite requested, rerunning stage.")
            else:
                raise ValueError(
                    f"{stage_label} (Polar) already completed with {old_steps} steps in {stage_dir}, "
                    f"longer than requested {nsteps} steps. Use overwrite mode to replace it."
                )
        elif old_steps < nsteps:
            if resume_mode == "overwrite":
                print(f"    ↻ {stage_label} (Polar): existing shorter run has {old_steps} steps, "
                      f"but overwrite requested; rerunning full stage from scratch.")
            else:
                print(f"    ↪ {stage_label} (Polar): existing completed run has {old_steps} steps; "
                      f"continuing to requested {nsteps} steps from {restart_path}")
                resume_from_existing_stage = True
                effective_init_velocities = False

    if not resume_from_existing_stage:
        if (input_atoms is None) == (read_restart_path is None):
            raise ValueError(
                "Provide exactly one of input_atoms or read_restart_path to "
                "run_nvt_polar_stage() when not resuming an existing stage."
            )

    model_pt = ensure_polar_mliap_model(model_path)

    read_data_file = None
    read_restart_file = None

    if resume_from_existing_stage:
        element_order = state.get("element_order")
        if not element_order:
            element_order = lc._infer_element_order_from_prior_stage(restart_path)
        read_restart_file = str(restart_path.resolve())
    elif input_atoms is not None:
        data_path = stage_dir / "starting_structure.lammps"
        element_order, _ = lc.write_lammps_structure(input_atoms, data_path)
        read_data_file = data_path.name
    else:
        if not read_restart_path.exists():
            raise FileNotFoundError(f"Restart file not found: {read_restart_path}")
        element_order = lc._infer_element_order_from_prior_stage(read_restart_path)
        read_restart_file = str(read_restart_path.resolve())

    if resume_from_existing_stage:
        steps_to_run = nsteps - old_steps
        if steps_to_run <= 0:
            raise ValueError(
                f"{stage_label} (Polar): computed non-positive remaining steps "
                f"({steps_to_run}) while trying to resume."
            )
    else:
        steps_to_run = nsteps

    input_text = build_nvt_polar_input(
        model_pt=model_pt,
        element_order=element_order,
        temp_K=temp_K,
        nsteps=steps_to_run,
        stage_label=stage_label,
        output_dump=f"{label_lower}.lammpstrj",
        output_data=f"{label_lower}.lammps",
        output_restart=restart_path.name,
        timestep_fs=timestep_fs,
        init_velocities=effective_init_velocities,
        charge=charge,
        spin=spin,
        external_field=external_field,
        read_data_file=read_data_file,
        read_restart_file=read_restart_file,
        restart_every_steps=restart_every_steps,
    )

    atoms_out, elapsed, rows, _ = lc._run_lammps_stage(
        input_text=input_text,
        stage_dir=stage_dir,
        input_filename=f"{label_lower}.in",
        log_filename="log.lammps",
        dump_filename=f"{label_lower}.lammpstrj",
        traj_name=traj_name,
        last_frame_name=lc.LAST_FRAME_PDB,
        csv_name=f"{label_lower}.csv",
        view_log_name=view_log_name,
        state_name="state.json",
        lammps_bin=lammps_bin,
        timestep_fs=timestep_fs,
        save_trajectory_pdb=save_pdb,
    )

    final_T, final_P, final_V = lc.final_thermo_values(rows)
    if final_V is None:
        final_V = atoms_out.get_volume()

    previous_elapsed = float(state.get("elapsed_seconds", 0.0)) if resume_from_existing_stage else 0.0
    total_elapsed = previous_elapsed + elapsed

    state.update({
        "stage": stage_label + " (Polar)",
        "temperature_K": temp_K,
        "status": "completed",
        "elapsed_seconds": total_elapsed,
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
        "polar_context": {"charge": charge, "spin": spin, "external_field": list(external_field)},
    })
    lc.save_stage_state(state_path, state)

    if resume_from_existing_stage:
        print(f"    ✅ {stage_label} (Polar) extended by {steps_to_run} steps "
              f"(total now {nsteps}) : {elapsed:.0f}s this run | "
              f"Final T={(final_T if final_T is not None else float('nan')):.1f} K | "
              f"Final V={final_V:.1f} Å³")
    else:
        print(f"    ✅ {stage_label} (Polar) done: {elapsed:.0f}s | "
              f"Final T={(final_T if final_T is not None else float('nan')):.1f} K | "
              f"Final V={final_V:.1f} Å³")

    if csv_path.exists():
        plot_path = stage_dir / f"{label_lower}_temp.png"
        saved = lc.maybe_plot_temp(
            csv_path, temp_K,
            f"{stage_label} (Polar) — Temperature vs Time ({temp_K:g} K)",
            plot_path,
        )
        if saved:
            print(f"    💾 Saved plot: {plot_path}")

    return {
        "atoms": atoms_out,
        "elapsed_s": total_elapsed,
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