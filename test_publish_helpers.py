import os
os.environ.update(TELEGRAM_API_ID='1', TELEGRAM_API_HASH='x', TELEGRAM_SESSION='', MAKE_API_KEY='x')
from main import PublishRequest, build_caption, build_keyboard, normalize_media

payload = PublishRequest(profile_id='1', photo='https://a.example/1.jpg\nhttps://a.example/2.jpg\nhttps://a.example/3.jpg', text='<span class="tg-bold">Жирний</span><br><blockquote>Цитата</blockquote>🙂', buttons=[{'text':'Старт','url':'https://example.com/start'}, {'text':'Фініш','url':'https://example.com/end'}])
assert len(normalize_media(payload)) == 3
assert build_caption(payload) == '<b>Жирний</b><br>Цитата'
assert build_keyboard(payload) == {'inline_keyboard': [[{'text':'Старт','url':'https://example.com/start'}, {'text':'Фініш','url':'https://example.com/end'}]]}
print('publisher helper tests passed')
