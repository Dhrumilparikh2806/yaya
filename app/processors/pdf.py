import pdfplumber

from app.processors.base import BaseProcessor


class PDFProcessor(BaseProcessor):
    def extract(self) -> str:
        text_parts = []
        with pdfplumber.open(self.job.file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text() or ""
                if not page_text.strip():
                    self.log.warning("pdf_page_no_text", page=i + 1)
                tables = page.extract_tables()
                for table in tables:
                    page_text += "\n" + self._table_to_markdown(table)
                text_parts.append(f"[Page {i + 1}]\n{page_text}")
        return "\n\n".join(text_parts)

    def summarise(self, text: str, db) -> dict:
        if len(text) > 30000:
            self.log.warning("pdf_text_truncated", original_len=len(text), truncated_to=30000)
            text = text[:30000]

        prompt = f"""You are a document analyst. Analyse the following document text and return ONLY valid JSON.
No preamble, no markdown code blocks, just raw JSON.

Return this exact structure:
{{
  "title": "document title or filename",
  "document_type": "report|contract|paper|manual|other",
  "summary": "2-3 sentence summary",
  "key_points": ["point 1", "point 2", ...],
  "risks": ["risk 1", ...],
  "entities": ["company names, person names, product names mentioned"],
  "tables_found": true|false
}}

Document text:
{text}
"""
        return self._call_gemini_json(prompt, db)
