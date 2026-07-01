"""
Master Database Builder for Piezo-LLM
Supports incremental updates without rebuilding entire database
Automatically syncs JSON, PDF, CIF, and TXT files for each crystal
"""

import os
import json
from datetime import datetime
from pathlib import Path


class MasterDatabaseBuilder:
    """
    Builds and maintains the Master Database for Piezo-LLM.
    
    Key features:
    - Incremental updates (add/update individual crystals)
    - Auto-detects new files (JSON, PDF, CIF, TXT)
    - Preserves existing data when files don't change
    - Admin panel for manual updates
    """

    def __init__(self, 
                 data_folder="../data",
                 output_path="../gui/public/database/master_database.json"):
        
        self.data_folder = Path(data_folder)
        self.output_path = Path(output_path)
        self.validation_report_path = Path(output_path).parent / "validation_report.json"
        
        # Create output directory if it doesn't exist
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing database if it exists
        self.database = self._load_existing_database()
        self.validation_report = {}
        self.changes = {"new": 0, "updated": 0, "unchanged": 0}

    # ========================================================
    
    def _load_existing_database(self):
        """
        Load the existing master database to preserve old data.
        This way we only update what changed.
        """
        if self.output_path.exists():
            try:
                with open(self.output_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    print(f"✅ Loaded existing database with {len(data.get('crystals', {}))} entries\n")
                    return data.get("crystals", {})
            except Exception as e:
                print(f"⚠️  Could not load existing database: {e}")
                print("Starting fresh...\n")
                return {}
        return {}

    # ========================================================
    
    def build(self, pmc_id=None):
        """
        Build master database - either full scan or update specific crystal.
        
        Args:
            pmc_id: If provided, only update this crystal (e.g., 'PMC-001')
                   If None, scan all PMC folders
        """
        print("=" * 80)
        if pmc_id:
            print(f"UPDATING CRYSTAL: {pmc_id}")
        else:
            print("SCANNING ALL CRYSTALS FOR UPDATES")
        print("=" * 80)
        print()

        if pmc_id:
            # Update single crystal
            folder_path = self.data_folder / pmc_id
            if folder_path.exists():
                self.process_folder(folder_path)
            else:
                print(f"❌ Folder not found: {folder_path}\n")
                return
        else:
            # Scan all PMC folders
            try:
                folders = sorted([f for f in os.listdir(self.data_folder) 
                                if f.startswith("PMC-")])
            except FileNotFoundError:
                print(f"❌ Data folder not found: {self.data_folder}")
                return

            for folder_name in folders:
                folder_path = self.data_folder / folder_name
                if folder_path.is_dir():
                    self.process_folder(folder_path)

    # ========================================================
    
    def build_aliases(self, entry):
        """
        Create searchable aliases from crystal metadata.
        Helps users find crystals by name, formula, or identifiers.
        """
        aliases = set()

        def add(value):
            if value is None:
                return
            if isinstance(value, list):
                for item in value:
                    if item:
                        aliases.add(str(item).strip())
            else:
                aliases.add(str(value).strip())

        add(entry.get("pmc_id"))
        add(entry.get("molecule_name"))
        add(entry.get("synonyms"))
        add(entry.get("ccdc_number"))
        add(entry.get("csd_refcode"))

        return sorted(aliases)

    # ========================================================
    
    def build_search_text(self, entry):
        """
        Build comprehensive search text for semantic search & RAG.
        Combines all searchable fields into one text blob.
        """
        words = []

        fields = [
            "pmc_id",
            "molecule_name",
            "chemical_formula",
            "crystal_type",
            "space_group_symbol",
            "crystal_system",
            "property_ref_doi",
            "structure_ref_doi"
        ]

        for field in fields:
            value = entry.get(field)
            if value:
                words.append(str(value))

        # Add aliases
        words.extend(entry.get("aliases", []))

        # Add property tags
        if entry.get("is_piezoelectric"):
            words.append("piezoelectric")
        if entry.get("is_ferroelectric"):
            words.append("ferroelectric")
        if entry.get("is_pyroelectric"):
            words.append("pyroelectric")

        return " ".join(words)

    # ========================================================
    
    def process_folder(self, folder_path):
        """
        Process a single PMC folder and update its entry.
        Detects what files are available without requiring all three.
        """
        pmc_id = folder_path.name
        folder_path = Path(folder_path)
        
        print(f"📁 Checking {pmc_id} ...")

        # Find available files
        json_path = None
        pdf_path = None
        cif_path = None
        txt_path = None

        for file in folder_path.iterdir():
            if file.is_file():
                lower_name = file.name.lower()

                if lower_name.endswith(".json"):
                    json_path = str(file)
                elif lower_name.endswith(".pdf"):
                    pdf_path = str(file)
                elif lower_name.endswith(".cif"):
                    cif_path = str(file)
                elif lower_name.endswith(".txt"):
                    txt_path = str(file)

        # Check if JSON exists (required for entry)
        if json_path is None:
            self.validation_report[pmc_id] = {
                "status": "⚠️  WARNING",
                "reason": "JSON file missing - cannot update"
            }
            print(f"   ⚠️  Skipping: No JSON file found\n")
            return

        # Load JSON data
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                json_data = json.load(f)
        except Exception as e:
            self.validation_report[pmc_id] = {
                "status": "❌ ERROR",
                "reason": f"JSON read error: {str(e)}"
            }
            print(f"   ❌ Error reading JSON: {e}\n")
            return

        # Build entry with all available data
        entry = {
            "pmc_id": pmc_id,
            "molecule_name": json_data.get("molecule_name"),
            "synonyms": json_data.get("synonyms", []),
            "chemical_formula": json_data.get("chemical_formula"),
            "molecular_weight": json_data.get("molecular_weight"),
            "crystal_type": json_data.get("crystal_type"),
            "component_count": json_data.get("component_count"),
            "ccdc_number": json_data.get("ccdc_number"),
            "csd_refcode": json_data.get("csd_refcode"),
            "space_group_symbol": json_data.get("space_group_symbol"),
            "space_group_number": json_data.get("space_group_number"),
            "crystal_system": json_data.get("crystal_system"),
            "centrosymmetric": json_data.get("centrosymmetric"),
            "is_piezoelectric": json_data.get("is_piezoelectric"),
            "is_ferroelectric": json_data.get("is_ferroelectric"),
            "is_pyroelectric": json_data.get("is_pyroelectric"),
            "property_ref_doi": json_data.get("property_ref_doi"),
            "structure_ref_doi": json_data.get("structure_ref_doi"),
            "json_schema_version": json_data.get("json_schema_version", "1.0"),
            "json_path": json_path,
            "pdf_path": pdf_path,
            "cif_path": cif_path,
            "txt_path": txt_path
        }

        # Add computed fields
        entry["aliases"] = self.build_aliases(entry)
        entry["search_text"] = self.build_search_text(entry)
        entry["status"] = {
            "json": json_path is not None,
            "pdf": pdf_path is not None,
            "cif": cif_path is not None,
            "txt": txt_path is not None
        }
        entry["validated"] = all([json_path, pdf_path, cif_path])
        entry["last_updated"] = datetime.now().isoformat(timespec="seconds")

        # Detect if this is new or updated
        if pmc_id not in self.database:
            print(f"   ✨ NEW ENTRY")
            self.changes["new"] += 1
            status = "NEW"
        else:
            # Check if anything changed
            old_entry = self.database[pmc_id]
            files_changed = (
                old_entry.get("pdf_path") != pdf_path or
                old_entry.get("cif_path") != cif_path or
                old_entry.get("txt_path") != txt_path
            )
            if files_changed:
                print(f"   🔄 UPDATED (files changed)")
                self.changes["updated"] += 1
                status = "UPDATED"
            else:
                print(f"   ✓ Unchanged")
                self.changes["unchanged"] += 1
                status = "OK"

        # Store in database
        self.database[pmc_id] = entry

        self.validation_report[pmc_id] = {
            "status": status,
            "files": entry["status"]
        }

        print()

    # ========================================================
    
    def save(self):
        """
        Save updated master database to the public folder.
        """
        print("💾 Saving database...")

        master_database = {
            "metadata": {
                "database_name": "Piezo-LLM Master Database",
                "database_version": "2.0",
                "generated_on": datetime.now().isoformat(timespec="seconds"),
                "total_crystals": len(self.database),
                "last_update": datetime.now().isoformat(timespec="seconds")
            },
            "crystals": self.database
        }

        # Write master database
        try:
            with open(self.output_path, "w", encoding="utf-8") as f:
                json.dump(master_database, f, indent=4, ensure_ascii=False)
            print(f"✅ Master database saved to: {self.output_path}\n")
        except Exception as e:
            print(f"❌ Error saving master database: {e}\n")
            return

        # Write validation report
        validation = {
            "metadata": {
                "generated_on": datetime.now().isoformat(timespec="seconds"),
                "total_crystals": len(self.database),
                "new": self.changes["new"],
                "updated": self.changes["updated"],
                "unchanged": self.changes["unchanged"]
            },
            "crystals": self.validation_report
        }

        try:
            with open(self.validation_report_path, "w", encoding="utf-8") as f:
                json.dump(validation, f, indent=4, ensure_ascii=False)
            print(f"✅ Validation report saved\n")
        except Exception as e:
            print(f"⚠️  Could not save validation report: {e}\n")

    # ========================================================
    
    def summary(self):
        """
        Print summary of database build/update.
        """
        print("=" * 80)
        print("📊 UPDATE SUMMARY")
        print("=" * 80)
        print(f"New entries       : {self.changes['new']}")
        print(f"Updated entries   : {self.changes['updated']}")
        print(f"Unchanged entries : {self.changes['unchanged']}")
        print(f"Total crystals    : {len(self.database)}")
        print()
        print("📁 Output Files:")
        print(f"   Master Database: {self.output_path}")
        print(f"   Validation Report: {self.validation_report_path}")
        print()
        print("=" * 80)

    # ========================================================
    
    def remove_crystal(self, pmc_id):
        """
        Remove a crystal from the database (if deleted from disk).
        """
        if pmc_id in self.database:
            del self.database[pmc_id]
            print(f"🗑️  Removed {pmc_id} from database")
            self.save()
        else:
            print(f"❌ Crystal {pmc_id} not found in database")


# ==========================================================
# COMMAND LINE INTERFACE
# ==========================================================

def print_menu():
    print("\n" + "=" * 80)
    print("PIEZO-LLM MASTER DATABASE ADMIN")
    print("=" * 80)
    print("1. Full scan (update all crystals)")
    print("2. Update specific crystal (enter PMC-ID)")
    print("3. Remove crystal from database")
    print("4. Exit")
    print("=" * 80)


# ==========================================================
# MAIN
# ==========================================================

if __name__ == "__main__":
    
    print("\n🚀 Piezo-LLM Master Database Builder\n")
    
    # Adjust these paths based on your setup
    data_folder = "../data"
    output_path = "../gui/public/database/master_database.json"
    
    builder = MasterDatabaseBuilder(data_folder, output_path)

    while True:
        print_menu()
        choice = input("\nSelect option (1-4): ").strip()

        if choice == "1":
            print()
            builder.build()
            builder.save()
            builder.summary()

        elif choice == "2":
            pmc_id = input("Enter PMC ID (e.g., PMC-001): ").strip()
            print()
            builder.build(pmc_id)
            builder.save()
            builder.summary()

        elif choice == "3":
            pmc_id = input("Enter PMC ID to remove: ").strip()
            print()
            builder.remove_crystal(pmc_id)
            builder.save()

        elif choice == "4":
            print("\n👋 Goodbye!\n")
            break

        else:
            print("❌ Invalid option. Try again.\n")