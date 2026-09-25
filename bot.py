import asyncio
import logging
import os
import random
import re
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

from database import Database
from generator import ChatGenerator
from meme import MemeGenerator

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("director-chat")

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
GUILD_ID = int(os.getenv("GUILD_ID", "1541744004188868689"))
TARGET_CHANNEL_ID = int(os.getenv("TARGET_CHANNEL_ID", "1541744004708966442"))
DEFAULT_CHANCE = float(os.getenv("DEFAULT_REPLY_CHANCE", "2"))
DATA_DIR = Path(os.getenv("DATA_DIR", "data"))

URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
COMMAND_RE = re.compile(r"^[/!?.]", re.IGNORECASE)

intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.guilds = True


class DirectorChatBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix="!", intents=intents)
        self.database = Database(DATA_DIR / "director_chat.sqlite3")
        self.generator = ChatGenerator(self.database)
        self.memes = MemeGenerator(self.database, DATA_DIR / "memes")
        self.ready_once = False
        self.history_loaded = False

    async def setup_hook(self) -> None:
        await self.database.connect()
        self.random_poll_loop.start()
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        logger.info("Slash-команды синхронизированы для guild %s", GUILD_ID)

    async def load_chat_history(self) -> None:
        if self.history_loaded:
            return
        guild = self.get_guild(GUILD_ID)
        if guild is None:
            logger.warning("Guild %s не найден, история чата не загружена.", GUILD_ID)
            return
        total = 0
        for channel in guild.text_channels:
            try:
                async for message in channel.history(limit=2000):
                    if message.author.bot or not message.guild:
                        continue
                    clean_text = self._clean_message(message)
                    if not clean_text:
                        continue
                    await self.database.save_message(message.guild.id, message.channel.id, clean_text)
                    total += 1
            except (discord.Forbidden, discord.HTTPException):
                logger.warning("Нет доступа к каналу %s для чтения истории", channel.id)
        self.history_loaded = True
        logger.info("Загружено %s исторических сообщений для guild %s", total, GUILD_ID)

    async def close(self) -> None:
        self.random_poll_loop.cancel()
        await self.database.close()
        await super().close()

    async def on_ready(self) -> None:
        if not self.ready_once:
            logger.info("Бот вошёл как %s", self.user)
            self.ready_once = True
            await self.load_chat_history()

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        if message.guild.id != GUILD_ID:
            return

        clean_text = self._clean_message(message)
        if clean_text:
            await self.database.save_message(
                guild_id=message.guild.id,
                channel_id=message.channel.id,
                text=clean_text,
            )
            for attachment in message.attachments:
                if attachment.content_type and attachment.content_type.startswith("image/"):
                    await self.database.save_image(message.guild.id, attachment.url)

        mentioned = self.user is not None and self.user in message.mentions
        if not mentioned and (not clean_text or message.channel.id != TARGET_CHANNEL_ID):
            return

        if not mentioned:
            chance = await self.database.get_chance(message.guild.id, DEFAULT_CHANCE)
            if random.random() * 100 >= chance:
                return

        prompt = clean_text or message.content[:300]
        response = await self.generator.generate(message.guild.id, prompt)
        if response:
            await message.reply(response, mention_author=False)

    @staticmethod
    def _clean_message(message: discord.Message) -> str:
        text = message.content.strip()
        if not text or COMMAND_RE.match(text) or URL_RE.search(text):
            return ""
        text = re.sub(r"<@&?\d+>", "", text)
        text = re.sub(r"@(?:everyone|here)\b", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:1000]

    @tasks.loop(hours=6)
    async def random_poll_loop(self) -> None:
        channel = self.get_channel(TARGET_CHANNEL_ID)
        if not isinstance(channel, discord.TextChannel):
            return
        guild = channel.guild
        poll = await self.generator.generate_poll(guild.id)
        if poll:
            await channel.send(poll)

    @random_poll_loop.before_loop
    async def before_random_poll_loop(self) -> None:
        await self.wait_until_ready()


bot = DirectorChatBot()


async def defer_interaction(interaction: discord.Interaction) -> bool:
    try:
        await interaction.response.defer()
    except discord.NotFound:
        logger.warning("Discord interaction %s уже истёк", interaction.id)
        return False
    return True


@bot.tree.command(name="help", description="Показать возможности директора чата")
async def help_command(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        "**Директор чата** умеет запоминать анонимизированные фразы этого сервера, "
        "отвечать на упоминания, иногда встревать сам, делать мемы и опросы.\n\n"
        "`/say` — сгенерировать фразу\n"
        "`/meme` — сделать демотиватор\n"
        "`/tone` — выбрать стиль: шутливый, токсичный или дружелюбный\n"
        "`/jail @пользователь` — шутливо отправить пользователя в тюрьму\n"
        "`/chance 0-100` — шанс случайного ответа (только админ)\n"
        "Упомяни бота, чтобы получить ответ сразу.",
        ephemeral=True,
    )


@bot.tree.command(name="say", description="Сгенерировать фразу в стиле чата")
async def say_command(interaction: discord.Interaction) -> None:
    if not interaction.guild:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return
    if not await defer_interaction(interaction):
        return
    text = await bot.generator.generate(interaction.guild.id, "")
    await interaction.followup.send(text or "Пока нечего сказать: сначала нужно немного поговорить.")


@bot.tree.command(name="meme", description="Создать случайный демотиватор")
async def meme_command(interaction: discord.Interaction) -> None:
    if not interaction.guild:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return
    if not await defer_interaction(interaction):
        return
    path = await bot.memes.create(interaction.guild.id)
    if path is None:
        await interaction.followup.send("Нужны хотя бы несколько фраз в базе для мема.")
        return
    await interaction.followup.send(file=discord.File(path))


chance_number = app_commands.Range[int, 0, 100]


@bot.tree.command(name="chance", description="Настроить шанс случайного ответа")
@app_commands.describe(value="Процент от 0 до 100")
@app_commands.checks.has_permissions(administrator=True)
async def chance_command(interaction: discord.Interaction, value: chance_number) -> None:
    if not interaction.guild:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return
    await bot.database.set_chance(interaction.guild.id, float(value))
    await interaction.response.send_message(f"Шанс случайного ответа установлен: {value}%.", ephemeral=True)


@bot.tree.command(name="tone", description="Настроить стиль общения бота")
@app_commands.describe(mode="Выбери: шутливый, токсичный или дружелюбный")
@app_commands.choices(
    mode=[
        app_commands.Choice(name="Шутливый", value="шутливый"),
        app_commands.Choice(name="Токсичный", value="токсичный"),
        app_commands.Choice(name="Дружелюбный", value="дружелюбный"),
    ]
)
@app_commands.checks.has_permissions(administrator=True)
async def tone_command(
    interaction: discord.Interaction,
    mode: app_commands.Choice[str],
) -> None:
    if not interaction.guild:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return
    mapping = {
        "шутливый": "jokey",
        "токсичный": "toxic",
        "дружелюбный": "friendly",
    }
    tone = mapping.get(mode.value, "jokey")
    await bot.database.set_tone(interaction.guild.id, tone)
    await interaction.response.send_message(f"Стиль общения бота установлен: {mode.value}.", ephemeral=True)


@bot.tree.command(name="jail", description="Шутливо посадить пользователя в тюрьму")
@app_commands.describe(target="Кого отправить в 'тюрьму'?")
async def jail_command(interaction: discord.Interaction, target: discord.Member) -> None:
    if not interaction.guild:
        await interaction.response.send_message("Команда доступна только на сервере.", ephemeral=True)
        return
    if interaction.user == target:
        await interaction.response.send_message("Сам себя в тюрьму не отправишь, это уже странно.", ephemeral=True)
        return
    await interaction.response.send_message(
        f"{interaction.user.mention} вкачал пользователя {target.mention} за такие слова."
        f"\nПроблемы с речью? Нет, просто у него слишком активный словарь.",
        allowed_mentions=discord.AllowedMentions(users=True),
    )


@chance_command.error
async def chance_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    if isinstance(error, app_commands.errors.MissingPermissions):
        message = "Настраивать шанс может только администратор."
    else:
        logger.exception("Ошибка команды chance", exc_info=error)
        message = "Не удалось изменить настройку."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


@tone_command.error
async def tone_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
    if isinstance(error, app_commands.errors.MissingPermissions):
        message = "Настраивать стиль может только администратор."
    else:
        logger.exception("Ошибка команды tone", exc_info=error)
        message = "Не удалось изменить стиль."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("DISCORD_TOKEN не задан. Скопируйте .env.example в .env и укажите новый токен.")
    asyncio.run(bot.start(TOKEN))
