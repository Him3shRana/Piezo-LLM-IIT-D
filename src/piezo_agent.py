"""
piezo_agent.py - Piezo-LLM Agent powered by Qwen3-8B
"""

import json
import re
import sys
import requests
from typing import Optional
from piezo_tools import TOOL_DEFINITIONS, execute_tool

SYSTEM_PROMPT = """You are Piezo-Agent, an AI research assistant for piezoelectric molecular crystal simulations.
You have access to tools that let you search a database of 43+ piezoelectric molecular crystals, generate supercells, run MACE-OFF23 simulations, and analyse results.
Always use tools to get data. Never make up crystal properties. Report PMC IDs. Be concise but include key numerical values with units."""

MAX_TOOL_CALLS = 10

class PiezoAgent:
    def __init__(self, llm_url="http://localhost:8000", model="Qwen/Qwen3-8B", temperature=0.2, verbose=False):
        self.llm_url = llm_url
        self.model = model
        self.temperature = temperature
        self.verbose = verbose

    def _call_llm(self, messages, tools=None):
        payload = {"model": self.model, "messages": messages, "temperature": self.temperature, "max_tokens": 2048}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            resp = requests.post(f"{self.llm_url}/v1/chat/completions", json=payload, timeout=120)
            if resp.status_code != 200:
                return {"error": f"LLM server error {resp.status_code}: {resp.text}"}
            return resp.json()
        except requests.exceptions.ConnectionError:
            return {"error": f"Cannot connect to LLM at {self.llm_url}. Is vLLM running?"}
        except requests.exceptions.Timeout:
            return {"error": "LLM request timed out."}

    def _extract_tool_calls(self, response):
        try:
            tc = response.get("choices", [{}])[0].get("message", {}).get("tool_calls", [])
            if tc:
                return tc
        except (IndexError, KeyError):
            pass
        try:
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            if "<tool_call>" in content:
                import re, json, uuid
                matches = re.findall(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', content, re.DOTALL)
                tool_calls = []
                for match in matches:
                    try:
                        data = json.loads(match)
                        tool_calls.append({"id": str(uuid.uuid4())[:8], "function": {"name": data.get("name", ""), "arguments": json.dumps(data.get("arguments", {}))}})
                    except json.JSONDecodeError:
                        pass
                return tool_calls
        except (IndexError, KeyError):
            pass
        return []

    def _extract_text(self, response):
        try:
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
            return re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
        except (IndexError, KeyError):
            return ""

    def run(self, user_input):
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_input}]
        tool_calls_log, tool_results_log = [], []
        iterations = 0

        while iterations < MAX_TOOL_CALLS:
            iterations += 1
            if self.verbose:
                print(f"  [Agent] Iteration {iterations}, calling LLM...")
            response = self._call_llm(messages, tools=TOOL_DEFINITIONS)
            if "error" in response:
                return {'answer': None, 'tool_calls': tool_calls_log, 'tool_results': tool_results_log, 'error': response["error"]}

            tool_calls = self._extract_tool_calls(response)
            if not tool_calls:
                return {'answer': self._extract_text(response), 'tool_calls': tool_calls_log, 'tool_results': tool_results_log, 'error': None}

            assistant_msg = response["choices"][0]["message"]
            messages.append(assistant_msg)

            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                try:
                    tool_args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, TypeError):
                    tool_args = {}
                if self.verbose:
                    print(f"  [Agent] Calling tool: {tool_name}({tool_args})")
                result = execute_tool(tool_name, tool_args)
                tool_calls_log.append({'tool': tool_name, 'arguments': tool_args})
                tool_results_log.append({'tool': tool_name, 'result': result})
                if self.verbose:
                    print(f"  [Agent] Tool result: {result.get('status', 'unknown')}")
                messages.append({"role": "user", "content": f"Tool {tool_name} returned: {json.dumps(result, default=str)}"})

        return {'answer': "Reached max steps.", 'tool_calls': tool_calls_log, 'tool_results': tool_results_log, 'error': 'max_iterations'}

    def run_offline(self, user_input):
        q = user_input.lower().strip()
        tool_calls_log, tool_results_log = [], []

        if any(w in q for w in ['how many', 'total', 'count', 'stats', 'statistics']):
            result = execute_tool('database_stats', {})
            tool_calls_log.append({'tool': 'database_stats', 'arguments': {}})
            tool_results_log.append({'tool': 'database_stats', 'result': result})

        elif any(w in q for w in ['list all', 'show all', 'all crystals']):
            f = None
            if 'piezoelectric' in q: f = 'piezoelectric'
            elif 'monoclinic' in q: f = 'monoclinic'
            elif 'orthorhombic' in q: f = 'orthorhombic'
            result = execute_tool('list_crystals', {'filter_by': f})
            tool_calls_log.append({'tool': 'list_crystals', 'arguments': {'filter_by': f}})
            tool_results_log.append({'tool': 'list_crystals', 'result': result})

        elif 'compare' in q and len(re.findall(r'PMC-\d+', q, re.IGNORECASE)) >= 2:
            pmc_ids = re.findall(r'(PMC-\d+)', q, re.IGNORECASE)
            result = execute_tool('compare_crystals', {'pmc_ids': pmc_ids})
            tool_calls_log.append({'tool': 'compare_crystals', 'arguments': {'pmc_ids': pmc_ids}})
            tool_results_log.append({'tool': 'compare_crystals', 'result': result})

        elif re.search(r'PMC-\d+', q, re.IGNORECASE):
            pmc_id = re.search(r'(PMC-\d+)', q, re.IGNORECASE).group(1).upper()

            if any(w in q for w in ['simulate', 'run', 'md', 'mace']):
                temp_match = re.search(r'(\d+)\s*k', q, re.IGNORECASE)
                temp = int(temp_match.group(1)) if temp_match else 300
                size_match = re.search(r'(\d)x\d', q)
                size = int(size_match.group(1)) if size_match else 2

                status = execute_tool('get_simulation_status', {'pmc_id': pmc_id})
                tool_calls_log.append({'tool': 'get_simulation_status', 'arguments': {'pmc_id': pmc_id}})

                if not status.get('data', {}).get('has_supercell'):
                    sc = execute_tool('generate_supercell', {'pmc_id': pmc_id, 'size': size})
                    tool_calls_log.append({'tool': 'generate_supercell', 'arguments': {'pmc_id': pmc_id, 'size': size}})
                    tool_results_log.append({'tool': 'generate_supercell', 'result': sc})

                sim = execute_tool('run_simulation', {'pmc_id': pmc_id, 'temperatures': [temp], 'supercell_size': f'{size}x{size}x{size}'})
                tool_calls_log.append({'tool': 'run_simulation', 'arguments': {'pmc_id': pmc_id, 'temperatures': [temp]}})
                tool_results_log.append({'tool': 'run_simulation', 'result': sim})

                if sim.get('status') == 'success':
                    ana = execute_tool('analyse_results', {'pmc_id': pmc_id, 'temperatures': [temp]})
                    tool_calls_log.append({'tool': 'analyse_results', 'arguments': {'pmc_id': pmc_id}})
                    tool_results_log.append({'tool': 'analyse_results', 'result': ana})

            elif any(w in q for w in ['supercell', 'generate', 'replicate']):
                size_match = re.search(r'(\d)x\d', q)
                size = int(size_match.group(1)) if size_match else 2
                result = execute_tool('generate_supercell', {'pmc_id': pmc_id, 'size': size})
                tool_calls_log.append({'tool': 'generate_supercell', 'arguments': {'pmc_id': pmc_id, 'size': size}})
                tool_results_log.append({'tool': 'generate_supercell', 'result': result})

            elif any(w in q for w in ['status', 'check', 'results']):
                result = execute_tool('get_simulation_status', {'pmc_id': pmc_id})
                tool_calls_log.append({'tool': 'get_simulation_status', 'arguments': {'pmc_id': pmc_id}})
                tool_results_log.append({'tool': 'get_simulation_status', 'result': result})

            elif any(w in q for w in ['analyse', 'analyze', 'graph', 'plot']):
                result = execute_tool('analyse_results', {'pmc_id': pmc_id})
                tool_calls_log.append({'tool': 'analyse_results', 'arguments': {'pmc_id': pmc_id}})
                tool_results_log.append({'tool': 'analyse_results', 'result': result})

            else:
                result = execute_tool('get_crystal_details', {'pmc_id': pmc_id})
                tool_calls_log.append({'tool': 'get_crystal_details', 'arguments': {'pmc_id': pmc_id}})
                tool_results_log.append({'tool': 'get_crystal_details', 'result': result})



        else:
            result = execute_tool('search_crystals', {'query': user_input})
            tool_calls_log.append({'tool': 'search_crystals', 'arguments': {'query': user_input}})
            tool_results_log.append({'tool': 'search_crystals', 'result': result})

        answer_parts = []
        for tr in tool_results_log:
            answer_parts.append(json.dumps(tr['result'], indent=2, default=str))

        return {'answer': '\n\n'.join(answer_parts), 'tool_calls': tool_calls_log, 'tool_results': tool_results_log, 'error': None}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python piezo_agent.py \"your question\"")
        print("  python piezo_agent.py \"How many crystals?\"")
        print("  python piezo_agent.py \"Tell me about PMC-010\"")
        print("  python piezo_agent.py --llm \"Simulate PMC-010 at 300K\"")
        sys.exit(0)

    use_llm = '--llm' in sys.argv
    query = ' '.join(arg for arg in sys.argv[1:] if arg != '--llm')
    agent = PiezoAgent(verbose=True)

    print(f"\n{'=' * 60}")
    print(f"  Piezo Agent | Mode: {'LLM' if use_llm else 'Offline'}")
    print(f"  Query: {query}")
    print(f"{'=' * 60}")

    result = agent.run(query) if use_llm else agent.run_offline(query)

    if result['tool_calls']:
        print(f"\n  Tools called:")
        for tc in result['tool_calls']:
            print(f"    -> {tc['tool']}({tc['arguments']})")

    if result['error']:
        print(f"\n  Error: {result['error']}")

    print(f"\n  Answer:\n{result['answer']}")
