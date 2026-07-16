#!/usr/bin/env python3
"""
run_npt_lammps.py
==================

Runs a full NPT MD pipeline for one Piezoelectric Molecular Crystal (PMC)
compound in LAMMPS, driven by ANY MACE-family model registered below --
provided that model has a LAMMPS-compatible .pt export (mliap unified
interface). Three stages run in sequence, one script call:

    minimization  ->  NPT equilibration  ->  NPT production

The only structural difference from run_nvt_lammps.py is the thermodynamic
ensemble: `fix npt` instead of `fix nvt`, which additionally couples a
barostat to the target --pressure. Everything else (registry, state
tracking, folder layout, dual step/ps input, adaptive logging) is identical
by design, so the two scripts stay easy to reason about side by side.

Each stage gets its own subfolder with its own state.json / restart.restart /
stage.log / structure.pdb, so any stage can be independently resumed without
touching the others.

This script is fully self-contained: no imports from sibling scripts
(run_npt_lammps.py, run_nvt_ase.py, rdf_compare.py, etc). RDF plotting is
DELIBERATELY NOT done here -- run rdf_compare.py afterward against
production/traj.extxyz. That keeps this script's only downstream contract
being "I produce a valid, standardized .extxyz trajectory," regardless of
what analysis you run on it later or how many times you re-run that analysis.

Usage (steps):
    python run_npt_lammps.py --pmc PMC-023 --model mace-off23 --version medium \
        --temperature 300 --pressure 1.0 --minimize-steps 500 --equil-step 5000 --target-step 50000

Usage (picoseconds instead of steps):
    python run_npt_lammps.py --pmc PMC-023 --model mace-off23 --version medium \
        --temperature 300 --pressure 1.0 --minimize-steps 500 --equil-ps 10 --target-ps 100

===============================================================================
HOW THIS SCRIPT ACTUALLY WORKS, END TO END (read this before touching anything)
===============================================================================

0. ENVIRONMENT -- this script does NOT create or activate any environment
   itself. It assumes one is ALREADY ACTIVE before you run it, providing:
     - `torch`, `mace`, `ase` importable in this Python
     - an `lmp` binary on PATH that supports the ML-IAP unified interface
   In practice that means `source env.sh` (or the run_pmc.sh wrapper, which
   does that sourcing for you) BEFORE calling this script. If you forget,
   you'll either get an ImportError immediately, or -- more dangerously --
   pick up a *different*, incompatible `lmp` binary from some other
   environment that happens to be active (this has actually happened: an
   older LAMMPS build without ML-IAP support silently shadowed the right
   one). That's exactly why check_lammps_binary() below prints the FULL
   resolved path of the lmp binary at startup and refuses to proceed if it
   doesn't support the required pair style -- don't remove that check.

1. MODEL SELECTION -- --model/--version (default: mace-off23/medium) look
   up an entry in the MODELS dict near the top of this file, which hardcodes
   the real file paths on disk (currently under ~/himesh_work/mace_models/).
   Run --list-models to see every registered combination and whether its
   .pt file is actually present.

2. STRUCTURE INPUT -- the source-of-truth CIF is found by globbing
   --cif-dir (default ~/himesh_work/data) for <PMC-ID>/*.cif. There must be
   exactly one .cif in that folder, or find_cif_for_pmc() errors loudly
   rather than guessing. The CIF is converted ONCE per (compound, supercell
   size) into a cached LAMMPS .data file under --data-dir, tagged with the
   supercell size so different --supercell-size values never collide.

3. THE THREE STAGES, IN ORDER, ONE SCRIPT CALL:
     minimization   -> LBFGS-style energy minimization, T=0, no thermostat/barostat
     equilibration  -> fix npt, brings the system to --temperature AND --pressure
     production     -> fix npt, the actual sampling run -> traj.extxyz
   Each stage is independently checkpointed (state.json + restart.restart,
   both OVERWRITTEN in place every --checkpoint-every steps, never
   accumulated as restart_1000.restart, restart_2000.restart, etc.) so any
   stage can resume on its own without re-running the ones before it.

4. WHERE OUTPUT GOES -- everything lands under:
     <--runs-dir>/<PMC-ID>/lammps-npt/<model>-<version>/<T>K_<P>bar_<N>x<N>x<N>/
       minimization/    equilibration/    production/
   This nesting (engine-ensemble / model-version / temperature+pressure+
   supercell) is deliberate: running the same compound at several
   temperatures/pressures produces clean SIBLING folders under the same
   model-version, instead of one long unwieldy folder name -- and syncing
   only LAMMPS-NPT results elsewhere (e.g. to a local machine) is then just
   "grab the lammps-npt/ subtree."

5. RESUME BEHAVIOR -- by default, rerunning the exact same command
   auto-detects and continues from the last checkpoint (compares
   last_completed_step against the newly requested target, never trusts a
   stale "status" string alone). Pass --fresh --confirm-fresh together to
   deliberately discard all checkpoints and start over -- --fresh alone is
   refused on purpose, so a single mistaken flag can't destroy hours of
   progress.
"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time
import atexit
import atexit
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Model registry (Section 4 of the original spec) -- hardcoded here on
# purpose, no shared config file across scripts. Add a model = add one line.
# ---------------------------------------------------------------------------
MODELS = {
    "mace-off23": {
        "small":  {"path": "~/himesh_work/mace_models/MACE-OFF23_small.model",  "lammps_pt": "~/himesh_work/mace_models/MACE-OFF23_small.model-mliap_lammps.pt",  "lammps_style": "mliap", "cutoff": 5.0},
        "medium": {"path": "~/himesh_work/mace_models/MACE-OFF23_medium.model", "lammps_pt": "~/himesh_work/mace_models/MACE-OFF23_medium.model-mliap_lammps.pt", "lammps_style": "mliap", "cutoff": 5.0},
        "large":  {"path": "~/himesh_work/mace_models/MACE-OFF23_large.model",  "lammps_pt": "~/himesh_work/mace_models/MACE-OFF23_large.model-mliap_lammps.pt",  "lammps_style": "mliap", "cutoff": 5.0},
    },
    "polarmace": {
        "small": {
            "path": "~/himesh_work/mace_models/MACE-POLAR-1-S.model",
            "lammps_pt": None,
            "cutoff": 6.0,
            "notes": "LAMMPS unsupported -- ACEsuit/mace#1409 (KeyError: 'fermi level' in LAMMPS-MLIAP)",
        },
        "medium": {
            "path": "~/himesh_work/mace_models/MACE-POLAR-1-M.model",
            "lammps_pt": None,
            "cutoff": 6.0,
            "notes": "LAMMPS unsupported -- ACEsuit/mace#1409 (KeyError: 'fermi level' in LAMMPS-MLIAP)",
        },
        "large": {
            "path": "~/himesh_work/mace_models/MACE-POLAR-1-L.model",
            "lammps_pt": None,
            "cutoff": 6.0,
            "notes": "LAMMPS unsupported -- ACEsuit/mace#1409 (KeyError: 'fermi level' in LAMMPS-MLIAP)",
        },
    },
}


def find_cif_for_pmc(cif_dir, pmc_id):
    """
    Locate the CIF for a compound inside its own subfolder, WITHOUT assuming
    an exact filename. Real filenames turned out to be PMC-ID + a compound
    slug (e.g. PMC-001-gamma-glycine.cif), not a bare <PMC-ID>.cif -- so we
    glob for any .cif in the folder instead of guessing the naming scheme.
    Fails loudly and specifically if zero or more than one CIF is found,
    rather than silently picking one.
    """
    pmc_folder = os.path.join(os.path.expanduser(cif_dir), pmc_id)
    if not os.path.isdir(pmc_folder):
        raise FileNotFoundError(f"No folder found for {pmc_id} at {pmc_folder}")

    matches = sorted(glob.glob(os.path.join(pmc_folder, "*.cif")))
    if not matches:
        raise FileNotFoundError(f"No .cif file found inside {pmc_folder}")
    if len(matches) > 1:
        raise FileNotFoundError(
            f"Multiple .cif files found inside {pmc_folder}, expected exactly one: {matches}. "
            f"Remove/rename the extras, or point --cif-dir at a more specific location."
        )
    return matches[0]


def resolve_model(model_family, model_size):
    """Validate (family, size) exists and has a usable LAMMPS .pt file present on disk."""
    family_entry = MODELS.get(model_family)
    if family_entry is None:
        raise ValueError(f"Unknown model family '{model_family}'. Known: {sorted(MODELS.keys())}")

    size_entry = family_entry.get(model_size)
    if size_entry is None:
        raise ValueError(f"Unknown size '{model_size}' for '{model_family}'. Known: {sorted(family_entry.keys())}")

    lammps_pt = size_entry.get("lammps_pt")
    if lammps_pt is None:
        note = size_entry.get("notes", "no LAMMPS-compatible .pt file registered for this model")
        raise NotImplementedError(f"{model_family}/{model_size} cannot run on the LAMMPS engine: {note}")

    resolved_path = os.path.expanduser(lammps_pt)
    if not os.path.exists(resolved_path):
        raise FileNotFoundError(
            f"{model_family}/{model_size} is registered for LAMMPS but {resolved_path} was not found on disk."
        )

    return {"family": model_family, "size": model_size, "lammps_pt": resolved_path, "cutoff": size_entry["cutoff"],
            "lammps_style": size_entry.get("lammps_style", "mace")}


# ---------------------------------------------------------------------------
# State tracking -- single file, always overwritten, per STAGE
# ---------------------------------------------------------------------------

STATE_FILENAME = "state.json"
RESTART_FILENAME = "restart.restart"


def get_run_action(state_path, new_target_step):
    """
    skip / resume / start_fresh, decided ONLY by comparing last_completed_step
    against the newly requested target_step -- never by trusting an old
    'status' string alone (that was the source of a real bug: a stage marked
    "completed" for an old lower target would wrongly skip a request to
    extend it further).
    """
    if not os.path.exists(state_path):
        return "start_fresh"
    with open(state_path) as f:
        state = json.load(f)
    last_done = state.get("last_completed_step", 0)
    if last_done >= new_target_step:
        return "skip"
    elif last_done > 0:
        return "resume"
    return "start_fresh"


def load_state(state_path):
    if not os.path.exists(state_path):
        return None
    with open(state_path) as f:
        return json.load(f)


def write_state(state_path, **fields):
    """Overwritten in place every checkpoint -- write-temp-then-replace so a mid-write crash never corrupts it."""
    fields["last_updated"] = datetime.now(timezone.utc).isoformat()
    tmp_path = state_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(fields, f, indent=2)
    os.replace(tmp_path, state_path)


def append_log(log_path, message):
    """Every stage's own .log is append-only -- narrative lines interleaved with re-emitted LAMMPS thermo lines."""
    timestamp = datetime.now(timezone.utc).isoformat()
    with open(log_path, "a") as f:
        f.write(f"[{timestamp}] {message}\n")


def log(msg):
    print(msg, flush=True)


def log_stage_banner(stage_title):
    """
    Prints a clearly separated banner announcing the start of a new stage
    (minimization / equilibration / production), with blank-line spacing
    before and after, so scrolling through console output makes it obvious
    at a glance where one stage ends and the next begins -- rather than
    everything running together as one undifferentiated stream of LAMMPS
    output.
    """
    print(flush=True)
    print("=" * 60, flush=True)
    print(f"  STAGE: {stage_title.upper()}", flush=True)
    print("=" * 60, flush=True)


def format_hms(seconds):
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def adaptive_print_interval(total_steps, target_lines=25, min_interval=1000, max_interval=5000):
    """
    Scales the console/log progress-print interval to the run size, clamped
    to a sane range:
      - small runs (e.g. a few thousand steps): print at least every
        min_interval (1000) steps, so you're not left staring at nothing
      - large runs (e.g. millions of steps): print at most every
        max_interval (5000) steps, so a huge run doesn't go silent for ages
        between updates even though target_lines alone would space them
        much further apart
      - everything in between: aim for roughly target_lines prints total
    """
    raw = max(1, total_steps // target_lines)
    return max(min_interval, min(max_interval, raw))


# ---------------------------------------------------------------------------
# CIF -> LAMMPS .data conversion (cached once per compound)
# ---------------------------------------------------------------------------

def ensure_lammps_data(pmc_id, cif_path, data_dir, supercell_size):
    # Cache filename includes the supercell size -- a 2x2x2 and a 3x3x3
    # conversion of the same compound are genuinely different structures,
    # so they must never share a cache entry.
    tag = f"{supercell_size}x{supercell_size}x{supercell_size}"
    data_path = os.path.join(data_dir, f"{pmc_id}_{tag}.data")
    type_map_path = os.path.join(data_dir, f"{pmc_id}_{tag}_type_map.json")

    if os.path.exists(data_path) and os.path.exists(type_map_path):
        log(f"Structure cache hit: {data_path}")
        return data_path, type_map_path

    if not os.path.exists(cif_path):
        raise FileNotFoundError(f"Source CIF not found: {cif_path}")

    from ase.io import read, write
    atoms = read(cif_path)
    if supercell_size != 1:
        atoms = atoms.repeat((supercell_size, supercell_size, supercell_size))
        log(f"Built {tag} supercell: {len(atoms)} atoms")
    os.makedirs(data_dir, exist_ok=True)
    # atom_style "atomic" -- required by the ML-IAP unified interface (the
    # format your *-mliap_lammps.pt exports actually need); "full" was wrong
    # for this pair style even though it's a common LAMMPS default elsewhere.
    write(data_path, atoms, format="lammps-data", atom_style="atomic")

    unique_symbols = sorted(set(atoms.get_chemical_symbols()))
    type_map = {str(i + 1): sym for i, sym in enumerate(unique_symbols)}
    with open(type_map_path, "w") as f:
        json.dump(type_map, f, indent=2)

    return data_path, type_map_path


# ---------------------------------------------------------------------------
# .in templates -- one per stage, since the physics commands genuinely differ
# (minimize has no thermostat/timestep-dynamics; equilibration/production
# both use fix npt but read_restart differs on resume).
# ---------------------------------------------------------------------------

def build_structure_block(mode, data_path=None, restart_path=None):
    """
    Two genuinely different ways to load the simulation box/atoms, and
    picking the wrong one either crashes ("read_restart after box defined")
    or, much worse, silently DISCARDS all prior physical state:

    - "read_data": only ever used by MINIMIZATION, the one true entry point
      of the pipeline -- reads the raw, unequilibrated CIF-derived
      structure. No other stage should ever do this.

    - "read_restart": used by EVERY equilibration/production invocation,
      whether resuming that stage's own progress (restart_path = that
      stage's own restart.restart) or starting that stage for the first
      time (restart_path = the PRECEDING stage's restart.restart). This
      was a real, serious bug caught on an actual run: production's first
      invocation ever used to fall through to "read_data" on the raw CIF
      structure -- completely bypassing equilibration's actual thermalized
      state, meaning production silently started over from T=0K, zero
      velocities, straight into a full thermostat/barostat every single
      time. That cold start is almost certainly what caused the violent
      NPT instability (temperature overshoot, box collapse, eventual
      CUDA-level crash) seen in a real run -- production was never
      actually continuing from equilibration at all.

    Either way, pair_style/pair_coeff/mass must still be specified
    AFTERWARD (below, in COMMON_HEADER) -- restart files do NOT store
    force-field settings, only the atomic/box state.
    """
    if mode == "read_data":
        return f"atom_style      atomic\nboundary        p p p\nread_data       {data_path}"
    else:
        return f"read_restart    {restart_path}"


def build_velocity_block(action, temperature):
    """
    Minimization ends at ABSOLUTE ZERO -- it's an energy minimization, so
    every atom has exactly zero velocity. The restart file faithfully
    carries those zero velocities forward, which means a freshly-started
    equilibration would begin at T=0K and have to be heated from nothing by
    the thermostat alone. That cold start is violent and artificial: the
    thermostat (and, in NPT, the barostat reacting to the resulting pressure
    spikes) has to inject an entire system's worth of kinetic energy almost
    instantly, which in a real run produced a temperature overshoot to
    ~996K and a collapsing simulation box.

    The standard fix, and what every conventional MD protocol does at the
    minimization->MD transition: assign initial velocities from a
    Maxwell-Boltzmann distribution at the target temperature, so the
    thermostat only has to make small corrections instead of creating all
    the kinetic energy from scratch.

    CRITICAL: only ever do this on a FRESH start. On resume, the restart
    file already carries properly thermalized velocities from where the run
    left off -- re-randomizing them would destroy the trajectory's continuity
    and silently corrupt the physics of a resumed run.

    `mom yes rot yes` zeroes net linear/angular momentum so the whole system
    doesn't drift or spin -- otherwise that bulk motion pollutes the
    temperature reading.
    """
    if action == "resume":
        return "# Resuming -- velocities come from the restart file, do NOT re-randomize."
    return (
        f"velocity        all create {temperature} 12345 dist gaussian mom yes rot yes"
    )


def build_pair_block(model, type_symbols):
    """
    Two genuinely different LAMMPS interfaces exist for MACE models, and
    picking the wrong one crashes at runtime rather than failing to parse:

    - "mace": the libtorch/TorchScript interface, `pair_style mace`, for
      *-lammps.pt exports.
    - "mliap": the newer ML-IAP unified interface, `pair_style mliap unified`,
      for *-mliap_lammps.pt exports (what mace-off23 actually gives us here).
      The trailing "0" is a REQUIRED ghostneigh toggle for this interface,
      not optional -- omitting it is a silent-until-runtime bug.
    """
    if model["lammps_style"] == "mliap":
        return (
            f"pair_style      mliap unified {model['lammps_pt']} 0\n"
            f"pair_coeff      * * {type_symbols}"
        )
    else:
        return (
            f"pair_style      mace no_domain_decomposition\n"
            f"pair_coeff      * * {model['lammps_pt']} {type_symbols}"
        )


def build_mass_lines(type_map):
    """
    LAMMPS with atom_style atomic requires an explicit `mass <type> <value>`
    line for EVERY numeric type, or it refuses to run at all ("Not all
    per-type masses are set"). The pair style itself (mliap/mace) does NOT
    supply this -- it was a real, easy-to-miss gap: the .data file and the
    pair_coeff line don't communicate atomic mass to LAMMPS on their own.
    We look up standard atomic weights from ASE's own periodic table (same
    source of truth already used elsewhere in this script for CIF/structure
    handling) rather than hardcoding a second, potentially-incomplete table.
    """
    from ase.data import atomic_masses, atomic_numbers
    lines = []
    for type_id in sorted(type_map, key=int):
        symbol = type_map[type_id]
        mass = atomic_masses[atomic_numbers[symbol]]
        lines.append(f"mass            {type_id} {mass:.4f}")
    return "\n".join(lines)


COMMON_HEADER = """\
# Auto-generated by run_npt_lammps.py -- do not hand-edit, re-run the script instead.
# compound={pmc_id}  model={model_family}/{model_size}  stage={stage}
units           metal
{structure_block}
{mass_block}
{pair_block}
"""

MINIMIZE_TEMPLATE = COMMON_HEADER + """
# Minimization: no thermostat, no MD timestep dynamics -- just relaxing the
# raw CIF-derived geometry before any dynamics start.
thermo          10
thermo_style    custom step pe fnorm
minimize        1.0e-8 1.0e-8 {max_iterations} {max_iterations}

write_dump      all custom minimized.lammpstrj id type x y z modify sort id
write_restart   {restart_placeholder}
"""

EQUIL_TEMPLATE = COMMON_HEADER + """
timestep        {timestep}
{velocity_block}
fix             1 all npt temp {temperature} {temperature} {tdamp} iso {pressure} {pressure} {pdamp}

thermo          {print_every}
thermo_style    custom step temp pe vol cella cellb cellc

restart         {checkpoint_every} {restart_file} {restart_file}

run             {target_step} upto

write_restart   {restart_file}
write_dump      all custom equil_final.lammpstrj id type x y z modify sort id
"""

PRODUCTION_TEMPLATE = COMMON_HEADER + """
timestep        {timestep}
{velocity_block}
fix             1 all npt temp {temperature} {temperature} {tdamp} iso {pressure} {pressure} {pdamp}

thermo          {print_every}
thermo_style    custom step temp pe vol cella cellb cellc

restart         {checkpoint_every} {restart_file} {restart_file}

dump            traj_dump all custom {dump_every} {traj_file_raw} id type x y z
dump_modify     traj_dump sort id

run             {target_step} upto

write_restart   {restart_file}
"""


# ---------------------------------------------------------------------------
# LAMMPS execution -- streams stdout live so progress lines print in real time
# ---------------------------------------------------------------------------

def run_lammps(in_path, stage_dir, log_path, lammps_binary="lmp", gpu=False, stage_name="", target_step=None, timestep_ps=None):
    # in_path must be made absolute BEFORE the subprocess call below, because
    # the subprocess's cwd is set to stage_dir -- if in_path were left as a
    # path relative to the ORIGINAL working directory (e.g.
    # "runs/PMC-001/.../minimization/generated.in"), LAMMPS would try to
    # resolve that same relative path AGAIN, this time relative to
    # stage_dir, and fail with "No such file or directory" even though the
    # file genuinely exists. This bit us in a real run -- don't remove.
    in_path = os.path.abspath(in_path)

    # When a program's stdout is piped (as it is here, into this Python
    # process) rather than connected to a real terminal, the C standard
    # library it's built against often silently switches from
    # line-buffered to fully block-buffered output. LAMMPS can then be
    # computing completely normally while APPEARING to hang -- nothing
    # reaches us until its internal buffer fills (often several KB) or the
    # process exits. `stdbuf -oL -eL` forces line-buffering on stdout/
    # stderr regardless of what's on the other end, restoring real-time
    # progress visibility. Falls back to running without it (same
    # possible-appears-stuck behavior as before) if stdbuf isn't available.
    if shutil.which("stdbuf"):
        cmd = ["stdbuf", "-oL", "-eL", lammps_binary]
    else:
        cmd = [lammps_binary]

    if gpu:
        # Required for GPU execution with the ML-IAP unified interface --
        # without these flags LAMMPS runs on CPU even if compiled with
        # Kokkos/CUDA support, silently leaving GPU performance on the table.
        cmd += ["-k", "on", "g", "1", "-sf", "kk", "-pk", "kokkos", "newton", "on", "neigh", "half"]
    cmd += ["-in", in_path, "-log", "none"]  # LAMMPS's own log folded into our stage.log instead

    run_start = time.time()
    process = subprocess.Popen(cmd, cwd=stage_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

    thermo_header = None  # column names of whatever thermo table is currently streaming
    with open(log_path, "a") as f:
        for line in process.stdout:
            f.write(line)  # ALWAYS log the full, untouched raw line -- nothing lost for debugging

            stripped = line.strip()

            # Detect the start of a thermo table (works for both minimize's
            # "Step PotEng Fnorm" and MD's "Step Temp PotEng Volume Cella...").
            if stripped.startswith("Step") and len(stripped.split()) >= 2:
                thermo_header = stripped.split()
                continue

            if thermo_header:
                parts = stripped.split()
                if len(parts) == len(thermo_header) and parts[0].lstrip("-").isdigit():
                    step = int(parts[0])

                    def col(name):
                        return float(parts[thermo_header.index(name)]) if name in thermo_header else None

                    temp_val, pe_val, vol_val = col("Temp"), col("PotEng"), col("Volume")
                    a_val, b_val, c_val = col("Cella"), col("Cellb"), col("Cellc")

                    if temp_val is not None:
                        # Full MD-stage line, matching the requested format exactly.
                        time_ps = step * timestep_ps if timestep_ps else 0.0
                        line_out = (
                            f"      Step {step:<8d} | {time_ps:6.1f} ps | T={temp_val:6.1f} K | "
                            f"E={pe_val:12.2f} eV"
                        )
                        if vol_val is not None:
                            line_out += f" | V={vol_val:8.1f} \u00c5\u00b3"
                        if a_val is not None:
                            line_out += f" | a={a_val:.3f} b={b_val:.3f} c={c_val:.3f}"
                    else:
                        # Minimization-stage line (no temperature/cell dynamics).
                        line_out = f"      Step {step:<8d} | PE={pe_val:12.2f} eV"

                    sys.stdout.write(line_out + "\n")
                    sys.stdout.flush()
                    continue
                else:
                    thermo_header = None  # table ended (blank line, "Loop time...", etc.)

            # Everything else (LAMMPS version banner, Kokkos setup chatter,
            # citation blocks, neighbor-list setup details, the end-of-run
            # Loop-time/MPI-timing/histogram stats block, compatibility
            # warnings, etc) is real and useful for DEBUGGING, so it always
            # goes into the log file above -- but it's not useful for
            # WATCHING a run, so none of it reaches the console by default.
            # The one exception: genuine errors always surface immediately,
            # since those need to be seen right away, not just logged.
            if "ERROR" in line:
                sys.stdout.write(line)

    process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"LAMMPS exited with code {process.returncode}; see {log_path}")


# ---------------------------------------------------------------------------
# structure.pdb writer -- one at the end of every stage, from whatever the
# stage's most recent structural output was (minimized dump / final MD frame)
# ---------------------------------------------------------------------------

def convert_lammpstrj_to_extxyz(raw_lammpstrj_path, extxyz_out_path, type_map):
    """
    This LAMMPS build lacks the EXTRA-DUMP package, so `dump ... extxyz`
    isn't available at all -- this was an open question in the original
    spec ("confirm whether EXTRA-DUMP is available, or whether
    .lammpstrj->extxyz conversion is required") and the answer, confirmed
    against a real run, is: conversion is required.

    Reads every frame from the raw `dump ... custom ... id type x y z`
    output (which every LAMMPS build supports) and rewrites it as the
    standardized .extxyz trajectory format used for all downstream analysis,
    regardless of engine -- matching the ORIGINAL requirement that only
    .extxyz ever leaves this pipeline as the analysis-ready trajectory.

    `specorder` (a LIST, not a dict) maps LAMMPS numeric type -> element
    symbol, e.g. type 1 -> specorder[0]. We build it directly from type_map
    (already type_id -> symbol) so both stay in sync automatically.
    """
    from ase.io import read, write
    specorder = [type_map[str(i + 1)] for i in range(len(type_map))]
    frames = read(raw_lammpstrj_path, index=":", format="lammps-dump-text", specorder=specorder)
    write(extxyz_out_path, frames, format="extxyz")


def write_stage_pdb(source_structure_path, source_format, pdb_out_path):
    from ase.io import read, write
    atoms = read(source_structure_path, format=source_format)
    write(pdb_out_path, atoms, format="proteindatabank")


# ---------------------------------------------------------------------------
# Equilibration temp-vs-time plot -- parsed directly out of equilibration.log,
# no separate CSV kept (fewer files).
# ---------------------------------------------------------------------------

def plot_temp_vs_time(equil_log_path, timestep_ps, png_out_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    steps, temps = [], []
    in_thermo_block = False
    with open(equil_log_path) as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("Step") and "Temp" in stripped:
                in_thermo_block = True
                continue
            if in_thermo_block:
                parts = stripped.split()
                if len(parts) >= 2 and parts[0].lstrip("-").isdigit():
                    try:
                        steps.append(int(parts[0]))
                        temps.append(float(parts[1]))
                    except ValueError:
                        in_thermo_block = False
                else:
                    in_thermo_block = False

    if not steps:
        log("WARNING: no thermo data parsed from equilibration.log -- skipping temp_vs_time.png")
        return

    times_ps = [s * timestep_ps for s in steps]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(times_ps, temps, linewidth=1.2)
    ax.set_xlabel("Time (ps)")
    ax.set_ylabel("Temperature (K)")
    ax.set_title("Equilibration: Temperature vs Time")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(png_out_path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Stage runner (shared logic across equilibrate/produce)
# ---------------------------------------------------------------------------

def steps_from_args(steps_arg, ps_arg, timestep_ps, label):
    if steps_arg is not None and ps_arg is not None:
        raise ValueError(f"Give either --{label}-step or --{label}-ps, not both.")
    if steps_arg is not None:
        return steps_arg
    if ps_arg is not None:
        return int(round(ps_arg / timestep_ps))
    return None


def run_equilibration_or_production(stage_name, template, stage_dir, pmc_id, model, data_path,
                                     type_symbols, type_map, args, target_step, prior_restart_rel, traj_filename=None):
    os.makedirs(stage_dir, exist_ok=True)
    state_path = os.path.join(stage_dir, STATE_FILENAME)
    log_path = os.path.join(stage_dir, f"{stage_name}.log")
    restart_path_full = os.path.join(stage_dir, RESTART_FILENAME)

    if args.fresh:
        # --fresh means: ignore and discard any prior progress for this stage,
        # not just "pretend" to start over -- so the stale restart/state files
        # are actually removed rather than left sitting there to confuse a
        # future run that forgets to pass --fresh again.
        if os.path.exists(state_path) or os.path.exists(restart_path_full):
            log(f"[{stage_name}] --fresh given: discarding existing checkpoint")
            append_log(log_path, "--fresh given: discarding existing state.json/restart.restart")
        if os.path.exists(state_path):
            os.remove(state_path)
        if os.path.exists(restart_path_full):
            os.remove(restart_path_full)
        action = "start_fresh"
        last_done = 0
    else:
        action = get_run_action(state_path, target_step)
        last_done = load_state(state_path)["last_completed_step"] if action != "start_fresh" else 0

    if action == "skip":
        log(f"[{stage_name}] last_completed_step={last_done}, target={target_step} -> already complete, skipping")
        append_log(log_path, f"Skip (already at step {last_done} >= target {target_step})")
        return

    steps_this_invocation = target_step if action == "start_fresh" else (target_step - last_done)

    if action == "resume":
        log(f"[{stage_name}] Resuming from step {last_done} -> target {target_step} using {RESTART_FILENAME}")
        append_log(log_path, f"Resuming from step {last_done} toward target {target_step}")
    else:
        log(f"[{stage_name}] Starting fresh -> target {target_step}")
        append_log(log_path, f"Starting fresh toward target {target_step}")

    print_every = adaptive_print_interval(steps_this_invocation)

    timestep_ps = args.timestep / 1000.0  # unified --timestep is in fs; LAMMPS wants ps
    fmt_kwargs = dict(
        pmc_id=pmc_id, model_family=model["family"], model_size=model["size"], stage=stage_name,
        data_path=data_path, lammps_pt=model["lammps_pt"], type_symbols=type_symbols,
        structure_block=build_structure_block(
            "read_restart",
            restart_path=(RESTART_FILENAME if action == "resume" else prior_restart_rel),
        ),
        pair_block=build_pair_block(model, type_symbols), mass_block=build_mass_lines(type_map),
        velocity_block=build_velocity_block(action, args.temperature),
        timestep=timestep_ps, tdamp=timestep_ps * 100, temperature=args.temperature,
        pressure=args.pressure, pdamp=timestep_ps * 1000,  # standard rule-of-thumb: pdamp ~1000x timestep, tdamp ~100x
        print_every=print_every, checkpoint_every=args.checkpoint_every,
        restart_file=RESTART_FILENAME, steps_this_invocation=steps_this_invocation, target_step=target_step,
    )
    if traj_filename:
        fmt_kwargs["dump_every"] = args.dump_every
        fmt_kwargs["traj_file_raw"] = "traj_raw.lammpstrj"

    in_content = template.format(**fmt_kwargs)
    in_path = os.path.join(stage_dir, "generated.in")
    with open(in_path, "w") as f:
        f.write(in_content)

    stage_start = time.time()
    run_lammps(in_path, stage_dir, log_path, lammps_binary=args.lammps_binary, gpu=args.gpu, stage_name=stage_name, target_step=target_step, timestep_ps=timestep_ps)
    elapsed = time.time() - stage_start

    if traj_filename:
        raw_traj_path = os.path.join(stage_dir, "traj_raw.lammpstrj")
        final_traj_path = os.path.join(stage_dir, traj_filename)
        convert_lammpstrj_to_extxyz(raw_traj_path, final_traj_path, type_map)
        if os.path.exists(raw_traj_path):
            os.remove(raw_traj_path)
        log(f"[{stage_name}] {traj_filename} written (converted from raw LAMMPS dump)")

    write_state(
        state_path, pmc_id=pmc_id, engine="lammps", model_family=model["family"], model_size=model["size"],
        stage=stage_name, temperature_K=args.temperature, last_completed_step=target_step, target_step=target_step,
        status="completed", restart_file=RESTART_FILENAME,
    )
    append_log(log_path, f"Checkpoint: reached step {target_step}, {RESTART_FILENAME}/{STATE_FILENAME} overwritten (not appended)")
    log(f"[{stage_name}] COMPLETE  step {target_step}/{target_step}  elapsed={format_hms(elapsed)} ({elapsed:.1f}s)")

    # structure.pdb at the end of every stage
    pdb_path = os.path.join(stage_dir, "structure.pdb")
    try:
        if traj_filename:
            write_stage_pdb(os.path.join(stage_dir, traj_filename), "extxyz", pdb_path)
        else:
            write_stage_pdb(os.path.join(stage_dir, "equil_final.lammpstrj"), "lammps-dump-text", pdb_path)
        log(f"[{stage_name}] structure.pdb written")
    except Exception as exc:
        log(f"WARNING: could not write structure.pdb for {stage_name}: {exc}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Full minimize -> equilibrate -> produce NPT pipeline, any MACE-family model, LAMMPS engine.")
    p.add_argument("--pmc", required=False, help="Compound ID, e.g. PMC-001. Required unless --list-models is used.")
    p.add_argument("--model", default="mace-off23", choices=sorted(MODELS.keys()), dest="model_family",
                    help="Which MACE model to use (default: mace-off23). "
                         "Run --list-models to see every model/version combination and whether it's usable on LAMMPS.")
    p.add_argument("--version", default="medium", choices=sorted({size for fam in MODELS.values() for size in fam.keys()}), dest="model_size",
                    help="Model version/size: small, medium, or large (default: medium). "
                         "Not every model has every version -- run --list-models to check.")
    p.add_argument("--list-models", action="store_true",
                    help="Print every model/version combination, whether it's usable "
                         "on the LAMMPS engine, and the resolved .pt path, then exit.")
    p.add_argument("--temperature", type=float, required=False, help="Kelvin. Required unless --list-models is used.")
    p.add_argument("--pressure", type=float, default=1.0, help="Target pressure in bar (default: 1.0, i.e. ~1 atm). Applied isotropically to the cell.")

    p.add_argument("--minimize-steps", type=int, default=500, help="Max minimization iterations (energy minimization, not MD steps)")

    # Equilibration / production: each accepts EITHER steps or picoseconds,
    # never both. Converted to steps immediately; everything downstream
    # (state.json, resume math) operates on step-counts only.
    p.add_argument("--equil-step", type=int)
    p.add_argument("--equil-ps", type=float)
    p.add_argument("--target-step", type=int)
    p.add_argument("--target-ps", type=float)

    p.add_argument("--checkpoint-every", type=int, default=500)
    p.add_argument("--dump-every", type=int, default=1000)
    p.add_argument("--supercell-size", type=int, default=2, help="N for an NxNxN supercell built from the CIF before simulating (default: 2)")
    p.add_argument("--timestep", type=float, default=1.0, help="MD timestep in FEMTOSECONDS (default: 1.0 fs) -- unified unit across all 4 scripts, converted internally to whatever each engine natively wants")

    p.add_argument("--cif-dir", default="~/himesh_work/data", help="Parent dir containing one folder per PMC-ID, each holding <PMC-ID>.cif")
    p.add_argument("--data-dir", default="structures/data")
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--lammps-binary", default="lmp")
    p.add_argument("--gpu", action="store_true", help="Pass Kokkos/GPU flags to lmp (requires a Kokkos+CUDA LAMMPS build)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--fresh", action="store_true",
                    help="Ignore any existing checkpoint and start every stage over from scratch "
                         "(deletes existing state.json/restart.restart per stage). Default behavior "
                         "without this flag is to auto-resume/skip based on existing progress. "
                         "MUST be paired with --confirm-fresh, or the script refuses to run -- this "
                         "is a deliberate safety gate so a single flag can't silently destroy a "
                         "long-running checkpoint (e.g. from an agent's mistaken inference).")
    p.add_argument("--confirm-fresh", action="store_true",
                    help="Required alongside --fresh to actually delete existing checkpoints. "
                         "Exists so --fresh alone is never enough to destroy progress by accident.")
    return p.parse_args()

# ---------------------------------------------------------------------------
# Safety/hardening helpers -- added so this script is safe to call from an
# unattended agent loop, not just interactively by a human who can read
# tracebacks. None of these change the physics; they change failure modes
# from "cryptic crash" or "silent data race" into "clear, structured error."
# ---------------------------------------------------------------------------

LOCK_FILENAME = ".run.lock"


def acquire_lock(condition_dir):
    """
    Refuses to run if another process already holds the lock for this exact
    condition folder AND that process's PID is still alive. Prevents two
    concurrent launches (human + agent, or two agent calls) from racing on
    the same state.json/restart.restart.
    """
    os.makedirs(condition_dir, exist_ok=True)
    lock_path = os.path.join(condition_dir, LOCK_FILENAME)
    if os.path.exists(lock_path):
        with open(lock_path) as f:
            old_pid = f.read().strip()
        try:
            os.kill(int(old_pid), 0)  # signal 0: check if PID is alive, doesn't actually kill
            raise RuntimeError(
                f"Another run appears to already be in progress for this exact condition "
                f"(lock held by PID {old_pid} at {lock_path}). Refusing to start a second one "
                f"against the same output folder. If that process is definitely dead, delete "
                f"{lock_path} manually and retry."
            )
        except (ValueError, ProcessLookupError, PermissionError):
            pass  # stale lock (process no longer exists) -- safe to take over
    with open(lock_path, "w") as f:
        f.write(str(os.getpid()))
    atexit.register(release_lock, condition_dir)


def release_lock(condition_dir):
    lock_path = os.path.join(condition_dir, LOCK_FILENAME)
    if os.path.exists(lock_path):
        try:
            os.remove(lock_path)
        except OSError:
            pass


def check_gpu_available():
    """
    Cheap pre-flight check for whether a GPU is actually visible on this
    node, BEFORE handing off to LAMMPS. Without this, --gpu on a node
    without a CUDA driver fails deep inside `lmp` with a cryptic
    "libcuda.so.1: cannot open shared object file" error that looks like a
    code bug rather than a "wrong node type" mistake -- this turns that into
    a clear, actionable message immediately.
    """
    try:
        result = subprocess.run(["nvidia-smi"], capture_output=True, timeout=10)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def check_lammps_binary(lammps_binary, required_style=None):
    """
    Resolves the FULL path of the lmp binary that will actually be used
    (not just the bare name), and -- if the model needs the ML-IAP unified
    interface -- verifies that build of LAMMPS actually supports it, by
    grepping `lmp -h`'s own package listing for "mliap".

    This exists because of a real, already-encountered failure mode: having
    two different lmp binaries reachable depending on which environment is
    active (e.g. an older stable build with no ML-IAP support vs. a
    develop-branch build-mliap install), which fails deep inside a LAMMPS
    run with a cryptic error that looks like a code bug rather than "wrong
    environment was active." Catching it here, loudly, before any GPU time
    is spent, is much cheaper than debugging it after a crash.
    """
    resolved = shutil.which(lammps_binary)
    if resolved is None:
        raise FileNotFoundError(
            f"'{lammps_binary}' not found on PATH. Is the right environment (env.sh) sourced?"
        )
    log(f"Using lmp binary: {resolved}")

    if required_style == "mliap":
        try:
            result = subprocess.run([resolved, "-h"], capture_output=True, text=True, timeout=30)
            help_text = (result.stdout + result.stderr).lower()
        except Exception as exc:
            log(f"WARNING: could not run '{resolved} -h' to verify ML-IAP support ({exc}) -- proceeding anyway")
            return resolved
        if "mliap" not in help_text:
            raise RuntimeError(
                f"The lmp binary at {resolved} does not appear to support the ML-IAP unified "
                f"interface (pair_style mliap) -- 'mliap' was not found in `lmp -h` output. "
                f"This model requires an ML-IAP-capable LAMMPS build. You are likely using the "
                f"wrong environment/lmp binary (e.g. an older stable build instead of the "
                f"develop/build-mliap install). Check which environment is active and which "
                f"lmp is first on PATH."
            )
    return resolved


def emit_result_json(status, **fields):
    """
    Prints one final, single-line JSON blob to stdout, prefixed so it's
    trivially greppable/parseable by an agent or wrapper script without
    having to text-scrape human-readable log lines. Always the LAST thing
    printed, success or failure.
    """
    payload = {"status": status, **fields}
    print("RESULT_JSON: " + json.dumps(payload), flush=True)

# ---------------------------------------------------------------------------
# Safety/hardening helpers -- added so this script is safe to call from an
# unattended agent loop, not just interactively by a human who can read
# tracebacks. None of these change the physics; they change failure modes
# from "cryptic crash" or "silent data race" into "clear, structured error."
# ---------------------------------------------------------------------------

LOCK_FILENAME = ".run.lock"


def acquire_lock(condition_dir):
    """
    Refuses to run if another process already holds the lock for this exact
    condition folder AND that process's PID is still alive. Prevents two
    concurrent launches (human + agent, or two agent calls) from racing on
    the same state.json/restart.restart.
    """
    os.makedirs(condition_dir, exist_ok=True)
    lock_path = os.path.join(condition_dir, LOCK_FILENAME)
    if os.path.exists(lock_path):
        with open(lock_path) as f:
            old_pid = f.read().strip()
        try:
            os.kill(int(old_pid), 0)  # signal 0: check if PID is alive, doesn't actually kill
            raise RuntimeError(
                f"Another run appears to already be in progress for this exact condition "
                f"(lock held by PID {old_pid} at {lock_path}). Refusing to start a second one "
                f"against the same output folder. If that process is definitely dead, delete "
                f"{lock_path} manually and retry."
            )
        except (ValueError, ProcessLookupError, PermissionError):
            pass  # stale lock (process no longer exists) -- safe to take over
    with open(lock_path, "w") as f:
        f.write(str(os.getpid()))
    atexit.register(release_lock, condition_dir)


def release_lock(condition_dir):
    lock_path = os.path.join(condition_dir, LOCK_FILENAME)
    if os.path.exists(lock_path):
        try:
            os.remove(lock_path)
        except OSError:
            pass


def check_gpu_available():
    """
    Cheap pre-flight check for whether a GPU is actually visible on this
    node, BEFORE handing off to LAMMPS. Without this, --gpu on a node
    without a CUDA driver fails deep inside `lmp` with a cryptic
    "libcuda.so.1: cannot open shared object file" error that looks like a
    code bug rather than a "wrong node type" mistake -- this turns that into
    a clear, actionable message immediately.
    """
    try:
        result = subprocess.run(["nvidia-smi"], capture_output=True, timeout=10)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def emit_result_json(status, **fields):
    """
    Prints one final, single-line JSON blob to stdout, prefixed so it's
    trivially greppable/parseable by an agent or wrapper script without
    having to text-scrape human-readable log lines. Always the LAST thing
    printed, success or failure.
    """
    payload = {"status": status, **fields}
    print("RESULT_JSON: " + json.dumps(payload), flush=True)


def main():
    args = parse_args()

    if args.list_models:
        print(f"{'family':<14} {'size':<10} {'LAMMPS-ready?':<15} {'.pt path (if ready)'}")
        print("-" * 80)
        for family, sizes in sorted(MODELS.items()):
            for size, entry in sorted(sizes.items()):
                if entry.get("lammps_pt"):
                    resolved = os.path.expanduser(entry["lammps_pt"])
                    ready = "yes" if os.path.exists(resolved) else "no (file missing)"
                    detail = resolved
                else:
                    ready = "no"
                    detail = entry.get("notes", "no LAMMPS .pt registered")
                print(f"{family:<14} {size:<10} {ready:<15} {detail}")
        return

    missing = [name for name, val in
               [("--pmc", args.pmc), ("--temperature", args.temperature)]
               if val is None]
    if missing:
        raise SystemExit(f"Missing required argument(s): {', '.join(missing)} "
                          f"(or run with --list-models to see available model options)")

    if args.fresh and not args.confirm_fresh:
        raise SystemExit(
            "--fresh was given without --confirm-fresh. Refusing to run: --fresh deletes any "
            "existing checkpoint (state.json/restart.restart) for every stage, which could destroy "
            "hours of prior progress. Pass BOTH --fresh --confirm-fresh if you're certain."
        )

    model = resolve_model(args.model_family, args.model_size)

    timestep_ps = args.timestep / 1000.0
    equil_target = steps_from_args(args.equil_step, args.equil_ps, timestep_ps, "equil")
    prod_target = steps_from_args(args.target_step, args.target_ps, timestep_ps, "target")
    if equil_target is None or prod_target is None:
        raise ValueError("Must supply both an equilibration length (--equil-step/--equil-ps) and a production length (--target-step/--target-ps).")

    cif_path = find_cif_for_pmc(args.cif_dir, args.pmc)
    condition_dir = os.path.join(
        args.runs_dir, args.pmc, "lammps-npt", f"{model['family']}-{model['size']}",
        f"{int(args.temperature)}K_{args.pressure:g}bar_{args.supercell_size}x{args.supercell_size}x{args.supercell_size}",
    )
    os.makedirs(condition_dir, exist_ok=True)
    acquire_lock(condition_dir)

    if args.gpu and not check_gpu_available():
        emit_result_json("error", pmc=args.pmc, message="--gpu was given but no GPU is visible on this node "
                          "(nvidia-smi failed/missing) -- you're likely on a login node, not a GPU compute node.")
        raise SystemExit(
            "--gpu was given but no GPU is visible on this node (nvidia-smi failed or is missing). "
            "You're likely on a login node -- request a GPU compute node (e.g. `qsub -I -l ngpus=1 ...`) "
            "and retry from inside that session."
        )

    try:
        check_lammps_binary(args.lammps_binary, required_style=model["lammps_style"])
    except (FileNotFoundError, RuntimeError) as exc:
        emit_result_json("error", pmc=args.pmc, message=str(exc))
        raise SystemExit(str(exc))

    log(f"[{args.pmc}] engine=lammps model={model['family']}/{model['size']} ({model['lammps_pt']}) ensemble=NPT T={args.temperature}K P={args.pressure} bar")
    log(f"Output dir: {condition_dir}/")

    with open(os.path.join(condition_dir, "config.yaml"), "w") as f:
        f.write(
            f"pmc: {args.pmc}\nengine: lammps\nmodel_family: {model['family']}\nmodel_size: {model['size']}\n"
            f"ensemble: npt\ntemperature_K: {args.temperature}\npressure_bar: {args.pressure}\nminimize_steps: {args.minimize_steps}\n"
            f"equil_steps: {equil_target}\ntarget_step: {prod_target}\n"
            f"checkpoint_every: {args.checkpoint_every}\ndump_every: {args.dump_every}\ntimestep_fs: {args.timestep}\ntimestep_ps: {timestep_ps}\nsupercell_size: {args.supercell_size}\n"
        )

    data_path, type_map_path = ensure_lammps_data(args.pmc, cif_path, args.data_dir, args.supercell_size)
    with open(type_map_path) as f:
        type_map = json.load(f)
    local_data_path = os.path.join(condition_dir, f"{args.pmc}.data")
    local_type_map_path = os.path.join(condition_dir, "type_map.json")
    if not os.path.exists(local_data_path):
        shutil.copy2(data_path, local_data_path)
    if not os.path.exists(local_type_map_path):
        shutil.copy2(type_map_path, local_type_map_path)
    type_symbols = " ".join(type_map[str(i + 1)] for i in range(len(type_map)))

    if args.dry_run:
        log("--dry-run set: stopping before invoking LAMMPS.")
        return

    overall_start = time.time()

    # --- Stage 1: minimization ---
    log_stage_banner("Minimization")
    min_dir = os.path.join(condition_dir, "minimization")
    os.makedirs(min_dir, exist_ok=True)
    min_state_path = os.path.join(min_dir, STATE_FILENAME)
    min_log_path = os.path.join(min_dir, "minimization.log")
    if args.fresh and os.path.exists(min_state_path):
        log("[minimization] --fresh given: discarding existing checkpoint")
        os.remove(min_state_path)
    # Compare against the CURRENTLY requested --minimize-steps, not just
    # whether a previous minimization ever completed at all -- checking
    # status alone (the old behavior here) would wrongly skip a rerun
    # asking for MORE iterations than a prior run used, exactly the class
    # of bug the original spec warned against for every other stage.
    min_action = get_run_action(min_state_path, args.minimize_steps)
    if min_action == "skip":
        prior_target = load_state(min_state_path).get("target_step", "?")
        log(f"[minimization] already complete at requested {args.minimize_steps} iterations "
            f"(previously ran to {prior_target}), skipping")
    else:
        if min_action == "resume":
            log(f"[minimization] Previous run used fewer iterations than now requested "
                f"({args.minimize_steps}) -- re-running minimization from scratch "
                f"(minimization doesn't support incremental resume, it's cheap enough to redo)")
        in_content = MINIMIZE_TEMPLATE.format(
            pmc_id=args.pmc, model_family=model["family"], model_size=model["size"], stage="minimization",
            data_path=os.path.relpath(local_data_path, min_dir), lammps_pt=model["lammps_pt"], type_symbols=type_symbols,
            structure_block=build_structure_block("read_data", data_path=os.path.relpath(local_data_path, min_dir)),
            pair_block=build_pair_block(model, type_symbols), mass_block=build_mass_lines(type_map),
            max_iterations=args.minimize_steps, restart_placeholder=RESTART_FILENAME,
        )
        in_path = os.path.join(min_dir, "generated.in")
        with open(in_path, "w") as f:
            f.write(in_content)
        append_log(min_log_path, f"Starting minimization, max_iterations={args.minimize_steps}")
        stage_start = time.time()
        run_lammps(in_path, min_dir, min_log_path, lammps_binary=args.lammps_binary, gpu=args.gpu, stage_name="minimization", target_step=args.minimize_steps)
        write_state(min_state_path, pmc_id=args.pmc, stage="minimization", last_completed_step=args.minimize_steps,
                    target_step=args.minimize_steps, status="completed")
        min_elapsed = time.time() - stage_start
        log(f"[minimization] COMPLETE  elapsed={format_hms(min_elapsed)} ({min_elapsed:.1f}s)")
        try:
            write_stage_pdb(os.path.join(min_dir, "minimized.lammpstrj"), "lammps-dump-text", os.path.join(min_dir, "structure.pdb"))
            log("[minimization] structure.pdb written")
        except Exception as exc:
            log(f"WARNING: could not write minimization structure.pdb: {exc}")

    # --- Stage 2: equilibration ---
    log_stage_banner("Equilibration")
    equil_dir = os.path.join(condition_dir, "equilibration")
    run_equilibration_or_production(
        "equilibration", EQUIL_TEMPLATE, equil_dir, args.pmc, model,
        os.path.relpath(local_data_path, equil_dir), type_symbols, type_map, args, equil_target,
        prior_restart_rel=os.path.relpath(os.path.join(min_dir, RESTART_FILENAME), equil_dir),
    )
    equil_log_path = os.path.join(equil_dir, "equilibration.log")
    png_path = os.path.join(equil_dir, "temp_vs_time.png")
    try:
        plot_temp_vs_time(equil_log_path, timestep_ps, png_path)
        log("[equilibration] temp_vs_time.png written")
    except Exception as exc:
        log(f"WARNING: could not generate temp_vs_time.png: {exc}")

    # --- Stage 3: production ---
    log_stage_banner("Production")
    prod_dir = os.path.join(condition_dir, "production")
    run_equilibration_or_production(
        "production", PRODUCTION_TEMPLATE, prod_dir, args.pmc, model,
        os.path.relpath(local_data_path, prod_dir), type_symbols, type_map, args, prod_target,
        prior_restart_rel=os.path.relpath(os.path.join(equil_dir, RESTART_FILENAME), prod_dir),
        traj_filename="traj.extxyz",
    )

    total_elapsed = time.time() - overall_start
    traj_path = os.path.join(prod_dir, "traj.extxyz")
    log("=" * 60)
    log(f"[{args.pmc}] PIPELINE COMPLETE")
    log(f"  Total time: {format_hms(total_elapsed)} ({total_elapsed:.1f} seconds)")
    log("=" * 60)
    log(f"Trajectory for RDF: {traj_path}")
    emit_result_json("completed", pmc=args.pmc, model=model["family"], version=model["size"],
                      temperature_K=args.temperature, pressure_bar=args.pressure, output_dir=condition_dir,
                      trajectory=traj_path, total_elapsed_s=round(total_elapsed, 1))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        emit_result_json("error", message=str(exc))
        raise