"""
PDF file processor.

Extracts text and tables page by page with pdfplumber.  Each page becomes a
'## Page N' markdown section so the chunker can split on page boundaries and
citations reference page numbers.  Tables are converted to markdown inline.

The LLM summary (title, document_type, key_points, risks, entities,
tables_found) is produced by a single Groq call after full extraction.
"""

import pdfplumber

from app.processors.base import BaseProcessor


class PDFProcessor(BaseProcessor):
    def extract(self) -> str:
        parts = [f"# {self.job.filename}"]
        with pdfplumber.open(self.job.file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                parts.append(f"## Page {i + 1}")

                page_text = page.extract_text() or ""
                if page_text.strip():
                    parts.append(page_text.strip())

                tables = page.extract_tables()
                for table in tables:
                    if table:
                        md_table = self._table_to_markdown(table)
                        if md_table:
                            parts.append(md_table)

        return "\n\n".join(parts)

    def summarise(self, text: str, db) -> dict:
        # Truncate for the summary LLM call only; full text goes to chunking
        summary_text = text[:12000] if len(text) > 12000 else text

        prompt = f"""You are a document analyst. Analyse the following document text and return ONLY valid JSON.
No preamble, no markdown code blocks, just raw JSON.

Return this exact structure:
{{
  "title": "document title or filename",
  "document_type": "report|contract|invoice|proposal|other",
  "summary": "2-3 sentence summary",
  "key_points": ["point 1", "point 2"],
  "entities": ["company names, person names, product names mentioned"]
}}

Document text:
{summary_text}
"""
        return self._call_gemini_json(prompt, db)
