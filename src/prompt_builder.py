class PromptBuilder:

    def __init__(self):

        # This prompt is reused for every request.

        self.system_prompt = """
You are Piezo-LLM.

You are an expert AI assistant for piezoelectric molecular crystals.

Answer only from the provided scientific context.

If the required information is missing, reply:

"The requested information is not available in the current database."

Do not invent scientific facts.

Do not mention JSON files, databases, or internal implementation.

Write clear, concise, and scientifically accurate answers.

Include numerical values, units, crystal IDs, and DOI information whenever available.
"""

    def build_prompt(self, context, question):

        # Create the final prompt for the language model.

        return f"""
{self.system_prompt}

Scientific Context

{context}

User Question

{question}

Answer
"""


if __name__ == "__main__":

    from json_retriever import JSONRetriever
    from context_builder import ContextBuilder

    retriever = JSONRetriever()

    results = retriever.retrieve("meta nitroaniline")

    builder = ContextBuilder()

    context = builder.build_context(results)

    prompt_builder = PromptBuilder()

    prompt = prompt_builder.build_prompt(
        context=context,
        question="What is the space group?"
    )

    print(prompt)