import json
from pathlib import Path


class DatabaseIndexer:

    def __init__(self):

        # Project root
        self.root = Path(__file__).resolve().parent.parent

        self.master_db = self.root / "database" / "master_database.json"
        self.output_index = self.root / "database" / "search_index.json"

    # =========================================================

    @staticmethod
    def safe(value):

        if value is None:
            return ""

        if isinstance(value, list):
            return " ".join(str(v) for v in value)

        return str(value)

    # =========================================================

    def build_document(self, metadata, crystal_json):

        parts = []

        # -----------------------------
        # High-weight fields
        # -----------------------------

        name = self.safe(metadata.get("molecule_name"))
        parts.extend([name] * 5)

        aliases = self.safe(metadata.get("aliases"))
        parts.extend([aliases] * 3)

        # -----------------------------
        # Metadata
        # -----------------------------

        parts.extend([

            self.safe(metadata.get("pmc_id")),
            self.safe(metadata.get("chemical_formula")),
            self.safe(metadata.get("csd_refcode")),
            self.safe(metadata.get("ccdc_number")),
            self.safe(metadata.get("space_group_symbol")),
            self.safe(metadata.get("crystal_system")),
            self.safe(metadata.get("property_ref_doi")),
            self.safe(metadata.get("structure_ref_doi")),
            self.safe(metadata.get("search_text"))

        ])

        # -----------------------------
        # Full JSON text
        # -----------------------------

        parts.append(
            self.safe(
                crystal_json.get("text")
            )
        )

        return " ".join(parts)

    # =========================================================

    def build_index(self):

        print("=" * 60)
        print("Building Search Index")
        print("=" * 60)

        if not self.master_db.exists():

            print("ERROR:")
            print(self.master_db)
            print("does not exist.")
            return

        with open(self.master_db, "r", encoding="utf-8") as f:

            master = json.load(f)

        crystals = master["crystals"]

        print(f"Found {len(crystals)} crystals.\n")

        index = []

        for crystal_id, metadata in crystals.items():

            json_path = (
                self.root /
                metadata["json_path"].replace("../", "")
            )

            if not json_path.exists():

                print(f"Missing JSON : {json_path}")
                continue

            with open(json_path, "r", encoding="utf-8") as f:

                crystal_json = json.load(f)

            document = self.build_document(
                metadata,
                crystal_json
            )

            index.append({

                "id": crystal_id,

                "molecule_name":
                    metadata["molecule_name"],

                "aliases":
                    metadata.get("aliases", []),

                "json_path":
                    str(json_path),

                "document":
                    document

            })

            print(f"Indexed {crystal_id}")

        print()

        with open(
            self.output_index,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                index,
                f,
                indent=2,
                ensure_ascii=False
            )

        print("=" * 60)
        print("DONE")
        print(f"Indexed {len(index)} crystals.")
        print(self.output_index)
        print("=" * 60)


# =============================================================

if __name__ == "__main__":

    DatabaseIndexer().build_index()