from langchain_text_splitters import RecursiveCharacterTextSplitter


class Chunker:
    """
    Splits research papers into overlapping chunks while
    preserving metadata for each chunk.
    """

    def __init__(self, chunk_size=1000, chunk_overlap=200):

        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=len,
            separators=[
                "\n\n",
                "\n",
                ". ",
                " ",
                ""
            ]
        )

    def split(self, pmc_id, text):
        """
        Split a research paper into structured chunks.

        Parameters
        ----------
        pmc_id : str
            PMC ID of the paper.

        text : str
            Extracted PDF text.

        Returns
        -------
        list[dict]
        """

        raw_chunks = self.splitter.split_text(text)

        chunks = []

        for i, chunk in enumerate(raw_chunks):

            chunks.append({
                "pmc_id": pmc_id,
                "chunk_id": i,
                "text": chunk,
                "length": len(chunk)
            })

        return chunks


if __name__ == "__main__":

    print("=" * 80)
    print("CHUNKER TEST")
    print("=" * 80)

    from pdf_processor import PDFProcessor

    pmc_id = "PMC-001"

    processor = PDFProcessor("../data")

    text = processor.extract_text(pmc_id)

    print("PDF Loaded")
    print("Characters :", len(text))

    chunker = Chunker()

    chunks = chunker.split(pmc_id, text)

    print("\nChunks Created :", len(chunks))

    print("=" * 80)

    for chunk in chunks[:3]:

        print(f"\nChunk ID : {chunk['chunk_id']}")
        print(f"Length   : {chunk['length']}")
        print("-" * 80)
        print(chunk["text"][:600])