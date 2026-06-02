"""
Image file processor (PNG, JPG, JPEG, WEBP).

Sends the image to Groq Vision (llama-4-scout) with _EXTRACTION_PROMPT, which
asks the model to OCR all visible text, describe charts and diagrams, and
extract structured data from forms and business cards.

The extracted markdown is wrapped in a '# filename' heading and stored as
_chunk_text for the hierarchical chunker.  This same _EXTRACTION_PROMPT and
the same _call_vision_markdown() method are reused by VideoProcessor when
processing individual video frames so the two pipelines stay consistent.
"""

from pathlib import Path

from app.processors.base import BaseProcessor

_MIME_MAP = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

_EXTRACTION_PROMPT = """Extract ALL content from this image as Markdown.

Include everything visible:
- All text exactly as written (OCR)
- Tables formatted as proper markdown tables with | col | col | headers
- Charts or graphs: describe type, axes, legend, and key data points/values
- Forms or structured layouts: preserve the field names and values
- Business cards: Name, Title, Company, Email, Phone, Address, Website
- Diagrams, flowcharts: describe the structure and labels
- Any other text or visual content

Output clean Markdown only. No preamble, no explanation."""


class ImageProcessor(BaseProcessor):
    def extract(self) -> str:
        # Extraction requires a DB connection for logging, so it happens in summarise
        return ""

    def summarise(self, text: str, db) -> dict:
        ext = Path(self.job.file_path).suffix.lower()
        mime_type = _MIME_MAP.get(ext, "image/jpeg")

        with open(self.job.file_path, "rb") as f:
            image_data = f.read()

        markdown = self._call_vision_markdown(_EXTRACTION_PROMPT, image_data, mime_type, db)

        # Build a heading so the chunker has a section label
        full_markdown = f"# {self.job.filename}\n\n{markdown}" if markdown.strip() else ""

        return {
            "_chunk_text": full_markdown,
            "image_type": "image",
            "filename": self.job.filename,
            "summary": f"Image content extracted from {self.job.filename}",
            "content_preview": markdown[:300],
        }
