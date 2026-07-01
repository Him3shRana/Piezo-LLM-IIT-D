import json
from pathlib import Path


REQUIRED_FIELDS = [
    "crystal_id",
    "molecule_name",
    "chemical_formula",
    "crystal_type",
    "property",
    "evidence",
    "space_group",
    "crystal_system",
    "research_paper_name",
    "journal",
    "year",
    "doi",
    "cif_file_name_local"
]


def validate_dataset(data_folder):

    data_folder = Path(data_folder)

    json_files = list(data_folder.rglob("*.json"))

    print("=" * 70)
    print(f"Found {len(json_files)} JSON files")
    print("=" * 70)

    valid = 0
    invalid = 0

    for file in json_files:

        print(f"\nChecking: {file.name}")

        try:
            with open(file, "r", encoding="utf-8") as f:
                data = json.load(f)

        except Exception as e:
            print(f" Invalid JSON")
            print(e)
            invalid += 1
            continue

        missing = []

        for field in REQUIRED_FIELDS:
            if field not in data:
                missing.append(field)

        if missing:

            print(" Missing Fields:")

            for m in missing:
                print("   -", m)

            invalid += 1

        else:

            print("✅ OK")
            valid += 1

    print("\n")
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Valid JSON Files   : {valid}")
    print(f"Invalid JSON Files : {invalid}")


if __name__ == "__main__":

    validate_dataset("../data")