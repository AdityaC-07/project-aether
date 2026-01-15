"""PDF parsing utility to extract text from PDF files."""

from io import BytesIO
from typing import Optional

from PyPDF2 import PdfReader


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """
    Extract text from a PDF file.

    Args:
        file_bytes: Raw PDF file bytes

    Returns:
        Extracted text from all pages, joined by newlines

    Raises:
        ValueError: If PDF is invalid or corrupted
    """
    try:
        pdf_file = BytesIO(file_bytes)
        reader = PdfReader(pdf_file)

        if not reader.pages:
            raise ValueError("PDF has no pages")

        text_content = []
        for page_num, page in enumerate(reader.pages):
            try:
                text = page.extract_text()
                if text:
                    text_content.append(text)
            except Exception as e:
                # Log but continue if one page fails
                print(f"Warning: Failed to extract text from page {page_num + 1}: {e}")
                continue

        if not text_content:
            raise ValueError("No text could be extracted from PDF")

        return "\n".join(text_content)

    except Exception as e:
        raise ValueError(f"Failed to parse PDF: {str(e)}")


def extract_metadata_and_text(file_bytes: bytes) -> dict:
    """
    Extract both metadata and text from PDF.

    Args:
        file_bytes: Raw PDF file bytes

    Returns:
        Dictionary with 'text', 'num_pages', and 'metadata'
    """
    try:
        pdf_file = BytesIO(file_bytes)
        reader = PdfReader(pdf_file)

        metadata = reader.metadata if reader.metadata else {}
        text = extract_text_from_pdf(file_bytes)

        return {
            "text": text,
            "num_pages": len(reader.pages),
            "metadata": {
                "title": metadata.get("/Title", ""),
                "author": metadata.get("/Author", ""),
                "subject": metadata.get("/Subject", ""),
                "creator": metadata.get("/Creator", ""),
            },
        }
    except Exception as e:
        raise ValueError(f"Failed to extract metadata: {str(e)}")
