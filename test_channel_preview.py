import os
import sys
import unittest
from datetime import datetime
from PySide6.QtCore import QCoreApplication, Qt, QModelIndex
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QPixmap

# Ensure QApplication exists for Qt tests
app = QApplication.instance()
if app is None:
    app = QApplication(sys.argv)

from channel_preview import (
    format_duration,
    format_upload_date,
    select_best_preview_thumbnail,
    ThumbnailCache,
    ThumbnailWorker,
    ChannelPreviewThread,
    VideoPreviewTableModel,
    VideoPreviewFilterProxyModel,
    ChannelPreviewDialog,
)
from main import App, APP_VERSION, APP_STATE_FILE


class TestFormattingHelpers(unittest.TestCase):
    def test_format_duration(self):
        self.assertEqual(format_duration(None), "-")
        self.assertEqual(format_duration("invalid"), "-")
        self.assertEqual(format_duration(-10), "-")
        self.assertEqual(format_duration(0), "00:00")
        self.assertEqual(format_duration(45), "00:45")
        self.assertEqual(format_duration(342), "05:42")
        self.assertEqual(format_duration(3600), "01:00:00")
        self.assertEqual(format_duration(3805), "01:03:25")
        self.assertEqual(format_duration(72000), "20:00:00")

    def test_format_upload_date(self):
        self.assertEqual(format_upload_date(None), "-")
        self.assertEqual(format_upload_date(""), "-")
        self.assertEqual(format_upload_date("20260830"), "2026-08-30")
        self.assertEqual(format_upload_date("2026-08-30"), "2026-08-30")
        self.assertEqual(format_upload_date("20241225"), "2024-12-25")
        # UNIX timestamps
        dt_str = datetime.fromtimestamp(1787443200).strftime("%Y-%m-%d")
        self.assertEqual(format_upload_date(1787443200), dt_str)
        self.assertEqual(format_upload_date("1787443200"), dt_str)

    def test_select_best_preview_thumbnail(self):
        self.assertIsNone(select_best_preview_thumbnail(None))
        self.assertEqual(select_best_preview_thumbnail("https://example.com/thumb.jpg"), "https://example.com/thumb.jpg")
        
        thumbs = [
            {"url": "https://img.youtube.com/vi/123/maxresdefault.jpg", "width": 1280, "height": 720},
            {"url": "https://img.youtube.com/vi/123/hqdefault.jpg", "width": 480, "height": 360},
            {"url": "https://img.youtube.com/vi/123/mqdefault.jpg", "width": 320, "height": 180},
            {"url": "https://img.youtube.com/vi/123/default.jpg", "width": 120, "height": 90},
        ]
        # Should pick the moderate size (hqdefault 480x360 <= 480)
        best = select_best_preview_thumbnail(thumbs, max_width=480)
        self.assertEqual(best, "https://img.youtube.com/vi/123/hqdefault.jpg")


class TestThumbnailCache(unittest.TestCase):
    def test_lru_cache_eviction(self):
        cache = ThumbnailCache(max_size=3)
        pix = QPixmap(10, 10)
        
        cache.put("vid1", pix)
        cache.put("vid2", pix)
        cache.put("vid3", pix)
        
        # Access vid1 and vid2, making vid3 the least recently used
        cache.get("vid1")
        cache.get("vid2")
        
        # Putting vid4 should evict vid3
        cache.put("vid4", pix)
        
        self.assertIsNotNone(cache.get("vid1"))
        self.assertIsNotNone(cache.get("vid2"))
        self.assertIsNotNone(cache.get("vid4"))
        self.assertIsNone(cache.get("vid3"))


class TestVideoPreviewTableModel(unittest.TestCase):
    def setUp(self):
        self.cache = ThumbnailCache(max_size=50)
        self.model = VideoPreviewTableModel(thumbnail_cache=self.cache)
        # Create 2000 dummy video items
        self.dummy_items = [
            {
                "url": f"https://www.youtube.com/watch?v=vid_{i:04d}",
                "title": f"Video Title {i} - {'Special Tutorial' if i % 5 == 0 else 'Daily Vlog'}",
                "video_id": f"vid_{i:04d}",
                "key": f"vid_{i:04d}",
                "playlist_index": i,
                "source": "Test Channel",
                "platform": "YouTube",
                "thumbnail_url": f"https://example.com/thumb_{i}.jpg",
                "duration": 60 + i * 10,
                "upload_date": "20260830",
            }
            for i in range(1, 2001)
        ]
        self.model.set_items(self.dummy_items)

    def test_model_dimensions(self):
        self.assertEqual(self.model.rowCount(), 2000)
        self.assertEqual(self.model.columnCount(), 6)

    def test_model_data_and_flags(self):
        idx_check = self.model.index(0, 0)
        idx_title = self.model.index(0, 2)
        idx_dur = self.model.index(0, 3)
        idx_date = self.model.index(0, 4)
        idx_id = self.model.index(0, 5)

        self.assertEqual(self.model.data(idx_check, Qt.CheckStateRole), Qt.Unchecked)
        self.assertEqual(self.model.data(idx_title, Qt.DisplayRole), "Video Title 1 - Daily Vlog")
        self.assertEqual(self.model.data(idx_dur, Qt.DisplayRole), "01:10")
        self.assertEqual(self.model.data(idx_date, Qt.DisplayRole), "2026-08-30")
        self.assertEqual(self.model.data(idx_id, Qt.DisplayRole), "vid_0001")

        flags = self.model.flags(idx_check)
        self.assertTrue(bool(flags & Qt.ItemIsUserCheckable))
        self.assertTrue(bool(flags & Qt.ItemIsEnabled))

    def test_selection_operations(self):
        # Select individual
        idx_check = self.model.index(0, 0)
        self.model.setData(idx_check, Qt.Checked, Qt.CheckStateRole)
        self.assertEqual(len(self.model.selected_ids), 1)
        self.assertIn("vid_0001", self.model.selected_ids)
        self.assertEqual(self.model.data(idx_check, Qt.CheckStateRole), Qt.Checked)

        # Toggle row
        self.model.toggle_row(0)
        self.assertEqual(len(self.model.selected_ids), 0)

        # Select all 2000
        self.model.select_all()
        self.assertEqual(len(self.model.selected_ids), 2000)
        self.assertEqual(len(self.model.get_selected_items()), 2000)

        # Clear selection
        self.model.clear_selection()
        self.assertEqual(len(self.model.selected_ids), 0)
        self.assertEqual(len(self.model.get_selected_items()), 0)

        # Select specific IDs
        self.model.select_ids(["vid_0001", "vid_0002", "vid_0050"])
        self.assertEqual(len(self.model.selected_ids), 3)

        # Unselect subset
        self.model.unselect_ids(["vid_0001"])
        self.assertEqual(len(self.model.selected_ids), 2)
        self.assertNotIn("vid_0001", self.model.selected_ids)


class TestVideoPreviewFilterProxyModel(unittest.TestCase):
    def setUp(self):
        self.model = VideoPreviewTableModel()
        self.items = [
            {"video_id": "v1", "title": "Belajar Python Dasar Bagian 1", "url": "url1"},
            {"video_id": "v2", "title": "Belajar Python Lanjutan Bagian 2", "url": "url2"},
            {"video_id": "v3", "title": "Tutorial JavaScript Modern", "url": "url3"},
            {"video_id": "v4", "title": "Podcast #10: Diskusi Teknologi AI", "url": "url4"},
            {"video_id": "v5", "title": "Live Stream Coding Python", "url": "url5"},
        ]
        self.model.set_items(self.items)
        self.proxy = VideoPreviewFilterProxyModel()
        self.proxy.setSourceModel(self.model)

    def test_filter_contains(self):
        self.proxy.set_filter_criteria("python", VideoPreviewFilterProxyModel.MODE_CONTAINS)
        self.assertEqual(self.proxy.rowCount(), 3)
        ids = self.proxy.get_filtered_video_ids()
        self.assertEqual(ids, ["v1", "v2", "v5"])

    def test_filter_exact(self):
        self.proxy.set_filter_criteria("tutorial javascript modern", VideoPreviewFilterProxyModel.MODE_EXACT)
        self.assertEqual(self.proxy.rowCount(), 1)
        self.assertEqual(self.proxy.get_filtered_video_ids(), ["v3"])

    def test_filter_starts_with(self):
        self.proxy.set_filter_criteria("belajar", VideoPreviewFilterProxyModel.MODE_STARTS_WITH)
        self.assertEqual(self.proxy.rowCount(), 2)
        self.assertEqual(self.proxy.get_filtered_video_ids(), ["v1", "v2"])

    def test_filter_regex_valid(self):
        self.proxy.set_filter_criteria(r"Python\s+(Dasar|Lanjutan)", VideoPreviewFilterProxyModel.MODE_REGEX)
        self.assertTrue(self.proxy.is_regex_valid)
        self.assertEqual(self.proxy.rowCount(), 2)
        self.assertEqual(self.proxy.get_filtered_video_ids(), ["v1", "v2"])

    def test_filter_regex_invalid(self):
        # Invalid regex [unclosed bracket
        self.proxy.set_filter_criteria(r"[unclosed(regex", VideoPreviewFilterProxyModel.MODE_REGEX)
        self.assertFalse(self.proxy.is_regex_valid)
        self.assertNotEqual(self.proxy.regex_error_message, "")
        # Should not crash, falls back to substring match
        self.assertGreaterEqual(self.proxy.rowCount(), 0)

    def test_selection_across_filter(self):
        # Select v1 and v3
        self.model.select_ids(["v1", "v3"])
        
        # Filter only "Python" -> v1, v2, v5 visible
        self.proxy.set_filter_criteria("Python", VideoPreviewFilterProxyModel.MODE_CONTAINS)
        self.assertEqual(self.proxy.rowCount(), 3)
        
        # v1 should still be checked in proxy
        src_v1_idx = self.model.index(0, 0)
        proxy_v1_idx = self.proxy.mapFromSource(src_v1_idx)
        self.assertEqual(self.proxy.data(proxy_v1_idx, Qt.CheckStateRole), Qt.Checked)
        
        # Select filtered
        filtered_ids = self.proxy.get_filtered_video_ids()
        self.model.select_ids(filtered_ids)
        # Now v1, v2, v5, and v3 should be selected
        self.assertEqual(self.model.selected_ids, {"v1", "v2", "v3", "v5"})


class TestQueueIntegration(unittest.TestCase):
    def test_queue_item_conversion(self):
        preview_items = [
            {
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "title": "Never Gonna Give You Up",
                "video_id": "dQw4w9WgXcQ",
                "key": "dQw4w9WgXcQ",
                "playlist_index": 1,
                "source": "Rick Astley Channel",
                "platform": "YouTube",
                "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
                "duration": 213,
                "upload_date": "20091025",
            }
        ]
        
        main_app = App()
        main_app.queue_items = []
        main_app.handle_channel_preview_items(preview_items)
        
        self.assertEqual(len(main_app.queue_items), 1)
        job = main_app.queue_items[0]
        self.assertEqual(job["url"], "https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(job["title"], "Never Gonna Give You Up")
        self.assertEqual(job["platform"], "YouTube")
        self.assertEqual(job["video_id"], "dQw4w9WgXcQ")
        self.assertEqual(job["status"], "Queued")
        self.assertEqual(job["progress"], 0)


class TestChannelPreviewDialog(unittest.TestCase):
    def test_dialog_full_flow(self):
        dialog = ChannelPreviewDialog(initial_url="https://www.youtube.com/@test/videos")
        self.assertEqual(dialog.url_input.text(), "https://www.youtube.com/@test/videos")
        self.assertFalse(dialog.add_queue_btn.isEnabled())

        # Test scan results handling
        items = [
            {
                "video_id": f"v_{i:03d}",
                "title": f"Video {i} - " + ("Music Clip" if i % 2 == 0 else "Tutorial Python"),
                "url": f"https://www.youtube.com/watch?v=v_{i:03d}",
                "duration": 180 + i,
                "upload_date": "20260830",
                "thumbnail_url": "https://example.com/thumb.jpg",
            }
            for i in range(1, 101)
        ]

        dialog.on_scan_finished(items, {"source": "Test Channel", "total": 100})
        self.assertEqual(dialog.table_model.rowCount(), 100)
        self.assertEqual(dialog.proxy_model.rowCount(), 100)
        self.assertIn("Total: 100", dialog.stats_label.text())
        self.assertIn("Selected: 0", dialog.stats_label.text())

        # Select all
        dialog.select_all_btn.click()
        self.assertEqual(len(dialog.table_model.selected_ids), 100)
        self.assertTrue(dialog.add_queue_btn.isEnabled())
        self.assertIn("Selected: 100", dialog.stats_label.text())

        # Filter
        dialog.search_input.setText("Music Clip")
        dialog.apply_search_filter()
        self.assertEqual(dialog.proxy_model.rowCount(), 50)
        self.assertIn("Filtered: 50", dialog.stats_label.text())

        # Clear all
        dialog.clear_all_btn.click()
        self.assertEqual(len(dialog.table_model.selected_ids), 0)
        self.assertFalse(dialog.add_queue_btn.isEnabled())

        # Select filtered
        dialog.select_filtered_btn.click()
        self.assertEqual(len(dialog.table_model.selected_ids), 50)
        self.assertIn("Selected: 50", dialog.stats_label.text())
        self.assertTrue(dialog.add_queue_btn.isEnabled())

        # Clear filter
        dialog.search_input.setText("")
        dialog.apply_search_filter()
        self.assertEqual(dialog.proxy_model.rowCount(), 100)
        self.assertEqual(len(dialog.table_model.selected_ids), 50)

        # Confirm and queue
        dialog.confirm_and_add_to_queue()
        self.assertEqual(len(dialog.selected_items), 50)


class TestAppRegression(unittest.TestCase):
    def test_app_widgets_and_mode(self):
        main_app = App()
        self.assertIsNotNone(main_app.channel_preview_btn)
        self.assertIsNotNone(main_app.channel_fetch_btn)
        self.assertIsNotNone(main_app.urls_input)
        self.assertIsNotNone(main_app.queue_table)
        
        # Test Simple Mode: Advanced tabs disabled and legacy direct controls hidden
        main_app.mode_combo.setCurrentText("Simple Mode")
        main_app.apply_ui_mode()
        self.assertFalse(main_app.tabs.isTabEnabled(1)) # Advanced tab disabled
        self.assertTrue(main_app.legacy_channel_controls.isHidden()) # Legacy controls hidden in Simple Mode
        
        # Test Power Mode: Advanced tabs enabled and legacy direct controls visible
        main_app.mode_combo.setCurrentText("Power Mode")
        main_app.apply_ui_mode()
        self.assertTrue(main_app.tabs.isTabEnabled(1)) # Advanced tab enabled
        self.assertFalse(main_app.legacy_channel_controls.isHidden()) # Legacy controls visible in Power Mode

    def test_initial_url_propagation(self):
        main_app = App()
        test_url = "https://www.youtube.com/@djwangi"
        main_app.channel_url_input.setText(test_url)

        dialog = ChannelPreviewDialog(parent=main_app, initial_url=test_url)
        self.assertEqual(dialog.url_input.text(), test_url)

    def test_queue_table_rendering_after_selection(self):
        main_app = App()
        main_app.queue_items = []
        main_app.queue_table.setRowCount(0)

        selected = [
            {"video_id": "vid_01", "title": "Song 1", "url": "https://youtube.com/watch?v=vid_01", "source": "Channel Test"},
            {"video_id": "vid_02", "title": "Song 2", "url": "https://youtube.com/watch?v=vid_02", "source": "Channel Test"},
            {"video_id": "vid_03", "title": "Song 3", "url": "https://youtube.com/watch?v=vid_03", "source": "Channel Test"},
        ]

        main_app.handle_channel_preview_items(selected)

        self.assertEqual(len(main_app.queue_items), 3)
        self.assertEqual(main_app.queue_table.rowCount(), 3)
        self.assertEqual(main_app.queue_table.item(0, 0).text(), "Song 1")
        self.assertEqual(main_app.queue_table.item(1, 0).text(), "Song 2")
        self.assertEqual(main_app.queue_table.item(2, 0).text(), "Song 3")
        self.assertEqual(main_app.queue_table.item(0, 4).text(), "Queued")

    def test_simple_mode_visibility_and_facade(self):
        main_app = App()
        
        # 1. Simple Mode
        main_app.mode_combo.setCurrentText("Simple Mode")
        main_app.apply_ui_mode()
        self.assertTrue(main_app.preset_label.isHidden())
        self.assertTrue(main_app.preset_combo.isHidden())
        self.assertTrue(main_app.format_label.isHidden())
        self.assertTrue(main_app.format_combo.isHidden())
        self.assertFalse(main_app.media_type_label.isHidden())
        self.assertFalse(main_app.media_type_combo.isHidden())
        self.assertFalse(main_app.quality_combo.isHidden())
        self.assertTrue(main_app.power_download_controls.isHidden())

        # 2. Power Mode
        main_app.mode_combo.setCurrentText("Power Mode")
        main_app.apply_ui_mode()
        self.assertFalse(main_app.preset_label.isHidden())
        self.assertFalse(main_app.preset_combo.isHidden())
        self.assertFalse(main_app.format_label.isHidden())
        self.assertFalse(main_app.format_combo.isHidden())
        self.assertTrue(main_app.media_type_label.isHidden())
        self.assertTrue(main_app.media_type_combo.isHidden())
        self.assertFalse(main_app.quality_combo.isHidden())
        self.assertFalse(main_app.power_download_controls.isHidden())

    def test_media_type_video_and_audio_mapping(self):
        main_app = App()
        main_app.mode_combo.setCurrentText("Simple Mode")
        main_app.apply_ui_mode()

        # Select Video
        main_app.media_type_combo.setCurrentText("Video")
        self.assertEqual(main_app.format_combo.currentText(), "MP4 Video")
        self.assertTrue(main_app.quality_combo.isEnabled())

        # Select Audio
        main_app.media_type_combo.setCurrentText("Audio")
        self.assertEqual(main_app.format_combo.currentText(), "MP3 Audio")
        self.assertFalse(main_app.quality_combo.isEnabled())

    def test_mode_switching_synchronization(self):
        main_app = App()
        
        # Set quality to 1440p
        main_app.quality_combo.setCurrentText("1440p")

        # In Power Mode, select FLAC Audio
        main_app.mode_combo.setCurrentText("Power Mode")
        main_app.apply_ui_mode()
        main_app.format_combo.setCurrentText("FLAC Audio")

        # Switch to Simple Mode
        main_app.mode_combo.setCurrentText("Simple Mode")
        main_app.apply_ui_mode()
        self.assertEqual(main_app.media_type_combo.currentText(), "Audio")
        self.assertEqual(main_app.format_combo.currentText(), "FLAC Audio")

        # Switch to Video in Simple Mode
        main_app.media_type_combo.setCurrentText("Video")
        self.assertEqual(main_app.format_combo.currentText(), "MP4 Video")
        self.assertEqual(main_app.quality_combo.currentText(), "1440p") # Quality preserved!

        # Switch back to Power Mode
        main_app.mode_combo.setCurrentText("Power Mode")
        main_app.apply_ui_mode()
        self.assertEqual(main_app.format_combo.currentText(), "MP4 Video")
        self.assertEqual(main_app.quality_combo.currentText(), "1440p")


if __name__ == "__main__":
    unittest.main()


