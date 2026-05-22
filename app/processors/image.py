from pathlib import Path

from app.processors.base import BaseProcessor


class ImageProcessor(BaseProcessor):
    def extract(self) -> str:
        return ""

    def summarise(self, text: str, db) -> dict:
        ext = Path(self.job.file_path).suffix.lower()
        mime_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }
        mime_type = mime_map.get(ext, "image/jpeg")

        with open(self.job.file_path, "rb") as f:
            image_data = f.read()

        prompt = """Analyse this image carefully. Return ONLY valid JSON with no preamble.

Return this exact structure:
{
  "image_type": "business_card|document|screenshot|chart|photo|whiteboard|other",
  "ocr_text": "all visible text extracted from the image verbatim",
  "language": "language of the text",
  "business_card": {
    "name": null,
    "title": null,
    "company": null,
    "email": null,
    "phone": null,
    "address": null,
    "website": null
  },
  "summary": "one sentence describing what this image contains"
}

If not a business card, set business_card fields to null.
"""
        return self._call_gemini_vision_json(prompt, image_data, mime_type, db)
