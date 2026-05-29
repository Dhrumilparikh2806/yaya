from docx import Document as DocxDocument
from docx.oxml.ns import qn

from app.processors.base import BaseProcessor

_HEADING_STYLES = {
    "Heading1": "#", "Heading 1": "#", "heading1": "#",
    "Heading2": "##", "Heading 2": "##", "heading2": "##",
    "Heading3": "###", "Heading 3": "###", "heading3": "###",
    "Heading4": "####", "Heading 4": "####",
    "Heading5": "####", "Heading 5": "####",
    "Title": "#",
}


def _get_style_id(para_element) -> str:
    pPr = para_element.find(qn("w:pPr"))
    if pPr is not None:
        pStyle = pPr.find(qn("w:pStyle"))
        if pStyle is not None:
            return pStyle.get(qn("w:val"), "")
    return ""


def _get_para_text(para_element) -> str:
    return "".join(
        node.text for node in para_element.iter(qn("w:t")) if node.text
    ).strip()


def _get_table_rows(tbl_element) -> list[list[str]]:
    rows = []
    for tr in tbl_element.iter(qn("w:tr")):
        row = []
        for tc in tr.findall(qn("w:tc")):
            cell_text = "".join(
                node.text for node in tc.iter(qn("w:t")) if node.text
            ).strip()
            row.append(cell_text)
        if row:
            rows.append(row)
    return rows


class DOCXProcessor(BaseProcessor):
    def extract(self) -> str:
        doc = DocxDocument(self.job.file_path)
        parts = [f"# {self.job.filename}"]

        for child in doc.element.body:
            tag = child.tag

            if tag == qn("w:p"):
                text = _get_para_text(child)
                if not text:
                    continue
                style_id = _get_style_id(child)
                prefix = _HEADING_STYLES.get(style_id, "")
                parts.append(f"{prefix} {text}" if prefix else text)

            elif tag == qn("w:tbl"):
                rows = _get_table_rows(child)
                if rows:
                    parts.append(self._table_to_markdown(rows))

        return "\n\n".join(parts)

    def summarise(self, text: str, db) -> dict:
        summary_text = text[:12000] if len(text) > 12000 else text

        prompt = f"""You are a document analyst. Analyse the following document text and return ONLY valid JSON.
No preamble, no markdown code blocks, just raw JSON.

Return this exact structure:
{{
  "title": "document title or filename",
  "document_type": "report|contract|paper|manual|other",
  "summary": "2-3 sentence summary",
  "key_points": ["point 1", "point 2"],
  "entities": ["company names, person names, product names mentioned"]
}}

Document text:
{summary_text}
"""
        return self._call_gemini_json(prompt, db)
