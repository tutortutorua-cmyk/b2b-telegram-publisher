# Tutor.ua B2B Telegram Publisher

`POST /publish` receives a B2B Make.com payload and publishes it through a
dedicated Telegram MTProto account. It is intentionally isolated from the
existing tutor-profile publisher.

## Supported publication formats

- legacy `photo` with one URL or one URL per line;
- `media` or `photos` with up to three URLs;
- one URL publishes one media post; two or three publish a Telegram album;
- HTML: `<b>`, `<i>`, `<u>`, `<s>`, `<a href>`, `<tg-spoiler>`,
  `<blockquote>` and `<blockquote expandable>`;
- `<br>`, `<p>` and `<div>` are converted to real Telegram newlines;
- ordinary Unicode emoji are preserved (Premium custom emoji are not used);
- up to two URL buttons in `buttons`, `inline_buttons`, or `inline_keyboard`.

`photo` remains supported for existing Make scenarios. The service selects `media`, then `photos`, then line-separated `photo` values.

## Make request example

```json
{
  "profile_id": "b2b-123",
  "channel": "@tutortutor",
  "media": [
    "https://example.com/one.jpg",
    "https://example.com/two.jpg",
    "https://example.com/three.jpg"
  ],
  "text": "<span class=\"tg-bold\">Важлива подія</span><br>Деталі за <a href=\"https://example.com\">посиланням</a>",
  "allow_comments": false,
  "buttons": [
    {"text": "Деталі", "url": "https://example.com"},
    {"text": "Записатися", "url": "https://example.com/signup"}
  ]
}
```

Response for this request includes:

```json
{
  "success": true,
  "media_count": 3,
  "media_mode": "album",
  "media_position": "above_text",
  "parse_mode": "HTML",
  "blockquote": true,
  "spoiler": true,
  "unicode_emojis": true,
  "custom_emojis": false,
  "buttons_count": 2
}
```

## Environment

- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_SESSION`
- `MAKE_API_KEY`
- `TELEGRAM_CHANNEL`

`render.yaml` creates a separate Render service named
`tutor-b2b-telegram-publisher`. Copy the current B2C values for
`TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION`, `MAKE_API_KEY` and
`TELEGRAM_CHANNEL` into this service. This reuses the same publishing identity
without modifying the existing B2C service.

Start command:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```
