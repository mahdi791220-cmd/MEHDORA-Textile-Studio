from krita import Krita, DockWidget, DockWidgetFactory, DockWidgetFactoryBase
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QMessageBox, QColorDialog, QProgressBar
)


DEFAULT_TARGETS = [
    QColor("#163A5F"), QColor("#1E8C87"), QColor("#D5A43A"),
    QColor("#D96C75"), QColor("#6B7F3A"), QColor("#EEE5D2"),
    QColor("#6A4C93"), QColor("#9A3B46")
]


def distance2(a, b):
    dr = a[0] - b[0]
    dg = a[1] - b[1]
    db = a[2] - b[2]
    return dr * dr + dg * dg + db * db


def luminance(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def kmeans(points, count, rounds=12):
    if not points:
        return []
    unique = list(dict.fromkeys(points))
    count = min(count, len(unique))
    centers = [unique[(i * len(unique)) // count] for i in range(count)]
    for _ in range(rounds):
        sums = [[0, 0, 0, 0] for _ in centers]
        for point in points:
            index = min(range(len(centers)), key=lambda i: distance2(point, centers[i]))
            row = sums[index]
            row[0] += point[0]
            row[1] += point[1]
            row[2] += point[2]
            row[3] += 1
        changed = False
        next_centers = []
        for old, row in zip(centers, sums):
            new = old if row[3] == 0 else (
                row[0] // row[3], row[1] // row[3], row[2] // row[3]
            )
            changed = changed or new != old
            next_centers.append(new)
        centers = next_centers
        if not changed:
            break
    population = [0] * len(centers)
    for point in points:
        index = min(range(len(centers)), key=lambda i: distance2(point, centers[i]))
        population[index] += 1
    return [item[0] for item in sorted(
        zip(centers, population), key=lambda item: item[1], reverse=True
    )]


class ColorButton(QPushButton):
    def __init__(self, color, editable=True):
        super().__init__()
        self.color = QColor(color)
        self.editable = editable
        self.setFixedHeight(28)
        self.clicked.connect(self.choose)
        self.refresh()

    def choose(self):
        if not self.editable:
            return
        selected = QColorDialog.getColor(self.color, self, "Choose target color")
        if selected.isValid():
            self.color = selected
            self.refresh()

    def set_color(self, color):
        self.color = QColor(color)
        self.refresh()

    def refresh(self):
        text = self.color.name().upper()
        foreground = "#111111" if self.color.lightness() > 145 else "#FFFFFF"
        self.setText(text)
        self.setStyleSheet(
            "QPushButton {background:%s;color:%s;border:1px solid #555;"
            "border-radius:4px;font-weight:600;}" % (text, foreground)
        )


class MehdoraColorLab(DockWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MEHDORA Color Lab")
        self.centers = []
        self.rows = []

        root = QWidget(self)
        layout = QVBoxLayout(root)

        title = QLabel("TEXTILE COLOR SEPARATION")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-weight:700;font-size:14px;padding:8px;")
        layout.addWidget(title)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Colors:"))
        self.count = QSpinBox()
        self.count.setRange(2, 8)
        self.count.setValue(6)
        controls.addWidget(self.count)
        self.detect_button = QPushButton("Detect Colors")
        self.detect_button.clicked.connect(self.detect_colors)
        controls.addWidget(self.detect_button)
        layout.addLayout(controls)

        self.colors_layout = QVBoxLayout()
        layout.addLayout(self.colors_layout)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.apply_button = QPushButton("Apply Colorway")
        self.apply_button.setStyleSheet(
            "QPushButton {background:#B07A33;color:white;padding:9px;"
            "font-weight:700;border-radius:5px;}"
        )
        self.apply_button.clicked.connect(self.apply_colorway)
        layout.addWidget(self.apply_button)

        note = QLabel("The original layer is never overwritten.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#777;font-size:11px;")
        layout.addWidget(note)
        layout.addStretch()
        self.setWidget(root)

    def canvasChanged(self, canvas):
        pass

    def message(self, title, text, critical=False):
        if critical:
            QMessageBox.critical(self, title, text)
        else:
            QMessageBox.information(self, title, text)

    def active_rgba_node(self):
        doc = Krita.instance().activeDocument()
        if not doc:
            self.message("MEHDORA", "Open a design first.", True)
            return None, None
        node = doc.activeNode()
        if not node:
            self.message("MEHDORA", "Select a paint layer first.", True)
            return None, None
        if node.colorModel() != "RGBA" or node.colorDepth() != "U8":
            self.message(
                "MEHDORA",
                "MVP supports RGBA 8-bit layers. Convert the image to RGBA/Alpha 8-bit first.",
                True
            )
            return None, None
        return doc, node

    def detect_colors(self):
        doc, node = self.active_rgba_node()
        if not doc:
            return
        thumb = node.thumbnail(320, 320)
        if thumb.isNull():
            self.message("MEHDORA", "The selected layer has no visible pixels.", True)
            return
        points = []
        stride = max(1, int((thumb.width() * thumb.height() / 18000) ** 0.5))
        for y in range(0, thumb.height(), stride):
            for x in range(0, thumb.width(), stride):
                color = thumb.pixelColor(x, y)
                if color.alpha() > 24:
                    points.append((color.red(), color.green(), color.blue()))
        self.centers = kmeans(points, self.count.value())
        self.render_rows()

    def clear_rows(self):
        while self.colors_layout.count():
            item = self.colors_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
            child = item.layout()
            if child:
                while child.count():
                    sub = child.takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()

    def render_rows(self):
        self.clear_rows()
        self.rows = []
        for index, center in enumerate(self.centers):
            row = QHBoxLayout()
            source = ColorButton(QColor(*center), editable=False)
            target = ColorButton(DEFAULT_TARGETS[index % len(DEFAULT_TARGETS)])
            row.addWidget(QLabel("%d" % (index + 1)))
            row.addWidget(source)
            row.addWidget(QLabel("→"))
            row.addWidget(target)
            self.colors_layout.addLayout(row)
            self.rows.append((source, target))

    def apply_colorway(self):
        if not self.centers:
            self.message("MEHDORA", "Detect colors first.", True)
            return
        doc, node = self.active_rgba_node()
        if not doc:
            return
        width, height = doc.width(), doc.height()
        if width * height > 80_000_000:
            self.message("MEHDORA", "This MVP is limited to 80 megapixels.", True)
            return

        self.progress.setVisible(True)
        self.progress.setRange(0, height)
        targets = [
            (button.color.red(), button.color.green(), button.color.blue())
            for _, button in self.rows
        ]
        source_luma = [luminance(c) for c in self.centers]

        original = bytes(node.pixelData(0, 0, width, height))
        if len(original) != width * height * 4:
            self.progress.setVisible(False)
            self.message("MEHDORA", "Unexpected pixel format in the selected layer.", True)
            return
        output = bytearray(original)
        row_bytes = width * 4
        for y in range(height):
            start = y * row_bytes
            end = start + row_bytes
            for pos in range(start, end, 4):
                b, g, r, a = original[pos:pos + 4]
                if a == 0:
                    continue
                rgb = (r, g, b)
                index = min(
                    range(len(self.centers)),
                    key=lambda i: distance2(rgb, self.centers[i])
                )
                target = targets[index]
                delta = luminance(rgb) - source_luma[index]
                nr = max(0, min(255, int(target[0] + delta)))
                ng = max(0, min(255, int(target[1] + delta)))
                nb = max(0, min(255, int(target[2] + delta)))
                output[pos:pos + 4] = bytes((nb, ng, nr, a))
            if y % 32 == 0:
                self.progress.setValue(y)

        duplicate = node.duplicate()
        duplicate.setName("MEHDORA Colorway")
        parent = node.parentNode() or doc.rootNode()
        parent.addChildNode(duplicate, node)
        duplicate.setPixelData(bytes(output), 0, 0, width, height)
        doc.setActiveNode(duplicate)
        doc.refreshProjection()
        self.progress.setValue(height)
        self.progress.setVisible(False)
        self.message("MEHDORA", "Colorway created on a new editable layer.")


Krita.instance().addDockWidgetFactory(
    DockWidgetFactory(
        "mehdora_color_lab",
        DockWidgetFactoryBase.DockRight,
        MehdoraColorLab
    )
)
