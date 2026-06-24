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
    if context in {"obj", "object", "object network", "objectnetwork"}:
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


class CpioItemDelegate(QtWidgets.QStyledItemDelegate):
    CARD_PADDING = 10
    IMAGE_TEXT_GAP = 8
    BORDER_RADIUS = 7

    def sizeHint(self, option, index):
        view = self.parent()
        if view:
            grid = view.gridSize()
            if grid.isValid():
                return grid
        return super().sizeHint(option, index)

    def paint(self, painter, option, index):
        asset = index.data(QtCore.Qt.UserRole)
        permanent = bool(asset and asset.get("meta", {}).get("permanent"))
        selected = bool(option.state & QtWidgets.QStyle.State_Selected)

        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        card_rect = option.rect.adjusted(5, 5, -5, -5)
        if permanent:
            painter.setPen(QtGui.QPen(QtGui.QColor("#3f5d51"), 1))
            painter.setBrush(QtGui.QColor("#263a34"))
        else:
            painter.setPen(QtGui.QPen(QtGui.QColor("#5a606a"), 1))
            painter.setBrush(QtGui.QColor("#20242b"))
        painter.drawRoundedRect(card_rect, self.BORDER_RADIUS, self.BORDER_RADIUS)

        image_rect = QtCore.QRect(
            card_rect.center().x() - option.decorationSize.width() // 2,
            card_rect.top() + self.CARD_PADDING,
            option.decorationSize.width(),
            option.decorationSize.height(),
        )
        icon = index.data(QtCore.Qt.DecorationRole)
        pixmap = icon.pixmap(option.decorationSize) if isinstance(icon, QtGui.QIcon) else QtGui.QPixmap()
        if not pixmap.isNull():
            target = QtCore.QRect(
                image_rect.center().x() - pixmap.width() // 2,
                image_rect.top(),
                pixmap.width(),
                pixmap.height(),
            )
            painter.drawPixmap(target, pixmap)

        text_rect = QtCore.QRect(
            card_rect.left() + self.CARD_PADDING,
            image_rect.bottom() + self.IMAGE_TEXT_GAP,
            max(1, card_rect.width() - self.CARD_PADDING * 2),
            max(1, card_rect.bottom() - image_rect.bottom() - self.IMAGE_TEXT_GAP - self.CARD_PADDING),
        )
        text = index.data(QtCore.Qt.DisplayRole) or ""
        lines = text.splitlines()
        context = lines[0] if lines else ""
        name = lines[1] if len(lines) > 1 else ""

        context_font = QtGui.QFont(option.font)
        context_font.setBold(True)
        context_font.setPointSize(max(10, option.font.pointSize() + 1))
        name_font = QtGui.QFont(option.font)
        name_font.setPointSize(max(10, option.font.pointSize() + 1))

        painter.setPen(QtGui.QColor("#edf6f0") if permanent else QtGui.QColor("#dfe3e8"))
        painter.setFont(context_font)
        line_height = QtGui.QFontMetrics(context_font).height()
        context_rect = QtCore.QRect(text_rect.left(), text_rect.top(), text_rect.width(), line_height)
        painter.drawText(context_rect, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter, context)

        painter.setFont(name_font)
        name_rect = QtCore.QRect(
            text_rect.left(),
            context_rect.bottom() + 3,
            text_rect.width(),
            max(1, text_rect.bottom() - context_rect.bottom() - 3),
        )
        painter.drawText(
            name_rect,
            QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop | QtCore.Qt.TextWordWrap,
            name,
        )

        if selected:
            border_rect = card_rect.adjusted(1, 1, -1, -1)
            painter.setPen(QtGui.QPen(QtGui.QColor("#f2f5f7"), 2))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawRoundedRect(border_rect, self.BORDER_RADIUS, self.BORDER_RADIUS)

        painter.restore()


class CpioListWidget(QtWidgets.QListWidget):
    def __init__(self, browser):
        super().__init__()
        self.browser = browser
        self._drag_start_pos = QtCore.QPoint()
        self._drag_start_item = None

    def mousePressEvent(self, event):
        if not self.indexAt(event.position().toPoint()).isValid():
            self.clearSelection()
            self.setCurrentIndex(QtCore.QModelIndex())
            self._drag_start_item = None
        elif event.button() == QtCore.Qt.LeftButton:
            self._drag_start_pos = event.position().toPoint()
            self._drag_start_item = self.itemAt(self._drag_start_pos)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            self._drag_start_item
            and event.buttons() & QtCore.Qt.LeftButton
            and (event.position().toPoint() - self._drag_start_pos).manhattanLength()
            >= QtWidgets.QApplication.startDragDistance()
        ):
            self.setCurrentItem(self._drag_start_item)
            self._drag_start_item.setSelected(True)
            self.startDrag(QtCore.Qt.CopyAction)
            self._drag_start_item = None
            event.accept()
            return
        super().mouseMoveEvent(event)

    def startDrag(self, supported_actions):
        item = self.currentItem()
        asset = item.data(QtCore.Qt.UserRole) if item else self.browser._selected()
        if not asset:
            return
        drag = QtGui.QDrag(self)
        mime = QtCore.QMimeData()
        mime.setData("application/x-hou-cpio-path", str(asset["path"]).encode("utf-8"))
        drag.setMimeData(mime)
        pixmap = asset.get("pixmap")
        if isinstance(pixmap, QtGui.QPixmap) and not pixmap.isNull():
            drag.setPixmap(pixmap.scaled(160, 90, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
            drag.setHotSpot(QtCore.QPoint(24, 24))
        drag.exec(QtCore.Qt.CopyAction)
        drop_pos = QtGui.QCursor.pos()
        pane = self.browser._network_editor_for_drop(drop_pos)
        if pane:
            self.browser.load_asset(asset, pane=pane, drop_pos=drop_pos)


class HouCpioBrowser(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or hou.qt.mainWindow())
        self.setWindowTitle("hou_cpio Browser")
        self.resize(1120, 700)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose)
        self.assets = []
        self._thumb_width = 240
        self._thumb_height = 135
        self._card_width = 270
        self._grid_scale = 100
        self._build_ui()
        self.path_edit.setText(DEFAULT_LIBRARY_PATH)
        self.refresh()

    def _build_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        path_row = QtWidgets.QHBoxLayout()
        self.path_edit = QtWidgets.QLineEdit()
        self.path_edit.editingFinished.connect(self._path_changed)
        browse = QtWidgets.QPushButton("Browse")
        browse.setAutoDefault(False)
        browse.setDefault(False)
        browse.clicked.connect(self._browse)
        refresh = QtWidgets.QPushButton("Refresh")
        refresh.setAutoDefault(False)
        refresh.setDefault(False)
        refresh.clicked.connect(lambda: self.refresh())
        path_row.addWidget(QtWidgets.QLabel("Library path"))
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)
        path_row.addWidget(refresh)
        outer.addLayout(path_row)

        filter_row = QtWidgets.QHBoxLayout()
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search name, path, context, HIP file or memo")
        self.search.textChanged.connect(lambda _text: self._populate())
        self.search.returnPressed.connect(self._search_return_pressed)
        self.context_combo = QtWidgets.QComboBox()
        self.context_combo.addItem("All contexts", "")
        for context in CONTEXTS:
            self.context_combo.addItem(context.upper(), context)
        self.context_combo.currentIndexChanged.connect(lambda _index: self._populate())
        filter_row.addWidget(self.search, 1)
        filter_row.addWidget(self.context_combo)
        outer.addLayout(filter_row)

        splitter = QtWidgets.QSplitter()
        self.list = CpioListWidget(self)
        self.list.setViewMode(QtWidgets.QListView.IconMode)
        self.list.setDragEnabled(True)
        self.list.setDragDropMode(QtWidgets.QAbstractItemView.DragOnly)
        self.list.setDefaultDropAction(QtCore.Qt.CopyAction)
        self.list.setResizeMode(QtWidgets.QListView.Adjust)
        self.list.setMovement(QtWidgets.QListView.Static)
        self.list.setWrapping(True)
        self.list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        self.list.setIconSize(QtCore.QSize(self._thumb_width, self._thumb_height))
        self.list.setGridSize(QtCore.QSize(270, self._thumb_height + 82))
        self.list.setItemDelegate(CpioItemDelegate(self.list))
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
        source_layout.addWidget(QtWidgets.QLabel("Memo"))
        self.note_edit = QtWidgets.QPlainTextEdit()
        self.note_edit.setPlaceholderText("Write a memo for this CPIO.")
        self.note_edit.setMaximumHeight(96)
        source_layout.addWidget(self.note_edit)
        note_row = QtWidgets.QHBoxLayout()
        note_row.addStretch()
        self.save_note_button = QtWidgets.QPushButton("Save Memo")
        self.save_note_button.setAutoDefault(False)
        self.save_note_button.setDefault(False)
        self.save_note_button.clicked.connect(self.save_note)
        note_row.addWidget(self.save_note_button)
        source_layout.addLayout(note_row)

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
        self.load_button.setAutoDefault(False)
        self.load_button.setDefault(False)
        self.load_button.clicked.connect(self.load_selected)
        self.delete_button = QtWidgets.QPushButton("Delete")
        self.delete_button.setAutoDefault(False)
        self.delete_button.setDefault(False)
        self.delete_button.clicked.connect(self.delete_selected)
        buttons.addWidget(self.load_button)
        buttons.addWidget(self.delete_button)
        detail_layout.addLayout(buttons)
        splitter.addWidget(detail)
        splitter.setSizes([730, 390])
        splitter.splitterMoved.connect(lambda _pos, _index: self._schedule_thumbnail_update())
        self.splitter = splitter
        outer.addWidget(splitter, 1)

        size_row = QtWidgets.QHBoxLayout()
        size_row.addWidget(QtWidgets.QLabel("Grid size"))
        self.grid_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.grid_slider.setRange(70, 160)
        self.grid_slider.setValue(self._grid_scale)
        self.grid_slider.setTickInterval(10)
        self.grid_slider.setSingleStep(5)
        self.grid_slider.valueChanged.connect(self._grid_scale_changed)
        self.grid_size_label = QtWidgets.QLabel("{}%".format(self._grid_scale))
        self.grid_size_label.setMinimumWidth(44)
        size_row.addWidget(self.grid_slider, 1)
        size_row.addWidget(self.grid_size_label)
        outer.addLayout(size_row)

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

    def _search_return_pressed(self):
        self._populate()
        self.search.setFocus(QtCore.Qt.OtherFocusReason)

    def keyPressEvent(self, event):
        if event.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            if self.focusWidget() is self.search:
                self._search_return_pressed()
                event.accept()
                return
        super().keyPressEvent(event)

    def _grid_scale_changed(self, value):
        self._grid_scale = value
        self.grid_size_label.setText("{}%".format(value))
        self._schedule_thumbnail_update()

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

    def refresh(self, select_path=None):
        if select_path is False:
            select_path = None
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
            self._populate(select_path=select_path)
            if removed:
                hou.ui.setStatusMessage(
                    "hou_cpio removed {} expired item(s).".format(removed),
                    severity=hou.severityType.Message,
                )
        except Exception as exc:
            hou.ui.displayMessage("Refresh failed:\n{}".format(exc))

    def _populate(self, select_path=None):
        selected_path = select_path
        if selected_path is None:
            selected = self._selected()
            if selected:
                selected_path = selected["path"]
        self.list.clear()
        query = self.search.text().strip().lower()
        context_filter = self.context_combo.currentData()
        for asset in self.assets:
            meta = asset["meta"]
            text = "{} {} {} {} {}".format(
                asset["relative"],
                asset["context"],
                meta.get("source_hip_path", ""),
                meta.get("saved_at", ""),
                meta.get("note", ""),
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
            asset["pixmap"] = pixmap
            item = QtWidgets.QListWidgetItem(
                QtGui.QIcon(pixmap),
                "{}\n{}".format(
                    (asset["context"] or "UNKNOWN").upper(),
                    asset["display_name"],
                ),
            )
            item.setTextAlignment(QtCore.Qt.AlignHCenter)
            item.setData(QtCore.Qt.UserRole, asset)
            if meta.get("permanent"):
                item.setBackground(QtGui.QBrush(QtGui.QColor("#263a34")))
                item.setForeground(QtGui.QBrush(QtGui.QColor("#edf6f0")))
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
        target_width = int(230 * self._grid_scale / 100.0)
        card_width = max(150, min(460, target_width, available))
        thumb_width = max(120, card_width - 24)
        thumb_height = max(68, int(thumb_width * 9 / 16))
        if thumb_width == self._thumb_width and card_width == self._card_width:
            return
        self._card_width = card_width
        self._thumb_width = thumb_width
        self._thumb_height = thumb_height
        self.list.setIconSize(QtCore.QSize(thumb_width, thumb_height))
        self.list.setGridSize(QtCore.QSize(card_width, thumb_height + 82))
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
        self.note_edit.setPlainText(meta.get("note") or "")
        self.path_value.setPlainText(str(asset["path"]))
        self.load_button.setEnabled(True)
        self.delete_button.setEnabled(True)
        self.save_note_button.setEnabled(True)

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
        self.note_edit.clear()
        self.path_value.clear()
        self.load_button.setEnabled(False)
        self.delete_button.setEnabled(False)
        self.save_note_button.setEnabled(False)

    def save_note(self):
        asset = self._selected()
        if not asset:
            return
        try:
            meta = dict(asset["meta"])
            meta.setdefault("schema_version", 1)
            meta.setdefault("cpio_path", asset["relative"])
            meta.setdefault("context", asset["context"])
            meta["note"] = self.note_edit.toPlainText()
            temporary_meta = asset["meta_path"].with_suffix(".json.tmp")
            if temporary_meta.exists():
                temporary_meta.unlink()
            temporary_meta.write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_meta.replace(asset["meta_path"])
            self.refresh(select_path=asset["path"])
            hou.ui.setStatusMessage("Saved memo for {}".format(asset["path"].name))
        except Exception as exc:
            try:
                if "temporary_meta" in locals() and temporary_meta.exists():
                    temporary_meta.unlink()
            except OSError:
                pass
            hou.ui.displayMessage("Memo save failed:\n{}".format(exc))

    def _network_editor_under_cursor(self):
        try:
            pane_under_cursor = getattr(hou.ui, "paneTabUnderCursor", None)
            pane = pane_under_cursor() if pane_under_cursor else None
            if pane and pane.type() == hou.paneTabType.NetworkEditor:
                return pane
        except Exception:
            pass
        return None

    def _network_editor_for_drop(self, global_pos):
        pane = self._network_editor_under_cursor()
        if pane:
            return pane
        try:
            if self.frameGeometry().contains(global_pos):
                return None
            main_window = hou.qt.mainWindow()
            if main_window and main_window.frameGeometry().contains(global_pos):
                return hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
        except Exception:
            pass
        return None

    def _load_parent_from_pane(self, pane):
        if pane:
            return pane.pwd()
        fallback = hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor)
        return fallback.pwd() if fallback else hou.node("/obj")

    def _target_position(self, pane, drop_pos=None):
        if pane and drop_pos is not None:
            try:
                return pane.cursorPosition()
            except Exception:
                pass
        if pane:
            try:
                return pane.visibleBounds().center()
            except Exception:
                pass
        return None

    def load_asset(self, asset, pane=None, drop_pos=None):
        if not asset:
            return
        try:
            parent = self._load_parent_from_pane(pane)
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
                target = self._target_position(pane, drop_pos)
                if target is None:
                    return
                anchor = selected[0].position()
                for node in selected:
                    node.setPosition(node.position() + target - anchor)
            hou.ui.setStatusMessage("Loaded {}".format(asset["path"].name))
        except Exception as exc:
            hou.ui.displayMessage("Load failed:\n{}".format(exc))

    def load_selected(self):
        self.load_asset(self._selected(), pane=hou.ui.paneTabOfType(hou.paneTabType.NetworkEditor))

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
