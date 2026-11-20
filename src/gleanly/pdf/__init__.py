"""PDF support: native text layer (this phase) and, with the [ocr] extra, scanned pages."""

from gleanly.pdf.native import PdfText, read_pdf

__all__ = ["PdfText", "read_pdf"]
