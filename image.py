import os
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from PyQt6.QtCore import QThread, pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, 
    QPushButton, QVBoxLayout, QHBoxLayout, QFileDialog,
    QProgressBar, QTextEdit, QMessageBox
)
from PIL import Image

VALID_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".gif")

class DropArea(QLabel):
    """A custom widget that accepts dragged and dropped folders, zip files, or images."""
    path_dropped = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setText("📂 Drag & Drop your Folder, ZIP file, or Images here\n(Or click Browse below)")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("""
            QLabel {
                border: 2px dashed #a0aec0;
                border-radius: 8px;
                background-color: #f7fafc;
                color: #4a5568;
                font-size: 14px;
                font-weight: bold;
                padding: 30px;
            }
            QLabel:hover {
                background-color: #edf2f7;
                border-color: #3182ce;
            }
        """)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            self.path_dropped.emit(file_path)


class ConversionWorker(QThread):
    progress_update = pyqtSignal(int, int, str)
    log_message = pyqtSignal(str)
    finished = pyqtSignal(int, int, float)

    def __init__(self, target_path):
        super().__init__()
        self.target_path = target_path

    def run(self):
        start_time = time.time()
        output_dir = os.path.join(os.path.dirname(self.target_path), "converted_dib")
        os.makedirs(output_dir, exist_ok=True)
        
        image_paths = []

        # Case 1: Dropped a Zip file
        if os.path.isfile(self.target_path) and self.target_path.lower().endswith(".zip"):
            self.log_message.emit("📦 Extracting ZIP file...")
            extract_dir = os.path.join(output_dir, "_temp_extracted")
            os.makedirs(extract_dir, exist_ok=True)
            try:
                with zipfile.ZipFile(self.target_path, 'r') as zip_ref:
                    zip_ref.extractall(extract_dir)
                for root, _, files in os.walk(extract_dir):
                    for f in files:
                        if f.lower().endswith(VALID_EXTENSIONS):
                            image_paths.append((os.path.join(root, f), f))
            except Exception as e:
                self.log_message.emit(f"❌ Failed to extract ZIP: {e}")
                self.finished.emit(0, 0, 0.0)
                return

        # Case 2: Dropped a Folder
        elif os.path.isdir(self.target_path):
            for root, _, files in os.walk(self.target_path):
                for f in files:
                    if f.lower().endswith(VALID_EXTENSIONS):
                        image_paths.append((os.path.join(root, f), f))

        # Case 3: Dropped a Single Image
        elif os.path.isfile(self.target_path) and self.target_path.lower().endswith(VALID_EXTENSIONS):
            f = os.path.basename(self.target_path)
            image_paths.append((self.target_path, f))

        total_files = len(image_paths)
        if total_files == 0:
            self.log_message.emit("❌ No valid images found in the selected path.")
            self.finished.emit(0, 0, 0.0)
            return

        self.log_message.emit(f"🚀 Found {total_files} images. Converting to 300 DPI DIB...")

        success_count, fail_count = 0, 0
        max_workers = os.cpu_count() or 4

        def convert_file(item):
            input_path, filename = item
            try:
                base_name = os.path.splitext(filename)[0]
                output_path = os.path.join(output_dir, f"{base_name}.dib")
                
                with Image.open(input_path) as img:
                    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                        img = img.convert("RGB")
                    # Save as BMP/DIB container with 300 DPI resolution metadata
                    img.save(output_path, "BMP", dpi=(300, 300))
                return filename, True, None
            except Exception as e:
                return filename, False, str(e)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(convert_file, item): item for item in image_paths}
            processed = 0
            
            for future in as_completed(futures):
                filename, success, error = future.result()
                processed += 1
                if success:
                    success_count += 1
                    self.log_message.emit(f"✅ Converted: {filename} -> 300 DPI")
                else:
                    fail_count += 1
                    self.log_message.emit(f"⚠️ Failed {filename}: {error}")
                
                self.progress_update.emit(processed, total_files, filename)

        elapsed = time.time() - start_time
        self.finished.emit(success_count, fail_count, elapsed)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Bulk DIB & 300 DPI Converter")
        self.setMinimumSize(600, 500)
        self.selected_path = ""
        self.init_ui()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(12)

        # Drag & Drop Zone
        self.drop_area = DropArea()
        self.drop_area.path_dropped.connect(self.handle_path_selected)
        layout.addWidget(self.drop_area)

        # Browse Button alternative
        btn_layout = QHBoxLayout()
        self.path_label = QLabel("No folder or file selected.")
        self.path_label.setStyleSheet("color: #718096; font-style: italic;")
        browse_btn = QPushButton("Browse Folder / ZIP...")
        browse_btn.clicked.connect(self.browse_path)
        btn_layout.addWidget(self.path_label, 1)
        btn_layout.addWidget(browse_btn)
        layout.addLayout(btn_layout)

        # Start Conversion Button
        self.start_btn = QPushButton("Start Conversion (300 DPI)")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #3182ce;
                color: white;
                font-weight: bold;
                font-size: 14px;
                padding: 12px;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: #2b6cb0;
            }
            QPushButton:disabled {
                background-color: #cbd5e0;
            }
        """)
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.start_conversion)
        layout.addWidget(self.start_btn)

        # Progress Bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        # Console Log
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setStyleSheet("background-color: #1a202c; color: #48bb78; font-family: monospace; font-size: 11px; border-radius: 4px;")
        layout.addWidget(self.console)

    def browse_path(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Zip or Image", "", "Archives & Images (*.zip *.png *.jpg *.jpeg *.bmp)")
        if not path:
            path = QFileDialog.getExistingDirectory(self, "Select Image Folder")
        if path:
            self.handle_path_selected(path)

    def handle_path_selected(self, path):
        self.selected_path = path
        name = os.path.basename(path)
        self.path_label.setText(f"Selected: {name}")
        self.drop_area.setText(f"📁 Ready: {name}\n(Drop another or click Start)")
        self.start_btn.setEnabled(True)

    def start_conversion(self):
        if not self.selected_path:
            return

        self.start_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.console.clear()

        self.worker = ConversionWorker(self.selected_path)
        self.worker.progress_update.connect(lambda cur, tot, _: self.progress_bar.setValue(int((cur/tot)*100)))
        self.worker.log_message.connect(self.console.append)
        self.worker.finished.connect(self.conversion_finished)
        self.worker.start()

    def conversion_finished(self, success, fail, elapsed):
        self.start_btn.setEnabled(True)
        self.console.append(f"\n🎉 Done! Success: {success} | Failed: {fail} | Time: {elapsed:.2f}s")
        QMessageBox.information(self, "Complete", f"Successfully converted {success} images to 300 DPI DIB!")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
