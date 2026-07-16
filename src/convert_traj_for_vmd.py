"""
Convert ASE .traj trajectories → VMD-readable formats
────────────────────────────────────────────────────────
ASE's .traj is a binary format specific to ASE — VMD can't read it directly.

This script converts a .traj file into:
  1. <name>.xyz          — simple, atom positions only (VMD ignores the
                            box for plain XYZ, so DON'T use this to check
                            lattice parameters, only atom motion)
  2. <name>.lammpstrj     — LAMMPS dump format. VMD has a native, robust
                            reader for this that also draws/updates the
                            simulation box each frame — use THIS to
                            actually see the NPT box breathing/deforming.
  3. <name>_lattice.csv   — a, b, c, alpha, beta, gamma, volume read
                            directly off each SAVED frame of the
                            trajectory (not the thermo log — the thermo
                            log is written on a different interval than
                            the trajectory frames, so reading straight
                            off the .traj guarantees frame-for-frame
                            agreement with what you'll see in VMD).

Usage:
  python convert_traj_for_vmd.py path/to/production_300K.traj
"""

import sys
import csv
from pathlib import Path

from ase.io.trajectory import Trajectory
from ase.io import write


def convert(traj_path: Path):
    traj_path = Path(traj_path)
    if not traj_path.exists():
        print(f"❌ File not found: {traj_path}")
        sys.exit(1)

    traj = Trajectory(str(traj_path))
    n_frames = len(traj)
    print(f"Reading {traj_path.name} — {n_frames} frames")

    if n_frames == 0:
        print("❌ Trajectory is empty, nothing to convert.")
        sys.exit(1)

    frames = [traj[i] for i in range(n_frames)]

    # 1. Plain XYZ (atom positions only — no reliable box in VMD)
    xyz_path = traj_path.with_suffix(".xyz")
    write(str(xyz_path), frames, format="xyz")
    print(f"  ✅ Wrote {xyz_path.name}  (atoms only — box NOT shown reliably in VMD)")

    # 2. LAMMPS dump format (box-aware — use this in VMD)
    lammpstrj_path = traj_path.with_suffix(".lammpstrj")
    write(str(lammpstrj_path), frames, format="lammps-dump-text")
    print(f"  ✅ Wrote {lammpstrj_path.name}  (box-aware — load this in VMD)")

    # 3. Per-frame lattice parameters, read straight off the trajectory
    lattice_path = traj_path.parent / f"{traj_path.stem}_lattice.csv"
    with open(lattice_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["frame", "a_A", "b_A", "c_A",
                          "alpha_deg", "beta_deg", "gamma_deg", "volume_A3"])
        for i, atoms in enumerate(frames):
            a, b, c, alpha, beta, gamma = atoms.get_cell().cellpar()
            vol = atoms.get_volume()
            writer.writerow([i, a, b, c, alpha, beta, gamma, vol])
    print(f"  ✅ Wrote {lattice_path.name}  ({n_frames} rows, frame-aligned with the .lammpstrj)")

    # Quick sanity printout: start vs end
    a0, b0, c0, *_ = frames[0].get_cell().cellpar()
    a1, b1, c1, *_ = frames[-1].get_cell().cellpar()
    print(f"\n  Frame 0    : a={a0:.4f} b={b0:.4f} c={c0:.4f} Å")
    print(f"  Frame {n_frames-1:>4d}: a={a1:.4f} b={b1:.4f} c={c1:.4f} Å")
    print(f"  Δ          : Δa={a1-a0:+.4f} Δb={b1-b0:+.4f} Δc={c1-c0:+.4f} Å")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python convert_traj_for_vmd.py path/to/file.traj")
        sys.exit(1)
    convert(Path(sys.argv[1]))