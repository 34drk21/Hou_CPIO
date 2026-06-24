# -*- coding: utf-8 -*-
"""hou_cpio Browser shelf script. Requires only Houdini, PySide6 and stdlib."""

import json
from datetime import datetime, timezone
from pathlib import Path

import hou
from PySide6 import QtCore, QtGui, QtWidgets

CONTEXTS = ("sop", "vop", "dop", "obj", "rop", "shop", "chop", "cop2", "lop", "top")

# Set the shared default used whenever this shelf tool is opened.
DEFAULT_LIBRARY_PATH = r"Z:\hou_cpio_library"


def normalize_context(value):
    context = (value or "").strip().lower()
    if context == "object":
        return "obj"
    return context


def parse_time(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except Exception:
        return None


def display_time(value):
    parsed = parse_time(value)
    if not parsed:
        return "-"
    return parsed.astimezone().strftime("%Y/%m/%d  %H:%M")


def read_json(path):
    try:
        if path.stat().st_size > 1024 * 1024:
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def human_bytes(value):
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return "{:.1f} {}".format(size, unit)
        size /= 1024
    return "{:.1f} PB".format(size)


def context_from_path(path):
    parts = [part.lower() for part in path.parts]
    if "cpio" in parts:
        index = parts.index("cpio")
        if index + 1 < len(parts):
            return normalize_context(parts[index + 1])
    return ""


def path_inside(root, value, subdirectory=None):
    if not value:
        return None
    allowed_root = (root / subdirectory).resolve() if subdirectory else root.resolve()
    candidate = (root / value).resolve()
    try:
        candidate.relative_to(allowed_root)
        return candidate
    except ValueError:
        return None


def display_name(path, context):
    name = path.stem
    prefix = (context or "").lower() + "_"
    if prefix != "_" and name.lower().startswith(prefix):
        return name[len(prefix):] or name
    return name


def thumbnail_for(root, cpio_path, metadata):
    configured = path_inside(root, metadata.get("thumbnail_path"), "thumbs")
    if configured and configured.stem == cpio_path.stem and configured.is_file():
        return configured
    for suffix in (".png", ".jpg", ".jpeg"):
        candidate = root / "thumbs" / (cpio_path.stem + suffix)
        if candidate.is_file() and is_within(candidate, root / "thumbs"):
            return candidate
    return None


def is_within(path, root):
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def placeholder(context, width, height):
    pixmap = QtGui.QPixmap(width, height)
    pixmap.fill(QtGui.QColor("#343941"))
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setPen(QtGui.QColor("#e8eaed"))
    font = QtGui.QFont()
    font.setBold(True)
    font.setPointSize(max(16, int(height * 0.18)))
    painter.setFont(font)
    painter.drawText(pixmap.rect(), QtCore.Qt.AlignCenter, (context or "CPIO").upper())
    painter.end()
    return pixmap


class HouCpioBrowser(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or hou.qt.mainWindow())
        self.setWindowTitle("hou_cpio Browser")
        self.resize(1120, 700)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.assets = []
        self._thumb_width = 240
        self._thumb_height = 135
        self._build_ui()
        self.path_edit.setText(DEFAULT_LIBRARY_PATH)
        self.refresh()

    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        path_row = QtWidgets.QHBoxLayout()
        self.path_edit = QtWidgets.QLineEdit()
        self.path_edit.editingFinished.connect(self._path_changed)
        browse = QtWidgets.QPushButton("Browse")
        browse.clicked.connect(self._browse)
        refresh = QtWidgets.QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        path_row.addWidget(QtWidgets.QLabel("Library path"))
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)
        path_row.addWidget(refresh)
        outer.addLayout(path_row)

        filter_row = QtWidgets.QHBoxLayout()
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search name, path, context or HIP file")
        self.search.textChanged.connect(self._populate)
        self.context_combo = QtWidgets.QComboBox()
        self.context_combo.addItem("All contexts", "")
        for context in CONTEXTS:
            self.context_combo.addItem(context.upper(), context)
        self.context_combo.currentIndexChanged.connect(self._populate)
        filter_row.addWidget(self.search, 1)
        filter_row.addWidget(self.context_combo)
        outer.addLayout(filter_row)

        splitter = QtWidgets.QSplitter()
        self.list = QtWidgets.QListWidget()
        self.list.setViewMode(QtWidgets.QListView.IconMode)
        self.list.setResizeMode(QtWidgets.QListView.Adjust)
        self.list.setMovement(QtWidgets.QListView.Static)
        self.list.setWrapping(True)
        self.list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.list.setIconSize(QtCore.QSize(self._thumb_width, self._thumb_height))
        self.list.setGridSize(QtCore.QSize(270, 190))
        self.list.itemSelectionChanged.connect(self._selection_changed)
        self.list.itemDoubleClicked.connect(lambda _item: self.load_selected())
        splitter.addWidget(self.list)

        detail = QtWidgets.QWidget()
        detail_layout = QtWidgets.QVBoxLayout(detail)
        self.preview = QtWidgets.QLabel()
        self.preview.setAlignment(QtCore.Qt.AlignCenter)
        self.preview.setFixedSize(360, 203)
        self.preview.setStyleSheet("QLabel { background:#202328; border:1px solid #454b55; }")
        detail_layout.addWidget(self.preview, 0, QtCore.Qt.AlignHCenter)

        basic_group = QtWidgets.QGroupBox("CPIO")
        basic_form = QtWidgets.QFormLayout(basic_group)
        self.name_value = self._value_label()
        self.context_value = self._value_label()
        self.size_value = self._value_label()
        basic_form.addRow("Name", self.name_value)
        basic_form.addRow("Context", self.context_value)
        basic_form.addRow("Size", self.size_value)
        detail_layout.addWidget(basic_group)

        date_group = QtWidgets.QGroupBox("Storage")
        date_form = QtWidgets.QFormLayout(date_group)
        self.saved_value = self._value_label()
        self.expires_value = self._value_label()
        date_form.addRow("Saved", self.saved_value)
        date_form.addRow("Expires", self.expires_value)
        detail_layout.addWidget(date_group)

        source_group = QtWidgets.QGroupBox("Source")
        source_layout = QtWidgets.QVBoxLayout(source_group)
        source_layout.addWidget(QtWidgets.QLabel("HIP path"))
        self.hip_value = QtWidgets.QLineEdit()
        self.hip_value.setReadOnly(True)
        self.hip_value.setPlaceholderText("No source HIP metadata")
        source_layout.addWidget(self.hip_value)
        source_layout.addWidget(QtWidgets.QLabel("CPIO path"))
        self.path_value = QtWidgets.QPlainTextEdit()
        self.path_value.setReadOnly(True)
        self.path_value.setMaximumHeight(70)
        source_layout.addWidget(self.path_value)
        detail_layout.addWidget(source_group, 1)

        buttons = QtWidgets.QHBoxLayout()
        self.load_button = QtWidgets.QPushButton("Load CPIO")
        self.load_button.clicked.connect(self.load_selected)
        self.delete_button = QtWidgets.QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete_selected)
        buttons.addWidget(self.load_button)
        buttons.addWidget(self.delete_button)
        detail_layout.addLayout(buttons)
        splitter.addWidget(detail)
        splitter.setSizes([730, 390])
        splitter.splitterMoved.connect(lambda _pos, _index: self._schedule_thumbnail_update())
        self.splitter = splitter
        outer.addWidget(splitter, 1)

    def _value_label(self):
        label = QtWidgets.QLabel("-")
        label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        label.setStyleSheet(
            "QLabel { background:#252a31; border:1px solid #3b414a;"
            " border-radius:4px; padding:5px 7px; }"
        )
        return label

    def _browse(self):
        selected = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Choose hou_cpio library", self.path_edit.text()
        )
        if selected:
            self.path_edit.setText(selected)
            self._path_changed()

    def _path_changed(self):
        self.refresh()

    def _root(self):
        value = self.path_edit.text().strip()
        return Path(value).resolve() if value else None

    def _cleanup_expired(self, root):
        removed = 0
        cpio_root = root / "cpio"
        for meta in cpio_root.rglob("*.json") if cpio_root.is_dir() else ():
            if not meta.is_file() or not is_within(meta, cpio_root):
                continue
            data = read_json(meta)
            if data.get("permanent", False):
                continue
            expiry = parse_time(data.get("expires_at"))
            if not expiry or expiry > datetime.now(timezone.utc):
                continue
            cpio = meta.with_suffix(".cpio")
            thumb = thumbnail_for(root, cpio, data)
            for target in (cpio, thumb, meta):
                if target and target.is_file():
                    target.unlink()
            removed += 1
        return removed

    def refresh(self):
        self.assets = []
        self.list.clear()
        self._clear_details()
        self.preview.clear()
        root = self._root()
        if not root:
            return
        if not root.is_dir():
            self.path_edit.setStyleSheet("QLineEdit { border: 1px solid #d05c5c; }")
            self.path_edit.setToolTip("Library path does not exist.")
            self.path_value.setPlainText(
                "Library path does not exist.\nChoose an existing library folder.\n\n{}".format(root)
            )
            return
        self.path_edit.setStyleSheet("")
        self.path_edit.setToolTip("")
        try:
            removed = self._cleanup_expired(root)
            cpio_root = root / "cpio"
            for path in cpio_root.rglob("*.cpio") if cpio_root.is_dir() else ():
                if (
                    not path.is_file()
                    or path.suffix.lower() != ".cpio"
                    or not is_within(path, cpio_root)
                ):
                    continue
                meta_path = path.with_suffix(".json")
                meta = (
                    read_json(meta_path)
                    if meta_path.is_file() and is_within(meta_path, cpio_root)
                    else {}
                )
                context = normalize_context(meta.get("context")) or context_from_path(path)
                thumb = thumbnail_for(root, path, meta)
                self.assets.append({
                    "path": path,
                    "relative": path.relative_to(root).as_posix(),
                    "context": context,
                    "display_name": display_name(path, context),
                    "meta_path": meta_path,
                    "meta": meta,
                    "thumb": thumb,
                    "size": path.stat().st_size,
                })
            self.assets.sort(key=lambda item: item["relative"].lower())
            self._populate()
            if removed:
                hou.ui.setStatusMessage(
                    "hou_cpio removed {} expired item(s).".format(removed),
                    severity=hou.severityType.Message,
                )
        except Exception as exc:
            hou.ui.displayMessage("Refresh failed:\n{}".format(exc))

    def _populate(self):
        selected_path = None
        selected = self._selected()
        if selected:
            selected_path = selected["path"]
        self.list.clear()
        query = self.search.text().strip().lower()
        context_filter = self.context_combo.currentData()
        for asset in self.assets:
            meta = asset["meta"]
            text = "{} {} {} {}".format(
                asset["relative"], asset["context"], meta.get("source_hip_path", ""), meta.get("saved_at", "")
            ).lower()
            if query and query not in text:
                continue
            if context_filter and asset["context"] != context_filter:
                continue
            if asset["thumb"] and asset["thumb"].is_file():
                pixmap = QtGui.QPixmap(str(asset["thumb"]))
                if pixmap.isNull():
                    pixmap = placeholder(
                        asset["context"], self._thumb_width, self._thumb_height
                    )
            else:
                pixmap = placeholder(
                    asset["context"], self._thumb_width, self._thumb_height
                )
            pixmap = pixmap.scaled(
                self._thumb_width,
                self._thumb_height,
                QtCore.Qt.KeepAspectRatioByExpanding,
                QtCore.Qt.SmoothTransformation,
            )
            item = QtWidgets.QListWidgetItem(
                QtGui.QIcon(pixmap),
                "{}\n{}".format(
                    (asset["context"] or "UNKNOWN").upper(),
                    asset["display_name"],
                ),
            )
            item.setTextAlignment(QtCore.Qt.AlignHCenter)
            item.setData(QtCore.Qt.UserRole, asset)
            self.list.addItem(item)
            if selected_path == asset["path"]:
                item.setSelected(True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "list"):
            self._schedule_thumbnail_update()

    def _schedule_thumbnail_update(self):
        QtCore.QTimer.singleShot(0, self._update_thumbnail_metrics)

    def _update_thumbnail_metrics(self):
        available = max(180, self.list.viewport().width() - 12)
        columns = max(1, available // 230)
        card_width = max(180, min(310, (available - (columns * 10)) // columns))
        thumb_width = max(156, card_width - 24)
        thumb_height = max(88, int(thumb_width * 9 / 16))
        if abs(thumb_width - self._thumb_width) < 8:
            return
        self._thumb_width = thumb_width
        self._thumb_height = thumb_height
        self.list.setIconSize(QtCore.QSize(thumb_width, thumb_height))
        self.list.setGridSize(QtCore.QSize(card_width, thumb_height + 58))
        self._populate()

    def _selected(self):
        items = self.list.selectedItems()
        return items[0].data(QtCore.Qt.UserRole) if items else None

    def _selection_changed(self):
        asset = self._selected()
        if not asset:
            self.preview.clear()
            self._clear_details()
            return
        if asset["thumb"] and asset["thumb"].is_file():
            pixmap = QtGui.QPixmap(str(asset["thumb"]))
        else:
            pixmap = placeholder(asset["context"], 360, 203)
        self.preview.setPixmap(
            pixmap.scaled(360, 203, QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation)
        )
        meta = asset["meta"]
        expiry = "Permanent" if meta.get("permanent") else display_time(meta.get("expires_at"))
        if not meta.get("permanent") and not meta.get("expires_at"):
            expiry = "No expiration metadata"
        self.name_value.setText(asset["display_name"])
        self.context_value.setText((asset["context"] or "-").upper())
        self.size_value.setText(human_bytes(asset["size"]))
        self.saved_value.setText(display_time(meta.get("saved_at")))
        self.expires_value.setText(expiry)
        self.hip_value.setText(meta.get("source_hip_path") or "")
        self.path_value.setPlainText(str(asset["path"]))
        self.load_button.setEnabled(True)
        self.delete_button.setEnabled(True)

    def _clear_details(self):
        for label in (
            self.name_value,
            self.context_value,
            self.size_value,
            self.saved_value,
            self.expires_value,
        ):
            label.setText("-")
        self.hip_value.clear()
        self.path_value.clear()
        self.load_button.setEnabled(False)
        self.delete_button.setEnabled(False)

    def load_selected(self):
        asset = self._selected()
        if not asset:
            return
        try:
            pane = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
            parent = pane.pwd() if pane else hou.node("/obj")
            expected = asset["context"]
            actual = (
                normalize_context(parent.childTypeCategory().name())
                if parent.childTypeCategory()
                else ""
            )
            if expected and actual != expected:
                hou.ui.displayMessage(
                    "Open a {} Network Editor before loading this CPIO.".format(expected.upper())
                )
                return
            hou.clearAllSelected()
            parent.loadItemsFromFile(str(asset["path"]), ignore_load_warnings=False)
            selected = hou.selectedNodes()
            if selected and pane:
                center = pane.visibleBounds().center()
                anchor = selected[0].position()
                for node in selected:
                    node.setPosition(node.position() + center - anchor)
            hou.ui.setStatusMessage("Loaded {}".format(asset["path"].name))
        except Exception as exc:
            hou.ui.displayMessage("Load failed:\n{}".format(exc))

    def delete_selected(self):
        asset = self._selected()
        if not asset:
            return
        result = QtWidgets.QMessageBox.question(
            self,
            "Delete CPIO",
            "Delete this CPIO and its metadata/thumbnail?\n\n{}".format(asset["path"]),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if result != QtWidgets.QMessageBox.Yes:
            return
        try:
            for target in (asset["path"], asset["meta_path"], asset["thumb"]):
                if target and target.is_file():
                    target.unlink()
            self.refresh()
        except Exception as exc:
            hou.ui.displayMessage("Delete failed:\n{}".format(exc))


def show_hou_cpio_browser():
    for widget in QtWidgets.QApplication.topLevelWidgets():
        if isinstance(widget, HouCpioBrowser):
            widget.showNormal()
            widget.raise_()
            widget.activateWindow()
            return
    HouCpioBrowser().show()


show_hou_cpio_browser()
