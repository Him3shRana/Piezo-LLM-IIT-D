"""
Stage 6: Simulation Analysis
─────────────────────────────
Reads the thermodynamic CSV logs from Stage 5 (NVT production),
generates plots, and compares with experimental data from the JSON.

Usage:
  python analyse_simulation.py

Input:
  - simulations/PMC-010/md_results/100K/thermo_100K.csv
  - simulations/PMC-010/md_results/200K/thermo_200K.csv
  - simulations/PMC-010/md_results/300K/thermo_300K.csv
  - simulations/PMC-010/md_results/400K/thermo_400K.csv
  - data/PMC-010/PMC-010.json (experimental reference)

Output:
  - simulations/PMC-010/analysis/
      ├── temperature_evolution.png
      ├── energy_vs_temperature.png
      ├── pressure_evolution.png
      ├── volume_vs_temperature.png
      ├── cell_parameters_vs_temperature.png
      ├── summary_report.txt
      └── comparison_with_experiment.png
"""

import os
import csv
import json
import numpy as np
from pathlib import Path
from collections import defaultdict

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

# ── Config ──────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SIM_DIR = PROJECT_ROOT / "simulations"
DATA_DIR = PROJECT_ROOT / "data"

PMC_ID = "PMC-010"
TEMPERATURES = [100, 200, 300, 400]

# Plot style
plt.rcParams.update({
    'figure.facecolor': 'white',
    'axes.facecolor': '#f8f8f8',
    'axes.grid': True,
    'grid.alpha': 0.3,
    'font.size': 11,
    'axes.titlesize': 13,
    'axes.labelsize': 11,
    'legend.fontsize': 9,
    'figure.dpi': 150,
})

TEMP_COLORS = {
    100: '#3B8BD4',   # blue (cold)
    200: '#1D9E75',   # teal
    300: '#EF9F27',   # amber
    400: '#D85A30',   # coral (hot)
}


def load_thermo_data(pmc_id: str, temperatures: list) -> dict:
    """Load thermodynamic CSV data for each temperature."""
    all_data = {}
    md_dir = SIM_DIR / pmc_id / "md_results"

    for temp in temperatures:
        csv_path = md_dir / f"{temp}K" / f"thermo_{temp}K.csv"

        if not csv_path.exists():
            print(f"  ⚠ Missing: {csv_path}")
            continue

        rows = []
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                parsed = {}
                for key, val in row.items():
                    try:
                        parsed[key] = float(val)
                    except (ValueError, TypeError):
                        parsed[key] = val
                rows.append(parsed)

        all_data[temp] = rows
        print(f"  ✅ Loaded {temp}K: {len(rows)} data points")

    return all_data


def load_experimental_data(pmc_id: str) -> dict:
    """Load experimental reference data from JSON."""
    json_path = DATA_DIR / pmc_id / f"{pmc_id}.json"

    if not json_path.exists():
        print(f"  ⚠ No experimental JSON found: {json_path}")
        return {}

    with open(json_path, 'r') as f:
        data = json.load(f)

    exp = {
        'molecule_name': data.get('molecule_name', pmc_id),
        'crystal_system': data.get('crystal_system', ''),
        'space_group': data.get('space_group_symbol', ''),
        'cell_a': data.get('cell_a'),
        'cell_b': data.get('cell_b'),
        'cell_c': data.get('cell_c'),
        'cell_alpha': data.get('cell_alpha'),
        'cell_beta': data.get('cell_beta'),
        'cell_gamma': data.get('cell_gamma'),
        'cell_volume': data.get('cell_volume'),
        'density': data.get('density_g_cm3'),
        'temperature': data.get('temperature_k'),
        'is_piezoelectric': data.get('is_piezoelectric'),
    }

    print(f"  ✅ Loaded experimental data: {exp['molecule_name']}")
    return exp


def extract_column(data: list, key: str) -> np.ndarray:
    """Extract a column from the thermo data as numpy array."""
    return np.array([row[key] for row in data if key in row])


def plot_temperature_evolution(all_data: dict, output_dir: Path):
    """Plot temperature vs time for all runs."""
    fig, ax = plt.subplots(figsize=(10, 5))

    for temp, data in sorted(all_data.items()):
        time_ps = extract_column(data, 'time_fs') / 1000.0
        temps = extract_column(data, 'temperature_K')
        color = TEMP_COLORS.get(temp, '#888888')
        ax.plot(time_ps, temps, color=color, alpha=0.7, linewidth=0.8,
                label=f'{temp} K (avg: {np.mean(temps):.1f} K)')
        ax.axhline(y=temp, color=color, linestyle='--', alpha=0.3, linewidth=0.5)

    ax.set_xlabel('Time (ps)')
    ax.set_ylabel('Temperature (K)')
    ax.set_title(f'{PMC_ID} — Temperature evolution during NVT production')
    ax.legend(loc='upper right')

    path = output_dir / 'temperature_evolution.png'
    fig.savefig(path, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved: {path.name}")


def plot_energy_vs_temperature(all_data: dict, output_dir: Path):
    """Plot average energy components vs temperature."""
    temps_list = []
    ke_avgs, pe_avgs, total_avgs = [], [], []
    ke_stds, pe_stds, total_stds = [], [], []

    for temp in sorted(all_data.keys()):
        data = all_data[temp]
        ke = extract_column(data, 'kinetic_eV')
        pe = extract_column(data, 'potential_eV')
        total = extract_column(data, 'total_eV')

        temps_list.append(temp)
        ke_avgs.append(np.mean(ke))
        pe_avgs.append(np.mean(pe))
        total_avgs.append(np.mean(total))
        ke_stds.append(np.std(ke))
        pe_stds.append(np.std(pe))
        total_stds.append(np.std(total))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # Total energy vs temperature
    ax1.errorbar(temps_list, total_avgs, yerr=total_stds,
                 marker='o', color='#534AB7', capsize=4, linewidth=2,
                 markersize=8, label='Total energy')
    ax1.set_xlabel('Temperature (K)')
    ax1.set_ylabel('Energy (eV)')
    ax1.set_title('Total energy vs temperature')
    ax1.legend()

    # KE and PE breakdown
    ax2.errorbar(temps_list, ke_avgs, yerr=ke_stds,
                 marker='s', color='#D85A30', capsize=4, linewidth=2,
                 markersize=7, label='Kinetic')
    ax2.errorbar(temps_list, pe_avgs, yerr=pe_stds,
                 marker='^', color='#3B8BD4', capsize=4, linewidth=2,
                 markersize=7, label='Potential')
    ax2.set_xlabel('Temperature (K)')
    ax2.set_ylabel('Energy (eV)')
    ax2.set_title('Energy breakdown vs temperature')
    ax2.legend()

    fig.suptitle(f'{PMC_ID} — Energy analysis', fontsize=14)
    fig.tight_layout()

    path = output_dir / 'energy_vs_temperature.png'
    fig.savefig(path, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved: {path.name}")


def plot_pressure_evolution(all_data: dict, output_dir: Path):
    """Plot pressure vs time for all runs."""
    fig, ax = plt.subplots(figsize=(10, 5))

    for temp, data in sorted(all_data.items()):
        time_ps = extract_column(data, 'time_fs') / 1000.0
        pressure = extract_column(data, 'pressure_GPa')
        color = TEMP_COLORS.get(temp, '#888888')
        ax.plot(time_ps, pressure, color=color, alpha=0.6, linewidth=0.8,
                label=f'{temp} K (avg: {np.mean(pressure):.3f} GPa)')

    ax.axhline(y=0, color='black', linestyle='-', alpha=0.2, linewidth=0.5)
    ax.set_xlabel('Time (ps)')
    ax.set_ylabel('Pressure (GPa)')
    ax.set_title(f'{PMC_ID} — Pressure evolution during NVT production')
    ax.legend(loc='upper right')

    path = output_dir / 'pressure_evolution.png'
    fig.savefig(path, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved: {path.name}")


def plot_volume_vs_temperature(all_data: dict, exp_data: dict, output_dir: Path):
    """Plot volume vs temperature with experimental reference."""
    temps_list = []
    vol_avgs, vol_stds = [], []

    for temp in sorted(all_data.keys()):
        data = all_data[temp]
        vols = extract_column(data, 'volume_A3')
        temps_list.append(temp)
        vol_avgs.append(np.mean(vols))
        vol_stds.append(np.std(vols))

    fig, ax = plt.subplots(figsize=(8, 5))

    ax.errorbar(temps_list, vol_avgs, yerr=vol_stds,
                marker='o', color='#534AB7', capsize=4, linewidth=2,
                markersize=8, label='Simulated (MACE-OFF23)')

    # Experimental reference (if available)
    if exp_data.get('cell_volume') and exp_data.get('temperature'):
        exp_vol = exp_data['cell_volume']
        exp_temp = exp_data['temperature']
        # Scale unit cell volume to supercell (2×2×2 = 8× volume)
        exp_vol_supercell = exp_vol * 8
        ax.scatter([exp_temp], [exp_vol_supercell], marker='*', s=200,
                   color='#D85A30', zorder=5, label=f'Experimental ({exp_temp} K)')
        ax.annotate(f'{exp_vol_supercell:.0f} ų',
                    xy=(exp_temp, exp_vol_supercell),
                    xytext=(exp_temp + 20, exp_vol_supercell + 50),
                    fontsize=9, color='#D85A30',
                    arrowprops=dict(arrowstyle='->', color='#D85A30'))

    ax.set_xlabel('Temperature (K)')
    ax.set_ylabel('Volume (ų)')
    ax.set_title(f'{PMC_ID} — Volume vs temperature')
    ax.legend()

    path = output_dir / 'volume_vs_temperature.png'
    fig.savefig(path, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved: {path.name}")


def plot_cell_parameters(all_data: dict, exp_data: dict, output_dir: Path):
    """Plot cell parameters (a, b, c, β) vs temperature."""
    fig, axes = plt.subplots(2, 2, figsize=(12, 9))

    params = [
        ('a_A', 'a (Å)', 'cell_a', axes[0, 0]),
        ('b_A', 'b (Å)', 'cell_b', axes[0, 1]),
        ('c_A', 'c (Å)', 'cell_c', axes[1, 0]),
        ('beta_deg', 'β (°)', 'cell_beta', axes[1, 1]),
    ]

    for csv_key, label, json_key, ax in params:
        temps_list = []
        avgs, stds = [], []

        for temp in sorted(all_data.keys()):
            data = all_data[temp]
            values = extract_column(data, csv_key)
            if len(values) > 0:
                temps_list.append(temp)
                # For supercell, a/b/c are 2× the unit cell values
                avgs.append(np.mean(values))
                stds.append(np.std(values))

        if temps_list:
            ax.errorbar(temps_list, avgs, yerr=stds,
                        marker='o', color='#534AB7', capsize=4,
                        linewidth=2, markersize=7, label='Simulated')

        # Experimental reference
        exp_val = exp_data.get(json_key)
        exp_temp = exp_data.get('temperature')
        if exp_val and exp_temp:
            # Scale cell params for supercell (a, b, c × 2 for 2×2×2)
            if json_key in ['cell_a', 'cell_b', 'cell_c']:
                exp_val_scaled = exp_val * 2
            else:
                exp_val_scaled = exp_val
            ax.scatter([exp_temp], [exp_val_scaled], marker='*', s=150,
                       color='#D85A30', zorder=5, label=f'Experimental')

        ax.set_xlabel('Temperature (K)')
        ax.set_ylabel(label)
        ax.set_title(label)
        ax.legend(fontsize=8)

    fig.suptitle(f'{PMC_ID} — Cell parameters vs temperature', fontsize=14)
    fig.tight_layout()

    path = output_dir / 'cell_parameters_vs_temperature.png'
    fig.savefig(path, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved: {path.name}")


def plot_comparison_dashboard(all_data: dict, exp_data: dict, output_dir: Path):
    """Single comparison dashboard: simulated vs experimental at 300K."""
    if 300 not in all_data:
        print("  ⚠ No 300K data for comparison dashboard")
        return

    data_300 = all_data[300]

    # Simulated averages at 300K
    sim = {
        'temperature': np.mean(extract_column(data_300, 'temperature_K')),
        'volume': np.mean(extract_column(data_300, 'volume_A3')),
        'a': np.mean(extract_column(data_300, 'a_A')),
        'b': np.mean(extract_column(data_300, 'b_A')),
        'c': np.mean(extract_column(data_300, 'c_A')),
        'beta': np.mean(extract_column(data_300, 'beta_deg')),
        'pressure': np.mean(extract_column(data_300, 'pressure_GPa')),
    }

    # Experimental values (scaled to supercell)
    exp = {
        'temperature': exp_data.get('temperature', 'N/A'),
        'volume': (exp_data.get('cell_volume', 0) or 0) * 8,
        'a': (exp_data.get('cell_a', 0) or 0) * 2,
        'b': (exp_data.get('cell_b', 0) or 0) * 2,
        'c': (exp_data.get('cell_c', 0) or 0) * 2,
        'beta': exp_data.get('cell_beta', 0) or 0,
    }

    fig, axes = plt.subplots(1, 3, figsize=(14, 5))

    # Bar chart: cell parameters
    labels = ['a (Å)', 'b (Å)', 'c (Å)', 'β (°)']
    sim_vals = [sim['a'], sim['b'], sim['c'], sim['beta']]
    exp_vals = [exp['a'], exp['b'], exp['c'], exp['beta']]

    x = np.arange(len(labels))
    width = 0.35

    axes[0].bar(x - width/2, sim_vals, width, label='Simulated (300K)',
                color='#534AB7', alpha=0.8)
    axes[0].bar(x + width/2, exp_vals, width, label=f'Experimental ({exp["temperature"]}K)',
                color='#D85A30', alpha=0.8)
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(labels)
    axes[0].set_title('Cell parameters')
    axes[0].legend(fontsize=8)

    # Volume comparison
    axes[1].bar(['Simulated\n(300K)', f'Experimental\n({exp["temperature"]}K)'],
                [sim['volume'], exp['volume']],
                color=['#534AB7', '#D85A30'], alpha=0.8)
    axes[1].set_ylabel('Volume (ų)')
    axes[1].set_title('Supercell volume')

    # Percentage differences
    if exp['a'] > 0:
        diffs = {
            'a': abs(sim['a'] - exp['a']) / exp['a'] * 100,
            'b': abs(sim['b'] - exp['b']) / exp['b'] * 100,
            'c': abs(sim['c'] - exp['c']) / exp['c'] * 100,
            'β': abs(sim['beta'] - exp['beta']) / exp['beta'] * 100 if exp['beta'] else 0,
            'V': abs(sim['volume'] - exp['volume']) / exp['volume'] * 100 if exp['volume'] else 0,
        }

        diff_labels = list(diffs.keys())
        diff_vals = list(diffs.values())
        bar_colors = ['#1D9E75' if d < 2 else '#EF9F27' if d < 5 else '#D85A30'
                      for d in diff_vals]

        axes[2].barh(diff_labels, diff_vals, color=bar_colors, alpha=0.8)
        axes[2].set_xlabel('Difference (%)')
        axes[2].set_title('Simulated vs experimental')
        axes[2].axvline(x=2, color='#1D9E75', linestyle='--', alpha=0.5, label='< 2% (good)')
        axes[2].axvline(x=5, color='#EF9F27', linestyle='--', alpha=0.5, label='< 5% (ok)')
        axes[2].legend(fontsize=7, loc='lower right')

    fig.suptitle(f'{PMC_ID} ({exp_data.get("molecule_name", "")}) — Simulation vs Experiment',
                 fontsize=14)
    fig.tight_layout()

    path = output_dir / 'comparison_with_experiment.png'
    fig.savefig(path, bbox_inches='tight')
    plt.close(fig)
    print(f"  Saved: {path.name}")


def generate_summary_report(all_data: dict, exp_data: dict, output_dir: Path):
    """Generate a text summary report."""
    path = output_dir / 'summary_report.txt'

    with open(path, 'w') as f:
        f.write("=" * 70 + "\n")
        f.write(f"  Simulation Analysis Report: {PMC_ID}\n")
        f.write(f"  {exp_data.get('molecule_name', '')}\n")
        f.write("=" * 70 + "\n\n")

        f.write("EXPERIMENTAL REFERENCE\n")
        f.write("-" * 40 + "\n")
        f.write(f"  Crystal system:  {exp_data.get('crystal_system', 'N/A')}\n")
        f.write(f"  Space group:     {exp_data.get('space_group', 'N/A')}\n")
        f.write(f"  Temperature:     {exp_data.get('temperature', 'N/A')} K\n")
        f.write(f"  a = {exp_data.get('cell_a', 'N/A')} Å\n")
        f.write(f"  b = {exp_data.get('cell_b', 'N/A')} Å\n")
        f.write(f"  c = {exp_data.get('cell_c', 'N/A')} Å\n")
        f.write(f"  β = {exp_data.get('cell_beta', 'N/A')}°\n")
        f.write(f"  Volume = {exp_data.get('cell_volume', 'N/A')} ų\n")
        f.write(f"  Piezoelectric: {exp_data.get('is_piezoelectric', 'N/A')}\n\n")

        f.write("SIMULATION RESULTS (MACE-OFF23)\n")
        f.write("-" * 40 + "\n")
        f.write(f"  {'Temp (K)':<10} {'Avg T (K)':<12} {'Avg E (eV)':<14} "
                f"{'Avg P (GPa)':<14} {'Avg V (ų)':<14}\n")
        f.write(f"  {'-'*62}\n")

        for temp in sorted(all_data.keys()):
            data = all_data[temp]
            avg_t = np.mean(extract_column(data, 'temperature_K'))
            avg_e = np.mean(extract_column(data, 'total_eV'))
            avg_p = np.mean(extract_column(data, 'pressure_GPa'))
            avg_v = np.mean(extract_column(data, 'volume_A3'))
            f.write(f"  {temp:<10} {avg_t:<12.1f} {avg_e:<14.2f} "
                    f"{avg_p:<14.4f} {avg_v:<14.1f}\n")

        # Comparison at 300K
        if 300 in all_data and exp_data.get('cell_volume'):
            f.write(f"\n\nCOMPARISON AT 300K\n")
            f.write("-" * 40 + "\n")
            data_300 = all_data[300]

            sim_vol = np.mean(extract_column(data_300, 'volume_A3'))
            exp_vol = exp_data['cell_volume'] * 8  # supercell
            vol_diff = abs(sim_vol - exp_vol) / exp_vol * 100

            sim_a = np.mean(extract_column(data_300, 'a_A'))
            exp_a = exp_data.get('cell_a', 0) * 2
            a_diff = abs(sim_a - exp_a) / exp_a * 100 if exp_a else 0

            sim_b = np.mean(extract_column(data_300, 'b_A'))
            exp_b = exp_data.get('cell_b', 0) * 2
            b_diff = abs(sim_b - exp_b) / exp_b * 100 if exp_b else 0

            sim_c = np.mean(extract_column(data_300, 'c_A'))
            exp_c = exp_data.get('cell_c', 0) * 2
            c_diff = abs(sim_c - exp_c) / exp_c * 100 if exp_c else 0

            f.write(f"  {'Parameter':<12} {'Simulated':<14} {'Experimental':<14} {'Diff %':<10}\n")
            f.write(f"  {'-'*48}\n")
            f.write(f"  {'Volume':<12} {sim_vol:<14.1f} {exp_vol:<14.1f} {vol_diff:<10.2f}\n")
            f.write(f"  {'a':<12} {sim_a:<14.4f} {exp_a:<14.4f} {a_diff:<10.2f}\n")
            f.write(f"  {'b':<12} {sim_b:<14.4f} {exp_b:<14.4f} {b_diff:<10.2f}\n")
            f.write(f"  {'c':<12} {sim_c:<14.4f} {exp_c:<14.4f} {c_diff:<10.2f}\n")

            f.write(f"\n  Overall assessment: ")
            max_diff = max(vol_diff, a_diff, b_diff, c_diff)
            if max_diff < 2:
                f.write("✅ Excellent agreement (< 2% deviation)\n")
            elif max_diff < 5:
                f.write("✅ Good agreement (< 5% deviation)\n")
            elif max_diff < 10:
                f.write("⚠ Fair agreement (< 10% deviation)\n")
            else:
                f.write("❌ Significant deviation (> 10%) — consider longer simulation or larger supercell\n")

        f.write(f"\n{'=' * 70}\n")

    print(f"  Saved: {path.name}")
    return path


def main():
    print("=" * 60)
    print(f"  Piezo-LLM: Stage 6 — Simulation Analysis")
    print(f"  Molecule: {PMC_ID}")
    print(f"  Temperatures: {TEMPERATURES} K")
    print("=" * 60)

    # Create output directory
    output_dir = SIM_DIR / PMC_ID / "analysis"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load data
    print("\nLoading thermodynamic data...")
    all_data = load_thermo_data(PMC_ID, TEMPERATURES)

    if not all_data:
        print("\n❌ No simulation data found.")
        print(f"   Run the simulation first: python run_mace_simulation.py")
        print(f"   Expected location: {SIM_DIR / PMC_ID / 'md_results'}")
        return

    print("\nLoading experimental reference...")
    exp_data = load_experimental_data(PMC_ID)

    # Generate plots
    print("\nGenerating plots...")
    plot_temperature_evolution(all_data, output_dir)
    plot_energy_vs_temperature(all_data, output_dir)
    plot_pressure_evolution(all_data, output_dir)
    plot_volume_vs_temperature(all_data, exp_data, output_dir)
    plot_cell_parameters(all_data, exp_data, output_dir)
    plot_comparison_dashboard(all_data, exp_data, output_dir)

    # Summary report
    print("\nGenerating summary report...")
    report_path = generate_summary_report(all_data, exp_data, output_dir)

    # Print summary to terminal
    print(f"\n{'=' * 60}")
    print(f"  ✅ Analysis complete!")
    print(f"  Output: {output_dir}")
    print(f"\n  Generated files:")
    for f in sorted(output_dir.iterdir()):
        size = f.stat().st_size / 1024
        print(f"    {f.name:<40} ({size:.1f} KB)")

    # Print report to terminal too
    print(f"\n{'=' * 60}")
    with open(report_path) as f:
        print(f.read())


if __name__ == "__main__":
    main()