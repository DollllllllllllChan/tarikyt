import sys
import time
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication
from channel_preview import ChannelPreviewDialog, VideoPreviewTableModel, VideoPreviewFilterProxyModel

app = QApplication.instance() or QApplication(sys.argv)

print("\n=== STARTING RAPID SCROLL & FILTER STRESS TEST (2,000 ITEMS) ===")

dialog = ChannelPreviewDialog()
dialog.show()

# Generate 2,000 realistic items
items = [
    {
        "video_id": f"id_{i:04d}",
        "title": f"Video {i:04d} - " + ("Electro House Music [NCS]" if i % 3 == 0 else "Tutorial PySide6 Desktop GUI"),
        "url": f"https://www.youtube.com/watch?v=id_{i:04d}",
        "duration": 120 + i,
        "upload_date": "20260830",
        "thumbnail_url": f"https://example.com/thumb_{i}.jpg",
    }
    for i in range(1, 2001)
]

dialog.on_scan_finished(items, {"source": "Stress Test Channel", "total": 2000})
assert dialog.table_model.rowCount() == 2000
assert dialog.proxy_model.rowCount() == 2000

# 1. Rapid Scrolling Simulation
print("1. Simulating rapid vertical scrolling...")
vbar = dialog.table_view.verticalScrollBar()
for pos in [0, 500, 1200, 1900, 300, 1600, 0]:
    vbar.setValue(pos)
    app.processEvents()
print("   -> Rapid scrolling completed without freeze or crash.")

# 2. Rapid Keyword Changes
print("2. Simulating rapid filter keyword changes...")
keywords = ["Electro", "House", "Tutorial", "PySide6", "Desktop", "id_01", "id_05", "xyz_no_match", ""]
for kw in keywords:
    dialog.search_input.setText(kw)
    dialog.apply_search_filter()
    app.processEvents()
print("   -> Filter changes applied smoothly.")

# 3. Filter Mode Switching
print("3. Switching filter modes rapidly...")
modes = ["Contains", "Exact", "Starts With", "Regex", "Contains"]
for mode in modes:
    dialog.filter_combo.setCurrentText(mode)
    dialog.search_input.setText("Video 005" if mode != "Regex" else r"Video\s+00[1-9]0")
    dialog.apply_search_filter()
    app.processEvents()
print("   -> Filter mode switches verified.")

# 4. Rapid Resize Events
print("4. Simulating rapid dialog resize events...")
for w, h in [(1200, 800), (900, 600), (1400, 900), (1080, 700)]:
    dialog.resize(w, h)
    app.processEvents()
print("   -> Dialog resize handled safely.")

# 5. Selection and Sorting Stress
print("5. Testing sorting while filtered & selected...")
dialog.search_input.setText("")
dialog.apply_search_filter()
dialog.select_all_btn.click()
assert len(dialog.table_model.selected_ids) == 2000

dialog.table_view.sortByColumn(VideoPreviewTableModel.COL_TITLE, Qt.DescendingOrder)
app.processEvents()
assert len(dialog.table_model.selected_ids) == 2000

dialog.table_view.sortByColumn(VideoPreviewTableModel.COL_DURATION, Qt.AscendingOrder)
app.processEvents()
assert len(dialog.table_model.selected_ids) == 2000

# 6. Safe close
dialog.close()
app.processEvents()
print("   -> Dialog closed cleanly.")

print("=== ALL STRESS TESTS PASSED SUCCESSFULLY! ===")
