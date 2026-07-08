from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import os
from pathlib import Path
from datetime import datetime
import paramiko
import threading

app = Flask(__name__)
CORS(app)

# Paths
DATA_DIR = Path(os.path.expanduser('~/Documents/Piezo-LLM/data'))
MASTER_DB_PATH = Path(os.path.expanduser('~/Documents/Piezo-LLM/gui/public/database/master_database.json'))

def load_json(path):
    """Load JSON file safely"""
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except:
        return None

def save_json(path, data):
    """Save JSON file"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def scan_crystal_directory(pmc_id, pmc_dir):
    """Scan a single PMC directory and return crystal data"""
    json_file = pmc_dir / f"{pmc_id}.json"
    pdf_file = None
    cif_file = None
    txt_file = pmc_dir / f"{pmc_id}.txt"

    for f in pmc_dir.glob('*.pdf'):
        pdf_file = f
        break

    for f in pmc_dir.glob('*.cif'):
        cif_file = f
        break

    status = {
        'json': json_file.exists(),
        'pdf': pdf_file is not None,
        'cif': cif_file is not None,
        'txt': txt_file.exists()
    }

    crystal_data = None
    if json_file.exists():
        crystal_data = load_json(json_file)

    entry = {
        'pmc_id': pmc_id,
        'molecule_name': crystal_data.get('molecule_name') if crystal_data else None,
        'synonyms': crystal_data.get('synonyms', []) if crystal_data else [],
        'chemical_formula': crystal_data.get('chemical_formula') if crystal_data else None,
        'molecular_weight': crystal_data.get('molecular_weight') if crystal_data else None,
        'crystal_type': crystal_data.get('crystal_type') if crystal_data else None,
        'component_count': crystal_data.get('component_count') if crystal_data else None,
        'ccdc_number': crystal_data.get('ccdc_number') if crystal_data else None,
        'csd_refcode': crystal_data.get('csd_refcode') if crystal_data else None,
        'space_group_symbol': crystal_data.get('space_group_symbol') if crystal_data else None,
        'space_group_number': crystal_data.get('space_group_number') if crystal_data else None,
        'crystal_system': crystal_data.get('crystal_system') if crystal_data else None,
        'centrosymmetric': crystal_data.get('centrosymmetric') if crystal_data else None,
        'is_piezoelectric': crystal_data.get('is_piezoelectric') if crystal_data else None,
        'is_ferroelectric': crystal_data.get('is_ferroelectric') if crystal_data else None,
        'is_pyroelectric': crystal_data.get('is_pyroelectric') if crystal_data else None,
        'property_ref_doi': crystal_data.get('property_ref_doi') if crystal_data else None,
        'structure_ref_doi': crystal_data.get('structure_ref_doi') if crystal_data else None,
        'json_schema_version': '1.0',
        'json_path': f'../data/{pmc_id}/{pmc_id}.json',
        'pdf_path': f'../data/{pmc_id}/{pdf_file.name}' if pdf_file else None,
        'cif_path': f'../data/{pmc_id}/{cif_file.name}' if cif_file else None,
        'txt_path': f'../data/{pmc_id}/{pmc_id}.txt',
        'aliases': [pmc_id],
        'search_text': f'{pmc_id} {crystal_data.get("molecule_name", "")} {crystal_data.get("chemical_formula", "")}' if crystal_data else pmc_id,
        'status': status,
        'validated': status['json'] and status['cif'],
        'last_updated': datetime.now().isoformat()
    }

    return entry

@app.route('/api/admin/rebuild-database', methods=['POST'])
def rebuild_database():
    """Rebuild master database by scanning all PMC directories"""
    try:
        master_db = {'crystals': {}}
        processed_count = 0

        for pmc_dir in sorted(DATA_DIR.iterdir()):
            if not pmc_dir.is_dir():
                continue

            pmc_id = pmc_dir.name

            if not pmc_id.startswith('PMC-'):
                continue

            try:
                crystal_entry = scan_crystal_directory(pmc_id, pmc_dir)
                master_db['crystals'][pmc_id] = crystal_entry
                processed_count += 1
            except Exception as e:
                print(f"Error processing {pmc_id}: {e}")
                continue

        master_db['metadata'] = {
            'version': '2.0',
            'total_crystals': len(master_db['crystals']),
            'last_updated': datetime.now().isoformat(),
            'source': 'admin_panel_rebuild'
        }

        save_json(MASTER_DB_PATH, master_db)

        return jsonify({
            'success': True,
            'message': f'Database rebuilt successfully with {processed_count} crystals',
            'processed_count': processed_count,
            'total_crystals': len(master_db['crystals']),
            'timestamp': datetime.now().isoformat()
        }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/admin/rebuild-vectordb', methods=['POST'])
def rebuild_vectordb():
    """Rebuild/update the Chroma vector database from per-molecule JSONs."""
    try:
        from build_rich_vectors import build_rich_vector_db

        result = build_rich_vector_db()

        if not result["success"]:
            return jsonify({
                'success': False,
                'error': result["error"] or "Vector DB build failed"
            }), 400

        return jsonify({
            'success': True,
            'message': 'Vector database updated successfully',
            'total_in_db': result["total_in_db"],
            'processed': result["processed"],
            'new': result["new"],
            'updated': result["updated"],
            'skipped': result["skipped"],
            'skipped_count': len(result["skipped"]),
            'timestamp': datetime.now().isoformat()
        }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/next-pmc-id', methods=['GET'])
def next_pmc_id():
    """Return the next available PMC id (for the upload modal preview)."""
    try:
        from crystal_uploader import get_next_pmc_id
        return jsonify({'next_id': get_next_pmc_id()}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/upload-crystal', methods=['POST'])
def upload_crystal():
    """Create a new crystal entry from an uploaded PDF + CIF (Phase 1)."""
    try:
        if 'pdf' not in request.files or 'cif' not in request.files:
            return jsonify({
                'success': False,
                'error': 'Both a PDF and a CIF file are required.'
            }), 400

        pdf = request.files['pdf']
        cif = request.files['cif']

        if not pdf.filename or not cif.filename:
            return jsonify({
                'success': False,
                'error': 'Both files must be selected.'
            }), 400

        if not pdf.filename.lower().endswith('.pdf'):
            return jsonify({'success': False, 'error': 'PDF file must be a .pdf'}), 400
        if not cif.filename.lower().endswith('.cif'):
            return jsonify({'success': False, 'error': 'CIF file must be a .cif'}), 400

        from crystal_uploader import create_crystal_entry

        result = create_crystal_entry(
            pdf.read(), pdf.filename,
            cif.read(), cif.filename
        )

        result['timestamp'] = datetime.now().isoformat()
        return jsonify(result), 200

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/papers', methods=['GET'])
def get_papers():
    """Return the reference papers behind every crystal."""
    try:
        papers = {}

        for pmc_dir in sorted(DATA_DIR.iterdir()):
            if not pmc_dir.is_dir() or not pmc_dir.name.startswith('PMC-'):
                continue

            pmc_id = pmc_dir.name
            json_file = pmc_dir / f"{pmc_id}.json"
            if not json_file.exists():
                continue

            data = load_json(json_file)
            if not data:
                continue

            molecule = data.get('molecule_name') or pmc_id

            prop_doi = data.get('property_ref_doi')
            if prop_doi or data.get('property_ref_title'):
                key = prop_doi or f"{pmc_id}-property"
                if key not in papers:
                    papers[key] = {
                        'title': data.get('property_ref_title'),
                        'journal': data.get('property_ref_journal'),
                        'year': data.get('property_ref_year'),
                        'authors': data.get('property_ref_authors', []),
                        'doi': prop_doi,
                        'type': 'Property (Piezoelectric)',
                        'molecules': [],
                    }
                papers[key]['molecules'].append({'pmc_id': pmc_id, 'name': molecule})

            struct_doi = data.get('structure_ref_doi')
            if struct_doi or data.get('structure_ref_authors'):
                key = struct_doi or f"{pmc_id}-structure"
                if key not in papers:
                    papers[key] = {
                        'title': None,
                        'journal': data.get('structure_ref_journal'),
                        'year': data.get('structure_ref_year'),
                        'authors': data.get('structure_ref_authors', []),
                        'doi': struct_doi,
                        'type': 'Structure (Crystallography)',
                        'molecules': [],
                    }
                papers[key]['molecules'].append({'pmc_id': pmc_id, 'name': molecule})

        return jsonify({
            'papers': list(papers.values()),
            'total': len(papers),
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/database-status', methods=['GET'])
def get_database_status():
    """Get database statistics"""
    try:
        master_db = load_json(MASTER_DB_PATH)

        if not master_db:
            return jsonify({'error': 'Database not found'}), 404

        crystals = master_db.get('crystals', {})

        total = len(crystals)
        complete = sum(1 for c in crystals.values() if c.get('validated'))
        incomplete = total - complete
        piezoelectric = sum(1 for c in crystals.values() if c.get('is_piezoelectric'))
        ferroelectric = sum(1 for c in crystals.values() if c.get('is_ferroelectric'))

        return jsonify({
            'total_crystals': total,
            'complete_crystals': complete,
            'incomplete_crystals': incomplete,
            'piezoelectric_count': piezoelectric,
            'ferroelectric_count': ferroelectric,
            'last_updated': master_db.get('metadata', {}).get('last_updated')
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/crystals', methods=['GET'])
def get_crystals_list():
    """Get list of all crystals"""
    try:
        master_db = load_json(MASTER_DB_PATH)

        if not master_db:
            return jsonify([]), 404

        crystals = master_db.get('crystals', {})
        result = list(crystals.values())

        return jsonify(result), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/remove-crystal', methods=['DELETE'])
def remove_crystal():
    """Remove a crystal from database"""
    try:
        pmc_id = request.args.get('pmc_id')

        if not pmc_id:
            return jsonify({'error': 'pmc_id required'}), 400

        master_db = load_json(MASTER_DB_PATH)

        if pmc_id in master_db.get('crystals', {}):
            del master_db['crystals'][pmc_id]
            save_json(MASTER_DB_PATH, master_db)
            return jsonify({'success': True, 'message': f'{pmc_id} removed'}), 200
        else:
            return jsonify({'error': 'Crystal not found'}), 404

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/llm-status', methods=['GET'])
def llm_status():
    model_path = os.path.expanduser("~/Documents/Piezo-LLM/gui/Qwen3-8B")
    installed = False
    safetensors = []
    if os.path.isdir(model_path):
        safetensors = [f for f in os.listdir(model_path) if f.endswith('.safetensors')]
        if safetensors:
            first_file = os.path.join(model_path, safetensors[0])
            installed = os.path.getsize(first_file) > 100_000_000
    return {
        'installed': installed,
        'model': 'Qwen3-8B' if installed else None,
        'path': model_path if installed else None,
    }


# ── Vector DB Viewer Routes ──

@app.route('/api/vectordb/browse', methods=['GET'])
def vectordb_browse():
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
        from langchain_chroma import Chroma
        VECTORDB_DIR = os.path.join(os.path.dirname(__file__), '..', 'vectordb')
        embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")
        db = Chroma(collection_name="piezo_crystals", embedding_function=embeddings, persist_directory=str(VECTORDB_DIR))
        results = db._collection.get(include=["metadatas", "documents"])
        documents = []
        for meta, doc in zip(results['metadatas'], results['documents']):
            documents.append({
                'pmc_id': meta.get('pmc_id', ''),
                'molecule_name': meta.get('molecule_name', ''),
                'crystal_system': meta.get('crystal_system', ''),
                'space_group': meta.get('space_group', ''),
                'is_piezoelectric': meta.get('is_piezoelectric', ''),
                'sources_used': meta.get('sources_used', ''),
                'has_txt': meta.get('has_txt', ''),
                'has_pdf': meta.get('has_pdf', ''),
                'has_cif': meta.get('has_cif', ''),
                'char_count': len(doc),
                'preview': doc[:300],
            })
        documents.sort(key=lambda x: x['pmc_id'])
        return jsonify({'status': 'success', 'total': len(documents), 'embedding_model': 'BAAI/bge-small-en-v1.5', 'embedding_dimensions': 384, 'documents': documents})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/vectordb/document/<pmc_id>', methods=['GET'])
def vectordb_document(pmc_id):
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
        from langchain_chroma import Chroma
        VECTORDB_DIR = os.path.join(os.path.dirname(__file__), '..', 'vectordb')
        embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")
        db = Chroma(collection_name="piezo_crystals", embedding_function=embeddings, persist_directory=str(VECTORDB_DIR))
        pmc_id = pmc_id.upper()
        results = db._collection.get(ids=[pmc_id], include=["metadatas", "documents", "embeddings"])
        if not results['documents']:
            return jsonify({'status': 'error', 'message': f'{pmc_id} not found'}), 404
        meta = results['metadatas'][0]
        doc = results['documents'][0]
        emb = results['embeddings'][0]
        return jsonify({'status': 'success', 'pmc_id': pmc_id, 'metadata': meta, 'full_text': doc, 'char_count': len(doc), 'embedding': [round(v, 6) for v in emb], 'embedding_dimensions': len(emb)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/vectordb/search', methods=['POST'])
def vectordb_search():
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
        from langchain_chroma import Chroma
        data = request.get_json()
        query = data.get('query', '').strip()
        top_k = data.get('top_k', 5)
        if not query:
            return jsonify({'status': 'error', 'message': 'No query provided'}), 400
        VECTORDB_DIR = os.path.join(os.path.dirname(__file__), '..', 'vectordb')
        embeddings = HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")
        db = Chroma(collection_name="piezo_crystals", embedding_function=embeddings, persist_directory=str(VECTORDB_DIR))
        results = db.similarity_search_with_score(query, k=min(top_k, 20))
        matches = []
        for doc, score in results:
            matches.append({'pmc_id': doc.metadata.get('pmc_id', ''), 'molecule_name': doc.metadata.get('molecule_name', ''), 'crystal_system': doc.metadata.get('crystal_system', ''), 'similarity': round(1 - score, 3), 'score': round(score, 4), 'preview': doc.page_content[:300]})
        return jsonify({'status': 'success', 'query': query, 'count': len(matches), 'results': matches})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

# ── GPU Simulation Config ──
GPU_CONFIG = {
    'hostname': 'pragya.iitd.ac.in',
    'username': 'cyz218376',
    'password': os.environ.get('PIEZO_GPU_PASSWORD', ''),
    'work_dir': '~/himesh_work',
}
simulation_status = {}

def run_remote_simulation(job_id, pmc_id, temps, steps, size):
    simulation_status[job_id] = {'pmc_id': pmc_id, 'status': 'connecting', 'progress': [], 'error': None, 'result': None}
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(GPU_CONFIG['hostname'], username=GPU_CONFIG['username'], password=GPU_CONFIG['password'], timeout=30)
        simulation_status[job_id]['status'] = 'connected'
        temps_str = ' '.join(str(t) for t in temps)
        cmd = f"cd {GPU_CONFIG['work_dir']} && export TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD=1 && python3 run_all.py {pmc_id} --temps {temps_str} --steps {steps} --size {size}"
        simulation_status[job_id]['status'] = 'running'
        stdin, stdout, stderr = ssh.exec_command(cmd, timeout=7200)
        for line in iter(stdout.readline, ''):
            line = line.strip()
            if line:
                simulation_status[job_id]['progress'].append(line)
        exit_code = stdout.channel.recv_exit_status()
        if exit_code != 0:
            simulation_status[job_id]['status'] = 'failed'
            simulation_status[job_id]['error'] = stderr.read().decode().strip()
            ssh.close()
            return
        simulation_status[job_id]['status'] = 'downloading'
        sftp = ssh.open_sftp()
        stdin_h, stdout_h, _ = ssh.exec_command('echo $HOME')
        home = stdout_h.read().decode().strip()
        remote_dir = f"{home}/himesh_work/simulations/{pmc_id}/md_results"
        local_dir = os.path.join(os.path.dirname(__file__), '..', 'simulations', pmc_id, 'md_results')
        def download_dir(rp, lp):
            os.makedirs(lp, exist_ok=True)
            for item in sftp.listdir_attr(rp):
                ri = f"{rp}/{item.filename}"
                li = os.path.join(lp, item.filename)
                if item.st_mode & 0o40000:
                    download_dir(ri, li)
                else:
                    sftp.get(ri, li)
                    simulation_status[job_id]['progress'].append(f"Downloaded: {item.filename}")
        try:
            download_dir(remote_dir, local_dir)
        except Exception as e:
            simulation_status[job_id]['progress'].append(f"Download note: {str(e)}")
        sftp.close()
        ssh.close()
        simulation_status[job_id]['status'] = 'complete'
        simulation_status[job_id]['result'] = {'pmc_id': pmc_id, 'temperatures': temps}
    except paramiko.AuthenticationException:
        simulation_status[job_id]['status'] = 'failed'
        simulation_status[job_id]['error'] = 'Auth failed. Check PIEZO_GPU_PASSWORD.'
    except Exception as e:
        simulation_status[job_id]['status'] = 'failed'
        simulation_status[job_id]['error'] = str(e)

@app.route('/api/simulate', methods=['POST'])
def start_simulation():
    data = request.get_json()
    pmc_id = data.get('pmc_id', '').upper()
    temps = data.get('temps', [300])
    steps = data.get('steps', 5000)
    size = data.get('size', 2)
    if not pmc_id:
        return jsonify({'error': 'No pmc_id provided'}), 400
    if not GPU_CONFIG['password']:
        return jsonify({'error': 'GPU password not set. Run: export PIEZO_GPU_PASSWORD=yourpassword'}), 500
    import uuid
    job_id = str(uuid.uuid4())[:8]
    thread = threading.Thread(target=run_remote_simulation, args=(job_id, pmc_id, temps, steps, size), daemon=True)
    thread.start()
    return jsonify({'status': 'started', 'job_id': job_id, 'pmc_id': pmc_id, 'temps': temps, 'steps': steps})

@app.route('/api/simulate/status/<job_id>', methods=['GET'])
def simulation_progress(job_id):
    if job_id not in simulation_status:
        return jsonify({'error': 'Job not found'}), 404
    job = simulation_status[job_id]
    return jsonify({'job_id': job_id, 'pmc_id': job['pmc_id'], 'status': job['status'], 'progress': job['progress'][-20:], 'error': job['error'], 'result': job['result']})

@app.route('/api/simulate/jobs', methods=['GET'])
def list_simulation_jobs():
    jobs = [{'job_id': jid, 'pmc_id': j['pmc_id'], 'status': j['status'], 'error': j.get('error')} for jid, j in simulation_status.items()]
    return jsonify({'jobs': jobs})

if __name__ == '__main__':
    app.run(debug=True, port=5000)
