"""Library window: your saved images and hands, plus the pen-tip helper."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSize, QPointF, QRectF, Signal
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QImage, QPen
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget, QListWidgetItem,
    QLineEdit, QFileDialog, QMessageBox, QInputDialog, QCheckBox, QWidget, QButtonGroup,
    QAbstractItemView,
)

import library

THUMB = 148


def thumbnail(path):
    """Square thumbnail on a light checkerboard (transparency stays visible)."""
    pix = QPixmap(THUMB, THUMB)
    pix.fill(QColor('#E9ECEF'))
    p = QPainter(pix)
    for y in range(0, THUMB, 12):
        for x in range(0, THUMB, 12):
            if (x // 12 + y // 12) % 2:
                p.fillRect(x, y, 12, 12, QColor('#D6DBE0'))
    image = QImage()
    if Path(path).suffix.lower() == '.svg':
        try:
            from PySide6.QtSvg import QSvgRenderer
            renderer = QSvgRenderer(str(path))
            if renderer.isValid():
                size = renderer.defaultSize()
                size.scale(THUMB - 12, THUMB - 12, Qt.AspectRatioMode.KeepAspectRatio)
                renderer.render(p, QRectF((THUMB - size.width()) / 2, (THUMB - size.height()) / 2,
                                          size.width(), size.height()))
        except Exception:
            pass
    else:
        image.load(str(path))
    if not image.isNull():
        scaled = image.scaled(THUMB - 8, THUMB - 8, Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
        p.drawImage((THUMB - scaled.width()) // 2, (THUMB - scaled.height()) // 2, scaled)
    p.end()
    return QIcon(pix)


class LibraryDialog(QDialog):
    """use_item(category, item) is called when the user picks an item."""

    def __init__(self, parent=None, category='images', use_item=None):
        super().__init__(parent)
        self.setWindowTitle('Library')
        self.resize(940, 640)
        self.use_item = use_item
        self.settings = library.load_settings()
        self.lib = library.Library(self.settings['root'])
        self.category = category
        self.setAcceptDrops(True)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16); root.setSpacing(10)
        title = QLabel('Library'); title.setStyleSheet('font-size: 18px; font-weight: 700;')
        root.addWidget(title)
        top = QHBoxLayout()
        self.folder_label = QLabel(); self.folder_label.setObjectName('note'); self.folder_label.setWordWrap(True)
        top.addWidget(self.folder_label, 1)
        open_folder = QPushButton('Open folder'); open_folder.setObjectName('subtle')
        open_folder.clicked.connect(lambda: library.reveal(self.lib.folder(self.category)))
        top.addWidget(open_folder)
        move = QPushButton('Change library folder…'); move.setObjectName('subtle')
        move.clicked.connect(self.change_folder)
        top.addWidget(move)
        root.addLayout(top)
        bar = QHBoxLayout()
        self.tab_group = QButtonGroup(self); self.tabs = {}
        for key, text in (('images', 'Images'), ('hands', 'Hands')):
            button = QPushButton(text); button.setCheckable(True); button.setMinimumWidth(110)
            button.clicked.connect(lambda checked=False, k=key: self.set_category(k))
            self.tab_group.addButton(button); self.tabs[key] = button
            bar.addWidget(button)
        bar.addSpacing(12)
        self.search = QLineEdit(); self.search.setPlaceholderText('Search…')
        self.search.textChanged.connect(self.reload)
        bar.addWidget(self.search, 1)
        upload = QPushButton('⬆  Upload…'); upload.setObjectName('primary')
        upload.clicked.connect(self.upload)
        bar.addWidget(upload)
        root.addLayout(bar)
        self.grid = QListWidget()
        self.grid.setViewMode(QListWidget.ViewMode.IconMode)
        self.grid.setIconSize(QSize(THUMB, THUMB))
        self.grid.setGridSize(QSize(THUMB + 22, THUMB + 44))
        self.grid.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.grid.setMovement(QListWidget.Movement.Static)
        self.grid.setWordWrap(True)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid.itemDoubleClicked.connect(lambda *_: self.use())
        self.grid.itemSelectionChanged.connect(self.refresh_buttons)
        root.addWidget(self.grid, 1)
        self.empty = QLabel(); self.empty.setObjectName('note'); self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.empty)
        actions = QHBoxLayout()
        self.keep = QCheckBox('Keep a copy of every file I import or load')
        self.keep.setChecked(bool(self.settings.get('keep_imports', True)))
        self.keep.setToolTip('Imported images, SVGs and hands are copied into the library automatically.')
        self.keep.toggled.connect(self.keep_changed)
        actions.addWidget(self.keep, 1)
        self.tip_button = QPushButton('Pen tip…'); self.tip_button.clicked.connect(self.edit_tip)
        actions.addWidget(self.tip_button)
        self.rename_button = QPushButton('Rename'); self.rename_button.clicked.connect(self.rename)
        actions.addWidget(self.rename_button)
        self.show_button = QPushButton('Show in folder'); self.show_button.clicked.connect(self.show_file)
        actions.addWidget(self.show_button)
        self.delete_button = QPushButton('Delete'); self.delete_button.clicked.connect(self.delete)
        actions.addWidget(self.delete_button)
        self.use_button = QPushButton('Use'); self.use_button.setObjectName('primary')
        self.use_button.clicked.connect(self.use)
        actions.addWidget(self.use_button)
        root.addLayout(actions)
        self.set_category(category)

    # ------------------------------------------------------------ listing
    def set_category(self, key):
        self.category = key
        for k, b in self.tabs.items():
            b.setChecked(k == key)
        self.reload()

    def reload(self, *args):
        self.folder_label.setText(f'Saved in: {self.lib.root}  •  copies are kept here, '
                                  'so moving or deleting the originals is safe')
        self.grid.clear()
        items = self.lib.items(self.category, self.search.text())
        for item in items:
            entry = QListWidgetItem(thumbnail(item.path), item.name)
            entry.setData(Qt.ItemDataRole.UserRole, item)
            entry.setToolTip(f'{item.name}\n{item.file}' + (f'\nfrom {item.original}' if item.original else ''))
            self.grid.addItem(entry)
        self.empty.setVisible(not items)
        self.empty.setText('Nothing here yet. Click Upload, or drag files onto this window.'
                           if not self.search.text() else 'No matches.')
        self.refresh_buttons()

    def selected(self):
        return [e.data(Qt.ItemDataRole.UserRole) for e in self.grid.selectedItems()]

    def refresh_buttons(self):
        chosen = self.selected()
        one = len(chosen) == 1
        self.use_button.setEnabled(one and self.use_item is not None)
        self.rename_button.setEnabled(one)
        self.show_button.setEnabled(one)
        self.delete_button.setEnabled(bool(chosen))
        self.tip_button.setVisible(self.category == 'hands')
        self.tip_button.setEnabled(one)

    # ------------------------------------------------------------ actions
    def add_files(self, paths):
        added, problems = 0, []
        for path in paths:
            try:
                tip = None
                if self.category == 'hands':
                    from hand_tip import find_tip
                    from PIL import Image
                    found = find_tip(Image.open(path))
                    tip = found[:2] if found else None
                self.lib.add(self.category, path, tip=tip)
                added += 1
            except Exception as exc:
                problems.append(str(exc))
        self.reload()
        if problems:
            QMessageBox.warning(self, 'Library', '\n'.join(problems[:10]))
        return added

    def upload(self):
        filt = ('Images (*.png *.jpg *.jpeg *.webp *.bmp *.svg)' if self.category == 'images'
                else 'Transparent hand PNG (*.png)')
        names, _ = QFileDialog.getOpenFileNames(self, 'Upload to the library', '', filt)
        if names:
            self.add_files(names)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.add_files([u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()])

    def use(self):
        chosen = self.selected()
        if len(chosen) == 1 and self.use_item:
            self.use_item(self.category, chosen[0])
            self.accept()

    def rename(self):
        chosen = self.selected()
        if len(chosen) != 1:
            return
        name, ok = QInputDialog.getText(self, 'Rename', 'Name:', text=chosen[0].name)
        if ok:
            self.lib.rename(chosen[0], name)
            self.reload()

    def show_file(self):
        chosen = self.selected()
        if chosen:
            library.reveal(chosen[0].path)

    def delete(self):
        chosen = self.selected()
        if not chosen:
            return
        if QMessageBox.question(self, 'Delete', f'Move {len(chosen)} item(s) to "Deleted items" in the '
                                'library folder? You can bring them back from there.') \
                != QMessageBox.StandardButton.Yes:
            return
        for item in chosen:
            self.lib.delete(item)
        self.reload()

    def edit_tip(self):
        chosen = self.selected()
        if len(chosen) != 1:
            return
        image = QImage(str(chosen[0].path))
        dialog = PenTipDialog(self, image, chosen[0].tip)
        if dialog.exec():
            self.lib.set_tip(chosen[0], dialog.tip)
            self.reload()

    def keep_changed(self, checked):
        self.settings = library.load_settings()
        self.settings['keep_imports'] = bool(checked)
        library.save_settings(self.settings)

    def change_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Choose where the library is kept',
                                                  str(self.lib.root.parent))
        if not folder:
            return
        target = Path(folder) / 'StrokeScribe Library' if Path(folder).name != 'StrokeScribe Library' else Path(folder)
        try:
            self.lib.move_to(target)
        except Exception as exc:
            QMessageBox.warning(self, 'Library', f'Could not move the library: {exc}')
        self.settings = library.load_settings()
        self.reload()


class TipCanvas(QWidget):
    clicked = Signal(float, float)

    def __init__(self, image, tip):
        super().__init__()
        self.image = image
        self.tip = tip
        self.setMinimumSize(420, 420)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _rect(self):
        size = self.image.size()
        size.scale(self.size() * .96, Qt.AspectRatioMode.KeepAspectRatio)
        return QRectF((self.width() - size.width()) / 2, (self.height() - size.height()) / 2,
                      size.width(), size.height())

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor('#E9ECEF'))
        rect = self._rect()
        p.drawImage(rect, self.image)
        if self.tip:
            x = rect.x() + self.tip[0] * rect.width(); y = rect.y() + self.tip[1] * rect.height()
            p.setPen(QPen(QColor('#E53935'), 2))
            p.drawEllipse(QPointF(x, y), 9, 9)
            p.drawLine(QPointF(x - 16, y), QPointF(x - 5, y)); p.drawLine(QPointF(x + 5, y), QPointF(x + 16, y))
            p.drawLine(QPointF(x, y - 16), QPointF(x, y - 5)); p.drawLine(QPointF(x, y + 5), QPointF(x, y + 16))
        p.end()

    def mousePressEvent(self, event):
        rect = self._rect()
        x = (event.position().x() - rect.x()) / max(1., rect.width())
        y = (event.position().y() - rect.y()) / max(1., rect.height())
        if 0 <= x <= 1 and 0 <= y <= 1:
            self.tip = (x, y)
            self.update()
            self.clicked.emit(x, y)


class PenTipDialog(QDialog):
    """Shows where the pen tip is; click to move it, or find it automatically."""

    def __init__(self, parent, image, tip=None):
        super().__init__(parent)
        self.setWindowTitle('Pen tip')
        self.resize(560, 620)
        self.image = image
        layout = QVBoxLayout(self)
        note = QLabel('The red mark is where lines come out of the pen. Click on the pen tip to move it.')
        note.setWordWrap(True); note.setObjectName('note')
        layout.addWidget(note)
        if tip is None:
            tip, self.confidence = self.auto()
        self.canvas = TipCanvas(image, tip)
        self.canvas.clicked.connect(lambda x, y: self.show_tip())
        layout.addWidget(self.canvas, 1)
        self.value = QLabel(); self.value.setObjectName('note')
        layout.addWidget(self.value)
        row = QHBoxLayout()
        auto = QPushButton('Find automatically'); auto.clicked.connect(self.find_again)
        row.addWidget(auto); row.addStretch(1)
        cancel = QPushButton('Cancel'); cancel.clicked.connect(self.reject)
        ok = QPushButton('Use this pen tip'); ok.setObjectName('primary'); ok.clicked.connect(self.accept)
        row.addWidget(cancel); row.addWidget(ok)
        layout.addLayout(row)
        self.show_tip()

    def auto(self):
        from hand_tip import find_tip
        found = find_tip(self.image)
        if not found:
            return (.1, .1), 0.
        return found[:2], found[2]

    def find_again(self):
        tip, _ = self.auto()
        self.canvas.tip = tip
        self.canvas.update()
        self.show_tip()

    def show_tip(self):
        x, y = self.canvas.tip
        self.value.setText(f'Pen tip X {x:.3f}  •  Y {y:.3f}')

    @property
    def tip(self):
        return self.canvas.tip
