"""Tutor.ua Telegram publisher.

The endpoint accepts both the original one-photo payload and the B2B payload
with up to three media URLs, Telegram-safe HTML and inline buttons.
"""
from __future__ import annotations

import html
import os
import re
import secrets
from html.parser import HTMLParser
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from telethon import Button, TelegramClient
from telethon.errors import MessageNotModifiedError
from telethon.extensions import html as telethon_html
from telethon.helpers import add_surrogate
from telethon.sessions import StringSession
from telethon.tl.types import MessageEntitySpoiler

API_ID = int(os.environ["TELEGRAM_API_ID"])
API_HASH = os.environ["TELEGRAM_API_HASH"]
# A user session is sufficient for regular channel posts. Telegram permits
# inline keyboards only for bot accounts, so B2B may optionally use a bot
# token without changing the shared B2C session.
SESSION_STRING = os.getenv("TELEGRAM_SESSION", "")
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
MAKE_API_KEY = os.environ["MAKE_API_KEY"]
DEFAULT_CHANNEL = os.getenv("TELEGRAM_CHANNEL", "@tutortutor")

app = FastAPI(title="Tutor.ua B2B Telegram Publisher")
client: TelegramClient | None = None


def telegram_client() -> TelegramClient:
    if client is None:
        raise RuntimeError("Telegram client is not connected.")
    return client


class InlineButton(BaseModel):
    text: str = Field(min_length=1, max_length=64)
    url: HttpUrl


class PublishRequest(BaseModel):
    # `channel` is optional only to preserve the original service contract.
    channel: str | None = None
    profile_id: str | int

    # Legacy input. It may contain one URL or one URL per line.
    photo: str | None = None
    media: list[HttpUrl] = Field(default_factory=list, max_length=3)
    photos: list[HttpUrl] = Field(default_factory=list, max_length=3)

    # The B2B path sends `text`; the remaining fields are legacy profile data.
    text: str = ""
    about: str = ""
    contacts: str | None = None
    contact_url: HttpUrl | None = None
    allow_comments: bool = False

    buttons: list[InlineButton] = Field(default_factory=list, max_length=2)
    inline_buttons: list[InlineButton] = Field(default_factory=list, max_length=2)
    inline_keyboard: list[list[InlineButton]] = Field(default_factory=list, max_length=2)

    name: str | None = None
    subject: str | None = None
    features: str | None = None
    age: str | None = None
    individual_lessons: str | None = None
    group_lessons: str | None = None
    other_lessons: str | None = None
    resources: str | None = None
    hashtags: str | None = None
    footer: str | None = None


def normalize_media(payload: PublishRequest) -> list[str]:
    """Return at most three unique media URLs across all supported inputs."""
    raw: list[Any] = list(payload.media or payload.photos)
    if not raw and payload.photo:
        raw = [line.strip() for line in payload.photo.splitlines() if line.strip()]

    media: list[str] = []
    for item in raw:
        url = str(item).strip()
        if url and url not in media:
            media.append(url)
        if len(media) == 3:
            break
    return media


class TelegramHTML(HTMLParser):
    """Sanitize rich text while retaining Telegram-supported formatting."""

    _span_tags = {
        "tg-bold": "b",
        "tg-italic": "i",
        "tg-spoiler": "tg-spoiler",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[tuple[str, str | None]] = []

    def _break(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_map = {name.lower(): value or "" for name, value in attrs}
        output: str | None = None
        if tag in {"b", "strong"}:
            output = "b"
        elif tag in {"i", "em"}:
            output = "i"
        elif tag in {"u", "ins"}:
            output = "u"
        elif tag in {"s", "strike", "del"}:
            output = "s"
        elif tag == "tg-spoiler":
            output = "tg-spoiler"
        elif tag == "span":
            classes = set(attrs_map.get("class", "").lower().split())
            output = next((mapped for css, mapped in self._span_tags.items() if css in classes), None)
        elif tag == "blockquote":
            output = "blockquote"
            collapsed = "expandable" in attrs_map or "expandable" in attrs_map.get("class", "").lower().split()
            self.stack.append((tag, output))
            self.parts.append("<blockquote expandable>" if collapsed else "<blockquote>")
            return
        elif tag == "a":
            href = attrs_map.get("href", "")
            if href.lower().startswith(("https://", "http://", "tg://")):
                self.parts.append(f'<a href="{html.escape(href, quote=True)}">')
                self.stack.append((tag, "a"))
                return
        elif tag == "br":
            self.parts.append("\n")
            return
        elif tag in {"p", "div"}:
            self._break()
        self.stack.append((tag, output))
        if output:
            self.parts.append(f"<{output}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, -1, -1):
            opened, output = self.stack[index]
            if opened != tag:
                continue
            del self.stack[index:]
            if output:
                self.parts.append(f"</{output}>")
            if tag in {"p", "div", "blockquote"}:
                self._break()
            return

    def handle_data(self, data: str) -> None:
        # Keep ordinary Unicode emoji. They work for every Telegram user and
        # do not require Premium or a custom-emoji document ID.
        self.parts.append(html.escape(data))

    def result(self) -> str:
        value = "".join(self.parts)
        value = re.sub(r"\(?\s*Про\s+мене\s*\)?\s*:?", "", value, flags=re.I)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return value.strip(" \n")


def normalize_html(value: str) -> str:
    parser = TelegramHTML()
    parser.feed(value or "")
    parser.close()
    return parser.result()


class SpoilerOffsets(HTMLParser):
    """Collect UTF-16 offsets Telethon's stock HTML parser omits."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_offset = 0
        self.starts: list[int] = []
        self.entities: list[MessageEntitySpoiler] = []
        self.collapsed_quotes: list[tuple[int, int]] = []
        self.quote_starts: list[int] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "tg-spoiler":
            self.starts.append(self.text_offset)
        elif tag == "blockquote" and any(name.lower() == "expandable" for name, _ in attrs):
            self.quote_starts.append(self.text_offset)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "tg-spoiler" and self.starts:
            start = self.starts.pop()
            if self.text_offset > start:
                self.entities.append(MessageEntitySpoiler(offset=start, length=self.text_offset - start))
        elif tag == "blockquote" and self.quote_starts:
            start = self.quote_starts.pop()
            if self.text_offset > start:
                self.collapsed_quotes.append((start, self.text_offset - start))

    def handle_data(self, data: str) -> None:
        self.text_offset += len(add_surrogate(data))


class TelegramParseMode:
    """Telethon HTML plus Bot API-compatible ``tg-spoiler`` support."""

    @staticmethod
    def parse(value: str):
        text, entities = telethon_html.parse(value)
        parser = SpoilerOffsets()
        parser.feed(value)
        parser.close()
        entities.extend(parser.entities)
        collapsed = set(parser.collapsed_quotes)
        for entity in entities:
            if type(entity).__name__ == "MessageEntityBlockquote" and (entity.offset, entity.length) in collapsed:
                entity.collapsed = True
        entities.sort(key=lambda entity: entity.offset)
        return text, entities

    @staticmethod
    def unparse(text: str, entities):
        return telethon_html.unparse(text, entities)


TELEGRAM_PARSE_MODE = TelegramParseMode()


def build_caption(payload: PublishRequest) -> str:
    if payload.text:
        caption = payload.text
    else:
        # Backward-compatible profile publication. Keep the actual "about"
        # copy but omit the category heading requested by the publication flow.
        parts = []
        if payload.name:
            parts.append(f"<b>{payload.name}</b>")
        if payload.subject:
            parts.append(f"<b>Предмет:</b> {payload.subject}")
        if payload.features:
            parts.append(f"<b>Особливості:</b><br>{payload.features}")
        if payload.age:
            parts.append(f"<b>Вік:</b> {payload.age}")
        if payload.about:
            parts.append(payload.about)
        if payload.individual_lessons:
            parts.append(f"<b>Індивідуальні заняття:</b><br>{payload.individual_lessons}")
        if payload.group_lessons:
            parts.append(f"<b>Групові заняття:</b><br>{payload.group_lessons}")
        if payload.other_lessons:
            parts.append(f"<b>Інші заняття:</b><br>{payload.other_lessons}")
        if payload.resources:
            parts.append(f"<b>Додаткові ресурси:</b><br>{payload.resources}")
        if payload.hashtags:
            parts.append(payload.hashtags)
        if payload.contacts:
            parts.append(payload.contacts)
        if payload.footer:
            parts.append(payload.footer)
        if payload.contact_url:
            parts.append(f'<a href="{payload.contact_url}">ЗВ’ЯЗАТИСЯ</a>')
        caption = "<br><br>".join(parts)
    return normalize_html(caption)


def build_keyboard(payload: PublishRequest) -> dict[str, list[list[dict[str, str]]]] | None:
    source: Any = payload.inline_keyboard or payload.inline_buttons or payload.buttons
    if not source:
        return None
    rows = source if isinstance(source[0], list) else [source]
    normalized = [
        [{"text": button.text, "url": str(button.url)} for button in row]
        for row in rows
    ]
    if sum(len(row) for row in normalized) > 2:
        raise HTTPException(status_code=400, detail="At most two inline buttons are allowed.")
    return {"inline_keyboard": normalized}


def telethon_buttons(keyboard: dict[str, list[list[dict[str, str]]]] | None):
    if not keyboard:
        return None
    return [[Button.url(item["text"], item["url"]) for item in row] for row in keyboard["inline_keyboard"]]


async def publish_single_post(channel: str, media: str | None, caption: str, buttons):
    telegram = telegram_client()
    if media:
        return await telegram.send_file(channel, file=media, caption=caption, parse_mode=TELEGRAM_PARSE_MODE, buttons=buttons)
    return await telegram.send_message(
        channel, message=caption, parse_mode=TELEGRAM_PARSE_MODE, link_preview=False, buttons=buttons
    )


async def publish_media_group(channel: str, media: list[str], caption: str, buttons):
    # Telegram creates albums as a separate RPC. It cannot receive reply markup
    # in the initial call, so add URL buttons to the captioned first message.
    captions = [caption] + [""] * (len(media) - 1)
    telegram = telegram_client()
    messages = await telegram.send_file(channel, file=media, caption=captions, parse_mode=TELEGRAM_PARSE_MODE)
    first = messages[0] if isinstance(messages, list) else messages
    if buttons:
        try:
            # Telegram needs the existing caption when reply markup is added
            # to the first item of an album. Passing only buttons can produce
            # MessageNotModified after the album has already been published.
            await telegram.edit_message(
                channel, first.id, caption, parse_mode=TELEGRAM_PARSE_MODE, buttons=buttons
            )
        except MessageNotModifiedError:
            # The requested caption and keyboard are already present. Treat
            # this as success so Make does not retry and create duplicates.
            pass
        except Exception:
            # Publishing an album and then failing to add its keyboard is a
            # partial write. Roll it back so a safe retry cannot duplicate it.
            published = messages if isinstance(messages, list) else [messages]
            await telegram.delete_messages(channel, [message.id for message in published])
            raise
    return messages


async def assert_button_capability(buttons) -> None:
    if not buttons:
        return
    identity = await telegram_client().get_me()
    if not getattr(identity, "bot", False):
        raise HTTPException(
            status_code=422,
            detail="Inline buttons require a bot-authorized TELEGRAM_SESSION. A user MTProto session can publish media but cannot attach keyboards.",
        )


@app.on_event("startup")
async def startup():
    global client
    # A bot token gives Telegram permission to attach inline keyboards. Use an
    # ephemeral session here: the token itself is the durable credential.
    session = StringSession() if BOT_TOKEN else StringSession(SESSION_STRING)
    client = TelegramClient(session, API_ID, API_HASH)
    if BOT_TOKEN:
        await client.start(bot_token=BOT_TOKEN)
        return
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("Telegram session is not authorized.")


@app.on_event("shutdown")
async def shutdown():
    if client:
        await client.disconnect()


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/publish")
async def publish(payload: PublishRequest, authorization: str | None = Header(default=None)):
    expected = f"Bearer {MAKE_API_KEY}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")

    channel = payload.channel or DEFAULT_CHANNEL
    media = normalize_media(payload)
    caption = build_caption(payload)
    keyboard = build_keyboard(payload)

    # Telegram accepts up to 1,024 characters for a media caption and 4,096
    # for a text-only message. This avoids partial album creation.
    limit = 1024 if media else 4096
    if len(re.sub(r"<[^>]+>", "", caption)) > limit:
        raise HTTPException(status_code=400, detail=f"Text too long: max {limit} visible characters for this post.")

    try:
        buttons = telethon_buttons(keyboard)
        await assert_button_capability(buttons)
        if len(media) > 1:
            messages = await publish_media_group(channel, media, caption, buttons)
            first = messages[0] if isinstance(messages, list) else messages
            media_mode = "album"
        else:
            first = await publish_single_post(channel, media[0] if media else None, caption, buttons)
            media_mode = "single_media" if media else "text"
        return {
            "success": True,
            "message_id": first.id,
            "profile_id": str(payload.profile_id),
            "media_count": len(media),
            "media_mode": media_mode,
            "media_position": "above_text",
            "parse_mode": "HTML",
            "blockquote": "<blockquote" in caption,
            "spoiler": "<tg-spoiler>" in caption,
            "unicode_emojis": True,
            "custom_emojis": False,
            "buttons_count": sum(len(row) for row in (keyboard or {"inline_keyboard": []})["inline_keyboard"]),
            "allow_comments": payload.allow_comments,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
