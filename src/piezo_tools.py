"""
piezo_tools.py
──────────────
All Piezo-LLM capabilities wrapped as tool functions.
The agent calls these — users never touch them directly.

Each tool has:
  - A clear name and description (for the LLM to understand)
  - Input parameters with types
  - A return dict with results
"""

import json
import os
import re
import csv
import numpy as np
from pathlib import Path
from collections import Counter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SIM_DIR = PROJECT_ROOT / "simulations"
VECTORDB_DIR = PROJECT_ROOT / "vectordb"
MASTER_DB_PATH = PROJECT_ROOT / "gui" / "public" / "database" / "master_database.json"


# ═══════════════════════════════════════════════════
# TOOL DEFINITIONS (for the LLM)
# ═══════════════════════════════════════════════════

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "search_crystals",
            "description": "Search the piezoelectric crystal database by name, formula, property, or any query. Returns matching crystals with their key properties.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query. Examples: 'L-Alanine', 'monoclinic crystals', 'PMC-010', 'amino acid piezoelectric'"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_crystal_details",
            "description": "Get full details of a specific crystal by its PMC ID. Returns all properties: cell parameters, space group, piezoelectric data, references, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pmc_id": {
                        "type": "string",
                        "description": "The PMC ID, e.g. 'PMC-010', 'PMC-007'"
                    }
                },
                "required": ["pmc_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_crystals",
            "description": "List all crystals in the database with optional filtering by crystal system, space group, or piezoelectric status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filter_by": {
                        "type": "string",
                        "description": "Optional filter: 'piezoelectric', 'ferroelectric', 'monoclinic', 'orthorhombic', 'triclinic', or a space group like 'P21'"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_supercell",
            "description": "Generate a supercell from a crystal's CIF file. Creates 2x2x2 or 3x3x3 replication of the unit cell for molecular dynamics simulation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pmc_id": {
                        "type": "string",
                        "description": "The PMC ID, e.g. 'PMC-010'"
                    },
                    "size": {
                        "type": "integer",
                        "description": "Supercell size: 2 for 2x2x2, 3 for 3x3x3. Default is 2.",
                        "default": 2
                    }
                },
                "required": ["pmc_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_simulation",
            "description": "Run MACE-OFF23 molecular dynamics simulation on a crystal supercell. Performs energy minimisation, NVT equilibration, and NVT production. Requires GPU.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pmc_id": {
                        "type": "string",
                        "description": "The PMC ID, e.g. 'PMC-010'"
                    },
                    "temperatures": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Temperatures in Kelvin. Default: [300]. Example: [100, 200, 300, 400]"
                    },
                    "supercell_size": {
                        "type": "string",
                        "description": "Supercell size string. Default: '2x2x2'"
                    },
                    "production_steps": {
                        "type": "integer",
                        "description": "Number of NVT production steps. Default: 5000"
                    }
                },
                "required": ["pmc_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyse_results",
            "description": "Analyse simulation results: generate plots, compare with experimental data, create summary report. Run this after simulation is complete.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pmc_id": {
                        "type": "string",
                        "description": "The PMC ID, e.g. 'PMC-010'"
                    },
                    "temperatures": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "description": "Temperatures to analyse. Default: [100, 200, 300, 400]"
                    }
                },
                "required": ["pmc_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compare_crystals",
            "description": "Compare properties of two or more crystals side by side. Shows cell parameters, space groups, piezoelectric properties, and any simulation results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pmc_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of PMC IDs to compare, e.g. ['PMC-007', 'PMC-010']"
                    }
                },
                "required": ["pmc_ids"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_simulation_status",
            "description": "Check if simulation results exist for a given crystal and what data is available.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pmc_id": {
                        "type": "string",
                        "description": "The PMC ID, e.g. 'PMC-010'"
                    }
                },
                "required": ["pmc_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "database_stats",
            "description": "Get overall statistics about the piezoelectric crystal database: total crystals, crystal systems, space groups, etc.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
]


# ═══════════════════════════════════════════════════
# TOOL IMPLEMENTATIONS
# ═══════════════════════════════════════════════════

def _load_master_db() -> dict:
    """Load the master database JSON."""
    if not MASTER_DB_PATH.exists():
        return {}
    with open(MASTER_DB_PATH, 'r') as f:
        return json.load(f)


def search_crystals(query: str) -> dict:
    """Search crystals by name, formula, or property."""
    # Try vector search first
    results = []

    try:
        from langchain_huggingface import HuggingFaceEmbeddings
        from langchain_chroma import Chroma

        db = Chroma(
            collection_name="piezo_crystals",
            embedding_function=HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5"),
            persist_directory=str(VECTORDB_DIR),
        )
        docs = db.similarity_search(query, k=5)
        for doc in docs:
            results.append({
                'pmc_id': doc.metadata.get('pmc_id', ''),
                'molecule_name': doc.metadata.get('molecule_name', ''),
                'crystal_system': doc.metadata.get('crystal_system', ''),
                'space_group': doc.metadata.get('space_group', ''),
                'is_piezoelectric': doc.metadata.get('is_piezoelectric', ''),
                'preview': doc.page_content[:200] + '...'
            })
    except Exception as e:
        # Fallback to JSON search
        master = _load_master_db()
        crystals = master.get('crystals', {})
        q_lower = query.lower()

        for pmc_id, crystal in crystals.items():
            name = (crystal.get('molecule_name', '') or '').lower()
            formula = (crystal.get('chemical_formula', '') or '').lower()
            system = (crystal.get('crystal_system', '') or '').lower()
            sg = (crystal.get('space_group_symbol', '') or '').lower()

            if (q_lower in name or q_lower in formula or
                q_lower in system or q_lower in pmc_id.lower() or
                q_lower in sg):
                results.append({
                    'pmc_id': pmc_id,
                    'molecule_name': crystal.get('molecule_name', ''),
                    'crystal_system': crystal.get('crystal_system', ''),
                    'space_group': crystal.get('space_group_symbol', ''),
                    'is_piezoelectric': crystal.get('is_piezoelectric', ''),
                })

    return {
        'status': 'success',
        'query': query,
        'count': len(results),
        'results': results
    }


def get_crystal_details(pmc_id: str) -> dict:
    """Get full details of a specific crystal."""
    pmc_id = pmc_id.upper()
    if not pmc_id.startswith('PMC-'):
        pmc_id = f'PMC-{pmc_id}'

    # Load from individual JSON
    json_path = DATA_DIR / pmc_id / f"{pmc_id}.json"
    if json_path.exists():
        with open(json_path, 'r') as f:
            data = json.load(f)

        # Check what files are available
        folder = DATA_DIR / pmc_id
        data['available_files'] = {
            'json': bool(list(folder.glob('*.json'))),
            'cif': bool(list(folder.glob('*.cif'))),
            'pdf': bool(list(folder.glob('*.pdf'))),
            'txt': bool(list(folder.glob('*.txt'))),
        }

        # Check simulation status
        sim_dir = SIM_DIR / pmc_id / "md_results"
        data['has_simulation'] = sim_dir.exists()

        return {'status': 'success', 'data': data}

    # Try master database
    master = _load_master_db()
    crystals = master.get('crystals', {})
    if pmc_id in crystals:
        return {'status': 'success', 'data': crystals[pmc_id]}

    return {'status': 'error', 'message': f'{pmc_id} not found in database'}


def list_crystals(filter_by: str = None) -> dict:
    """List all crystals with optional filtering."""
    master = _load_master_db()
    crystals = master.get('crystals', {})

    results = []
    for pmc_id, crystal in sorted(crystals.items()):
        include = True

        if filter_by:
            f = filter_by.lower()
            if f == 'piezoelectric':
                include = crystal.get('is_piezoelectric') == True
            elif f == 'ferroelectric':
                include = crystal.get('is_ferroelectric') == True
            elif f in ['monoclinic', 'orthorhombic', 'triclinic', 'hexagonal', 'tetragonal', 'cubic', 'trigonal']:
                include = (crystal.get('crystal_system', '') or '').lower() == f
            else:
                include = f in (crystal.get('space_group_symbol', '') or '').lower()

        if include:
            results.append({
                'pmc_id': pmc_id,
                'molecule_name': crystal.get('molecule_name', ''),
                'crystal_system': crystal.get('crystal_system', ''),
                'space_group': crystal.get('space_group_symbol', ''),
                'is_piezoelectric': crystal.get('is_piezoelectric'),
            })

    return {
        'status': 'success',
        'total': len(results),
        'filter': filter_by,
        'crystals': results
    }


def generate_supercell(pmc_id: str, size: int = 2) -> dict:
    """Generate a supercell from a crystal's CIF file."""
    pmc_id = pmc_id.upper()
    if not pmc_id.startswith('PMC-'):
        pmc_id = f'PMC-{pmc_id}'

    # Find CIF file
    folder = DATA_DIR / pmc_id
    if not folder.exists():
        return {'status': 'error', 'message': f'Folder not found: {folder}'}

    cif_files = list(folder.glob('*.cif'))
    if not cif_files:
        return {'status': 'error', 'message': f'No CIF file found for {pmc_id}'}

    try:
        from ase.io import read, write
        from ase.build import make_supercell

        atoms = read(str(cif_files[0]))
        P = np.diag([size, size, size])
        supercell = make_supercell(atoms, P)

        # Save outputs
        sim_dir = SIM_DIR / pmc_id
        sim_dir.mkdir(parents=True, exist_ok=True)

        size_str = f"{size}x{size}x{size}"
        cif_out = sim_dir / f"{pmc_id}_supercell_{size_str}.cif"
        write(str(cif_out), supercell, format='cif')

        cell = supercell.get_cell()
        a, b, c, alpha, beta, gamma = cell.cellpar()

        return {
            'status': 'success',
            'pmc_id': pmc_id,
            'supercell_size': size_str,
            'unit_cell_atoms': len(atoms),
            'supercell_atoms': len(supercell),
            'cell_parameters': {
                'a': round(a, 4), 'b': round(b, 4), 'c': round(c, 4),
                'alpha': round(alpha, 2), 'beta': round(beta, 2), 'gamma': round(gamma, 2),
            },
            'volume': round(cell.volume, 2),
            'output_file': str(cif_out),
            'formula': supercell.get_chemical_formula(),
        }

    except Exception as e:
        return {'status': 'error', 'message': str(e)}


def run_simulation(pmc_id: str, temperatures: list = None,
                   supercell_size: str = "2x2x2",
                   production_steps: int = 5000,
                   mace_model: str = "medium") -> dict:
    """Run MACE-OFF23 MD simulation directly."""
    pmc_id = pmc_id.upper()
    if not pmc_id.startswith('PMC-'):
        pmc_id = f'PMC-{pmc_id}'
    if temperatures is None:
        temperatures = [300]
    try:
        import subprocess, os as _os
        temps_str = ' '.join(str(t) for t in temperatures)
        size = int(supercell_size[0]) if isinstance(supercell_size, str) else supercell_size
        cmd = f"python3 run_all.py {pmc_id} --temps {temps_str} --steps {production_steps} --size {size} --model {mace_model}"
        work_dir = _os.path.dirname(_os.path.abspath(__file__))
        result = subprocess.run(cmd, shell=True, cwd=work_dir, capture_output=True, text=True, timeout=7200)
        if result.returncode == 0:
            return {'status': 'success', 'pmc_id': pmc_id, 'temperatures': temperatures, 'steps': production_steps, 'message': f'Simulation complete for {pmc_id}', 'output': result.stdout[-500:] if result.stdout else ''}
        else:
            return {'status': 'error', 'message': result.stderr[-500:] if result.stderr else 'Simulation failed'}
    except subprocess.TimeoutExpired:
        return {'status': 'error', 'message': 'Simulation timed out after 2 hours'}
    except Exception as e:
        return {'status': 'error', 'message': f'Could not run simulation: {str(e)}'}


def analyse_results(pmc_id: str, temperatures: list = None) -> dict:
    """Analyse simulation results and generate plots."""
    pmc_id = pmc_id.upper()
    if not pmc_id.startswith('PMC-'):
        pmc_id = f'PMC-{pmc_id}'

    if temperatures is None:
        temperatures = [100, 200, 300, 400]

    md_dir = SIM_DIR / pmc_id / "md_results"
    if not md_dir.exists():
        return {'status': 'error', 'message': f'No simulation results found for {pmc_id}'}

    # Load available thermo data
    all_data = {}
    for temp in temperatures:
        csv_path = md_dir / f"{temp}K" / f"thermo_{temp}K.csv"
        if csv_path.exists():
            rows = []
            with open(csv_path, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append({k: float(v) for k, v in row.items()})
            all_data[temp] = rows

    if not all_data:
        return {'status': 'error', 'message': f'No thermo CSV files found for {pmc_id}'}

    # Load experimental data
    exp = {}
    json_path = DATA_DIR / pmc_id / f"{pmc_id}.json"
    if json_path.exists():
        with open(json_path, 'r') as f:
            exp = json.load(f)

    # Generate summary
    summary = {}
    for temp, data in sorted(all_data.items()):
        temps_arr = [d['temperature_K'] for d in data]
        energies = [d['total_eV'] for d in data]
        pressures = [d['pressure_GPa'] for d in data]
        volumes = [d['volume_A3'] for d in data]

        summary[temp] = {
            'avg_temperature': round(np.mean(temps_arr), 1),
            'std_temperature': round(np.std(temps_arr), 1),
            'avg_energy': round(np.mean(energies), 2),
            'avg_pressure': round(np.mean(pressures), 4),
            'avg_volume': round(np.mean(volumes), 1),
        }

    # Comparison with experiment at 300K
    comparison = None
    if 300 in all_data and exp.get('cell_volume'):
        data_300 = all_data[300]
        sim_vol = np.mean([d['volume_A3'] for d in data_300])
        exp_vol = exp['cell_volume'] * 8  # supercell scale

        comparison = {
            'simulated_volume': round(sim_vol, 1),
            'experimental_volume': round(exp_vol, 1),
            'volume_difference_percent': round(abs(sim_vol - exp_vol) / exp_vol * 100, 2),
            'experimental_temperature': exp.get('temperature_k'),
        }

    # Try to generate plots
    plots_generated = []
    try:
        import analyse_simulation
        output_dir = SIM_DIR / pmc_id / "analysis"
        output_dir.mkdir(parents=True, exist_ok=True)

        analyse_simulation.PMC_ID = pmc_id
        analyse_simulation.TEMPERATURES = list(all_data.keys())

        analyse_simulation.plot_temperature_evolution(all_data, output_dir)
        plots_generated.append('temperature_evolution.png')

        analyse_simulation.plot_energy_vs_temperature(all_data, output_dir)
        plots_generated.append('energy_vs_temperature.png')

        analyse_simulation.plot_volume_vs_temperature(all_data, exp, output_dir)
        plots_generated.append('volume_vs_temperature.png')

        analyse_simulation.plot_comparison_dashboard(all_data, exp, output_dir)
        plots_generated.append('comparison_with_experiment.png')
    except Exception as e:
        plots_generated.append(f'plot_error: {str(e)}')

    return {
        'status': 'success',
        'pmc_id': pmc_id,
        'temperatures_analysed': list(all_data.keys()),
        'summary': summary,
        'comparison_300K': comparison,
        'plots': plots_generated,
        'molecule_name': exp.get('molecule_name', pmc_id),
    }


def compare_crystals(pmc_ids: list) -> dict:
    """Compare properties of multiple crystals."""
    comparisons = []
    for pmc_id in pmc_ids:
        result = get_crystal_details(pmc_id)
        if result['status'] == 'success':
            d = result['data']
            comparisons.append({
                'pmc_id': d.get('id', pmc_id),
                'molecule_name': d.get('molecule_name', ''),
                'crystal_system': d.get('crystal_system', ''),
                'space_group': d.get('space_group_symbol', ''),
                'cell_a': d.get('cell_a'),
                'cell_b': d.get('cell_b'),
                'cell_c': d.get('cell_c'),
                'cell_beta': d.get('cell_beta'),
                'cell_volume': d.get('cell_volume'),
                'is_piezoelectric': d.get('is_piezoelectric'),
                'experimental_method': d.get('experimental_method', ''),
                'density': d.get('density_g_cm3'),
            })

    return {
        'status': 'success',
        'count': len(comparisons),
        'crystals': comparisons
    }


def get_simulation_status(pmc_id: str) -> dict:
    """Check simulation status for a crystal."""
    pmc_id = pmc_id.upper()
    if not pmc_id.startswith('PMC-'):
        pmc_id = f'PMC-{pmc_id}'

    sim_dir = SIM_DIR / pmc_id
    md_dir = sim_dir / "md_results"
    analysis_dir = sim_dir / "analysis"

    status = {
        'pmc_id': pmc_id,
        'has_supercell': bool(list(sim_dir.glob('*_supercell_*.cif'))) if sim_dir.exists() else False,
        'has_simulation': md_dir.exists(),
        'has_analysis': analysis_dir.exists(),
        'supercell_files': [],
        'simulation_temperatures': [],
        'analysis_files': [],
    }

    if sim_dir.exists():
        status['supercell_files'] = [f.name for f in sim_dir.glob('*_supercell_*')]

    if md_dir.exists():
        for d in sorted(md_dir.iterdir()):
            if d.is_dir() and d.name.endswith('K'):
                temp = d.name.replace('K', '')
                csv_file = d / f"thermo_{d.name}.csv"
                status['simulation_temperatures'].append({
                    'temperature': temp,
                    'has_thermo_csv': csv_file.exists(),
                    'has_trajectory': bool(list(d.glob('*.traj'))),
                })

    if analysis_dir.exists():
        status['analysis_files'] = [f.name for f in sorted(analysis_dir.iterdir())]

    return {'status': 'success', 'data': status}


def database_stats() -> dict:
    """Get overall database statistics."""
    master = _load_master_db()
    crystals = master.get('crystals', {})

    systems = Counter()
    space_groups = Counter()
    piezo_count = 0
    ferro_count = 0

    for crystal in crystals.values():
        cs = crystal.get('crystal_system', 'Unknown')
        sg = crystal.get('space_group_symbol', 'Unknown')
        systems[cs] += 1
        space_groups[sg] += 1
        if crystal.get('is_piezoelectric'):
            piezo_count += 1
        if crystal.get('is_ferroelectric'):
            ferro_count += 1

    # Check simulations
    sim_count = 0
    if SIM_DIR.exists():
        for d in SIM_DIR.iterdir():
            if d.is_dir() and (d / "md_results").exists():
                sim_count += 1

    return {
        'status': 'success',
        'total_crystals': len(crystals),
        'piezoelectric': piezo_count,
        'ferroelectric': ferro_count,
        'crystal_systems': dict(systems.most_common()),
        'top_space_groups': dict(space_groups.most_common(10)),
        'crystals_with_simulations': sim_count,
    }


# ═══════════════════════════════════════════════════
# TOOL EXECUTOR
# ═══════════════════════════════════════════════════

TOOL_MAP = {
    'search_crystals': search_crystals,
    'get_crystal_details': get_crystal_details,
    'list_crystals': list_crystals,
    'generate_supercell': generate_supercell,
    'run_simulation': run_simulation,
    'analyse_results': analyse_results,
    'compare_crystals': compare_crystals,
    'get_simulation_status': get_simulation_status,
    'database_stats': database_stats,
}


def execute_tool(name: str, arguments: dict) -> dict:
    """Execute a tool by name with given arguments."""
    if name not in TOOL_MAP:
        return {'status': 'error', 'message': f'Unknown tool: {name}'}

    try:
        return TOOL_MAP[name](**arguments)
    except Exception as e:
        return {'status': 'error', 'message': f'Tool {name} failed: {str(e)}'}