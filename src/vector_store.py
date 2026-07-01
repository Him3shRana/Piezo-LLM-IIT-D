import chromadb


class VectorStore:
    """
    Handles storage and retrieval of embeddings using ChromaDB.
    """

    def __init__(self, db_path="../database"):

        self.client = chromadb.PersistentClient(path=db_path)

        self.collection = self.client.get_or_create_collection(
            name="piezo_crystals"
        )

        print("\nConnected to ChromaDB")

    def add_chunks(self, embedded_chunks):
        """
        Store embedded chunks in ChromaDB.
        """

        ids = []
        documents = []
        embeddings = []
        metadatas = []

        for chunk in embedded_chunks:

            ids.append(
                f"{chunk['pmc_id']}_chunk_{chunk['chunk_id']}"
            )

            documents.append(chunk["text"])

            embeddings.append(chunk["embedding"])

            metadatas.append({
                "pmc_id": chunk["pmc_id"],
                "chunk_id": chunk["chunk_id"],
                "length": chunk["length"]
            })

        self.collection.add(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas
        )

        print(f"\nStored {len(ids)} chunks.")

    def search(self, query_embedding, n_results=5):
        """
        Perform semantic search.
        """

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results
        )

        return results

    def count(self):
        return self.collection.count()

    def clear_database(self):
        """
        Delete all stored vectors.
        """

        try:
            self.client.delete_collection("piezo_crystals")
        except Exception:
            pass

        self.collection = self.client.get_or_create_collection(
            name="piezo_crystals"
        )

        print("Database cleared.")


if __name__ == "__main__":

    from pdf_processor import PDFProcessor
    from chunker import Chunker
    from embedder import Embedder

    pmc_id = "PMC-001"

    print("=" * 80)
    print("VECTOR STORE TEST")
    print("=" * 80)

    processor = PDFProcessor("../data")
    text = processor.extract_text(pmc_id)

    chunker = Chunker()
    chunks = chunker.split(pmc_id, text)

    embedder = Embedder()
    embedded_chunks = embedder.embed_chunks(chunks)

    store = VectorStore()

    # Prevent duplicate entries during testing
    store.clear_database()

    store.add_chunks(embedded_chunks)

    print("\nTotal Stored Chunks :", store.count())