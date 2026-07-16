# CLI Arguments Reference — run_nvt.py / run_npt.py

## Common to both scripts

| Flag | Type | Default | What it changes |
|---|---|---|---|
| `molecule` (positional) | str | *required* | PMC ID to simulate, e.g. `PMC-004` or just `004`. Use `all` to run every molecule with a CIF. |
| `--temps` | int (one or more) | `300` | Temperature(s) in K, e.g. `--temps 100 200 300 400` |
| `--size` | int | `2` | Supercell size (N×N×N) |
| `--timestep` | float | `0.5` | MD timestep in fs |
| `--eq-steps` | int | `20000` | NVT equilibration steps (thermalisation stage) |
| `--model` | str | `medium` | MACE model size: `small` / `medium` / `large` |
| `--slice-steps` | int | none (no cap) | Max MD/optimiser steps run in *this* invocation — used to chop a big simulation into resumable slices |
| `--status` | flag | off | Print checkpoint progress table and exit (no simulation run) |
| `--list` | flag | off | List available molecules and exit (ignores all other flags) |

## run_nvt.py only

| Flag | Type | Default | What it changes |
|---|---|---|---|
| `--steps` | int | `200000` | NVT production steps |

## run_npt.py only

| Flag | Type | Default | What it changes |
|---|---|---|---|
| `--npt-eq-steps` | int | same as `--eq-steps` | NPT equilibration steps |
| `--npt-steps` | int | `200000` | NPT production steps |
| `--pressure` | float | `1.0` | External pressure in bar |

## Examples

```bash
# NVT — defaults (300 K, medium model, 0.5 fs)
python3 run_nvt.py PMC-004

# NVT — custom timestep/model, single temperature
python3 run_nvt.py PMC-004 --timestep 1.0 --model large --temps 250

# NVT — multiple temperatures, bigger supercell, longer production
python3 run_nvt.py PMC-004 --temps 100 200 300 400 --size 3 --steps 500000

# NPT — with pressure
python3 run_npt.py PMC-004 --timestep 1.0 --model large --temps 300 --pressure 1.0

# NPT — chunked run: 50k steps this invocation, rerun later to continue
python3 run_npt.py PMC-004 --npt-steps 2000000 --slice-steps 50000

# Progress check, no simulation
python3 run_nvt.py PMC-004 --status
python3 run_npt.py PMC-004 --status

# List all available molecules
python3 run_nvt.py --list
```

## Notes

- `--eq-steps` feeds the NVT equilibration stage in **both** scripts. They run independently, so you can pass different values to each — but keep them consistent if you want NVT and NPT results to be comparable.
- Rerunning with a **larger** step count than before (e.g. `--steps 200000` → `--steps 500000`) extends the existing checkpointed run rather than starting over — nothing needs to be deleted.
- `--slice-steps` caps steps per *invocation*, not per stage. If a slice runs out mid-stage, only that stage resumes on the next run.
