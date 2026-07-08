"""
build_rich_vectors.py
---------------------
Builds ChromaDB embeddings from ALL four data sources per molecule:
  - JSON  → structured properties
  - TXT   → metadata summary
  - PDF   → extracted paper text (experimental details, discussion)
  - CIF   → atomic coordinates, bond lengths, symmetry info

Each molecule gets ONE rich combined document in the vector DB,
so Qwen3 gets maximum context when answering questions.

Usage:
  cd ~/Documents/Piezo-LLM/src
  source ../venv/bin/activate   (or venv-finetune)
  python build_rich_vectors.py

Requirements:
  pip install langchain-huggingface langchain-chroma chromadb PyMuPDF
"""

import json
import os
import re
from pathlib import Path

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from langchain_core.documents import Document

# ── Paths ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
VECTORDB_DIR = PROJECT_ROOT / "vectordb"

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
COLLECTION_NAME = "piezo_crystals"


# ── PDF text extraction ────────────────────────────────
def extract_pdf_text(pdf_path: str, max_chars: int = 4000) -> str:
    """Extract text from a PDF using PyMuPDF (fitz)."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(pdf_path)
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()

        full_text = "\n".join(text_parts)

        # Clean up: remove excessive whitespace, headers/footers
        full_text = re.sub(r'\n{3,}', '\n\n', full_text)
        full_text = re.sub(r'[ \t]{2,}', ' ', full_text)

        # Remove common journal boilerplate
        for pattern in [
            r'Downloaded from .*?\n',
            r'©.*?reserved\.?\n?',
            r'DOI:.*?\n',
            r'Received \d+.*?Accepted \d+.*?\n',
        ]:
            full_text = re.sub(pattern, '', full_text, flags=re.IGNORECASE)

        # Truncate to max_chars to keep embedding quality high
        if len(full_text) > max_chars:
            full_text = full_text[:max_chars] + "..."

        return full_text.strip()

    except ImportError:
        print("  ⚠ PyMuPDF not installed. Run: pip install PyMuPDF")
        return ""
    except Exception as e:
        print(f"  ⚠ PDF extraction failed: {e}")
        return ""


# ── CIF text extraction ───────────────────────────────
def extract_cif_info(cif_path: str) -> str:
    """
    Extract key crystallographic info from a CIF file.
    Pulls: cell parameters, space group, atom sites, symmetry ops.
    """
    try:
        with open(cif_path, 'r', errors='ignore') as f:
            content = f.read()

        info_parts = []

        # Cell parameters
        cell_keys = {
            '_cell_length_a': 'a',
            '_cell_length_b': 'b',
            '_cell_length_c': 'c',
            '_cell_angle_alpha': 'alpha',
            '_cell_angle_beta': 'beta',
            '_cell_angle_gamma': 'gamma',
            '_cell_volume': 'volume',
        }
        cell_params = []
        for cif_key, label in cell_keys.items():
            match = re.search(rf'^{cif_key}\s+(.+)$', content, re.MULTILINE)
            if match:
                cell_params.append(f"{label}={match.group(1).strip()}")
        if cell_params:
            info_parts.append(f"Unit cell: {', '.join(cell_params)}")

        # Space group
        for sg_key in ['_symmetry_space_group_name_H-M',
                       '_space_group_name_H-M_alt',
                       '_space_group.name_H-M_full']:
            match = re.search(rf"^{re.escape(sg_key)}\s+['\"]?(.+?)['\"]?\s*$",
                              content, re.MULTILINE)
            if match:
                info_parts.append(f"Space group: {match.group(1).strip()}")
                break

        # Chemical formula
        for formula_key in ['_chemical_formula_sum',
                            '_chemical_formula_moiety']:
            match = re.search(rf"^{re.escape(formula_key)}\s+['\"]?(.+?)['\"]?\s*$",
                              content, re.MULTILINE)
            if match:
                info_parts.append(f"Formula (CIF): {match.group(1).strip()}")
                break

        # Count atom sites
        atom_lines = re.findall(
            r'^[A-Z][a-z]?\d*\s+[A-Z][a-z]?\s+[\d.]+\s+[\d.]+\s+[\d.]+',
            content, re.MULTILINE
        )
        if atom_lines:
            info_parts.append(f"Atom sites in CIF: {len(atom_lines)}")

        # Symmetry operations
        sym_ops = re.findall(
            r"^'([^']+)'",
            content, re.MULTILINE
        )
        if sym_ops:
            info_parts.append(
                f"Symmetry operations ({len(sym_ops)}): "
                + "; ".join(sym_ops[:4])
                + ("..." if len(sym_ops) > 4 else "")
            )

        return "\n".join(info_parts) if info_parts else ""

    except Exception as e:
        print(f"  ⚠ CIF extraction failed: {e}")
        return ""


# ── Load and combine all sources ──────────────────────
def load_all_sources():
    """
    Walk data/PMC-*/ folders. For each molecule, combine:
      JSON text field + TXT content + PDF extracted text + CIF info
    into one rich document.
    """
    documents = []
    ids = []
    skipped = []

    if not DATA_DIR.exists():
        print(f"Data directory not found: {DATA_DIR}")
        return documents, ids, skipped

    folders = sorted(
        [d for d in DATA_DIR.iterdir() if d.is_dir() and d.name.startswith("PMC-")]
    )

    print(f"Found {len(folders)} PMC folders\n")

    for folder in folders:
        pmc_id = folder.name

        # ── Find the JSON ──
        json_files = list(folder.glob("*.json"))
        if not json_files:
            skipped.append(f"{pmc_id}: no JSON found (empty/placeholder)")
            continue

        json_path = json_files[0]
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
        except Exception as e:
            skipped.append(f"{pmc_id}: JSON read error ({e})")
            continue

        molecule_name = data.get("molecule_name", pmc_id)
        text_parts = []

        # ── 1. JSON text field (always present) ──
        json_text = data.get("text", "")
        if json_text:
            text_parts.append(f"[Summary] {json_text}")

        # ── 2. TXT file (metadata narrative) ──
        txt_files = list(folder.glob("*.txt"))
        for txt_file in txt_files:
            try:
                txt_content = txt_file.read_text(errors='ignore').strip()
                if txt_content and len(txt_content) > 50:
                    # Don't duplicate if TXT is very similar to JSON text
                    text_parts.append(f"[Metadata] {txt_content}")
                    print(f"  {pmc_id}: ✅ TXT loaded ({len(txt_content)} chars)")
            except Exception as e:
                print(f"  {pmc_id}: ⚠ TXT error: {e}")

        # ── 3. PDF file (research paper) ──
        pdf_files = list(folder.glob("*.pdf"))
        for pdf_file in pdf_files:
            pdf_text = extract_pdf_text(str(pdf_file))
            if pdf_text and len(pdf_text) > 100:
                text_parts.append(f"[Paper] {pdf_text}")
                print(f"  {pmc_id}: ✅ PDF loaded ({len(pdf_text)} chars)")

        # ── 4. CIF file (crystal structure) ──
        cif_files = list(folder.glob("*.cif"))
        for cif_file in cif_files:
            cif_info = extract_cif_info(str(cif_file))
            if cif_info:
                text_parts.append(f"[Structure] {cif_info}")
                print(f"  {pmc_id}: ✅ CIF loaded")

        # ── Combine everything ──
        if not text_parts:
            skipped.append(f"{pmc_id}: no usable text content")
            continue

        combined_text = "\n\n".join(text_parts)

        # If the combined text is very long, we can chunk it
        # For now, keep it as one document per molecule (ChromaDB handles it)
        doc = Document(
            page_content=combined_text,
            metadata={
                "pmc_id": pmc_id,
                "molecule_name": molecule_name,
                "chemical_formula": data.get("chemical_formula", ""),
                "crystal_system": data.get("crystal_system", ""),
                "space_group": data.get("space_group_symbol", ""),
                "is_piezoelectric": str(data.get("is_piezoelectric", "")),
                "has_txt": str(bool(txt_files)),
                "has_pdf": str(bool(pdf_files)),
                "has_cif": str(bool(cif_files)),
                "sources_used": ",".join(
                    [s.split("]")[0].replace("[", "") for s in text_parts]
                ),
            }
        )
        documents.append(doc)
        ids.append(pmc_id)

        sources = [s.split("]")[0].replace("[", "") for s in text_parts]
        print(f"  {pmc_id} ({molecule_name}): {len(combined_text)} chars "
              f"from {', '.join(sources)}")

    return documents, ids, skipped


# ── Build the vector DB ───────────────────────────────
def build_rich_vector_db():
    """Build/update ChromaDB with rich combined documents."""
    documents, ids, skipped = load_all_sources()

    if not documents:
        return {
            "success": False,
            "error": "No documents to index",
            "skipped": skipped,
            "total_in_db": 0,
            "processed": 0,
            "new": 0,
            "updated": 0,
        }

    print(f"\nLoading embedding model '{EMBED_MODEL}'...")
    embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL)

    print(f"Opening Chroma DB at: {VECTORDB_DIR}")
    db = Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=str(VECTORDB_DIR),
    )

    before = db._collection.count()
    print(f"Updating/adding molecules by pmc_id...")
    db.add_documents(documents=documents, ids=ids)
    after = db._collection.count()

    new = after - before
    updated = len(documents) - new

    return {
        "success": True,
        "total_in_db": after,
        "processed": len(documents),
        "new": new,
        "updated": updated,
        "skipped": skipped,
        "error": None,
    }


# ── Main ──────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  Piezo-LLM: Rich Vector DB Builder")
    print("  Sources: JSON + TXT + PDF + CIF")
    print("=" * 60)
    print(f"\nData directory: {DATA_DIR}\n")

    result = build_rich_vector_db()

    print("\n" + "=" * 60)

    if result["skipped"]:
        print(f"\nSkipped {len(result['skipped'])}:")
        for s in result["skipped"]:
            print(f"   - {s}")

    if not result["success"]:
        print(f"\n❌ Build failed: {result['error']}")
        return

    print(f"\n✅ Vector DB updated!")
    print(f"   Total molecules: {result['total_in_db']}")
    print(f"   Processed: {result['processed']} "
          f"({result['new']} new, {result['updated']} updated)")

    # ── Test search ──
    print(f"\n{'=' * 60}")
    print("Test searches:\n")
    embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
    db = Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=str(VECTORDB_DIR),
    )

    test_queries = [
        "piezoelectric amino acid crystal",
        "X-ray three-beam diffraction technique",
        "hydrogen bonding in crystal structure",
    ]
    for query in test_queries:
        print(f'  Query: "{query}"')
        results = db.similarity_search(query, k=3)
        for i, doc in enumerate(results, 1):
            pmc = doc.metadata.get("pmc_id", "?")
            name = doc.metadata.get("molecule_name", "?")
            sources = doc.metadata.get("sources_used", "")
            print(f"    {i}. [{pmc}] {name} (sources: {sources})")
        print()


if __name__ == "__main__":
    main()