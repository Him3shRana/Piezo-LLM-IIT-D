from pathlib import Path

from pdf_processor import PDFProcessor
from chunker import Chunker
from embedder import Embedder
from vector_store import VectorStore


class IndexBuilder:

    def __init__(self, data_folder="../data"):

        self.data_folder = Path(data_folder)

        self.processor = PDFProcessor(data_folder)
        self.chunker = Chunker()
        self.embedder = Embedder()
        self.store = VectorStore()

    def build(self):

        print("=" * 80)
        print("BUILDING PIEZO DATABASE")
        print("=" * 80)

        self.store.clear_database()

        pmc_folders = sorted(
            [
                folder
                for folder in self.data_folder.iterdir()
                if folder.is_dir() and folder.name.startswith("PMC-")
            ]
        )

        total_chunks = 0

        for folder in pmc_folders:

            pmc_id = folder.name

            print(f"\nProcessing {pmc_id}")

            try:

                text = self.processor.extract_text(pmc_id)

                chunks = self.chunker.split(pmc_id, text)

                embedded = self.embedder.embed_chunks(chunks)

                self.store.add_chunks(embedded)

                total_chunks += len(embedded)

                print(f"✓ Stored {len(embedded)} chunks")

            except Exception as e:

                print(f"✗ Skipped {pmc_id}")
                print(e)

        print("\n")
        print("=" * 80)
        print("INDEX BUILD COMPLETE")
        print("=" * 80)

        print(f"Total Stored Chunks : {self.store.count()}")
        print(f"Total Embedded Chunks : {total_chunks}")


if __name__ == "__main__":

    builder = IndexBuilder("../data")

    builder.build()