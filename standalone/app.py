import os
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
from PySide6.QtCore import Qt, QSize, QPoint
from PySide6.QtGui import (
    QAction, QColor, QImage, QKeySequence, QPainter, QPen, QPixmap
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QColorDialog, QDialog, QDialogButtonBox,
    QDoubleSpinBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel,
    QListWidget, QMainWindow, QMessageBox, QPushButton, QScrollArea, QSpinBox,
    QSplitter, QStatusBar, QToolBar, QVBoxLayout, QWidget
)


APP_NAME = "MEHDORA Textile Studio"
APP_VERSION = "0.2.0"

DEFAULT_PALETTE = [
    "#173B5F", "#168C86", "#D2A33A", "#D66B73",
    "#71813B", "#EEE3CD", "#674C90", "#973C49",
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
    image = Image.fromarray(rgba, "RGBA")
    image.thumbnail((360, 360), Image.Resampling.LANCZOS)
    pixels = np.asarray(image, dtype=np.uint8).reshape(-1, 4)
    pixels = pixels[pixels[:, 3] > 24, :3]
    if len(pixels) == 0:
        return []
    if len(pixels) > 24000:
        step = max(1, len(pixels) // 24000)
        pixels = pixels[::step]
    unique = np.unique(pixels, axis=0)
    count = min(count, len(unique))
    centers = unique[np.linspace(0, len(unique) - 1, count).astype(int)].astype(
        np.float32
    )
    for _ in range(15):
        distances = ((pixels[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        labels = distances.argmin(axis=1)
        next_centers = centers.copy()
        for index in range(count):
            group = pixels[labels == index]
            if len(group):
                next_centers[index] = group.mean(axis=0)
        if np.allclose(centers, next_centers, atol=0.5):
            centers = next_centers
            break
        centers = next_centers
    distances = ((pixels[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
    labels = distances.argmin(axis=1)
    population = np.bincount(labels, minlength=count)
    order = np.argsort(population)[::-1]
    return [tuple(np.clip(centers[i], 0, 255).astype(np.uint8)) for i in order]


def apply_colorway(rgba, sources, targets):
    rgb = rgba[:, :, :3].astype(np.float32)
    alpha = rgba[:, :, 3:4].copy()
    source = np.asarray(sources, dtype=np.float32)
    target = np.asarray(targets, dtype=np.float32)
    flat = rgb.reshape(-1, 3)
    distances = ((flat[:, None, :] - source[None, :, :]) ** 2).sum(axis=2)
    labels = distances.argmin(axis=1)

    weights = np.asarray([0.2126, 0.7152, 0.0722], dtype=np.float32)
    source_luma = source @ weights
    pixel_luma = flat @ weights
    delta = pixel_luma - source_luma[labels]
    recolored = target[labels] + delta[:, None]
    recolored = np.clip(recolored, 0, 255).astype(np.uint8).reshape(rgb.shape)
    return np.concatenate((recolored, alpha), axis=2)


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
        self.canvas = Canvas()
        splitter.addWidget(self.canvas)
        splitter.addWidget(self.build_right_panel())
        splitter.setSizes([210, 950, 300])
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

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction("Zoom In", self.zoom_in, QKeySequence.StandardKey.ZoomIn)
        view_menu.addAction("Zoom Out", self.zoom_out, QKeySequence.StandardKey.ZoomOut)
        view_menu.addAction("Fit Canvas", self.fit_canvas, "Ctrl+0")

        color_menu = self.menuBar().addMenu("&Colorway")
        color_menu.addAction("Detect Colors", self.detect_colors)
        color_menu.addAction("Apply Colorway", self.make_colorway)
        color_menu.addAction("Restore Original", self.restore_original)

        image_menu = self.menuBar().insertMenu(color_menu.menuAction(), "&Image")
        image_size = QAction("Image Size…", self)
        image_size.setShortcut("Alt+Ctrl+I")
        image_size.triggered.connect(self.image_size)
        image_menu.addAction(image_size)

        tools_menu = self.menuBar().insertMenu(image_menu.menuAction(), "&Tools")
        remove_action = QAction("Remove Tool…", self)
        remove_action.setShortcut("J")
        remove_action.triggered.connect(self.remove_tool)
        tools_menu.addAction(remove_action)

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction("About MEHDORA", self.about)

    def build_toolbar(self):
        toolbar = QToolBar("Main")
        toolbar.setIconSize(QSize(20, 20))
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        toolbar.addAction("Open", self.open_image)
        toolbar.addAction("Save As", self.save_as)
        toolbar.addSeparator()
        toolbar.addAction("Image Size", self.image_size)
        toolbar.addAction("Remove Tool", self.remove_tool)
        toolbar.addSeparator()
        toolbar.addAction("Detect Colors", self.detect_colors)
        toolbar.addAction("Apply Colorway", self.make_colorway)
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
            ("Open Design", self.open_image),
            ("Image Size", self.image_size),
            ("Remove Tool", self.remove_tool),
            ("Detect Colors", self.detect_colors),
            ("Apply Colorway", self.make_colorway),
            ("Restore Original", self.restore_original),
            ("Save Output", self.save_as),
        ]:
            button = QPushButton(text)
            button.setMinimumHeight(38)
            button.clicked.connect(callback)
            layout.addWidget(button)
        layout.addStretch()
        version = QLabel(f"Independent Edition {APP_VERSION}\nOffline • Windows")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version.setStyleSheet("color:#777780;font-size:11px;padding:12px;")
        layout.addWidget(version)
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

        detect = QPushButton("Detect from Image")
        detect.clicked.connect(self.detect_colors)
        layout.addWidget(detect)
        apply_button = QPushButton("CREATE COLORWAY")
        apply_button.setMinimumHeight(42)
        apply_button.setStyleSheet(
            "QPushButton{background:#A66F2E;color:white;font-weight:800;"
            "border-radius:6px;} QPushButton:hover{background:#C08339;}"
        )
        apply_button.clicked.connect(self.make_colorway)
        layout.addWidget(apply_button)

        layout.addSpacing(12)
        layout.addWidget(QLabel("LAYERS"))
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
            result = apply_colorway(self.original, self.sources, targets)
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
