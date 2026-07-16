#!/usr/bin/env python3
"""
all_nvt_ase.py
==============

Runs a full NVT MD pipeline for one Piezoelectric Molecular Crystal (PMC)
compound using ASE's built-in MD engine, driven by ANY MACE-family model
registered in the MODELS dict below (mace-off23, polarmace, or any future
model you add — one line in MODELS is all it takes).

"all" in the filename means "any model via one --model/--version arg", NOT
"all 47 compounds at once" — this script runs ONE compound per invocation,
and you (or the agent) call it once per compound.

===============================================================================
HOW THIS SCRIPT ACTUALLY WORKS, END TO END (read this before touching anything)
===============================================================================

0. ENVIRONMENT — this script does NOT create or activate any environment
   itself. It assumes one is ALREADY ACTIVE before you run it, providing:
     - `torch`, `mace`, `ase` importable in this Python
   In practice that means `source env.sh` (or the run_pmc.sh wrapper)
   BEFORE calling this script. Unlike the LAMMPS scripts, no external
   binary (lmp) is needed — everything runs inside this Python process.

1. MODEL SELECTION — --model/--version (default: mace-off23/medium) look
   up an entry in the MODELS dict, which hardcodes real file paths on disk
   (currently under ~/himesh_work/mace_models/). Run --list-models to see
   every registered combination and whether its .model file is present.
   PolarMACE is ONLY available via ASE (not LAMMPS — upstream export bug),
   so this script is the only way to run it.

2. STRUCTURE INPUT — the source-of-truth CIF is found by globbing
   --cif-dir (default ~/himesh_work/data) for <PMC-ID>/*.cif.

3. THE THREE STAGES, IN ORDER, ONE SCRIPT CALL:
     minimization   -> LBFGS energy minimization, T=0
     equilibration  -> Langevin NVT, brings system to --temperature
     production     -> Langevin NVT, sampling run -> traj.extxyz

4. WHERE OUTPUT GOES:
     <--runs-dir>/<PMC-ID>/ase-nvt/<model>-<version>/<T>K_<N>x<N>x<N>/
       minimization/    equilibration/    production/

5. RESUME BEHAVIOR — rerunning the exact same command auto-resumes from
   the last checkpoint. Pass --fresh --confirm-fresh to start over.

Usage:
    python all_nvt_ase.py --pmc PMC-001 --temperature 300 \\
        --minimize-steps 200 --equil-step 2000 --target-step 20000

    python all_nvt_ase.py --pmc PMC-001 --model polarmace --version small \\
        --temperature 300 --equil-step 5000 --target-step 50000

    python all_nvt_ase.py --list-models
"""

import argparse
import glob
import json
import os
import shutil
import sys
import time
import warnings

import numpy as np

# Suppress known-noisy warnings from torch/e3nn/mace before any imports trigger them
warnings.filterwarnings("ignore", message=".*not interpreted for space group.*")
warnings.filterwarnings("ignore", message=".*weights_only.*")
warnings.filterwarnings("ignore", message=".*TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD.*")
warnings.filterwarnings("ignore", category=UserWarning, module="e3nn")
warnings.filterwarnings("ignore", category=UserWarning, module="mace")

# ---------------------------------------------------------------------------
# Model registry — add new models here (one entry = one line)
# ---------------------------------------------------------------------------
MODELS_DIR = os.path.expanduser("~/himesh_work/mace_models")
MODELS = {
    # MACE models (existing - unchanged)
    ("mace-off23", "small"):  {"family": "mace-off23", "size": "small",  "model_path": f"{MODELS_DIR}/MACE-OFF23_small.model",  "calc_type": "mace_off"},
    ("mace-off23", "medium"): {"family": "mace-off23", "size": "medium", "model_path": f"{MODELS_DIR}/MACE-OFF23_medium.model", "calc_type": "mace_off"},
    ("mace-off23", "large"):  {"family": "mace-off23", "size": "large",  "model_path": f"{MODELS_DIR}/MACE-OFF23_large.model",  "calc_type": "mace_off"},
    ("polarmace", "small"):   {"family": "polarmace",  "size": "small",  "model_path": f"{MODELS_DIR}/MACE-POLAR-1-S.model",    "calc_type": "mace_polar"},
    ("polarmace", "medium"):  {"family": "polarmace",  "size": "medium", "model_path": f"{MODELS_DIR}/MACE-POLAR-1-M.model",    "calc_type": "mace_polar"},
    ("polarmace", "large"):   {"family": "polarmace",  "size": "large",  "model_path": f"{MODELS_DIR}/MACE-POLAR-1-L.model",    "calc_type": "mace_polar"},
    # MACE-MP-0 (auto-download)
    ("mace-mp0", "small"):    {"family": "mace-mp0",   "size": "small",  "model_path": f"{MODELS_DIR}/mace-mp0-small.model",    "calc_type": "mace_mp0"},
    ("mace-mp0", "medium"):   {"family": "mace-mp0",   "size": "medium", "model_path": f"{MODELS_DIR}/mace-mp0-medium.model",   "calc_type": "mace_mp0"},
    ("mace-mp0", "large"):    {"family": "mace-mp0",   "size": "large",  "model_path": f"{MODELS_DIR}/mace-mp0-large.model",    "calc_type": "mace_mp0"},
    # CHGNet (auto-managed)
    ("chgnet", "pretrained"): {"family": "chgnet",     "size": "pretrained", "calc_type": "chgnet"},
    # GRACE (auto-managed)
    ("grace", "GRACE-2L-OMAT-medium-ft-AM"): {"family": "grace", "size": "GRACE-2L-OMAT-medium-ft-AM", "model_name": "GRACE-2L-OMAT-medium-ft-AM", "calc_type": "grace"},
    ("grace", "GRACE-2L-OAM"):               {"family": "grace", "size": "GRACE-2L-OAM",               "model_name": "GRACE-2L-OAM",               "calc_type": "grace"},
    # ORB (auto-managed)
    ("orb", "orb-v2"):                       {"family": "orb",   "size": "orb-v2",                     "model_name": "orb-v2",                     "calc_type": "orb"},
    ("orb", "orb-v3-conservative-inf-omat"):  {"family": "orb",   "size": "orb-v3-conservative-inf-omat", "model_name": "orb-v3-conservative-inf-omat", "calc_type": "orb"},
}

STATE_FILENAME = "state.json"
RESTART_FILENAME = "restart.extxyz"
LOCK_FILENAME = ".run.lock"

# CHGNet ASE Calculator wrapper - defined at module level to prevent garbage collection
try:
    from ase.calculators.calculator import Calculator
    from pymatgen.io.ase import AseAtomsAdaptor
    class CHGNetASECalc(Calculator):
        implemented_properties = ['energy', 'forces', 'stress']
        def __init__(self, m):
            Calculator.__init__(self)
            self.model = m
            self.adaptor = AseAtomsAdaptor()
        def calculate(self, atoms=None, properties=['energy'], system_changes=['positions', 'numbers', 'cell', 'pbc']):
            Calculator.calculate(self, atoms, properties, system_changes)
            structure = self.adaptor.get_structure(atoms)
            result = self.model.predict_structure(structure)
            self.results['energy'] = float(result['e'])
            self.results['forces'] = result['f']
            self.results['stress'] = result['s']
except ImportError:
    CHGNetASECalc = None


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def log(msg):
    print(msg, flush=True)


def log_stage_banner(stage_title):
    print(flush=True)
    print("=" * 60, flush=True)
    print(f"  STAGE: {stage_title.upper()}", flush=True)
    print("=" * 60, flush=True)


def format_hms(seconds):
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def calculate_total_time(log_path):
    """Calculate total simulation time from log file across all runs"""
    if not os.path.exists(log_path):
        return 0
    from datetime import datetime, timezone
    timestamps = []
    with open(log_path) as f:
        for line in f:
            if line.startswith("[") and "Step" in line:
                try:
                    ts_str = line[1:line.index("]")]
                    ts = datetime.fromisoformat(ts_str)
                    timestamps.append(ts)
                except:
                    continue
    if len(timestamps) < 2:
        return 0
    total_seconds = 0
    for i in range(1, len(timestamps)):
        gap = (timestamps[i] - timestamps[i-1]).total_seconds()
        if gap < 600:
            total_seconds += gap
    return total_seconds


def adaptive_print_interval(total_steps, target_lines=25, min_interval=1000, max_interval=5000):
    raw = max(1, total_steps // target_lines)
    return max(min_interval, min(max_interval, raw))


def append_log(path, msg):
    from datetime import datetime, timezone
    with open(path, "a") as f:
        f.write(f"[{datetime.now(timezone.utc).isoformat()}] {msg}\n")


def write_state(path, **fields):
    from datetime import datetime, timezone
    fields["timestamp"] = datetime.now(timezone.utc).isoformat()
    with open(path, "w") as f:
        json.dump(fields, f, indent=2)


def load_state(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


def get_run_action(state_path, target_step):
    state = load_state(state_path)
    if state is None:
        return "start_fresh", 0
    last = state.get("last_completed_step", 0)
    if last >= target_step:
        return "skip", last
    return "resume", last


def acquire_lock(lock_path):
    if os.path.exists(lock_path):
        try:
            with open(lock_path) as f:
                old_pid = int(f.read().strip())
            if os.path.exists(f"/proc/{old_pid}"):
                raise SystemExit(
                    f"Another run is already in progress (PID {old_pid}, lock: {lock_path}). "
                    f"If this is stale, delete {lock_path} and retry."
                )
        except (ValueError, IOError):
            pass
    with open(lock_path, "w") as f:
        f.write(str(os.getpid()))


def release_lock(lock_path):
    if os.path.exists(lock_path):
        os.remove(lock_path)


def emit_result_json(status, **fields):
    d = {"status": status}
    d.update(fields)
    log(f"RESULT_JSON: {json.dumps(d)}")


def find_cif_for_pmc(cif_dir, pmc_id):
    folder = os.path.join(cif_dir, pmc_id)
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"CIF directory not found: {folder}")
    cifs = glob.glob(os.path.join(folder, "*.cif"))
    if len(cifs) == 0:
        raise FileNotFoundError(f"No .cif file found in {folder}")
    if len(cifs) > 1:
        raise FileNotFoundError(f"Multiple .cif files in {folder}: {cifs} — expected exactly one")
    return cifs[0]


def check_gpu_available():
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


def build_calculator(model, device="cpu"):
    """Build the appropriate calculator for the given model entry."""
    calc_type = model["calc_type"]

    if calc_type == "mace_off":
        from mace.calculators import mace_off
        return mace_off(model=model["model_path"], device=device, default_dtype="float64")

    elif calc_type == "mace_polar":
        from mace.calculators import MACECalculator
        return MACECalculator(model_paths=model["model_path"], device=device, default_dtype="float64")

    elif calc_type == "mace_mp0":
        from mace.calculators import mace_mp
        return mace_mp(model=model["model_path"], device=device, default_dtype="float64")

    elif calc_type == "chgnet":
        if CHGNetASECalc is None:
            raise ImportError("pymatgen not installed. Run: pip install pymatgen")
        from chgnet.model import CHGNet
        chgnet_model = CHGNet.load()
        if device == "cuda":
            chgnet_model = chgnet_model.to("cuda")
        return CHGNetASECalc(chgnet_model)

    elif calc_type == "grace":
        from tensorpotential.calculator.asecalculator import TPCalculator
        model_path = os.path.expanduser(f"~/.cache/grace/{model['model_name']}")
        return TPCalculator(model_path)

    elif calc_type == "orb":
        from orb_models.forcefield import pretrained
        from orb_models.forcefield.inference.calculator import ORBCalculator
        model_fn = pretrained.ORB_PRETRAINED_MODELS[model["model_name"]]
        orb_model, atoms_adapter = model_fn(device=device)
        return ORBCalculator(orb_model, atoms_adapter, device=device)

    else:
        raise ValueError(f"Unknown calc_type: {calc_type}")


# ---------------------------------------------------------------------------
# Minimization
# ---------------------------------------------------------------------------

def run_minimization(atoms, min_dir, max_steps, log_path):
    """LBFGS minimization — relaxes atomic positions at T=0."""
    from ase.optimize import LBFGS
    from ase.io import write

    log(f"[minimization] Starting LBFGS, max {max_steps} steps")

    restart_path = os.path.join(min_dir, RESTART_FILENAME)
    traj_path = os.path.join(min_dir, "minimization_traj.extxyz")

    step_count = [0]
    start_pe = atoms.get_potential_energy()
    log(f"      Step {0:<8d} | PE={start_pe:12.4f} eV")

    def print_progress():
        step_count[0] += 1
        pe = atoms.get_potential_energy()
        fmax = np.max(np.abs(atoms.get_forces()))
        if step_count[0] % 10 == 0 or step_count[0] <= 5:
            log(f"      Step {step_count[0]:<8d} | PE={pe:12.4f} eV | fmax={fmax:.4f} eV/Å")

    opt = LBFGS(atoms, logfile=log_path)
    opt.attach(print_progress)

    stage_start = time.time()
    opt.run(fmax=0.01, steps=max_steps)
    elapsed = time.time() - stage_start

    final_pe = atoms.get_potential_energy()
    log(f"      Step {step_count[0]:<8d} | PE={final_pe:12.4f} eV (final)")

    # Save minimized structure
    write(restart_path, atoms, format="extxyz")
    write(os.path.join(min_dir, "structure.pdb"), atoms, format="proteindatabank")

    return elapsed


# ---------------------------------------------------------------------------
# MD stages (equilibration / production)
# ---------------------------------------------------------------------------

def run_md_stage(stage_name, atoms, stage_dir, temperature, timestep_fs,
                 target_step, start_step, print_every, checkpoint_every,
                 dump_every, log_path, traj_filename=None):
    """Run Langevin NVT MD for equilibration or production."""
    from ase.md.langevin import Langevin
    from ase.io import write, read
    from ase import units

    restart_path = os.path.join(stage_dir, RESTART_FILENAME)
    state_path = os.path.join(stage_dir, STATE_FILENAME)

    # Langevin thermostat — friction coefficient 0.01 fs^-1 is a reasonable
    # default for molecular crystals; not too aggressive (over-damped), not
    # too weak (slow equilibration).
    dyn = Langevin(atoms, timestep=timestep_fs * units.fs,
                   temperature_K=temperature, friction=0.01 / units.fs)

    steps_to_run = target_step - start_step
    current_step = [start_step]
    stage_start = time.time()

    # Trajectory collection (production only)
    traj_frames = []

    def md_callback():
        current_step[0] += 1
        step = current_step[0]

        # Progress line with ETA and log file writing
        if step % print_every == 0 or step == start_step + 1:
            pe = atoms.get_potential_energy()
            ke = atoms.get_kinetic_energy()
            temp = 2.0 * ke / (3.0 * len(atoms) * units.kB)
            vol = atoms.get_volume()
            cell = atoms.get_cell().cellpar()[:3]
            time_ps = step * timestep_fs / 1000.0
            elapsed_this_run = time.time() - stage_start
            steps_done_this_run = step - start_step
            time_per_step = elapsed_this_run / steps_done_this_run if steps_done_this_run > 0 else 0
            steps_remaining = target_step - step
            eta_seconds = steps_remaining * time_per_step
            msg = (f"Step {step:<8d} | {time_ps:7.2f} ps | T={temp:6.1f} K | "
                   f"E={pe:12.4f} eV | V={vol:10.4f} Å³ | "
                   f"a={cell[0]:.4f} b={cell[1]:.4f} c={cell[2]:.4f} | "
                   f"ETA={format_hms(eta_seconds)} | {time_per_step:.3f} s/step")
            log(f"      {msg}")
            append_log(log_path, msg)

        # Checkpoint
        if step % checkpoint_every == 0:
            write(restart_path, atoms, format="extxyz")
            write_state(state_path, pmc_id="", stage=stage_name,
                        last_completed_step=step, target_step=target_step,
                        status="running", restart_file=RESTART_FILENAME)

        # PDB trajectory (all stages)
        if step % dump_every == 0:
            pdb_path = os.path.join(stage_dir, "trajectory.pdb")
            write(pdb_path, atoms, format="proteindatabank", append=True)

        # Trajectory dump (production only)
        if traj_filename and step % dump_every == 0:
            traj_frames.append(atoms.copy())

    _calc = atoms.calc
    dyn.atoms.calc = _calc
    # Patch _refresh_properties to ensure calculator is always attached
    def _safe_refresh():
        if dyn.atoms.calc is None:
            dyn.atoms.calc = _calc
        dyn.atoms.get_forces()
    dyn._refresh_properties = _safe_refresh
    dyn.attach(md_callback, interval=1)
    dyn.run(steps_to_run)

    elapsed = time.time() - stage_start

    # Write final state
    write(restart_path, atoms, format="extxyz")
    write_state(state_path, pmc_id="", stage=stage_name,
                last_completed_step=target_step, target_step=target_step,
                status="completed", restart_file=RESTART_FILENAME)

    # Write trajectory (production)
    if traj_filename and traj_frames:
        traj_path = os.path.join(stage_dir, traj_filename)
        write(traj_path, traj_frames, format="extxyz")
        log(f"[{stage_name}] {traj_filename} written ({len(traj_frames)} frames)")

    # Write structure.pdb
    try:
        write(os.path.join(stage_dir, "structure.pdb"), atoms, format="proteindatabank")
        log(f"[{stage_name}] structure.pdb written")
    except Exception as exc:
        log(f"WARNING: could not write structure.pdb for {stage_name}: {exc}")

    return elapsed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="ASE NVT MD pipeline for PMC compounds")
    p.add_argument("--pmc", default=None, help="PMC ID (e.g. PMC-001)")
    p.add_argument("--model", default="mace-off23", help="Model family (default: mace-off23)")
    p.add_argument("--version", default="medium")
    p.add_argument("--temperature", type=float, default=None, help="Target temperature in K")
    p.add_argument("--timestep", type=float, default=0.5, help="Timestep in fs (default: 0.5)")
    p.add_argument("--supercell-size", type=int, default=2, help="Supercell NxNxN (default: 2)")
    p.add_argument("--minimize-steps", type=int, default=500, help="Max minimization steps")
    p.add_argument("--equil-step", type=int, default=None, help="Equilibration target (steps)")
    p.add_argument("--equil-ps", type=float, default=None, help="Equilibration target (ps)")
    p.add_argument("--target-step", type=int, default=None, help="Production target (steps)")
    p.add_argument("--target-ps", type=float, default=None, help="Production target (ps)")
    p.add_argument("--checkpoint-every", type=int, default=500)
    p.add_argument("--dump-every", type=int, default=1000, help="Trajectory dump interval (steps)")
    p.add_argument("--cif-dir", default=os.path.expanduser("~/himesh_work/data"))
    p.add_argument("--runs-dir", default="runs")
    p.add_argument("--gpu", action="store_true", help="Use GPU (CUDA) for model evaluation")
    p.add_argument("--fresh", action="store_true", help="Discard all checkpoints and start over")
    p.add_argument("--confirm-fresh", action="store_true")
    p.add_argument("--list-models", action="store_true", help="Show registered models and exit")
    args = p.parse_args()

    # --list-models
    if args.list_models:
        log("Registered models:")
        for (fam, sz), m in sorted(MODELS.items()):
            path = m.get("model_path", "auto-managed")
            exists = "\u2705" if "model_path" not in m or os.path.exists(path) else "\u274c"
            log(f"  {exists} {fam}/{sz}  ->  {path}  (calc: {m['calc_type']})")
        return

    # Resolve model
    # --pmc and --temperature are only required for actual runs, not --list-models
    if not args.pmc:
        raise SystemExit("--pmc is required (e.g. --pmc PMC-001)")
    if args.temperature is None:
        raise SystemExit("--temperature is required (e.g. --temperature 300)")

    key = (args.model, args.version)
    if key not in MODELS:
        emit_result_json("error", pmc=args.pmc, message=f"Unknown model: {args.model}/{args.version}")
        raise SystemExit(f"Unknown model: {args.model}/{args.version}. Use --list-models.")
    model = MODELS[key]
    if "model_path" in model and not os.path.exists(model["model_path"]):
        emit_result_json("error", pmc=args.pmc, message=f"Model file missing: {model['model_path']}")
        raise SystemExit(f"Model file not found: {model['model_path']}")

    # Resolve step targets
    def resolve_steps(step_arg, ps_arg, label):
        if step_arg is not None:
            return step_arg
        if ps_arg is not None:
            return int(ps_arg * 1000.0 / args.timestep)
        raise SystemExit(f"Provide either --{label}-step or --{label}-ps")

    equil_target = resolve_steps(args.equil_step, args.equil_ps, "equil")
    prod_target = resolve_steps(args.target_step, args.target_ps, "target")

    # --fresh safety
    if args.fresh and not args.confirm_fresh:
        raise SystemExit("--fresh requires --confirm-fresh (safety gate against accidental data loss)")

    # Build output directory
    N = args.supercell_size
    condition_dir = os.path.join(
        args.runs_dir, args.pmc, "ase-nvt", f"{model['family']}-{model['size']}",
        f"{int(args.temperature)}K_{N}x{N}x{N}",
    )
    os.makedirs(condition_dir, exist_ok=True)

    # GPU check
    device = "cpu"
    if args.gpu:
        if not check_gpu_available():
            emit_result_json("error", pmc=args.pmc, message="--gpu given but no CUDA device available")
            raise SystemExit("--gpu given but torch.cuda.is_available() returned False")
        device = "cuda"

    model_path_str = model.get("model_path", "auto-managed")
    log(f"[{args.pmc}] engine=ase model={model['family']}/{model['size']} ({model_path_str}) ensemble=NVT T={args.temperature}K device={device}")
    log(f"Output dir: {condition_dir}/")

    # Lock
    lock_path = os.path.join(condition_dir, LOCK_FILENAME)
    acquire_lock(lock_path)

    pipeline_start = time.time()

    try:
        from ase.io import read, write
        from ase.md.velocitydistribution import MaxwellBoltzmannDistribution

        # Find CIF and build supercell
        cif_path = find_cif_for_pmc(args.cif_dir, args.pmc)
        atoms = read(cif_path)
        atoms = atoms.repeat((N, N, N))
        atoms.set_pbc(True)
        log(f"Built {N}x{N}x{N} supercell: {len(atoms)} atoms from {cif_path}")

        # Build calculator
        calc = build_calculator(model, device=device)
        atoms.calc = calc

        # Write config
        from datetime import datetime, timezone
        config = {
            "pmc": args.pmc, "model": model["family"], "version": model["size"],
            "engine": "ase", "ensemble": "nvt", "temperature_K": args.temperature,
            "timestep_fs": args.timestep, "supercell": f"{N}x{N}x{N}",
            "equil_steps": equil_target, "equil_ps": equil_target * args.timestep / 1000.0,
            "prod_steps": prod_target, "prod_ps": prod_target * args.timestep / 1000.0,
            "minimize_steps": args.minimize_steps,
            "checkpoint_every": args.checkpoint_every,
            "dump_every": args.dump_every,
            "device": device,
            "run_started": datetime.now(timezone.utc).isoformat(),
        }
        with open(os.path.join(condition_dir, "config.yaml"), "w") as f:
            for k, v in config.items():
                f.write(f"{k}: {v}\n")

        # ── Stage 1: Minimization ──
        log_stage_banner("Minimization")
        min_dir = os.path.join(condition_dir, "minimization")
        os.makedirs(min_dir, exist_ok=True)
        min_state_path = os.path.join(min_dir, STATE_FILENAME)
        min_log_path = os.path.join(min_dir, "minimization.log")

        if args.fresh and os.path.exists(min_state_path):
            log("[minimization] --fresh given: discarding existing checkpoint")
            os.remove(min_state_path)

        min_action, _ = get_run_action(min_state_path, args.minimize_steps)
        if min_action == "skip":
            log(f"[minimization] already complete at requested {args.minimize_steps} steps, skipping")
            restart = os.path.join(min_dir, RESTART_FILENAME)
            if os.path.exists(restart):
                atoms = read(restart)
                atoms.set_pbc(True)
                calc = build_calculator(model, device=device)
                atoms.calc = calc
        else:
            min_elapsed = run_minimization(atoms, min_dir, args.minimize_steps, min_log_path)
            write_state(min_state_path, pmc_id=args.pmc, stage="minimization",
                        last_completed_step=args.minimize_steps, target_step=args.minimize_steps,
                        status="completed")
            log(f"[minimization] COMPLETE  elapsed={format_hms(min_elapsed)} ({min_elapsed:.1f}s)")

        # ── Stage 2: Equilibration ──
        log_stage_banner("Equilibration")
        equil_dir = os.path.join(condition_dir, "equilibration")
        os.makedirs(equil_dir, exist_ok=True)
        equil_state_path = os.path.join(equil_dir, STATE_FILENAME)
        equil_log_path = os.path.join(equil_dir, "equilibration.log")

        if args.fresh and os.path.exists(equil_state_path):
            log("[equilibration] --fresh given: discarding existing checkpoint")
            os.remove(equil_state_path)

        equil_action, equil_last = get_run_action(equil_state_path, equil_target)
        if equil_action == "skip":
            log(f"[equilibration] already complete at step {equil_last}, skipping")
            restart = os.path.join(equil_dir, RESTART_FILENAME)
            if os.path.exists(restart):
                atoms = read(restart)
                atoms.set_pbc(True)
                calc = build_calculator(model, device=device)
                atoms.calc = calc
        else:
            if equil_action == "resume":
                log(f"[equilibration] Resuming from step {equil_last} -> target {equil_target}")
                restart = os.path.join(equil_dir, RESTART_FILENAME)
                atoms = read(restart)
                atoms.set_pbc(True)
                calc = build_calculator(model, device=device)
                atoms.calc = calc
            else:
                log(f"[equilibration] Starting fresh -> target {equil_target}")
                # Assign Maxwell-Boltzmann velocities (minimization leaves T=0)
                MaxwellBoltzmannDistribution(atoms, temperature_K=args.temperature)
                log(f"[equilibration] Assigned Maxwell-Boltzmann velocities at {args.temperature}K")

            print_every = adaptive_print_interval(equil_target - equil_last)
            equil_elapsed = run_md_stage(
                "equilibration", atoms, equil_dir, args.temperature, args.timestep,
                equil_target, equil_last, print_every, args.checkpoint_every,
                args.dump_every, equil_log_path,
            )
            log(f"[equilibration] COMPLETE  step {equil_target}/{equil_target}  elapsed={format_hms(equil_elapsed)} ({equil_elapsed:.1f}s)")

            # temp_vs_time.png
            try:
                _write_temp_plot(equil_log_path, os.path.join(equil_dir, "temp_vs_time.png"))
                log("[equilibration] temp_vs_time.png written")
            except Exception:
                pass

        # ── Stage 3: Production ──
        log_stage_banner("Production")
        prod_dir = os.path.join(condition_dir, "production")
        os.makedirs(prod_dir, exist_ok=True)
        prod_state_path = os.path.join(prod_dir, STATE_FILENAME)
        prod_log_path = os.path.join(prod_dir, "production.log")

        if args.fresh and os.path.exists(prod_state_path):
            log("[production] --fresh given: discarding existing checkpoint")
            os.remove(prod_state_path)

        prod_action, prod_last = get_run_action(prod_state_path, prod_target)
        if prod_action == "skip":
            log(f"[production] already complete at step {prod_last}, skipping")
        else:
            if prod_action == "resume":
                log(f"[production] Resuming from step {prod_last} -> target {prod_target}")
                restart = os.path.join(prod_dir, RESTART_FILENAME)
                atoms = read(restart)
                atoms.set_pbc(True)
                calc = build_calculator(model, device=device)
                atoms.calc = calc
            else:
                log(f"[production] Starting fresh -> target {prod_target}")
                # Velocities already thermalized from equilibration — no re-randomization

            print_every = adaptive_print_interval(prod_target - prod_last)
            prod_elapsed = run_md_stage(
                "production", atoms, prod_dir, args.temperature, args.timestep,
                prod_target, prod_last, print_every, args.checkpoint_every,
                args.dump_every, prod_log_path, traj_filename="traj.extxyz",
            )
            log(f"[production] COMPLETE  step {prod_target}/{prod_target}  elapsed={format_hms(prod_elapsed)} ({prod_elapsed:.1f}s)")

        # ── Pipeline complete ──
        total_elapsed = time.time() - pipeline_start
        log(f"\n{'=' * 60}")
        log(f"[{args.pmc}] PIPELINE COMPLETE")
        log(f"  Total time this run : {format_hms(total_elapsed)}")

        equil_total = calculate_total_time(equil_log_path)
        prod_total = calculate_total_time(prod_log_path)
        grand_total = equil_total + prod_total

        log(f"\n  {'─'*40}")
        log(f"  TIME SUMMARY (across all job runs):")
        log(f"  {'─'*40}")
        log(f"  Equilibration : {format_hms(equil_total)}")
        log(f"  Production    : {format_hms(prod_total)}")
        log(f"  Grand Total   : {format_hms(grand_total)}")
        log(f"  {'─'*40}")
        if prod_total > 0 and prod_last > 0:
            steps_per_sec = prod_last / prod_total
            log(f"  Speed         : {steps_per_sec:.2f} steps/sec")
            log(f"  Per step      : {1/steps_per_sec:.3f} sec/step")
        log(f"  {'─'*40}")
        log(f"{'=' * 60}")

        traj_path = os.path.join(prod_dir, "traj.extxyz")
        log(f"Trajectory for RDF: {traj_path}")
        emit_result_json("completed", pmc=args.pmc, model=model["family"], version=model["size"],
                         temperature_K=args.temperature, output_dir=condition_dir,
                         trajectory=traj_path, total_elapsed_s=round(total_elapsed, 1))

    except Exception as exc:
        emit_result_json("error", pmc=args.pmc, message=str(exc))
        raise
    finally:
        release_lock(lock_path)


def _write_temp_plot(log_path, png_path):
    """Parse temperature from the log and plot temp vs time."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return

    steps, temps = [], []
    with open(log_path) as f:
        for line in f:
            if "Step" in line and "T=" in line:
                parts = line.split("|")
                for p in parts:
                    p = p.strip()
                    if p.startswith("Step"):
                        steps.append(int(p.split()[1]))
                    if p.startswith("T="):
                        temps.append(float(p.split("=")[1].split()[0]))

    if len(steps) > 1 and len(steps) == len(temps):
        plt.figure(figsize=(8, 4))
        plt.plot(steps, temps, linewidth=0.8)
        plt.xlabel("Step")
        plt.ylabel("Temperature (K)")
        plt.title("Equilibration Temperature")
        plt.tight_layout()
        plt.savefig(png_path, dpi=150)
        plt.close()


if __name__ == "__main__":
    main()