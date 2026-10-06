"""The entire standalone interface: history, API settings and manual send."""
from collections import deque
import os
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QSize, QRectF
from PyQt6.QtGui import QFont, QFontDatabase, QIcon, QPixmap, QPainter, QPainterPath, QRegion, QColor, QPen, QBrush
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit,
    QPushButton, QSizeGrip, QVBoxLayout, QWidget, QStyle, QStyleOptionButton)

from .api import ChatTranslationAPI, TranslationError, completion_url, protect_api_key, validate_model
from .backend import Backend
from .settings import Settings


FONT_FAMILY = 'Segoe UI'
FONT_SIZE = 9
# Snapshot of XuanShu's current UI palette, not linked to its private settings.
STYLE = '''
QWidget { background: #181825; color: #cdd6f4; font-family: "Segoe UI", "Microsoft YaHei"; font-size: 9pt; }
QWidget#ChatSurface, QDialog#APISettings { border: 1px solid #89dceb; border-radius: 8px; }
QLineEdit, QComboBox, QPlainTextEdit { background: #1e1e2e; color: #cdd6f4; }
QLineEdit, QComboBox { padding: 4px; border: 1px solid #45475a; border-radius: 4px; }
QPlainTextEdit { border: none; padding: 8px; selection-background-color: rgba(205,214,244,40); }
QComboBox QAbstractItemView { background: #1e1e2e; color: #cdd6f4; selection-background-color: rgba(205,214,244,25); }
QPushButton { background: #6c7086; color: white; border: none; border-radius: 4px; padding: 4px 8px; }
QPushButton:hover { background: #8a8ea4; }
QPushButton:pressed { background: #585c72; }
QPushButton:disabled { color: #7f849c; background: #313244; }
QLabel#AuthorCredit { color: #a6adc8; background: transparent; }
QScrollBar:vertical { width: 6px; background: transparent; margin: 0; }
QScrollBar:horizontal { height: 6px; background: transparent; margin: 0; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: rgba(205,214,244,40); border-radius: 3px; min-height: 20px; min-width: 20px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page, QScrollBar::sub-page, QAbstractScrollArea::corner { background: transparent; }
QToolTip { background: #1e1e2e; color: #cdd6f4; border: 1px solid #89dceb; border-radius: 4px; padding: 4px 6px; }
'''


class ThemedCheckBox(QCheckBox):
    """XuanShu's painted rounded indicator and contrasting check mark."""

    def __init__(self, text='', parent=None):
        super().__init__(text, parent)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            'QCheckBox { spacing: 6px; background: transparent; }'
            'QCheckBox::indicator { width: 16px; height: 16px; background: transparent; border: none; }')

    def paintEvent(self, event):
        option = QStyleOptionButton()
        self.initStyleOption(option)
        painter = QPainter(self)
        self.style().drawControl(QStyle.ControlElement.CE_CheckBox, option, painter, self)
        indicator = self.style().subElementRect(
            QStyle.SubElement.SE_CheckBoxIndicator, option, self).adjusted(1, 1, -1, -1)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        checked = self.isChecked()
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        enabled = self.isEnabled()
        accent, text, background = QColor('#89dceb'), QColor('#cdd6f4'), QColor('#1e1e2e')
        if not enabled:
            accent.setAlpha(90)
            text.setAlpha(70)
            background.setAlpha(70)
        border = QColor(accent if (checked or hovered) else text)
        if not checked and not hovered:
            border.setAlpha(90 if enabled else 50)
        painter.setPen(QPen(border, 1.4))
        painter.setBrush(QBrush(accent if checked else background))
        painter.drawRoundedRect(QRectF(indicator), 3.0, 3.0)
        if checked:
            mark = QColor('#11131f')
            if not enabled:
                mark.setAlpha(120)
            pen = QPen(mark, 2.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            x, y = indicator.x(), indicator.y()
            painter.drawLine(x + 3, y + 7, x + 6, y + 10)
            painter.drawLine(x + 6, y + 10, x + 12, y + 4)
        painter.end()


PIN_ON = '<path d="M12 17v5"/><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/>'
PIN_OFF = '<path d="M12 17v5"/><path d="M15 9.34V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H7.89"/><path d="m2 2 20 20"/><path d="M9 9v1.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h11"/>'


def ensure_ui_font():
    # Some Qt environments don't enumerate Windows fonts. Load an existing
    # system font directly rather than shipping Microsoft's font or tool assets.
    fonts = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    for family, filename in ((FONT_FAMILY, 'segoeui.ttf'), ('Microsoft YaHei', 'msyh.ttc')):
        if family not in QFontDatabase.families() and (fonts / filename).is_file():
            QFontDatabase.addApplicationFont(str(fonts / filename))
    QApplication.instance().setFont(QFont(FONT_FAMILY, FONT_SIZE))


def titlebar_icon(path):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#89dceb" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{path}</svg>'
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(svg.encode()).render(painter)
    painter.end()
    return QIcon(pixmap)


def titlebar_button(path, tooltip, action, *, close=False):
    # Same vector artwork, dimensions and hover treatment as XuanShu.
    button = QPushButton()
    button.setIcon(titlebar_icon(path))
    button.setIconSize(QSize(16, 16))
    button.setFixedSize(32, 24)
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)
    button.setAutoDefault(False)
    button.setDefault(False)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    hover = 'rgba(232,17,35,200)' if close else 'rgba(255,255,255,30)'
    button.setStyleSheet('QPushButton { background: transparent; border: none; padding: 4px; }'
                        f'QPushButton:hover {{ background: {hover}; border-radius: 4px; }}')
    button.clicked.connect(action)
    return button


def round_window(window):
    # Match the original window's Windows 11 rounding, with an older-system mask.
    import ctypes
    import ctypes.wintypes
    try:
        preference = ctypes.c_int(2)
        result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.wintypes.HWND(int(window.winId())), 33,
            ctypes.byref(preference), ctypes.sizeof(preference))
    except (AttributeError, OSError):
        result = -1
    if result == 0:
        window.clearMask()
    else:
        path = QPainterPath()
        path.addRoundedRect(0, 0, window.width(), window.height(), 8, 8)
        window.setMask(QRegion(path.toFillPolygon().toPolygon()))


def add_titlebar(window, layout, title, *, settings_action=None):
    window.setWindowFlag(Qt.WindowType.FramelessWindowHint)
    bar = QWidget()
    bar.setFixedHeight(32)
    row = QHBoxLayout(bar)
    row.setContentsMargins(4, 0, 4, 0)
    row.setSpacing(0)
    api_button = None
    if settings_action:
        window.pin_button = titlebar_button(PIN_OFF, '窗口未置顶（点击置顶）', window.toggle_topmost)
        window.pin_button.setCheckable(True)
        row.addWidget(window.pin_button)
        api_button = titlebar_button(
            '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
            '翻译 API 接口设置', settings_action)
        row.addWidget(api_button)
    else:
        row.addSpacing(64)
    label = QLabel(title)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet('font-weight: bold; background: transparent;')
    row.addWidget(label, 1)
    row.addWidget(titlebar_button('<path d="M5 12h14"/>', '最小化', window.showMinimized))
    row.addWidget(titlebar_button('<path d="M18 6 6 18M6 6l12 12"/>', '关闭', window.close, close=True))
    def drag(event):
        if event.button() == Qt.MouseButton.LeftButton and window.windowHandle():
            window.windowHandle().startSystemMove()
    bar.mousePressEvent = drag
    label.mousePressEvent = drag
    layout.addWidget(bar)
    return api_button


class APISettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setObjectName('APISettings')
        self.setWindowTitle('玄译 · API 接口设置')
        self.resize(620, 310)
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(8)
        add_titlebar(self, layout, '玄译 · API 接口设置')
        form = QFormLayout()
        self.url = QLineEdit(settings.data['chat_translation_api_url'])
        self.model = QLineEdit(settings.data['chat_translation_model'])
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setMaxLength(2048)
        self.key.setPlaceholderText('已保存；留空保留原 Key' if settings.data['chat_translation_api_key_protected'] else '填写你的 API Key')
        form.addRow('API 地址', self.url)
        form.addRow('模型', self.model)
        form.addRow('API Key', self.key)
        layout.addLayout(form)
        self.remove_key = ThemedCheckBox('删除已保存的 API Key')
        layout.addWidget(self.remove_key)
        info = QLabel('支持 DeepSeek / OpenAI 兼容接口。开启翻译或手动填入中文时，正文会发送至该服务，可能产生费用。\nKey 仅由当前 Windows 用户加密保存，不随 EXE 发布。此软件不自动回复。')
        info.setWordWrap(True)
        layout.addWidget(info)
        layout.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('保存')
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText('取消')
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.finished.connect(lambda _: self.key.clear())

    def showEvent(self, event):
        super().showEvent(event)
        round_window(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        round_window(self)

    def save(self):
        try:
            protected = self.settings.data['chat_translation_api_key_protected']
            if self.remove_key.isChecked():
                protected = ''
            elif self.key.text():
                protected = protect_api_key(self.key.text())
            self.settings.save({'chat_translation_api_url': completion_url(self.url.text()),
                                'chat_translation_model': validate_model(self.model.text()),
                                'chat_translation_api_key_protected': protected})
        except Exception as exc:
            QMessageBox.warning(self, '未保存', str(exc) if isinstance(exc, TranslationError) else '无法保存本地设置，请检查目录权限。')
            return
        self.accept()


class MainWindow(QMainWindow):
    def __init__(self, *, settings=None, backend=None):
        super().__init__()
        self.settings = settings or Settings()
        self.backend = backend or Backend(self)
        self.setWindowTitle('玄译 · XuanYi')
        icon_root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
        self.setWindowIcon(QIcon(str(icon_root / 'XuanYi.ico')))
        self.resize(720, 520)
        self.setMinimumSize(620, 440)
        self.listening = False
        self.sending = False
        self.closing = False
        self.allow_close = False
        self.history = deque(maxlen=200)
        self.pending_text = None
        widget = QWidget()
        widget.setObjectName('ChatSurface')
        self.setCentralWidget(widget)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(8)
        self.api_button = add_titlebar(self, layout, '玄译 · XuanYi',
                                      settings_action=self.open_api_settings)
        row = QHBoxLayout()
        row.addWidget(QLabel('游戏窗口'))
        self.clients = QComboBox()
        self.clients.addItem('等待游戏客户端…', None)
        self.clients.setMinimumWidth(190)
        self.clients.setMaximumWidth(260)
        row.addWidget(self.clients)
        self.read_button = QPushButton('开始读取')
        self.read_button.clicked.connect(self.toggle_reading)
        row.addWidget(self.read_button)
        row.addStretch()
        layout.addLayout(row)
        row = QHBoxLayout()
        self.translate_box = ThemedCheckBox('自动翻译收到的聊天')
        self.translate_box.toggled.connect(self.toggle_translation)
        row.addWidget(self.translate_box)
        row.addStretch()
        clear = QPushButton('清空记录')
        clear.clicked.connect(self.clear_history)
        row.addWidget(clear)
        layout.addLayout(row)
        self.messages = QPlainTextEdit()
        self.messages.setReadOnly(True)
        self.messages.setMaximumBlockCount(600)
        self.messages.setPlaceholderText('展开游戏聊天记录并开始读取后，这里显示新消息和译文。\n不会翻译连接前的历史，不自动回复。')
        layout.addWidget(self.messages, 1)
        self.read_status = QLabel('读取：未启动')
        self.read_status.setWordWrap(True)
        self.translation_status = QLabel('翻译：未启用')
        self.translation_status.setWordWrap(True)
        layout.addWidget(self.read_status)
        layout.addWidget(self.translation_status)
        send_row = QHBoxLayout()
        self.send_text = QLineEdit()
        self.send_text.setMaxLength(80)
        self.send_text.setPlaceholderText('中文译成英文填入，英文直接填入（频道在游戏里选择）')
        self.send_text.returnPressed.connect(self.send_message)
        send_row.addWidget(self.send_text, 1)
        self.send_button = QPushButton('翻译并填入')
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self.send_message)
        send_row.addWidget(self.send_button)
        layout.addLayout(send_row)
        self.send_status = QLabel('先在游戏里选择频道/私聊对象并展开空输入栏；填入后由你发送。')
        self.send_status.setWordWrap(True)
        layout.addWidget(self.send_status)
        footer = QHBoxLayout()
        footer.addStretch()
        self.author_label = QLabel('作者:炙逸')
        self.author_label.setObjectName('AuthorCredit')
        self.author_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        footer.addWidget(self.author_label)
        self.size_grip = QSizeGrip(self)
        self.size_grip.setFixedSize(14, 14)
        footer.addWidget(self.size_grip)
        layout.addLayout(footer)
        self.backend.event.connect(self.handle_event)
        self.backend.finished.connect(self.backend_finished)
        self.backend.start()
        self.configure_api()

    def showEvent(self, event):
        super().showEvent(event)
        round_window(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        round_window(self)

    def configure_api(self):
        self.backend.command('api', options=dict(self.settings.data), enabled=self.translate_box.isChecked())

    def open_api_settings(self):
        if APISettingsDialog(self.settings, self).exec() == QDialog.DialogCode.Accepted:
            if self.translate_box.isChecked() and not self.settings.data['chat_translation_api_key_protected']:
                self.translate_box.blockSignals(True)
                self.translate_box.setChecked(False)
                self.translate_box.blockSignals(False)
            self.configure_api()

    def toggle_translation(self, enabled):
        if enabled:
            try:
                ChatTranslationAPI(self.settings.data)  # Local validation, no HTTP request.
            except TranslationError as exc:
                self.translate_box.blockSignals(True)
                self.translate_box.setChecked(False)
                self.translate_box.blockSignals(False)
                QMessageBox.warning(self, '请先配置接口', str(exc))
                return
        self.configure_api()

    def toggle_topmost(self, enabled):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
        self.pin_button.setChecked(enabled)
        self.pin_button.setIcon(titlebar_icon(PIN_ON if enabled else PIN_OFF))
        tip = '窗口已置顶（点击取消）' if enabled else '窗口未置顶（点击置顶）'
        self.pin_button.setToolTip(tip)
        self.pin_button.setAccessibleName(tip)
        self.show()

    def toggle_reading(self):
        target = self.clients.currentData()
        if not self.listening and target is None:
            self.read_status.setText('未找到游戏窗口，请先启动游戏。')
            return
        self.listening = not self.listening
        self.update_buttons()
        self.backend.command('listen', handle=target['handle'] if target else None, enabled=self.listening)

    def update_buttons(self):
        self.read_button.setText('停止读取' if self.listening else '开始读取')
        self.clients.setEnabled(not self.listening and not self.sending and not self.closing)
        self.read_button.setEnabled(not self.closing)
        self.send_text.setEnabled(not self.sending and not self.closing)
        self.send_button.setEnabled(self.listening and not self.sending and not self.closing)

    def send_message(self):
        if not self.listening or self.sending or self.closing:
            return
        if not self.send_text.text().strip():
            return
        self.sending = True
        self.pending_text = self.send_text.text()
        self.update_buttons()
        self.backend.command('send', text=self.pending_text)

    def clear_history(self):
        self.history.clear()
        self.messages.clear()

    def render_history(self):
        scroll = self.messages.verticalScrollBar()
        position, bottom = scroll.value(), scroll.value() >= scroll.maximum()
        self.messages.setPlainText('\n\n'.join(
            f"[{row['channel']}] {row['sender']}：{row['message']}" +
            ('\n译文：' + row['translation'] if row.get('translation') else '')
            for row in self.history))
        scroll.setValue(scroll.maximum() if bottom else position)

    def handle_event(self, event):
        kind = event['kind']
        if kind == 'clients':
            selected = self.clients.currentData()
            self.clients.clear()
            for client in event['clients']:
                self.clients.addItem(f"{client['title']}（PID {client['pid']}）", client)
            if self.clients.count() == 0:
                self.clients.addItem('等待游戏客户端…', None)
            if selected:
                for index in range(self.clients.count()):
                    item = self.clients.itemData(index)
                    if item and item['handle'] == selected['handle']:
                        self.clients.setCurrentIndex(index)
                        break
        elif kind == 'status':
            self.read_status.setText(event['status'])
        elif kind == 'translation_status':
            self.translation_status.setText(event['status'])
        elif kind == 'listening':
            self.listening = event['enabled']
            self.update_buttons()
        elif kind == 'message':
            self.history.append(dict(event))
            self.render_history()
        elif kind == 'translation':
            for row in self.history:
                if row['id'] == event['id']:
                    row['translation'] = event['text']
                    self.render_history()
                    break
        elif kind in ('send_status', 'send_done', 'send_busy'):
            self.send_status.setText(event['status'])
            if kind == 'send_done':
                self.sending = False
                self.update_buttons()

    def closeEvent(self, event):
        if self.allow_close or not self.backend.isRunning():
            event.accept()
            return
        self.closing = True
        self.read_status.setText('正在断开自己的连接；接口请求最迟在超时后结束…')
        self.update_buttons()
        self.backend.command('shutdown')
        event.ignore()

    def backend_finished(self):
        if self.closing:
            self.allow_close = True
            self.close()
        else:
            self.listening = False
            self.sending = False
            self.update_buttons()


def launch():
    # Keep the standalone app's taskbar identity separate from Python/XuanShu.
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('xuanshu.XuanYi')
    except (AttributeError, OSError):
        pass
    app = QApplication(sys.argv)
    app.setApplicationName('XuanYi')
    app.setApplicationDisplayName('玄译 · XuanYi')
    ensure_ui_font()
    app.setStyleSheet(STYLE)
    window = MainWindow()
    app.setWindowIcon(window.windowIcon())
    window.show()
    return app.exec()
