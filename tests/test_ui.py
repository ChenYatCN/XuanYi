import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

import tempfile
import unittest
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLineEdit, QCheckBox
from xuanyi.settings import Settings
from xuanyi.ui import MainWindow, APISettingsDialog, STYLE, ensure_ui_font, FONT_FAMILY, FONT_SIZE, ThemedCheckBox


class FakeBackend(QObject):
    event = pyqtSignal(dict)
    finished = pyqtSignal()
    def __init__(self):
        super().__init__()
        self.commands = []
    def command(self, kind, **values):
        self.commands.append((kind, values))
    def start(self):
        pass
    def isRunning(self):
        return False


class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        ensure_ui_font()
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings = Settings(Path(self.temp.name) / 'settings.json')
        self.backend = FakeBackend()
        self.window = MainWindow(settings=self.settings, backend=self.backend)

    def tearDown(self):
        self.window.close()
        self.temp.cleanup()

    def test_starts_without_listening_translation_or_secret(self):
        self.assertFalse(self.window.listening)
        self.assertFalse(self.window.translate_box.isChecked())
        self.assertFalse(self.window.send_button.isEnabled())
        self.assertEqual(self.backend.commands[0][0], 'api')
        self.assertEqual(self.backend.commands[0][1]['options']['chat_translation_api_key_protected'], '')

    def test_plain_original_and_correlated_translation(self):
        self.window.handle_event({'kind': 'message', 'id': 7, 'channel': '附近',
                                  'sender': 'Amber', 'message': '<b>hello</b>'})
        self.window.handle_event({'kind': 'translation', 'id': 7, 'text': '你好'})
        self.assertIn('<b>hello</b>', self.window.messages.toPlainText())
        self.assertIn('译文：你好', self.window.messages.toPlainText())
        self.window.clear_history()
        self.assertEqual(self.window.messages.toPlainText(), '')

    def test_send_is_explicit_and_cannot_be_queued_twice(self):
        self.window.handle_event({'kind': 'clients', 'clients': [{'pid': 3, 'handle': 123, 'title': 'Wizard101'}]})
        self.window.toggle_reading()
        self.window.send_text.setText('hello')
        self.window.send_message()
        self.window.send_message()
        self.assertEqual(len([c for c in self.backend.commands if c[0] == 'send']), 1)
        self.window.handle_event({'kind': 'send_done', 'status': '已填入', 'filled': True, 'invoked': False})
        self.assertEqual(self.window.send_text.text(), 'hello')
        self.assertFalse(self.window.sending)

    def test_api_dialog_never_populates_saved_key(self):
        self.settings.data['chat_translation_api_key_protected'] = 'encrypted-dummy'
        dialog = APISettingsDialog(self.settings, self.window)
        self.assertEqual(dialog.key.text(), '')
        self.assertEqual(dialog.key.echoMode(), QLineEdit.EchoMode.Password)
        self.assertIn('已保存', dialog.key.placeholderText())
        dialog.reject()

    def test_original_style_font_and_author_are_outside_history(self):
        self.window.show()
        self.app.processEvents()
        self.assertTrue(self.window.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertEqual(self.window.messages.font().family(), FONT_FAMILY)
        self.assertEqual(self.window.messages.font().pointSize(), FONT_SIZE)
        self.assertEqual(self.window.author_label.text(), '作者:炙逸')
        self.assertEqual(self.window.windowTitle(), '玄译 · XuanYi')
        self.assertEqual(self.window.send_button.text(), '翻译并填入')
        self.assertTrue(self.window.author_label.isVisible())
        self.assertGreater(self.window.author_label.y(), self.window.send_text.y())
        self.assertNotIn('作者', self.window.messages.toPlainText())
        self.assertFalse(self.window.api_button.icon().isNull())

    def test_titlebar_does_not_change_return_send_behavior(self):
        self.window.handle_event({'kind': 'clients', 'clients': [{'pid': 3, 'handle': 123, 'title': 'Wizard101'}]})
        self.window.toggle_reading()
        self.window.show()
        self.window.send_text.setText('hello')
        self.window.send_text.setFocus()
        QTest.keyClick(self.window.send_text, Qt.Key.Key_Return)
        self.assertEqual(len([c for c in self.backend.commands if c[0] == 'send']), 1)
        self.assertFalse(self.window.isMinimized())

    def test_api_dialog_matches_window_frame_and_font(self):
        dialog = APISettingsDialog(self.settings, self.window)
        dialog.show()
        self.app.processEvents()
        self.assertTrue(dialog.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertEqual(dialog.url.font().family(), FONT_FAMILY)
        self.assertEqual(dialog.url.font().pointSize(), FONT_SIZE)
        self.assertGreaterEqual(dialog.height(), dialog.minimumSizeHint().height())
        dialog.reject()

    def test_application_icon_loads_from_project_asset(self):
        self.assertFalse(self.window.windowIcon().isNull())
        for size in (16, 32, 48, 256):
            self.assertFalse(self.window.windowIcon().pixmap(size, size).isNull())

    def test_topmost_icon_next_to_settings_toggles_without_backend_commands(self):
        self.window.show()
        self.app.processEvents()
        self.assertFalse(self.window.pin_button.isChecked())
        self.assertEqual(self.window.pin_button.parent(), self.window.api_button.parent())
        self.assertLess(self.window.pin_button.x(), self.window.api_button.x())
        self.assertFalse(any(c.text() == '窗口置顶' for c in self.window.findChildren(QCheckBox)))
        original_commands = list(self.backend.commands)
        off_icon = self.window.pin_button.icon().cacheKey()
        self.window.pin_button.click()
        self.assertTrue(self.window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.assertTrue(self.window.pin_button.isChecked())
        self.assertIn('已置顶', self.window.pin_button.toolTip())
        self.assertNotEqual(self.window.pin_button.icon().cacheKey(), off_icon)
        self.window.pin_button.click()
        self.assertFalse(self.window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.assertFalse(self.window.pin_button.isChecked())
        self.assertEqual(self.backend.commands, original_commands)

    def test_check_mark_indicator_and_compact_client_selector(self):
        self.window.show()
        self.app.processEvents()
        self.assertIsInstance(self.window.translate_box, ThemedCheckBox)
        self.assertLessEqual(self.window.clients.width(), 260)
        self.assertGreater(self.window.clients.width(), 180)
        dialog = APISettingsDialog(self.settings, self.window)
        self.assertIsInstance(dialog.remove_key, ThemedCheckBox)
        dialog.reject()
        box = self.window.translate_box
        box.blockSignals(True)  # Only paint synthetic states, never enable API.
        off = box.grab().toImage()
        box.setChecked(True)
        on = box.grab().toImage()
        self.assertNotEqual(on, off)
        # A checked indicator has a dark contrasting mark, not a solid square.
        dark = sum(on.pixelColor(x, y).red() < 30 and on.pixelColor(x, y).green() < 30
                   for x in range(3, 15) for y in range(3, 15))
        self.assertGreater(dark, 5)
        box.setChecked(False)
        box.blockSignals(False)
