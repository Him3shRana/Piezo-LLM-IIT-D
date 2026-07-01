import json
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


class JSONRetriever:

    def __init__(self):

        root = Path(__file__).resolve().parent.parent

        self.index_path = root / "database" / "search_index.json"

        with open(self.index_path, "r", encoding="utf-8") as f:
            self.index = json.load(f)

        self.documents = [
            item["document"]
            for item in self.index
        ]

        self.vectorizer = TfidfVectorizer(
            lowercase=True,
            stop_words="english",
            ngram_range=(1, 2)
        )

        self.document_matrix = self.vectorizer.fit_transform(
            self.documents
        )

        print(f"Loaded {len(self.index)} indexed crystals.")

    # ====================================================

    def search(self, query, top_k=5):

        query_vector = self.vectorizer.transform([query])

        similarities = cosine_similarity(
            query_vector,
            self.document_matrix
        )[0]

        ranked = sorted(

            zip(self.index, similarities),

            key=lambda x: x[1],

            reverse=True

        )

        return ranked[:top_k]

    # ====================================================

    def retrieve(self, query, top_k=5):

        matches = self.search(query, top_k)

        results = []

        for item, score in matches:

            if score <= 0:
                continue

            with open(
                item["json_path"],
                "r",
                encoding="utf-8"
            ) as f:

                crystal = json.load(f)

            results.append({

                "score": float(score),

                "id": item["id"],

                "molecule_name": item["molecule_name"],

                "json": crystal

            })

        return results


# =======================================================

if __name__ == "__main__":

    retriever = JSONRetriever()

    print("=" * 70)
    print("Piezo-LLM Retriever")
    print("=" * 70)

    while True:

        query = input("\nAsk : ")

        if query.lower() == "exit":
            break

        results = retriever.retrieve(query)

        print()

        if len(results) == 0:

            print("No match found.")

            continue

        print("Top Matches\n")

        for i, r in enumerate(results, start=1):

            print(
                f"{i}. "
                f"{r['id']} | "
                f"{r['molecule_name']} | "
                f"{r['score']:.3f}"
            )