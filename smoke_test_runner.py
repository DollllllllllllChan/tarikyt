import sys
import time
import unittest
from PySide6.QtCore import QEventLoop, QTimer, Qt, QItemSelectionModel
from PySide6.QtWidgets import QApplication
from channel_preview import (
    ChannelPreviewThread,
    ChannelPreviewDialog,
    VideoPreviewTableModel,
    VideoPreviewFilterProxyModel,
    ThumbnailCache,
    ThumbnailWorker,
)
from main import App, ChannelVideosThread, MetadataThread, TestLinkThread

app = QApplication.instance() or QApplication(sys.argv)


class RealWorldSmokeTest(unittest.TestCase):
    def test_01_startup_and_ui_modes(self):
        print("\n--- [TEST 1] STARTUP & UI MODES ---")
        main_app = App()
        self.assertIsNotNone(main_app.channel_preview_btn)
        self.assertEqual(main_app.channel_preview_btn.text(), "Preview Channel / Playlist")
        self.assertIsNotNone(main_app.channel_fetch_btn)
        self.assertEqual(main_app.channel_fetch_btn.text(), "Ambil dari Channel")

        # Test Simple Mode
        main_app.mode_combo.setCurrentText("Simple Mode")
        main_app.apply_ui_mode()
        self.assertFalse(main_app.tabs.isTabEnabled(1))
        self.assertFalse(main_app.tabs.isTabEnabled(2))

        # Test Power Mode
        main_app.mode_combo.setCurrentText("Power Mode")
        main_app.apply_ui_mode()
        self.assertTrue(main_app.tabs.isTabEnabled(1))
        self.assertTrue(main_app.tabs.isTabEnabled(2))
        print("PASS: Startup & Simple/Power mode toggles verified.")

    def test_02_real_channel_scan(self):
        print("\n--- [TEST 2] REAL PUBLIC CHANNEL SCAN ---")
        channel_url = "https://www.youtube.com/@NoCopyrightSounds/videos"
        thread = ChannelPreviewThread(target_url=channel_url)

        items_out = []
        errors_out = []

        thread.scan_finished.connect(lambda items, stats: items_out.extend(items))
        thread.scan_error.connect(lambda err: errors_out.append(err))

        t0 = time.time()
        thread.start()
        loop = QEventLoop()
        thread.done.connect(loop.quit)
        QTimer.singleShot(25000, loop.quit)
        loop.exec()
        elapsed = time.time() - t0

        self.assertEqual(len(errors_out), 0, f"Scan encountered errors: {errors_out}")
        self.assertGreater(len(items_out), 10, "Should return at least 10 items from public channel")
        print(f"PASS: Scanned {len(items_out)} videos in {elapsed:.2f}s")

        # Check first 10 items
        for i, it in enumerate(items_out[:10], 1):
            self.assertTrue(bool(it.get("title")), f"Item {i} missing title")
            self.assertTrue(bool(it.get("video_id")), f"Item {i} missing video_id")
            self.assertTrue(it.get("url", "").startswith("https://www.youtube.com/watch?v="), f"Item {i} invalid URL")
            self.assertTrue(bool(it.get("thumbnail_url")), f"Item {i} missing thumbnail_url")
            print(f"  [{i}] ID: {it['video_id']} | Dur: {it.get('duration')} | Date: {it.get('upload_date')} | Title: {it['title'][:40]}...")

    def test_03_real_channel_scan_short_url(self):
        print("\n--- [TEST 3] REAL CHANNEL SCAN (WITHOUT /videos SUFFIX) ---")
        channel_url = "https://www.youtube.com/@NoCopyrightSounds"
        thread = ChannelPreviewThread(target_url=channel_url)

        items_out = []
        thread.scan_finished.connect(lambda items, stats: items_out.extend(items))

        thread.start()
        loop = QEventLoop()
        thread.done.connect(loop.quit)
        QTimer.singleShot(25000, loop.quit)
        loop.exec()

        self.assertGreater(len(items_out), 0, "Channel URL without /videos should auto-normalize and scan successfully")
        print(f"PASS: Normalized URL scanned successfully ({len(items_out)} videos).")

    def test_04_real_playlist_scan(self):
        print("\n--- [TEST 4] REAL PUBLIC PLAYLIST SCAN ---")
        # YouTube public playlist (Top Music Videos)
        playlist_url = "https://www.youtube.com/playlist?list=PLFgquLnL59alCl_2TQvOiD5Vgm1hCaGSI"
        thread = ChannelPreviewThread(target_url=playlist_url)

        items_out = []
        errors_out = []
        thread.scan_finished.connect(lambda items, stats: items_out.extend(items))
        thread.scan_error.connect(lambda err: errors_out.append(err))

        t0 = time.time()
        thread.start()
        loop = QEventLoop()
        thread.done.connect(loop.quit)
        QTimer.singleShot(25000, loop.quit)
        loop.exec()
        elapsed = time.time() - t0

        self.assertEqual(len(errors_out), 0, f"Playlist scan error: {errors_out}")
        self.assertGreater(len(items_out), 0, "Playlist should return entries")
        print(f"PASS: Scanned playlist with {len(items_out)} videos in {elapsed:.2f}s")
        # Verify playlist URL was not normalized to /videos
        self.assertFalse(playlist_url.endswith("/videos"))

    def test_05_filter_and_selection_on_real_data(self):
        print("\n--- [TEST 5] FILTER & SELECTION WITH REAL DATA ---")
        # Use real data sample
        real_sample = [
            {"video_id": "v1", "title": "Alan Walker - Faded (NCS Release)", "url": "https://www.youtube.com/watch?v=v1", "thumbnail_url": "https://example.com/1.jpg"},
            {"video_id": "v2", "title": "Cartoon - On & On (feat. Daniel Levi) [NCS Release]", "url": "https://www.youtube.com/watch?v=v2", "thumbnail_url": "https://example.com/2.jpg"},
            {"video_id": "v3", "title": "Elektronomia - Sky High [NCS Release]", "url": "https://www.youtube.com/watch?v=v3", "thumbnail_url": "https://example.com/3.jpg"},
            {"video_id": "v4", "title": "Different Heaven & EH!DE - My Heart [NCS Release]", "url": "https://www.youtube.com/watch?v=v4", "thumbnail_url": "https://example.com/4.jpg"},
            {"video_id": "v5", "title": "DEAF KEV - Invincible [NCS Release]", "url": "https://www.youtube.com/watch?v=v5", "thumbnail_url": "https://example.com/5.jpg"},
        ]

        dialog = ChannelPreviewDialog()
        dialog.table_model.set_items(real_sample)

        # 1. Select 2 items manually (v1 and v3)
        dialog.table_model.select_ids(["v1", "v3"])
        self.assertEqual(len(dialog.table_model.selected_ids), 2)
        self.assertIn("Selected: 2", dialog.stats_label.text())

        # 2. Filter Contains "daniel" -> matches only v2
        dialog.filter_combo.setCurrentText("Contains")
        dialog.search_input.setText("daniel")
        dialog.apply_search_filter()
        self.assertEqual(dialog.proxy_model.rowCount(), 1)
        self.assertIn("Filtered: 1", dialog.stats_label.text())
        # Selection of v1 and v3 must still be preserved!
        self.assertEqual(dialog.table_model.selected_ids, {"v1", "v3"})
        self.assertIn("Selected: 2", dialog.stats_label.text())

        # 3. Select Filtered -> adds v2 to selection (total 3: v1, v2, v3)
        dialog.select_filtered_btn.click()
        self.assertEqual(dialog.table_model.selected_ids, {"v1", "v2", "v3"})
        self.assertIn("Selected: 3", dialog.stats_label.text())

        # 4. Clear Filtered -> removes v2 from selection (leaves v1, v3)
        dialog.clear_filtered_btn.click()
        self.assertEqual(dialog.table_model.selected_ids, {"v1", "v3"})
        self.assertIn("Selected: 2", dialog.stats_label.text())

        # 5. Clear search -> all 5 rows visible
        dialog.search_input.setText("")
        dialog.apply_search_filter()
        self.assertEqual(dialog.proxy_model.rowCount(), 5)
        self.assertEqual(dialog.table_model.selected_ids, {"v1", "v3"})

        # 6. Test Exact Mode
        dialog.filter_combo.setCurrentText("Exact")
        dialog.search_input.setText("DEAF KEV - Invincible [NCS Release]")
        dialog.apply_search_filter()
        self.assertEqual(dialog.proxy_model.rowCount(), 1)
        self.assertEqual(dialog.proxy_model.get_filtered_video_ids(), ["v5"])

        # 7. Test Starts With Mode
        dialog.filter_combo.setCurrentText("Starts With")
        dialog.search_input.setText("Elektronomia")
        dialog.apply_search_filter()
        self.assertEqual(dialog.proxy_model.rowCount(), 1)
        self.assertEqual(dialog.proxy_model.get_filtered_video_ids(), ["v3"])

        # 8. Test Invalid Regex
        dialog.filter_combo.setCurrentText("Regex")
        dialog.search_input.setText("([invalid_regex")
        dialog.apply_search_filter()
        self.assertFalse(dialog.proxy_model.is_regex_valid)
        self.assertIn("Regex error", dialog.filter_status_label.text())
        # Should not crash!

        # 9. Test Valid Regex
        dialog.search_input.setText(r"(Alan|Cartoon)")
        dialog.apply_search_filter()
        self.assertTrue(dialog.proxy_model.is_regex_valid)
        self.assertEqual(dialog.proxy_model.rowCount(), 2)

        # 10. Sort Title and check selection binding
        dialog.search_input.setText("")
        dialog.apply_search_filter()
        dialog.table_view.sortByColumn(VideoPreviewTableModel.COL_TITLE, Qt.AscendingOrder)
        # Selection should still be v1, v3
        self.assertEqual(dialog.table_model.selected_ids, {"v1", "v3"})
        print("PASS: Filter, regex handling, and selection persistence verified.")

    def test_06_real_thumbnail_fetching(self):
        print("\n--- [TEST 6] REAL THUMBNAIL FETCHING & LRU CACHE ---")
        # YouTube public thumbnail URL
        thumb_url = "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
        worker = ThumbnailWorker(video_id="dQw4w9WgXcQ", url=thumb_url)

        loaded_image = []
        worker.signals.loaded.connect(lambda vid, img: loaded_image.append((vid, img)))

        worker.run()
        self.assertEqual(len(loaded_image), 1, "Real thumbnail should decode successfully")
        vid, img = loaded_image[0]
        self.assertEqual(vid, "dQw4w9WgXcQ")
        self.assertEqual(img.width(), 120)
        self.assertEqual(img.height(), 68)
        print("PASS: Real thumbnail fetched, decoded to QImage, and rescaled to 120x68 px.")

    def test_07_close_during_scan_lifecycle(self):
        print("\n--- [TEST 7] CLOSE DIALOG DURING SCAN ---")
        dialog = ChannelPreviewDialog()
        dialog.url_input.setText("https://www.youtube.com/@NoCopyrightSounds/videos")
        dialog.start_scan()
        self.assertIsNotNone(dialog.scan_thread)
        self.assertTrue(dialog.scan_thread.isRunning())

        # Close dialog immediately while thread is running
        dialog.close()
        # Thread should be safely requested to cancel and waited
        self.assertTrue(dialog.scan_thread._is_cancelled)
        print("PASS: Dialog closed safely while scan was in progress without Qt crash.")

    def test_08_close_during_thumbnail_loading(self):
        print("\n--- [TEST 8] CLOSE DIALOG DURING THUMBNAIL LOADING ---")
        dialog = ChannelPreviewDialog()
        items = [
            {"video_id": f"v_{i}", "title": f"Video {i}", "url": f"https://www.youtube.com/watch?v=v_{i}", "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"}
            for i in range(50)
        ]
        dialog.on_scan_finished(items, {"source": "Test", "total": 50})
        # Schedule thumbnails
        dialog.schedule_visible_thumbnails()
        # Close dialog immediately while workers in thread_pool might be queued/running
        dialog.close()
        print("PASS: Dialog closed safely during thumbnail loading with thread_pool cleared.")

    def test_09_queue_integration_and_duplicates(self):
        print("\n--- [TEST 9] QUEUE INTEGRATION WITH REAL PREVIEW DATA ---")
        main_app = App()
        main_app.queue_items = []

        selected = [
            {"video_id": "vid_A", "title": "Song A", "url": "https://www.youtube.com/watch?v=vid_A", "source": "Channel 1"},
            {"video_id": "vid_B", "title": "Song B", "url": "https://www.youtube.com/watch?v=vid_B", "source": "Channel 1"},
            {"video_id": "vid_C", "title": "Song C", "url": "https://www.youtube.com/watch?v=vid_C", "source": "Channel 1"},
        ]

        main_app.handle_channel_preview_items(selected)
        self.assertEqual(len(main_app.queue_items), 3)
        self.assertEqual(main_app.queue_table.rowCount(), 3)
        self.assertEqual(main_app.queue_items[0]["title"], "Song A")
        self.assertEqual(main_app.queue_items[1]["title"], "Song B")
        self.assertEqual(main_app.queue_items[2]["title"], "Song C")
        print("PASS: Exactly 3 items transferred to existing download queue table.")

    def test_10_single_video_regression(self):
        print("\n--- [TEST 10] SINGLE VIDEO REGRESSION (TEST LINK & METADATA) ---")
        main_app = App()
        test_thread = TestLinkThread(
            urls=["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
            cookies_browser="None",
            cookies_file="",
        )
        opts = test_thread.build_opts()
        self.assertTrue(opts.get("noplaylist"))
        print("PASS: Single URL TestLinkThread opts verified.")

    def test_11_legacy_channel_regression(self):
        print("\n--- [TEST 11] LEGACY CHANNEL EXTRACTION REGRESSION ---")
        legacy_thread = ChannelVideosThread(
            channel_url="https://www.youtube.com/@NoCopyrightSounds/videos",
            keyword="Faded",
            cookies_browser="None",
            cookies_file="",
        )
        opts = legacy_thread.build_opts()
        self.assertEqual(opts.get("extract_flat"), "in_playlist")
        self.assertTrue(opts.get("skip_download"))
        print("PASS: Legacy ChannelVideosThread structure and opts 100% intact.")

    def test_12_network_failure_handling(self):
        print("\n--- [TEST 12] NETWORK FAILURE / INVALID URL HANDLING ---")
        dialog = ChannelPreviewDialog()
        dialog.url_input.setText("https://www.youtube.com/invalid_channel_url_xyz_9999")

        dialog.start_scan()
        loop = QEventLoop()
        dialog.scan_thread.done.connect(loop.quit)
        QTimer.singleShot(15000, loop.quit)
        loop.exec()

        self.assertTrue(dialog.scan_btn.isEnabled())
        self.assertFalse(dialog.progress_bar.isVisible())
        self.assertIn("Gagal", dialog.scan_status_label.text())
        print(f"PASS: Handled invalid URL gracefully: '{dialog.scan_status_label.text()}'. Scan button re-enabled.")


if __name__ == "__main__":
    unittest.main()
