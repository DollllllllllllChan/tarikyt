import os
import re
import threading
import time
import urllib.request
from collections import OrderedDict
from datetime import datetime

import yt_dlp
from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QRegularExpression,
    QRunnable,
    QSize,
    QSortFilterProxyModel,
    Qt,
    QThread,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStyle,
    QTableView,
    QVBoxLayout,
    QWidget,
)


def format_duration(seconds):
    if seconds is None:
        return "-"
    try:
        sec = int(round(float(seconds)))
        if sec < 0:
            return "-"
        if sec < 3600:
            return f"{sec // 60:02d}:{sec % 60:02d}"
        hours = sec // 3600
        rem = sec % 3600
        return f"{hours:02d}:{rem // 60:02d}:{rem % 60:02d}"
    except (TypeError, ValueError):
        return "-"


def format_upload_date(date_val):
    if not date_val:
        return "-"
    if isinstance(date_val, (int, float)):
        try:
            return datetime.fromtimestamp(float(date_val)).strftime("%Y-%m-%d")
        except (TypeError, ValueError, OSError):
            return "-"
    s = str(date_val).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    if s.isdigit() and len(s) >= 9:
        try:
            return datetime.fromtimestamp(float(s)).strftime("%Y-%m-%d")
        except (TypeError, ValueError, OSError):
            pass
    return s if s else "-"


def select_best_preview_thumbnail(thumbnails, max_width=480):
    if not thumbnails:
        return None
    if isinstance(thumbnails, str):
        return thumbnails

    valid = []
    for item in thumbnails:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not url or not url.startswith("http"):
            continue
        w = item.get("width") or 0
        h = item.get("height") or 0
        valid.append((w, h, url))

    if not valid:
        return None

    # Filter out maxres if smaller reasonable sizes exist
    moderate = [item for item in valid if item[0] <= max_width and item[0] > 0]
    if moderate:
        # pick highest resolution within moderate limit
        moderate.sort(key=lambda x: (x[0] * x[1], x[0]), reverse=True)
        return moderate[0][2]

    # Otherwise pick lowest positive resolution available or first
    valid.sort(key=lambda x: (x[0] * x[1] if x[0] > 0 else 999999))
    return valid[0][2]


class ThumbnailCache:
    def __init__(self, max_size=1000):
        self.max_size = max_size
        self._cache = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            return None

    def put(self, key, pixmap):
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = pixmap
            else:
                if len(self._cache) >= self.max_size:
                    self._cache.popitem(last=False)
                self._cache[key] = pixmap

    def clear(self):
        with self._lock:
            self._cache.clear()


class ThumbnailWorkerSignals(QObject):
    loaded = Signal(str, QImage)
    failed = Signal(str)


class ThumbnailWorker(QRunnable):
    def __init__(self, video_id, url, target_size=(120, 68)):
        super().__init__()
        self.video_id = video_id
        self.url = url
        self.target_size = target_size
        self.signals = ThumbnailWorkerSignals()
        self.setAutoDelete(True)

    def run(self):
        if not self.url:
            self.signals.failed.emit(self.video_id)
            return

        try:
            req = urllib.request.Request(
                self.url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = resp.read()

            image = QImage.fromData(data)
            if image.isNull():
                try:
                    self.signals.failed.emit(self.video_id)
                except (RuntimeError, AttributeError):
                    pass
                return

            scaled = image.scaled(
                self.target_size[0],
                self.target_size[1],
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            # Crop to exact target size from center if needed
            if scaled.width() > self.target_size[0] or scaled.height() > self.target_size[1]:
                x = max(0, (scaled.width() - self.target_size[0]) // 2)
                y = max(0, (scaled.height() - self.target_size[1]) // 2)
                scaled = scaled.copy(x, y, self.target_size[0], self.target_size[1])

            try:
                self.signals.loaded.emit(self.video_id, scaled)
            except (RuntimeError, AttributeError):
                pass
        except Exception:
            try:
                self.signals.failed.emit(self.video_id)
            except (RuntimeError, AttributeError):
                pass


class ChannelPreviewThread(QThread):
    scan_started = Signal(str)
    scan_finished = Signal(list, dict)
    scan_error = Signal(str)
    log = Signal(str)
    done = Signal()

    def __init__(self, target_url, cookies_browser=None, cookies_file=None):
        super().__init__()
        self.target_url = target_url
        self.cookies_browser = cookies_browser
        self.cookies_file = cookies_file
        self._is_cancelled = False

    def request_cancel(self):
        self._is_cancelled = True
        self.requestInterruption()

    def build_opts(self):
        opts = {
            "extract_flat": "in_playlist",
            "quiet": True,
            "no_warnings": True,
            "ignoreerrors": True,
            "skip_download": True,
            "extractor_args": {
                "youtubetab": {"approximate_date": [""]},
            },
        }
        if self.cookies_file and os.path.isfile(self.cookies_file):
            opts["cookiefile"] = self.cookies_file
        elif self.cookies_browser and self.cookies_browser.lower() not in {"none", ""}:
            opts["cookiesfrombrowser"] = (self.cookies_browser.lower(),)
        return opts

    def run(self):
        try:
            raw_url = (self.target_url or "").strip()
            if not raw_url:
                self.scan_error.emit("URL channel atau playlist masih kosong.")
                return

            # Basic normalization for YouTube channel URLs
            if "youtube.com" in raw_url or "youtu.be" in raw_url:
                if "/@" in raw_url and not any(raw_url.endswith(x) for x in ["/videos", "/shorts", "/streams", "/playlists"]):
                    raw_url = raw_url.rstrip("/") + "/videos"

            self.scan_started.emit(raw_url)
            self.log.emit(f"Scanning daftar video: {raw_url}")

            with yt_dlp.YoutubeDL(self.build_opts()) as ydl:
                info = ydl.extract_info(raw_url, download=False)

            if not info:
                self.scan_error.emit("Gagal: yt-dlp tidak mengembalikan metadata untuk URL ini.")
                return

            channel_title = info.get("title") or raw_url
            entries = [e for e in info.get("entries") or [] if e is not None]

            # If not a playlist/channel container but a single video
            if not entries and info.get("_type") != "playlist" and info.get("id"):
                entries = [info]

            items = []
            seen_ids = set()

            for index, entry in enumerate(entries, start=1):
                if self._is_cancelled or self.isInterruptionRequested():
                    self.log.emit("Scan dibatalkan oleh pengguna.")
                    return

                vid_id = entry.get("id")
                if not vid_id:
                    continue

                if vid_id in seen_ids:
                    continue
                seen_ids.add(vid_id)

                title = entry.get("title") or entry.get("url") or f"Video {vid_id}"
                web_url = entry.get("webpage_url") or entry.get("url")
                if not web_url or not str(web_url).startswith("http"):
                    web_url = f"https://www.youtube.com/watch?v={vid_id}"

                thumb = select_best_preview_thumbnail(entry.get("thumbnails") or entry.get("thumbnail"))

                raw_date = entry.get("upload_date")
                if not raw_date:
                    ts = entry.get("timestamp") or entry.get("release_timestamp")
                    if ts:
                        try:
                            raw_date = datetime.fromtimestamp(float(ts)).strftime("%Y%m%d")
                        except (TypeError, ValueError, OSError):
                            raw_date = None

                items.append({
                    "url": web_url,
                    "title": title,
                    "video_id": vid_id,
                    "key": vid_id,
                    "playlist_index": index,
                    "source": channel_title,
                    "platform": "YouTube",
                    "thumbnail_url": thumb,
                    "duration": entry.get("duration"),
                    "upload_date": raw_date,
                })

            if not items:
                self.scan_error.emit("Gagal: Tidak ada video yang ditemukan pada URL ini.")
                return

            stats = {
                "source": channel_title,
                "total": len(items),
            }

            self.log.emit(f"Scan selesai: {len(items)} video ditemukan pada '{channel_title}'.")
            self.scan_finished.emit(items, stats)
        except Exception as e:
            self.scan_error.emit(f"Gagal scan channel/playlist: {e}")
        finally:
            self.done.emit()


class VideoPreviewTableModel(QAbstractTableModel):
    selection_changed = Signal()

    COL_CHECK = 0
    COL_THUMB = 1
    COL_TITLE = 2
    COL_DURATION = 3
    COL_DATE = 4
    COL_ID = 5
    COLUMN_COUNT = 6

    COL_HEADERS = ["", "Thumbnail", "Judul Video", "Durasi", "Tgl Upload", "Video ID"]

    def __init__(self, thumbnail_cache=None, parent=None):
        super().__init__(parent)
        self._items = []
        self._row_by_id = {}
        self.selected_ids = set()
        self.thumbnail_cache = thumbnail_cache or ThumbnailCache()
        self._placeholder_pixmap = self._create_placeholder_pixmap()

    def _create_placeholder_pixmap(self):
        pix = QPixmap(120, 68)
        pix.fill(QColor("#1e222d"))
        painter = QPainter(pix)
        painter.setPen(QColor("#64748b"))
        font = QFont("Segoe UI", 8)
        painter.setFont(font)
        painter.drawText(pix.rect(), Qt.AlignCenter, "No Preview")
        painter.end()
        return pix

    def rowCount(self, parent=QModelIndex()):
        return len(self._items) if not parent.isValid() else 0

    def columnCount(self, parent=QModelIndex()):
        return self.COLUMN_COUNT

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        if index.column() == self.COL_CHECK:
            return Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._items):
            return None

        row = index.row()
        col = index.column()
        item = self._items[row]
        vid_id = item.get("video_id") or ""

        if role == Qt.CheckStateRole and col == self.COL_CHECK:
            return Qt.Checked if vid_id in self.selected_ids else Qt.Unchecked

        if role == Qt.TextAlignmentRole:
            if col in (self.COL_CHECK, self.COL_THUMB, self.COL_DURATION, self.COL_DATE, self.COL_ID):
                return Qt.AlignCenter
            return Qt.AlignLeft | Qt.AlignVCenter

        if role == Qt.DisplayRole:
            if col == self.COL_CHECK or col == self.COL_THUMB:
                return ""
            if col == self.COL_TITLE:
                return item.get("title", "")
            if col == self.COL_DURATION:
                return format_duration(item.get("duration"))
            if col == self.COL_DATE:
                return format_upload_date(item.get("upload_date"))
            if col == self.COL_ID:
                return vid_id

        if role == Qt.DecorationRole and col == self.COL_THUMB:
            cached = self.thumbnail_cache.get(vid_id)
            return cached if cached else self._placeholder_pixmap

        if role == Qt.ToolTipRole:
            title = item.get("title", "")
            dur = format_duration(item.get("duration"))
            date = format_upload_date(item.get("upload_date"))
            return f"Judul: {title}\nID: {vid_id}\nDurasi: {dur}\nUpload: {date}"

        return None

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid():
            return False

        if index.column() == self.COL_CHECK and role == Qt.CheckStateRole:
            row = index.row()
            if row < len(self._items):
                vid_id = self._items[row].get("video_id")
                if vid_id:
                    if value == Qt.Checked or value == 2:
                        self.selected_ids.add(vid_id)
                    else:
                        self.selected_ids.discard(vid_id)
                    self.dataChanged.emit(index, index, [Qt.CheckStateRole])
                    self.selection_changed.emit()
                    return True
        return False

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal:
            if role == Qt.DisplayRole:
                if 0 <= section < len(self.COL_HEADERS):
                    return self.COL_HEADERS[section]
            if role == Qt.TextAlignmentRole:
                if section in (self.COL_CHECK, self.COL_THUMB, self.COL_DURATION, self.COL_DATE, self.COL_ID):
                    return Qt.AlignCenter
                return Qt.AlignLeft | Qt.AlignVCenter
        return None

    def set_items(self, items):
        self.beginResetModel()
        self._items = list(items or [])
        self._row_by_id = {
            item.get("video_id"): row
            for row, item in enumerate(self._items)
            if item.get("video_id")
        }
        self.selected_ids.clear()
        self.endResetModel()
        self.selection_changed.emit()

    def get_items(self):
        return self._items

    def get_item(self, row):
        if 0 <= row < len(self._items):
            return self._items[row]
        return None

    def select_all(self):
        self.selected_ids = {item.get("video_id") for item in self._items if item.get("video_id")}
        if self._items:
            top_left = self.index(0, self.COL_CHECK)
            bottom_right = self.index(len(self._items) - 1, self.COL_CHECK)
            self.dataChanged.emit(top_left, bottom_right, [Qt.CheckStateRole])
        self.selection_changed.emit()

    def clear_selection(self):
        self.selected_ids.clear()
        if self._items:
            top_left = self.index(0, self.COL_CHECK)
            bottom_right = self.index(len(self._items) - 1, self.COL_CHECK)
            self.dataChanged.emit(top_left, bottom_right, [Qt.CheckStateRole])
        self.selection_changed.emit()

    def select_ids(self, ids_to_select):
        valid = {vid for vid in ids_to_select if vid}
        self.selected_ids.update(valid)
        if self._items:
            top_left = self.index(0, self.COL_CHECK)
            bottom_right = self.index(len(self._items) - 1, self.COL_CHECK)
            self.dataChanged.emit(top_left, bottom_right, [Qt.CheckStateRole])
        self.selection_changed.emit()

    def unselect_ids(self, ids_to_unselect):
        valid = {vid for vid in ids_to_unselect if vid}
        self.selected_ids.difference_update(valid)
        if self._items:
            top_left = self.index(0, self.COL_CHECK)
            bottom_right = self.index(len(self._items) - 1, self.COL_CHECK)
            self.dataChanged.emit(top_left, bottom_right, [Qt.CheckStateRole])
        self.selection_changed.emit()

    def toggle_row(self, row):
        if 0 <= row < len(self._items):
            vid_id = self._items[row].get("video_id")
            if vid_id:
                if vid_id in self.selected_ids:
                    self.selected_ids.remove(vid_id)
                else:
                    self.selected_ids.add(vid_id)
                idx = self.index(row, self.COL_CHECK)
                self.dataChanged.emit(idx, idx, [Qt.CheckStateRole])
                self.selection_changed.emit()

    def get_selected_items(self):
        return [item for item in self._items if item.get("video_id") in self.selected_ids]

    def update_thumbnail(self, video_id, qimage):
        pixmap = QPixmap.fromImage(qimage)
        self.thumbnail_cache.put(video_id, pixmap)
        row = self._row_by_id.get(video_id)
        if row is not None and 0 <= row < len(self._items):
            idx = self.index(row, self.COL_THUMB)
            self.dataChanged.emit(idx, idx, [Qt.DecorationRole])


class VideoPreviewFilterProxyModel(QSortFilterProxyModel):
    MODE_CONTAINS = "Contains"
    MODE_EXACT = "Exact"
    MODE_STARTS_WITH = "Starts With"
    MODE_REGEX = "Regex"
    FILTER_MODES = [MODE_CONTAINS, MODE_EXACT, MODE_STARTS_WITH, MODE_REGEX]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.filter_text = ""
        self.filter_mode = self.MODE_CONTAINS
        self.is_regex_valid = True
        self.regex_error_message = ""
        self._compiled_regex = None
        self.setDynamicSortFilter(True)

    def set_filter_criteria(self, text, mode=MODE_CONTAINS):
        self.filter_text = (text or "").strip()
        self.filter_mode = mode if mode in self.FILTER_MODES else self.MODE_CONTAINS
        self.is_regex_valid = True
        self.regex_error_message = ""
        self._compiled_regex = None

        if self.filter_mode == self.MODE_REGEX and self.filter_text:
            try:
                self._compiled_regex = re.compile(self.filter_text, re.IGNORECASE)
            except re.error as e:
                self.is_regex_valid = False
                self.regex_error_message = str(e)
                self._compiled_regex = None

        if hasattr(self, "invalidate"):
            self.invalidate()
        elif hasattr(self, "invalidateRowsFilter"):
            self.invalidateRowsFilter()
        else:
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row, source_parent):
        if not self.filter_text:
            return True

        source_model = self.sourceModel()
        if not source_model:
            return True

        idx = source_model.index(source_row, VideoPreviewTableModel.COL_TITLE, source_parent)
        title = str(source_model.data(idx, Qt.DisplayRole) or "")

        if self.filter_mode == self.MODE_CONTAINS:
            return self.filter_text.lower() in title.lower()
        if self.filter_mode == self.MODE_EXACT:
            return self.filter_text.lower() == title.lower()
        if self.filter_mode == self.MODE_STARTS_WITH:
            return title.lower().startswith(self.filter_text.lower())
        if self.filter_mode == self.MODE_REGEX:
            if not self.is_regex_valid or not self._compiled_regex:
                return self.filter_text.lower() in title.lower()
            return bool(self._compiled_regex.search(title))

        return True

    def lessThan(self, left, right):
        source_model = self.sourceModel()
        if not source_model:
            return super().lessThan(left, right)

        col = left.column()
        left_item = source_model.get_item(left.row()) or {}
        right_item = source_model.get_item(right.row()) or {}

        if col == VideoPreviewTableModel.COL_DURATION:
            l_dur = left_item.get("duration") or 0
            r_dur = right_item.get("duration") or 0
            return (l_dur if isinstance(l_dur, (int, float)) else 0) < (r_dur if isinstance(r_dur, (int, float)) else 0)

        if col == VideoPreviewTableModel.COL_DATE:
            l_date = str(left_item.get("upload_date") or "")
            r_date = str(right_item.get("upload_date") or "")
            return l_date < r_date

        if col == VideoPreviewTableModel.COL_TITLE:
            l_title = str(left_item.get("title") or "").lower()
            r_title = str(right_item.get("title") or "").lower()
            return l_title < r_title

        if col == VideoPreviewTableModel.COL_CHECK:
            l_sel = left_item.get("video_id") in source_model.selected_ids
            r_sel = right_item.get("video_id") in source_model.selected_ids
            return l_sel < r_sel

        return super().lessThan(left, right)

    def get_filtered_video_ids(self):
        source_model = self.sourceModel()
        if not source_model:
            return []

        ids = []
        for r in range(self.rowCount()):
            src_idx = self.mapToSource(self.index(r, 0))
            item = source_model.get_item(src_idx.row())
            if item and item.get("video_id"):
                ids.append(item["video_id"])
        return ids


class ChannelPreviewDialog(QDialog):
    items_selected = Signal(list)

    def __init__(self, parent=None, initial_url="", cookies_browser=None, cookies_file=None, theme="dark"):
        super().__init__(parent)
        self.setWindowTitle("Channel / Playlist Preview & Selective Download")
        self.resize(1120, 720)
        self.setMinimumSize(880, 520)

        self.cookies_browser = cookies_browser
        self.cookies_file = cookies_file
        self.theme_mode = str(theme or "dark").lower()
        self.selected_items = []

        # Data & Threading
        self.thumbnail_cache = ThumbnailCache(max_size=250)
        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(4)
        self.scan_thread = None
        self._in_flight_thumbnails = set()
        self._failed_thumbnails = set()

        # Models
        self.table_model = VideoPreviewTableModel(thumbnail_cache=self.thumbnail_cache, parent=self)
        self.proxy_model = VideoPreviewFilterProxyModel(parent=self)
        self.proxy_model.setSourceModel(self.table_model)

        # Debounce timer for live search
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(200)
        self.search_timer.timeout.connect(self.apply_search_filter)

        self.create_widgets()
        self.build_layout()
        self.apply_dialog_styles()

        if initial_url:
            self.url_input.setText(initial_url)
            self.url_input.selectAll()
            self.scan_btn.setFocus()

        self.table_model.selection_changed.connect(self.update_counters)
        self.proxy_model.layoutChanged.connect(self.on_filter_or_layout_changed)
        self.proxy_model.modelReset.connect(self.on_filter_or_layout_changed)

    def create_widgets(self):
        # Scan bar
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Paste URL channel atau playlist YouTube (contoh: https://www.youtube.com/@channel/videos)")
        self.url_input.returnPressed.connect(self.start_scan)

        self.scan_btn = QPushButton("Scan Video")
        self.scan_btn.setMinimumWidth(110)
        self.scan_btn.clicked.connect(self.start_scan)

        self.scan_status_label = QLabel("Masukkan URL lalu klik Scan.")
        self.scan_status_label.setStyleSheet("color: #94a3b8;")

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setFixedHeight(5)
        self.progress_bar.setVisible(False)

        # Filter bar
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Cari judul video...")
        self.search_input.textChanged.connect(lambda: self.search_timer.start())

        self.filter_combo = QComboBox()
        self.filter_combo.addItems(VideoPreviewFilterProxyModel.FILTER_MODES)
        self.filter_combo.currentTextChanged.connect(self.apply_search_filter)

        self.filter_status_label = QLabel("")
        self.filter_status_label.setStyleSheet("color: #f87171; font-size: 8.5pt;")

        # Selection actions
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self.table_model.select_all)

        self.clear_all_btn = QPushButton("Clear Selection")
        self.clear_all_btn.clicked.connect(self.table_model.clear_selection)

        self.select_filtered_btn = QPushButton("Select Filtered")
        self.select_filtered_btn.clicked.connect(self.select_filtered_items)

        self.clear_filtered_btn = QPushButton("Clear Filtered")
        self.clear_filtered_btn.clicked.connect(self.clear_filtered_items)

        self.stats_label = QLabel("Total: 0  |  Filtered: 0  |  Selected: 0")
        self.stats_label.setStyleSheet("font-weight: 600; color: #60a5fa; font-size: 10pt;")

        # Table view
        self.table_view = QTableView()
        self.table_view.setModel(self.proxy_model)
        self.table_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table_view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setShowGrid(True)
        self.table_view.setSortingEnabled(True)
        self.table_view.verticalHeader().setDefaultSectionSize(74)
        self.table_view.verticalHeader().setVisible(False)

        header = self.table_view.horizontalHeader()
        header.setSectionResizeMode(VideoPreviewTableModel.COL_CHECK, QHeaderView.Fixed)
        self.table_view.setColumnWidth(VideoPreviewTableModel.COL_CHECK, 36)

        header.setSectionResizeMode(VideoPreviewTableModel.COL_THUMB, QHeaderView.Fixed)
        self.table_view.setColumnWidth(VideoPreviewTableModel.COL_THUMB, 130)

        header.setSectionResizeMode(VideoPreviewTableModel.COL_TITLE, QHeaderView.Stretch)

        header.setSectionResizeMode(VideoPreviewTableModel.COL_DURATION, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(VideoPreviewTableModel.COL_DATE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(VideoPreviewTableModel.COL_ID, QHeaderView.ResizeToContents)

        self.table_view.clicked.connect(self.on_table_clicked)
        self.table_view.doubleClicked.connect(self.on_table_double_clicked)
        self.table_view.verticalScrollBar().valueChanged.connect(lambda: self.schedule_visible_thumbnails())

        # Bottom Bar
        self.cancel_btn = QPushButton("Batal")
        self.cancel_btn.setMinimumHeight(32)
        self.cancel_btn.clicked.connect(self.reject)

        self.add_queue_btn = QPushButton("Tambahkan ke Queue")
        self.add_queue_btn.setEnabled(False)
        self.add_queue_btn.setMinimumHeight(34)
        self.add_queue_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0a84ff, stop:1 #0066d6);
                color: #ffffff;
                font-weight: 700;
                font-size: 10pt;
                border: 1px solid #0a84ff;
                border-radius: 8px;
                padding: 6px 22px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2593ff, stop:1 #0077fa);
                border-color: #2593ff;
            }
            QPushButton:disabled {
                background: #232d3b;
                color: #5a6d82;
                border-color: transparent;
            }
        """)
        self.add_queue_btn.clicked.connect(self.confirm_and_add_to_queue)

    def build_layout(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        # Scan section Frame
        scan_group = QFrame()
        scan_group.setFrameShape(QFrame.StyledPanel)
        scan_layout = QVBoxLayout(scan_group)
        scan_layout.setContentsMargins(12, 10, 12, 10)
        scan_layout.setSpacing(6)

        url_row = QHBoxLayout()
        url_lbl = QLabel("URL Channel / Playlist:")
        url_lbl.setStyleSheet("font-weight: 600; color: #f1f5f9;")
        url_row.addWidget(url_lbl)
        url_row.addWidget(self.url_input, 1)
        url_row.addWidget(self.scan_btn)
        scan_layout.addLayout(url_row)
        scan_layout.addWidget(self.progress_bar)
        scan_layout.addWidget(self.scan_status_label)
        root.addWidget(scan_group)

        # Filter & Action toolbar Frame
        toolbar_group = QFrame()
        toolbar_group.setFrameShape(QFrame.StyledPanel)
        toolbar_layout = QVBoxLayout(toolbar_group)
        toolbar_layout.setContentsMargins(12, 8, 12, 8)
        toolbar_layout.setSpacing(8)

        filter_row = QHBoxLayout()
        filter_lbl = QLabel("Cari Judul:")
        filter_lbl.setStyleSheet("font-weight: 600; color: #f1f5f9;")
        filter_row.addWidget(filter_lbl)
        filter_row.addWidget(self.search_input, 1)
        mode_lbl = QLabel("Mode:")
        mode_lbl.setStyleSheet("font-weight: 600; color: #f1f5f9;")
        filter_row.addWidget(mode_lbl)
        filter_row.addWidget(self.filter_combo)
        filter_row.addWidget(self.filter_status_label)
        toolbar_layout.addLayout(filter_row)

        action_row = QHBoxLayout()
        action_row.addWidget(self.select_all_btn)
        action_row.addWidget(self.clear_all_btn)
        action_row.addWidget(self.select_filtered_btn)
        action_row.addWidget(self.clear_filtered_btn)
        action_row.addStretch()
        action_row.addWidget(self.stats_label)
        toolbar_layout.addLayout(action_row)

        root.addWidget(toolbar_group)

        # Table View
        root.addWidget(self.table_view, 1)

        # Bottom Bar
        bottom_row = QHBoxLayout()
        bottom_row.addStretch()
        bottom_row.addWidget(self.cancel_btn)
        bottom_row.addWidget(self.add_queue_btn)
        root.addLayout(bottom_row)

    def apply_dialog_styles(self):
        is_light = getattr(self, "theme_mode", "dark") == "light"
        if is_light:
            p = {
                "bg": "#f6f8fb",
                "card": "#ffffff",
                "border": "rgba(15, 23, 42, 0.10)",
                "text": "#0f172a",
                "label": "#1e293b",
                "input_bg": "#f8fafc",
                "input_focus": "#ffffff",
                "popup_bg": "#ffffff",
                "btn_bg": "#f1f5f9",
                "btn_hover": "#e2e8f0",
                "btn_pressed": "#cbd5e1",
                "btn_dis_bg": "#f1f5f9",
                "btn_dis_fg": "#94a3b8",
                "table_bg": "#ffffff",
                "table_alt": "#f8fafc",
                "grid": "rgba(15, 23, 42, 0.05)",
                "header_bg": "#f1f5f9",
                "header_fg": "#475569",
                "scroll": "rgba(15, 23, 42, 0.18)",
                "scroll_hover": "rgba(15, 23, 42, 0.34)",
            }
        else:
            p = {
                "bg": "#16171a",
                "card": "#202127",
                "border": "rgba(255, 255, 255, 0.08)",
                "text": "#f5f5f7",
                "label": "#e5e5ea",
                "input_bg": "#141519",
                "input_focus": "#181a21",
                "popup_bg": "#1f2027",
                "btn_bg": "#2a2c36",
                "btn_hover": "#353844",
                "btn_pressed": "#1f2128",
                "btn_dis_bg": "#191a20",
                "btn_dis_fg": "#555762",
                "table_bg": "#17181d",
                "table_alt": "#1c1e24",
                "grid": "rgba(255, 255, 255, 0.03)",
                "header_bg": "#22232a",
                "header_fg": "#a1a1a6",
                "scroll": "rgba(255, 255, 255, 0.16)",
                "scroll_hover": "rgba(255, 255, 255, 0.32)",
            }

        self.setStyleSheet(f"""
            QDialog {{
                background-color: {p['bg']};
                color: {p['text']};
                font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI Variable Display", "Segoe UI", sans-serif;
                font-size: 9.5pt;
            }}
            QFrame {{
                background-color: {p['card']};
                border: 1px solid {p['border']};
                border-radius: 10px;
            }}
            QLabel {{
                background-color: transparent;
                color: {p['label']};
            }}
            QLineEdit, QComboBox {{
                min-height: 28px;
                padding: 4px 10px;
                border: 1px solid {p['border']};
                border-radius: 8px;
                background-color: {p['input_bg']};
                color: {p['text']};
                selection-background-color: #0071e3;
                selection-color: #ffffff;
            }}
            QLineEdit:focus, QComboBox:focus {{
                border: 1.5px solid #0071e3;
                background-color: {p['input_focus']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 22px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {p['popup_bg']};
                color: {p['text']};
                border: 1px solid {p['border']};
                border-radius: 8px;
                selection-background-color: #0071e3;
                selection-color: #ffffff;
            }}
            QPushButton {{
                min-height: 28px;
                padding: 4px 14px;
                border: 1px solid {p['border']};
                border-radius: 8px;
                background-color: {p['btn_bg']};
                color: {p['text']};
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {p['btn_hover']};
                border-color: #0071e3;
            }}
            QPushButton:pressed {{
                background-color: {p['btn_pressed']};
            }}
            QPushButton:disabled {{
                background-color: {p['btn_dis_bg']};
                color: {p['btn_dis_fg']};
                border-color: transparent;
            }}
            QTableView {{
                background-color: {p['table_bg']};
                alternate-background-color: {p['table_alt']};
                color: {p['text']};
                border: 1px solid {p['border']};
                border-radius: 10px;
                gridline-color: {p['grid']};
                selection-background-color: rgba(0, 113, 227, 0.25);
                selection-color: {p['text']};
            }}
            QTableView::item {{
                padding: 6px;
            }}
            QTableView::item:selected {{
                background-color: rgba(0, 113, 227, 0.30);
                color: {p['text']};
            }}
            QHeaderView::section {{
                background-color: {p['header_bg']};
                color: {p['header_fg']};
                padding: 7px 10px;
                border: none;
                border-bottom: 1px solid {p['border']};
                font-weight: 600;
                font-size: 8.5pt;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 2px 0;
            }}
            QScrollBar::handle:vertical {{
                background: {p['scroll']};
                min-height: 24px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {p['scroll_hover']};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QProgressBar {{
                background-color: {p['input_bg']};
                border: 1px solid {p['border']};
                border-radius: 6px;
                min-height: 10px;
                max-height: 12px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0071e3, stop:1 #30d158);
                border-radius: 5px;
            }}
        """)

    def start_scan(self):
        url = self.url_input.text().strip()
        if not url:
            self.scan_status_label.setText("Masukkan URL channel atau playlist terlebih dahulu.")
            self.scan_status_label.setStyleSheet("color: #f87171;")
            return

        if self.scan_thread and self.scan_thread.isRunning():
            return

        self.scan_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.scan_status_label.setText("Sedang memindai daftar video (flat extraction)...")
        self.scan_status_label.setStyleSheet("color: #60a5fa;")

        self._in_flight_thumbnails.clear()
        self._failed_thumbnails.clear()
        self.thumbnail_cache.clear()
        self.table_model.set_items([])

        self.scan_thread = ChannelPreviewThread(
            target_url=url,
            cookies_browser=self.cookies_browser,
            cookies_file=self.cookies_file,
        )
        self.scan_thread.scan_finished.connect(self.on_scan_finished)
        self.scan_thread.scan_error.connect(self.on_scan_error)
        self.scan_thread.done.connect(self.on_scan_thread_done)
        self.scan_thread.start()

    def on_scan_finished(self, items, stats):
        self.table_model.set_items(items)
        total = stats.get("total", len(items))
        source = stats.get("source", "Channel")
        self.scan_status_label.setText(f"Berhasil memindai '{source}': {total} video ditemukan.")
        self.scan_status_label.setStyleSheet("color: #34d399; font-weight: 500;")
        self.update_counters()
        QTimer.singleShot(100, self.schedule_visible_thumbnails)

    def on_scan_error(self, message):
        self.scan_status_label.setText(message)
        self.scan_status_label.setStyleSheet("color: #f87171; font-weight: 500;")

    def on_scan_thread_done(self):
        self.scan_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.scan_thread = None

    def apply_search_filter(self):
        text = self.search_input.text()
        mode = self.filter_combo.currentText()
        self.proxy_model.set_filter_criteria(text, mode)

        if not self.proxy_model.is_regex_valid:
            self.filter_status_label.setText(f"Regex error: {self.proxy_model.regex_error_message}")
        else:
            self.filter_status_label.setText("")

        self.update_counters()
        QTimer.singleShot(80, self.schedule_visible_thumbnails)

    def update_counters(self):
        total = self.table_model.rowCount()
        filtered = self.proxy_model.rowCount()
        selected = len(self.table_model.selected_ids)
        self.stats_label.setText(f"Total: {total}  |  Filtered: {filtered}  |  Selected: {selected}")
        self.add_queue_btn.setText(f"Tambahkan {selected} Video ke Queue" if selected > 0 else "Tambahkan ke Queue")
        self.add_queue_btn.setEnabled(selected > 0)

    def on_filter_or_layout_changed(self):
        self.update_counters()
        QTimer.singleShot(60, self.schedule_visible_thumbnails)

    def select_filtered_items(self):
        ids = self.proxy_model.get_filtered_video_ids()
        self.table_model.select_ids(ids)

    def clear_filtered_items(self):
        ids = self.proxy_model.get_filtered_video_ids()
        self.table_model.unselect_ids(ids)

    def on_table_clicked(self, proxy_index):
        if not proxy_index.isValid():
            return
        if proxy_index.column() == VideoPreviewTableModel.COL_CHECK:
            src_idx = self.proxy_model.mapToSource(proxy_index)
            self.table_model.toggle_row(src_idx.row())

    def on_table_double_clicked(self, proxy_index):
        if not proxy_index.isValid():
            return
        src_idx = self.proxy_model.mapToSource(proxy_index)
        self.table_model.toggle_row(src_idx.row())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Space:
            curr = self.table_view.currentIndex()
            if curr.isValid():
                src_idx = self.proxy_model.mapToSource(curr)
                self.table_model.toggle_row(src_idx.row())
                return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(150, self.schedule_visible_thumbnails)

    def schedule_visible_thumbnails(self):
        if self.proxy_model.rowCount() == 0:
            return

        viewport = self.table_view.viewport()
        top_row = self.table_view.rowAt(0)
        bottom_row = self.table_view.rowAt(viewport.height() - 1)

        if top_row < 0:
            top_row = 0
        if bottom_row < 0:
            bottom_row = min(top_row + 25, self.proxy_model.rowCount() - 1)

        # Prefetch buffer
        start_row = max(0, top_row - 4)
        end_row = min(self.proxy_model.rowCount() - 1, bottom_row + 8)

        for proxy_row in range(start_row, end_row + 1):
            src_idx = self.proxy_model.mapToSource(self.proxy_model.index(proxy_row, 0))
            item = self.table_model.get_item(src_idx.row())
            if not item:
                continue

            vid_id = item.get("video_id")
            thumb_url = item.get("thumbnail_url")

            if not vid_id or not thumb_url:
                continue
            if self.thumbnail_cache.get(vid_id) is not None:
                continue
            if vid_id in self._in_flight_thumbnails or vid_id in self._failed_thumbnails:
                continue

            self._in_flight_thumbnails.add(vid_id)
            worker = ThumbnailWorker(video_id=vid_id, url=thumb_url)
            worker.signals.loaded.connect(self.on_thumbnail_loaded)
            worker.signals.failed.connect(self.on_thumbnail_failed)
            self.thread_pool.start(worker)

    def on_thumbnail_loaded(self, video_id, qimage):
        self._in_flight_thumbnails.discard(video_id)
        if hasattr(self, "table_model") and self.table_model:
            self.table_model.update_thumbnail(video_id, qimage)

    def on_thumbnail_failed(self, video_id):
        self._in_flight_thumbnails.discard(video_id)
        self._failed_thumbnails.add(video_id)

    def confirm_and_add_to_queue(self):
        selected = self.table_model.get_selected_items()
        if not selected:
            QMessageBox.information(self, "Preview", "Belum ada video yang dipilih.")
            return

        self.selected_items = selected
        self.items_selected.emit(selected)
        self.accept()

    def closeEvent(self, event):
        if self.scan_thread and self.scan_thread.isRunning():
            self.scan_thread.request_cancel()
            self.scan_thread.wait(1000)
        self.thread_pool.clear()
        self.thread_pool.waitForDone(150)
        super().closeEvent(event)
