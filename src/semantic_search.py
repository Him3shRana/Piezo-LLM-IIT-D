from embedder import Embedder
from vector_store import VectorStore


class SemanticSearch:

    def __init__(self):

        self.embedder = Embedder()
        self.store = VectorStore()

    def search(self, query, top_k=5):

        print("\nEmbedding query...")

        query_embedding = self.embedder.model.encode(query).tolist()

        print("Searching database...")

        results = self.store.search(
            query_embedding,
            n_results=top_k
        )

        return results


if __name__ == "__main__":

    print("=" * 80)
    print("SEMANTIC SEARCH TEST")
    print("=" * 80)

    searcher = SemanticSearch()

    query = input("\nAsk a question:\n\n> ")

    results = searcher.search(query)

    print("\n")
    print("=" * 80)
    print("TOP RESULTS")
    print("=" * 80)

    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    for i in range(len(documents)):

        print(f"\nResult {i+1}")
        print("-" * 80)

        print("PMC ID :", metadatas[i]["pmc_id"])
        print("Chunk  :", metadatas[i]["chunk_id"])
        print("Score  :", round(distances[i], 4))

        print("\n")

        print(documents[i][:800])

        print("\n" + "=" * 80)