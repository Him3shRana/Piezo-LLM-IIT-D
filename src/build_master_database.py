import os
import json
from datetime import datetime

print("build_master_database.py started")


class MasterDatabaseBuilder:
    """
    Builds the Master Database for Piezo-LLM.

    It scans every PMC folder and creates

    1. master_database.json
    2. validation_report.json

    The master database acts as the first level
    of retrieval before JSON/PDF/CIF search.
    """

    def __init__(self, data_folder="../data"):

        self.data_folder = data_folder

        self.database = {}

        self.validation_report = {}

        self.success = 0

        self.warning = 0

    # ======================================================

    def build(self):

        print("=" * 80)
        print("BUILDING MASTER DATABASE")
        print("=" * 80)
        print()

        folders = sorted(os.listdir(self.data_folder))

        for folder in folders:

            if not folder.startswith("PMC-"):
                continue

            folder_path = os.path.join(self.data_folder, folder)

            if not os.path.isdir(folder_path):
                continue

            self.process_folder(folder_path)

    # ======================================================

    def build_aliases(self, entry):

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

        add(entry["pmc_id"])

        add(entry["molecule_name"])

        add(entry["synonyms"])

        add(entry["ccdc_number"])

        add(entry["csd_refcode"])

        return sorted(aliases)

    # ======================================================

    def build_search_text(self, entry):

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

        words.extend(entry["aliases"])

        if entry.get("is_piezoelectric"):

            words.append("piezoelectric")

        if entry.get("is_ferroelectric"):

            words.append("ferroelectric")

        if entry.get("is_pyroelectric"):

            words.append("pyroelectric")

        return " ".join(words)

    # ======================================================

    def process_folder(self, folder_path):

        pmc_id = os.path.basename(folder_path)

        print(f"Scanning {pmc_id} ...")

        json_path = None
        pdf_path = None
        cif_path = None

        for file in os.listdir(folder_path):

            lower = file.lower()

            if lower.endswith(".json"):

                json_path = os.path.join(folder_path, file)

            elif lower.endswith(".pdf"):

                pdf_path = os.path.join(folder_path, file)

            elif lower.endswith(".cif"):

                cif_path = os.path.join(folder_path, file)

        missing = []

        if json_path is None:

            missing.append("JSON")

        if pdf_path is None:

            missing.append("PDF")

        if cif_path is None:

            missing.append("CIF")

        # ------------------------

        if json_path is None:

            self.warning += 1

            self.validation_report[pmc_id] = {

                "status": "WARNING",

                "missing": missing

            }

            print("   WARNING ->", ", ".join(missing))
            print()

            return

        # ------------------------

        try:

            with open(json_path, "r", encoding="utf-8") as f:

                data = json.load(f)

        except Exception as e:

            self.warning += 1

            self.validation_report[pmc_id] = {

                "status": "ERROR",

                "reason": str(e)

            }

            print("   ERROR reading JSON")
            print()

            return

        # =====================================================
        # Build Rich Entry
        # =====================================================

        entry = {

            "pmc_id": pmc_id,

            "molecule_name": data.get("molecule_name"),

            "synonyms": data.get("synonyms", []),

            "chemical_formula": data.get("chemical_formula"),

            "molecular_weight": data.get("molecular_weight"),

            "crystal_type": data.get("crystal_type"),

            "component_count": data.get("component_count"),

            "ccdc_number": data.get("ccdc_number"),

            "csd_refcode": data.get("csd_refcode"),

            "space_group_symbol": data.get("space_group_symbol"),

            "space_group_number": data.get("space_group_number"),

            "crystal_system": data.get("crystal_system"),

            "centrosymmetric": data.get("centrosymmetric"),

            "is_piezoelectric": data.get("is_piezoelectric"),

            "is_ferroelectric": data.get("is_ferroelectric"),

            "is_pyroelectric": data.get("is_pyroelectric"),

            "property_ref_doi": data.get("property_ref_doi"),

            "structure_ref_doi": data.get("structure_ref_doi"),

            "json_schema_version": data.get("schema_version"),

            "json_path": json_path,

            "pdf_path": pdf_path,

            "cif_path": cif_path

        }

        entry["aliases"] = self.build_aliases(entry)

        entry["search_text"] = self.build_search_text(entry)

        entry["status"] = {

            "json": json_path is not None,

            "pdf": pdf_path is not None,

            "cif": cif_path is not None

        }

        entry["validated"] = len(missing) == 0

        self.database[pmc_id] = entry

        if len(missing) == 0:

            self.validation_report[pmc_id] = {

                "status": "OK"

            }

            self.success += 1

            print("   OK")

        else:

            self.validation_report[pmc_id] = {

                "status": "WARNING",

                "missing": missing

            }

            self.warning += 1

            print("   WARNING ->", ", ".join(missing))

        print()

    # ======================================================

    def save(self):

        os.makedirs("../database", exist_ok=True)

        # -----------------------------------------
        # Master Database Metadata
        # -----------------------------------------

        master_database = {

            "metadata": {

                "database_name": "Piezo-LLM Master Database",

                "database_version": "2.0",

                "generated_on": datetime.now().isoformat(timespec="seconds"),

                "total_crystals": len(self.database),

                "successful_folders": self.success,

                "folders_with_warnings": self.warning

            },

            "crystals": self.database

        }

        # -----------------------------------------

        with open(
            "../database/master_database.json",
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                master_database,
                f,
                indent=4,
                ensure_ascii=False
            )

        # -----------------------------------------

        validation = {

            "metadata": {

                "generated_on": datetime.now().isoformat(timespec="seconds"),

                "total_folders": self.success + self.warning,

                "successful": self.success,

                "warnings": self.warning

            },

            "folders": self.validation_report

        }

        with open(
            "../database/validation_report.json",
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                validation,
                f,
                indent=4,
                ensure_ascii=False
            )

    # ======================================================

    def summary(self):

        print("=" * 80)
        print("SUMMARY")
        print("=" * 80)

        print(f"Successful folders      : {self.success}")

        print(f"Folders with warnings   : {self.warning}")

        print(f"Master Database Entries : {len(self.database)}")

        print()

        print("Files Created")

        print("   ../database/master_database.json")

        print("   ../database/validation_report.json")

        print()

        print("Master Database Version : 2.0")

        print("=" * 80)


# ==========================================================
# MAIN
# ==========================================================

if __name__ == "__main__":

    builder = MasterDatabaseBuilder("../data")

    builder.build()

    builder.save()

    builder.summary()