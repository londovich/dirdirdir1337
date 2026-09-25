import asyncio
import tempfile
from pathlib import Path

from database import Database
from generator import ChatGenerator
from meme import MemeGenerator


async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Database(Path(directory) / "test.sqlite3")
        await database.connect()
        try:
            for text in ["это тестовая фраза", "ещё одна фраза для генерации", "сегодня всё работает отлично", "проверяем мем и опрос", "вот ещё один вариант", "система работает"]:
                await database.save_message(1, 2, text)
            generator = ChatGenerator(database)
            assert await generator.generate(1)
            assert await generator.generate_poll(1)
            meme = await MemeGenerator(database, Path(directory) / "memes").create(1)
            assert meme and meme.exists()
        finally:
            await database.close()


if __name__ == "__main__":
    asyncio.run(main())
