import os
os.environ.update(TELEGRAM_API_ID='1', TELEGRAM_API_HASH='x', TELEGRAM_SESSION='', MAKE_API_KEY='x')
import asyncio
from types import SimpleNamespace
from fastapi import HTTPException
from telethon.tl.types import MessageEntityBlockquote, MessageEntitySpoiler

from main import (
    TELEGRAM_PARSE_MODE,
    PublishRequest,
    build_caption,
    build_keyboard,
    normalize_media,
    publish,
    publish_link_preview_post,
    visible_text_length,
)

payload = PublishRequest(profile_id='1', photo='https://a.example/1.jpg\nhttps://a.example/2.jpg\nhttps://a.example/3.jpg', text='<span class="tg-bold">Жирний</span><br><blockquote expandable>Цитата</blockquote><tg-spoiler>Секрет</tg-spoiler>🙂', buttons=[{'text':'Старт','url':'https://example.com/start'}, {'text':'Фініш','url':'https://example.com/end'}])
assert len(normalize_media(payload)) == 3
caption = build_caption(payload)
assert caption == '<b>Жирний</b>\n<blockquote expandable>Цитата</blockquote>\n<tg-spoiler>Секрет</tg-spoiler>🙂'
text, entities = TELEGRAM_PARSE_MODE.parse(caption)
assert text == 'Жирний\nЦитата\nСекрет🙂'
assert any(isinstance(entity, MessageEntityBlockquote) and entity.collapsed for entity in entities)
assert any(isinstance(entity, MessageEntitySpoiler) for entity in entities)
assert visible_text_length(caption) == len('Жирний\nЦитата\nСекрет🙂')
assert visible_text_length('<b>' + ('А' * 1025) + '</b>') == 1025
assert build_keyboard(payload) == {'inline_keyboard': [[{'text':'Старт','url':'https://example.com/start'}, {'text':'Фініш','url':'https://example.com/end'}]]}

long_album = PublishRequest(
    profile_id='2',
    media=['https://a.example/1.jpg', 'https://a.example/2.jpg'],
    text='А' * 1025,
)
try:
    asyncio.run(publish(long_album, authorization='Bearer x'))
except HTTPException as exc:
    assert exc.status_code == 422
    assert exc.detail == 'Posts longer than 1024 visible characters may contain only one media item.'
else:
    raise AssertionError('Long posts with multiple media must be rejected before publishing')

class FakeTelegram:
    def __init__(self):
        self.request = None

    async def get_input_entity(self, channel):
        return channel

    def build_reply_markup(self, buttons):
        return buttons

    async def __call__(self, request):
        self.request = request
        return SimpleNamespace()

    def _get_response_message(self, request, result, peer):
        return SimpleNamespace(id=123)

fake = FakeTelegram()
import main
original_client = main.client
main.client = fake
try:
    result = asyncio.run(
        publish_link_preview_post(
            '@test',
            'https://example.com/photo.jpg?x=1&y=2',
            '<b>Довгий текст</b>',
            None,
        )
    )
finally:
    main.client = original_client
assert result.id == 123
assert fake.request.media.url == 'https://example.com/photo.jpg?x=1&y=2'
assert fake.request.media.force_large_media is True
assert fake.request.invert_media is True
assert fake.request.message == 'Довгий текст'
print('publisher helper tests passed')
