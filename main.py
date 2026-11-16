import glob
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime
from difflib import SequenceMatcher
from urllib.parse import parse_qs, unquote, urlparse
import unicodedata

import yt_dlp
from PySide6 import __version__ as PYSIDE_VERSION
from PySide6.QtCore import QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QListWidget,
    QListWidgetItem,
    QSizeGrip,
    QSizePolicy,
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSystemTrayIcon,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from channel_preview import ChannelPreviewDialog

APP_NAME = "TarikYT"
APP_VERSION = "v2.0.0"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
MAX_ACTIVE_DOWNLOADS = 3
MAX_ACTIVE_MERGES = 1

QUALITY_HEIGHTS = {
    "8K / 4320p": 4320,
    "4K / 2160p": 2160,
    "1440p": 1440,
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
    "360p": 360,
}

ACTIVE_STATUSES = {
    "Checking",
    "Downloading",
    "Merging",
    "Post-processing",
    "Moving final file",
}
RECOVERABLE_STATUSES = ACTIVE_STATUSES | {"Downloaded", "Paused"}
DONE_STATUSES = {"Done", "Done with warning"}
VIDEO_FORMATS = {"MP4 Video", "MKV Video", "WEBM Video"}
AUDIO_FORMATS = {"MP3 Audio", "M4A Audio", "WAV Audio", "OPUS Audio", "FLAC Audio"}
IMAGE_FORMATS = {"Image"}
AUDIO_EXTENSIONS = {"mp3", "m4a", "wav", "opus", "flac"}
VIDEO_EXTENSIONS = {"mp4", "mkv", "webm"}
IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif", "avif"}
IMAGE_CONTENT_TYPES = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/avif": "avif",
}
PLATFORM_FOLDERS = {
    "YouTube": "YouTube",
    "TikTok": "TikTok",
    "Instagram": "Instagram",
    "Twitter-X": "Twitter-X",
    "Other": "Other",
}
SOCIAL_VIDEO_PLATFORMS = {"TikTok", "Instagram", "Twitter-X"}
PLATFORM_LABELS = {
    "Twitter-X": "X/Twitter",
}
QUALITY_MODES = {"Exact only", "Best up to selected"}
SUBTITLE_MODES = {"Off", "Manual only", "Auto only", "Manual + Auto"}
COOKIE_BROWSERS = {"None": None, "Chrome": "chrome", "Edge": "edge", "Firefox": "firefox"}
CODEC_FILTERS = {
    "Auto": None,
    "H.264 / AVC": "vcodec^=avc1",
    "VP9": "vcodec^=vp9",
    "AV1": "vcodec^=av01",
}
AUDIO_SELECTORS = {
    "Auto": "ba",
    "M4A": "ba[ext=m4a]/ba",
    "Opus": "ba[acodec^=opus]/ba",
}
FILENAME_TEMPLATES = {
    "Title [ID]": "%(title).200s [%(id)s].%(ext)s",
    "Channel - Title [ID]": "%(channel).80s - %(title).180s [%(id)s].%(ext)s",
    "Date - Title [ID]": "%(upload_date)s - %(title).180s [%(id)s].%(ext)s",
    "Playlist index - Title [ID]": "%(playlist_index)s - %(title).180s [%(id)s].%(ext)s",
}
PRESET_PROFILES = {
    "Custom": {},
    "Fast 720p": {
        "quality": "720p",
        "quality_mode": "Best up to selected",
        "format": "MP4 Video",
        "subtitle": "Off",
    },
    "Normal 1080p MP4": {
        "quality": "1080p",
        "quality_mode": "Best up to selected",
        "format": "MP4 Video",
        "subtitle": "Manual + Auto",
    },
    "High Quality 4K MKV": {
        "quality": "4K / 2160p",
        "quality_mode": "Exact only",
        "format": "MKV Video",
        "auto_container": True,
        "subtitle": "Manual + Auto",
    },
    "Audio MP3": {
        "format": "MP3 Audio",
        "audio_bitrate": 192,
    },
    "Playlist Safe": {
        "quality": "1080p",
        "quality_mode": "Best up to selected",
        "format": "MP4 Video",
        "subtitle": "Manual + Auto",
        "playlist": True,
        "fragments": 1,
    },
}
APP_STATE_FILE = os.path.join(APP_DIR, "yt_downloader_v2_state.json")
HISTORY_FILE = os.path.join(APP_DIR, "yt_downloader_v2_history.jsonl")
SETTINGS_FILE = os.path.join(APP_DIR, "yt_downloader_v2_settings.json")


class DownloadCancelled(Exception):
    pass


def resource_path(name):
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, name)


def is_existing_file(path):
    try:
        return bool(path) and os.path.isfile(path)
    except OSError:
        return False


def find_common_ffmpeg():
    candidates = [
        resource_path("ffmpeg.exe"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg.exe"),
        shutil.which("ffmpeg"),
    ]

    winget_root = os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "Microsoft",
        "WinGet",
        "Packages",
    )
    if winget_root:
        candidates.extend(
            glob.glob(
                os.path.join(winget_root, "Gyan.FFmpeg_*", "ffmpeg-*", "bin", "ffmpeg.exe")
            )
        )

    for candidate in candidates:
        if is_existing_file(candidate):
            return candidate
    return None


def classify_download_error_hint(error_text):
    """Return an actionable Indonesian troubleshooting hint for common yt-dlp/FFmpeg errors."""
    if not error_text:
        return ""
    lowered = str(error_text).lower()
    if any(
        token in lowered
        for token in (
            "sign in to confirm",
            "not a bot",
            "http error 403",
            "403: forbidden",
            "use --cookies",
            "cookies are needed",
            "login required",
        )
    ):
        return (
            "Saran: YouTube membatasi akses atau meminta verifikasi. "
            "Buka tab 'Subtitle & Cookies' lalu pilih Browser Cookies (Chrome/Edge/Firefox) atau file cookies.txt."
        )
    if any(
        token in lowered
        for token in (
            "ffmpeg is not installed",
            "ffprobe is not installed",
            "ffmpeg not found",
            "postprocessing",
            "unable to merge",
        )
    ):
        return (
            "Saran: FFmpeg bermasalah atau belum terdeteksi. "
            "Buka tab 'Output / FFmpeg' lalu klik 'Detect' atau arahkan ke folder ffmpeg.exe."
        )
    if any(
        token in lowered
        for token in (
            "timed out",
            "connection reset",
            "connection aborted",
            "urlopen error",
            "ssl",
            "temporary failure in name resolution",
            "network is unreachable",
        )
    ):
        return "Saran: Gangguan koneksi jaringan/DNS terdeteksi. Cek koneksi internet/VPN lalu klik 'Retry Failed'."
    if any(
        token in lowered
        for token in (
            "private video",
            "video unavailable",
            "has been removed",
            "account associated with this video has been terminated",
        )
    ):
        return "Saran: Video berstatus privat, dihapus, atau tidak tersedia secara publik."
    return ""


def resolve_ffmpeg(manual_path=None):
    clean_path = manual_path.strip() if isinstance(manual_path, str) and manual_path.strip() else None
    if clean_path:
        if os.path.isdir(clean_path):
            candidate = os.path.join(clean_path, "ffmpeg.exe")
            if is_existing_file(candidate):
                return candidate
        if is_existing_file(clean_path):
            return clean_path
    return find_common_ffmpeg()


def find_common_ffprobe(companion_ffmpeg=None):
    candidates = []
    if companion_ffmpeg and is_existing_file(companion_ffmpeg):
        candidates.append(os.path.join(os.path.dirname(companion_ffmpeg), "ffprobe.exe"))

    candidates.append(resource_path("ffprobe.exe"))
    candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffprobe.exe"))
    candidates.append(shutil.which("ffprobe"))

    winget_root = os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "Microsoft",
        "WinGet",
        "Packages",
    )
    if winget_root:
        candidates.extend(
            glob.glob(
                os.path.join(winget_root, "Gyan.FFmpeg_*", "ffmpeg-*", "bin", "ffprobe.exe")
            )
        )

    for candidate in candidates:
        if candidate and is_existing_file(candidate):
            return candidate
    return None


def resolve_ffprobe(manual_path=None):
    clean_path = manual_path.strip() if isinstance(manual_path, str) and manual_path.strip() else None
    if clean_path:
        if os.path.isdir(clean_path):
            candidate = os.path.join(clean_path, "ffprobe.exe")
            if is_existing_file(candidate):
                return candidate
        if is_existing_file(clean_path):
            if "ffprobe" in os.path.basename(clean_path).lower():
                return clean_path
            candidate = os.path.join(os.path.dirname(clean_path), "ffprobe.exe")
            if is_existing_file(candidate):
                return candidate

    companion = resolve_ffmpeg(clean_path)
    return find_common_ffprobe(companion)


def cookie_option(browser_label):
    browser = COOKIE_BROWSERS.get(browser_label)
    return (browser,) if browser else None


def add_cookie_opts(opts, browser_label, cookies_file=None):
    if is_existing_file(cookies_file):
        opts["cookiefile"] = cookies_file
        return

    cookies = cookie_option(browser_label)
    if cookies:
        opts["cookiesfrombrowser"] = cookies


def normalize_search_text(text):
    text = str(text or "").casefold()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact_search_text(text):
    return normalize_search_text(text).replace(" ", "")


def token_similar(a, b):
    if not a or not b:
        return False

    if a == b or a in b or b in a:
        return True

    ratio = SequenceMatcher(None, a, b).ratio()
    length = max(len(a), len(b))

    if length <= 3:
        return ratio >= 0.67
    if length <= 5:
        return ratio >= 0.75
    return ratio >= 0.80


def fuzzy_title_match(keyword, title):
    normalized_keyword = normalize_search_text(keyword)
    normalized_title = normalize_search_text(title)

    if not normalized_keyword or not normalized_title:
        return False

    if normalized_keyword in normalized_title:
        return True

    compact_keyword = compact_search_text(keyword)
    compact_title = compact_search_text(title)

    if compact_keyword and compact_keyword in compact_title:
        return True

    keyword_tokens = normalized_keyword.split()
    title_tokens = normalized_title.split()

    if not keyword_tokens or not title_tokens:
        return False

    for keyword_token in keyword_tokens:
        matched = any(token_similar(keyword_token, title_token) for title_token in title_tokens)
        if not matched:
            return False

    return True


def normalize_channel_videos_url(url):
    raw_url = (url or "").strip()
    if not raw_url:
        return ""

    if raw_url.startswith("www.youtube.com/") or raw_url.startswith("youtube.com/"):
        raw_url = f"https://{raw_url}"

    parsed = urlparse(raw_url)
    path = re.sub(r"/+", "/", parsed.path or "").rstrip("/")
    netloc = parsed.netloc.lower()

    if "youtube.com" in netloc:
        parts = [part for part in path.split("/") if part]
        if parts and parts[0].startswith("@"):
            path = f"/{parts[0]}"
            if len(parts) > 1 and parts[1].lower() == "videos":
                path += "/videos"
            else:
                path += "/videos"
        elif len(parts) >= 2 and parts[0].lower() == "channel":
            path = f"/channel/{parts[1]}"
            if len(parts) > 2 and parts[2].lower() == "videos":
                path += "/videos"
            else:
                path += "/videos"

    return parsed._replace(path=path, query="", fragment="").geturl()


def video_key(url):
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    if query.get("v"):
        return query["v"][0]

    match = re.search(r"(?:youtu\.be/|shorts/)([^/?&#]+)", url)
    if match:
        return match.group(1)

    tiktok_match = re.search(r"/video/(\d+)", parsed.path)
    if tiktok_match:
        return tiktok_match.group(1)

    instagram_match = re.search(r"/(?:reel|reels|p|tv)/([^/?&#]+)", parsed.path)
    if instagram_match:
        return instagram_match.group(1)

    twitter_match = re.search(r"/status(?:es)?/(\d+)", parsed.path)
    if twitter_match:
        return twitter_match.group(1)

    return url.strip()


def detect_platform_from_info(info_dict, url):
    info_dict = info_dict or {}
    candidates = [
        str(info_dict.get("extractor_key") or ""),
        str(info_dict.get("extractor") or ""),
    ]
    text = " ".join(candidates).lower()
    if "tiktok" in text:
        return "TikTok"
    if "youtube" in text:
        return "YouTube"
    if "instagram" in text:
        return "Instagram"
    if "twitter" in text or text == "x" or "x.com" in text:
        return "Twitter-X"

    parsed = urlparse(url or "")
    domain = parsed.netloc.lower()
    if "tiktok.com" in domain:
        return "TikTok"
    if "youtube.com" in domain or "youtu.be" in domain:
        return "YouTube"
    if "instagram.com" in domain:
        return "Instagram"
    if "twitter.com" in domain or domain == "x.com" or domain.endswith(".x.com"):
        return "Twitter-X"
    return "Other"


def display_platform(platform):
    return PLATFORM_LABELS.get(platform, platform or "Other")


def social_platform_cookie_hint(platform):
    label = display_platform(platform)
    return (
        f"Catatan {label}: jika gagal, aktifkan cookies browser/cookies.txt "
        "dari browser yang sudah login."
    )


def looks_like_url(url):
    parsed = urlparse(url or "")
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def detect_media_type(selected_format, output_ext=None):
    if selected_format in AUDIO_FORMATS:
        return "Audio"
    if selected_format in VIDEO_FORMATS:
        return "Video"
    if selected_format in IMAGE_FORMATS:
        return "Image"
    ext = (output_ext or "").lower().lstrip(".")
    if ext in AUDIO_EXTENSIONS:
        return "Audio"
    if ext in VIDEO_EXTENSIONS:
        return "Video"
    if ext in IMAGE_EXTENSIONS:
        return "Image"
    return "Video"


def platform_video_key(platform, video_id):
    return (platform or "Other", video_id or "")


def safe_platform_folder(platform):
    return PLATFORM_FOLDERS.get(platform or "Other", "Other")


def safe_filename_component(value, fallback="download"):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", str(value or fallback))
    value = re.sub(r"\s+", " ", value).strip(" .")
    return (value or fallback)[:160]


def clean_extracted_url(url):
    if not url:
        return None
    text = str(url).replace("\\/", "/").replace("\\u0026", "&")
    try:
        text = bytes(text, "utf-8").decode("unicode_escape")
    except UnicodeDecodeError:
        pass
    text = unquote(text).strip()
    return text if text.startswith(("http://", "https://")) else None


def image_ext_from_url(url):
    parsed = urlparse(url or "")
    query = parse_qs(parsed.query)
    if query.get("format"):
        ext = query["format"][0].lower().lstrip(".")
        if ext in IMAGE_EXTENSIONS:
            return "jpg" if ext == "jpeg" else ext
    match = re.search(r"\.([a-zA-Z0-9]{2,5})(?:$|[?#])", parsed.path)
    if match:
        ext = match.group(1).lower()
        if ext in IMAGE_EXTENSIONS:
            return "jpg" if ext == "jpeg" else ext
    return None


def image_ext_from_content_type(content_type):
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    return IMAGE_CONTENT_TYPES.get(mime)


def normalize_image_url(url, platform=None):
    url = clean_extracted_url(url)
    if not url:
        return None
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if platform == "Twitter-X" and "pbs.twimg.com" in domain:
        query = parse_qs(parsed.query)
        fmt = (query.get("format") or [image_ext_from_url(url) or "jpg"])[0]
        return parsed._replace(query=f"format={fmt}&name=orig").geturl()
    return url


def looks_like_image_url(url, platform=None):
    url = clean_extracted_url(url)
    if not url:
        return False
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    lower = url.lower()
    if platform == "Twitter-X":
        return "pbs.twimg.com/media/" in lower or "pbs.twimg.com/tweet_video_thumb/" in lower
    if platform == "Instagram":
        if "profile_pic" in lower or "profile_pic_url" in lower:
            return False
        return (
            image_ext_from_url(url) in IMAGE_EXTENSIONS
            or "cdninstagram.com" in domain
            or "fbcdn.net" in domain
            or "scontent" in domain
        )
    if platform == "TikTok":
        if "avatar" in lower:
            return False
        return (
            image_ext_from_url(url) in IMAGE_EXTENSIONS
            or "tiktokcdn" in domain
            or "tiktokv" in domain
            or "byteimg" in domain
        )
    return image_ext_from_url(url) in IMAGE_EXTENSIONS


def image_candidate_score(candidate, platform=None):
    url = candidate.get("url") or ""
    width = candidate.get("width") or 0
    height = candidate.get("height") or 0
    lower = url.lower()
    preference = candidate.get("preference") or 0
    original_bonus = 0
    if "name=orig" in lower or "maxresdefault" in lower or "origin" in lower:
        original_bonus += 100000000
    if "profile" in lower or "avatar" in lower:
        original_bonus -= 100000000
    if platform == "YouTube" and "maxresdefault" in lower:
        original_bonus += 100000000
    return (original_bonus, width * height, max(width, height), preference)


def add_image_candidate(candidates, url, width=None, height=None, platform=None, source=None, headers=None, preference=0):
    url = normalize_image_url(url, platform)
    if not looks_like_image_url(url, platform):
        return
    key = url.split("#", 1)[0]
    if key in candidates:
        existing = candidates[key]
        existing["width"] = max(existing.get("width") or 0, width or 0) or None
        existing["height"] = max(existing.get("height") or 0, height or 0) or None
        existing["preference"] = max(existing.get("preference") or 0, preference or 0)
        return
    candidates[key] = {
        "url": url,
        "width": width,
        "height": height,
        "source": source,
        "headers": dict(headers or {}),
        "preference": preference,
    }


def collect_image_candidates(value, candidates, platform=None, headers=None, source=None):
    if isinstance(value, dict):
        width = (
            value.get("width")
            or value.get("config_width")
            or value.get("w")
            or value.get("Width")
        )
        height = (
            value.get("height")
            or value.get("config_height")
            or value.get("h")
            or value.get("Height")
        )
        preference = value.get("preference") or value.get("quality") or 0
        for key in ("url", "src", "display_url", "display_src", "thumbnail", "media_url_https", "media_url"):
            if key in value:
                add_image_candidate(
                    candidates,
                    value.get(key),
                    width=width,
                    height=height,
                    platform=platform,
                    source=source or key,
                    headers=headers,
                    preference=preference,
                )
        for item in value.values():
            collect_image_candidates(item, candidates, platform=platform, headers=headers, source=source)
    elif isinstance(value, list):
        for item in value:
            collect_image_candidates(item, candidates, platform=platform, headers=headers, source=source)
    elif isinstance(value, str):
        add_image_candidate(candidates, value, platform=platform, source=source, headers=headers)


def image_candidates_from_text(text, platform=None, headers=None):
    candidates = {}
    for match in re.finditer(r"https?:\\?/\\?/[^\"'<> ]+", text or ""):
        raw = match.group(0).rstrip("\\,;)")
        add_image_candidate(candidates, raw, platform=platform, source="page", headers=headers)
    return list(candidates.values())


def best_image_candidates(candidates, platform=None, limit=30):
    unique = {}
    for candidate in candidates or []:
        add_image_candidate(
            unique,
            candidate.get("url"),
            width=candidate.get("width"),
            height=candidate.get("height"),
            platform=platform,
            source=candidate.get("source"),
            headers=candidate.get("headers"),
            preference=candidate.get("preference") or 0,
        )
    ranked = sorted(
        unique.values(),
        key=lambda item: image_candidate_score(item, platform=platform),
        reverse=True,
    )
    if platform == "YouTube":
        return ranked[:1]
    return ranked[:limit]


def available_format_summary(formats, limit=12):
    labels = []
    for fmt in formats or []:
        format_id = fmt.get("format_id") or "unknown"
        height = fmt.get("height")
        width = fmt.get("width")
        fps = fmt.get("fps")
        vcodec = fmt.get("vcodec")
        acodec = fmt.get("acodec")
        size = human_size(format_filesize_bytes(fmt))
        if width and height:
            quality = f"{width}x{height}"
        elif height:
            quality = f"{height}p"
        else:
            quality = "unknown"
        parts = [str(format_id), quality]
        if fps:
            parts.append(f"{fps}fps")
        if vcodec and vcodec != "none":
            parts.append(str(vcodec))
        if acodec and acodec != "none":
            parts.append(str(acodec))
        parts.append(size)
        labels.append(" - ".join(parts))
    return "; ".join(labels[:limit]) if labels else "-"


def friendly_metadata_error(error, url):
    platform = detect_platform_from_info({}, url)
    if platform in SOCIAL_VIDEO_PLATFORMS:
        label = PLATFORM_LABELS.get(platform, platform)
        return (
            f"Gagal cek link {label}. Platform ini kadang membutuhkan update yt-dlp, "
            "cookies browser, cookies.txt, atau login untuk konten private/age-restricted. "
            "Coba Update yt-dlp atau aktifkan cookies."
        )
    return f"Gagal cek link: {error}"


def human_size(num_bytes):
    if not num_bytes:
        return "-"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def human_speed(num_bytes):
    if not num_bytes:
        return "-"
    return f"{num_bytes / 1024 / 1024:.1f} MB/s"


def human_eta(seconds):
    if seconds in (None, "", 0):
        return "-"
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "-"
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {sec}s"
    if minutes:
        return f"{minutes}m {sec}s"
    return f"{sec}s"


def format_filesize_bytes(fmt):
    if not fmt:
        return None
    value = fmt.get("filesize") or fmt.get("filesize_approx")
    if not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def best_audio_format(formats):
    best = None
    best_score = (-1, -1, -1)
    for fmt in formats or []:
        if fmt.get("acodec") in (None, "none"):
            continue
        if fmt.get("vcodec") not in (None, "none"):
            continue
        score = (
            fmt.get("abr") or 0,
            fmt.get("tbr") or 0,
            format_filesize_bytes(fmt) or 0,
        )
        if score > best_score:
            best = fmt
            best_score = score
    return best


def best_video_format(formats):
    best = None
    best_score = (-1, -1, -1)
    for fmt in formats or []:
        if fmt.get("vcodec") in (None, "none"):
            continue
        width = fmt.get("width") or 0
        height = fmt.get("height") or 0
        short_side = min(width, height) if width and height else height
        score = (
            short_side,
            fmt.get("fps") or 0,
            format_filesize_bytes(fmt) or 0,
        )
        if score > best_score:
            best = fmt
            best_score = score
    return best


def estimated_output_size_bytes(video_format, formats):
    video_size = format_filesize_bytes(video_format)
    if not video_size:
        return None

    if video_format.get("acodec") and video_format.get("acodec") != "none":
        return video_size

    audio = best_audio_format(formats)
    audio_size = format_filesize_bytes(audio)
    if audio_size:
        return video_size + audio_size
    return video_size


def best_filesize_summary(formats):
    best = best_video_format(formats)
    if not best:
        return "-"
    return human_size(estimated_output_size_bytes(best, formats))


def video_quality_label(fmt):
    if not fmt:
        return None

    width = fmt.get("width")
    height = fmt.get("height")
    fps = fmt.get("fps")

    if width and height:
        label = f"{width}x{height}"
    elif height:
        label = f"{height}p"
    else:
        return None

    if fps:
        label = f"{label} {fps}fps"
    return label


def video_quality_size_label(fmt, formats):
    label = video_quality_label(fmt)
    if not label:
        return None
    return f"{label} ({human_size(estimated_output_size_bytes(fmt, formats))})"


def available_video_quality_summary(formats, limit=10, include_size=False):
    seen = set()
    labels = []
    video_formats = [
        fmt
        for fmt in formats or []
        if fmt.get("vcodec") and fmt.get("vcodec") != "none"
    ]
    video_formats.sort(
        key=lambda fmt: (
            max(fmt.get("width") or 0, fmt.get("height") or 0),
            fmt.get("fps") or 0,
            estimated_output_size_bytes(fmt, formats) or 0,
        ),
        reverse=True,
    )

    for fmt in video_formats:
        label = video_quality_label(fmt)
        if label and label not in seen:
            seen.add(label)
            if include_size:
                labels.append(video_quality_size_label(fmt, formats))
            else:
                labels.append(label)

    return ", ".join(labels[:limit]) if labels else "tidak ada format video"


def highest_available_quality(formats):
    best = None
    best_score = (-1, -1)

    for fmt in formats or []:
        if fmt.get("vcodec") in (None, "none"):
            continue

        width = fmt.get("width") or 0
        height = fmt.get("height") or 0
        short_side = min(width, height) if width and height else height
        score = (short_side, fmt.get("fps") or 0)
        if score > best_score:
            best = fmt
            best_score = score

    return video_quality_label(best) if best else "tidak diketahui"


class UpdateYtDlpThread(QThread):
    log = Signal(str)
    finished_update = Signal(bool, str)

    def __init__(self, workdir):
        super().__init__()
        self.workdir = workdir

    def run(self):
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
                cwd=self.workdir,
                capture_output=True,
                text=True,
                timeout=180,
            )
            if result.stdout:
                self.log.emit(result.stdout.strip())
            if result.stderr:
                self.log.emit(result.stderr.strip())
            if result.returncode == 0:
                self.finished_update.emit(
                    True,
                    "Update yt-dlp selesai. Restart aplikasi (dan rebuild exe jika memakai versi exe) agar versi baru aktif.",
                )
            else:
                self.finished_update.emit(False, f"Update yt-dlp gagal dengan kode {result.returncode}.")
        except Exception as e:
            self.finished_update.emit(False, f"Update yt-dlp gagal: {e}")


class ChannelVideosThread(QThread):
    log = Signal(str)
    queue_ready = Signal(list, dict)
    error = Signal(str)
    done = Signal()

    def __init__(self, channel_url, keyword, cookies_browser, cookies_file):
        super().__init__()
        self.channel_url = channel_url
        self.keyword = keyword
        self.cookies_browser = cookies_browser
        self.cookies_file = cookies_file

    def build_opts(self):
        opts = {
            "extract_flat": "in_playlist",
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
            "skip_download": True,
        }
        add_cookie_opts(opts, self.cookies_browser, self.cookies_file)
        return opts

    def playlist_entry_url(self, entry):
        if entry.get("webpage_url"):
            return entry["webpage_url"]
        if entry.get("url", "").startswith("http"):
            return entry["url"]
        if entry.get("id"):
            return f"https://www.youtube.com/watch?v={entry['id']}"
        return entry.get("url")

    def run(self):
        stats = {
            "total": 0,
            "matched": 0,
            "queued": 0,
            "channel_url": "",
            "keyword": (self.keyword or "").strip(),
            "source": "",
        }

        try:
            channel_url = normalize_channel_videos_url(self.channel_url)
            keyword = (self.keyword or "").strip()
            stats["channel_url"] = channel_url

            if not channel_url:
                self.error.emit("URL channel masih kosong.")
                return
            if not keyword:
                self.error.emit("Keyword judul masih kosong.")
                return

            self.log.emit(f"Mengambil daftar video channel: {channel_url}")
            self.log.emit(f"Filter judul: {keyword}")

            with yt_dlp.YoutubeDL(self.build_opts()) as ydl:
                info = ydl.extract_info(channel_url, download=False)

            if not info:
                self.error.emit("yt-dlp tidak mengembalikan data channel.")
                return

            entries = [entry for entry in info.get("entries") or [] if entry]
            channel_title = info.get("title") or channel_url
            stats["total"] = len(entries)
            stats["source"] = channel_title

            items = []
            seen = set()

            for index, entry in enumerate(entries, start=1):
                title = entry.get("title") or ""
                if not fuzzy_title_match(keyword, title):
                    continue

                stats["matched"] += 1
                video_url = self.playlist_entry_url(entry)
                if not video_url:
                    continue

                platform = detect_platform_from_info(entry, video_url)
                key = entry.get("id") or video_key(video_url)
                dedupe_key = platform_video_key(platform, key or video_url)
                if dedupe_key in seen:
                    continue

                seen.add(dedupe_key)
                items.append({
                    "url": video_url,
                    "title": title or video_url,
                    "playlist_index": index,
                    "source": channel_title,
                    "platform": platform,
                    "key": key,
                    "video_id": key,
                })

            stats["queued"] = len(items)
            self.log.emit(
                f"Channel scan selesai: {stats['total']} video ditemukan, "
                f"{stats['matched']} match keyword, {stats['queued']} dikirim ke queue."
            )
            self.queue_ready.emit(items, stats)
        except Exception as e:
            self.error.emit(f"Gagal ambil daftar video channel: {e}")
        finally:
            self.done.emit()


class MetadataThread(QThread):
    log = Signal(str)
    queue_ready = Signal(object)
    done = Signal(bool, str)

    def __init__(
        self,
        urls,
        playlist_enabled,
        cookies_browser,
        cookies_file,
        playlist_start,
        playlist_end,
        check_mode,
    ):
        super().__init__()
        self.urls = urls
        self.playlist_enabled = playlist_enabled
        self.cookies_browser = cookies_browser
        self.cookies_file = cookies_file
        self.playlist_start = playlist_start
        self.playlist_end = playlist_end
        self.check_mode = check_mode

    def build_opts(self):
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": not self.playlist_enabled,
        }
        add_cookie_opts(opts, self.cookies_browser, self.cookies_file)
        if self.playlist_enabled:
            opts["extract_flat"] = "in_playlist"
        return opts

    def playlist_entry_url(self, entry):
        if entry.get("webpage_url"):
            return entry["webpage_url"]
        if entry.get("url", "").startswith("http"):
            return entry["url"]
        if entry.get("id"):
            return f"https://www.youtube.com/watch?v={entry['id']}"
        return entry.get("url")

    def run(self):
        items = []
        seen = set()

        try:
            with yt_dlp.YoutubeDL(self.build_opts()) as ydl:
                for url in self.urls:
                    info = ydl.extract_info(url, download=False)

                    if info.get("_type") == "playlist":
                        entries = [entry for entry in info.get("entries") or [] if entry]
                        if self.playlist_start:
                            entries = entries[max(0, self.playlist_start - 1):]
                        if self.playlist_end:
                            entries = entries[: max(0, self.playlist_end - (self.playlist_start or 1) + 1)]
                        self.log.emit(
                            f"Playlist terdeteksi: {info.get('title') or url} ({len(entries)} video)"
                        )
                        for index, entry in enumerate(entries, start=1):
                            entry_url = self.playlist_entry_url(entry)
                            if not entry_url:
                                continue
                            platform = detect_platform_from_info(entry, entry_url)
                            key = entry.get("id") or video_key(entry_url)
                            dedupe_key = platform_video_key(platform, key)
                            if dedupe_key in seen:
                                self.log.emit(f"Skip duplikat: {entry.get('title') or entry_url}")
                                continue
                            seen.add(dedupe_key)
                            items.append({
                                "url": entry_url,
                                "title": entry.get("title") or entry_url,
                                "playlist_index": index,
                                "source": info.get("title") or "Playlist",
                                "platform": platform,
                                "key": key,
                                "video_id": key,
                            })
                        continue

                    formats = info.get("formats") or []
                    qualities = available_video_quality_summary(formats)
                    quality_sizes = available_video_quality_summary(
                        formats,
                        include_size=True,
                    )
                    size = best_filesize_summary(formats)
                    estimate_bytes = None
                    best_fmt = best_video_format(formats)
                    if best_fmt:
                        estimate_bytes = estimated_output_size_bytes(best_fmt, formats)
                    title = info.get("title") or url
                    item_url = info.get("webpage_url") or url
                    platform = detect_platform_from_info(info, item_url)
                    key = info.get("id") or video_key(item_url)
                    dedupe_key = platform_video_key(platform, key)
                    if dedupe_key in seen:
                        self.log.emit(f"Skip duplikat: {title}")
                        continue
                    seen.add(dedupe_key)
                    self.log.emit(f"Detected platform: {platform}")
                    if platform in SOCIAL_VIDEO_PLATFORMS:
                        self.log.emit(social_platform_cookie_hint(platform))
                    if platform in SOCIAL_VIDEO_PLATFORMS:
                        self.log.emit(f"Available format: {available_format_summary(formats)}")
                    else:
                        self.log.emit(f"{title}: {quality_sizes}")
                    items.append({
                        "url": item_url,
                        "title": title,
                        "platform": platform,
                        "qualities": qualities,
                        "quality_sizes": quality_sizes,
                        "formats": formats if self.check_mode == "Full check" else [],
                        "size": size,
                        "estimated_size_bytes": estimate_bytes,
                        "key": key,
                        "video_id": key,
                    })

            if not items:
                self.done.emit(False, "Tidak ada video yang bisa dimasukkan ke queue.")
                return

            self.queue_ready.emit(items)
            self.done.emit(True, f"Queue siap: {len(items)} item.")
        except Exception as e:
            first_url = self.urls[0] if self.urls else ""
            self.done.emit(False, friendly_metadata_error(e, first_url))


class TestLinkThread(QThread):
    log = Signal(str)
    done = Signal(bool, str)

    def __init__(self, urls, cookies_browser, cookies_file):
        super().__init__()
        self.urls = urls
        self.cookies_browser = cookies_browser
        self.cookies_file = cookies_file

    def build_opts(self):
        opts = {
            "quiet": True,
            "no_warnings": False,
            "noplaylist": True,
        }
        add_cookie_opts(opts, self.cookies_browser, self.cookies_file)
        return opts

    def run(self):
        success_count = 0
        failed_count = 0

        try:
            with yt_dlp.YoutubeDL(self.build_opts()) as ydl:
                for url in self.urls:
                    if not looks_like_url(url):
                        failed_count += 1
                        self.log.emit(f"URL tidak valid: {url}")
                        continue

                    try:
                        info = ydl.extract_info(url, download=False)
                        platform = detect_platform_from_info(info, info.get("webpage_url") or url)
                        title = info.get("title") or url

                        if info.get("_type") == "playlist":
                            entries = [entry for entry in info.get("entries") or [] if entry]
                            self.log.emit(
                                f"OK: {display_platform(platform)} playlist - {title} ({len(entries)} item)"
                            )
                        else:
                            formats = info.get("formats") or []
                            qualities = available_video_quality_summary(formats, include_size=True)
                            self.log.emit(f"OK: {display_platform(platform)} - {title}")
                            self.log.emit(f"Resolusi tersedia: {qualities}")

                        if platform in SOCIAL_VIDEO_PLATFORMS:
                            self.log.emit(social_platform_cookie_hint(platform))
                        success_count += 1
                    except Exception as e:
                        failed_count += 1
                        self.log.emit(friendly_metadata_error(e, url))
        except Exception as e:
            first_url = self.urls[0] if self.urls else ""
            self.done.emit(False, friendly_metadata_error(e, first_url))
            return

        self.done.emit(
            success_count > 0,
            f"Test Link selesai. OK: {success_count}, gagal: {failed_count}.",
        )


class YtdlpStatusLogger:
    def __init__(self, owner, row=None):
        self.owner = owner
        self.row = row

    def debug(self, message):
        self._handle(message)

    def info(self, message):
        self._handle(message)

    def warning(self, message):
        self._handle(message)

    def error(self, message):
        self.owner.log.emit(message)

    def _handle(self, message):
        try:
            if not message:
                return
            text = str(message)
            lower = text.lower()
            if "[merger]" in text or "merging formats into" in lower:
                self.owner.set_post_status(
                    "Merging",
                    "Merging video/audio... large files may take several minutes",
                    row=self.row,
                )
                path = self.owner.extract_quoted_path(text)
                if path:
                    self.owner.remember_output_candidate(path, row=self.row)
            elif "[extractaudio]" in text:
                self.owner.set_post_status("Post-processing", "Converting audio with FFmpeg...", row=self.row)
            elif "[embedsubtitle]" in text:
                self.owner.set_post_status("Post-processing", "Embedding subtitles...", row=self.row)
            elif "[embedthumbnail]" in text:
                self.owner.set_post_status("Post-processing", "Embedding thumbnail...", row=self.row)
            elif "[metadata]" in text:
                self.owner.set_post_status("Post-processing", "Writing metadata...", row=self.row)
            elif "[movefiles]" in text or "moving file" in lower:
                self.owner.set_post_status("Moving final file", "Moving final file...", row=self.row)
            elif "deleting original file" in lower:
                self.owner.set_post_status("Post-processing", "Cleaning temporary files...", row=self.row)
            elif self.owner.debug_mode:
                self.owner.log.emit(text)
        except DownloadCancelled:
            raise
        except Exception:
            return


class DeferredPostProcessYoutubeDL(yt_dlp.YoutubeDL):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.deferred_postprocess = []

    def post_process(self, filename, info, files_to_move=None):
        info["filepath"] = filename
        self.deferred_postprocess.append((filename, info, dict(files_to_move or {})))
        return info

    def run_deferred_post_processes(self):
        result = None
        for filename, info, files_to_move in self.deferred_postprocess:
            info.pop("__files_to_move", None)
            result = super().post_process(filename, info, dict(files_to_move))
        self.deferred_postprocess.clear()
        return result


class DownloadThread(QThread):
    progress = Signal(int)
    row_update = Signal(int, str, int)
    format_update = Signal(int, str)
    speed_update = Signal(int, str, str)
    file_ready = Signal(int, str)
    live_status = Signal(str)
    item_notification = Signal(str, str)
    log = Signal(str)
    done = Signal(int, int, bool)

    def __init__(
        self,
        items,
        quality,
        quality_mode,
        file_format,
        output_dir,
        ffmpeg_path,
        subtitle_mode,
        subtitle_langs,
        audio_bitrate,
        cookies_browser,
        cookies_file,
        download_thumbnail,
        embed_metadata,
        speed_limit_mbps,
        fragment_concurrency,
        filename_template,
        auto_container,
        codec_preference,
        audio_preference,
        sort_media_folders,
        platform_sort_folders,
        subtitle_optional,
        debug_mode,
    ):
        super().__init__()
        self.items = items
        self.quality = quality
        self.quality_mode = quality_mode
        self.file_format = file_format
        self.output_dir = output_dir
        self.ffmpeg_path = resolve_ffmpeg(ffmpeg_path)
        self.subtitle_mode = subtitle_mode
        self.subtitle_langs = subtitle_langs
        self.audio_bitrate = audio_bitrate
        self.cookies_browser = cookies_browser
        self.cookies_file = cookies_file
        self.download_thumbnail = download_thumbnail
        self.embed_metadata = embed_metadata
        self.speed_limit_mbps = speed_limit_mbps
        self.fragment_concurrency = fragment_concurrency
        self.filename_template = filename_template
        self.auto_container = auto_container
        self.codec_preference = codec_preference
        self.audio_preference = audio_preference
        self.sort_media_folders = sort_media_folders
        self.platform_sort_folders = platform_sort_folders
        self.subtitle_optional = subtitle_optional
        self.current_item = None
        self.debug_mode = debug_mode
        self._cancel_requested = False
        self.current_row = 0
        self.last_speed_log = 0
        self.last_speed_log_by_row = {}
        self.row_percents = [0 for _ in items]
        self.current_status = "Queued"
        self.last_live_status = 0
        self.output_candidates = {}
        self.state_lock = threading.RLock()

    def request_cancel(self):
        self._cancel_requested = True
        self.requestInterruption()

    def emit_live_status(self, text, force=False):
        now = time.time()
        with self.state_lock:
            should_emit = force or now - self.last_live_status >= 0.7
            if should_emit:
                self.last_live_status = now
        if should_emit:
            self.live_status.emit(text)

    def set_post_status(self, status, message=None, row=None):
        try:
            row = self.current_row if row is None else row
            with self.state_lock:
                self.current_status = status
                percent = self.row_percents[row]
            self.row_update.emit(row, status, percent)
            self.emit_live_status(message or status, force=True)
        except Exception:
            return

    def extract_quoted_path(self, text):
        match = re.search(r'["\u201c](.+?)["\u201d]', text)
        if match:
            return match.group(1)
        return None

    def remember_output_candidate(self, path, row=None):
        if path:
            row = self.current_row if row is None else row
            with self.state_lock:
                self.output_candidates[row] = path

    def is_video_download(self):
        return self.file_format in VIDEO_FORMATS

    def is_image_download(self):
        return self.file_format in IMAGE_FORMATS

    def requested_quality_height(self):
        return QUALITY_HEIGHTS.get(self.quality)

    def effective_container(self):
        container = self.file_format.split()[0].lower()
        height = self.requested_quality_height()
        if (
            self.auto_container
            and self.file_format == "MP4 Video"
            and height
            and height >= 1440
        ):
            return "mkv"
        return container

    def update_progress(self, row, percent):
        with self.state_lock:
            self.row_percents[row] = max(0, min(100, percent))
            total = sum(self.row_percents) / max(1, len(self.row_percents))
            row_percent = self.row_percents[row]
        self.progress.emit(int(total))
        self.row_update.emit(row, "Downloading", row_percent)

    def progress_hook(self, d, row=None):
        row = self.current_row if row is None else row
        if self._cancel_requested or self.isInterruptionRequested():
            raise DownloadCancelled("Download dibatalkan.")

        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes", 0)

            if total:
                percent = int(downloaded / total * 100)
                self.update_progress(row, percent)

            now = time.time()
            speed = d.get("speed")
            eta = d.get("eta")
            last_speed_log = self.last_speed_log_by_row.get(row, 0)
            if now - last_speed_log >= 1:
                speed_text = human_speed(speed)
                eta_text = human_eta(eta)
                with self.state_lock:
                    percent_text = f"{self.row_percents[row]}%"
                self.speed_update.emit(row, speed_text, eta_text)
                self.emit_live_status(
                    f"Downloading • {percent_text} • {speed_text} • ETA {eta_text}"
                )
                self.last_speed_log_by_row[row] = now

        elif d["status"] == "finished":
            finished_percent = 95 if self.should_defer_postprocessing() else 100
            with self.state_lock:
                self.row_percents[row] = finished_percent
                total = sum(self.row_percents) / max(1, len(self.row_percents))
            self.progress.emit(int(total))
            self.row_update.emit(row, "Downloaded", finished_percent)
            if self.should_defer_postprocessing():
                self.emit_live_status("Download finished. Merge can run while other downloads continue.", force=True)
                self.log.emit("Download finished. Merge queued.")
            else:
                self.emit_live_status(
                    "Post-processing with FFmpeg... please wait",
                    force=True,
                )
                self.log.emit("Download started post-processing.")

    def build_video_format(self, item=None):
        height = self.requested_quality_height()
        platform = (item or {}).get("platform") or "Other"
        if platform in SOCIAL_VIDEO_PLATFORMS:
            return "bestvideo*+bestaudio/best"
        has_ffmpeg = bool(self.ffmpeg_path)
        audio_selector = AUDIO_SELECTORS.get(self.audio_preference, "ba")
        codec_filter = CODEC_FILTERS.get(self.codec_preference)

        def vf(selector):
            if codec_filter:
                return f"{selector}[{codec_filter}]"
            return selector

        def merged(video_selector):
            return f"{vf(video_selector)}+{audio_selector}"

        if not height:
            if not has_ffmpeg:
                return "best"
            if codec_filter or self.audio_preference != "Auto":
                return f"{merged('bv*')}/bv*+ba/best"
            return "bv*+ba/best"

        if self.quality_mode == "Best up to selected":
            if has_ffmpeg:
                preferred = (
                    f"{merged(f'bv*[height<={height}]')}/"
                    f"{merged(f'bv*[width<={height}]')}"
                )
                fallback = (
                    f"bv*[height<={height}]+ba/"
                    f"bv*[width<={height}]+ba/"
                    f"b[height<={height}]/"
                    f"b[width<={height}]"
                )
                return f"{preferred}/{fallback}"
            return f"b[height<={height}]/b[width<={height}]"

        if has_ffmpeg:
            preferred = (
                f"{merged(f'bv*[height={height}]')}/"
                f"{merged(f'bv*[width={height}]')}"
            )
            fallback = (
                f"bv*[height={height}]+ba/"
                f"bv*[width={height}]+ba/"
                f"b[height={height}]/"
                f"b[width={height}]"
            )
            return f"{preferred}/{fallback}"
        return f"b[height={height}]/b[width={height}]"

    def build_subtitle_langs(self):
        langs = [
            lang.strip()
            for lang in self.subtitle_langs.split(",")
            if lang.strip()
        ]
        return langs or ["id", "en"]

    def output_template(self, item):
        if item.get("platform") in SOCIAL_VIDEO_PLATFORMS:
            fallback_uploader = item.get("platform") or "Social"
            template = f"%(uploader|{fallback_uploader})s - %(title).80s [%(id)s].%(ext)s"
        else:
            template = FILENAME_TEMPLATES.get(
                self.filename_template,
                FILENAME_TEMPLATES["Title [ID]"],
            )
        if self.filename_template == "Playlist index - Title [ID]" and item.get("playlist_index"):
            template = f"{int(item['playlist_index']):03d} - %(title).180s [%(id)s].%(ext)s"
        folder = self.output_folder(item)
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, template)

    def output_folder(self, item=None, output_ext=None):
        folder = self.output_dir
        item = item or {}
        if self.platform_sort_folders:
            folder = os.path.join(folder, safe_platform_folder(item.get("platform")))
        if self.sort_media_folders:
            media_type = detect_media_type(self.file_format, output_ext)
            folder = os.path.join(folder, media_type)
        return folder

    def add_cookie_opts(self, opts):
        add_cookie_opts(opts, self.cookies_browser, self.cookies_file)

    def build_image_metadata_opts(self):
        opts = {
            "quiet": not self.debug_mode,
            "verbose": self.debug_mode,
            "no_warnings": False,
            "noplaylist": True,
            "skip_download": True,
            "ignore_no_formats_error": True,
            "windowsfilenames": True,
        }
        self.add_cookie_opts(opts)
        return opts

    def image_headers(self, item=None, info=None, candidate=None):
        platform = (item or {}).get("platform") or detect_platform_from_info(info or {}, (item or {}).get("url"))
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0 Safari/537.36"
            )
        }
        if platform == "Instagram":
            headers["Referer"] = "https://www.instagram.com/"
        elif platform == "TikTok":
            headers["Referer"] = "https://www.tiktok.com/"
        elif platform == "Twitter-X":
            headers["Referer"] = "https://x.com/"
        elif platform == "YouTube":
            headers["Referer"] = "https://www.youtube.com/"
        headers.update((info or {}).get("http_headers") or {})
        headers.update((candidate or {}).get("headers") or {})
        return headers

    def collect_images_from_info(self, info, item=None):
        platform = (item or {}).get("platform") or detect_platform_from_info(info or {}, (item or {}).get("url"))
        headers = self.image_headers(item, info)
        candidates = {}
        collect_image_candidates(info or {}, candidates, platform=platform, headers=headers, source="metadata")
        return best_image_candidates(candidates.values(), platform=platform)

    def collect_images_from_page(self, ydl, item):
        platform = item.get("platform") or detect_platform_from_info({}, item.get("url"))
        headers = self.image_headers(item)
        request = urllib.request.Request(item["url"], headers=headers)
        response = ydl.urlopen(request)
        try:
            page = response.read().decode("utf-8", errors="replace")
        finally:
            close = getattr(response, "close", None)
            if close:
                close()
        return best_image_candidates(
            image_candidates_from_text(page, platform=platform, headers=headers),
            platform=platform,
        )

    def image_output_path(self, item, candidate, index=1, total=1, ext=None):
        folder = self.output_folder(item, output_ext=ext or image_ext_from_url(candidate.get("url")) or "jpg")
        os.makedirs(folder, exist_ok=True)
        title = safe_filename_component(item.get("title") or item.get("url"), "image")
        media_id = safe_filename_component(item.get("video_id") or item.get("key") or "image", "image")
        suffix = f" - {index:02d}" if total > 1 else ""
        extension = ext or image_ext_from_url(candidate.get("url")) or "jpg"
        path = os.path.join(folder, f"{title} [{media_id}]{suffix}.{extension}")
        if not os.path.exists(path):
            return path
        base, current_ext = os.path.splitext(path)
        counter = 2
        while True:
            candidate_path = f"{base}-{counter}{current_ext}"
            if not os.path.exists(candidate_path):
                return candidate_path
            counter += 1

    def download_image_file(self, ydl, item, candidate, index=1, total=1):
        headers = self.image_headers(item, candidate=candidate)
        request = urllib.request.Request(candidate["url"], headers=headers)
        response = ydl.urlopen(request)
        try:
            content_type = response.headers.get("Content-Type") if response.headers else None
            ext = image_ext_from_content_type(content_type) or image_ext_from_url(candidate["url"]) or "jpg"
            output_path = self.image_output_path(item, candidate, index=index, total=total, ext=ext)
            total_bytes = response.headers.get("Content-Length") if response.headers else None
            try:
                total_bytes = int(total_bytes) if total_bytes else 0
            except (TypeError, ValueError):
                total_bytes = 0

            downloaded = 0
            with open(output_path, "wb") as file:
                while True:
                    if self._cancel_requested or self.isInterruptionRequested():
                        raise DownloadCancelled("Download dibatalkan.")
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    file.write(chunk)
                    downloaded += len(chunk)
                    if total_bytes:
                        item_fraction = downloaded / max(1, total_bytes)
                        percent = int(((index - 1) + item_fraction) / max(1, total) * 100)
                        self.update_progress(self.current_row, percent)

            if not total_bytes:
                percent = int(index / max(1, total) * 100)
                self.update_progress(self.current_row, percent)
            return output_path
        finally:
            close = getattr(response, "close", None)
            if close:
                close()

    def download_images(self, item, row=None):
        self.current_item = item
        self.current_row = self.current_row if row is None else row
        platform = item.get("platform") or detect_platform_from_info({}, item.get("url"))
        item["platform"] = platform
        self.log.emit("Mode gambar: mengambil URL gambar resolusi tertinggi...")

        info = None
        with yt_dlp.YoutubeDL(self.build_image_metadata_opts()) as ydl:
            try:
                info = ydl.extract_info(item["url"], download=False)
            except Exception as e:
                self.log.emit(f"Metadata video tidak tersedia untuk gambar, coba baca halaman: {e}")

            candidates = self.collect_images_from_info(info, item=item)
            if not candidates:
                candidates = self.collect_images_from_page(ydl, item)

            if not candidates:
                raise ValueError("Tidak menemukan URL gambar resolusi asli untuk link ini.")

            if info:
                item["title"] = info.get("title") or item.get("title") or item.get("url")
                item["video_id"] = info.get("id") or item.get("video_id") or item.get("key")

            downloaded = []
            total = len(candidates)
            for index, candidate in enumerate(candidates, start=1):
                if self._cancel_requested or self.isInterruptionRequested():
                    raise DownloadCancelled("Download dibatalkan.")
                self.log.emit(f"Download gambar {index}/{total}: {candidate['url']}")
                path = self.download_image_file(ydl, item, candidate, index=index, total=total)
                downloaded.append({
                    "filepath": path,
                    "width": candidate.get("width"),
                    "height": candidate.get("height"),
                    "url": candidate.get("url"),
                })

        return {
            "id": item.get("video_id") or item.get("key"),
            "title": item.get("title"),
            "ext": os.path.splitext(downloaded[0]["filepath"])[1].lstrip(".") if downloaded else None,
            "filepath": downloaded[0]["filepath"] if downloaded else None,
            "downloaded_images": downloaded,
        }

    def postprocessor_hook(self, d, row=None):
        row = self.current_row if row is None else row
        try:
            if self._cancel_requested or self.isInterruptionRequested():
                raise DownloadCancelled("Download dibatalkan.")
            pp = d.get("postprocessor") or d.get("postprocessor_name") or ""
            status = d.get("status") or ""
            name = str(pp)
            name_lower = name.lower()
            if "merger" in name_lower or "ffmpegmerger" in name_lower:
                mapped = "Merging"
                message = "Merging large file. This may take a while depending on disk speed."
            elif "extractaudio" in name_lower:
                mapped = "Post-processing"
                message = "Converting audio with FFmpeg..."
            elif "embedsubtitle" in name_lower:
                mapped = "Post-processing"
                message = "Embedding subtitles..."
            elif "embedthumbnail" in name_lower:
                mapped = "Post-processing"
                message = "Embedding thumbnail..."
            elif "metadata" in name_lower:
                mapped = "Post-processing"
                message = "Writing metadata..."
            elif "movefiles" in name_lower:
                mapped = "Moving final file"
                message = "Moving final file..."
            else:
                mapped = "Post-processing"
                message = f"Post-processing with FFmpeg... {name}" if name else "Post-processing with FFmpeg..."

            if status in {"started", "processing"}:
                self.set_post_status(mapped, message, row=row)
            elif status == "finished":
                self.set_post_status("Post-processing", "Post-processing finished. Finalizing...", row=row)
                info = d.get("info_dict") or {}
                path = info.get("filepath") or info.get("_filename") or info.get("filename")
                self.remember_output_candidate(path, row=row)
        except DownloadCancelled:
            raise
        except Exception:
            return

    def build_ydl_opts(self, item, subtitle_mode=None, row=None):
        active_subtitle_mode = self.subtitle_mode if subtitle_mode is None else subtitle_mode
        opts = {
            "outtmpl": self.output_template(item),
            "progress_hooks": [lambda d, row=row: self.progress_hook(d, row=row)],
            "postprocessor_hooks": [lambda d, row=row: self.postprocessor_hook(d, row=row)],
            "logger": YtdlpStatusLogger(self, row=row),
            "noplaylist": True,
            "quiet": not self.debug_mode,
            "verbose": self.debug_mode,
            "no_warnings": False,
            "continuedl": True,
            "retries": 10,
            "fragment_retries": 10,
            "concurrent_fragment_downloads": self.fragment_concurrency,
            "windowsfilenames": True,
            "trim_file_name": 180,
        }
        self.add_cookie_opts(opts)

        if self.speed_limit_mbps:
            opts["ratelimit"] = self.speed_limit_mbps * 1024 * 1024

        if self.ffmpeg_path:
            opts["ffmpeg_location"] = os.path.dirname(self.ffmpeg_path)

        if self.download_thumbnail or self.embed_metadata:
            opts["writethumbnail"] = True

        postprocessors = []

        if active_subtitle_mode != "Off":
            langs = self.build_subtitle_langs()
            opts["subtitleslangs"] = langs
            opts["subtitlesformat"] = "srt/best"
            opts["convertsubtitles"] = "srt"
            opts["writesubtitles"] = active_subtitle_mode in {"Manual only", "Manual + Auto"}
            opts["writeautomaticsub"] = active_subtitle_mode in {"Auto only", "Manual + Auto"}

        if self.file_format in AUDIO_FORMATS:
            codec = self.file_format.split()[0].lower()
            if self.audio_preference == "M4A":
                opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"
            elif self.audio_preference == "Opus":
                opts["format"] = "bestaudio[acodec^=opus]/bestaudio/best"
            else:
                opts["format"] = "bestaudio/best"
            postprocessors.append({
                "key": "FFmpegExtractAudio",
                "preferredcodec": codec,
                "preferredquality": str(self.audio_bitrate),
            })
        else:
            opts["format"] = self.build_video_format(item)
            if self.ffmpeg_path:
                opts["merge_output_format"] = self.effective_container()

        if self.embed_metadata:
            postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})
            postprocessors.append({"key": "EmbedThumbnail"})

        if postprocessors:
            opts["postprocessors"] = postprocessors

        return opts

    def is_subtitle_error(self, error):
        message = str(error).lower()
        return (
            "subtitle" in message
            or "subtitles" in message
            or "requested subtitles are not available" in message
        )

    def output_path_from_info(self, info, item=None, row=None):
        if not info:
            return None

        downloaded_images = info.get("downloaded_images") or []
        if downloaded_images:
            first_image = downloaded_images[0].get("filepath")
            if first_image and os.path.exists(first_image):
                return first_image

        after_move = info.get("__finaldir") or info.get("filepath")
        if after_move and os.path.exists(after_move):
            return after_move

        if row is not None:
            with self.state_lock:
                candidate = self.output_candidates.get(row)
            if candidate and os.path.exists(candidate):
                return candidate

        downloads = info.get("requested_downloads") or []
        for downloaded in downloads:
            for key in ("filepath", "filename", "_filename"):
                path = downloaded.get(key)
                if path and os.path.exists(path) and not self.is_temporary_path(path):
                    return path

        requested = info.get("requested_formats") or []
        for downloaded in requested:
            path = downloaded.get("filepath") or downloaded.get("_filename")
            if path and os.path.exists(path) and not self.is_temporary_path(path):
                return path

        for key in ("filepath", "_filename", "filename"):
            path = info.get(key)
            if path and os.path.exists(path) and not self.is_temporary_path(path):
                return path

        output_ext = info.get("ext") if info else None
        return self.scan_output_for_final_file(item or info, output_ext=output_ext)

    def is_temporary_path(self, path):
        lower = str(path).lower()
        return lower.endswith((".part", ".ytdl", ".temp", ".tmp"))

    def scan_output_for_final_file(self, item, output_ext=None):
        if not item:
            return None
        title = re.sub(r'[<>:"/\\|?*]+', "", item.get("title") or "")
        video_id = item.get("video_id") or item.get("key")
        candidates = []
        folder = self.output_folder(item, output_ext=output_ext)
        try:
            for root, _, files in os.walk(folder):
                for name in files:
                    if self.is_temporary_path(name):
                        continue
                    full_path = os.path.join(root, name)
                    if video_id and video_id in name:
                        return full_path
                    if title and title[:50].lower() in name.lower():
                        candidates.append(full_path)
        except OSError:
            return None
        if candidates:
            candidates.sort(key=lambda path: os.path.getmtime(path), reverse=True)
            return candidates[0]

        return None

    def format_matches_quality(self, fmt, requested_height):
        if not fmt or fmt.get("vcodec") in (None, "none"):
            return False
        return fmt.get("height") == requested_height or fmt.get("width") == requested_height

    def precheck_video_quality(self, item):
        if not self.is_video_download():
            return
        platform = item.get("platform") or "Other"
        if self.quality_mode != "Exact only":
            return

        requested_height = self.requested_quality_height()
        if not requested_height:
            return

        formats = item.get("formats") or []
        if not formats:
            opts = {"quiet": True, "no_warnings": True, "noplaylist": True}
            self.add_cookie_opts(opts)
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(item["url"], download=False)
            formats = info.get("formats") or []

        self.log.emit(
            f"Resolusi tersedia: {available_video_quality_summary(formats, include_size=True)}"
        )
        if any(self.format_matches_quality(fmt, requested_height) for fmt in formats):
            return

        highest = highest_available_quality(formats)
        if platform in SOCIAL_VIDEO_PLATFORMS:
            label = PLATFORM_LABELS.get(platform, platform)
            self.log.emit(f"{label} format fallback to best available")
            self.log.emit(f"Resolusi {label} tertinggi yang terdeteksi: {highest}.")
            return
        raise ValueError(
            f"{self.quality} tidak tersedia untuk video ini. "
            f"Resolusi tertinggi yang terdeteksi: {highest}."
        )

    def format_details(self, info):
        if not info:
            return None

        requested_formats = info.get("requested_formats") or []
        video_format = next(
            (
                fmt
                for fmt in requested_formats
                if fmt.get("vcodec") and fmt.get("vcodec") != "none"
            ),
            None,
        )
        format_info = video_format or info
        width = format_info.get("width")
        height = format_info.get("height")
        fps = format_info.get("fps")
        vcodec = format_info.get("vcodec")
        acodec = info.get("acodec")
        ext = info.get("ext")
        format_id = info.get("format_id")

        if requested_formats:
            format_id = "+".join(
                str(fmt.get("format_id"))
                for fmt in requested_formats
                if fmt.get("format_id")
            ) or format_id
            audio_format = next(
                (
                    fmt
                    for fmt in requested_formats
                    if fmt.get("acodec") and fmt.get("acodec") != "none"
                ),
                None,
            )
            if audio_format:
                acodec = audio_format.get("acodec")

        parts = []
        if width and height:
            parts.append(f"{width}x{height}")
        elif height:
            parts.append(f"{height}p")
        if fps:
            parts.append(f"{fps}fps")
        if ext:
            parts.append(f"container {ext}")
        if format_id:
            parts.append(f"format {format_id}")
        if vcodec and vcodec != "none":
            parts.append(f"video {vcodec}")
        if acodec and acodec != "none":
            parts.append(f"audio {acodec}")

        return ", ".join(parts) if parts else None

    def friendly_error(self, error, item=None):
        message = str(error)
        if "Requested format is not available" in message:
            if self.quality_mode == "Exact only":
                return (
                    f"{self.quality} tidak tersedia untuk video ini. "
                    "Coba Cek Resolusi, pilih Best up to selected, atau pilih Best available."
                )
            return "Format yang diminta tidak tersedia. Coba pilih Best available."
        if self.is_subtitle_error(error):
            return (
                "Subtitle gagal didownload. Video bisa tetap diunduh dengan Subtitle = Off, "
                "atau coba bahasa lain / cookies browser."
            )
        platform = (item or self.current_item or {}).get("platform") if hasattr(self, "current_item") else None
        if platform in SOCIAL_VIDEO_PLATFORMS or any(
            keyword in message.lower()
            for keyword in ("tiktok", "instagram", "twitter", "x.com")
        ):
            label = PLATFORM_LABELS.get(platform, platform or "platform ini")
            return (
                f"{label} kadang membutuhkan update yt-dlp, cookies browser, atau cookies.txt. "
                "Untuk konten private/age-restricted, pastikan browser sudah login. "
                f"Detail: {message}"
            )
        if isinstance(error, ValueError):
            return message
        return f"Error: {message}"

    def should_use_parallel_pipeline(self):
        return len(self.items) > 1

    def should_defer_postprocessing(self):
        return self.is_video_download() and bool(self.ffmpeg_path) and len(self.items) > 1

    def download_item(self, item, subtitle_mode=None, defer_postprocessing=False, row=None):
        if self.is_image_download():
            return self.download_images(item, row=row)

        ydl_opts = self.build_ydl_opts(item, subtitle_mode=subtitle_mode, row=row)
        self.log.emit(f"Selector yt-dlp: {ydl_opts.get('format')}")
        if defer_postprocessing:
            ydl = DeferredPostProcessYoutubeDL(ydl_opts)
            ydl.__enter__()
            try:
                info = ydl.extract_info(item["url"], download=True)
                return {"ydl": ydl, "info": info}
            except Exception:
                ydl.__exit__(*sys.exc_info())
                raise
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(item["url"], download=True)

    def close_deferred_record(self, record):
        ydl = (record or {}).get("ydl")
        if not ydl or record.get("closed"):
            return
        record["closed"] = True
        ydl.__exit__(None, None, None)

    def run_deferred_postprocessing(self, record):
        ydl = record["ydl"]
        info = ydl.run_deferred_post_processes() or record.get("info")
        record["info"] = info
        return info

    def finalize_successful_item(self, index, item, info):
        downloaded_images = (info or {}).get("downloaded_images") or []
        if downloaded_images:
            first = downloaded_images[0]
            count = len(downloaded_images)
            dimensions = []
            if first.get("width") and first.get("height"):
                dimensions.append(f"{first['width']}x{first['height']}")
            dimensions.append(os.path.splitext(first.get("filepath") or "")[1].lstrip(".").upper() or "IMAGE")
            details = f"{count} image" if count == 1 else f"{count} images"
            if dimensions:
                details = f"{details} ({', '.join(dimensions)})"
            self.log.emit(f"Gambar tersimpan: {count} file.")
        else:
            details = self.format_details(info)
        if details:
            item["actual_format"] = details
            self.format_update.emit(index, details)
            self.log.emit(f"Resolusi/format aktual: {details}")

        output_path = self.output_path_from_info(info, item=item, row=index)
        if output_path:
            item["output_path"] = output_path
            self.file_ready.emit(index, output_path)
            self.log.emit(f"Final file saved: {output_path}")
        else:
            self.log.emit("Final file saved: Unknown")

        with self.state_lock:
            self.row_percents[index] = 100
            self.current_status = "Done"
            total = sum(self.row_percents) / len(self.row_percents)
        self.speed_update.emit(index, "-", "-")
        self.row_update.emit(index, "Done" if output_path else "Done with warning", 100)
        self.progress.emit(int(total))
        self.emit_live_status(f"Done • {item.get('title')}", force=True)
        self.item_notification.emit("Download complete", item.get("title") or "Item complete")
        self.log.emit("Completed.")
        return output_path

    def validate_requirements(self):
        if self.file_format in AUDIO_FORMATS and not self.ffmpeg_path:
            raise ValueError("Audio MP3/M4A/WAV butuh FFmpeg. Isi FFmpeg path atau install FFmpeg.")

        if self.is_video_download() and self.file_format == "MKV Video" and not self.ffmpeg_path:
            raise ValueError("Output MKV butuh FFmpeg. Isi FFmpeg path atau install FFmpeg.")

        requested_height = self.requested_quality_height()
        if self.is_video_download() and requested_height and requested_height >= 1440 and not self.ffmpeg_path:
            raise ValueError(
                f"Download {self.quality} butuh FFmpeg karena YouTube biasanya menyediakan "
                "resolusi tinggi sebagai video dan audio terpisah."
            )

        if self.embed_metadata and not self.ffmpeg_path:
            raise ValueError("Embed metadata/thumbnail butuh FFmpeg.")

    def download_pipeline_item(self, index, item):
        if self._cancel_requested or self.isInterruptionRequested():
            raise DownloadCancelled("Download dibatalkan.")

        self.current_item = item
        self.current_row = index
        self.current_status = "Downloading"
        self.last_speed_log_by_row[index] = 0
        self.row_update.emit(index, "Checking", 0)
        self.emit_live_status(f"Checking metadata • {item.get('title')}", force=True)
        self.log.emit(f"Download phase {index + 1}/{len(self.items)}: {item.get('title')}")
        self.log.emit(f"Detected platform: {item.get('platform', 'Other')}")
        if item.get("platform") in SOCIAL_VIDEO_PLATFORMS:
            self.log.emit(social_platform_cookie_hint(item.get("platform")))
        self.log.emit(f"URL: {item['url']}")

        self.precheck_video_quality(item)
        self.row_update.emit(index, "Downloading", 0)
        defer_pp = self.should_defer_postprocessing()
        try:
            info_or_record = self.download_item(item, defer_postprocessing=defer_pp, row=index)
        except Exception as e:
            if (
                self.subtitle_mode == "Off"
                or not self.subtitle_optional
                or not self.is_subtitle_error(e)
            ):
                raise
            self.log.emit(
                "Subtitle gagal atau kena rate limit. Retry download video tanpa subtitle..."
            )
            info_or_record = self.download_item(
                item,
                subtitle_mode="Off",
                defer_postprocessing=defer_pp,
                row=index,
            )

        if defer_pp:
            record = info_or_record
            next_status = "Downloaded"
            next_message = f"Downloaded • merge queued • {item.get('title')}"
            next_log = "Download complete. Merge queued."
        else:
            record = {
                "ydl": None,
                "info": info_or_record,
                "no_merge": True,
            }
            next_status = "Downloaded"
            next_message = f"Downloaded • finalizing • {item.get('title')}"
            next_log = "Download complete. Finalizing without deferred merge."

        with self.state_lock:
            self.row_percents[index] = 95
            total = sum(self.row_percents) / max(1, len(self.row_percents))
        self.progress.emit(int(total))
        self.speed_update.emit(index, "-", "-")
        self.row_update.emit(index, next_status, 95)
        self.emit_live_status(next_message, force=True)
        self.log.emit(next_log)
        return record

    def merge_pipeline_item(self, index, item, record):
        if self._cancel_requested or self.isInterruptionRequested():
            raise DownloadCancelled("Download dibatalkan.")

        self.current_item = item
        self.current_row = index
        self.current_status = "Merging"
        with self.state_lock:
            percent = self.row_percents[index]
        self.row_update.emit(index, "Merging", percent)
        self.emit_live_status(f"Merging • {item.get('title')}", force=True)
        self.log.emit(f"Merge phase {index + 1}/{len(self.items)}: {item.get('title')}")

        try:
            if record.get("no_merge"):
                info = record.get("info")
                self.finalize_successful_item(index, item, info)
                return info

            info = self.run_deferred_postprocessing(record)
            self.finalize_successful_item(index, item, info)
            return info
        finally:
            self.close_deferred_record(record)

    def run_pipeline_download_and_merge(self):
        success_count = 0
        failed_count = 0
        canceled = False
        deferred_records = []
        terminal_rows = set()

        self.log.emit(
            f"Pipeline mode aktif: maksimal {MAX_ACTIVE_DOWNLOADS} download aktif, "
            f"merge maksimal {MAX_ACTIVE_MERGES} aktif."
        )

        download_executor = ThreadPoolExecutor(max_workers=MAX_ACTIVE_DOWNLOADS)
        merge_executor = ThreadPoolExecutor(max_workers=MAX_ACTIVE_MERGES)
        download_futures = {}
        merge_futures = {}
        next_index = 0

        def submit_downloads():
            nonlocal next_index
            while (
                next_index < len(self.items)
                and len(download_futures) < MAX_ACTIVE_DOWNLOADS
                and not self._cancel_requested
                and not self.isInterruptionRequested()
            ):
                item = self.items[next_index]
                future = download_executor.submit(self.download_pipeline_item, next_index, item)
                download_futures[future] = (next_index, item)
                next_index += 1

        submit_downloads()

        try:
            while download_futures or merge_futures:
                if self._cancel_requested or self.isInterruptionRequested():
                    canceled = True
                    break

                active_futures = set(download_futures) | set(merge_futures)
                done_futures, _ = wait(active_futures, timeout=0.2, return_when=FIRST_COMPLETED)
                if not done_futures:
                    continue

                for future in done_futures:
                    if future in download_futures:
                        index, item = download_futures.pop(future)
                        try:
                            record = future.result()
                            deferred_records.append(record)
                            merge_future = merge_executor.submit(
                                self.merge_pipeline_item,
                                index,
                                item,
                                record,
                            )
                            merge_futures[merge_future] = (index, item, record)
                        except DownloadCancelled:
                            canceled = True
                            terminal_rows.add(index)
                            self.row_update.emit(index, "Canceled", 0)
                            self.log.emit("Download dibatalkan.")
                        except Exception as e:
                            failed_count += 1
                            terminal_rows.add(index)
                            self.row_update.emit(index, "Failed", 0)
                            self.item_notification.emit("Download failed", item.get("title") or str(e))
                            self.log.emit(self.friendly_error(e, item=item))
                        submit_downloads()
                    elif future in merge_futures:
                        index, item, record = merge_futures.pop(future)
                        try:
                            future.result()
                            success_count += 1
                            terminal_rows.add(index)
                        except DownloadCancelled:
                            canceled = True
                            terminal_rows.add(index)
                            self.row_update.emit(index, "Canceled", 0)
                            self.log.emit("Download dibatalkan.")
                        except Exception as e:
                            failed_count += 1
                            terminal_rows.add(index)
                            self.row_update.emit(index, "Failed", 0)
                            self.item_notification.emit("Download failed", item.get("title") or str(e))
                            self.log.emit(self.friendly_error(e, item=item))
                        finally:
                            self.close_deferred_record(record)
        finally:
            for future in download_futures:
                future.cancel()
            for future in merge_futures:
                future.cancel()
            wait_for_threads = not (canceled or self._cancel_requested or self.isInterruptionRequested())
            download_executor.shutdown(wait=wait_for_threads, cancel_futures=True)
            merge_executor.shutdown(wait=wait_for_threads, cancel_futures=True)

        for record in deferred_records:
            self.close_deferred_record(record)

        if canceled:
            for row in range(len(self.items)):
                if row not in terminal_rows:
                    self.row_update.emit(row, "Canceled", 0)

        return success_count, failed_count, canceled

    def run(self):
        success_count = 0
        failed_count = 0
        canceled = False

        try:
            os.makedirs(self.output_dir, exist_ok=True)
            self.validate_requirements()

            if self.ffmpeg_path:
                self.log.emit(f"FFmpeg aktif: {self.ffmpeg_path}")
            else:
                self.log.emit(
                    "FFmpeg tidak ditemukan. Video hanya bisa memakai format single-file yang tersedia."
                )

            if self.subtitle_mode != "Off":
                self.log.emit(
                    f"Subtitle: {self.subtitle_mode} ({', '.join(self.build_subtitle_langs())})"
                )

            if self.auto_container and self.file_format == "MP4 Video" and self.effective_container() == "mkv":
                self.log.emit("Auto container aktif: output 1440p/4K/8K diarahkan ke MKV.")

            if self.should_use_parallel_pipeline():
                success_count, failed_count, canceled = self.run_pipeline_download_and_merge()
                self.done.emit(success_count, failed_count, canceled)
                return

            for index, item in enumerate(self.items):
                if self._cancel_requested or self.isInterruptionRequested():
                    canceled = True
                    break

                self.current_item = item
                self.current_row = index
                self.last_speed_log = 0
                self.current_status = "Checking"
                self.row_update.emit(index, "Checking", 0)
                self.emit_live_status(f"Checking metadata • {item.get('title')}", force=True)
                self.log.emit(f"Download started {index + 1}/{len(self.items)}: {item.get('title')}")
                self.log.emit(f"Detected platform: {item.get('platform', 'Other')}")
                if item.get("platform") in SOCIAL_VIDEO_PLATFORMS:
                    self.log.emit(social_platform_cookie_hint(item.get("platform")))
                self.log.emit(f"URL: {item['url']}")

                try:
                    self.precheck_video_quality(item)
                    self.row_update.emit(index, "Downloading", 0)
                    try:
                        info = self.download_item(item, row=index)
                    except Exception as e:
                        if (
                            self.subtitle_mode == "Off"
                            or not self.subtitle_optional
                            or not self.is_subtitle_error(e)
                        ):
                            raise
                        self.log.emit(
                            "Subtitle gagal atau kena rate limit. Retry download video tanpa subtitle..."
                        )
                        info = self.download_item(item, subtitle_mode="Off", row=index)

                    self.finalize_successful_item(index, item, info)
                    success_count += 1
                except DownloadCancelled:
                    canceled = True
                    self.row_update.emit(index, "Canceled", 0)
                    self.log.emit("Download dibatalkan.")
                    break
                except Exception as e:
                    failed_count += 1
                    self.row_update.emit(index, "Failed", 0)
                    self.item_notification.emit("Download failed", item.get("title") or str(e))
                    self.log.emit(self.friendly_error(e, item=item))

            if canceled:
                for row in range(self.current_row + 1, len(self.items)):
                    self.row_update.emit(row, "Canceled", 0)

            self.done.emit(success_count, failed_count, canceled)

        except Exception as e:
            for row in range(len(self.items)):
                self.row_update.emit(row, "Failed", 0)
            self.log.emit(self.friendly_error(e))
            self.done.emit(success_count, failed_count + len(self.items), canceled)


class App(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        icon_path = os.path.join(getattr(sys, "_MEIPASS", APP_DIR), "assets", "tarikyt_icon.png")
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setMinimumSize(1060, 800)
        self.resize(1120, 860)
        self._drag_pos = None
        self.header_bar = None

        self.settings_data = {}
        self.theme_mode = "dark"
        self.default_output = os.path.join(os.path.expanduser("~"), "Downloads", "TarikYT")
        self.thread = None
        self.metadata_thread = None
        self.test_thread = None
        self.channel_thread = None
        self.update_thread = None
        self.queue_items = []
        self._last_checked_urls = []
        self.auto_start_after_check = False
        self.applying_preset = False
        self.updating_media_type = False
        self._last_video_format = "MP4 Video"
        self._last_audio_format = "MP3 Audio"
        self.history_loaded = False
        self.tray_icon = QSystemTrayIcon(self) if QSystemTrayIcon.isSystemTrayAvailable() else None

        self.create_widgets()
        self.build_layout()
        self._setup_shortcuts()
        self.load_settings_file()
        self.load_settings()
        self.apply_style()
        self.update_audio_controls(self.format_combo.currentText())
        self.refresh_ffmpeg_status()
        self.recover_previous_state()
        self.update_target_info()

    def create_widgets(self):
        self.urls_input = QTextEdit()
        self.urls_input.setPlaceholderText("Paste link YouTube, TikTok, Instagram, X/Twitter, atau playlist. Bisa banyak link, satu link per baris...")
        self.urls_input.setFixedHeight(46)
        self.urls_input.textChanged.connect(self.invalidate_queue)

        self.paste_btn = QPushButton("📋 Paste Link")
        self.paste_btn.setToolTip("Paste link langsung dari clipboard")
        self.paste_btn.setFixedHeight(24)
        self.paste_btn.clicked.connect(self.paste_from_clipboard)

        self.channel_url_input = QLineEdit()
        self.channel_url_input.setPlaceholderText("Paste link channel / playlist YouTube, contoh: https://www.youtube.com/@fikra1401/videos")
        self.channel_url_input.setFixedHeight(28)
        self.channel_preview_btn = QPushButton("Preview Channel / Playlist")
        self.channel_preview_btn.setFixedHeight(28)
        self.channel_preview_btn.clicked.connect(self.open_channel_preview)
        self.channel_keyword_input = QLineEdit()
        self.channel_keyword_input.setPlaceholderText("Keyword judul (direct filter), contoh: yeni inka / jkt48")
        self.channel_keyword_input.setFixedHeight(26)
        self.channel_fetch_btn = QPushButton("Ambil dari Channel")
        self.channel_fetch_btn.setFixedHeight(26)
        self.channel_fetch_btn.clicked.connect(self.fetch_channel_videos)
        self.channel_status_label = QLabel("")
        self.channel_status_label.setWordWrap(True)
        self.channel_status_label.setVisible(False)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Simple Mode", "Power Mode"])
        self.mode_combo.setFixedHeight(28)
        self.mode_combo.currentTextChanged.connect(self.apply_ui_mode)

        self.preset_label = QLabel("Preset profile")
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(PRESET_PROFILES))
        self.preset_combo.setFixedHeight(28)
        self.preset_combo.currentTextChanged.connect(self.apply_preset)

        self.quality_combo = QComboBox()
        self.quality_combo.addItems([
            "Best available",
            "8K / 4320p",
            "4K / 2160p",
            "1440p",
            "1080p",
            "720p",
            "480p",
            "360p",
        ])
        self.quality_combo.setFixedHeight(28)
        self.quality_combo.currentTextChanged.connect(self.mark_custom_preset)

        self.quality_mode_combo = QComboBox()
        self.quality_mode_combo.addItems(["Exact only", "Best up to selected"])
        self.quality_mode_combo.setFixedHeight(28)
        self.quality_mode_combo.currentTextChanged.connect(self.mark_custom_preset)

        self.format_label = QLabel("Format")
        self.format_combo = QComboBox()
        self.format_combo.addItems([
            "MP4 Video",
            "MKV Video",
            "WEBM Video",
            "Image",
            "MP3 Audio",
            "M4A Audio",
            "WAV Audio",
            "OPUS Audio",
            "FLAC Audio",
        ])
        self.format_combo.setFixedHeight(28)
        self.format_combo.currentTextChanged.connect(self.sync_media_type_from_format)
        self.format_combo.currentTextChanged.connect(self.update_audio_controls)
        self.format_combo.currentTextChanged.connect(self.mark_custom_preset)

        self.media_type_label = QLabel("Tipe")
        self.media_type_combo = QComboBox()
        self.media_type_combo.addItems(["Video", "Audio"])
        self.media_type_combo.setFixedHeight(28)
        self.media_type_combo.currentTextChanged.connect(self.on_media_type_changed)

        self.auto_container_checkbox = QCheckBox("Auto MKV untuk 1440p/4K/8K")
        self.auto_container_checkbox.setChecked(True)
        self.auto_container_checkbox.toggled.connect(self.mark_custom_preset)
        self.high_res_hint_label = QLabel("")
        self.high_res_hint_label.setWordWrap(True)
        self.power_download_controls = None

        self.audio_bitrate = QSpinBox()
        self.audio_bitrate.setRange(64, 320)
        self.audio_bitrate.setSingleStep(32)
        self.audio_bitrate.setSuffix(" kbps")
        self.audio_bitrate.setValue(192)
        self.audio_bitrate.setFixedHeight(28)
        self.audio_bitrate.valueChanged.connect(self.mark_custom_preset)

        self.output_input = QLineEdit(self.default_output)
        self.browse_btn = QPushButton("Pilih Folder")
        self.browse_btn.clicked.connect(self.choose_folder)
        self.open_folder_btn = QPushButton("Buka Folder")
        self.open_folder_btn.clicked.connect(self.open_selected_folder)
        self.output_open_folder_btn = QPushButton("Buka Folder")
        self.output_open_folder_btn.clicked.connect(self.open_output_folder)
        self.sort_media_checkbox = QCheckBox("Pisah folder Audio / Video")
        self.sort_media_checkbox.setChecked(True)
        self.platform_sort_checkbox = QCheckBox("Pisah folder berdasarkan platform")
        self.platform_sort_checkbox.setChecked(True)

        self.ffmpeg_input = QLineEdit()
        self.ffmpeg_input.setPlaceholderText("Kosongkan untuk auto-detect FFmpeg")
        self.ffmpeg_browse_btn = QPushButton("Pilih FFmpeg")
        self.ffmpeg_browse_btn.clicked.connect(self.choose_ffmpeg)
        self.ffmpeg_detect_btn = QPushButton("Auto Detect")
        self.ffmpeg_detect_btn.clicked.connect(self.autodetect_ffmpeg)
        self.ffmpeg_status_label = QLabel("FFmpeg: checking...")

        self.playlist_checkbox = QCheckBox("Seluruh playlist jika URL punya playlist")
        self.playlist_checkbox.setChecked(False)
        self.playlist_checkbox.toggled.connect(self.mark_custom_preset)
        self.playlist_start = QSpinBox()
        self.playlist_start.setRange(0, 9999)
        self.playlist_start.setSpecialValueText("Awal")
        self.playlist_end = QSpinBox()
        self.playlist_end.setRange(0, 9999)
        self.playlist_end.setSpecialValueText("Akhir")

        self.check_mode_combo = QComboBox()
        self.check_mode_combo.addItems(["Full check", "Fast check"])

        self.codec_combo = QComboBox()
        self.codec_combo.addItems(list(CODEC_FILTERS))
        self.audio_pref_combo = QComboBox()
        self.audio_pref_combo.addItems(list(AUDIO_SELECTORS))

        self.subtitle_mode_combo = QComboBox()
        self.subtitle_mode_combo.addItems(["Off", "Manual only", "Auto only", "Manual + Auto"])
        self.subtitle_mode_combo.currentTextChanged.connect(self.mark_custom_preset)
        self.subtitle_optional_checkbox = QCheckBox("Subtitle optional")
        self.subtitle_optional_checkbox.setChecked(True)
        self.subtitle_lang_input = QLineEdit("id,en")
        self.subtitle_lang_input.setPlaceholderText("Contoh: id,en atau en atau all")

        self.thumbnail_checkbox = QCheckBox("Download thumbnail")
        self.embed_metadata_checkbox = QCheckBox("Embed metadata + thumbnail")

        self.cookies_combo = QComboBox()
        self.cookies_combo.addItems(["None", "Chrome", "Edge", "Firefox"])
        self.cookies_file_input = QLineEdit()
        self.cookies_file_input.setPlaceholderText("cookies.txt opsional")
        self.cookies_file_btn = QPushButton("Cookies.txt")
        self.cookies_file_btn.clicked.connect(self.choose_cookies_file)

        self.speed_limit = QSpinBox()
        self.speed_limit.setRange(0, 200)
        self.speed_limit.setSuffix(" MB/s")
        self.speed_limit.setSpecialValueText("Unlimited")

        self.fragment_concurrency = QSpinBox()
        self.fragment_concurrency.setRange(1, 16)
        self.fragment_concurrency.setValue(4)
        self.fragment_concurrency.valueChanged.connect(self.mark_custom_preset)

        self.filename_template_combo = QComboBox()
        self.filename_template_combo.addItems(list(FILENAME_TEMPLATES))
        self.debug_checkbox = QCheckBox("Debug yt-dlp")

        self.test_link_btn = QPushButton("Test Link")
        self.test_link_btn.setFixedHeight(34)
        self.test_link_btn.clicked.connect(self.test_links)
        self.check_btn = QPushButton("Cek Resolusi")
        self.check_btn.setFixedHeight(34)
        self.check_btn.clicked.connect(self.check_resolution)
        self.download_btn = QPushButton("Download")
        self.download_btn.setFixedHeight(34)
        self.download_btn.clicked.connect(self.start_download)
        self.retry_failed_btn = QPushButton("Retry Failed")
        self.retry_failed_btn.clicked.connect(self.retry_failed)
        self.clear_completed_btn = QPushButton("Clear Completed")
        self.clear_completed_btn.clicked.connect(self.clear_completed)
        self.clear_queue_btn = QPushButton("Clear Queue")
        self.clear_queue_btn.clicked.connect(self.clear_queue)
        self.open_selected_btn = QPushButton("Buka File")
        self.open_selected_btn.clicked.connect(self.open_selected_file)
        self.save_queue_btn = QPushButton("Save Queue")
        self.save_queue_btn.clicked.connect(self.save_queue)
        self.load_queue_btn = QPushButton("Load Queue")
        self.load_queue_btn.clicked.connect(self.load_queue)
        self.update_ytdlp_btn = QPushButton("Update yt-dlp")
        self.update_ytdlp_btn.clicked.connect(self.update_ytdlp)
        self.clean_temp_btn = QPushButton("Clean Temp Files")
        self.clean_temp_btn.clicked.connect(self.clean_temp_files)
        self.about_btn = QPushButton("About")
        self.about_btn.clicked.connect(self.show_about)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setFixedHeight(34)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_download)
        self.clear_log_btn = QPushButton("Clear Log")
        self.clear_log_btn.clicked.connect(self.clear_log)
        self.export_log_btn = QPushButton("Export Log")
        self.export_log_btn.clicked.connect(self.export_log)
        self.refresh_history_btn = QPushButton("Refresh History")
        self.refresh_history_btn.clicked.connect(self.refresh_history)
        self.open_history_btn = QPushButton("Buka File History")
        self.open_history_btn.clicked.connect(self.open_history_file)
        self.history_search_input = QLineEdit()
        self.history_search_input.setPlaceholderText("Search history...")
        self.history_search_input.textChanged.connect(self.refresh_history)
        self.history_filter_combo = QComboBox()
        self.history_filter_combo.addItems([
            "All",
            "Done",
            "Failed",
            "Video",
            "Audio",
            "Image",
            "YouTube",
            "TikTok",
            "Instagram",
            "Twitter-X",
            "Other",
        ])
        self.history_filter_combo.currentTextChanged.connect(self.refresh_history)
        self.history_open_file_btn = QPushButton("Open File")
        self.history_open_file_btn.clicked.connect(self.open_selected_history_file)
        self.history_open_folder_btn = QPushButton("Open Folder")
        self.history_open_folder_btn.clicked.connect(self.open_selected_history_folder)
        self.history_copy_url_btn = QPushButton("Copy URL")
        self.history_copy_url_btn.clicked.connect(self.copy_selected_history_url)
        self.history_redownload_btn = QPushButton("Re-download")
        self.history_redownload_btn.clicked.connect(self.redownload_selected_history)
        self.clear_history_btn = QPushButton("Clear History")
        self.clear_history_btn.clicked.connect(self.clear_history)

        self.target_info_label = QLabel("Target: Best available • Container: Auto (MKV/MP4)")
        self.target_info_label.setStyleSheet("color: #94a3b8; font-size: 9pt;")
        self.check_engine_btn = QPushButton("Check Engine")
        self.check_engine_btn.clicked.connect(self.show_engine_health_dialog)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.status_label = QLabel("Ready")

        self.queue_table = QTableWidget(0, 9)
        self.queue_table.setHorizontalHeaderLabels([
            "Judul / URL",
            "Platform",
            "Resolusi / Format",
            "Estimasi Size",
            "Status",
            "Progress",
            "Speed",
            "ETA",
            "File",
        ])
        self.queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.queue_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.queue_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.queue_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.queue_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.queue_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.queue_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.queue_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.queue_table.horizontalHeader().setSectionResizeMode(8, QHeaderView.Stretch)
        self.queue_table.setMinimumHeight(120)
        self.queue_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.queue_table.customContextMenuRequested.connect(self.show_queue_context_menu)
        self.queue_table.itemSelectionChanged.connect(self.on_queue_selection_changed)
        self.queue_table.cellDoubleClicked.connect(self.on_queue_double_clicked)
        self.queue_table.setAlternatingRowColors(True)
        self.queue_table.setShowGrid(False)
        self.queue_table.verticalHeader().setDefaultSectionSize(32)
        self.queue_table.verticalHeader().setVisible(False)

        self.download_btn.setObjectName("primary_action")
        self.cancel_btn.setObjectName("cancel_action")

        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(65)
        self.log_box.setMaximumHeight(90)
        self.log_box.setVisible(False)
        self.toggle_log_btn = QPushButton("📜 Tampilkan Log")
        self.toggle_log_btn.clicked.connect(self.toggle_log_visibility)

        self.history_table = QTableWidget(0, 7)
        self.history_table.setHorizontalHeaderLabels(["Time", "Title", "Platform", "Status", "Format", "URL", "File"])
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setShowGrid(False)
        self.history_table.verticalHeader().setDefaultSectionSize(30)
        self.history_table.verticalHeader().setVisible(False)

    def toggle_maximized(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and hasattr(self, "header_bar") and self.header_bar and self.header_bar.underMouse():
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self._drag_pos is not None:
            if not self.isMaximized():
                self.move(event.globalPosition().toPoint() - self._drag_pos)
                event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if hasattr(self, "header_bar") and self.header_bar and self.header_bar.underMouse():
            self.toggle_maximized()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def on_nav_item_changed(self, current, previous):
        if not current:
            return
        idx = current.data(Qt.UserRole)
        if idx is not None and 0 <= idx < self.tabs.count():
            if self.tabs.currentIndex() != idx:
                self.tabs.setCurrentIndex(idx)

    def on_tab_changed(self, index):
        titles = [
            "Download Video & Audio",
            "Pengaturan Lanjutan (Advanced)",
            "Subtitle & Browser Cookies",
            "Folder Output & Engine FFmpeg",
            "Riwayat Download (History)",
        ]
        if hasattr(self, "page_title") and 0 <= index < len(titles):
            self.page_title.setText(titles[index])

        if hasattr(self, "nav_list"):
            for r in range(self.nav_list.count()):
                it = self.nav_list.item(r)
                if it.data(Qt.UserRole) == index:
                    self.nav_list.setCurrentRow(r)
                    break

        if self.tabs.tabText(index) == "History" and not getattr(self, "history_loaded", False):
            self.history_loaded = True
            self.refresh_history()

    def build_layout(self):
        root = QVBoxLayout()
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        window_container = QWidget()
        window_container.setObjectName("window_container")
        win_layout = QHBoxLayout(window_container)
        win_layout.setContentsMargins(0, 0, 0, 0)
        win_layout.setSpacing(0)

        # 1. macOS Sidebar
        self.sidebar = QWidget()
        self.sidebar.setObjectName("mac_sidebar")
        self.sidebar.setFixedWidth(210)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(14, 14, 14, 14)
        sidebar_layout.setSpacing(12)

        # Traffic lights (Close, Min, Zoom)
        traffic_box = QHBoxLayout()
        traffic_box.setSpacing(8)

        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("mac_close")
        self.btn_close.setFixedSize(12, 12)
        self.btn_close.setToolTip("Tutup")
        self.btn_close.clicked.connect(self.close)

        self.btn_min = QPushButton("−")
        self.btn_min.setObjectName("mac_min")
        self.btn_min.setFixedSize(12, 12)
        self.btn_min.setToolTip("Kecilkan")
        self.btn_min.clicked.connect(self.showMinimized)

        self.btn_zoom = QPushButton("+")
        self.btn_zoom.setObjectName("mac_zoom")
        self.btn_zoom.setFixedSize(12, 12)
        self.btn_zoom.setToolTip("Perbesar")
        self.btn_zoom.clicked.connect(self.toggle_maximized)

        traffic_box.addWidget(self.btn_close)
        traffic_box.addWidget(self.btn_min)
        traffic_box.addWidget(self.btn_zoom)
        traffic_box.addStretch()
        sidebar_layout.addLayout(traffic_box)
        sidebar_layout.addSpacing(10)

        # App Branding
        brand_layout = QVBoxLayout()
        brand_layout.setSpacing(2)
        app_title = QLabel(APP_NAME)
        app_title.setObjectName("mac_brand_title")
        app_ver = QLabel(f"{APP_VERSION} • macOS Edition")
        app_ver.setObjectName("mac_brand_ver")
        brand_layout.addWidget(app_title)
        brand_layout.addWidget(app_ver)
        sidebar_layout.addLayout(brand_layout)
        sidebar_layout.addSpacing(12)

        # Navigation List
        nav_label = QLabel("NAVIGASI")
        nav_label.setObjectName("mac_nav_header")
        sidebar_layout.addWidget(nav_label)

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("mac_nav")
        self.nav_list.setSpacing(3)

        nav_items = [
            ("📥  Download", 0),
            ("⚙️  Advanced", 1),
            ("🌐  Subtitle & Cookies", 2),
            ("📁  Output & FFmpeg", 3),
            ("📜  Riwayat Download", 4),
        ]

        for title, tab_idx in nav_items:
            item = QListWidgetItem(title)
            item.setData(Qt.UserRole, tab_idx)
            item.setSizeHint(QSize(180, 34))
            self.nav_list.addItem(item)

        self.nav_list.setCurrentRow(0)
        self.nav_list.currentItemChanged.connect(self.on_nav_item_changed)
        sidebar_layout.addWidget(self.nav_list, 1)

        # Sidebar Bottom: Theme toggle & FFmpeg status chip
        sidebar_bottom = QVBoxLayout()
        sidebar_bottom.setSpacing(8)
        self.theme_toggle_btn = QPushButton("☀ Light Mode")
        self.theme_toggle_btn.setObjectName("theme_toggle_btn")
        self.theme_toggle_btn.setToolTip("Ganti tema Dark / Light Mode")
        self.theme_toggle_btn.clicked.connect(self.toggle_theme)
        sidebar_bottom.addWidget(self.theme_toggle_btn)

        self.header_status_chip = QLabel("● Ready")
        self.header_status_chip.setAlignment(Qt.AlignCenter)
        self.header_status_chip.setStyleSheet("font-size: 8pt; font-weight: 600; color: #30d158; background-color: rgba(48, 209, 88, 0.12); border: 1px solid rgba(48, 209, 88, 0.25); border-radius: 8px; padding: 4px 8px;")
        sidebar_bottom.addWidget(self.header_status_chip)
        sidebar_layout.addLayout(sidebar_bottom)

        win_layout.addWidget(self.sidebar)

        # 2. Main Canvas Area
        self.main_canvas = QWidget()
        self.main_canvas.setObjectName("main_canvas")
        canvas_layout = QVBoxLayout(self.main_canvas)
        canvas_layout.setContentsMargins(18, 12, 18, 10)
        canvas_layout.setSpacing(8)

        # Main Header Bar (Draggable)
        self.header_bar = QWidget()
        self.header_bar.setObjectName("canvas_header")
        self.header_bar.setFixedHeight(36)
        header_layout = QHBoxLayout(self.header_bar)
        header_layout.setContentsMargins(0, 0, 0, 0)

        self.page_title = QLabel("Download Video & Audio")
        self.page_title.setObjectName("mac_page_title")
        header_layout.addWidget(self.page_title)
        header_layout.addStretch()

        engine_badge = QLabel("yt-dlp Core • Multi-Thread")
        engine_badge.setObjectName("mac_engine_badge")
        header_layout.addWidget(engine_badge)
        canvas_layout.addWidget(self.header_bar)

        # Tab Widget (Hidden tab bar header, driven cleanly by sidebar!)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("mac_tabs")
        self.tabs.tabBar().setVisible(False)
        self.tabs.addTab(self.build_download_tab(), "Download")
        self.tabs.addTab(self.build_advanced_tab(), "Advanced")
        self.tabs.addTab(self.build_subtitle_tab(), "Subtitle && Cookies")
        self.tabs.addTab(self.build_output_tab(), "Output / FFmpeg")
        self.tabs.addTab(self.build_history_tab(), "History")
        self.tabs.currentChanged.connect(self.on_tab_changed)
        canvas_layout.addWidget(self.tabs, 1)

        bottom_bar = QHBoxLayout()
        bottom_bar.setContentsMargins(0, 0, 0, 0)
        bottom_bar.addStretch()
        size_grip = QSizeGrip(self)
        size_grip.setFixedSize(14, 14)
        bottom_bar.addWidget(size_grip)
        canvas_layout.addLayout(bottom_bar)

        win_layout.addWidget(self.main_canvas, 1)
        root.addWidget(window_container)
        self.setLayout(root)

    def build_download_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # Card 1: Input URL & Channel
        input_card = QFrame()
        input_card.setObjectName("apple_card")
        in_card_layout = QVBoxLayout(input_card)
        in_card_layout.setContentsMargins(14, 12, 14, 12)
        in_card_layout.setSpacing(8)

        in_top = QHBoxLayout()
        in_label = QLabel("LINK / URL VIDEO, PLAYLIST, ATAU CHANNEL")
        in_label.setStyleSheet("font-size: 7.5pt; font-weight: 700; color: #8e8e93; letter-spacing: 0.5px;")
        in_top.addWidget(in_label)
        in_top.addStretch()
        in_top.addWidget(self.paste_btn)
        in_card_layout.addLayout(in_top)

        in_card_layout.addWidget(self.urls_input)

        # Channel input row
        chan_row = QHBoxLayout()
        chan_row.setSpacing(8)
        chan_icon = QLabel("📺")
        chan_row.addWidget(chan_icon)
        chan_row.addWidget(self.channel_url_input, 1)
        chan_row.addWidget(self.channel_preview_btn)
        in_card_layout.addLayout(chan_row)

        self.legacy_channel_controls = QWidget()
        legacy_layout = QHBoxLayout()
        legacy_layout.setContentsMargins(0, 2, 0, 0)
        legacy_layout.setSpacing(8)
        legacy_layout.addWidget(QLabel("Legacy Direct Filter:"))
        legacy_layout.addWidget(self.channel_keyword_input, 1)
        legacy_layout.addWidget(self.channel_fetch_btn)
        self.legacy_channel_controls.setLayout(legacy_layout)
        in_card_layout.addWidget(self.legacy_channel_controls)
        in_card_layout.addWidget(self.channel_status_label)

        layout.addWidget(input_card)

        # Card 2: Format & Kualitas (Spacious Cupertino Inset Surface)
        self.format_card = QFrame()
        self.format_card.setObjectName("apple_card")
        fmt_card_layout = QVBoxLayout(self.format_card)
        fmt_card_layout.setContentsMargins(14, 12, 14, 12)
        fmt_card_layout.setSpacing(10)

        fmt_title = QLabel("FORMAT & KUALITAS")
        fmt_title.setStyleSheet("font-size: 7.5pt; font-weight: 700; color: #8e8e93; letter-spacing: 0.5px;")
        fmt_card_layout.addWidget(fmt_title)

        primary_format_layout = QGridLayout()
        primary_format_layout.setHorizontalSpacing(14)
        primary_format_layout.setVerticalSpacing(8)
        primary_format_layout.setRowMinimumHeight(0, 28)
        primary_format_layout.setRowMinimumHeight(1, 28)
        primary_format_layout.setColumnMinimumWidth(0, 80)
        primary_format_layout.setColumnMinimumWidth(2, 90)
        primary_format_layout.setColumnStretch(0, 0)
        primary_format_layout.setColumnStretch(1, 1)
        primary_format_layout.setColumnStretch(2, 0)
        primary_format_layout.setColumnStretch(3, 1)

        primary_format_layout.addWidget(QLabel("Mode UI"), 0, 0)
        primary_format_layout.addWidget(self.mode_combo, 0, 1)
        primary_format_layout.addWidget(self.preset_label, 0, 2)
        primary_format_layout.addWidget(self.preset_combo, 0, 3)

        primary_format_layout.addWidget(QLabel("Kualitas"), 1, 0)
        primary_format_layout.addWidget(self.quality_combo, 1, 1)
        primary_format_layout.addWidget(self.media_type_label, 1, 2)
        primary_format_layout.addWidget(self.media_type_combo, 1, 3)
        primary_format_layout.addWidget(self.format_label, 1, 2)
        primary_format_layout.addWidget(self.format_combo, 1, 3)

        fmt_card_layout.addLayout(primary_format_layout)

        self.power_download_controls = QWidget()
        power_format_layout = QGridLayout()
        power_format_layout.setContentsMargins(0, 2, 0, 0)
        power_format_layout.setHorizontalSpacing(14)
        power_format_layout.setVerticalSpacing(6)
        power_format_layout.setRowMinimumHeight(0, 28)
        power_format_layout.setColumnMinimumWidth(0, 80)
        power_format_layout.setColumnMinimumWidth(2, 90)
        power_format_layout.setColumnStretch(0, 0)
        power_format_layout.setColumnStretch(1, 1)
        power_format_layout.setColumnStretch(2, 0)
        power_format_layout.setColumnStretch(3, 1)

        power_format_layout.addWidget(QLabel("Mode kualitas"), 0, 0)
        power_format_layout.addWidget(self.quality_mode_combo, 0, 1)
        power_format_layout.addWidget(QLabel("Audio bitrate"), 0, 2)
        power_format_layout.addWidget(self.audio_bitrate, 0, 3)
        power_format_layout.addWidget(self.high_res_hint_label, 1, 0, 1, 4)
        self.power_download_controls.setLayout(power_format_layout)
        fmt_card_layout.addWidget(self.power_download_controls)

        fmt_card_layout.addWidget(self.target_info_label)
        layout.addWidget(self.format_card)

        # Card 3: Action Buttons Bar
        main_actions = QHBoxLayout()
        main_actions.setSpacing(10)
        main_actions.addWidget(self.download_btn) # Primary CTA first!
        main_actions.addWidget(self.check_btn)
        main_actions.addWidget(self.cancel_btn)
        main_actions.addSpacing(10)
        main_actions.addWidget(self.status_label)
        main_actions.addStretch()
        layout.addLayout(main_actions)

        layout.addWidget(self.progress_bar)

        # Card 4: Antrean Download (macOS List/Card style)
        q_card = QFrame()
        q_card.setObjectName("apple_card")
        q_card_layout = QVBoxLayout(q_card)
        q_card_layout.setContentsMargins(14, 12, 14, 12)
        q_card_layout.setSpacing(8)

        queue_header_row = QHBoxLayout()
        queue_label = QLabel("ANTREAN DOWNLOAD")
        queue_label.setStyleSheet("font-size: 7.5pt; font-weight: 700; color: #8e8e93; letter-spacing: 0.5px;")
        queue_header_row.addWidget(queue_label)
        queue_header_row.addStretch()

        queue_actions = QHBoxLayout()
        queue_actions.setSpacing(6)
        queue_actions.addWidget(self.retry_failed_btn)
        queue_actions.addWidget(self.clear_completed_btn)
        queue_actions.addWidget(self.clear_queue_btn)
        queue_actions.addWidget(self.open_selected_btn)
        queue_actions.addWidget(self.open_folder_btn)
        queue_header_row.addLayout(queue_actions)
        q_card_layout.addLayout(queue_header_row)

        q_card_layout.addWidget(self.queue_table, 1)

        log_header_row = QHBoxLayout()
        log_label = QLabel("Log Ringkas")
        log_label.setStyleSheet("font-weight: 600; font-size: 8pt; color: #8e8e93;")
        log_header_row.addWidget(log_label)
        log_header_row.addStretch()
        log_header_row.addWidget(self.clear_log_btn)
        log_header_row.addWidget(self.export_log_btn)
        log_header_row.addWidget(self.toggle_log_btn)
        q_card_layout.addLayout(log_header_row)

        q_card_layout.addWidget(self.log_box)

        layout.addWidget(q_card, 1) # Expanding!

        tab.setLayout(layout)
        return tab

    def _make_card_header(self, title):
        lbl = QLabel(title)
        lbl.setObjectName("card_header")
        return lbl

    def build_advanced_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        advanced_card = QFrame()
        advanced_card.setObjectName("apple_card")
        advanced_outer = QVBoxLayout(advanced_card)
        advanced_outer.setContentsMargins(14, 12, 14, 12)
        advanced_outer.setSpacing(8)
        advanced_outer.addWidget(self._make_card_header("PENGATURAN LANJUTAN"))

        advanced_layout = QGridLayout()
        advanced_layout.setHorizontalSpacing(14)
        advanced_layout.setVerticalSpacing(8)
        advanced_layout.addWidget(QLabel("Codec"), 0, 0)
        advanced_layout.addWidget(self.codec_combo, 0, 1)
        advanced_layout.addWidget(QLabel("Audio preference"), 0, 2)
        advanced_layout.addWidget(self.audio_pref_combo, 0, 3)
        advanced_layout.addWidget(QLabel("Limit speed"), 1, 0)
        advanced_layout.addWidget(self.speed_limit, 1, 1)
        advanced_layout.addWidget(QLabel("Fragments"), 1, 2)
        advanced_layout.addWidget(self.fragment_concurrency, 1, 3)
        advanced_layout.addWidget(QLabel("Check mode"), 2, 0)
        advanced_layout.addWidget(self.check_mode_combo, 2, 1)
        advanced_layout.addWidget(QLabel("Nama file"), 2, 2)
        advanced_layout.addWidget(self.filename_template_combo, 2, 3)
        advanced_layout.addWidget(self.auto_container_checkbox, 3, 0, 1, 2)
        advanced_layout.addWidget(self.thumbnail_checkbox, 3, 2, 1, 2)
        advanced_layout.addWidget(self.embed_metadata_checkbox, 4, 0, 1, 2)
        advanced_layout.addWidget(self.debug_checkbox, 4, 2, 1, 2)
        advanced_layout.setColumnStretch(1, 1)
        advanced_layout.setColumnStretch(3, 1)
        advanced_outer.addLayout(advanced_layout)
        layout.addWidget(advanced_card)

        playlist_card = QFrame()
        playlist_card.setObjectName("apple_card")
        playlist_outer = QVBoxLayout(playlist_card)
        playlist_outer.setContentsMargins(14, 12, 14, 12)
        playlist_outer.setSpacing(8)
        playlist_outer.addWidget(self._make_card_header("PLAYLIST"))

        playlist_layout = QGridLayout()
        playlist_layout.setHorizontalSpacing(14)
        playlist_layout.setVerticalSpacing(8)
        playlist_layout.addWidget(self.playlist_checkbox, 0, 0, 1, 4)
        playlist_layout.addWidget(QLabel("Mulai"), 1, 0)
        playlist_layout.addWidget(self.playlist_start, 1, 1)
        playlist_layout.addWidget(QLabel("Akhir"), 1, 2)
        playlist_layout.addWidget(self.playlist_end, 1, 3)
        playlist_layout.setColumnStretch(1, 1)
        playlist_layout.setColumnStretch(3, 1)
        playlist_outer.addLayout(playlist_layout)
        layout.addWidget(playlist_card)

        util_card = QFrame()
        util_card.setObjectName("apple_card")
        util_actions = QHBoxLayout(util_card)
        util_actions.setContentsMargins(14, 10, 14, 10)
        util_actions.setSpacing(8)
        util_actions.addWidget(self.save_queue_btn)
        util_actions.addWidget(self.load_queue_btn)
        util_actions.addWidget(self.test_link_btn)
        util_actions.addWidget(self.update_ytdlp_btn)
        util_actions.addWidget(self.about_btn)
        util_actions.addStretch()
        layout.addWidget(util_card)
        layout.addStretch()
        tab.setLayout(layout)
        return tab

    def build_subtitle_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        subtitle_card = QFrame()
        subtitle_card.setObjectName("apple_card")
        sub_outer = QVBoxLayout(subtitle_card)
        sub_outer.setContentsMargins(14, 12, 14, 12)
        sub_outer.setSpacing(8)
        sub_outer.addWidget(self._make_card_header("SUBTITLE"))

        subtitle_layout = QGridLayout()
        subtitle_layout.setHorizontalSpacing(14)
        subtitle_layout.setVerticalSpacing(8)
        subtitle_layout.addWidget(QLabel("Mode"), 0, 0)
        subtitle_layout.addWidget(self.subtitle_mode_combo, 0, 1)
        subtitle_layout.addWidget(QLabel("Bahasa"), 1, 0)
        subtitle_layout.addWidget(self.subtitle_lang_input, 1, 1)
        subtitle_layout.addWidget(self.subtitle_optional_checkbox, 2, 1)
        note_lbl = QLabel("Catatan: subtitle YouTube bisa kena HTTP 429. Jika optional aktif, video tetap dicoba tanpa subtitle.")
        note_lbl.setObjectName("muted_hint")
        subtitle_layout.addWidget(note_lbl, 3, 0, 1, 2)
        subtitle_layout.setColumnStretch(1, 1)
        sub_outer.addLayout(subtitle_layout)
        layout.addWidget(subtitle_card)

        cookies_card = QFrame()
        cookies_card.setObjectName("apple_card")
        cookies_outer = QVBoxLayout(cookies_card)
        cookies_outer.setContentsMargins(14, 12, 14, 12)
        cookies_outer.setSpacing(8)
        cookies_outer.addWidget(self._make_card_header("BROWSER COOKIES"))

        cookies_layout = QGridLayout()
        cookies_layout.setHorizontalSpacing(14)
        cookies_layout.setVerticalSpacing(8)
        cookies_layout.addWidget(QLabel("Cookies browser"), 0, 0)
        cookies_layout.addWidget(self.cookies_combo, 0, 1, 1, 2)
        cookies_layout.addWidget(QLabel("cookies.txt"), 1, 0)
        cookies_layout.addWidget(self.cookies_file_input, 1, 1)
        cookies_layout.addWidget(self.cookies_file_btn, 1, 2)
        cookies_layout.setColumnStretch(1, 1)
        cookies_outer.addLayout(cookies_layout)
        layout.addWidget(cookies_card)
        layout.addStretch()
        tab.setLayout(layout)
        return tab

    def build_output_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        output_card = QFrame()
        output_card.setObjectName("apple_card")
        out_outer = QVBoxLayout(output_card)
        out_outer.setContentsMargins(14, 12, 14, 12)
        out_outer.setSpacing(8)
        out_outer.addWidget(self._make_card_header("FOLDER OUTPUT"))

        output_layout = QGridLayout()
        output_layout.setHorizontalSpacing(10)
        output_layout.setVerticalSpacing(8)
        output_layout.addWidget(QLabel("Folder"), 0, 0)
        output_layout.addWidget(self.output_input, 0, 1)
        output_layout.addWidget(self.browse_btn, 0, 2)
        output_layout.addWidget(self.output_open_folder_btn, 0, 3)
        output_layout.addWidget(self.sort_media_checkbox, 1, 1, 1, 3)
        output_layout.addWidget(self.platform_sort_checkbox, 2, 1, 1, 3)
        output_layout.setColumnStretch(1, 1)
        out_outer.addLayout(output_layout)
        layout.addWidget(output_card)

        ffmpeg_card = QFrame()
        ffmpeg_card.setObjectName("apple_card")
        ff_outer = QVBoxLayout(ffmpeg_card)
        ff_outer.setContentsMargins(14, 12, 14, 12)
        ff_outer.setSpacing(8)
        ff_outer.addWidget(self._make_card_header("ENGINE FFMPEG & DIAGNOSTIK"))

        ffmpeg_layout = QGridLayout()
        ffmpeg_layout.setHorizontalSpacing(10)
        ffmpeg_layout.setVerticalSpacing(8)
        ffmpeg_layout.addWidget(QLabel("Path"), 0, 0)
        ffmpeg_layout.addWidget(self.ffmpeg_input, 0, 1)
        ffmpeg_layout.addWidget(self.ffmpeg_browse_btn, 0, 2)
        ffmpeg_layout.addWidget(self.ffmpeg_detect_btn, 0, 3)
        ffmpeg_layout.addWidget(self.ffmpeg_status_label, 1, 1, 1, 3)
        ffmpeg_layout.setColumnStretch(1, 1)
        ff_outer.addLayout(ffmpeg_layout)
        layout.addWidget(ffmpeg_card)

        tools_card = QFrame()
        tools_card.setObjectName("apple_card")
        temp_actions = QHBoxLayout(tools_card)
        temp_actions.setContentsMargins(14, 10, 14, 10)
        temp_actions.setSpacing(8)
        temp_actions.addWidget(self.clean_temp_btn)
        temp_actions.addWidget(self.check_engine_btn)
        temp_actions.addStretch()
        layout.addWidget(tools_card)
        layout.addStretch()
        tab.setLayout(layout)
        return tab

    def build_history_tab(self):
        tab = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        top_card = QFrame()
        top_card.setObjectName("apple_card")
        top_outer = QVBoxLayout(top_card)
        top_outer.setContentsMargins(14, 12, 14, 12)
        top_outer.setSpacing(8)
        top_outer.addWidget(self._make_card_header("FILTER & AKSI RIWAYAT"))

        filters = QHBoxLayout()
        filters.setSpacing(8)
        filters.addWidget(QLabel("Search"))
        filters.addWidget(self.history_search_input, 1)
        filters.addWidget(QLabel("Filter"))
        filters.addWidget(self.history_filter_combo)
        top_outer.addLayout(filters)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        actions.addWidget(self.history_open_file_btn)
        actions.addWidget(self.history_open_folder_btn)
        actions.addWidget(self.history_copy_url_btn)
        actions.addWidget(self.history_redownload_btn)
        actions.addWidget(self.clear_history_btn)
        actions.addStretch()
        top_outer.addLayout(actions)
        layout.addWidget(top_card)

        table_card = QFrame()
        table_card.setObjectName("apple_card")
        table_outer = QVBoxLayout(table_card)
        table_outer.setContentsMargins(14, 12, 14, 12)
        table_outer.setSpacing(8)
        table_outer.addWidget(self._make_card_header("RIWAYAT DOWNLOAD"))
        table_outer.addWidget(self.history_table, 1)
        layout.addWidget(table_card, 1)

        tab.setLayout(layout)
        return tab

    def toggle_theme(self):
        self.theme_mode = "light" if self.theme_mode == "dark" else "dark"
        self.apply_style()
        self.save_settings()

    def apply_style(self):
        is_light = getattr(self, "theme_mode", "dark") == "light"
        if hasattr(self, "theme_toggle_btn"):
            self.theme_toggle_btn.setText("🌙 Dark Mode" if is_light else "☀ Light Mode")

        if is_light:
            p = {
                "shell_bg": "#eef2f6",
                "shell_border": "rgba(15, 23, 42, 0.14)",
                "sidebar_bg": "#e4e9f0",
                "sidebar_border": "rgba(15, 23, 42, 0.08)",
                "canvas_bg": "#f6f8fb",
                "card_bg": "#ffffff",
                "card_border": "rgba(15, 23, 42, 0.09)",
                "text": "#0f172a",
                "text_muted": "#64748b",
                "text_subtle": "#475569",
                "input_bg": "#f8fafc",
                "input_focus_bg": "#ffffff",
                "input_border": "rgba(15, 23, 42, 0.14)",
                "combo_bg": "#f1f5f9",
                "combo_hover": "#e2e8f0",
                "combo_popup_bg": "#ffffff",
                "btn_bg": "rgba(15, 23, 42, 0.05)",
                "btn_hover": "rgba(15, 23, 42, 0.10)",
                "btn_pressed": "rgba(15, 23, 42, 0.03)",
                "btn_disabled_bg": "#f1f5f9",
                "btn_disabled_fg": "#94a3b8",
                "nav_item_fg": "#475569",
                "nav_hover_bg": "rgba(15, 23, 42, 0.06)",
                "nav_hover_fg": "#0f172a",
                "nav_disabled_fg": "#cbd5e1",
                "badge_bg": "rgba(15, 23, 42, 0.05)",
                "table_bg": "#ffffff",
                "table_alt": "#f8fafc",
                "table_header_bg": "#f1f5f9",
                "table_header_fg": "#475569",
                "progress_bg": "#e2e8f0",
                "scroll_handle": "rgba(15, 23, 42, 0.18)",
                "scroll_hover": "rgba(15, 23, 42, 0.34)",
                "menu_bg": "#ffffff",
                "checkbox_bg": "#ffffff",
                "checkbox_border": "rgba(15, 23, 42, 0.25)",
            }
        else:
            p = {
                "shell_bg": "#141417",
                "shell_border": "rgba(255, 255, 255, 0.12)",
                "sidebar_bg": "#19191e",
                "sidebar_border": "rgba(255, 255, 255, 0.08)",
                "canvas_bg": "#121215",
                "card_bg": "#1a1a20",
                "card_border": "rgba(255, 255, 255, 0.07)",
                "text": "#f5f5f7",
                "text_muted": "#8e8e93",
                "text_subtle": "#a1a1a6",
                "input_bg": "#121216",
                "input_focus_bg": "#15151b",
                "input_border": "rgba(255, 255, 255, 0.12)",
                "combo_bg": "#24242c",
                "combo_hover": "#2c2c36",
                "combo_popup_bg": "#1e1e24",
                "btn_bg": "rgba(255, 255, 255, 0.07)",
                "btn_hover": "rgba(255, 255, 255, 0.12)",
                "btn_pressed": "rgba(255, 255, 255, 0.05)",
                "btn_disabled_bg": "#1a1a20",
                "btn_disabled_fg": "#555762",
                "nav_item_fg": "#a1a1a6",
                "nav_hover_bg": "rgba(255, 255, 255, 0.06)",
                "nav_hover_fg": "#ffffff",
                "nav_disabled_fg": "#4a4a52",
                "badge_bg": "rgba(255, 255, 255, 0.05)",
                "table_bg": "#15151a",
                "table_alt": "#191920",
                "table_header_bg": "#1a1a21",
                "table_header_fg": "#8e8e93",
                "progress_bg": "#121215",
                "scroll_handle": "rgba(255, 255, 255, 0.16)",
                "scroll_hover": "rgba(255, 255, 255, 0.32)",
                "menu_bg": "#23232c",
                "checkbox_bg": "#141519",
                "checkbox_border": "rgba(255, 255, 255, 0.22)",
            }

        self.setStyleSheet(f"""
            QWidget {{
                background-color: {p['shell_bg']};
                color: {p['text']};
                font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", "Segoe UI Variable Display", "Segoe UI", sans-serif;
                font-size: 9.5pt;
            }}

            QLabel {{
                background-color: transparent;
                color: {p['text']};
            }}

            QLabel#mac_brand_title {{
                font-size: 11pt;
                font-weight: 700;
                color: {p['text']};
                letter-spacing: -0.3px;
            }}

            QLabel#mac_brand_ver {{
                font-size: 7.5pt;
                font-weight: 600;
                color: {p['text_muted']};
            }}

            QLabel#mac_nav_header, QLabel#card_header {{
                font-size: 7.5pt;
                font-weight: 700;
                color: {p['text_muted']};
                letter-spacing: 0.6px;
            }}

            QLabel#mac_page_title {{
                font-size: 13pt;
                font-weight: 700;
                color: {p['text']};
                letter-spacing: -0.3px;
            }}

            QLabel#mac_engine_badge {{
                font-size: 8pt;
                color: {p['text_muted']};
                background-color: {p['badge_bg']};
                border-radius: 6px;
                padding: 3px 8px;
            }}

            QLabel#muted_hint {{
                font-size: 8.5pt;
                color: {p['text_muted']};
            }}

            QWidget#window_container {{
                background-color: {p['shell_bg']};
                border: 1px solid {p['shell_border']};
                border-radius: 12px;
            }}

            QWidget#mac_sidebar {{
                background-color: {p['sidebar_bg']};
                border-top-left-radius: 11px;
                border-bottom-left-radius: 11px;
                border-right: 1px solid {p['sidebar_border']};
            }}

            QPushButton#mac_close {{
                background-color: #ff5f56;
                border: 1px solid #e0443e;
                border-radius: 6px;
                color: transparent;
                font-size: 7.5pt;
                font-weight: 800;
                padding: 0px;
            }}
            QPushButton#mac_close:hover {{
                color: #4d0000;
            }}
            QPushButton#mac_min {{
                background-color: #ffbd2e;
                border: 1px solid #dea123;
                border-radius: 6px;
                color: transparent;
                font-size: 7.5pt;
                font-weight: 800;
                padding: 0px;
            }}
            QPushButton#mac_min:hover {{
                color: #5c3b00;
            }}
            QPushButton#mac_zoom {{
                background-color: #27c93f;
                border: 1px solid #1aab29;
                border-radius: 6px;
                color: transparent;
                font-size: 7.5pt;
                font-weight: 800;
                padding: 0px;
            }}
            QPushButton#mac_zoom:hover {{
                color: #004000;
            }}

            QListWidget#mac_nav {{
                background: transparent;
                border: none;
                outline: none;
            }}

            QListWidget#mac_nav::item {{
                border-radius: 7px;
                padding: 6px 10px;
                color: {p['nav_item_fg']};
                font-weight: 500;
                margin-bottom: 2px;
            }}

            QListWidget#mac_nav::item:hover {{
                background-color: {p['nav_hover_bg']};
                color: {p['nav_hover_fg']};
            }}

            QListWidget#mac_nav::item:selected {{
                background-color: #0071e3;
                color: #ffffff;
                font-weight: 600;
            }}

            QListWidget#mac_nav::item:disabled {{
                color: {p['nav_disabled_fg']};
                background: transparent;
            }}

            QWidget#main_canvas {{
                background-color: {p['canvas_bg']};
                border-top-right-radius: 11px;
                border-bottom-right-radius: 11px;
            }}

            QFrame#apple_card {{
                background-color: {p['card_bg']};
                border: 1px solid {p['card_border']};
                border-radius: 10px;
            }}

            QTabWidget::pane {{
                border: none;
                background-color: transparent;
            }}

            QLineEdit, QSpinBox, QTextEdit {{
                background-color: {p['input_bg']};
                color: {p['text']};
                border: 1px solid {p['input_border']};
                border-radius: 7px;
                padding: 4px 8px;
                selection-background-color: #0071e3;
                selection-color: #ffffff;
            }}

            QLineEdit:focus, QTextEdit:focus, QSpinBox:focus {{
                border: 1.5px solid #0071e3;
                background-color: {p['input_focus_bg']};
            }}

            QComboBox {{
                background-color: {p['combo_bg']};
                color: {p['text']};
                border: 1px solid {p['input_border']};
                border-radius: 7px;
                padding: 3px 10px;
                font-weight: 500;
                min-height: 26px;
            }}

            QComboBox:hover {{
                background-color: {p['combo_hover']};
                border-color: #0071e3;
            }}

            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}

            QComboBox QAbstractItemView {{
                background-color: {p['combo_popup_bg']};
                color: {p['text']};
                border: 1px solid {p['input_border']};
                border-radius: 7px;
                selection-background-color: #0071e3;
                selection-color: #ffffff;
                padding: 4px;
            }}

            QPushButton {{
                background-color: {p['btn_bg']};
                color: {p['text']};
                border: 1px solid {p['input_border']};
                border-radius: 7px;
                font-size: 9pt;
                font-weight: 500;
                padding: 4px 12px;
            }}

            QPushButton:hover {{
                background-color: {p['btn_hover']};
                border-color: #0071e3;
            }}

            QPushButton:pressed {{
                background-color: {p['btn_pressed']};
            }}

            QPushButton:disabled {{
                background-color: {p['btn_disabled_bg']};
                color: {p['btn_disabled_fg']};
                border-color: transparent;
            }}

            QPushButton#theme_toggle_btn {{
                border-radius: 8px;
                padding: 5px 10px;
                font-size: 8.5pt;
                font-weight: 600;
            }}

            QPushButton#primary_action {{
                background: #0071e3;
                color: #ffffff;
                font-weight: 700;
                font-size: 10pt;
                border: none;
                border-radius: 8px;
                padding: 6px 20px;
            }}

            QPushButton#primary_action:hover {{
                background: #0077ed;
            }}

            QPushButton#primary_action:pressed {{
                background: #005bb5;
            }}

            QPushButton#cancel_action {{
                background-color: rgba(255, 69, 58, 0.15);
                color: #ff453a;
                border: 1px solid rgba(255, 69, 58, 0.3);
                border-radius: 8px;
                font-weight: 600;
                font-size: 9pt;
                padding: 6px 14px;
            }}

            QPushButton#cancel_action:hover {{
                background-color: #ff453a;
                color: #ffffff;
            }}

            QProgressBar {{
                border: none;
                border-radius: 3px;
                background-color: {p['progress_bg']};
                text-align: center;
                color: transparent;
                min-height: 6px;
                max-height: 6px;
            }}

            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0071e3, stop:1 #30d158);
                border-radius: 3px;
            }}

            QTableWidget {{
                background-color: {p['table_bg']};
                alternate-background-color: {p['table_alt']};
                color: {p['text']};
                gridline-color: transparent;
                border: 1px solid {p['card_border']};
                border-radius: 8px;
                selection-background-color: rgba(0, 113, 227, 0.25);
                selection-color: {p['text']};
                font-size: 9pt;
            }}

            QHeaderView::section {{
                background-color: {p['table_header_bg']};
                color: {p['table_header_fg']};
                font-weight: 600;
                font-size: 8.5pt;
                border: none;
                border-bottom: 1px solid {p['card_border']};
                padding: 6px 8px;
            }}

            QCheckBox {{
                background-color: transparent;
                color: {p['text']};
                spacing: 8px;
                font-size: 9pt;
            }}

            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 1px solid {p['checkbox_border']};
                border-radius: 4px;
                background-color: {p['checkbox_bg']};
            }}

            QCheckBox::indicator:checked {{
                background-color: #0071e3;
                border-color: #0071e3;
            }}

            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 2px 0;
            }}

            QScrollBar::handle:vertical {{
                background: {p['scroll_handle']};
                min-height: 24px;
                border-radius: 4px;
            }}

            QScrollBar::handle:vertical:hover {{
                background: {p['scroll_hover']};
            }}

            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}

            QScrollBar:horizontal {{
                background: transparent;
                height: 8px;
                margin: 0 2px;
            }}

            QScrollBar::handle:horizontal {{
                background: {p['scroll_handle']};
                min-width: 24px;
                border-radius: 4px;
            }}

            QScrollBar::handle:horizontal:hover {{
                background: {p['scroll_hover']};
            }}

            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}

            QMenu {{
                background-color: {p['menu_bg']};
                color: {p['text']};
                border: 1px solid {p['input_border']};
                border-radius: 8px;
                padding: 4px;
            }}

            QMenu::item {{
                padding: 6px 20px;
                border-radius: 5px;
            }}

            QMenu::item:selected {{
                background-color: #0071e3;
                color: #ffffff;
            }}
        """)

    def load_settings_file(self):
        self.settings_data = self.read_json_file(SETTINGS_FILE, default={}) or {}

    def setting_value(self, key, default=None, value_type=None):
        value = self.settings_data.get(key, default)
        if value_type is bool:
            return bool(value)
        if value_type is int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return int(default or 0)
        return value

    def load_settings(self):
        self.applying_preset = True
        self.output_input.setText(self.setting_value("output_dir", self.default_output))
        self.ffmpeg_input.setText(self.setting_value("ffmpeg_path", ""))
        self.playlist_checkbox.setChecked(self.setting_value("playlist_enabled", False, bool))
        self.playlist_start.setValue(self.setting_value("playlist_start", 0, int))
        self.playlist_end.setValue(self.setting_value("playlist_end", 0, int))
        self.subtitle_lang_input.setText(self.setting_value("subtitle_langs", "id,en"))
        self.audio_bitrate.setValue(self.setting_value("audio_bitrate", 192, int))
        self.speed_limit.setValue(self.setting_value("speed_limit_mbps", 0, int))
        self.fragment_concurrency.setValue(self.setting_value("fragment_concurrency", 4, int))
        self.auto_container_checkbox.setChecked(self.setting_value("auto_container", True, bool))
        self.sort_media_checkbox.setChecked(self.setting_value("sort_media_folders", True, bool))
        self.platform_sort_checkbox.setChecked(self.setting_value("platform_sort_folders", True, bool))
        self.thumbnail_checkbox.setChecked(self.setting_value("download_thumbnail", False, bool))
        self.embed_metadata_checkbox.setChecked(self.setting_value("embed_metadata", False, bool))
        self.subtitle_optional_checkbox.setChecked(self.setting_value("subtitle_optional", True, bool))
        self.cookies_file_input.setText(self.setting_value("cookies_file", ""))
        self.debug_checkbox.setChecked(self.setting_value("debug_mode", False, bool))
        self.set_combo_value(self.quality_combo, self.setting_value("quality", "1080p"))
        self.set_combo_value(self.quality_mode_combo, self.setting_value("quality_mode", "Best up to selected"))
        self.set_combo_value(self.format_combo, self.setting_value("file_format", "MP4 Video"))
        self.set_combo_value(self.subtitle_mode_combo, self.setting_value("subtitle_mode", "Off"))
        self.set_combo_value(self.cookies_combo, self.setting_value("cookies_browser", "None"))
        self.set_combo_value(self.filename_template_combo, self.setting_value("filename_template", "Title [ID]"))
        self.set_combo_value(self.check_mode_combo, self.setting_value("check_mode", "Full check"))
        self.set_combo_value(self.codec_combo, self.setting_value("codec_preference", "Auto"))
        self.set_combo_value(self.audio_pref_combo, self.setting_value("audio_preference", "Auto"))
        self.set_combo_value(self.preset_combo, self.setting_value("preset_profile", "Custom"))
        self.set_combo_value(self.mode_combo, self.setting_value("ui_mode", "Simple Mode"))
        saved_theme = str(self.setting_value("theme_mode", "dark")).lower()
        self.theme_mode = saved_theme if saved_theme in ("dark", "light") else "dark"
        self.applying_preset = False
        self.apply_ui_mode()
        self.update_high_res_hint()

    def save_settings(self):
        self.settings_data = {
            "app_version": APP_VERSION,
            "output_dir": self.output_input.text().strip(),
            "ffmpeg_path": self.ffmpeg_input.text().strip(),
            "playlist_enabled": self.playlist_checkbox.isChecked(),
            "playlist_start": self.playlist_start.value(),
            "playlist_end": self.playlist_end.value(),
            "subtitle_langs": self.subtitle_lang_input.text().strip(),
            "audio_bitrate": self.audio_bitrate.value(),
            "speed_limit_mbps": self.speed_limit.value(),
            "fragment_concurrency": self.fragment_concurrency.value(),
            "auto_container": self.auto_container_checkbox.isChecked(),
            "sort_media_folders": self.sort_media_checkbox.isChecked(),
            "platform_sort_folders": self.platform_sort_checkbox.isChecked(),
            "download_thumbnail": self.thumbnail_checkbox.isChecked(),
            "embed_metadata": self.embed_metadata_checkbox.isChecked(),
            "subtitle_optional": self.subtitle_optional_checkbox.isChecked(),
            "cookies_file": self.cookies_file_input.text().strip(),
            "debug_mode": self.debug_checkbox.isChecked(),
            "quality": self.quality_combo.currentText(),
            "quality_mode": self.quality_mode_combo.currentText(),
            "file_format": self.format_combo.currentText(),
            "subtitle_mode": self.subtitle_mode_combo.currentText(),
            "cookies_browser": self.cookies_combo.currentText(),
            "filename_template": self.filename_template_combo.currentText(),
            "check_mode": self.check_mode_combo.currentText(),
            "codec_preference": self.codec_combo.currentText(),
            "audio_preference": self.audio_pref_combo.currentText(),
            "preset_profile": self.preset_combo.currentText(),
            "ui_mode": self.mode_combo.currentText(),
            "theme_mode": getattr(self, "theme_mode", "dark"),
        }
        self.write_json_file(SETTINGS_FILE, self.settings_data)

    def set_combo_value(self, combo, value):
        index = combo.findText(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def update_mode_visibility(self):
        self.apply_ui_mode()

    def apply_ui_mode(self):
        if not hasattr(self, "tabs"):
            return
        is_power = self.mode_combo.currentText() == "Power Mode"
        for index in range(1, self.tabs.count()):
            self.tabs.setTabEnabled(index, is_power)
            if hasattr(self, "nav_list"):
                for r in range(self.nav_list.count()):
                    it = self.nav_list.item(r)
                    if it.data(Qt.UserRole) == index:
                        it.setFlags(it.flags() | Qt.ItemIsEnabled if is_power else it.flags() & ~Qt.ItemIsEnabled)
        if not is_power and self.tabs.currentIndex() > 0:
            self.tabs.setCurrentIndex(0)
        if hasattr(self, "preset_label") and self.preset_label:
            self.preset_label.setVisible(is_power)
        if hasattr(self, "preset_combo") and self.preset_combo:
            self.preset_combo.setVisible(is_power)
        if hasattr(self, "format_label") and self.format_label:
            self.format_label.setVisible(is_power)
        if hasattr(self, "format_combo") and self.format_combo:
            self.format_combo.setVisible(is_power)
        if hasattr(self, "media_type_label") and self.media_type_label:
            self.media_type_label.setVisible(not is_power)
        if hasattr(self, "media_type_combo") and self.media_type_combo:
            self.media_type_combo.setVisible(not is_power)
        if hasattr(self, "power_download_controls") and self.power_download_controls:
            self.power_download_controls.setVisible(is_power)
        if hasattr(self, "legacy_channel_controls") and self.legacy_channel_controls:
            self.legacy_channel_controls.setVisible(is_power)
        if hasattr(self, "format_combo") and hasattr(self, "media_type_combo"):
            self.sync_media_type_from_format(self.format_combo.currentText())
        if not self.applying_preset:
            self.save_settings()

    def on_media_type_changed(self, text):
        if self.updating_media_type:
            return
        if text == "Audio":
            target = self._last_audio_format if self._last_audio_format in AUDIO_FORMATS else "MP3 Audio"
            self.set_combo_value(self.format_combo, target)
        else:
            target = self._last_video_format if self._last_video_format in VIDEO_FORMATS else "MP4 Video"
            self.set_combo_value(self.format_combo, target)

    def sync_media_type_from_format(self, format_name):
        if format_name in AUDIO_FORMATS:
            self._last_audio_format = format_name
            if hasattr(self, "media_type_combo") and self.media_type_combo.currentText() != "Audio":
                self.updating_media_type = True
                self.set_combo_value(self.media_type_combo, "Audio")
                self.updating_media_type = False
        elif format_name in VIDEO_FORMATS:
            self._last_video_format = format_name
            if hasattr(self, "media_type_combo") and self.media_type_combo.currentText() != "Video":
                self.updating_media_type = True
                self.set_combo_value(self.media_type_combo, "Video")
                self.updating_media_type = False

    def mark_custom_preset(self, *args):
        if self.applying_preset:
            return
        if self.preset_combo.currentText() != "Custom":
            self.applying_preset = True
            self.set_combo_value(self.preset_combo, "Custom")
            self.applying_preset = False
        self.update_high_res_hint()

    def apply_preset(self, name):
        if self.applying_preset:
            return
        profile = PRESET_PROFILES.get(name) or {}
        if not profile:
            return
        self.applying_preset = True
        if "quality" in profile:
            self.set_combo_value(self.quality_combo, profile["quality"])
        if "quality_mode" in profile:
            self.set_combo_value(self.quality_mode_combo, profile["quality_mode"])
        if "format" in profile:
            self.set_combo_value(self.format_combo, profile["format"])
        if "subtitle" in profile:
            self.set_combo_value(self.subtitle_mode_combo, profile["subtitle"])
        if "audio_bitrate" in profile:
            self.audio_bitrate.setValue(profile["audio_bitrate"])
        if "auto_container" in profile:
            self.auto_container_checkbox.setChecked(profile["auto_container"])
        if "playlist" in profile:
            self.playlist_checkbox.setChecked(profile["playlist"])
        if "fragments" in profile:
            self.fragment_concurrency.setValue(profile["fragments"])
        self.applying_preset = False
        self.update_audio_controls(self.format_combo.currentText())
        self.update_high_res_hint()
        self.update_target_info()
        self.apply_ui_mode()

    def on_tab_changed(self, index):
        titles = [
            "Download Video & Audio",
            "Pengaturan Lanjutan (Advanced)",
            "Subtitle & Browser Cookies",
            "Folder Output & Engine FFmpeg",
            "Riwayat Download (History)",
        ]
        if hasattr(self, "page_title") and 0 <= index < len(titles):
            self.page_title.setText(titles[index])

        if hasattr(self, "nav_list"):
            for r in range(self.nav_list.count()):
                it = self.nav_list.item(r)
                if it.data(Qt.UserRole) == index:
                    if self.nav_list.currentRow() != r:
                        self.nav_list.setCurrentRow(r)
                    break

        if self.tabs.tabText(index) == "History" and not getattr(self, "history_loaded", False):
            self.history_loaded = True
            self.refresh_history()

    def on_queue_selection_changed(self):
        rows = self.queue_table.selectionModel().selectedRows()
        if rows:
            r = rows[0].row()
            if 0 <= r < len(self.queue_items):
                self.update_target_info(self.queue_items[r])
                return
        self.update_target_info()

    def update_target_info(self, item=None):
        if not hasattr(self, "target_info_label"):
            return
        format_str = self.format_combo.currentText()
        if format_str in AUDIO_FORMATS:
            container = format_str.split()[0]
            bitrate = self.audio_bitrate.value()
            self.target_info_label.setText(f"Target: Audio ({container}) • {bitrate} kbps")
            return
        if format_str in IMAGE_FORMATS:
            self.target_info_label.setText("Target: Image (Original)")
            return

        quality = self.quality_combo.currentText()
        auto_mkv = self.auto_container_checkbox.isChecked()
        container = "Auto (MKV/MP4)" if auto_mkv else format_str.split()[0]

        if item:
            actual = item.get("actual_format") or item.get("resolution")
            available = item.get("qualities") or item.get("quality_sizes")
            if actual and actual != "-":
                self.target_info_label.setText(f"Target: {quality} • Actual: {actual} • {container}")
                return
            elif available and available != "-":
                self.target_info_label.setText(f"Target: {quality} • Available: {available} • {container}")
                return

        self.target_info_label.setText(f"Target: {quality} • Container: {container}")

    def show_engine_health_dialog(self):
        try:
            import yt_dlp
            ytdlp_ver = getattr(yt_dlp, "__version__", "Available")
            ytdlp_status = f"{ytdlp_ver} (OK)"
        except Exception as e:
            ytdlp_status = f"Unavailable ({e})"

        ffmpeg_path = resolve_ffmpeg(self.ffmpeg_input.text().strip())
        if ffmpeg_path:
            try:
                out = subprocess.check_output([ffmpeg_path, "-version"], stderr=subprocess.STDOUT, text=True, timeout=3)
                first_line = out.splitlines()[0] if out else "OK"
                ffmpeg_status = f"OK ({first_line[:40]}...)"
            except Exception:
                ffmpeg_status = f"OK ({ffmpeg_path})"
        else:
            ffmpeg_status = "Not found (isi path di tab Output / FFmpeg)"

        ffprobe_path = resolve_ffprobe(self.ffmpeg_input.text().strip())
        if ffprobe_path:
            try:
                out = subprocess.check_output([ffprobe_path, "-version"], stderr=subprocess.STDOUT, text=True, timeout=3)
                first_line = out.splitlines()[0] if out else "OK"
                ffprobe_status = f"OK ({first_line[:40]}...)"
            except Exception:
                ffprobe_status = f"OK ({ffprobe_path})"
        else:
            ffprobe_status = "Not found"

        try:
            import yt_dlp_ejs
            js_status = f"yt-dlp-ejs {getattr(yt_dlp_ejs, '__version__', 'Installed')} (OK)"
        except ImportError:
            js_status = "Built-in / Deno / Node fallback"

        text = (
            f"Downloader Engine Status\n"
            f"-----------------------------------------\n"
            f"yt-dlp:    {ytdlp_status}\n"
            f"FFmpeg:    {ffmpeg_status}\n"
            f"FFprobe:   {ffprobe_status}\n"
            f"JS Engine: {js_status}\n\n"
            f"Komponen inti diperiksa secara lokal (tanpa internet)."
        )

        msg = QMessageBox(self)
        msg.setWindowTitle("Downloader Engine Health")
        msg.setText(text)
        msg.setIcon(QMessageBox.Information)
        msg.exec()

    def update_high_res_hint(self):
        if self.format_combo.currentText() in AUDIO_FORMATS | IMAGE_FORMATS:
            self.high_res_hint_label.setText("")
            return
        height = QUALITY_HEIGHTS.get(self.quality_combo.currentText()) or 0
        if height >= 2160 and not self.auto_container_checkbox.isChecked():
            self.auto_container_checkbox.setChecked(True)
            return
        if height >= 2160:
            self.high_res_hint_label.setText("For 4K/8K, MKV is recommended to avoid slow conversion.")
        elif (
            self.format_combo.currentText() == "MP4 Video"
            and self.codec_combo.currentText() in {"VP9", "AV1"}
            and height >= 1440
        ):
            self.high_res_hint_label.setText(
                "MP4 may be slower or less compatible for VP9/AV1 high-res videos. MKV is safer."
            )
        else:
            self.high_res_hint_label.setText("")

    def parse_urls(self):
        return [
            line.strip()
            for line in self.urls_input.toPlainText().splitlines()
            if line.strip()
        ]

    def is_image_mode(self):
        return self.format_combo.currentText() in IMAGE_FORMATS

    def image_queue_items_from_urls(self, urls):
        items = []
        for url in urls:
            platform = detect_platform_from_info({}, url)
            key = video_key(url)
            items.append({
                "url": url,
                "title": url,
                "platform": platform,
                "qualities": "Original image",
                "quality_sizes": "Original image",
                "size": "-",
                "key": key,
                "video_id": key,
                "media_type": "Image",
            })
        return items

    def prepare_image_queue(self, urls, prompt_duplicates=True):
        items = self.image_queue_items_from_urls(urls)
        self.prepare_queue_table(items, prompt_duplicates)
        self.log(
            f"Queue gambar siap: {len(items)} item. "
            "Download akan mengambil resolusi tertinggi yang tersedia."
        )

    def fetch_channel_videos(self):
        channel_url = self.channel_url_input.text().strip()
        keyword = self.channel_keyword_input.text().strip()

        if not channel_url:
            message = "URL channel masih kosong."
            self.channel_status_label.setText(message)
            self.log(message)
            return
        if not keyword:
            message = "Keyword judul masih kosong."
            self.channel_status_label.setText(message)
            self.log(message)
            return
        if self.thread and self.thread.isRunning():
            self.log("Download masih berjalan.")
            return
        if self.metadata_thread and self.metadata_thread.isRunning():
            self.log("Cek resolusi masih berjalan.")
            return
        if self.test_thread and self.test_thread.isRunning():
            self.log("Test Link masih berjalan.")
            return
        if self.channel_thread and self.channel_thread.isRunning():
            self.log("Ambil dari Channel masih berjalan.")
            return

        self.save_settings()
        self.channel_fetch_btn.setEnabled(False)
        self.channel_status_label.setText("Mengambil daftar video channel...")
        self.status_label.setText("Mengambil daftar video channel...")
        self.log("Mengambil daftar video channel...")

        self.channel_thread = ChannelVideosThread(
            channel_url=channel_url,
            keyword=keyword,
            cookies_browser=self.cookies_combo.currentText(),
            cookies_file=self.cookies_file_input.text().strip(),
        )
        self.channel_thread.log.connect(self.log)
        self.channel_thread.queue_ready.connect(self.handle_channel_queue_ready)
        self.channel_thread.error.connect(self.handle_channel_fetch_error)
        self.channel_thread.done.connect(self.channel_fetch_finished)
        self.channel_thread.start()

    def handle_channel_queue_ready(self, items, stats):
        stats = stats or {}
        message = (
            f"Channel: {stats.get('total', 0)} video ditemukan, "
            f"{stats.get('matched', 0)} match keyword, "
            f"{stats.get('queued', len(items))} item dikirim ke queue."
        )

        if not items:
            message = f"{message} Tidak ada item yang cocok untuk ditambahkan."
            self.channel_status_label.setText(message)
            self.status_label.setText("Ready")
            self.log(message)
            return

        before_count = len(self.queue_items)
        self.prepare_queue_table(items, True)
        added_count = max(0, len(self.queue_items) - before_count)
        message = f"{message} Item baru di queue: {added_count}."
        self.channel_status_label.setText(message)
        self.status_label.setText("Ready")
        self.log(message)

    def handle_channel_fetch_error(self, message):
        self.channel_status_label.setText(message)
        self.status_label.setText("Ready")
        self.log(message)

    def channel_fetch_finished(self):
        self.channel_fetch_btn.setEnabled(True)
        if self.status_label.text() == "Mengambil daftar video channel...":
            self.status_label.setText("Ready")
        self.channel_thread = None

    def open_channel_preview(self):
        url = self.channel_url_input.text().strip()
        if not url:
            urls = self.parse_urls()
            if urls:
                url = urls[0]

        if self.thread and self.thread.isRunning():
            self.log("Download masih berjalan.")
            return
        if self.metadata_thread and self.metadata_thread.isRunning():
            self.log("Cek resolusi masih berjalan.")
            return
        if self.test_thread and self.test_thread.isRunning():
            self.log("Test Link masih berjalan.")
            return

        self.save_settings()

        dialog = ChannelPreviewDialog(
            parent=self,
            initial_url=url,
            cookies_browser=self.cookies_combo.currentText(),
            cookies_file=self.cookies_file_input.text().strip(),
            theme=getattr(self, "theme_mode", "dark"),
        )
        dialog.items_selected.connect(self.handle_channel_preview_items)
        if dialog.exec():
            scanned_url = dialog.url_input.text().strip()
            if scanned_url and not self.channel_url_input.text().strip():
                self.channel_url_input.setText(scanned_url)

    def handle_channel_preview_items(self, items):
        if not items:
            return

        queue_items = []
        for item in items:
            queue_items.append({
                "url": item["url"],
                "title": item.get("title") or item["url"],
                "platform": item.get("platform") or "YouTube",
                "video_id": item.get("video_id") or item.get("key"),
                "key": item.get("key") or item.get("video_id"),
                "playlist_index": item.get("playlist_index"),
                "source": item.get("source") or "Channel Preview",
                "status": "Queued",
                "progress": 0,
            })

        before_count = len(self.queue_items)
        self.prepare_queue_table(queue_items, prompt_duplicates=True)
        added_count = max(0, len(self.queue_items) - before_count)
        message = f"Preview: {len(items)} video dipilih, {added_count} ditambahkan ke queue."
        self.channel_status_label.setText(message)
        self.log(message)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Pilih Folder Output")
        if folder:
            self.output_input.setText(folder)
            self.save_settings()

    def choose_ffmpeg(self):
        path, _ = QFileDialog.getOpenFileName(self, "Pilih ffmpeg.exe", "", "FFmpeg (ffmpeg.exe)")
        if path:
            self.ffmpeg_input.setText(path)
            self.save_settings()
            self.refresh_ffmpeg_status()

    def choose_cookies_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Pilih cookies.txt", "", "Cookies (*.txt);;All files (*.*)")
        if path:
            self.cookies_file_input.setText(path)
            self.save_settings()

    def autodetect_ffmpeg(self):
        ffmpeg = find_common_ffmpeg()
        if ffmpeg:
            self.ffmpeg_input.setText(ffmpeg)
            self.log(f"FFmpeg ditemukan: {ffmpeg}")
        else:
            self.log("FFmpeg tidak ditemukan otomatis.")
        self.save_settings()
        self.refresh_ffmpeg_status()

    def open_output_folder(self):
        folder = self.output_input.text().strip()
        if not folder:
            self.log("Folder output masih kosong.")
            return
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def refresh_ffmpeg_status(self):
        ffmpeg = resolve_ffmpeg(self.ffmpeg_input.text().strip())
        if ffmpeg:
            self.ffmpeg_status_label.setText(f"FFmpeg OK: {ffmpeg}")
            self.status_label.setText("Ready - FFmpeg OK")
            self.update_header_status("FFmpeg OK", "ready")
        else:
            self.ffmpeg_status_label.setText("FFmpeg tidak ditemukan. Isi path untuk 4K/audio/metadata.")
            self.status_label.setText("Ready - FFmpeg tidak ditemukan")
            self.update_header_status("FFmpeg Missing", "warning")

    def update_audio_controls(self, file_format):
        is_audio = file_format in AUDIO_FORMATS
        is_image = file_format in IMAGE_FORMATS
        is_video = file_format in VIDEO_FORMATS
        self.audio_bitrate.setEnabled(is_audio)
        self.quality_combo.setEnabled(is_video)
        self.quality_mode_combo.setEnabled(is_video)
        self.auto_container_checkbox.setEnabled(is_video)
        self.codec_combo.setEnabled(is_video)
        self.audio_pref_combo.setEnabled(is_audio)
        self.thumbnail_checkbox.setEnabled(not is_image)
        self.embed_metadata_checkbox.setEnabled(not is_image)
        self.update_high_res_hint()

    def prepare_queue_table(self, items, prompt_duplicates=False):
        existing = list(self.queue_items)
        if prompt_duplicates:
            items = self.resolve_duplicate_items(items)
            if not items:
                self.log("Tidak ada item baru yang ditambahkan.")
                return
            if existing:
                items = existing + items
        self.queue_items = items
        self.queue_table.setRowCount(len(items))
        for row, item in enumerate(items):
            title = item.get("title") or item.get("url")
            quality = item.get("actual_format") or item.get("quality_sizes") or item.get("qualities") or "-"
            size = item.get("size") or "-"
            status = item.get("status", "Queued")
            progress = item.get("progress", 0)
            self.queue_table.setItem(row, 0, QTableWidgetItem(title))
            self.queue_table.setItem(row, 1, QTableWidgetItem(item.get("platform", "Other")))
            self.queue_table.setItem(row, 2, QTableWidgetItem(quality))
            self.queue_table.setItem(row, 3, QTableWidgetItem(size))
            status_item = QTableWidgetItem(status)
            self._apply_status_item_style(status_item, status)
            self.queue_table.setItem(row, 4, status_item)
            self.queue_table.setItem(row, 5, QTableWidgetItem(f"{progress}%"))
            self.queue_table.setItem(row, 6, QTableWidgetItem(item.get("speed", "-")))
            self.queue_table.setItem(row, 7, QTableWidgetItem(item.get("eta", "-")))
            self.queue_table.setItem(row, 8, QTableWidgetItem(item.get("output_path", "")))
            self.queue_table.setRowHeight(row, 32)
        self.save_state()
        if items:
            self.queue_table.scrollToItem(self.queue_table.item(len(items) - 1, 0))
            self.queue_table.viewport().update()

    def queue_item_identity(self, item):
        platform = item.get("platform", "Other")
        key = item.get("video_id") or item.get("key") or video_key(item.get("url", ""))
        return platform_video_key(platform, key)

    def queue_urls(self):
        return [
            item.get("url")
            for item in self.queue_items
            if item.get("url")
        ]

    def merge_queue_metadata(self, checked_items):
        metadata_by_key = {}
        metadata_by_url = {}
        for item in checked_items:
            metadata_by_key[self.queue_item_identity(item)] = item
            if item.get("url"):
                metadata_by_url[item.get("url")] = item

        merged = []
        updated_count = 0
        for item in self.queue_items:
            match = metadata_by_key.get(self.queue_item_identity(item))
            if not match and item.get("url"):
                match = metadata_by_url.get(item.get("url"))

            if match:
                merged_item = dict(item)
                merged_item.update(match)
                merged.append(merged_item)
                updated_count += 1
            else:
                merged.append(item)

        self.prepare_queue_table(merged)
        self.log(f"Resolusi queue diperbarui: {updated_count}/{len(merged)} item.")

    def resolve_duplicate_items(self, new_items):
        existing_keys = {
            platform_video_key(item.get("platform", "Other"), item.get("video_id") or item.get("key")): index
            for index, item in enumerate(self.queue_items)
        }
        history = self.load_history_items()
        history_by_key = {
            platform_video_key(item.get("platform", "Other"), item.get("video_id") or item.get("key")): item
            for item in history
            if item.get("status") in DONE_STATUSES or item.get("status") == "Done"
        }
        resolved = []
        for item in new_items:
            key = platform_video_key(item.get("platform", "Other"), item.get("video_id") or item.get("key"))
            if key in existing_keys:
                choice = self.ask_queue_duplicate(existing_keys[key], item.get("platform", "Other"))
                if choice == "add":
                    resolved.append(item)
                elif choice == "focus":
                    self.queue_table.selectRow(existing_keys[key])
                continue
            hist = history_by_key.get(key)
            if hist:
                choice = self.ask_history_duplicate(hist, item.get("platform", "Other"))
                if choice == "open":
                    self.open_path_or_folder(hist.get("output_path") or hist.get("file"))
                elif choice == "download":
                    resolved.append(item)
                continue
            resolved.append(item)
        return resolved

    def paste_from_clipboard(self):
        clip = QApplication.clipboard().text().strip()
        if not clip:
            self.log("Clipboard kosong.")
            return
        current = self.urls_input.toPlainText().strip()
        if current:
            if clip in current:
                self.log("Link sudah ada di daftar input.")
                return
            self.urls_input.setPlainText(current + "\n" + clip)
        else:
            self.urls_input.setPlainText(clip)
        self.log(f"Link ditambahkan dari clipboard: {clip[:60]}...")

    def toggle_log_visibility(self):
        is_visible = self.log_box.isVisible()
        self.log_box.setVisible(not is_visible)
        self.toggle_log_btn.setText("📜 Tampilkan Log" if is_visible else "📜 Sembunyikan Log")

    def on_queue_double_clicked(self, row, column):
        if 0 <= row < len(self.queue_items):
            path = self.queue_items[row].get("output_path")
            if path and os.path.exists(path):
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            else:
                self.open_selected_folder()

    def update_header_status(self, text, kind="ready"):
        if not hasattr(self, "header_status_chip"):
            return
        if kind == "ready":
            self.header_status_chip.setText(f"● {text}")
            self.header_status_chip.setStyleSheet("font-size: 8.5pt; font-weight: 600; color: #30d158; background-color: rgba(48, 209, 88, 0.12); border: 1px solid rgba(48, 209, 88, 0.25); border-radius: 10px; padding: 3px 12px;")
        elif kind == "busy":
            self.header_status_chip.setText(f"● {text}")
            self.header_status_chip.setStyleSheet("font-size: 8.5pt; font-weight: 600; color: #0a84ff; background-color: rgba(10, 132, 255, 0.15); border: 1px solid rgba(10, 132, 255, 0.3); border-radius: 10px; padding: 3px 12px;")
        elif kind == "warning":
            self.header_status_chip.setText(f"● {text}")
            self.header_status_chip.setStyleSheet("font-size: 8.5pt; font-weight: 600; color: #ff9f0a; background-color: rgba(255, 159, 10, 0.15); border: 1px solid rgba(255, 159, 10, 0.3); border-radius: 10px; padding: 3px 12px;")
        elif kind == "error":
            self.header_status_chip.setText(f"● {text}")
            self.header_status_chip.setStyleSheet("font-size: 8.5pt; font-weight: 600; color: #ff453a; background-color: rgba(255, 69, 58, 0.15); border: 1px solid rgba(255, 69, 58, 0.3); border-radius: 10px; padding: 3px 12px;")

    def _apply_status_item_style(self, item, status):
        if not item:
            return
        font = item.font()
        font.setBold(True)
        item.setFont(font)
        if status in {"Done", "Done with warning"}:
            item.setForeground(QColor("#30d158"))
        elif status in {"Failed", "Error", "Cancelled", "Canceled"}:
            item.setForeground(QColor("#ff453a"))
        elif status in {"Downloading", "In progress", "Running"}:
            item.setForeground(QColor("#0a84ff"))
        elif status in {"Merging", "Post-processing", "Moving final file"}:
            item.setForeground(QColor("#ff9f0a"))
        else:
            item.setForeground(QColor("#a1a1a6"))

    def _setup_shortcuts(self):
        for seq in ("Ctrl+Return", "Ctrl+Enter"):
            sc = QShortcut(QKeySequence(seq), self)
            sc.activated.connect(self.start_download)
        del_sc = QShortcut(QKeySequence(Qt.Key_Delete), self.queue_table)
        del_sc.setContext(Qt.WidgetShortcut)
        del_sc.activated.connect(self.delete_selected_queue_rows)

    def delete_selected_queue_rows(self):
        if self.thread and self.thread.isRunning():
            self.status_label.setText("Tidak bisa hapus item saat download berjalan")
            self.log("Tidak bisa hapus item saat download masih berjalan.")
            return
        selected = {idx.row() for idx in self.queue_table.selectedIndexes()}
        if not selected:
            return
        remaining = [
            item for idx, item in enumerate(self.queue_items) if idx not in selected
        ]
        self.prepare_queue_table(remaining)
        self.update_target_info()

    def invalidate_queue(self):
        if self.thread and self.thread.isRunning():
            return
        if self.metadata_thread and self.metadata_thread.isRunning():
            return
        if self.test_thread and self.test_thread.isRunning():
            return
        if not self.urls_input.toPlainText().strip():
            # Pertahankan item yang berasal dari Channel Preview / Playlist Preview
            has_channel_items = any(
                item.get("source") in ("Channel Preview", "channel_preview")
                for item in self.queue_items
            )
            if not has_channel_items:
                self.queue_items = []
                self._last_checked_urls = []
                self.queue_table.setRowCount(0)

    def test_links(self):
        urls = self.parse_urls()
        if not urls:
            self.log("Link masih kosong.")
            return
        if self.thread and self.thread.isRunning():
            self.log("Download masih berjalan.")
            return
        if self.metadata_thread and self.metadata_thread.isRunning():
            self.log("Cek resolusi masih berjalan.")
            return
        if self.test_thread and self.test_thread.isRunning():
            self.log("Test Link masih berjalan.")
            return

        self.save_settings()
        self.set_testing_state(True)
        self.log_box.clear()
        self.log("Mengetes link...")
        self.test_thread = TestLinkThread(
            urls=urls,
            cookies_browser=self.cookies_combo.currentText(),
            cookies_file=self.cookies_file_input.text().strip(),
        )
        self.test_thread.log.connect(self.log)
        self.test_thread.done.connect(self.test_link_finished)
        self.test_thread.start()

    def test_link_finished(self, success, message):
        self.set_testing_state(False)
        self.log(message)

    def check_resolution(self):
        urls = self.parse_urls()
        check_existing_queue = False
        if not urls:
            urls = self.queue_urls()
            check_existing_queue = bool(urls)
            if not urls:
                self.log("Link masih kosong dan queue kosong.")
                return

        if self.is_image_mode():
            self.log_box.clear()
            self.prepare_image_queue(urls, prompt_duplicates=not check_existing_queue)
            return

        if self.metadata_thread and self.metadata_thread.isRunning():
            self.log("Cek resolusi masih berjalan.")
            return
        if self.test_thread and self.test_thread.isRunning():
            self.log("Test Link masih berjalan.")
            return

        self.save_settings()
        if not check_existing_queue:
            self._last_checked_urls = list(urls)
        self.auto_start_after_check = False
        self.set_checking_state(True)
        self.log_box.clear()
        if check_existing_queue:
            self.log("Mengecek metadata dan resolusi dari queue...")
        else:
            self.log("Mengecek metadata dan resolusi...")
        self.metadata_thread = MetadataThread(
            urls=urls,
            playlist_enabled=False if check_existing_queue else self.playlist_checkbox.isChecked(),
            cookies_browser=self.cookies_combo.currentText(),
            cookies_file=self.cookies_file_input.text().strip(),
            playlist_start=self.playlist_start.value(),
            playlist_end=self.playlist_end.value(),
            check_mode=self.check_mode_combo.currentText(),
        )
        self.metadata_thread.log.connect(self.log)
        if check_existing_queue:
            self.metadata_thread.queue_ready.connect(self.merge_queue_metadata)
        else:
            self.metadata_thread.queue_ready.connect(lambda items: self.prepare_queue_table(items, True))
        self.metadata_thread.done.connect(self.metadata_finished)
        self.metadata_thread.start()

    def start_download(self):
        urls = self.parse_urls()
        output_dir = self.output_input.text().strip()

        if not urls and not self.queue_items:
            self.status_label.setText("Link masih kosong")
            self.update_header_status("Link masih kosong", "warning")
            self.log("Link masih kosong dan queue kosong.")
            return
        if not output_dir:
            self.status_label.setText("Folder output kosong")
            self.update_header_status("Folder output kosong", "warning")
            self.log("Folder output masih kosong.")
            return
        if self.thread and self.thread.isRunning():
            self.log("Download masih berjalan.")
            return
        if self.test_thread and self.test_thread.isRunning():
            self.log("Test Link masih berjalan.")
            return

        self.save_settings()

        # Jika user mengubah/paste link baru di urls_input setelah Cek Resolusi sebelumnya,
        # sinkronkan antrean agar link baru yang diproses (kecuali item berasal dari Channel Preview).
        if urls and self.queue_items and urls != getattr(self, "_last_checked_urls", []):
            has_channel_items = any(
                item.get("source") in ("Channel Preview", "channel_preview")
                for item in self.queue_items
            )
            if not has_channel_items:
                self.queue_items = []
                self.queue_table.setRowCount(0)

        if not self.queue_items:
            self._last_checked_urls = list(urls)
            if self.is_image_mode():
                self.prepare_image_queue(urls, prompt_duplicates=True)
                self.start_download_thread()
                return

            self.auto_start_after_check = True
            self.set_checking_state(True)
            self.log_box.clear()
            self.log("Menyiapkan queue...")
            self.metadata_thread = MetadataThread(
                urls=urls,
                playlist_enabled=self.playlist_checkbox.isChecked(),
                cookies_browser=self.cookies_combo.currentText(),
                cookies_file=self.cookies_file_input.text().strip(),
                playlist_start=self.playlist_start.value(),
                playlist_end=self.playlist_end.value(),
                check_mode=self.check_mode_combo.currentText(),
            )
            self.metadata_thread.log.connect(self.log)
            self.metadata_thread.queue_ready.connect(lambda items: self.prepare_queue_table(items, True))
            self.metadata_thread.done.connect(self.metadata_finished)
            self.metadata_thread.start()
            return

        self.start_download_thread()

    def start_download_thread(self):
        if not self.queue_items:
            self.log("Queue kosong. Jalankan Cek Resolusi dulu.")
            return
        if not self.confirm_disk_space_for_large_files():
            self.log("Download dibatalkan karena storage check.")
            return

        self.progress_bar.setValue(0)
        self.set_running_state(True)
        self.thread = DownloadThread(
            items=self.queue_items,
            quality=self.quality_combo.currentText(),
            quality_mode=self.quality_mode_combo.currentText(),
            file_format=self.format_combo.currentText(),
            output_dir=self.output_input.text().strip(),
            ffmpeg_path=self.ffmpeg_input.text().strip(),
            subtitle_mode=self.subtitle_mode_combo.currentText(),
            subtitle_langs=self.subtitle_lang_input.text().strip(),
            audio_bitrate=self.audio_bitrate.value(),
            cookies_browser=self.cookies_combo.currentText(),
            cookies_file=self.cookies_file_input.text().strip(),
            download_thumbnail=self.thumbnail_checkbox.isChecked(),
            embed_metadata=self.embed_metadata_checkbox.isChecked(),
            speed_limit_mbps=self.speed_limit.value(),
            fragment_concurrency=self.fragment_concurrency.value(),
            filename_template=self.filename_template_combo.currentText(),
            auto_container=self.auto_container_checkbox.isChecked(),
            codec_preference=self.codec_combo.currentText(),
            audio_preference=self.audio_pref_combo.currentText(),
            sort_media_folders=self.sort_media_checkbox.isChecked(),
            platform_sort_folders=self.platform_sort_checkbox.isChecked(),
            subtitle_optional=self.subtitle_optional_checkbox.isChecked(),
            debug_mode=self.debug_checkbox.isChecked(),
        )
        self.thread.progress.connect(self.progress_bar.setValue)
        self.thread.row_update.connect(self.update_queue_row)
        self.thread.format_update.connect(self.update_queue_format)
        self.thread.speed_update.connect(self.update_queue_speed)
        self.thread.file_ready.connect(self.update_queue_file)
        self.thread.live_status.connect(self.status_label.setText)
        self.thread.item_notification.connect(self.show_notification)
        self.thread.log.connect(self.log)
        self.thread.done.connect(self.download_finished)
        self.thread.start()

    def metadata_finished(self, success, message):
        self.set_checking_state(False)
        self.log(message)
        if success:
            estimated = sum(int(item.get("estimated_size_bytes") or 0) for item in self.queue_items)
            if estimated > 10 * 1024 ** 3:
                self.log("Very large file detected. Make sure you have at least 2x free disk space.")
            elif estimated > 5 * 1024 ** 3:
                self.log("Large file detected. Download and merge may take longer.")
        if success and self.auto_start_after_check:
            self.auto_start_after_check = False
            self.start_download_thread()
        else:
            self.auto_start_after_check = False

    def set_testing_state(self, is_testing):
        self.test_link_btn.setEnabled(not is_testing)
        self.check_btn.setEnabled(not is_testing)
        self.download_btn.setEnabled(not is_testing)
        self.channel_fetch_btn.setEnabled(not is_testing)
        self.clear_queue_btn.setEnabled(not is_testing)
        self.status_label.setText("Testing" if is_testing else "Ready")
        self.update_header_status("Testing..." if is_testing else "Ready", "busy" if is_testing else "ready")

    def set_checking_state(self, is_checking):
        self.test_link_btn.setEnabled(not is_checking)
        self.check_btn.setEnabled(not is_checking)
        self.download_btn.setEnabled(not is_checking)
        self.channel_fetch_btn.setEnabled(not is_checking)
        self.clear_queue_btn.setEnabled(not is_checking)
        self.status_label.setText("Checking" if is_checking else "Ready")
        self.update_header_status("Checking..." if is_checking else "Ready", "busy" if is_checking else "ready")

    def set_running_state(self, is_running):
        self.test_link_btn.setEnabled(not is_running)
        self.check_btn.setEnabled(not is_running)
        self.download_btn.setEnabled(not is_running)
        self.channel_fetch_btn.setEnabled(not is_running)
        self.retry_failed_btn.setEnabled(not is_running)
        self.clear_completed_btn.setEnabled(not is_running)
        self.clear_queue_btn.setEnabled(not is_running)
        self.open_selected_btn.setEnabled(not is_running)
        self.save_queue_btn.setEnabled(not is_running)
        self.load_queue_btn.setEnabled(not is_running)
        self.update_ytdlp_btn.setEnabled(not is_running)
        self.cancel_btn.setEnabled(is_running)
        self.browse_btn.setEnabled(not is_running)
        self.output_open_folder_btn.setEnabled(not is_running)
        self.sort_media_checkbox.setEnabled(not is_running)
        self.platform_sort_checkbox.setEnabled(not is_running)
        self.ffmpeg_browse_btn.setEnabled(not is_running)
        self.ffmpeg_detect_btn.setEnabled(not is_running)
        self.format_combo.setEnabled(not is_running)
        if hasattr(self, "media_type_combo"):
            self.media_type_combo.setEnabled(not is_running)
        current_format = self.format_combo.currentText()
        is_audio = current_format in AUDIO_FORMATS
        is_image = current_format in IMAGE_FORMATS
        is_video = current_format in VIDEO_FORMATS
        self.quality_combo.setEnabled(not is_running and is_video)
        self.quality_mode_combo.setEnabled(not is_running and is_video)
        self.audio_bitrate.setEnabled(not is_running and is_audio)
        self.playlist_checkbox.setEnabled(not is_running)
        self.subtitle_mode_combo.setEnabled(not is_running)
        self.subtitle_lang_input.setEnabled(not is_running)
        self.cookies_combo.setEnabled(not is_running)
        self.cookies_file_input.setEnabled(not is_running)
        self.cookies_file_btn.setEnabled(not is_running)
        self.thumbnail_checkbox.setEnabled(not is_running and not is_image)
        self.embed_metadata_checkbox.setEnabled(not is_running and not is_image)
        self.speed_limit.setEnabled(not is_running)
        self.fragment_concurrency.setEnabled(not is_running)
        self.filename_template_combo.setEnabled(not is_running)
        self.debug_checkbox.setEnabled(not is_running)
        self.playlist_start.setEnabled(not is_running)
        self.playlist_end.setEnabled(not is_running)
        self.check_mode_combo.setEnabled(not is_running)
        self.audio_pref_combo.setEnabled(not is_running and is_audio)
        self.codec_combo.setEnabled(not is_running and is_video)
        self.subtitle_optional_checkbox.setEnabled(not is_running)
        self.auto_container_checkbox.setEnabled(not is_running and is_video)
        self.status_label.setText("Running" if is_running else "Ready")
        self.update_header_status("Downloading..." if is_running else "Ready", "busy" if is_running else "ready")

    def cancel_download(self):
        if self.thread and self.thread.isRunning():
            if any(
                item.get("status") in {"Merging", "Post-processing", "Moving final file"}
                for item in self.queue_items
            ):
                result = QMessageBox.question(
                    self,
                    "Cancel during merge",
                    "Cancel during merge may leave temporary files. Continue?",
                )
                if result != QMessageBox.Yes:
                    return
            self.log("Membatalkan download...")
            self.status_label.setText("Membatalkan download...")
            self.cancel_btn.setEnabled(False)
            self.thread.request_cancel()

    def update_queue_row(self, row, status, percent):
        status_item = self.queue_table.item(row, 4)
        progress_item = self.queue_table.item(row, 5)
        if 0 <= row < len(self.queue_items):
            self.queue_items[row]["status"] = status
            self.queue_items[row]["progress"] = percent
        if status_item:
            status_item.setText(status)
            self._apply_status_item_style(status_item, status)
        if progress_item:
            progress_item.setText(f"{percent}%")
        if status in {"Merging", "Post-processing", "Moving final file"}:
            self.progress_bar.setRange(0, 0)
        elif self.progress_bar.minimum() == 0 and self.progress_bar.maximum() == 0:
            self.progress_bar.setRange(0, 100)

    def update_queue_speed(self, row, speed, eta):
        if 0 <= row < len(self.queue_items):
            self.queue_items[row]["speed"] = speed
            self.queue_items[row]["eta"] = eta
        speed_item = self.queue_table.item(row, 6)
        eta_item = self.queue_table.item(row, 7)
        if speed_item:
            speed_item.setText(speed)
        if eta_item:
            eta_item.setText(eta)

    def update_queue_format(self, row, details):
        if 0 <= row < len(self.queue_items):
            self.queue_items[row]["actual_format"] = details
        format_item = self.queue_table.item(row, 2)
        if format_item:
            format_item.setText(details)
        if 0 <= row < len(self.queue_items):
            self.update_target_info(self.queue_items[row])

    def update_queue_file(self, row, path):
        if 0 <= row < len(self.queue_items):
            self.queue_items[row]["output_path"] = path
        file_item = self.queue_table.item(row, 8)
        if file_item:
            file_item.setText(path)

    def selected_row(self):
        rows = self.queue_table.selectionModel().selectedRows()
        if not rows:
            return -1
        return rows[0].row()

    def open_selected_file(self):
        row = self.selected_row()
        if row < 0 or row >= len(self.queue_items):
            self.log("Pilih item queue dulu.")
            return

        path = self.queue_items[row].get("output_path")
        if not path or not os.path.exists(path):
            self.log("File output belum tersedia untuk item ini.")
            return

        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def open_selected_folder(self):
        row = self.selected_row()
        if row < 0 or row >= len(self.queue_items):
            self.open_output_folder()
            return
        path = self.queue_items[row].get("output_path")
        folder = os.path.dirname(path) if path else self.output_input.text().strip()
        if not folder:
            self.log("Folder output belum tersedia.")
            return
        os.makedirs(folder, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def open_path_or_folder(self, path):
        if path and os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            return
        folder = os.path.dirname(path) if path else self.output_input.text().strip()
        if folder:
            os.makedirs(folder, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def copy_text(self, text, label):
        QApplication.clipboard().setText(text or "")
        self.log(f"{label} dicopy.")

    def remove_selected_queue_item(self):
        row = self.selected_row()
        if row < 0 or row >= len(self.queue_items):
            return
        del self.queue_items[row]
        self.prepare_queue_table(self.queue_items)

    def show_queue_context_menu(self, position):
        row = self.queue_table.rowAt(position.y())
        if row < 0 or row >= len(self.queue_items):
            return
        self.queue_table.selectRow(row)
        item = self.queue_items[row]
        output_path = item.get("output_path")
        has_file = bool(output_path and os.path.exists(output_path))

        menu = QMenu(self)
        open_file = menu.addAction("Open File")
        open_file.setEnabled(has_file)
        open_folder = menu.addAction("Open Folder")
        copy_output = menu.addAction("Copy Output Path")
        copy_output.setEnabled(bool(output_path))
        copy_url = menu.addAction("Copy URL")
        retry = menu.addAction("Retry")
        retry.setEnabled(item.get("status") in {"Failed", "Canceled", "Interrupted"})
        remove = menu.addAction("Remove from Queue")
        clear_completed = menu.addAction("Clear Completed")

        action = menu.exec(self.queue_table.viewport().mapToGlobal(position))
        if action == open_file:
            self.open_selected_file()
        elif action == open_folder:
            self.open_selected_folder()
        elif action == copy_output:
            self.copy_text(output_path, "Output path")
        elif action == copy_url:
            self.copy_text(item.get("url"), "URL")
        elif action == retry:
            item["status"] = "Queued"
            item["progress"] = 0
            self.prepare_queue_table([item])
            self.start_download_thread()
        elif action == remove:
            self.remove_selected_queue_item()
        elif action == clear_completed:
            self.clear_completed()

    def retry_failed(self):
        failed_items = [
            item
            for item in self.queue_items
            if item.get("status") in {"Failed", "Canceled", "Interrupted"}
        ]
        if not failed_items:
            self.log("Tidak ada item Failed/Canceled untuk retry.")
            return
        for item in failed_items:
            item["status"] = "Queued"
            item["progress"] = 0
        self.prepare_queue_table(failed_items)
        self.start_download_thread()

    def clear_completed(self):
        remaining = [
            item
            for item in self.queue_items
            if item.get("status") != "Done"
        ]
        removed = len(self.queue_items) - len(remaining)
        self.prepare_queue_table(remaining)
        self.log(f"Clear completed: {removed} item dibersihkan.")

    def clear_queue(self):
        if self.thread and self.thread.isRunning() or self.active_download_status_present():
            self.log("Queue tidak bisa dibersihkan saat download/merge berjalan.")
            return
        removed = len(self.queue_items)
        self.prepare_queue_table([])
        self.progress_bar.setValue(0)
        self.status_label.setText("Ready")
        self.log(f"Clear queue: {removed} item dibersihkan.")

    def save_state(self):
        self.write_json_file(APP_STATE_FILE, {"app_version": APP_VERSION, "queue": self.queue_items})

    def save_queue(self):
        if not self.queue_items:
            self.log("Queue kosong.")
            return
        self.write_json_file(APP_STATE_FILE, {"app_version": APP_VERSION, "queue": self.queue_items})
        self.log(f"Queue disimpan: {APP_STATE_FILE}")

    def load_queue(self):
        data = self.read_json_file(APP_STATE_FILE, default={})
        items = data.get("queue") or []
        if not items:
            self.log("Tidak ada queue tersimpan.")
            return
        self.prepare_queue_table(items)
        self.log(f"Queue diload: {len(items)} item.")

    def write_json_file(self, path, data):
        with open(path, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)

    def read_json_file(self, path, default=None):
        try:
            with open(path, "r", encoding="utf-8") as file:
                return json.load(file)
        except (OSError, json.JSONDecodeError):
            return default

    def recover_previous_state(self):
        data = self.read_json_file(APP_STATE_FILE, default={}) or {}
        items = data.get("queue") or []
        if not items:
            return
        changed = False
        for item in items:
            if item.get("status") in RECOVERABLE_STATUSES:
                item["status"] = "Interrupted"
                changed = True
        self.prepare_queue_table(items)
        if changed:
            self.log("Recovered previous queue. Running items were marked as Interrupted.")
            self.write_json_file(APP_STATE_FILE, {"app_version": APP_VERSION, "queue": self.queue_items})

    def append_history(self):
        try:
            with open(HISTORY_FILE, "a", encoding="utf-8") as file:
                for item in self.queue_items:
                    if item.get("status") in DONE_STATUSES | {"Failed", "Canceled"}:
                        file.write(json.dumps({
                            "time": datetime.now().isoformat(timespec="seconds"),
                            "downloaded_at": datetime.now().isoformat(timespec="seconds"),
                            "title": item.get("title"),
                            "url": item.get("url"),
                            "platform": item.get("platform", "Other"),
                            "video_id": item.get("video_id") or item.get("key"),
                            "file": item.get("output_path"),
                            "output_path": item.get("output_path"),
                            "filesize": item.get("size"),
                            "quality": self.quality_combo.currentText(),
                            "format": self.format_combo.currentText(),
                            "type": detect_media_type(self.format_combo.currentText(), os.path.splitext(item.get("output_path") or "")[1]),
                            "status": item.get("status"),
                        }, ensure_ascii=False) + "\n")
        except OSError as e:
            self.log(f"Gagal tulis history: {e}")

    def update_ytdlp(self):
        if getattr(sys, "frozen", False):
            self.log(
                "Update yt-dlp dari exe belum bisa langsung. Jalankan dari source lalu rebuild exe, "
                "atau rebuild aplikasi setelah update package Python."
            )
            return

        if self.update_thread and self.update_thread.isRunning():
            self.log("Update yt-dlp sedang berjalan...")
            return

        self.update_ytdlp_btn.setEnabled(False)
        self.update_ytdlp_btn.setText("Updating yt-dlp...")
        self.status_label.setText("Updating yt-dlp...")
        self.update_header_status("Updating yt-dlp...", "warning")
        self.log("Menjalankan update yt-dlp di background...")

        self.update_thread = UpdateYtDlpThread(os.path.dirname(os.path.abspath(__file__)))
        self.update_thread.log.connect(self.log)
        self.update_thread.finished_update.connect(self.on_update_ytdlp_finished)
        self.update_thread.start()

    def on_update_ytdlp_finished(self, success, message):
        self.update_ytdlp_btn.setEnabled(True)
        self.update_ytdlp_btn.setText("Update yt-dlp")
        self.log(message)
        self.refresh_ffmpeg_status()
        self.update_thread = None

    def load_history_items(self):
        items = []
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as file:
                lines = file.readlines()
        except OSError:
            return items
        for line in lines:
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return items

    def refresh_history(self):
        if not hasattr(self, "history_table"):
            return
        query = self.history_search_input.text().strip().lower()
        selected_filter = self.history_filter_combo.currentText()
        items = self.load_history_items()[-500:]
        filtered = []
        for item in reversed(items):
            status = item.get("status", "Done")
            platform = item.get("platform") or "Other"
            item_type = item.get("type") or detect_media_type(
                item.get("format"),
                os.path.splitext(item.get("output_path") or item.get("file") or "")[1],
            )
            if selected_filter == "Done" and status not in DONE_STATUSES:
                continue
            if selected_filter not in {"All", "Done", status, item_type, platform}:
                continue
            text = " ".join(str(item.get(key, "")) for key in ("title", "url", "file", "output_path", "format", "platform")).lower()
            if query and query not in text:
                continue
            filtered.append(item)

        self.history_table.setRowCount(len(filtered))
        for row, item in enumerate(filtered):
            values = [
                item.get("downloaded_at") or item.get("time", "-"),
                item.get("title", "-"),
                item.get("platform", "Other"),
                item.get("status", "Done"),
                item.get("format", "-"),
                item.get("url", "-"),
                item.get("output_path") or item.get("file", "-"),
            ]
            for col, value in enumerate(values):
                table_item = QTableWidgetItem(str(value))
                table_item.setData(Qt.UserRole, item)
                self.history_table.setItem(row, col, table_item)

    def selected_history_item(self):
        rows = self.history_table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.history_table.item(rows[0].row(), 0)
        return item.data(Qt.UserRole) if item else None

    def open_selected_history_file(self):
        item = self.selected_history_item()
        if not item:
            self.log("Pilih item history dulu.")
            return
        path = item.get("output_path") or item.get("file")
        if path and os.path.exists(path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        else:
            self.log("File history tidak ditemukan.")

    def open_selected_history_folder(self):
        item = self.selected_history_item()
        if not item:
            self.log("Pilih item history dulu.")
            return
        self.open_path_or_folder(item.get("output_path") or item.get("file"))

    def copy_selected_history_url(self):
        item = self.selected_history_item()
        if item:
            self.copy_text(item.get("url"), "URL history")

    def redownload_selected_history(self):
        item = self.selected_history_item()
        if not item:
            self.log("Pilih item history dulu.")
            return
        self.urls_input.setPlainText(item.get("url") or "")
        self.queue_items = []
        self.tabs.setCurrentIndex(0)

    def clear_history(self):
        if not os.path.exists(HISTORY_FILE):
            return
        result = QMessageBox.question(self, "Clear History", "Hapus seluruh history v2?")
        if result != QMessageBox.Yes:
            return
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8"):
                pass
            self.refresh_history()
            self.log("History v2 dibersihkan.")
        except OSError as e:
            self.log(f"Gagal clear history: {e}")

    def open_history_file(self):
        if not os.path.exists(HISTORY_FILE):
            self.log("File history belum ada.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(HISTORY_FILE))

    def ask_history_duplicate(self, history_item, platform="Other"):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Duplicate History")
        dialog.setText(f"Video {platform} ini sudah pernah didownload.")
        open_btn = dialog.addButton("Open File", QMessageBox.AcceptRole)
        download_btn = dialog.addButton("Download Lagi", QMessageBox.DestructiveRole)
        cancel_btn = dialog.addButton("Cancel", QMessageBox.RejectRole)
        history_path = history_item.get("output_path") or history_item.get("file")
        if not (history_path and os.path.exists(history_path)):
            open_btn.setEnabled(False)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked == open_btn:
            return "open"
        if clicked == download_btn:
            return "download"
        if clicked == cancel_btn:
            return "cancel"
        return "cancel"

    def ask_queue_duplicate(self, row, platform="Other"):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Duplicate Queue")
        dialog.setText(f"Video {platform} ini sudah ada di queue.")
        add_btn = dialog.addButton("Tetap Tambahkan", QMessageBox.AcceptRole)
        focus_btn = dialog.addButton("Fokus ke Item Lama", QMessageBox.ActionRole)
        cancel_btn = dialog.addButton("Cancel", QMessageBox.RejectRole)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked == add_btn:
            return "add"
        if clicked == focus_btn:
            return "focus"
        if clicked == cancel_btn:
            return "cancel"
        return "cancel"

    def effective_output_folder(self):
        output_dir = self.output_input.text().strip()
        folder = output_dir
        first_item = self.queue_items[0] if self.queue_items else {}
        if self.platform_sort_checkbox.isChecked():
            folder = os.path.join(folder, safe_platform_folder(first_item.get("platform", "Other")))
        if self.sort_media_checkbox.isChecked():
            folder = os.path.join(folder, detect_media_type(self.format_combo.currentText()))
        return folder

    def confirm_disk_space_for_large_files(self):
        estimated = sum(int(item.get("estimated_size_bytes") or 0) for item in self.queue_items)
        if not estimated:
            return True
        if estimated > 5 * 1024 ** 3:
            self.log("Large file detected. Download and merge may take longer.")
        if estimated <= 10 * 1024 ** 3:
            return True
        folder = self.effective_output_folder()
        try:
            os.makedirs(folder, exist_ok=True)
            free = shutil.disk_usage(folder).free
        except OSError as e:
            self.log(f"Gagal cek free space: {e}")
            return True
        recommended = int(estimated * 2.5)
        self.log("Very large file detected. Make sure you have at least 2x free disk space.")
        if free >= recommended:
            return True
        message = (
            "Storage may be insufficient. "
            f"Estimated size: {human_size(estimated)}, "
            f"recommended free space: {human_size(recommended)}, "
            f"available: {human_size(free)}. Continue?"
        )
        result = QMessageBox.question(self, "Storage Check", message)
        return result == QMessageBox.Yes

    def active_download_status_present(self):
        return any(item.get("status") in ACTIVE_STATUSES for item in self.queue_items)

    def clean_temp_files(self):
        if self.thread and self.thread.isRunning() or self.active_download_status_present():
            QMessageBox.warning(self, "Clean Temp Files", "Cannot clean temp files while download or merge is running.")
            return
        folder = self.output_input.text().strip()
        if not folder or not os.path.isdir(folder):
            self.log("Folder output belum ada.")
            return
        temp_files = []
        for root, _, files in os.walk(folder):
            for name in files:
                if name.lower().endswith((".part", ".ytdl", ".temp", ".tmp")):
                    temp_files.append(os.path.join(root, name))
        if not temp_files:
            self.log("Tidak ada temp file di output v2.")
            return
        result = QMessageBox.question(
            self,
            "Clean Temp Files",
            f"Hapus {len(temp_files)} temp file dari folder output v2?",
        )
        if result != QMessageBox.Yes:
            return
        deleted = 0
        for path in temp_files:
            try:
                os.remove(path)
                deleted += 1
            except OSError as e:
                self.log(f"Gagal hapus {path}: {e}")
        self.log(f"Clean Temp Files: {deleted} file dihapus.")

    def show_notification(self, title, message):
        try:
            if self.tray_icon:
                if not self.tray_icon.isVisible():
                    self.tray_icon.setIcon(self.windowIcon())
                    self.tray_icon.show()
                self.tray_icon.showMessage(title, message, QSystemTrayIcon.Information, 5000)
            else:
                self.log(f"{title}: {message}")
        except Exception:
            self.log(f"{title}: {message}")

    def show_about(self):
        ffmpeg = resolve_ffmpeg(self.ffmpeg_input.text().strip()) or "Not found"
        details = (
            f"{APP_NAME}\n"
            f"Version: {APP_VERSION}\n"
            f"yt-dlp version: {getattr(getattr(yt_dlp, 'version', None), '__version__', 'unknown')}\n"
            f"FFmpeg: {ffmpeg}\n"
            f"Output folder: {self.output_input.text().strip() or self.default_output}\n"
            f"Python: {sys.version.split()[0]}\n"
            f"PySide6: {PYSIDE_VERSION}\n\n"
            "For personal use."
        )
        QMessageBox.about(self, "About", details)

    def log(self, text):
        self.log_box.append(text)
        hint = classify_download_error_hint(text)
        if hint:
            self.log_box.append(f"💡 {hint}")

    def clear_log(self):
        self.log_box.clear()

    def export_log(self):
        path, _ = QFileDialog.getSaveFileName(self, "Simpan Log", "yt-downloader-log.txt", "Text (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as file:
                file.write(self.log_box.toPlainText())
            self.log(f"Log disimpan: {path}")
        except OSError as e:
            self.log(f"Gagal simpan log: {e}")

    def download_finished(self, success_count, failed_count, canceled):
        self.set_running_state(False)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.setRange(0, 100)
        self.refresh_ffmpeg_status()

        if canceled:
            self.progress_bar.setValue(0)
            self.status_label.setText("Canceled")
            self.update_header_status("Canceled", "warning")
            self.log(f"Dibatalkan. Berhasil: {success_count}, gagal: {failed_count}.")
        elif failed_count and success_count:
            self.status_label.setText("Done with errors")
            self.update_header_status("Done with warnings", "warning")
            self.log(f"Selesai dengan error. Berhasil: {success_count}, gagal: {failed_count}.")
        elif failed_count:
            self.status_label.setText("Failed")
            self.update_header_status("Failed", "error")
            self.log(f"Gagal. Berhasil: {success_count}, gagal: {failed_count}.")
        else:
            self.progress_bar.setValue(100)
            self.status_label.setText("Done")
            self.update_header_status("Done", "ready")
            self.log(f"Selesai. Berhasil: {success_count}, gagal: {failed_count}.")

        self.show_notification("Queue complete", f"Berhasil: {success_count}, gagal: {failed_count}.")
        self.append_history()
        self.refresh_history()
        if self.queue_items:
            self.write_json_file(APP_STATE_FILE, {"app_version": APP_VERSION, "queue": self.queue_items})

    def closeEvent(self, event):
        self.save_settings()
        if self.thread and self.thread.isRunning():
            result = QMessageBox.question(
                self,
                "Download masih berjalan",
                "Download masih berjalan. Batalkan dan tutup aplikasi?",
            )
            if result != QMessageBox.Yes:
                event.ignore()
                return
            for item in self.queue_items:
                if item.get("status") in ACTIVE_STATUSES:
                    item["status"] = "Interrupted"
            self.write_json_file(APP_STATE_FILE, {"app_version": APP_VERSION, "queue": self.queue_items})
            self.thread.request_cancel()
            self.thread.wait(1500)

        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = App()
    window.show()
    sys.exit(app.exec())
