import random
import re

import markovify

from database import Database

STYLE_WORDS = {
    "friendly": [
        "привет", "дружище", "супер", "круто", "хорошо", "друг", "давай",
        "ладно", "молодец", "согласен", "всё норм", "пожалуйста", "всем",
    ],
    "jokey": [
        "смешно", "мем", "почему", "типо", "ну", "хах", "ахах", "шутка",
        "серьезно", "как будто", "вот это", "неожиданно", "топ", "парадокс",
    ],
    "toxic": [
        "бред", "снова", "серьезно", "почему", "опять", "ну нет", "этот вайб",
        "тут уже", "вот это", "не понимаю", "всё пиздец", "всегда так",
    ],
}

STYLE_PREFIXES = {
    "friendly": ["ну что", "ладно", "смотри", "дружище", "с тобой согласен", "давай так"],
    "jokey": ["серьезно", "как будто", "вот это", "почему нет", "типо", "ну и что"],
    "toxic": ["снова", "блин", "серьезно", "это уже", "почему опять", "ну и отлично"],
}

STYLE_ENDINGS = {
    "friendly": ["и это прям приятно.", "классно, что так и есть.", "вот это уже вайб.", "да, это логично."],
    "jokey": ["как будто кто-то запустил мем вместо логики.", "оба варианта в итоге смешные.", "теперь это уже не шутка, это стиль.", "вот это уже уровень."],
    "toxic": ["и почему мы всё это терпим.", "как будто этот чат живёт на хардмоде.", "надеюсь, это не будет новой нормой.", "ну это уже перебор."],
}


class ChatGenerator:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.models: dict[int, markovify.Text] = {}
        self.model_sizes: dict[int, int] = {}

    async def _model(self, guild_id: int) -> markovify.Text | None:
        messages = await self.database.get_messages(guild_id)
        if len(messages) < 3:
            return None
        size = len(messages)
        if guild_id not in self.models or self.model_sizes.get(guild_id) != size:
            corpus = "\n".join(messages)
            self.models[guild_id] = markovify.NewlineText(corpus, state_size=2, well_formed=False)
            self.model_sizes[guild_id] = size
        return self.models[guild_id]

    async def analyze_style(self, guild_id: int) -> str:
        messages = await self.database.get_messages(guild_id, limit=2000)
        if not messages:
            return "jokey"
        scores = {style: 0 for style in STYLE_WORDS}
        for text in messages:
            lowered = text.lower()
            for style, words in STYLE_WORDS.items():
                scores[style] += sum(1 for word in words if word in lowered)
        if any(ch in "😂🤣😅😆" for message in messages for ch in message):
            scores["jokey"] += 2
        chosen = max(scores, key=scores.get)
        custom = await self.database.get_tone(guild_id, chosen)
        return custom if custom in scores else chosen

    async def generate(self, guild_id: int, prompt: str = "") -> str | None:
        messages = await self.database.get_messages(guild_id)
        if not messages:
            return None
        style = await self.analyze_style(guild_id)
        model = await self._model(guild_id)
        if model is not None:
            for _ in range(10):
                sentence = model.make_sentence(tries=40)
                if sentence:
                    result = self._clean(sentence)
                    if 6 <= len(result) <= 200 and result.lower() != prompt.lower():
                        return self._apply_style(result, style)[:220]
        return self._template_from_messages(messages, style, prompt)

    async def generate_poll(self, guild_id: int) -> str | None:
        messages = await self.database.get_messages(guild_id, limit=200)
        if len(messages) < 6:
            return None
        options = random.sample(messages, k=min(3, len(messages)))
        options = [self._clean(option)[:70] for option in options]
        options = [option for option in options if option]
        if len(options) < 2:
            return None
        lines = ["**Внезапный опрос от директора чата:**", "Что сегодня звучит убедительнее?"]
        lines.extend(f"{index}. {option}" for index, option in enumerate(options, start=1))
        return "\n".join(lines)

    def _apply_style(self, text: str, style: str) -> str:
        prefix = random.choice(STYLE_PREFIXES.get(style, STYLE_PREFIXES["jokey"]))
        suffix = random.choice(STYLE_ENDINGS.get(style, STYLE_ENDINGS["jokey"]))
        return self._clean(f"{prefix}, {text.lower().capitalize()} {suffix}")

    def _template_from_messages(self, messages: list[str], style: str, prompt: str) -> str | None:
        pool = [self._clean(m) for m in messages if len(self._clean(m)) > 8]
        if not pool:
            return None
        sample = random.sample(pool, k=min(6, len(pool)))
        words: list[str] = []
        for phrase in sample:
            tokens = re.findall(r"[А-Яа-яЁёA-Za-z]{3,}", phrase)
            words.extend(tokens)
        if not words:
            return None
        seed = random.sample(words, k=min(8, len(words)))
        if prompt:
            prompt_words = re.findall(r"[А-Яа-яЁёA-Za-z]{3,}", prompt)
            if prompt_words:
                seed = random.sample(prompt_words + seed, k=min(10, len(prompt_words) + len(seed)))
        sentence = " ".join(seed)
        prefix = random.choice(STYLE_PREFIXES.get(style, STYLE_PREFIXES["jokey"]))
        suffix = random.choice(STYLE_ENDINGS.get(style, STYLE_ENDINGS["jokey"]))
        return self._clean(f"{prefix}, {sentence} — {suffix}")[:220]

    @staticmethod
    def _clean(text: str) -> str:
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"<@&?\d+>|@(?:everyone|here)", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+", " ", text).strip()
        return text
