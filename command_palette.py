"""Ctrl+K: find any command by typing (exp.239, UI clean-up step 3).

Every menu command is listed with its menu path ("File › Save project") and its
shortcut. Typing filters the list (all typed words must appear, in any order);
Up/Down choose, Enter runs, Esc closes.
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout


def menu_commands(window):
    """(label, shortcut, action) for every enabled command in the window's menus."""
    found = []

    def walk(actions, path):
        for action in actions:
            if action.isSeparator():
                continue
            menu = action.menu()
            text = action.text().replace('&&', '\0').replace('&', '').replace('\0', '&')
            name, _, key = text.partition('\t')
            name = name.strip().rstrip('…').rstrip('.').strip() or ''
            if menu is not None:
                walk(menu.actions(), path + [name])
                continue
            if not name or not action.isEnabled() or not action.isVisible():
                continue
            if not key and not action.shortcut().isEmpty():
                key = action.shortcut().toString()
            found.append((' › '.join(path + [name]), key.strip(), action))

    bar = window.menuBar() if hasattr(window, 'menuBar') else None
    if bar is not None:
        walk(bar.actions(), [])
    found += extra_commands(window)
    seen, unique = set(), []
    for label, key, action in found:          # the same command twice: list it once
        if label not in seen:
            seen.add(label)
            unique.append((label, key, action))
    return unique


class _Call:
    """Something that is not in a menu (a timeline or top-bar button) but can be found."""

    def __init__(self, call):
        self.trigger = call


def extra_commands(window):
    found = []
    for label, key, name, args in (
            ('Preview › Play / pause', 'Space', 'toggle', ()),
            ('Preview › Pre-render', '', 'prerender_whole', ()),
            ('Timeline › Add camera clip', '', 'add_camera_menu', ('add_camera_clip_button',)),
            ('Timeline › Add hand motion', '', 'add_hand_motion', ()),
            ('Timeline › Hand paths', '', 'open_hand_paths', ())):
        method = getattr(window, name, None)
        if not callable(method):
            continue
        values = tuple(getattr(window, a, None) for a in args)
        found.append((label, key, _Call(lambda m=method, v=values: m(*v))))
    return found


def matches(label, query):
    words = query.lower().split()
    text = label.lower()
    return all(word in text for word in words)


class CommandPalette(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.setObjectName('commandPalette')
        self.setWindowTitle('Find a command')
        self.setModal(True)
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Type a command… (e.g. export, camera, save)')
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        self.list = QListWidget()
        self.list.setObjectName('commandList')
        self.list.setMinimumHeight(320)
        layout.addWidget(self.list)
        self.empty = QLabel('No command matches.')
        self.empty.setObjectName('note')
        self.empty.hide()
        layout.addWidget(self.empty)
        self.commands = menu_commands(window)
        self.search.textChanged.connect(self.fill)
        self.search.installEventFilter(self)
        self.list.itemActivated.connect(self.run)
        self.fill('')
        self.search.setFocus()

    def fill(self, query):
        self.list.clear()
        for index, (label, key, action) in enumerate(self.commands):
            if matches(label, query):
                item = QListWidgetItem(label + (f'      {key}' if key else ''))
                item.setData(Qt.ItemDataRole.UserRole, index)
                self.list.addItem(item)
        self.empty.setVisible(self.list.count() == 0)
        if self.list.count():
            self.list.setCurrentRow(0)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self.search and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                row = self.list.currentRow() + (1 if key == Qt.Key.Key_Down else -1)
                if 0 <= row < self.list.count():
                    self.list.setCurrentRow(row)
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.run(self.list.currentItem())
                return True
        return super().eventFilter(obj, event)

    def run(self, item):
        if item is None:
            return
        index = item.data(Qt.ItemDataRole.UserRole)
        action = self.commands[index][2] if isinstance(index, int) else None
        self.accept()
        if action is not None:
            QTimer.singleShot(0, action.trigger)   # after the palette has closed


def open_palette(window):
    palette = CommandPalette(window)
    palette.exec()
    return palette
