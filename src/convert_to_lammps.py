"""
Stage 3: Convert Supercell to LAMMPS Data Format
─────────────────────────────────────────────────
Takes the supercell CIF from Stage 2 and creates a LAMMPS .data file
with atom types, masses, positions, and simulation box dimensions.

Usage:
  cd ~/Documents/Piezo-LLM/src
  python convert_to_lammps.py

Output:
  - PMC-010_lammps.data  (LAMMPS data file, atomic style)
"""

import os
import numpy as np
from pathlib import Path
from ase.io import read
from collections import Counter

# ── Config ──────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SIM_DIR = PROJECT_ROOT / "simulations"

PMC_ID = "PMC-010"
SUPERCELL_SIZE = "2x2x2"  # Must match what you generated in Stage 2


# ── Atomic masses (standard) ────────────────────────
ATOMIC_MASSES = {
    'H': 1.008, 'He': 4.003, 'Li': 6.941, 'Be': 9.012,
    'B': 10.81, 'C': 12.011, 'N': 14.007, 'O': 15.999,
    'F': 18.998, 'Ne': 20.180, 'Na': 22.990, 'Mg': 24.305,
    'Al': 26.982, 'Si': 28.086, 'P': 30.974, 'S': 32.065,
    'Cl': 35.453, 'Ar': 39.948, 'K': 39.098, 'Ca': 40.078,
    'Br': 79.904, 'I': 126.904, 'Zn': 65.38, 'Cu': 63.546,
    'Fe': 55.845,
}


def cif_to_lammps(pmc_id: str, supercell_size: str):
    """
    Convert a supercell CIF to LAMMPS data format.

    LAMMPS data file (atomic style) contains:
      - Header: atom count, type count, box dimensions
      - Masses section: mass for each atom type
      - Atoms section: id, type, x, y, z for each atom
    """
    # ── Find the supercell CIF ──
    sim_dir = SIM_DIR / pmc_id
    cif_path = sim_dir / f"{pmc_id}_supercell_{supercell_size}.cif"

    if not cif_path.exists():
        raise FileNotFoundError(
            f"Supercell CIF not found: {cif_path}\n"
            f"Run generate_supercell.py first (Stage 2)"
        )

    print(f"Reading supercell: {cif_path.name}")
    atoms = read(str(cif_path))

    # ── Get basic info ──
    symbols = atoms.get_chemical_symbols()
    positions = atoms.get_positions()  # Cartesian coordinates in Å
    cell = atoms.get_cell()
    n_atoms = len(atoms)

    print(f"  Atoms: {n_atoms}")
    print(f"  Elements: {sorted(set(symbols))}")
    print(f"  Formula: {atoms.get_chemical_formula()}")

    # ── Assign atom types (1-indexed, sorted alphabetically) ──
    unique_elements = sorted(set(symbols))
    n_types = len(unique_elements)
    element_to_type = {elem: i + 1 for i, elem in enumerate(unique_elements)}

    print(f"\n  Atom type mapping:")
    for elem, type_id in element_to_type.items():
        count = symbols.count(elem)
        mass = ATOMIC_MASSES.get(elem, 0.0)
        print(f"    Type {type_id}: {elem:2s}  (mass: {mass:8.3f} amu, count: {count})")

    # ── Calculate LAMMPS box parameters ──
    # For triclinic/monoclinic boxes, LAMMPS needs:
    #   xlo, xhi, ylo, yhi, zlo, zhi, xy, xz, yz
    #
    # The cell vectors [a, b, c] map to LAMMPS as:
    #   a = (ax, 0, 0)        → ax = xhi - xlo
    #   b = (bx, by, 0)       → bx = xy, by = yhi - ylo
    #   c = (cx, cy, cz)      → cx = xz, cy = yz, cz = zhi - zlo

    cell_matrix = cell.array  # 3×3 matrix, rows are a, b, c vectors

    # Convert to LAMMPS convention
    # ASE cell: row vectors. LAMMPS needs specific orientation.
    a_vec = cell_matrix[0]
    b_vec = cell_matrix[1]
    c_vec = cell_matrix[2]

    # Cell lengths
    a_len = np.linalg.norm(a_vec)
    b_len = np.linalg.norm(b_vec)
    c_len = np.linalg.norm(c_vec)

    # Cell angles
    cos_alpha = np.dot(b_vec, c_vec) / (b_len * c_len)
    cos_beta = np.dot(a_vec, c_vec) / (a_len * c_len)
    cos_gamma = np.dot(a_vec, b_vec) / (a_len * b_len)

    # LAMMPS triclinic box (right-handed, a along x)
    lx = a_len
    xy = b_len * cos_gamma
    xz = c_len * cos_beta
    ly = np.sqrt(b_len**2 - xy**2)
    yz = (b_len * c_len * cos_alpha - xy * xz) / ly
    lz = np.sqrt(c_len**2 - xz**2 - yz**2)

    xlo, xhi = 0.0, lx
    ylo, yhi = 0.0, ly
    zlo, zhi = 0.0, lz

    print(f"\n  LAMMPS box dimensions:")
    print(f"    xlo, xhi = {xlo:.6f}, {xhi:.6f}  (lx = {lx:.4f} Å)")
    print(f"    ylo, yhi = {ylo:.6f}, {yhi:.6f}  (ly = {ly:.4f} Å)")
    print(f"    zlo, zhi = {zlo:.6f}, {zhi:.6f}  (lz = {lz:.4f} Å)")
    print(f"    xy = {xy:.6f}")
    print(f"    xz = {xz:.6f}")
    print(f"    yz = {yz:.6f}")

    is_triclinic = (abs(xy) > 1e-6 or abs(xz) > 1e-6 or abs(yz) > 1e-6)
    print(f"    Box type: {'Triclinic' if is_triclinic else 'Orthogonal'}")

    # ── Transform atom positions to LAMMPS frame ──
    # Build LAMMPS cell matrix (column vectors)
    lammps_cell = np.array([
        [lx, 0.0, 0.0],
        [xy, ly, 0.0],
        [xz, yz, lz]
    ])

    # Convert fractional → LAMMPS Cartesian
    # First get fractional coordinates from ASE
    frac_coords = atoms.get_scaled_positions()

    # Then convert using LAMMPS cell
    lammps_positions = frac_coords @ lammps_cell

    # ── Write LAMMPS data file ──
    output_path = sim_dir / f"{pmc_id}_lammps.data"

    with open(output_path, 'w') as f:
        # Header
        f.write(f"LAMMPS data file for {pmc_id} ({supercell_size} supercell)\n\n")

        f.write(f"{n_atoms} atoms\n")
        f.write(f"{n_types} atom types\n\n")

        # Box bounds
        if is_triclinic:
            f.write(f"{xlo:.6f} {xhi:.6f} xlo xhi\n")
            f.write(f"{ylo:.6f} {yhi:.6f} ylo yhi\n")
            f.write(f"{zlo:.6f} {zhi:.6f} zlo zhi\n")
            f.write(f"{xy:.6f} {xz:.6f} {yz:.6f} xy xz yz\n\n")
        else:
            f.write(f"{xlo:.6f} {xhi:.6f} xlo xhi\n")
            f.write(f"{ylo:.6f} {yhi:.6f} ylo yhi\n")
            f.write(f"{zlo:.6f} {zhi:.6f} zlo zhi\n\n")

        # Masses
        f.write("Masses\n\n")
        for elem, type_id in element_to_type.items():
            mass = ATOMIC_MASSES.get(elem, 0.0)
            f.write(f"{type_id} {mass:.4f}  # {elem}\n")
        f.write("\n")

        # Atoms section (atomic style: id type x y z)
        f.write("Atoms  # atomic\n\n")
        for i in range(n_atoms):
            atom_type = element_to_type[symbols[i]]
            x, y, z = lammps_positions[i]
            f.write(f"{i+1} {atom_type} {x:.6f} {y:.6f} {z:.6f}\n")

    print(f"\n  ✅ Saved LAMMPS data file: {output_path}")
    print(f"     File size: {output_path.stat().st_size / 1024:.1f} KB")

    # ── Verify the file ──
    print(f"\n  Verification:")
    print(f"    First 5 atoms:")
    for i in range(min(5, n_atoms)):
        atom_type = element_to_type[symbols[i]]
        x, y, z = lammps_positions[i]
        print(f"      {i+1:4d}  type {atom_type} ({symbols[i]:2s})  "
              f"x={x:10.4f}  y={y:10.4f}  z={z:10.4f}")

    print(f"    Last 3 atoms:")
    for i in range(max(0, n_atoms - 3), n_atoms):
        atom_type = element_to_type[symbols[i]]
        x, y, z = lammps_positions[i]
        print(f"      {i+1:4d}  type {atom_type} ({symbols[i]:2s})  "
              f"x={x:10.4f}  y={y:10.4f}  z={z:10.4f}")

    # ── Summary ──
    print(f"\n  Element summary in LAMMPS file:")
    counts = Counter(symbols)
    for elem in unique_elements:
        type_id = element_to_type[elem]
        print(f"    Type {type_id} ({elem}): {counts[elem]} atoms")
    print(f"    Total: {sum(counts.values())} atoms")

    return output_path


def preview_lammps_file(filepath: Path, lines: int = 25):
    """Show the first N lines of the LAMMPS data file."""
    print(f"\n{'─' * 60}")
    print(f"  Preview: {filepath.name}")
    print(f"{'─' * 60}")
    with open(filepath) as f:
        for i, line in enumerate(f):
            if i >= lines:
                print(f"  ... ({filepath.stat().st_size / 1024:.1f} KB total)")
                break
            print(f"  {line.rstrip()}")


def main():
    print("=" * 60)
    print("  Piezo-LLM: Stage 3 — LAMMPS Format Conversion")
    print(f"  Molecule: {PMC_ID}")
    print(f"  Supercell: {SUPERCELL_SIZE}")
    print("=" * 60)

    output_path = cif_to_lammps(PMC_ID, SUPERCELL_SIZE)
    preview_lammps_file(output_path)

    print(f"\n{'=' * 60}")
    print(f"  ✅ Stage 3 complete!")
    print(f"  LAMMPS data file: {output_path}")
    print(f"  Next: Stage 4 — Set up MACE force field + LAMMPS input scripts")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()