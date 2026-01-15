"""PDF parsing utility to extract text and tables from PDF files."""

from io import BytesIO
from typing import Optional, List
import warnings

from PyPDF2 import PdfReader
import camelot

from app.schemas.context import Metric


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


def extract_tables_from_pdf(file_bytes: bytes) -> List[Metric]:
    """
    Extract tables from PDF and convert to metrics.

    Args:
        file_bytes: Raw PDF file bytes

    Returns:
        List of Metric objects from numeric values in tables
    """
    metrics = []
    
    # Save bytes to temporary file (Camelot requires file path)
    import tempfile
    import os
    
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        
        # Suppress Camelot warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tables = camelot.read_pdf(tmp_path, pages="all")
        
        if not tables:
            return metrics
        
        # Process each table
        for table in tables:
            df = table.df
            if df.empty or len(df) < 2:  # Need at least header + 1 row
                continue
            
            # First row is header
            headers = df.iloc[0].tolist()
            
            # Process remaining rows
            for row_idx in range(1, len(df)):
                row = df.iloc[row_idx]
                region = str(row.iloc[0]) if len(row) > 0 else None
                
                # Check each column for numeric values
                for col_idx, header in enumerate(headers):
                    if col_idx >= len(row):
                        continue
                    
                    cell_value = row.iloc[col_idx]
                    
                    # Try to convert to numeric
                    try:
                        numeric_value = float(str(cell_value).strip())
                        metric = Metric(
                            name=str(header).strip(),
                            region=region,
                            value=numeric_value
                        )
                        metrics.append(metric)
                    except (ValueError, TypeError):
                        # Not numeric, skip
                        continue
    
    except Exception as e:
        # Log but don't crash - table parsing is optional
        print(f"Warning: Failed to extract tables from PDF: {e}")
        return metrics
    
    finally:
        # Clean up temporary file
        try:
            if 'tmp_path' in locals():
                os.unlink(tmp_path)
        except Exception:
            pass
    
    return metrics


def extract_metadata_and_text(file_bytes: bytes) -> dict:
    """
    Extract both metadata, text, and tables from PDF.

    Args:
        file_bytes: Raw PDF file bytes

    Returns:
        Dictionary with 'text', 'num_pages', 'metadata', and 'metrics'
    """
    try:
        pdf_file = BytesIO(file_bytes)
        reader = PdfReader(pdf_file)

        metadata = reader.metadata if reader.metadata else {}
        text = extract_text_from_pdf(file_bytes)
        metrics = extract_tables_from_pdf(file_bytes)

        return {
            "text": text,
            "num_pages": len(reader.pages),
            "metadata": {
                "title": metadata.get("/Title", ""),
                "author": metadata.get("/Author", ""),
                "subject": metadata.get("/Subject", ""),
                "creator": metadata.get("/Creator", ""),
            },
            "metrics": metrics,
        }
    except Exception as e:
        raise ValueError(f"Failed to extract metadata: {str(e)}")
