import os
import sys
import gc
import tempfile
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
try:
    from .color_engine import (
        analyze_colors,
        apply_colorway,
        create_colorway_targets,
        extract_reference_palette,
        prepare_colorway,
        render_prepared_colorway,
    )
except ImportError:
    from color_engine import (
        analyze_colors,
        apply_colorway,
        create_colorway_targets,
        extract_reference_palette,
        prepare_colorway,
        render_prepared_colorway,
    )
from PySide6.QtCore import (
    Qt, QSize, QPoint, QTimer, QObject, QThread, Signal, Slot
)
from PySide6.QtGui import (
    QAction, QColor, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QColorDialog, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QListView, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QScrollArea, QSpinBox, QSplitter, QStatusBar, QToolBar,
    QVBoxLayout, QWidget, QSplashScreen
)


APP_NAME = "MEHDORA Textile Studio"
APP_VERSION = "0.5.4"

DEFAULT_PALETTE = [
    "#173B5F", "#168C86", "#D2A33A", "#D66B73",
    "#71813B", "#EEE3CD", "#674C90", "#973C49",
]

COLORWAY_PALETTES = [
    ["#F1E6D2", "#173B5F", "#168C86", "#D2A33A", "#D66B73", "#71813B", "#674C90", "#973C49"],
    ["#F4EBDD", "#243A73", "#547AA5", "#D9A441", "#B84A62", "#65743A", "#8B6D9C", "#3A2D44"],
    ["#E8DDC8", "#6B1F2B", "#A3414A", "#D59A52", "#2E5C55", "#7A8C64", "#392F4A", "#C7775D"],
    ["#E5E1D5", "#123F46", "#1F7770", "#75A09A", "#C69A42", "#8B3C46", "#57416C", "#9B7653"],
    ["#EFE5D2", "#313B2C", "#697A3D", "#A7A36D", "#C98855", "#8D4145", "#3B566A", "#D5B66A"],
    ["#EDE3DA", "#222A4A", "#3C5A8A", "#718FB4", "#B9804A", "#A64B55", "#665179", "#D1A86A"],
    ["#F2E7D8", "#4A2635", "#8E3E55", "#C85D65", "#D3A04E", "#3D6A5B", "#6F8B69", "#34485D"],
    ["#E6E0D4", "#24272C", "#4A555F", "#7D8D91", "#B38851", "#7B3E45", "#3E665F", "#B0A071"],
    ["#F0E2C9", "#164C63", "#23859A", "#63AEB0", "#D19A45", "#C35F51", "#667B40", "#5C426C"],
    ["#E9DED1", "#3B2148", "#754B7D", "#A7799B", "#C9954C", "#9B4B47", "#42665B", "#74864A"],
]


@dataclass
class DocumentLayer:
    name: str
    rgba: np.ndarray
    visible: bool = True
    locked: bool = False
    opacity: int = 255
    blend_mode: str = "normal"
    top: int = 0
    left: int = 0


class LayeredTiffWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, filename, cache_directory):
        super().__init__()
        self.filename = str(filename)
        self.cache_directory = Path(cache_directory)

    @Slot()
    def run(self):
        try:
            from psdtags import (
                PsdChannelId,
                PsdLayerFlag,
                TiffImageSourceData,
            )

            image_source_data = TiffImageSourceData.fromtiff(self.filename)
            layers = []
            for index, source_layer in enumerate(image_source_data.layers):
                height, width = source_layer.shape
                cache_path = self.cache_directory / f"layer_{index:04d}.npy"
                pixels = np.lib.format.open_memmap(
                    cache_path,
                    mode="w+",
                    dtype=np.uint8,
                    shape=(height, width, 4),
                )
                pixels[:, :, :3] = 0
                pixels[:, :, 3] = 255
                for channel in source_layer.channels:
                    if channel.data is None:
                        continue
                    channel_id = channel.channelid
                    if PsdChannelId.CHANNEL0 <= channel_id <= PsdChannelId.CHANNEL2:
                        pixels[:, :, int(channel_id)] = channel.data
                    elif channel_id == PsdChannelId.TRANSPARENCY_MASK:
                        pixels[:, :, 3] = channel.data
                    channel.data = None
                pixels.flush()
                layers.append(
                    DocumentLayer(
                        name=source_layer.name,
                        rgba=pixels,
                        visible=not bool(
                            source_layer.flags & PsdLayerFlag.VISIBLE
                        ),
                        opacity=int(source_layer.opacity),
                        blend_mode=str(source_layer.blendmode),
                        top=int(source_layer.rectangle.top),
                        left=int(source_layer.rectangle.left),
                    )
                )
            if not layers:
                raise ValueError("No readable Photoshop layers were found.")
            self.finished.emit(layers)
        except Exception as error:
            self.failed.emit(str(error))


def resource_path(relative_path):
    """Resolve bundled PyInstaller assets and normal source-tree assets."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative_path
    return Path(__file__).resolve().parent / relative_path


def qimage_from_rgba(array):
    array = np.ascontiguousarray(array)
    height, width, _ = array.shape
    image = QImage(
        array.data, width, height, width * 4, QImage.Format.Format_RGBA8888
    )
    return image.copy()


def rgb_tuple(color):
    return (color.red(), color.green(), color.blue())


def detect_dominant_colors(rgba, count):
    return [cluster.rgb for cluster in analyze_colors(rgba, count)]


class ImageSizeDialog(QDialog):
    UNIT_FACTORS = {"Pixels": None, "Centimeters": 2.54, "Millimeters": 25.4, "Inches": 1.0}
    METHODS = {
        "Automatic": Image.Resampling.LANCZOS,
        "Bicubic": Image.Resampling.BICUBIC,
        "Bicubic Sharper": Image.Resampling.LANCZOS,
        "Bicubic Smoother": Image.Resampling.BICUBIC,
        "Nearest Neighbor": Image.Resampling.NEAREST,
        "Lanczos": Image.Resampling.LANCZOS,
    }

    def __init__(self, width, height, dpi, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Image Size")
        self.setMinimumWidth(470)
        self.original_width = int(width)
        self.original_height = int(height)
        self.ratio = width / max(1, height)
        self.width_px = int(width)
        self.height_px = int(height)
        self._updating = False
        self.previous_dpi = float(dpi[0] if isinstance(dpi, (tuple, list)) else dpi)
        if self.previous_dpi <= 0:
            self.previous_dpi = 300.0

        root = QVBoxLayout(self)
        header = QLabel("IMAGE SIZE")
        header.setStyleSheet("font-size:17px;font-weight:800;color:#D3A052;padding:6px;")
        root.addWidget(header)

        self.summary = QLabel()
        self.summary.setStyleSheet(
            "background:#1C1C20;border:1px solid #414148;border-radius:5px;"
            "padding:10px;color:#CFCFD5;"
        )
        root.addWidget(self.summary)

        form = QFormLayout()
        self.unit = QComboBox()
        self.unit.addItems(self.UNIT_FACTORS.keys())
        self.unit.currentTextChanged.connect(self.refresh_fields)
        form.addRow("Dimensions unit", self.unit)

        self.width = QDoubleSpinBox()
        self.width.setRange(0.01, 1_000_000)
        self.width.setDecimals(2)
        self.width.valueChanged.connect(self.width_changed)
        form.addRow("Width", self.width)

        self.height = QDoubleSpinBox()
        self.height.setRange(0.01, 1_000_000)
        self.height.setDecimals(2)
        self.height.valueChanged.connect(self.height_changed)
        form.addRow("Height", self.height)

        self.constrain = QCheckBox("Constrain proportions")
        self.constrain.setChecked(True)
        form.addRow("", self.constrain)

        self.resolution = QDoubleSpinBox()
        self.resolution.setRange(1, 2400)
        self.resolution.setDecimals(2)
        self.resolution.setSuffix(" pixels/inch")
        self.resolution.setValue(self.previous_dpi)
        self.resolution.valueChanged.connect(self.resolution_changed)
        form.addRow("Resolution", self.resolution)

        self.resample = QCheckBox("Resample image")
        self.resample.setChecked(True)
        self.resample.toggled.connect(self.resample_toggled)
        form.addRow("", self.resample)

        self.method = QComboBox()
        self.method.addItems(self.METHODS.keys())
        form.addRow("Resample method", self.method)
        root.addLayout(form)

        note = QLabel(
            "Turn Resample off to change print DPI without changing pixel dimensions."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#8D8D96;font-size:11px;padding:5px;")
        root.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.refresh_fields()

    def current_dpi(self):
        return max(1.0, self.resolution.value())

    def pixels_to_value(self, pixels):
        factor = self.UNIT_FACTORS[self.unit.currentText()]
        if factor is None:
            return float(pixels)
        return float(pixels) / self.current_dpi() * factor

    def value_to_pixels(self, value):
        factor = self.UNIT_FACTORS[self.unit.currentText()]
        if factor is None:
            return max(1, int(round(value)))
        return max(1, int(round(float(value) / factor * self.current_dpi())))

    def refresh_fields(self):
        self._updating = True
        is_pixels = self.unit.currentText() == "Pixels"
        decimals = 0 if is_pixels else 2
        suffix = " px" if is_pixels else {
            "Centimeters": " cm", "Millimeters": " mm", "Inches": " in"
        }[self.unit.currentText()]
        for field in (self.width, self.height):
            field.setDecimals(decimals)
            field.setSuffix(suffix)
        self.width.setValue(self.pixels_to_value(self.width_px))
        self.height.setValue(self.pixels_to_value(self.height_px))
        self._updating = False
        self.update_summary()

    def width_changed(self, value):
        if self._updating:
            return
        self.width_px = self.value_to_pixels(value)
        if self.constrain.isChecked():
            self.height_px = max(1, int(round(self.width_px / self.ratio)))
        self.refresh_fields()

    def height_changed(self, value):
        if self._updating:
            return
        self.height_px = self.value_to_pixels(value)
        if self.constrain.isChecked():
            self.width_px = max(1, int(round(self.height_px * self.ratio)))
        self.refresh_fields()

    def resolution_changed(self, dpi):
        if self._updating:
            return
        old_dpi = max(1.0, self.previous_dpi)
        if self.resample.isChecked() and self.unit.currentText() != "Pixels":
            scale = dpi / old_dpi
            self.width_px = max(1, int(round(self.width_px * scale)))
            self.height_px = max(1, int(round(self.height_px * scale)))
        self.previous_dpi = dpi
        self.refresh_fields()

    def resample_toggled(self, checked):
        self.width.setEnabled(checked)
        self.height.setEnabled(checked)
        self.method.setEnabled(checked)
        self.unit.setEnabled(checked)
        if not checked:
            self.width_px = self.original_width
            self.height_px = self.original_height
        self.refresh_fields()

    def update_summary(self):
        old_bytes = self.original_width * self.original_height * 4
        new_bytes = self.width_px * self.height_px * 4
        self.summary.setText(
            f"Pixel Dimensions: {self.width_px:,} × {self.height_px:,} px\n"
            f"Estimated memory: {new_bytes / 1048576:.1f} MB "
            f"(original {old_bytes / 1048576:.1f} MB)"
        )

    def result_values(self):
        return {
            "width": self.width_px,
            "height": self.height_px,
            "dpi": self.current_dpi(),
            "resample": self.resample.isChecked(),
            "method": self.METHODS[self.method.currentText()],
        }


class RemoveMaskCanvas(QLabel):
    def __init__(self, rgba, parent=None):
        super().__init__(parent)
        image = Image.fromarray(rgba, "RGBA")
        image.thumbnail((920, 620), Image.Resampling.LANCZOS)
        self.preview_rgba = np.array(image, dtype=np.uint8)
        self.base = QPixmap.fromImage(qimage_from_rgba(self.preview_rgba))
        self.mask = QImage(
            self.base.width(), self.base.height(), QImage.Format.Format_Grayscale8
        )
        self.mask.fill(0)
        self.overlay = QPixmap(self.base.size())
        self.overlay.fill(Qt.GlobalColor.transparent)
        self.brush_size = 32
        self.drawing = False
        self.last_point = QPoint()
        self.setFixedSize(self.base.size())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.refresh()

    def set_brush_size(self, size):
        self.brush_size = int(size)

    def clear_mask(self):
        self.mask.fill(0)
        self.overlay.fill(Qt.GlobalColor.transparent)
        self.refresh()

    def paint_segment(self, start, end):
        painter = QPainter(self.mask)
        pen = QPen(Qt.GlobalColor.white, self.brush_size)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawLine(start, end)
        painter.end()
        overlay_painter = QPainter(self.overlay)
        overlay_pen = QPen(QColor(225, 45, 55, 175), self.brush_size)
        overlay_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        overlay_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        overlay_painter.setPen(overlay_pen)
        overlay_painter.drawLine(start, end)
        overlay_painter.end()
        self.refresh()

    def refresh(self):
        composite = QPixmap(self.base)
        painter = QPainter(composite)
        painter.drawPixmap(0, 0, self.overlay)
        painter.end()
        self.setPixmap(composite)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drawing = True
            self.last_point = event.position().toPoint()
            self.paint_segment(self.last_point, self.last_point)

    def mouseMoveEvent(self, event):
        if self.drawing and event.buttons() & Qt.MouseButton.LeftButton:
            point = event.position().toPoint()
            self.paint_segment(self.last_point, point)
            self.last_point = point

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drawing = False

    def mask_array(self):
        image = self.mask.convertToFormat(QImage.Format.Format_Grayscale8)
        bits = image.bits()
        array = np.frombuffer(bits, dtype=np.uint8).reshape(
            image.height(), image.bytesPerLine()
        )
        return array[:, :image.width()].copy()


class RemoveToolDialog(QDialog):
    def __init__(self, rgba, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Remove Tool")
        self.source = rgba
        self.result = None
        self.setMinimumSize(760, 620)
        root = QVBoxLayout(self)

        header = QHBoxLayout()
        title = QLabel("REMOVE TOOL")
        title.setStyleSheet("font-size:17px;font-weight:800;color:#D3A052;")
        header.addWidget(title)
        header.addStretch()
        header.addWidget(QLabel("Brush Size"))
        self.brush = QSpinBox()
        self.brush.setRange(4, 200)
        self.brush.setValue(32)
        header.addWidget(self.brush)
        root.addLayout(header)

        instructions = QLabel(
            "Paint over the object in red. MEHDORA fills the selected area "
            "from its surrounding texture."
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet("color:#AFAFB7;padding:4px;")
        root.addWidget(instructions)

        scroll = QScrollArea()
        self.canvas = RemoveMaskCanvas(rgba)
        self.brush.valueChanged.connect(self.canvas.set_brush_size)
        scroll.setWidget(self.canvas)
        scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scroll.setWidgetResizable(False)
        root.addWidget(scroll, 1)

        controls = QHBoxLayout()
        clear = QPushButton("Clear Mask")
        clear.clicked.connect(self.canvas.clear_mask)
        controls.addWidget(clear)
        controls.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        controls.addWidget(cancel)
        remove = QPushButton("REMOVE")
        remove.setStyleSheet(
            "QPushButton{background:#A66F2E;color:white;font-weight:800;"
            "padding:8px 22px;border-radius:5px;}"
        )
        remove.clicked.connect(self.process)
        controls.addWidget(remove)
        root.addLayout(controls)

    def process(self):
        preview_mask = self.canvas.mask_array()
        if not np.any(preview_mask):
            QMessageBox.information(self, APP_NAME, "Paint over an object first.")
            return
        height, width, _ = self.source.shape
        mask = cv2.resize(
            preview_mask, (width, height), interpolation=cv2.INTER_NEAREST
        )
        mask = np.where(mask > 10, 255, 0).astype(np.uint8)
        rgb = self.source[:, :, :3]
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        radius = max(3, int(round(
            self.brush.value() * width / max(1, self.canvas.width()) * 0.16
        )))
        repaired = cv2.inpaint(bgr, mask, radius, cv2.INPAINT_TELEA)
        repaired_rgb = cv2.cvtColor(repaired, cv2.COLOR_BGR2RGB)
        self.result = np.dstack((repaired_rgb, self.source[:, :, 3]))
        self.accept()


class ColorButton(QPushButton):
    def __init__(self, color="#FFFFFF", editable=True):
        super().__init__()
        self._color = QColor(color)
        self.editable = editable
        self.setMinimumHeight(32)
        self.clicked.connect(self.choose)
        self.refresh()

    def color(self):
        return QColor(self._color)

    def set_color(self, color):
        self._color = QColor(color)
        self.refresh()

    def choose(self):
        if not self.editable:
            return
        selected = QColorDialog.getColor(self._color, self, "Choose Color")
        if selected.isValid():
            self._color = selected
            self.refresh()

    def refresh(self):
        name = self._color.name().upper()
        foreground = "#111111" if self._color.lightness() > 145 else "#FFFFFF"
        self.setText(name)
        self.setStyleSheet(
            "QPushButton{background:%s;color:%s;border:1px solid #5C5C62;"
            "border-radius:5px;font-weight:700;}" % (name, foreground)
        )


class Canvas(QScrollArea):
    def __init__(self):
        super().__init__()
        self.label = QLabel("Open a textile design to begin")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("color:#8D8D96;font-size:17px;")
        self.setWidget(self.label)
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.zoom = 1.0
        self.pixmap = None

    def set_image(self, rgba):
        self.pixmap = QPixmap.fromImage(qimage_from_rgba(rgba))
        self.zoom = 1.0
        self.render()

    def render(self):
        if not self.pixmap:
            return
        size = self.pixmap.size() * self.zoom
        self.label.setPixmap(
            self.pixmap.scaled(
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.label.resize(size)

    def zoom_in(self):
        self.zoom = min(8.0, self.zoom * 1.2)
        self.render()

    def zoom_out(self):
        self.zoom = max(0.08, self.zoom / 1.2)
        self.render()

    def fit(self):
        if not self.pixmap:
            return
        viewport = self.viewport().size()
        sx = max(1, viewport.width() - 30) / self.pixmap.width()
        sy = max(1, viewport.height() - 30) / self.pixmap.height()
        self.zoom = min(1.0, sx, sy)
        self.render()


class MehdoraWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — {APP_VERSION}")
        self.resize(1440, 900)
        self.original = None
        self.current = None
        self.layers = []
        self.document_layers = []
        self.document_is_layered = False
        self.imported_layer_count = 0
        self.source_path = None
        self.source_dpi = (300, 300)
        self.sources = []
        self.color_rows = []
        self.colorway_recipes = []
        self.customer_palette = []
        self.prepared_colorway = None
        self._tiff_thread = None
        self._tiff_worker = None
        self._layer_cache = None
        self.build_ui()

    def build_ui(self):
        self.setStyleSheet(
            """
            QMainWindow,QWidget{background:#242429;color:#E8E8EC;}
            QMenuBar,QMenu,QToolBar{background:#1D1D21;color:#E8E8EC;}
            QMenu::item:selected{background:#A66F2E;}
            QPushButton,QComboBox,QSpinBox{
                background:#34343A;border:1px solid #505058;border-radius:5px;
                padding:6px;color:#F2F2F4;
            }
            QPushButton:hover{border-color:#C38A43;}
            QListWidget{background:#1F1F24;border:1px solid #404047;}
            QScrollArea{background:#18181C;}
            QStatusBar{background:#1D1D21;color:#BEBEC6;}
            """
        )
        self.build_menu()
        self.build_toolbar()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.build_left_panel())
        splitter.addWidget(self.build_center_panel())
        splitter.addWidget(self.build_right_panel())
        splitter.setSizes([210, 1020, 330])
        self.setCentralWidget(splitter)

        status = QStatusBar()
        status.showMessage("Ready — Offline textile workspace")
        self.setStatusBar(status)

    def build_menu(self):
        file_menu = self.menuBar().addMenu("&File")
        open_action = QAction("Open Image…", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_image)
        file_menu.addAction(open_action)
        save_action = QAction("Save Colorway As…", self)
        save_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        save_action.triggered.connect(self.save_as)
        file_menu.addAction(save_action)
        file_menu.addAction("Save Layered PSD…", self.save_layered_psd_as)
        file_menu.addAction("Save Layered TIFF…", self.save_layered_tiff_as)
        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        design_menu = self.menuBar().addMenu("&Design")
        design_menu.addAction("Analyze Colors", self.detect_colors)
        design_menu.addAction("Import Customer Palette…", self.import_palette)
        design_menu.addAction("Generate Automatic Colorways", self.generate_auto_colorways)

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction("Zoom In", self.zoom_in, QKeySequence.StandardKey.ZoomIn)
        view_menu.addAction("Zoom Out", self.zoom_out, QKeySequence.StandardKey.ZoomOut)
        view_menu.addAction("Fit Canvas", self.fit_canvas, "Ctrl+0")

        color_menu = self.menuBar().addMenu("&Colorway")
        color_menu.addAction("Detect Colors", self.detect_colors)
        color_menu.addAction("Apply Colorway", self.make_colorway)
        color_menu.addAction("Generate Batch", self.generate_auto_colorways)
        color_menu.addAction("Save All Colorways…", self.save_all_colorways)
        color_menu.addAction("Export Selected…", self.save_as)

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction("About MEHDORA", self.about)

    def build_toolbar(self):
        toolbar = QToolBar("Main")
        toolbar.setIconSize(QSize(20, 20))
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        toolbar.addAction("Open", self.open_image)
        toolbar.addAction("Export", self.save_as)
        toolbar.addSeparator()
        toolbar.addAction("Analyze", self.detect_colors)
        toolbar.addAction("Import Palette", self.import_palette)
        toolbar.addAction("Auto Colorways", self.generate_auto_colorways)
        toolbar.addSeparator()
        toolbar.addAction("−", self.zoom_out)
        toolbar.addAction("+", self.zoom_in)
        toolbar.addAction("Fit", self.fit_canvas)

    def build_left_panel(self):
        panel = QWidget()
        panel.setMinimumWidth(190)
        panel.setMaximumWidth(260)
        layout = QVBoxLayout(panel)
        logo = QLabel("MEHDORA")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(
            "font-size:24px;font-weight:800;color:#D3A052;padding:16px 4px;"
        )
        layout.addWidget(logo)
        subtitle = QLabel("TEXTILE STUDIO")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("letter-spacing:3px;color:#A9A9B0;")
        layout.addWidget(subtitle)
        layout.addSpacing(18)
        for text, callback in [
            ("OPEN DESIGN", self.open_image),
            ("ANALYZE COLORS", self.detect_colors),
            ("IMPORT PALETTE", self.import_palette),
            ("AUTO COLORWAYS", self.generate_auto_colorways),
            ("SAVE ALL COLORWAYS", self.save_all_colorways),
            ("EXPORT SELECTED", self.save_as),
        ]:
            button = QPushButton(text)
            button.setMinimumHeight(38)
            button.clicked.connect(callback)
            layout.addWidget(button)
        layout.addStretch()
        version = QLabel(f"COLORWAY ENGINE {APP_VERSION}\nOffline • Windows")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version.setStyleSheet("color:#777780;font-size:11px;padding:12px;")
        layout.addWidget(version)
        return panel

    def build_center_panel(self):
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        self.canvas = Canvas()
        layout.addWidget(self.canvas, 4)
        strip_title = QLabel("AUTOMATIC COLORWAYS")
        strip_title.setStyleSheet(
            "font-weight:800;color:#D3A052;padding:7px 10px;"
            "border-top:1px solid #3F3F45;"
        )
        layout.addWidget(strip_title)
        self.colorway_list = QListWidget()
        self.colorway_list.setViewMode(QListView.ViewMode.IconMode)
        self.colorway_list.setFlow(QListView.Flow.LeftToRight)
        self.colorway_list.setWrapping(False)
        self.colorway_list.setResizeMode(QListView.ResizeMode.Adjust)
        self.colorway_list.setIconSize(QSize(110, 150))
        self.colorway_list.setGridSize(QSize(135, 185))
        self.colorway_list.setMaximumHeight(215)
        self.colorway_list.itemClicked.connect(self.open_colorway_recipe)
        layout.addWidget(self.colorway_list)
        return panel

    def build_right_panel(self):
        panel = QWidget()
        panel.setMinimumWidth(270)
        panel.setMaximumWidth(380)
        layout = QVBoxLayout(panel)

        heading = QLabel("COLOR SEPARATION")
        heading.setStyleSheet("font-weight:800;color:#D3A052;padding:8px 0;")
        layout.addWidget(heading)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Detected colors"))
        self.color_count = QSpinBox()
        self.color_count.setRange(2, 12)
        self.color_count.setValue(6)
        controls.addWidget(self.color_count)
        layout.addLayout(controls)

        self.palette_layout = QVBoxLayout()
        layout.addLayout(self.palette_layout)

        detect = QPushButton("ANALYZE DESIGN")
        detect.clicked.connect(self.detect_colors)
        layout.addWidget(detect)
        import_button = QPushButton("IMPORT CUSTOMER PALETTE")
        import_button.clicked.connect(self.import_palette)
        layout.addWidget(import_button)

        auto_row = QHBoxLayout()
        auto_row.addWidget(QLabel("Automatic outputs"))
        self.auto_count = QSpinBox()
        self.auto_count.setRange(1, 250)
        self.auto_count.setValue(12)
        auto_row.addWidget(self.auto_count)
        layout.addLayout(auto_row)

        apply_button = QPushButton("GENERATE COLORWAYS")
        apply_button.setMinimumHeight(42)
        apply_button.setStyleSheet(
            "QPushButton{background:#A66F2E;color:white;font-weight:800;"
            "border-radius:6px;} QPushButton:hover{background:#C08339;}"
        )
        apply_button.clicked.connect(self.generate_auto_colorways)
        layout.addWidget(apply_button)

        self.vivid_colors = QCheckBox("Vivid Colors — stronger print color")
        self.vivid_colors.setChecked(True)
        layout.addWidget(self.vivid_colors)

        self.preserve_brightness = QCheckBox("Preserve Original Brightness")
        self.preserve_brightness.setChecked(True)
        layout.addWidget(self.preserve_brightness)

        layout.addSpacing(12)
        self.layer_status = QLabel("NO DOCUMENT")
        self.layer_status.setStyleSheet(
            "font-weight:800;color:#D3A052;padding:5px 0;"
        )
        layout.addWidget(self.layer_status)
        self.layer_progress = QProgressBar()
        self.layer_progress.setRange(0, 0)
        self.layer_progress.setTextVisible(True)
        self.layer_progress.setFormat("Caching Photoshop layers safely…")
        self.layer_progress.hide()
        layout.addWidget(self.layer_progress)
        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel("Color target"))
        self.layer_scope = QComboBox()
        self.layer_scope.addItems(["Selected Layer", "All Visible Layers"])
        scope_row.addWidget(self.layer_scope)
        layout.addLayout(scope_row)
        layout.addWidget(QLabel("LAYERS"))
        self.layer_list = QListWidget()
        self.layer_list.setIconSize(QSize(34, 44))
        self.layer_list.itemChanged.connect(self.layer_visibility_changed)
        self.layer_list.currentItemChanged.connect(self.layer_selection_changed)
        self.layer_list.itemDoubleClicked.connect(self.solo_selected_layer)
        layout.addWidget(self.layer_list)
        layer_buttons = QHBoxLayout()
        toggle_layer = QPushButton("SHOW / HIDE")
        toggle_layer.clicked.connect(self.toggle_selected_layer)
        layer_buttons.addWidget(toggle_layer)
        solo_layer = QPushButton("SOLO")
        solo_layer.clicked.connect(self.solo_selected_layer)
        layer_buttons.addWidget(solo_layer)
        show_all = QPushButton("SHOW ALL")
        show_all.clicked.connect(self.show_all_layers)
        layer_buttons.addWidget(show_all)
        layout.addLayout(layer_buttons)
        save_psd = QPushButton("SAVE LAYERED PSD")
        save_psd.clicked.connect(self.save_layered_psd_as)
        layout.addWidget(save_psd)
        save_tiff = QPushButton("SAVE LAYERED TIFF")
        save_tiff.clicked.connect(self.save_layered_tiff_as)
        layout.addWidget(save_tiff)
        layout.addStretch()
        return panel

    def clear_palette(self):
        while self.palette_layout.count():
            item = self.palette_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            if item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()
        self.color_rows = []

    def open_image(self):
        if self._tiff_thread is not None and self._tiff_thread.isRunning():
            QMessageBox.information(
                self,
                APP_NAME,
                "Photoshop layers are still loading. Please wait.",
            )
            return
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Open Textile Design",
            "",
            "Design Files (*.psd *.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp)",
        )
        if not filename:
            return
        try:
            extension = Path(filename).suffix.lower()
            if extension == ".psd":
                self.release_layer_cache()
                rgba = self.open_layered_psd(filename)
            elif extension in (".tif", ".tiff") and self.tiff_has_layers(filename):
                self.open_layered_tiff_async(filename)
                return
            else:
                self.release_layer_cache()
                with Image.open(filename) as image:
                    self.source_dpi = image.info.get("dpi", (300, 300))
                    rgba = np.array(image.convert("RGBA"), dtype=np.uint8)
                self.document_layers = [
                    DocumentLayer("Background", rgba.copy())
                ]
                self.document_is_layered = False
                self.imported_layer_count = 0
        except Exception as error:
            QMessageBox.critical(self, APP_NAME, f"Could not open image:\n{error}")
            return
        self.source_path = Path(filename)
        self.original = rgba.copy()
        self.current = rgba.copy()
        self.layers = [("Original", self.original.copy())]
        self.refresh_layers()
        self.canvas.set_image(self.current)
        self.canvas.fit()
        self.clear_palette()
        self.sources = []
        self.colorway_recipes = []
        self.customer_palette = []
        self.prepared_colorway = None
        self.colorway_list.clear()
        height, width, _ = rgba.shape
        self.statusBar().showMessage(
            f"{self.source_path.name} — {width} × {height}px"
        )

    @staticmethod
    def tiff_has_layers(filename):
        with Image.open(filename) as image:
            return 37724 in image.tag_v2

    def open_layered_tiff_async(self, filename):
        try:
            from psdtags import TiffImageSourceData  # noqa: F401
        except ImportError:
            QMessageBox.critical(
                self,
                APP_NAME,
                "Layered TIFF support is not installed in this build.",
            )
            return
        try:
            with Image.open(filename) as image:
                self.source_dpi = image.info.get("dpi", (300, 300))
                rgba = np.array(image.convert("RGBA"), dtype=np.uint8)
        except Exception as error:
            QMessageBox.critical(self, APP_NAME, f"Could not open image:\n{error}")
            return

        self.release_layer_cache()
        self._layer_cache = tempfile.TemporaryDirectory(
            prefix="mehdora-layers-"
        )
        self.source_path = Path(filename)
        # Avoid three extra 350 MB copies for print-scale TIFF documents.
        self.original = rgba
        self.current = rgba
        self.layers = []
        self.document_layers = []
        self.document_is_layered = True
        self.imported_layer_count = 0
        self.clear_palette()
        self.sources = []
        self.colorway_recipes = []
        self.customer_palette = []
        self.prepared_colorway = None
        self.colorway_list.clear()
        self.layer_list.clear()
        self.layer_status.setText("LAYERED TIFF — LOADING LAYERS")
        self.layer_progress.show()
        self.canvas.set_image(self.current)
        self.canvas.fit()
        height, width, _ = rgba.shape
        self.statusBar().showMessage(
            f"{self.source_path.name} — {width} × {height}px — "
            "loading Photoshop layers in background"
        )

        thread = QThread(self)
        worker = LayeredTiffWorker(filename, self._layer_cache.name)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self.on_tiff_layers_loaded)
        worker.failed.connect(self.on_tiff_layers_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self.clear_tiff_loader)
        thread.finished.connect(thread.deleteLater)
        self._tiff_thread = thread
        self._tiff_worker = worker
        thread.start()

    @Slot(object)
    def on_tiff_layers_loaded(self, layers):
        self.document_layers = layers
        self.document_is_layered = True
        self.imported_layer_count = len(layers)
        self.layer_progress.hide()
        self.refresh_layers()
        self.statusBar().showMessage(
            f"{self.source_path.name} — {len(layers)} Photoshop layers ready"
        )

    @Slot(str)
    def on_tiff_layers_failed(self, message):
        self.layer_progress.hide()
        self.release_layer_cache()
        self.document_layers = [
            DocumentLayer("Background", self.original, visible=True)
        ]
        self.document_is_layered = False
        self.imported_layer_count = 0
        self.refresh_layers()
        QMessageBox.critical(
            self,
            APP_NAME,
            f"Could not load Photoshop layers:\n{message}",
        )

    @Slot()
    def clear_tiff_loader(self):
        self._tiff_worker = None
        self._tiff_thread = None

    def release_layer_cache(self):
        if self._layer_cache is None:
            return
        self.document_layers = []
        gc.collect()
        try:
            self._layer_cache.cleanup()
        except OSError:
            # Windows can briefly retain a mapped handle. TemporaryDirectory
            # will make another cleanup attempt when the object is finalized.
            pass
        self._layer_cache = None

    def open_layered_psd(self, filename):
        try:
            from psd_tools import PSDImage
        except ImportError as error:
            raise RuntimeError(
                "PSD support is not installed in this build."
            ) from error

        psd = PSDImage.open(filename)
        composite = psd.composite()
        if composite is None:
            raise ValueError("The PSD has no readable composite image.")
        rgba = np.array(composite.convert("RGBA"), dtype=np.uint8)
        height, width, _ = rgba.shape
        layers = []

        def collect(container, prefix="", parent_visible=True):
            for layer in container:
                visible = parent_visible and layer.is_visible()
                if layer.is_group():
                    collect(layer, f"{prefix}{layer.name} / ", visible)
                    continue
                rendered = layer.composite(layer_filter=lambda _: True)
                if rendered is None:
                    continue
                pixels = np.array(rendered.convert("RGBA"), dtype=np.uint8)
                full = np.zeros((height, width, 4), dtype=np.uint8)
                layer_left = int(layer.left)
                layer_top = int(layer.top)
                left = max(0, layer_left)
                top = max(0, layer_top)
                source_left = max(0, -layer_left)
                source_top = max(0, -layer_top)
                right = min(width, layer_left + pixels.shape[1])
                bottom = min(height, layer_top + pixels.shape[0])
                if right > left and bottom > top:
                    full[top:bottom, left:right] = pixels[
                        source_top : source_top + bottom - top,
                        source_left : source_left + right - left,
                    ]
                layers.append(
                    DocumentLayer(
                        name=f"{prefix}{layer.name}",
                        rgba=full,
                        visible=visible,
                        # Layer rendering already bakes masks, effects, opacity,
                        # and blend appearance into the pixel representation.
                        opacity=255,
                        blend_mode="normal",
                        top=0,
                        left=0,
                    )
                )

        collect(psd)
        if not layers:
            layers = [DocumentLayer("Background", rgba.copy())]
        self.document_layers = layers
        self.document_is_layered = len(layers) > 1
        self.imported_layer_count = len(layers)
        self.source_dpi = (300, 300)
        return rgba

    def detect_colors(self):
        if self.current is None:
            QMessageBox.information(self, APP_NAME, "Open a design first.")
            return
        analysis_image = self.active_color_source()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.sources = detect_dominant_colors(
                analysis_image, self.color_count.value()
            )
            self.prepared_colorway = None
        finally:
            QApplication.restoreOverrideCursor()
        self.clear_palette()
        for index, source in enumerate(self.sources):
            row = QHBoxLayout()
            source_button = ColorButton(QColor(*source), editable=False)
            target_button = ColorButton(DEFAULT_PALETTE[index % len(DEFAULT_PALETTE)])
            row.addWidget(source_button)
            row.addWidget(QLabel("→"))
            row.addWidget(target_button)
            self.palette_layout.addLayout(row)
            self.color_rows.append((source_button, target_button))
        self.statusBar().showMessage(f"Detected {len(self.sources)} dominant colors")

    def active_layer_index(self):
        item = self.layer_list.currentItem()
        if item is None:
            return None
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is None or not 0 <= index < len(self.document_layers):
            return None
        return index

    def active_color_source(self):
        if (
            not self.document_is_layered
            and len(self.document_layers) == 1
            and self.original is not None
        ):
            return self.original
        if (
            hasattr(self, "layer_scope")
            and self.layer_scope.currentIndex() == 0
        ):
            index = self.active_layer_index()
            if index is not None:
                return self.document_layers[index].rgba
        composed = self.compose_document_layers()
        return composed if composed is not None else self.original

    def import_palette(self):
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Import Customer Palette",
            "",
            "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp)",
        )
        if not filename:
            return
        if self.original is None:
            QMessageBox.information(self, APP_NAME, "Open a design first.")
            return
        try:
            with Image.open(filename) as image:
                palette_rgba = np.array(image.convert("RGBA"), dtype=np.uint8)
            if not self.sources:
                self.detect_colors()
            palette = extract_reference_palette(
                palette_rgba, max(2, len(self.sources))
            )
        except Exception as error:
            QMessageBox.critical(self, APP_NAME, f"Could not read palette:\n{error}")
            return
        if not palette:
            return
        for index, (_, target) in enumerate(self.color_rows):
            target.set_color(QColor(*palette[index % len(palette)]))
        self.customer_palette = list(palette)
        self.statusBar().showMessage(
            f"Customer palette imported — {len(palette)} colors"
        )

    def automatic_targets(self, index):
        if self.customer_palette:
            base = self.customer_palette
        else:
            selected = COLORWAY_PALETTES[index % len(COLORWAY_PALETTES)]
            base = [rgb_tuple(QColor(color)) for color in selected]
        variant = index if self.customer_palette else index // len(COLORWAY_PALETTES)
        return create_colorway_targets(
            self.sources,
            base,
            variant,
            preserve_lightness=0.68 if self.preserve_brightness.isChecked() else 0.0,
        )

    def generate_auto_colorways(self):
        if self.original is None:
            QMessageBox.information(self, APP_NAME, "Open a design first.")
            return
        if not self.sources:
            self.detect_colors()
            if not self.sources:
                return
        count = self.auto_count.value()
        self.colorway_list.clear()
        self.colorway_recipes = []
        color_source = self.active_color_source()
        preview_image = Image.fromarray(color_source, "RGBA")
        preview_image.thumbnail((150, 170), Image.Resampling.LANCZOS)
        preview_rgba = np.array(preview_image, dtype=np.uint8)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for index in range(count):
                targets = self.automatic_targets(index)
                preview = self.render_colorway(preview_rgba, targets, use_cache=False)
                pixmap = QPixmap.fromImage(qimage_from_rgba(preview))
                item = QListWidgetItem(
                    QIcon(pixmap), f"CW-{index + 1:03d}"
                )
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
                self.colorway_list.addItem(item)
                self.colorway_recipes.append(targets)
        finally:
            QApplication.restoreOverrideCursor()
        if self.colorway_list.count():
            self.colorway_list.setCurrentRow(0)
            self.open_colorway_recipe(self.colorway_list.item(0))
        self.statusBar().showMessage(
            f"{count} automatic colorways generated as lightweight recipes"
        )

    def open_colorway_recipe(self, item):
        row = self.colorway_list.row(item)
        if row < 0 or row >= len(self.colorway_recipes):
            return
        targets = self.colorway_recipes[row]
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.current = self.render_colorway(
                self.active_color_source(), targets
            )
        finally:
            QApplication.restoreOverrideCursor()
        for index, (_, target) in enumerate(self.color_rows):
            if index < len(targets):
                target.set_color(QColor(*targets[index]))
        self.canvas.set_image(self.current)
        self.canvas.fit()
        self.statusBar().showMessage(
            f"CW-{row + 1:03d} rendered at original dimensions and DPI"
        )

    def make_colorway(self):
        if self.original is None:
            QMessageBox.information(self, APP_NAME, "Open a design first.")
            return
        if not self.sources:
            self.detect_colors()
            if not self.sources:
                return
        targets = [rgb_tuple(target.color()) for _, target in self.color_rows]
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            result = self.render_colorway(self.active_color_source(), targets)
        except Exception as error:
            QMessageBox.critical(self, APP_NAME, f"Colorway failed:\n{error}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        source_index = self.active_layer_index()
        if self.layer_scope.currentIndex() == 0 and source_index is not None:
            source_name = self.document_layers[source_index].name
            name = f"{source_name} — Colorway"
        else:
            name = f"Colorway {len(self.layers)}"
        self.current = result
        self.layers.append((name, result.copy()))
        result_top = 0
        result_left = 0
        if self.layer_scope.currentIndex() == 0 and source_index is not None:
            result_top = self.document_layers[source_index].top
            result_left = self.document_layers[source_index].left
        self.document_layers.append(
            DocumentLayer(
                name,
                result.copy(),
                visible=True,
                top=result_top,
                left=result_left,
            )
        )
        self.document_is_layered = len(self.document_layers) > 1
        self.refresh_layers()
        self.layer_list.setCurrentRow(0)
        self.canvas.set_image(self.current)
        self.canvas.fit()
        self.statusBar().showMessage(f"{name} created — original preserved")

    def render_colorway(self, rgba, targets, use_cache=True):
        if use_cache and rgba is self.original:
            if self.prepared_colorway is None:
                self.statusBar().showMessage(
                    "Preparing fast colorway cache — this happens once per design"
                )
                QApplication.processEvents()
                self.prepared_colorway = prepare_colorway(
                    self.original, self.sources, edge_softness=0.12
                )
            return render_prepared_colorway(
                self.prepared_colorway,
                targets,
                texture=1.0,
                chroma_detail=0.42 if self.vivid_colors.isChecked() else 0.30,
                vibrance=1.16 if self.vivid_colors.isChecked() else 1.03,
            )
        if self.vivid_colors.isChecked():
            return apply_colorway(
                rgba,
                self.sources,
                targets,
                texture=1.0,
                chroma_detail=0.42,
                edge_softness=0.12,
                vibrance=1.16,
            )
        return apply_colorway(
            rgba,
            self.sources,
            targets,
            texture=1.0,
            chroma_detail=0.30,
            edge_softness=0.18,
            vibrance=1.03,
        )

    def save_all_colorways(self):
        if self.original is None:
            QMessageBox.information(self, APP_NAME, "Open a design first.")
            return
        if not self.colorway_recipes:
            self.generate_auto_colorways()
            if not self.colorway_recipes:
                return
        folder = QFileDialog.getExistingDirectory(
            self, "Choose Folder for All Colorways"
        )
        if not folder:
            return
        stem = self.source_path.stem if self.source_path else "MEHDORA"
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for index, targets in enumerate(self.colorway_recipes, 1):
                self.statusBar().showMessage(
                    f"Saving colorway {index} of {len(self.colorway_recipes)}…"
                )
                QApplication.processEvents()
                result = self.render_colorway(self.original, targets)
                destination = Path(folder) / f"{stem}-CW-{index:03d}.png"
                Image.fromarray(result, "RGBA").save(
                    destination, dpi=self.source_dpi
                )
        except Exception as error:
            QMessageBox.critical(
                self, APP_NAME, f"Could not save all colorways:\n{error}"
            )
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.statusBar().showMessage(
            f"Saved {len(self.colorway_recipes)} colorways to {folder}"
        )
        QMessageBox.information(
            self,
            APP_NAME,
            f"Saved {len(self.colorway_recipes)} colorways successfully.",
        )

    def refresh_layers(self):
        self.layer_list.blockSignals(True)
        self.layer_list.clear()
        for index in range(len(self.document_layers) - 1, -1, -1):
            layer = self.document_layers[index]
            thumb = Image.fromarray(layer.rgba, "RGBA")
            thumb.thumbnail((34, 44), Image.Resampling.LANCZOS)
            pixmap = QPixmap.fromImage(
                qimage_from_rgba(np.array(thumb, dtype=np.uint8))
            )
            state_icon = "👁" if layer.visible else "○"
            item = QListWidgetItem(
                QIcon(pixmap), f"{state_icon}  {layer.name}"
            )
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsSelectable
            )
            item.setCheckState(
                Qt.CheckState.Checked
                if layer.visible
                else Qt.CheckState.Unchecked
            )
            self.layer_list.addItem(item)
        self.layer_list.blockSignals(False)
        count = len(self.document_layers)
        if self.document_is_layered:
            self.layer_status.setText(f"LAYERED DOCUMENT — {count} LAYERS")
        elif count:
            self.layer_status.setText("FLATTENED IMAGE — 1 LAYER")
        else:
            self.layer_status.setText("NO DOCUMENT")
        if count and self.layer_list.currentRow() < 0:
            self.layer_list.setCurrentRow(0)

    def layer_visibility_changed(self, item):
        index = item.data(Qt.ItemDataRole.UserRole)
        if index is None or not 0 <= index < len(self.document_layers):
            return
        self.document_layers[index].visible = (
            item.checkState() == Qt.CheckState.Checked
        )
        state_icon = "👁" if self.document_layers[index].visible else "○"
        item.setText(f"{state_icon}  {self.document_layers[index].name}")
        self.current = self.compose_document_layers()
        self.canvas.set_image(self.current)
        self.statusBar().showMessage(
            f"{self.document_layers[index].name} visibility changed"
        )

    def toggle_selected_layer(self):
        item = self.layer_list.currentItem()
        if item is None:
            return
        item.setCheckState(
            Qt.CheckState.Unchecked
            if item.checkState() == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )

    def solo_selected_layer(self, *args):
        index = self.active_layer_index()
        if index is None:
            return
        for layer_index, layer in enumerate(self.document_layers):
            layer.visible = layer_index == index
        self.refresh_layers()
        self.select_layer_index(index)
        self.current = self.compose_document_layers()
        self.canvas.set_image(self.current)
        self.statusBar().showMessage(
            f"Solo layer: {self.document_layers[index].name}"
        )

    def show_all_layers(self):
        if not self.document_layers:
            return
        selected_index = self.active_layer_index()
        for layer in self.document_layers:
            layer.visible = True
        self.refresh_layers()
        if selected_index is not None:
            self.select_layer_index(selected_index)
        self.current = self.compose_document_layers()
        self.canvas.set_image(self.current)
        self.statusBar().showMessage("All layers are visible")

    def select_layer_index(self, document_index):
        for row in range(self.layer_list.count()):
            item = self.layer_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == document_index:
                self.layer_list.setCurrentRow(row)
                return

    def layer_selection_changed(self, current, previous):
        if current is None:
            return
        index = current.data(Qt.ItemDataRole.UserRole)
        if index is None or not 0 <= index < len(self.document_layers):
            return
        self.sources = []
        self.prepared_colorway = None
        self.colorway_recipes = []
        self.colorway_list.clear()
        self.clear_palette()
        self.statusBar().showMessage(
            f"Selected layer: {self.document_layers[index].name}"
        )

    def compose_document_layers(self):
        if not self.document_layers:
            return self.current
        if self.original is not None:
            height, width = self.original.shape[:2]
        else:
            height, width = self.document_layers[0].rgba.shape[:2]
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        for layer in self.document_layers:
            if not layer.visible:
                continue
            image = Image.fromarray(layer.rgba, "RGBA")
            if layer.opacity < 255:
                alpha = image.getchannel("A").point(
                    lambda value, opacity=layer.opacity: value * opacity // 255
                )
                image.putalpha(alpha)
            canvas.alpha_composite(image, (layer.left, layer.top))
        return np.array(canvas, dtype=np.uint8)

    def restore_original(self):
        if self.original is None:
            return
        self.current = self.original.copy()
        self.canvas.set_image(self.current)
        self.canvas.fit()
        self.statusBar().showMessage("Original image restored")

    def image_size(self):
        if self.current is None:
            QMessageBox.information(self, APP_NAME, "Open a design first.")
            return
        height, width, _ = self.current.shape
        dialog = ImageSizeDialog(width, height, self.source_dpi, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        values = dialog.result_values()
        self.source_dpi = (values["dpi"], values["dpi"])
        if not values["resample"]:
            self.statusBar().showMessage(
                f"Resolution changed to {values['dpi']:.2f} DPI — pixels unchanged"
            )
            return
        if values["width"] == width and values["height"] == height:
            self.statusBar().showMessage(
                f"Image remains {width} × {height}px at {values['dpi']:.2f} DPI"
            )
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            image = Image.fromarray(self.current, "RGBA")
            resized = image.resize(
                (values["width"], values["height"]), values["method"]
            )
            result = np.array(resized, dtype=np.uint8)
        except Exception as error:
            QMessageBox.critical(self, APP_NAME, f"Resize failed:\n{error}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        self.current = result
        self.layers.append(("Image Size", result.copy()))
        self.document_layers = [
            DocumentLayer("Resized Composite", result.copy())
        ]
        self.document_is_layered = False
        self.imported_layer_count = 0
        self.refresh_layers()
        self.canvas.set_image(self.current)
        self.canvas.fit()
        self.statusBar().showMessage(
            f"Resized to {values['width']:,} × {values['height']:,}px "
            f"at {values['dpi']:.2f} DPI"
        )

    def remove_tool(self):
        if self.current is None:
            QMessageBox.information(self, APP_NAME, "Open a design first.")
            return
        dialog = RemoveToolDialog(self.current, self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.result is None:
            return
        self.current = dialog.result
        self.layers.append(("Remove Tool", self.current.copy()))
        self.document_layers.append(
            DocumentLayer("Remove Tool", self.current.copy())
        )
        self.document_is_layered = len(self.document_layers) > 1
        self.refresh_layers()
        self.canvas.set_image(self.current)
        self.canvas.fit()
        self.statusBar().showMessage(
            "Remove Tool applied on a new layer — original preserved"
        )

    def save_as(self):
        if self.current is None:
            QMessageBox.information(self, APP_NAME, "Nothing to save.")
            return
        stem = self.source_path.stem if self.source_path else "MEHDORA-Colorway"
        layered = len(self.document_layers) > 1
        default_name = (
            f"{stem}-MEHDORA-LAYERED.psd"
            if layered
            else f"{stem}-MEHDORA.png"
        )
        filename, selected = QFileDialog.getSaveFileName(
            self,
            "Save Colorway",
            default_name,
            "Photoshop PSD — Preserve Layers (*.psd);;"
            "Photoshop Layered TIFF (*.tif *.tiff);;"
            "PNG — Flattened (*.png);;JPEG — Flattened (*.jpg *.jpeg)",
        )
        if not filename:
            return
        path = Path(filename)
        if selected.startswith("Photoshop PSD"):
            filename = str(path.with_suffix(".psd"))
        elif selected.startswith("Photoshop Layered TIFF"):
            filename = str(path.with_suffix(".tif"))
        elif selected.startswith("PNG"):
            filename = str(path.with_suffix(".png"))
        elif selected.startswith("JPEG"):
            filename = str(path.with_suffix(".jpg"))
        try:
            extension = Path(filename).suffix.lower()
            if extension == ".psd":
                self.save_layered_psd(filename)
            elif (
                extension in (".tif", ".tiff")
                and len(self.document_layers) > 1
            ):
                self.save_layered_tiff(filename)
            else:
                image = Image.fromarray(self.current, "RGBA")
                if extension in (".jpg", ".jpeg"):
                    image = image.convert("RGB")
                    image.save(filename, quality=96, dpi=self.source_dpi)
                else:
                    image.save(filename, dpi=self.source_dpi)
        except Exception as error:
            QMessageBox.critical(self, APP_NAME, f"Could not save image:\n{error}")
            return
        self.statusBar().showMessage(f"Saved: {filename}")

    def save_layered_psd_as(self):
        if not self.document_layers:
            QMessageBox.information(self, APP_NAME, "No layers are ready to save.")
            return
        stem = self.source_path.stem if self.source_path else "MEHDORA"
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Layered Photoshop Document",
            f"{stem}-MEHDORA-LAYERED.psd",
            "Photoshop PSD (*.psd)",
        )
        if not filename:
            return
        filename = str(Path(filename).with_suffix(".psd"))
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.save_layered_psd(filename)
        except Exception as error:
            QMessageBox.critical(
                self, APP_NAME, f"Could not save layered PSD:\n{error}"
            )
            return
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(
            self, APP_NAME, f"Layered PSD saved successfully:\n{filename}"
        )

    def save_layered_tiff_as(self):
        if not self.document_layers:
            QMessageBox.information(self, APP_NAME, "No layers are ready to save.")
            return
        stem = self.source_path.stem if self.source_path else "MEHDORA"
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Photoshop Layered TIFF",
            f"{stem}-MEHDORA-LAYERED.tif",
            "Photoshop Layered TIFF (*.tif *.tiff)",
        )
        if not filename:
            return
        filename = str(Path(filename).with_suffix(".tif"))
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.save_layered_tiff(filename)
        except Exception as error:
            QMessageBox.critical(
                self, APP_NAME, f"Could not save layered TIFF:\n{error}"
            )
            return
        finally:
            QApplication.restoreOverrideCursor()
        QMessageBox.information(
            self, APP_NAME, f"Layered TIFF saved successfully:\n{filename}"
        )

    def save_layered_psd(self, filename):
        try:
            from psd_tools import PSDImage
        except ImportError as error:
            raise RuntimeError(
                "PSD support is not installed in this build."
            ) from error
        if not self.document_layers:
            raise ValueError("There are no layers to save.")
        if self.original is not None:
            height, width = self.original.shape[:2]
        else:
            height, width = self.document_layers[0].rgba.shape[:2]
        preserve_source = (
            self.source_path is not None
            and self.source_path.suffix.lower() == ".psd"
            and self.source_path.exists()
            and self.imported_layer_count > 0
        )
        if preserve_source:
            psd = PSDImage.open(self.source_path)
            original_leaves = []

            def collect_leaves(container):
                for source_layer in container:
                    if source_layer.is_group():
                        collect_leaves(source_layer)
                    else:
                        original_leaves.append(source_layer)

            collect_leaves(psd)
            for index, source_layer in enumerate(original_leaves):
                if index < self.imported_layer_count:
                    source_layer.visible = self.document_layers[index].visible
            layers_to_add = self.document_layers[self.imported_layer_count :]
        else:
            psd = PSDImage.new(mode="RGB", size=(width, height), depth=8)
            layers_to_add = self.document_layers

        for layer in layers_to_add:
            pixel_layer = psd.create_pixel_layer(
                Image.fromarray(layer.rgba, "RGBA"),
                name=layer.name,
                top=layer.top,
                left=layer.left,
                opacity=max(0, min(255, int(layer.opacity))),
            )
            pixel_layer.visible = layer.visible
        psd.save(filename)

    def save_layered_tiff(self, filename):
        try:
            import tifffile
            from psdtags import (
                PsdBlendMode,
                PsdChannel,
                PsdChannelId,
                PsdCompressionType,
                PsdFormat,
                PsdKey,
                PsdLayer,
                PsdLayerFlag,
                PsdLayerMask,
                PsdLayers,
                PsdRectangle,
                PsdString,
                PsdUserMask,
                TiffImageResources,
                TiffImageSourceData,
            )
        except ImportError as error:
            raise RuntimeError(
                "Layered TIFF support is not installed in this build."
            ) from error

        def make_psd_layer(layer):
            rgba = np.ascontiguousarray(layer.rgba, dtype=np.uint8)
            flags = PsdLayerFlag.PHOTOSHOP5
            if not layer.visible:
                flags |= PsdLayerFlag.VISIBLE
            return PsdLayer(
                name=layer.name,
                rectangle=PsdRectangle(
                    layer.top,
                    layer.left,
                    layer.top + rgba.shape[0],
                    layer.left + rgba.shape[1],
                ),
                channels=[
                    PsdChannel(
                        channelid=PsdChannelId.TRANSPARENCY_MASK,
                        compression=PsdCompressionType.ZIP,
                        data=rgba[:, :, 3],
                    ),
                    PsdChannel(
                        channelid=PsdChannelId.CHANNEL0,
                        compression=PsdCompressionType.ZIP,
                        data=rgba[:, :, 0],
                    ),
                    PsdChannel(
                        channelid=PsdChannelId.CHANNEL1,
                        compression=PsdCompressionType.ZIP,
                        data=rgba[:, :, 1],
                    ),
                    PsdChannel(
                        channelid=PsdChannelId.CHANNEL2,
                        compression=PsdCompressionType.ZIP,
                        data=rgba[:, :, 2],
                    ),
                ],
                mask=PsdLayerMask(),
                opacity=max(0, min(255, int(layer.opacity))),
                blendmode=PsdBlendMode.NORMAL,
                flags=flags,
                info=[PsdString(PsdKey.UNICODE_LAYER_NAME, layer.name)],
            )

        preserve_source = (
            self.source_path is not None
            and self.source_path.suffix.lower() in (".tif", ".tiff")
            and self.source_path.exists()
            and self.imported_layer_count > 0
        )
        resources = None
        if preserve_source:
            image_source_data = TiffImageSourceData.fromtiff(self.source_path)
            for index, source_layer in enumerate(image_source_data.layers):
                if index >= self.imported_layer_count:
                    break
                if self.document_layers[index].visible:
                    source_layer.flags &= ~PsdLayerFlag.VISIBLE
                else:
                    source_layer.flags |= PsdLayerFlag.VISIBLE
            image_source_data.layers.layers.extend(
                make_psd_layer(layer)
                for layer in self.document_layers[self.imported_layer_count :]
            )
            try:
                resources = TiffImageResources.fromtiff(self.source_path)
            except Exception:
                resources = None
        else:
            image_source_data = TiffImageSourceData(
                name=Path(filename).name,
                psdformat=PsdFormat.LE32BIT,
                layers=PsdLayers(
                    key=PsdKey.LAYER,
                    has_transparency=True,
                    layers=[
                        make_psd_layer(layer)
                        for layer in self.document_layers
                    ],
                ),
                usermask=PsdUserMask(),
            )

        composite = self.compose_document_layers()
        extras = [image_source_data.tifftag(maxworkers=4)]
        if resources is not None:
            extras.append(resources.tifftag())
        tifffile.imwrite(
            filename,
            composite[:, :, :3],
            photometric="rgb",
            compression="adobe_deflate",
            resolution=self.source_dpi,
            resolutionunit="inch",
            metadata=None,
            extratags=extras,
        )

    def zoom_in(self):
        self.canvas.zoom_in()

    def zoom_out(self):
        self.canvas.zoom_out()

    def fit_canvas(self):
        self.canvas.fit()

    def about(self):
        QMessageBox.about(
            self,
            "About MEHDORA",
            f"<h2>{APP_NAME}</h2><p>Version {APP_VERSION}</p>"
            "<p>Independent offline textile colorway software.</p>"
            "<p>ALI AHMAD TEXTILE</p>",
        )

    def closeEvent(self, event):
        if self._tiff_thread is not None and self._tiff_thread.isRunning():
            QMessageBox.information(
                self,
                APP_NAME,
                "Photoshop layers are still loading. Please wait before closing.",
            )
            event.ignore()
            return
        self.release_layer_cache()
        super().closeEvent(event)


def main():
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("ALI AHMAD TEXTILE")
    icon = QIcon(str(resource_path("assets/mehdora.ico")))
    app.setWindowIcon(icon)

    splash_pixmap = QPixmap(str(resource_path("assets/mehdora_splash.png")))
    if not splash_pixmap.isNull():
        splash_pixmap = splash_pixmap.scaled(
            1100,
            620,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        splash = QSplashScreen(
            splash_pixmap, Qt.WindowType.WindowStaysOnTopHint
        )
        splash.show()
        app.processEvents()
    else:
        splash = None

    window = MehdoraWindow()
    window.setWindowIcon(icon)

    def show_main_window():
        window.show()
        if splash is not None:
            splash.finish(window)

    QTimer.singleShot(1800 if splash is not None else 0, show_main_window)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
