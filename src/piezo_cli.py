"""
piezo_cli.py
────────────
Interactive terminal interface for the Piezo Agent.

Usage:
  python piezo_cli.py              # Offline mode (no GPU needed)
  python piezo_cli.py --llm        # LLM mode (needs vLLM + Qwen3)
  python piezo_cli.py --llm-url http://gpu:8000  # Custom LLM server

Commands inside the CLI:
  Type any question or command naturally
  /help     - Show available commands
  /tools    - List available tools
  /status   - Show system status
  /quit     - Exit
"""

import sys
import json
from piezo_agent import PiezoAgent


BANNER = """
╔═══════════════════════════════════════════════════╗
║                                                   ║
║   ⚡ Piezo-LLM Agent                              ║
║   Piezoelectric Molecular Crystal Assistant        ║
║                                                   ║
║   Type naturally or use /help for commands         ║
║   Type /quit to exit                               ║
║                                                   ║
╚═══════════════════════════════════════════════════╝
"""

HELP_TEXT = """
  Available commands:
  ──────────────────────────────────────────────
  /help              Show this help
  /tools             List available tools
  /status            Show database & system status
  /status PMC-010    Check simulation status for a crystal
  /quit              Exit the CLI

  Example queries:
  ──────────────────────────────────────────────
  "How many crystals are in the database?"
  "Tell me about L-Arginine Hydrochloride"
  "What is the space group of PMC-010?"
  "List all monoclinic crystals"
  "Compare PMC-007 and PMC-010"
  "Generate 2x2x2 supercell for PMC-010"
  "Check simulation status for PMC-010"
  "Search for amino acid crystals"
  "Which crystals have P21 space group?"
"""


def format_result(result: dict) -> str:
    """Format agent result for terminal display."""
    output = []

    # Show tool calls
    if result['tool_calls']:
        output.append("  Tools used:")
        for tc in result['tool_calls']:
            args_str = ', '.join(f'{k}={v}' for k, v in tc['arguments'].items())
            output.append(f"    → {tc['tool']}({args_str})")
        output.append("")

    # Show answer
    if result['answer']:
        # Try to pretty-print JSON answers
        try:
            data = json.loads(result['answer'])
            output.append(format_data(data))
        except (json.JSONDecodeError, TypeError):
            output.append(result['answer'])

    # Show error
    if result['error']:
        output.append(f"  ⚠ Error: {result['error']}")

    return '\n'.join(output)


def format_data(data: dict, indent: int = 2) -> str:
    """Pretty-format tool result data for terminal."""
    lines = []
    prefix = ' ' * indent

    if isinstance(data, dict):
        status = data.get('status', '')

        # Database stats
        if 'total_crystals' in data:
            lines.append(f"{prefix}Database Statistics:")
            lines.append(f"{prefix}  Total crystals: {data['total_crystals']}")
            lines.append(f"{prefix}  Piezoelectric:  {data.get('piezoelectric', 'N/A')}")
            lines.append(f"{prefix}  Ferroelectric:  {data.get('ferroelectric', 'N/A')}")
            lines.append(f"{prefix}  Simulated:      {data.get('crystals_with_simulations', 0)}")
            if 'crystal_systems' in data:
                lines.append(f"{prefix}  Crystal systems:")
                for system, count in data['crystal_systems'].items():
                    lines.append(f"{prefix}    {system}: {count}")

        # Crystal list
        elif 'crystals' in data and isinstance(data['crystals'], list):
            lines.append(f"{prefix}Found {data.get('total', data.get('count', len(data['crystals'])))} crystals:")
            for c in data['crystals']:
                pmc = c.get('pmc_id', '')
                name = c.get('molecule_name', '')
                sg = c.get('space_group', '')
                cs = c.get('crystal_system', '')
                lines.append(f"{prefix}  {pmc:<10} {name:<40} {cs:<15} {sg}")

        # Single crystal details
        elif 'data' in data and isinstance(data['data'], dict):
            d = data['data']
            lines.append(f"{prefix}Crystal: {d.get('molecule_name', d.get('id', ''))}")
            lines.append(f"{prefix}  ID:             {d.get('id', 'N/A')}")
            lines.append(f"{prefix}  Formula:        {d.get('chemical_formula', 'N/A')}")
            lines.append(f"{prefix}  Crystal system: {d.get('crystal_system', 'N/A')}")
            lines.append(f"{prefix}  Space group:    {d.get('space_group_symbol', 'N/A')}")
            if d.get('cell_a'):
                lines.append(f"{prefix}  Cell: a={d['cell_a']}, b={d.get('cell_b')}, c={d.get('cell_c')} Å")
                lines.append(f"{prefix}        β={d.get('cell_beta', 'N/A')}°")
            lines.append(f"{prefix}  Volume:         {d.get('cell_volume', 'N/A')} ų")
            lines.append(f"{prefix}  Piezoelectric:  {d.get('is_piezoelectric', 'N/A')}")

        # Search results
        elif 'results' in data and isinstance(data['results'], list):
            lines.append(f"{prefix}Search results ({data.get('count', len(data['results']))} found):")
            for r in data['results']:
                pmc = r.get('pmc_id', '')
                name = r.get('molecule_name', '')
                lines.append(f"{prefix}  {pmc:<10} {name}")

        # Supercell generation
        elif 'supercell_atoms' in data:
            lines.append(f"{prefix}Supercell generated:")
            lines.append(f"{prefix}  Crystal:      {data.get('pmc_id')}")
            lines.append(f"{prefix}  Size:         {data.get('supercell_size')}")
            lines.append(f"{prefix}  Unit cell:    {data.get('unit_cell_atoms')} atoms")
            lines.append(f"{prefix}  Supercell:    {data.get('supercell_atoms')} atoms")
            lines.append(f"{prefix}  Formula:      {data.get('formula', '')}")
            cp = data.get('cell_parameters', {})
            if cp:
                lines.append(f"{prefix}  Cell: a={cp.get('a')}, b={cp.get('b')}, c={cp.get('c')} Å")

        # Simulation status
        elif 'has_supercell' in data or ('data' in data and 'has_supercell' in data.get('data', {})):
            d = data.get('data', data)
            lines.append(f"{prefix}Simulation status for {d.get('pmc_id', '')}:")
            lines.append(f"{prefix}  Supercell:    {'✅' if d.get('has_supercell') else '❌'}")
            lines.append(f"{prefix}  Simulation:   {'✅' if d.get('has_simulation') else '❌'}")
            lines.append(f"{prefix}  Analysis:     {'✅' if d.get('has_analysis') else '❌'}")
            if d.get('simulation_temperatures'):
                lines.append(f"{prefix}  Temperatures:")
                for t in d['simulation_temperatures']:
                    csv_ok = '✅' if t.get('has_thermo_csv') else '❌'
                    lines.append(f"{prefix}    {t['temperature']}K: CSV {csv_ok}")

        # Fallback: raw JSON
        else:
            lines.append(json.dumps(data, indent=2, default=str))

    else:
        lines.append(str(data))

    return '\n'.join(lines)


def main():
    # Parse args
    use_llm = '--llm' in sys.argv
    llm_url = "http://localhost:8000"

    for i, arg in enumerate(sys.argv):
        if arg == '--llm-url' and i + 1 < len(sys.argv):
            llm_url = sys.argv[i + 1]
            use_llm = True

    agent = PiezoAgent(llm_url=llm_url, verbose=True)
    mode = "LLM (Qwen3-8B)" if use_llm else "Offline"

    print(BANNER)
    print(f"  Mode: {mode}")
    if use_llm:
        print(f"  LLM URL: {llm_url}")
    print(f"  Type /help for commands\n")

    while True:
        try:
            user_input = input("  You > ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\n  Goodbye! 👋")
            break

        if not user_input:
            continue

        # Handle commands
        if user_input.lower() in ['/quit', '/exit', '/q']:
            print("\n  Goodbye! 👋")
            break

        elif user_input.lower() == '/help':
            print(HELP_TEXT)
            continue

        elif user_input.lower() == '/tools':
            print("\n  Available tools:")
            from piezo_tools import TOOL_DEFINITIONS
            for tool in TOOL_DEFINITIONS:
                name = tool['function']['name']
                desc = tool['function']['description'][:60]
                print(f"    {name:<25} {desc}...")
            print()
            continue

        elif user_input.lower().startswith('/status'):
            parts = user_input.split()
            if len(parts) > 1:
                result = agent.run_offline(f"check status {parts[1]}")
            else:
                result = agent.run_offline("database stats")
            print(f"\n{format_result(result)}\n")
            continue

        # Run the query
        print()
        if use_llm:
            result = agent.run(user_input)
        else:
            result = agent.run_offline(user_input)

        print(f"\n{format_result(result)}")
        print()


if __name__ == "__main__":
    main()