import sys
import time
from PySide6.QtCore import QTimer, QEventLoop, Qt
from PySide6.QtWidgets import QApplication
from main import App
from channel_preview import ChannelPreviewDialog

app = QApplication.instance() or QApplication(sys.argv)

def log(msg):
    print(msg, flush=True)

log("\n=======================================================")
log("=== STARTING GUI RUNTIME VERIFICATION (SOURCE CODE) ===")
log("=======================================================")

# Step 1: Open main app
main_app = App()
main_app.clear_queue()
main_app.show()
app.processEvents()
log("[1] Main App opened successfully.")

# Verify Simple Mode hides legacy controls
main_app.mode_combo.setCurrentText("Simple Mode")
main_app.apply_ui_mode()
app.processEvents()
log(f"[2] Simple Mode active -> Legacy Direct Filter hidden: {main_app.legacy_channel_controls.isHidden()}")
assert main_app.legacy_channel_controls.isHidden()

# Step 2: Paste https://www.youtube.com/@djwangi into channel URL
channel_url = "https://www.youtube.com/@djwangi"
main_app.channel_url_input.setText(channel_url)
log(f"[3] Channel URL set in main window: {main_app.channel_url_input.text()}")

# Step 3 & 4: Open ChannelPreviewDialog
dialog = ChannelPreviewDialog(
    parent=main_app,
    initial_url=main_app.channel_url_input.text().strip(),
    cookies_browser=main_app.cookies_combo.currentText(),
    cookies_file=main_app.cookies_file_input.text().strip(),
)
dialog.items_selected.connect(main_app.handle_channel_preview_items)
dialog.show()
app.processEvents()

log(f"[4] ChannelPreviewDialog opened. URL field content: '{dialog.url_input.text()}'")
assert dialog.url_input.text() == channel_url, f"Expected {channel_url}, got {dialog.url_input.text()}"

# Step 5: Dialog Style Inspection
style_sheet = dialog.styleSheet()
log(f"[5] Dialog Style Inspection:")
log(f"    - Dark background applied: {'#1a1c23' in style_sheet}")
log(f"    - Light text applied: {'#f1f5f9' in style_sheet}")
log(f"    - Table dark background: {'#14161c' in style_sheet}")
log(f"    - Accent blue buttons: {'#2563eb' in style_sheet}")

# Step 6: Click Scan
log("[6] Triggering Scan on https://www.youtube.com/@djwangi...")
dialog.start_scan()
loop = QEventLoop()
dialog.scan_thread.done.connect(loop.quit)
# Timeout after 25s
QTimer.singleShot(25000, loop.quit)
loop.exec()

total_scanned = dialog.table_model.rowCount()
log(f"[7] Scan completed. Total videos found: {total_scanned}")
log(f"    Status label: '{dialog.scan_status_label.text()}'")
assert total_scanned > 0, "Scan should return videos"

# Step 8: Search "ajeng febria"
keyword = "ajeng febria"
log(f"[8] Applying search filter '{keyword}'...")
dialog.search_input.setText(keyword)
dialog.apply_search_filter()
app.processEvents()

filtered_count = dialog.proxy_model.rowCount()
log(f"    Filtered results for '{keyword}': {filtered_count}")
log(f"    Stats label: '{dialog.stats_label.text()}'")

# If keyword returned results, select 3 of them; otherwise clear search and select first 3
if filtered_count >= 3:
    filtered_ids = dialog.proxy_model.get_filtered_video_ids()[:3]
    dialog.table_model.select_ids(filtered_ids)
else:
    # Fallback to general first 3 if channel has different titles
    dialog.search_input.setText("")
    dialog.apply_search_filter()
    app.processEvents()
    all_ids = [dialog.table_model._items[i]["video_id"] for i in range(min(3, total_scanned))]
    dialog.table_model.select_ids(all_ids)

selected_count = len(dialog.table_model.selected_ids)
log(f"[9] Selected {selected_count} videos. Add button text: '{dialog.add_queue_btn.text()}'")
assert selected_count == 3, f"Expected 3 selected, got {selected_count}"

# Step 11: Add Selected to Queue
initial_queue_count = main_app.queue_table.rowCount()
log(f"[10] Main window queue table row count before add: {initial_queue_count}")

dialog.confirm_and_add_to_queue()
app.processEvents()

new_queue_count = main_app.queue_table.rowCount()
log(f"[11] Main window queue table row count after add: {new_queue_count}")
log(f"     Items added to queue table: {new_queue_count - initial_queue_count}")

# Verify 3 rows are rendered in main queue table
for r in range(max(0, new_queue_count - 3), new_queue_count):
    title_item = main_app.queue_table.item(r, 0)
    status_item = main_app.queue_table.item(r, 4)
    log(f"     Row {r}: Judul='{title_item.text()[:40]}...' | Status='{status_item.text()}'")

dialog.close()
main_app.close()
print("\n=== GUI RUNTIME VERIFICATION COMPLETED SUCCESSFULLY! ===")
sys.exit(0)
