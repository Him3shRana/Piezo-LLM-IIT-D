from sentence_transformers import SentenceTransformer


class Embedder:
    """
    Generates embeddings using BAAI/bge-large-en-v1.5
    """

    def __init__(self,
                 model_name="BAAI/bge-large-en-v1.5"):

        print("\nLoading embedding model...")
        self.model = SentenceTransformer(model_name)
        print("Embedding model loaded successfully.\n")

    def embed_text(self, text):
        """
        Generate embedding for a single text.
        """

        embedding = self.model.encode(
            text,
            normalize_embeddings=True
        )

        return embedding.tolist()

    def embed_chunks(self, chunks):
        """
        Generate embeddings for all chunks.

        Parameters
        ----------
        chunks : list

        Returns
        -------
        list
        """

        embedded_chunks = []

        total = len(chunks)

        for i, chunk in enumerate(chunks):

            print(f"Embedding {i+1}/{total}")

            vector = self.embed_text(chunk["text"])

            embedded_chunks.append({
                "pmc_id": chunk["pmc_id"],
                "chunk_id": chunk["chunk_id"],
                "text": chunk["text"],
                "length": chunk["length"],
                "embedding": vector
            })

        return embedded_chunks


if __name__ == "__main__":

    from pdf_processor import PDFProcessor
    from chunker import Chunker

    pmc_id = "PMC-001"

    print("=" * 80)
    print("EMBEDDER TEST")
    print("=" * 80)

    # Step 1: Extract text
    processor = PDFProcessor("../data")
    text = processor.extract_text(pmc_id)

    # Step 2: Split into chunks
    chunker = Chunker()
    chunks = chunker.split(pmc_id, text)

    print(f"\nChunks created : {len(chunks)}")

    # Step 3: Generate embeddings
    embedder = Embedder()

    embedded_chunks = embedder.embed_chunks(chunks)

    print("\nEmbedding Complete")
    print("=" * 80)

    print(f"Total Embedded Chunks : {len(embedded_chunks)}")

    print("\nFirst Chunk")

    print("-----------------------------------------")
    print("PMC ID    :", embedded_chunks[0]["pmc_id"])
    print("Chunk ID  :", embedded_chunks[0]["chunk_id"])
    print("Length    :", embedded_chunks[0]["length"])
    print("Vector Dim:", len(embedded_chunks[0]["embedding"]))
    print("-----------------------------------------")