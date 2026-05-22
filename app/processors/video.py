from app.processors.base import BaseProcessor


class VideoAudioProcessor(BaseProcessor):
    def extract(self) -> str:
        return ""

    def summarise(self, text: str, db) -> dict:
        raise NotImplementedError("VideoAudioProcessor will be implemented on Day 4")
