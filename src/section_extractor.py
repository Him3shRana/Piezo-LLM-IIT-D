import re


class SectionExtractor:
    """
    Extracts important scientific sections from a cleaned research paper.
    """

    def __init__(self):

        self.section_titles = [
            "Abstract",
            "Introduction",
            "Experimental",
            "Materials and Methods",
            "Methods",
            "Results",
            "Results and Discussion",
            "Discussion",
            "Conclusion",
            "Conclusions"
        ]

    def extract(self, text):

        sections = {}

        matches = []

        for title in self.section_titles:

            pattern = rf"\b{re.escape(title)}\b"

            m = re.search(pattern, text, re.IGNORECASE)

            if m:
                matches.append((m.start(), title))

        matches.sort()

        for i, (start, title) in enumerate(matches):

            if i < len(matches) - 1:
                end = matches[i + 1][0]
            else:
                end = len(text)

            sections[title] = text[start:end].strip()

        return sections


if __name__ == "__main__":

    from pdf_processor import PDFProcessor
    from text_cleaner import TextCleaner

    pdf = PDFProcessor("../data")

    cleaner = TextCleaner()

    text = pdf.extract_text("PMC-001")

    cleaned = cleaner.clean(text)

    extractor = SectionExtractor()

    sections = extractor.extract(cleaned)

    print("=" * 80)

    print("SECTIONS FOUND")

    print("=" * 80)

    for name, content in sections.items():

        print(f"\n{name}")
        print("-" * 80)
        print(content[:500])
