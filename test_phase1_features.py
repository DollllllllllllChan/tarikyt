import os
import sys
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

app = QApplication.instance() or QApplication(sys.argv)

from main import App, HISTORY_FILE, resolve_ffmpeg, resolve_ffprobe, find_common_ffprobe, classify_download_error_hint

class TestPhase1Features(unittest.TestCase):
    def setUp(self):
        self.main_app = App()

    def test_lazy_history_initialization(self):
        # 1. On startup, history should NOT be loaded
        self.assertFalse(self.main_app.history_loaded)
        self.assertEqual(self.main_app.history_table.rowCount(), 0)

        # 2. When switching to History tab (index 4), it loads
        history_tab_idx = -1
        for i in range(self.main_app.tabs.count()):
            if self.main_app.tabs.tabText(i) == "History":
                history_tab_idx = i
                break
        self.assertNotEqual(history_tab_idx, -1)

        self.main_app.tabs.setCurrentIndex(history_tab_idx)
        app.processEvents()
        self.assertTrue(self.main_app.history_loaded)

        # 3. Switching back and forth does not duplicate rows
        count_first = self.main_app.history_table.rowCount()
        self.main_app.tabs.setCurrentIndex(0)
        app.processEvents()
        self.main_app.tabs.setCurrentIndex(history_tab_idx)
        app.processEvents()
        self.assertEqual(self.main_app.history_table.rowCount(), count_first)

    def test_target_info_formatting(self):
        # Video mode
        self.main_app.format_combo.setCurrentText("MP4 Video")
        self.main_app.quality_combo.setCurrentText("1440p")
        self.main_app.auto_container_checkbox.setChecked(True)
        self.main_app.update_target_info()
        text = self.main_app.target_info_label.text()
        self.assertIn("1440p", text)
        self.assertIn("Auto (MKV/MP4)", text)

        # Audio mode
        self.main_app.format_combo.setCurrentText("MP3 Audio")
        self.main_app.audio_bitrate.setValue(320)
        self.main_app.update_target_info()
        text_audio = self.main_app.target_info_label.text()
        self.assertIn("Audio (MP3)", text_audio)
        self.assertIn("320 kbps", text_audio)

        # Image mode
        self.main_app.format_combo.setCurrentText("Image")
        self.main_app.update_target_info()
        text_img = self.main_app.target_info_label.text()
        self.assertIn("Image (Original)", text_img)

    def test_target_info_with_queue_item(self):
        self.main_app.format_combo.setCurrentText("MP4 Video")
        self.main_app.quality_combo.setCurrentText("1080p")
        
        # Item with available info only
        item_available = {
            "title": "Test Video",
            "qualities": "1080p, 720p",
            "quality_sizes": "1080p (~120MB)",
            "actual_format": "-"
        }
        self.main_app.update_target_info(item_available)
        self.assertIn("Available:", self.main_app.target_info_label.text())

        # Item with actual format
        item_actual = {
            "title": "Test Video",
            "actual_format": "1920x1080 60fps (~110MB)",
        }
        self.main_app.update_target_info(item_actual)
        self.assertIn("Actual:", self.main_app.target_info_label.text())
        self.assertIn("1920x1080", self.main_app.target_info_label.text())

    def test_resolve_ffprobe_companion(self):
        # When resolve_ffmpeg returns a path, resolve_ffprobe finds its companion beside it
        ffmpeg = resolve_ffmpeg()
        ffprobe = resolve_ffprobe()
        if ffmpeg and os.path.exists(ffmpeg):
            self.assertIsNotNone(ffprobe)
            self.assertTrue(os.path.exists(ffprobe))
            # Sibling check if directory matches
            companion = os.path.join(os.path.dirname(ffmpeg), "ffprobe.exe")
            if os.path.exists(companion):
                self.assertEqual(os.path.normcase(ffprobe), os.path.normcase(companion))

    def test_resolve_ffprobe_directory_and_file_input(self):
        ffmpeg = resolve_ffmpeg()
        if ffmpeg and os.path.exists(ffmpeg):
            ff_dir = os.path.dirname(ffmpeg)
            # Directory input
            resolved_from_dir = resolve_ffprobe(ff_dir)
            self.assertIsNotNone(resolved_from_dir)
            self.assertTrue(os.path.exists(resolved_from_dir))

            # Full path to ffmpeg.exe input
            resolved_from_ffmpeg = resolve_ffprobe(ffmpeg)
            self.assertIsNotNone(resolved_from_ffmpeg)

            # Full path to ffprobe.exe input
            companion = os.path.join(ff_dir, "ffprobe.exe")
            if os.path.exists(companion):
                resolved_from_probe = resolve_ffprobe(companion)
                self.assertEqual(os.path.normcase(resolved_from_probe), os.path.normcase(companion))

    def test_resolve_ffprobe_invalid_path(self):
        # Invalid / nonexistent path must not crash
        resolved = resolve_ffprobe("C:\\nonexistent_invalid_path\\ffmpeg.exe")
        # Should fallback gracefully or return valid system fallback
        self.assertTrue(resolved is None or os.path.exists(resolved))

    def test_show_engine_health_dialog_execution(self):
        # show_engine_health_dialog must execute cleanly without NameError / exception
        with patch("PySide6.QtWidgets.QMessageBox.exec", return_value=0):
            try:
                self.main_app.show_engine_health_dialog()
            except Exception as e:
                self.fail(f"show_engine_health_dialog raised exception: {e}")

    def test_show_engine_health_dialog_missing_components(self):
        # Test when ffmpeg/ffprobe resolution returns None
        with patch("main.resolve_ffmpeg", return_value=None), \
             patch("main.resolve_ffprobe", return_value=None), \
             patch("PySide6.QtWidgets.QMessageBox.exec", return_value=0):
            try:
                self.main_app.show_engine_health_dialog()
            except Exception as e:
                self.fail(f"show_engine_health_dialog crashed when components missing: {e}")

    def test_classify_download_error_hint(self):
        self.assertIn("Cookies", classify_download_error_hint("ERROR: Sign in to confirm you're not a bot"))
        self.assertIn("Cookies", classify_download_error_hint("HTTP Error 403: Forbidden"))
        self.assertIn("FFmpeg", classify_download_error_hint("ffmpeg is not installed or postprocessing failed"))
        self.assertIn("koneksi", classify_download_error_hint("Connection timed out while downloading").lower())
        self.assertIn("privat", classify_download_error_hint("Private video. Sign in if you've been granted access").lower())
        self.assertEqual(classify_download_error_hint("Download selesai 100%"), "")

    def test_dual_theme_toggle(self):
        initial_mode = self.main_app.theme_mode
        self.main_app.toggle_theme()
        app.processEvents()
        self.assertNotEqual(self.main_app.theme_mode, initial_mode)
        self.main_app.toggle_theme()
        app.processEvents()
        self.assertEqual(self.main_app.theme_mode, initial_mode)

    def test_all_tabs_use_cupertino_cards_without_groupbox(self):
        from PySide6.QtWidgets import QGroupBox
        for idx in range(self.main_app.tabs.count()):
            tab_widget = self.main_app.tabs.widget(idx)
            group_boxes = tab_widget.findChildren(QGroupBox)
            self.assertEqual(len(group_boxes), 0, f"Tab index {idx} still contains legacy QGroupBox")

    def test_invalidate_queue_preserves_channel_preview_items(self):
        self.main_app.prepare_queue_table([
            {
                "url": "https://www.youtube.com/watch?v=test_cp_1",
                "title": "Test Video",
                "platform": "YouTube",
                "source": "Channel Preview",
                "status": "Queued",
                "progress": 0,
            }
        ])
        self.assertEqual(len(self.main_app.queue_items), 1)
        self.main_app.urls_input.setPlainText("")
        self.main_app.invalidate_queue()
        self.assertEqual(len(self.main_app.queue_items), 1)

    def test_start_download_empty_updates_visible_status(self):
        self.main_app.urls_input.setPlainText("")
        self.main_app.queue_items = []
        self.main_app.start_download()
        self.assertIn("kosong", self.main_app.status_label.text().lower())

    def test_delete_selected_queue_rows(self):
        self.main_app.prepare_queue_table([
            {"url": "https://www.youtube.com/watch?v=v1", "title": "Video 1", "platform": "YouTube", "status": "Queued", "progress": 0},
            {"url": "https://www.youtube.com/watch?v=v2", "title": "Video 2", "platform": "YouTube", "status": "Queued", "progress": 0},
        ])
        self.assertEqual(len(self.main_app.queue_items), 2)
        self.main_app.queue_table.selectRow(0)
        self.main_app.delete_selected_queue_rows()
        self.assertEqual(len(self.main_app.queue_items), 1)
        self.assertEqual(self.main_app.queue_items[0]["title"], "Video 2")

if __name__ == "__main__":
    unittest.main()
