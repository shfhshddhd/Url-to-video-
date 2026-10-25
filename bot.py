import asyncio, ipaddress, logging, os, re, socket, tempfile, time
from pathlib import Path
from urllib.parse import urlparse
import requests
import yt_dlp
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("video-downloader")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
MAX_UPLOAD = int(os.getenv("MAX_UPLOAD_MB", "49")) * 1024 * 1024
MAX_DOWNLOAD = int(os.getenv("MAX_DOWNLOAD_MB", "500")) * 1024 * 1024
TMP = Path("/tmp/video-downloader"); TMP.mkdir(exist_ok=True)
JOBS = {}; TTL = 1800
URL_RE = re.compile(r"https?://[^\s<>]+", re.I)

def safe_url(raw):
    u = raw.strip().rstrip(".,);]}>")
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password:
        raise ValueError("HTTP/HTTPS video link bhejein; embedded credentials allowed nahi hain.")
    host = p.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith((".local", ".internal")):
        raise ValueError("Local/private network URL allowed nahi hai.")
    try:
        for item in socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM):
            if not ipaddress.ip_address(item[4][0]).is_global:
                raise ValueError("Private network URL blocked.")
    except socket.gaierror:
        pass
    return u

def metadata(url):
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True, "socket_timeout": 20, "retries": 1}
    with yt_dlp.YoutubeDL(opts) as ydl: d = ydl.extract_info(url, download=False)
    if not d or d.get("entries") or d.get("_type") in ("playlist", "multi_video"):
        raise ValueError("Single video URL bhejein; playlist supported nahi hai.")
    best = {}
    for f in d.get("formats") or []:
        if f.get("vcodec") in (None, "none") or not f.get("height"): continue
        h = int(f["height"]); size = f.get("filesize") or f.get("filesize_approx")
        item = {"id": str(f["format_id"]), "height": h, "size": int(size) if size else None, "ext": f.get("ext") or "mp4", "audio": f.get("acodec") not in (None, "none")}
        old = best.get(h)
        if not old or (item["audio"], bool(item["size"]), item["ext"] == "mp4") > (old["audio"], bool(old["size"]), old["ext"] == "mp4"): best[h] = item
    formats = sorted(best.values(), key=lambda x:x["height"], reverse=True)[:10]
    if not formats: formats = [{"id":"best[protocol^=http]/best","height":0,"size":None,"ext":"mp4","audio":True}]
    return {"title":str(d.get("title") or "Video")[:180], "duration":d.get("duration"), "thumbnail":d.get("thumbnail"), "formats":formats}

def size_text(n): return f"{n/1048576:.1f} MB" if n else "size unknown"
def duration_text(n):
    if not n: return "Unknown"
    n=int(n); return f"{n//3600:02}:{n%3600//60:02}:{n%60:02}" if n>=3600 else f"{n//60:02}:{n%60:02}"
def md(s): return re.sub(r"([_*\[\]`])", r"\\\1", str(s))
def getjob(uid,jid):
    j=JOBS.get(uid)
    return j if j and j["id"]==jid and time.time()-j["time"]<TTL else None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎬 Video Downloader\n\nSupported public video website ya direct HTTP(S) video URL bhejo. Bot thumbnail, duration, available quality aur size dikhayega. /cancel selection clear karta hai.\n\nLogin/DRM-protected/private links aur unsupported sites fail ho sakte hain.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    JOBS.pop(update.effective_user.id, None); await update.message.reply_text("Selection cancelled.")

async def url_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    match=URL_RE.search(update.message.text or "")
    if not match: return await update.message.reply_text("Video URL bhejein.")
    try: url=safe_url(match.group(0))
    except ValueError as e: return await update.message.reply_text("❌ "+str(e))
    status=await update.message.reply_text("🔎 Video link check ho raha hai…")
    try:
        info=await asyncio.to_thread(metadata,url); uid=update.effective_user.id; jid=str(int(time.time()*1000))
        JOBS[uid]={"id":jid,"time":time.time(),"url":url,"info":info}
        rows=[]
        for i,f in enumerate(info["formats"]):
            q=f'{f["height"]}p' if f["height"] else "Original"
            rows.append([InlineKeyboardButton(f"📥 {q} · {size_text(f['size'])}",callback_data=f"q:{jid}:{i}")])
        caption=f"🎞 *{md(info['title'])}*\n⏱ Duration: {duration_text(info['duration'])}\n\nAvailable quality select karein:"
        thumb=info.get("thumbnail")
        if thumb:
            try:
                thumb=safe_url(thumb)
                r=await asyncio.to_thread(requests.get,thumb,timeout=12,headers={"User-Agent":"Mozilla/5.0"})
                r.raise_for_status()
                if r.headers.get("content-type","").startswith("image/") and len(r.content)<=4*1024*1024:
                    await status.delete()
                    return await update.message.reply_photo(photo=r.content,caption=caption,parse_mode="Markdown",reply_markup=InlineKeyboardMarkup(rows))
            except Exception: log.info("Thumbnail not available")
        await status.edit_text(caption,parse_mode="Markdown",reply_markup=InlineKeyboardMarkup(rows))
    except Exception as e:
        log.warning("metadata failed: %s",e)
        await status.edit_text("❌ Video available nahi hai ya supported nahi hai. Public URL try karein; login/DRM/private links supported nahi hain.")

async def quality(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    try:
        _,jid,idx=q.data.split(":"); j=getjob(q.from_user.id,jid)
        if not j: return await q.edit_message_text("Selection expire ho gayi. URL dobara bhejein.")
        j["format"]=j["info"]["formats"][int(idx)]
        f=j["format"]; quality=f'{f["height"]}p' if f["height"] else "Original quality"
        text=f"Quality: {quality}\nEstimated size: {size_text(f['size'])}\n\nDelivery type choose karein:"
        kb=InlineKeyboardMarkup([[InlineKeyboardButton("🎬 Video",callback_data=f"d:{jid}:video"),InlineKeyboardButton("📎 Document",callback_data=f"d:{jid}:document")],[InlineKeyboardButton("❌ Cancel",callback_data=f"x:{jid}")]])
        if q.message.photo: await q.edit_message_caption(caption=text,reply_markup=kb)
        else: await q.edit_message_text(text,reply_markup=kb)
    except Exception: log.exception("quality callback failed"); await q.message.reply_text("Selection error. URL dobara bhejein.")

async def delivery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer()
    try:
        _,jid,mode=q.data.split(":"); j=getjob(q.from_user.id,jid)
        if not j: return await q.message.reply_text("Selection expire ho gayi. URL dobara bhejein.")
        f=j["format"]; status=await q.message.reply_text("⬇️ Download shuru ho raha hai…")
        with tempfile.TemporaryDirectory(dir=TMP) as td:
            def hook(d):
                if d.get("status")=="downloading":
                    total=d.get("total_bytes") or d.get("total_bytes_estimate"); got=d.get("downloaded_bytes",0)
                    if total: log.info("Download %.1f%%",got*100/total)
            opts={"quiet":True,"no_warnings":True,"noplaylist":True,"outtmpl":str(Path(td)/"%(title).100B.%(ext)s"),"progress_hooks":[hook],"max_filesize":MAX_DOWNLOAD,"socket_timeout":25,"retries":2,"merge_output_format":"mp4","format":f["id"]}
            def run():
                with yt_dlp.YoutubeDL(opts) as ydl: ydl.download([j["url"]])
            await asyncio.to_thread(run)
            candidates=[p for p in Path(td).iterdir() if p.is_file() and not p.name.endswith((".part",".ytdl"))]
            if not candidates: raise ValueError("Download file create nahi hui.")
            path=max(candidates,key=lambda p:p.stat().st_size); size=path.stat().st_size
            if size>MAX_UPLOAD: return await status.edit_text(f"❌ File {size/1048576:.1f} MB hai; configured upload cap {MAX_UPLOAD/1048576:.0f} MB. Lower quality select karein.")
            await status.edit_text(f"📤 Upload ho raha hai ({size/1048576:.1f} MB)…")
            with path.open("rb") as fp:
                if mode=="video": await q.message.reply_video(video=fp,caption=j["info"]["title"][:900],supports_streaming=True,read_timeout=180,write_timeout=180,connect_timeout=30)
                else: await q.message.reply_document(document=fp,filename=path.name,caption=j["info"]["title"][:900],read_timeout=180,write_timeout=180,connect_timeout=30)
            await status.edit_text("✅ Video bhej diya."); JOBS.pop(q.from_user.id,None)
    except (BadRequest,Forbidden) as e:
        log.warning("Telegram upload error: %s",e); await q.message.reply_text("❌ Telegram upload reject hua. File size/API limit ya bot permissions check karein.")
    except Exception as e:
        log.exception("download failed: %s",e); await q.message.reply_text("❌ Download fail hua. Link expired/unsupported ho sakta hai, ya format unavailable hai.")
async def cancel_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer("Cancelled"); JOBS.pop(q.from_user.id,None)
    try: await q.edit_message_caption(caption="❌ Cancelled.")
    except BadRequest: await q.edit_message_text("❌ Cancelled.")

def main():
    if not TOKEN: raise SystemExit("Set TELEGRAM_BOT_TOKEN in GitHub Actions Secrets.")
    app=Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",start)); app.add_handler(CommandHandler("help",start)); app.add_handler(CommandHandler("cancel",cancel))
    app.add_handler(CallbackQueryHandler(quality,pattern=r"^q:")); app.add_handler(CallbackQueryHandler(delivery,pattern=r"^d:")); app.add_handler(CallbackQueryHandler(cancel_button,pattern=r"^x:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,url_message))
    app.run_polling(drop_pending_updates=True)
if __name__=="__main__": main()
