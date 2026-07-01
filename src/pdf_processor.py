from pathlib import Path
import fitz  # PyMuPDF


class PDFProcessor:
    """
    Extracts text from research paper PDFs.
    """

    def __init__(self, data_folder):
        self.data_folder = Path(data_folder)

    def find_pdf(self, pmc_id):
        """
        Finds the PDF corresponding to a PMC ID.
        Example:
            PMC-001 -> PMC-001-gamma-glycine.pdf
            PMC-021 -> PMC-021-L-Leucine.pdf
        """

        pmc_folder = self.data_folder / pmc_id

        if not pmc_folder.exists():
            raise FileNotFoundError(f"{pmc_folder} does not exist.")

        pdf_files = list(pmc_folder.glob("*.pdf"))

        if len(pdf_files) == 0:
            raise FileNotFoundError(f"No PDF found inside {pmc_folder}")

        return pdf_files[0]

    def extract_text(self, pmc_id):
        """
        Extract text from the PDF belonging to a PMC ID.
        """

        pdf_path = self.find_pdf(pmc_id)

        document = fitz.open(pdf_path)

        text = ""

        for page in document:
            text += page.get_text()

        document.close()

        return text


if __name__ == "__main__":

    processor = PDFProcessor("../data")

    # Change only the PMC ID
    pmc = "PMC-001"

    text = processor.extract_text(pmc)

    print("=" * 80)
    print(text[:3000])      # First 3000 characters
    print("=" * 80)

    print(f"\nPMC ID      : {pmc}")
    print(f"Characters  : {len(text)}")