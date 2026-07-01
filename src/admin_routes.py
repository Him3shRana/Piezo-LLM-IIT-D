"""
Flask Backend Setup for Piezo-LLM Database Admin
Integrate this into your existing Flask application
"""

from flask import Flask, Blueprint, request, jsonify, send_file
import subprocess
import json
import os
from pathlib import Path
from datetime import datetime
import sys

# ========================================================
# Configuration (Update these paths for your setup)
# ========================================================

DATABASE_BUILDER_SCRIPT = os.path.join(
    os.path.dirname(__file__),
    "../src/build_master_database_v2.py"
)

OUTPUT_DATABASE = os.path.join(
    os.path.dirname(__file__),
    "../gui/public/database/master_database.json"
)

DATA_FOLDER = os.path.join(
    os.path.dirname(__file__),
    "../data"
)

# ========================================================
# Create Blueprint for Admin Routes
# ========================================================

admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')

# ========================================================
# Helper Functions
# ========================================================

def run_database_builder(pmc_id=None, full_scan=True):
    """
    Run the Python database builder script
    
    Args:
        pmc_id: If provided, update only this crystal
        full_scan: If True, scan all crystals
    
    Returns:
        dict with success status and statistics
    """
    try:
        # Change to src directory to run script
        src_dir = os.path.dirname(DATABASE_BUILDER_SCRIPT)
        
        # Build command arguments
        cmd = [sys.executable, DATABASE_BUILDER_SCRIPT]
        
        # For now, the script is interactive
        # We'll need to modify it to accept command-line arguments
        # For the initial implementation, we'll just run a full scan
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
            cwd=src_dir
        )

        if result.returncode != 0:
            return {
                "success": False,
                "error": result.stderr or "Database builder failed"
            }

        # Parse output to extract statistics
        output = result.stdout
        
        # Count occurrences in output
        new_count = output.count("✨ NEW ENTRY")
        updated_count = output.count("🔄 UPDATED")
        unchanged_count = output.count("✓ Unchanged")

        return {
            "success": True,
            "stats": {
                "new": new_count,
                "updated": updated_count,
                "unchanged": unchanged_count
            },
            "output": output[-500:] if len(output) > 500 else output  # Last 500 chars
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": "Database scan took too long (>5 minutes)"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Error running database builder: {str(e)}"
        }


def load_master_database():
    """Load and return the master database"""
    try:
        if not os.path.exists(OUTPUT_DATABASE):
            return None
        
        with open(OUTPUT_DATABASE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading database: {e}")
        return None


def save_master_database(db):
    """Save the master database"""
    try:
        os.makedirs(os.path.dirname(OUTPUT_DATABASE), exist_ok=True)
        with open(OUTPUT_DATABASE, 'w', encoding='utf-8') as f:
            json.dump(db, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error saving database: {e}")
        return False


# ========================================================
# API Endpoints
# ========================================================

@admin_bp.route('/rebuild-database', methods=['POST'])
def rebuild_database():
    """
    Rebuild master database (full scan or single crystal update)
    
    Request body:
    {
        "full_scan": true,  # or provide pmc_id for single update
        "pmc_id": "PMC-001"  # optional
    }
    """
    try:
        data = request.get_json() or {}
        full_scan = data.get('full_scan', True)
        pmc_id = data.get('pmc_id')

        # Run the database builder
        result = run_database_builder(pmc_id=pmc_id, full_scan=full_scan)

        if not result['success']:
            return jsonify({
                "status": "error",
                "message": result['error']
            }), 400

        # Load and return updated database info
        db = load_master_database()
        if not db:
            return jsonify({
                "status": "error",
                "message": "Failed to load updated database"
            }), 500

        crystals = db.get('crystals', {})
        stats = result['stats']

        return jsonify({
            "status": "success",
            "message": "Database updated successfully",
            "new": stats['new'],
            "updated": stats['updated'],
            "unchanged": stats['unchanged'],
            "total": len(crystals),
            "timestamp": datetime.now().isoformat()
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@admin_bp.route('/database-status', methods=['GET'])
def database_status():
    """
    Get current database status
    """
    try:
        db = load_master_database()
        
        if not db:
            return jsonify({
                "status": "empty",
                "total": 0,
                "complete": 0,
                "incomplete": 0
            })

        crystals = db.get('crystals', {})
        complete = sum(1 for c in crystals.values() if c.get('validated'))
        incomplete = len(crystals) - complete

        return jsonify({
            "status": "success",
            "total": len(crystals),
            "complete": complete,
            "incomplete": incomplete,
            "last_updated": db.get('metadata', {}).get('generated_on'),
            "database_version": db.get('metadata', {}).get('database_version')
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@admin_bp.route('/remove-crystal', methods=['DELETE'])
def remove_crystal():
    """
    Remove a crystal from the database
    
    Request body:
    {
        "pmc_id": "PMC-001"
    }
    """
    try:
        data = request.get_json()
        pmc_id = data.get('pmc_id')

        if not pmc_id:
            return jsonify({
                "status": "error",
                "message": "PMC ID is required"
            }), 400

        db = load_master_database()
        if not db:
            return jsonify({
                "status": "error",
                "message": "Database not found"
            }), 404

        crystals = db.get('crystals', {})

        if pmc_id not in crystals:
            return jsonify({
                "status": "error",
                "message": f"Crystal {pmc_id} not found in database"
            }), 404

        # Remove crystal
        del crystals[pmc_id]
        
        # Update metadata
        db['metadata']['total_crystals'] = len(crystals)
        db['metadata']['last_update'] = datetime.now().isoformat(timespec='seconds')

        # Save updated database
        if not save_master_database(db):
            return jsonify({
                "status": "error",
                "message": "Failed to save database"
            }), 500

        return jsonify({
            "status": "success",
            "message": f"Removed {pmc_id} from database",
            "total": len(crystals)
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@admin_bp.route('/crystals', methods=['GET'])
def get_crystals():
    """
    Get all crystals from database (with optional filtering)
    
    Query parameters:
    - filter: 'all', 'complete', 'incomplete'
    - search: search term
    """
    try:
        db = load_master_database()
        
        if not db:
            return jsonify({
                "crystals": [],
                "total": 0
            })

        crystals = list(db.get('crystals', {}).values())
        
        # Apply filters if requested
        filter_type = request.args.get('filter', 'all')
        search_term = request.args.get('search', '').lower()

        if filter_type == 'complete':
            crystals = [c for c in crystals if c.get('validated')]
        elif filter_type == 'incomplete':
            crystals = [c for c in crystals if not c.get('validated')]

        if search_term:
            crystals = [c for c in crystals if (
                search_term in c.get('pmc_id', '').lower() or
                search_term in c.get('molecule_name', '').lower() or
                search_term in c.get('chemical_formula', '').lower()
            )]

        # Sort by PMC ID
        crystals.sort(key=lambda c: c.get('pmc_id', ''))

        return jsonify({
            "crystals": crystals,
            "total": len(crystals)
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@admin_bp.route('/export-database', methods=['GET'])
def export_database():
    """
    Export master database as JSON file
    """
    try:
        if not os.path.exists(OUTPUT_DATABASE):
            return jsonify({
                "status": "error",
                "message": "Database file not found"
            }), 404

        return send_file(
            OUTPUT_DATABASE,
            mimetype='application/json',
            as_attachment=True,
            download_name=f"master_database_{datetime.now().strftime('%Y-%m-%d')}.json"
        )

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@admin_bp.route('/validation-report', methods=['GET'])
def validation_report():
    """
    Get validation report for all crystals
    """
    try:
        validation_path = os.path.join(
            os.path.dirname(OUTPUT_DATABASE),
            "validation_report.json"
        )
        
        if not os.path.exists(validation_path):
            return jsonify({
                "status": "error",
                "message": "Validation report not found"
            }), 404

        with open(validation_path, 'r', encoding='utf-8') as f:
            report = json.load(f)

        return jsonify(report)

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# ========================================================
# Integration with Flask App
# ========================================================

def register_admin_routes(app: Flask):
    """
    Register admin routes with your Flask app
    
    Usage in your main app.py:
    ----
    from admin_routes import register_admin_routes
    
    app = Flask(__name__)
    register_admin_routes(app)
    ----
    """
    app.register_blueprint(admin_bp)
    print("✅ Admin routes registered at /api/admin/*")


# ========================================================
# If running this file directly for testing
# ========================================================

if __name__ == "__main__":
    from flask import Flask
    
    app = Flask(__name__)
    register_admin_routes(app)
    
    # Test the endpoints
    print("Starting test server on http://localhost:5000")
    print("Test endpoints:")
    print("  GET  http://localhost:5000/api/admin/database-status")
    print("  GET  http://localhost:5000/api/admin/crystals")
    print("  POST http://localhost:5000/api/admin/rebuild-database")
    
    app.run(debug=True, port=5000)