import asyncio
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from database import Database


class MemeGenerator:
    def __init__(self, database: Database, output_dir: Path) -> None:
        self.database = database
        self.output_dir = output_dir
        self.font_candidates = [
            Path("C:/Windows/Fonts/impact.ttf"),
            Path("C:/Windows/Fonts/arialbd.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ]

    async def create(self, guild_id: int) -> Path | None:
        messages = await self.database.get_messages(guild_id, limit=200)
        if not messages:
            return None
        phrase = random.choice(messages).strip()[:140]
        return await asyncio.to_thread(self._render, phrase)

    def _render(self, phrase: str) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        width, height = 1200, 800
        image = Image.new("RGB", (width, height), (22, 24, 29))
        draw = ImageDraw.Draw(image)
        for y in range(height):
            shade = int(32 + 18 * y / height)
            draw.line((0, y, width, y), fill=(shade, shade + 3, shade + 9))
        draw.rectangle((45, 45, width - 45, height - 45), outline=(245, 190, 66), width=5)
        font = self._font(54)
        small = self._font(24)
        lines = self._wrap(draw, phrase, font, width - 180)
        total_height = len(lines) * 68
        top = max(130, (height - total_height) // 2)
        for index, line in enumerate(lines):
            box = draw.textbbox((0, 0), line, font=font, stroke_width=2)
            x = (width - (box[2] - box[0])) // 2
            y = top + index * 68
            draw.text((x + 3, y + 3), line, font=font, fill=(0, 0, 0), stroke_width=2, stroke_fill=(0, 0, 0))
            draw.text((x, y), line, font=font, fill=(255, 255, 255), stroke_width=2, stroke_fill=(0, 0, 0))
        draw.text((70, height - 90), "ДИРЕКТОР ЧАТ // SERVER EDITION", font=small, fill=(245, 190, 66))
        path = self.output_dir / "latest-meme.png"
        image.save(path, format="PNG")
        return path

    def _font(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        for candidate in self.font_candidates:
            if candidate.exists():
                return ImageFont.truetype(str(candidate), size)
        return ImageFont.load_default()

    @staticmethod
    def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines or ["Система пока молчит"]
