import json
import re
from pathlib import Path


SOURCE_FOLDER = Path("../data")
OUTPUT_FOLDER = Path("../standardized_data")

OUTPUT_FOLDER.mkdir(exist_ok=True)


def parse_space_group(space_group):

    if isinstance(space_group, dict):
        return space_group

    symbol = ""
    number = None

    match = re.search(r"\(No\.\s*(\d+)\)", space_group)

    if match:
        number = int(match.group(1))

    symbol = space_group.split("(")[0].strip()

    return {
        "symbol": symbol,
        "number": number
    }


def convert_file(json_path):

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Already in new format
    if "crystal_id" in data:

        crystal_id = data["crystal_id"]

        output_dir = OUTPUT_FOLDER / crystal_id
        output_dir.mkdir(exist_ok=True)

        with open(output_dir / json_path.name, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)

        print(f"Copied {crystal_id}")

        return

    crystal_id = data.get("Crystal ID", "")

    cif_name = data.get("CIF_File_Name", "")

    base_name = cif_name.replace(".cif", "")

    new_data = {

        "crystal_id": crystal_id,

        "molecule_name": data.get("Molecule_Name", ""),

        "chemical_formula": data.get("Chemical_Formula", ""),

        "crystal_type": data.get("Crystal_Type", ""),

        "property": [
            data.get("Property", "")
        ],

        "evidence": {

            "piezoelectricity": data.get("Evidence", ""),

            "ferroelectricity": ""

        },

        "space_group": parse_space_group(
            data.get("Space_Group", "")
        ),

        "crystal_system": data.get("Crystal_System", ""),

        "research_paper_name": data.get(
            "Research_Paper_Name",
            ""
        ),

        "journal": data.get(
            "Journal",
            ""
        ),

        "year": data.get(
            "Year",
            ""
        ),

        "doi": data.get(
            "DOI",
            ""
        ),

        "pdf_file_name_local": base_name + ".pdf",

        "text_file_name_local": base_name + ".txt",

        "cif_file_name_local": cif_name

    }

    output_dir = OUTPUT_FOLDER / crystal_id
    output_dir.mkdir(exist_ok=True)

    output_file = output_dir / f"{crystal_id}.json"

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(
            new_data,
            f,
            indent=4,
            ensure_ascii=False
        )

    print(f"Converted {crystal_id}")


def main():

    json_files = list(
        SOURCE_FOLDER.rglob("*.json")
    )

    print(f"\nFound {len(json_files)} JSON files\n")

    for file in json_files:

        try:

            convert_file(file)

        except Exception as e:

            print(f"Failed: {file}")
            print(e)

    print("\nDone!\n")


if __name__ == "__main__":
    main()