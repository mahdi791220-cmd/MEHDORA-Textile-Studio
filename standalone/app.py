import os
import sys
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
    )
except ImportError:
    from color_engine import (
        analyze_colors,
        apply_colorway,
        create_colorway_targets,
        extract_reference_palette,
    )
from PySide6.QtCore import Qt, QSize, QPoint
from PySide6.QtGui import (
    QAction, QColor, QIcon, QImage, QKeySequence, QPainter, QPen, QPixmap
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QColorDialog, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QListView, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QSplitter, QStatusBar, QToolBar,
    QVBoxLayout, QWidget
)


APP_NAME = "MEHDORA Textile Studio"
APP_VERSION = "0.4.0"

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
        self.source_path = None
        self.source_dpi = (300, 300)
        self.sources = []
        self.color_rows = []
        self.colorway_recipes = []
        self.customer_palette = []
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

        layout.addSpacing(12)
        layout.addWidget(QLabel("WORK HISTORY"))
        self.layer_list = QListWidget()
        layout.addWidget(self.layer_list)
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
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Open Textile Design",
            "",
            "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.webp)",
        )
        if not filename:
            return
        try:
            with Image.open(filename) as image:
                self.source_dpi = image.info.get("dpi", (300, 300))
                rgba = np.array(image.convert("RGBA"), dtype=np.uint8)
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
        self.colorway_list.clear()
        height, width, _ = rgba.shape
        self.statusBar().showMessage(
            f"{self.source_path.name} — {width} × {height}px"
        )

    def detect_colors(self):
        if self.current is None:
            QMessageBox.information(self, APP_NAME, "Open a design first.")
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self.sources = detect_dominant_colors(
                self.original, self.color_count.value()
            )
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
        return create_colorway_targets(self.sources, base, variant)

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
        preview_image = Image.fromarray(self.original, "RGBA")
        preview_image.thumbnail((150, 170), Image.Resampling.LANCZOS)
        preview_rgba = np.array(preview_image, dtype=np.uint8)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for index in range(count):
                targets = self.automatic_targets(index)
                preview = self.render_colorway(preview_rgba, targets)
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
            self.current = self.render_colorway(self.original, targets)
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
            result = self.render_colorway(self.original, targets)
        except Exception as error:
            QMessageBox.critical(self, APP_NAME, f"Colorway failed:\n{error}")
            return
        finally:
            QApplication.restoreOverrideCursor()
        name = f"Colorway {len(self.layers)}"
        self.current = result
        self.layers.append((name, result.copy()))
        self.refresh_layers()
        self.layer_list.setCurrentRow(len(self.layers) - 1)
        self.canvas.set_image(self.current)
        self.canvas.fit()
        self.statusBar().showMessage(f"{name} created — original preserved")

    def render_colorway(self, rgba, targets):
        if self.vivid_colors.isChecked():
            return apply_colorway(
                rgba,
                self.sources,
                targets,
                texture=1.0,
                chroma_detail=1.0,
                edge_softness=0.12,
                vibrance=1.16,
            )
        return apply_colorway(
            rgba,
            self.sources,
            targets,
            texture=1.0,
            chroma_detail=1.0,
            edge_softness=0.18,
            vibrance=1.03,
        )

    def refresh_layers(self):
        self.layer_list.clear()
        for name, _ in reversed(self.layers):
            self.layer_list.addItem(name)

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
        filename, selected = QFileDialog.getSaveFileName(
            self,
            "Save Colorway",
            f"{stem}-MEHDORA.png",
            "PNG (*.png);;TIFF (*.tif *.tiff);;JPEG (*.jpg *.jpeg)",
        )
        if not filename:
            return
        try:
            image = Image.fromarray(self.current, "RGBA")
            extension = Path(filename).suffix.lower()
            if extension in (".jpg", ".jpeg"):
                image = image.convert("RGB")
                image.save(filename, quality=96, dpi=self.source_dpi)
            else:
                image.save(filename, dpi=self.source_dpi)
        except Exception as error:
            QMessageBox.critical(self, APP_NAME, f"Could not save image:\n{error}")
            return
        self.statusBar().showMessage(f"Saved: {filename}")

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


def main():
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("ALI AHMAD TEXTILE")
    window = MehdoraWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
