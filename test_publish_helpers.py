import os
os.environ.update(TELEGRAM_API_ID='1', TELEGRAM_API_HASH='x', TELEGRAM_SESSION='', MAKE_API_KEY='x')
from telethon.tl.types import MessageEntityBlockquote, MessageEntitySpoiler

from main import (
    TELEGRAM_PARSE_MODE,
    PublishRequest,
    build_caption,
    build_keyboard,
    normalize_media,
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
print('publisher helper tests passed')
