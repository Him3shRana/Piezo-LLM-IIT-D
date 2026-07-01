import re


class TextCleaner:
    """
    Cleans extracted PDF text before chunking.
    """

    def __init__(self):

        self.stop_sections = [
            "References",
            "REFERENCES",
            "Bibliography",
            "Acknowledgements",
            "Acknowledgments",
            "Funding",
            "Conflict of Interest"
        ]

        self.patterns = [
            r"Downloaded from.*",
            r"This content was downloaded.*",
            r"View the article online.*",
            r"You may also like.*",
            r"Phys\. Scr\..*",
            r"PAPER\s*•\s*OPEN ACCESS",
            r"OPEN ACCESS",
            r"To cite this article:.*",
            r"https://doi\.org/\S+",
            r"E-mail:.*",
            r"Page \d+ of \d+",
            r"Received.*",
            r"Accepted.*",
            r"Published.*",
            r"©.*",
        ]

    def remove_reference_section(self, text):

        for section in self.stop_sections:
            index = text.find(section)

            if index != -1:
                return text[:index]

        return text

    def remove_noise(self, text):

        for pattern in self.patterns:
            text = re.sub(pattern, "", text, flags=re.MULTILINE)

        return text

    def remove_extra_whitespace(self, text):

        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)

        return text.strip()

    def clean(self, text):

        abstract_index = text.find("Abstract")

        if abstract_index != -1:
            text = text[abstract_index:]

        text = self.remove_reference_section(text)
        text = self.remove_noise(text)
        text = self.remove_extra_whitespace(text)

        return text


if __name__ == "__main__":

    from pdf_processor import PDFProcessor

    processor = PDFProcessor("../data")

    text = processor.extract_text("PMC-001")

    cleaner = TextCleaner()

    cleaned = cleaner.clean(text)

    print("=" * 80)
    print("ORIGINAL")
    print("=" * 80)
    print(text[:1200])

    print("\n")
    print("=" * 80)
    print("CLEANED")
    print("=" * 80)
    print(cleaned[:1200])