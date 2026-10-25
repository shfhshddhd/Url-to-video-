# Telegram Video Downloader Bot

A Python Telegram bot using python-telegram-bot and yt-dlp. Send a public supported video URL or direct HTTP(S) media URL, view metadata/thumbnail and available qualities, then deliver as a Telegram video or document.

## Setup
1. Add repository secret `TELEGRAM_BOT_TOKEN` in Settings → Secrets and variables → Actions.
2. Open Actions → Video Downloader Bot → Run workflow.
3. Send /start to your Telegram bot and then send a public video URL.

Optional Actions variables: `MAX_UPLOAD_MB` (default 49) and `MAX_DOWNLOAD_MB` (default 500). Verify the upload cap for the Bot API endpoint you actually use before changing it.

## Limits
- GitHub Actions is temporary testing, not 24/7 hosting. This workflow stops after 350 minutes; restart manually.
- Scheduled workflows are not guaranteed to start exactly on time.
- Not every URL works. Private/login-required, DRM-protected, expired, or unsupported links may fail. This bot does not bypass access controls.
- Exact file size may be unknown before download if the source does not provide it.
- Python syntax can be checked in CI, but real Telegram upload tests require a valid token and a reachable source.
- Never commit your bot token.
