"""
Stage 2: Supercell Generation
─────────────────────────────
Takes a CIF file and generates a 2×2×2 or 3×3×3 supercell.

Usage:
  python generate_supercell.py

Output:
  - supercell CIF file
  - summary of unit cell vs supercell
  - 3D visualization (optional, if matplotlib available)
"""

import os
import sys
from pathlib import Path
from ase.io import read, write
from ase.build import make_supercell
import numpy as np

# ── Config ──────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "simulations"

# Which molecule and what supercell size
PMC_ID = "PMC-010"
SUPERCELL_SIZE = (2, 2, 2)  # Change to (3,3,3) if needed


def find_cif(pmc_id: str) -> Path:
    """Find the CIF file for a given PMC ID."""
    folder = DATA_DIR / pmc_id
    if not folder.exists():
        raise FileNotFoundError(f"Folder not found: {folder}")

    cif_files = list(folder.glob("*.cif"))
    if not cif_files:
        raise FileNotFoundError(f"No CIF file found in {folder}")

    return cif_files[0]


def print_crystal_info(atoms, label: str):
    """Print key info about a crystal structure."""
    cell = atoms.get_cell()
    a, b, c, alpha, beta, gamma = cell.cellpar()

    print(f"\n{'─' * 50}")
    print(f"  {label}")
    print(f"{'─' * 50}")
    print(f"  Atoms:       {len(atoms)}")
    print(f"  Elements:    {sorted(set(atoms.get_chemical_symbols()))}")
    print(f"  Formula:     {atoms.get_chemical_formula()}")
    print(f"  a = {a:.4f} Å")
    print(f"  b = {b:.4f} Å")
    print(f"  c = {c:.4f} Å")
    print(f"  α = {alpha:.2f}°")
    print(f"  β = {beta:.2f}°")
    print(f"  γ = {gamma:.2f}°")
    print(f"  Volume:      {cell.volume:.2f} ų")
    print(f"  Density:     {len(atoms) / cell.volume:.4f} atoms/ų")

    # Element count
    symbols = atoms.get_chemical_symbols()
    from collections import Counter
    counts = Counter(symbols)
    print(f"  Composition: {dict(sorted(counts.items()))}")


def generate_supercell(cif_path: Path, size: tuple) -> tuple:
    """
    Read a CIF file and generate a supercell.

    Returns: (unit_cell_atoms, supercell_atoms)
    """
    print(f"\nReading CIF: {cif_path.name}")

    # Read the unit cell from CIF
    unit_cell = read(str(cif_path))

    print_crystal_info(unit_cell, f"{PMC_ID} — Unit Cell")

    # Build the supercell transformation matrix
    # (2,2,2) → diagonal matrix [[2,0,0],[0,2,0],[0,0,2]]
    P = np.diag(size)
    supercell = make_supercell(unit_cell, P)

    print_crystal_info(supercell, f"{PMC_ID} — {size[0]}×{size[1]}×{size[2]} Supercell")

    # Sanity checks
    expected_atoms = len(unit_cell) * size[0] * size[1] * size[2]
    actual_atoms = len(supercell)
    print(f"\n  Expected atoms: {expected_atoms}")
    print(f"  Actual atoms:   {actual_atoms}")
    if expected_atoms == actual_atoms:
        print("  ✅ Atom count matches!")
    else:
        print("  ⚠ Atom count mismatch — check CIF symmetry")

    # Volume check
    expected_volume = unit_cell.get_cell().volume * size[0] * size[1] * size[2]
    actual_volume = supercell.get_cell().volume
    print(f"\n  Expected volume: {expected_volume:.2f} ų")
    print(f"  Actual volume:   {actual_volume:.2f} ų")
    if abs(expected_volume - actual_volume) < 0.1:
        print("  ✅ Volume matches!")
    else:
        print("  ⚠ Volume mismatch")

    return unit_cell, supercell


def save_supercell(supercell, pmc_id: str, size: tuple):
    """Save the supercell in multiple formats."""
    # Create output directory
    sim_dir = OUTPUT_DIR / pmc_id
    sim_dir.mkdir(parents=True, exist_ok=True)

    size_str = f"{size[0]}x{size[1]}x{size[2]}"



    # Save as XYZ (simple format, good for quick viewing)
    xyz_out = sim_dir / f"{pmc_id}_supercell_{size_str}.xyz"
    write(str(xyz_out), supercell, format='xyz')
    print(f"  Saved XYZ:     {xyz_out}")


    return sim_dir


def try_visualize(unit_cell, supercell, sim_dir, size):
    """Try to create a simple 2D projection plot."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

        # Unit cell
        pos = unit_cell.get_positions()
        symbols = unit_cell.get_chemical_symbols()
        colors_map = {'C': '#444444', 'H': '#cccccc', 'N': '#3050F8',
                      'O': '#FF0D0D', 'Cl': '#1FF01F', 'S': '#FFFF30',
                      'P': '#FF8000', 'F': '#90E050', 'Br': '#A62929'}
        colors = [colors_map.get(s, '#888888') for s in symbols]
        sizes = [80 if s != 'H' else 30 for s in symbols]

        ax1.scatter(pos[:, 0], pos[:, 1], c=colors, s=sizes, alpha=0.8, edgecolors='black', linewidths=0.3)
        ax1.set_title(f'{PMC_ID} — Unit Cell ({len(unit_cell)} atoms)', fontsize=12)
        ax1.set_xlabel('x (Å)')
        ax1.set_ylabel('y (Å)')
        ax1.set_aspect('equal')
        ax1.grid(True, alpha=0.2)

        # Supercell
        pos2 = supercell.get_positions()
        symbols2 = supercell.get_chemical_symbols()
        colors2 = [colors_map.get(s, '#888888') for s in symbols2]
        sizes2 = [80 if s != 'H' else 30 for s in symbols2]

        ax2.scatter(pos2[:, 0], pos2[:, 1], c=colors2, s=sizes2, alpha=0.6, edgecolors='black', linewidths=0.2)
        size_str = f"{size[0]}×{size[1]}×{size[2]}"
        ax2.set_title(f'{PMC_ID} — {size_str} Supercell ({len(supercell)} atoms)', fontsize=12)
        ax2.set_xlabel('x (Å)')
        ax2.set_ylabel('y (Å)')
        ax2.set_aspect('equal')
        ax2.grid(True, alpha=0.2)

        plt.tight_layout()
        plot_path = sim_dir / f"{PMC_ID}_supercell_comparison.png"
        plt.savefig(str(plot_path), dpi=150, bbox_inches='tight')
        plt.close()
        print(f"  Saved plot:    {plot_path}")

    except ImportError:
        print("  (matplotlib not available — skipping plot)")
    except Exception as e:
        print(f"  (plot failed: {e})")


def main():
    print("=" * 60)
    print("  Piezo-LLM: Stage 2 — Supercell Generation")
    print(f"  Molecule: {PMC_ID}")
    print(f"  Target:   {SUPERCELL_SIZE[0]}×{SUPERCELL_SIZE[1]}×{SUPERCELL_SIZE[2]}")
    print("=" * 60)

    # Find CIF
    cif_path = find_cif(PMC_ID)
    print(f"\nFound CIF: {cif_path}")

    # Generate supercell
    unit_cell, supercell = generate_supercell(cif_path, SUPERCELL_SIZE)

    # Save outputs
    sim_dir = save_supercell(supercell, PMC_ID, SUPERCELL_SIZE)

    # Try visualization
    try_visualize(unit_cell, supercell, sim_dir, SUPERCELL_SIZE)

    print(f"\n{'=' * 60}")
    print(f"  ✅ Stage 2 complete!")
    print(f"  Output directory: {sim_dir}")
    print(f"  Next: Stage 3 — Convert to LAMMPS format")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()