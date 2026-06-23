# -*- coding: utf-8 -*-
"""hou_cpio Export shelf script. Requires only Houdini, PySide6 and stdlib."""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import hou
from PySide6 import QtCore, QtGui, QtWidgets

CONTEXTS = ("sop", "vop", "dop", "obj", "rop", "shop", "chop", "cop2", "lop", "top")
DEFAULT_DAYS = 7

# Set the shared default used whenever this shelf tool is opened.
DEFAULT_LIBRARY_PATH = r"Z:\hou_cpio_library"


def clean_name(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value.strip())
    value = re.sub(r"\s+", "_", value).strip(" ._")
    if value.upper() in {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    }:
        value = "_" + value
    return value[:120]


def node_context(node):
    try:
        return node.type().category().name().lower()
    except Exception:
        return "unknown"


def utc_text(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class CaptureOverlay(QtWidgets.QWidget):
    captured = QtCore.Signal(QtGui.QPixmap)
    dismissed = QtCore.Signal()

    def __init__(self):
        super().__init__(None)
        screens = QtGui.QGuiApplication.screens()
        rect = screens[0].geometry()
        for screen in screens[1:]:
            rect = rect.united(screen.geometry())
        self._virtual_rect = rect
        self._origin = None
        self._current = None
        self.setGeometry(rect)
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.Tool
            | QtCore.Qt.WindowStaysOnTopHint
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.setCursor(QtCore.Qt.CrossCursor)

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 100))
        if self._origin and self._current:
            selection = QtCore.QRect(self._origin, self._current).normalized()
            painter.setCompositionMode(QtGui.QPainter.CompositionMode_Clear)
            painter.fillRect(selection, QtCore.Qt.transparent)
            painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)
            painter.setPen(QtGui.QPen(QtGui.QColor("#4c8bf5"), 2))
            painter.drawRect(selection)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self.update()

    def mouseMoveEvent(self, event):
        if self._origin:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != QtCore.Qt.LeftButton or not self._origin:
            return
        selection = QtCore.QRect(self._origin, event.position().toPoint()).normalized()
        self.hide()
        QtWidgets.QApplication.processEvents()
        if selection.width() < 4 or selection.height() < 4:
            self.close()
            return
        try:
            global_rect = selection.translated(self._virtual_rect.topLeft())
            result = QtGui.QPixmap(global_rect.size())
            result.fill(QtCore.Qt.transparent)
            painter = QtGui.QPainter(result)
            try:
                for screen in QtGui.QGuiApplication.screens():
                    overlap = global_rect.intersected(screen.geometry())
                    if overlap.isEmpty():
                        continue
                    local = overlap.translated(-screen.geometry().topLeft())
                    shot = screen.grabWindow(0, local.x(), local.y(), local.width(), local.height())
                    painter.drawPixmap(overlap.topLeft() - global_rect.topLeft(), shot)
            finally:
                painter.end()
            self.captured.emit(result)
        finally:
            self.close()

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self.close()

    def closeEvent(self, event):
        self.dismissed.emit()
        super().closeEvent(event)


class HouCpioExport(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or hou.qt.mainWindow())
        self.setWindowTitle("hou_cpio Export")
        self.resize(520, 560)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self._image = QtGui.QPixmap()
        self._overlay = None
        self._build_ui()
        self.path_edit.setText(DEFAULT_LIBRARY_PATH)
        self._load_clipboard()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()

        path_row = QtWidgets.QHBoxLayout()
        self.path_edit = QtWidgets.QLineEdit()
        browse = QtWidgets.QPushButton("Browse")
        browse.clicked.connect(self._browse)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)
        form.addRow("Library path", path_row)

        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("setup name")
        form.addRow("Name", self.name_edit)

        keep_row = QtWidgets.QHBoxLayout()
        self.days = QtWidgets.QSpinBox()
        self.days.setRange(1, 36500)
        self.days.setValue(DEFAULT_DAYS)
        self.days.setSuffix(" days")
        self.permanent = QtWidgets.QCheckBox("Keep permanently")
        self.permanent.toggled.connect(lambda checked: self.days.setEnabled(not checked))
        keep_row.addWidget(self.days)
        keep_row.addWidget(self.permanent)
        keep_row.addStretch()
        form.addRow("Retention", keep_row)
        layout.addLayout(form)

        self.preview = QtWidgets.QLabel("No image\nBrowser will show a context placeholder.")
        self.preview.setAlignment(QtCore.Qt.AlignCenter)
        self.preview.setMinimumHeight(270)
        self.preview.setStyleSheet("QLabel { background:#202328; border:1px solid #454b55; }")
        layout.addWidget(self.preview, 1)

        image_row = QtWidgets.QHBoxLayout()
        clipboard = QtWidgets.QPushButton("Use Clipboard")
        clipboard.clicked.connect(self._load_clipboard)
        screenshot = QtWidgets.QPushButton("Screenshot Area")
        screenshot.clicked.connect(self._start_capture)
        clear = QtWidgets.QPushButton("Clear Image")
        clear.clicked.connect(self._clear_image)
        image_row.addWidget(clipboard)
        image_row.addWidget(screenshot)
        image_row.addWidget(clear)
        layout.addLayout(image_row)

        export = QtWidgets.QPushButton("Export CPIO")
        export.setMinimumHeight(38)
        export.clicked.connect(self._export)
        layout.addWidget(export)

    def _browse(self):
        selected = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Choose hou_cpio library", self.path_edit.text()
        )
        if selected:
            self.path_edit.setText(selected)

    def _set_image(self, pixmap):
        self._image = pixmap
        if pixmap.isNull():
            self.preview.setPixmap(QtGui.QPixmap())
            self.preview.setText("No image\nBrowser will show a context placeholder.")
            return
        self.preview.setText("")
        self.preview.setPixmap(
            pixmap.scaled(self.preview.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_image") and hasattr(self, "preview") and not self._image.isNull():
            self._set_image(self._image)

    def _load_clipboard(self):
        image = QtWidgets.QApplication.clipboard().image()
        if not image.isNull():
            self._set_image(QtGui.QPixmap.fromImage(image))

    def _clear_image(self):
        self._set_image(QtGui.QPixmap())

    def _start_capture(self):
        self.hide()
        QtCore.QTimer.singleShot(250, self._show_overlay)

    def _show_overlay(self):
        self._overlay = CaptureOverlay()
        self._overlay.captured.connect(self._capture_done)
        self._overlay.dismissed.connect(self._restore_after_capture)
        self._overlay.show()
        self._overlay.raise_()
        self._overlay.activateWindow()

    def _capture_done(self, pixmap):
        self._set_image(pixmap)

    def _restore_after_capture(self):
        self._overlay = None
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _paths(self, root, context, base):
        cpio = root / "cpio" / context / (base + ".cpio")
        meta = cpio.with_suffix(".json")
        thumb = root / "thumbs" / (base + ".png")
        return cpio, meta, thumb

    def _export(self):
        nodes = hou.selectedNodes()
        if not nodes:
            hou.ui.displayMessage("Select one or more nodes first.")
            return
        root_text = self.path_edit.text().strip()
        name = clean_name(self.name_edit.text())
        if not root_text or not name:
            hou.ui.displayMessage("Library path and name are required.")
            return
        root = Path(root_text).resolve()
        if not root.is_dir():
            hou.ui.displayMessage(
                "Library path does not exist.\nChoose an existing library folder.\n\n{}".format(root)
            )
            return
        context = node_context(nodes[0])
        if context not in CONTEXTS:
            hou.ui.displayMessage("Unsupported node context: {}".format(context))
            return
        base = "{}_{}".format(context, name)
        cpio, meta, thumb = self._paths(root, context, base)
        if cpio.exists():
            choice = QtWidgets.QMessageBox.question(
                self,
                "Already exists",
                "Overwrite the existing CPIO?\nChoose No to save with an incremented name.",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.No,
            )
            if choice == QtWidgets.QMessageBox.Cancel:
                return
            if choice == QtWidgets.QMessageBox.No:
                index = 1
                while cpio.exists():
                    base = "{}_{}_{:03d}".format(context, name, index)
                    cpio, meta, thumb = self._paths(root, context, base)
                    index += 1
        try:
            cpio.parent.mkdir(parents=True, exist_ok=True)
            thumb.parent.mkdir(parents=True, exist_ok=True)
            parent = nodes[0].parent()
            if any(node.parent() != parent for node in nodes):
                raise RuntimeError("All selected nodes must have the same parent.")
            temporary_cpio = cpio.with_name(cpio.stem + ".tmp.cpio")
            temporary_thumb = thumb.with_name(thumb.stem + ".tmp.png")
            temporary_meta = meta.with_suffix(".json.tmp")
            for temporary in (temporary_cpio, temporary_thumb, temporary_meta):
                if temporary.exists():
                    temporary.unlink()
            parent.saveItemsToFile(nodes, str(temporary_cpio), save_hda_fallbacks=False)
            thumb_rel = None
            if not self._image.isNull():
                image = self._image.scaled(
                    960, 540, QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation
                )
                x = max(0, (image.width() - 960) // 2)
                y = max(0, (image.height() - 540) // 2)
                image = image.copy(x, y, min(960, image.width()), min(540, image.height()))
                if not image.save(str(temporary_thumb), "PNG"):
                    raise RuntimeError("Could not save thumbnail.")
                thumb_rel = thumb.relative_to(root).as_posix()

            now = datetime.now(timezone.utc)
            permanent = self.permanent.isChecked()
            expires = None if permanent else now + timedelta(days=self.days.value())
            data = {
                "schema_version": 1,
                "cpio_path": cpio.relative_to(root).as_posix(),
                "context": context,
                "source_hip_path": hou.hipFile.path(),
                "saved_at": utc_text(now),
                "retention_days": None if permanent else self.days.value(),
                "expires_at": None if permanent else utc_text(expires),
                "permanent": permanent,
                "thumbnail_path": thumb_rel,
            }
            temporary_meta.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_cpio.replace(cpio)
            if thumb_rel:
                temporary_thumb.replace(thumb)
            for suffix in (".png", ".jpg", ".jpeg"):
                old_thumb = root / "thumbs" / (base + suffix)
                if old_thumb != thumb or not thumb_rel:
                    if old_thumb.is_file():
                        old_thumb.unlink()
            temporary_meta.replace(meta)
            hou.ui.displayMessage("Saved:\n{}".format(cpio))
            self.close()
        except Exception as exc:
            for temporary in (
                locals().get("temporary_cpio"),
                locals().get("temporary_thumb"),
                locals().get("temporary_meta"),
            ):
                try:
                    if temporary and temporary.exists():
                        temporary.unlink()
                except OSError:
                    pass
            hou.ui.displayMessage("Export failed:\n{}".format(exc))


def show_hou_cpio_export():
    for widget in QtWidgets.QApplication.topLevelWidgets():
        if isinstance(widget, HouCpioExport):
            widget.showNormal()
            widget.raise_()
            widget.activateWindow()
            return
    HouCpioExport().show()


show_hou_cpio_export()
