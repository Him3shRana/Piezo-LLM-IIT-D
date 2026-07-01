import re

from json_retriever import JSONRetriever


class QueryRouter:

    """
    Understands user queries and routes them
    to the correct retriever.
    """

    def __init__(self):

        self.retriever = JSONRetriever()

        self.intent_keywords = {

            "space_group": [
                "space group",
                "spacegroup",
                "sg"
            ],

            "crystal_system": [
                "crystal system"
            ],

            "formula": [
                "formula",
                "chemical formula",
                "composition"
            ],

            "molecular_weight": [
                "molecular weight",
                "molar mass"
            ],

            "piezoelectric": [
                "piezoelectric",
                "piezoelectricity",
                "piezo"
            ],

            "ferroelectric": [
                "ferroelectric",
                "ferroelectricity"
            ],

            "pyroelectric": [
                "pyroelectric",
                "pyroelectricity"
            ],

            "doi": [
                "doi",
                "paper",
                "publication"
            ],

            "ccdc": [
                "ccdc"
            ],

            "refcode": [
                "refcode",
                "csd"
            ],

            "cif": [
                "cif",
                "crystal structure"
            ],

            "summary": [
                "summary",
                "summarize",
                "overview"
            ],

            "abstract": [
                "abstract"
            ],

            "conclusion": [
                "conclusion",
                "conclude"
            ]
        }

    # =====================================================

    def normalize(self, text):

        text = text.lower()

        text = text.replace("γ", "gamma")
        text = text.replace("β", "beta")
        text = text.replace("α", "alpha")

        text = re.sub(r"[^\w\s\-]", " ", text)

        text = re.sub(r"\s+", " ", text)

        return text.strip()

    # =====================================================

    def detect_intent(self, query):

        query = self.normalize(query)

        for intent, keywords in self.intent_keywords.items():

            for keyword in keywords:

                if keyword in query:

                    return intent

        return "general"

    # =====================================================

    def route(self, query):

        retrieval = self.retriever.retrieve_with_score(query)

        if retrieval is None:

            return {

                "status": "not_found",

                "intent": None,

                "crystal_id": None,

                "score": 0,

                "json": None

            }

        intent = self.detect_intent(query)

        return {

            "status": "success",

            "intent": intent,

            "crystal_id": retrieval["crystal_id"],

            "score": retrieval["score"],

            "json": retrieval["json"]

        }


# =============================================================

if __name__ == "__main__":

    router = QueryRouter()

    print("=" * 70)
    print("Piezo-LLM Query Router")
    print("=" * 70)

    while True:

        print()

        question = input("Question : ")

        if question.lower() == "exit":
            break

        result = router.route(question)

        print()

        print("=" * 70)

        print("Status     :", result["status"])
        print("Intent     :", result["intent"])
        print("Crystal ID :", result["crystal_id"])
        print("Score      :", result["score"])

        if result["json"] is not None:

            crystal = result["json"]

            print()
            print("Molecule :", crystal["molecule_name"])
            print("Formula  :", crystal["chemical_formula"])
            print("SpaceGrp :", crystal["space_group_symbol"])

        print("=" * 70)