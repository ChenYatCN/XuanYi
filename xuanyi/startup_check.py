"""Packaging check only; no real settings, game connection or service request."""
def check():
    import json
    import os
    import ssl
    import sys
    import tempfile
    from pathlib import Path
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    import certifi
    from PyQt6.QtCore import QObject, pyqtSignal
    from PyQt6.QtWidgets import QApplication
    from .ui import MainWindow, APISettingsDialog, STYLE, ensure_ui_font, FONT_FAMILY, FONT_SIZE, ThemedCheckBox
    from .settings import Settings
    from .api import protect_api_key, unprotect_api_key

    class QuietBackend(QObject):
        event = pyqtSignal(dict)
        finished = pyqtSignal()
        def start(self):
            pass
        def command(self, *args, **kwargs):
            pass
        def isRunning(self):
            return False

    output = Path(sys.executable).parent / 'XuanYi-startup-check.json'
    if output.exists():
        return 2  # Preserve earlier diagnostics; never silently overwrite.
    result = {'game_connected': False, 'chat_sent': False, 'api_requested': False,
              'real_key_read': False}
    try:
        ssl.create_default_context(cafile=certifi.where())
        app = QApplication([])
        ensure_ui_font()
        app.setStyleSheet(STYLE)
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(Path(directory) / 'settings.json')
            assert settings.data['chat_translation_api_key_protected'] == ''
            window = MainWindow(settings=settings, backend=QuietBackend())
            window.show()
            app.processEvents()
            assert not window.listening and not window.translate_box.isChecked()
            assert window.author_label.text() == '作者:炙逸'
            assert window.messages.font().family() == FONT_FAMILY
            assert window.messages.font().pointSize() == FONT_SIZE
            assert not window.api_button.icon().isNull()
            assert not window.windowIcon().isNull()
            assert not window.windowIcon().pixmap(32, 32).isNull()
            assert isinstance(window.translate_box, ThemedCheckBox)
            assert window.clients.width() <= 260
            window.pin_button.click()
            assert window.pin_button.isChecked()
            window.pin_button.click()
            assert not window.pin_button.isChecked()
            dialog = APISettingsDialog(settings, window)
            dialog.show()
            app.processEvents()
            assert dialog.url.font().family() == FONT_FAMILY
            dialog.reject()
            window.handle_event({'kind': 'message', 'id': 1, 'channel': '附近', 'sender': '测试', 'message': 'hello'})
            window.handle_event({'kind': 'translation', 'id': 1, 'text': '你好'})
            assert '译文：你好' in window.messages.toPlainText()
            window.close()
            protected = protect_api_key('dummy-local-startup-check')
            assert unprotect_api_key(protected) == 'dummy-local-startup-check'
        result.update(qt_startup=True, native_crypto_round_trip=True,
                      empty_key_default=True, https_certificates_loaded=True,
                      ui_font_matches=True, author_credit_present=True, titlebar_svg_loaded=True,
                      application_icon_loaded=True, check_mark_control_loaded=True,
                      pin_button_toggles=True, compact_selector=True)
    except Exception as exc:
        result.update(error_type=type(exc).__name__, error=str(exc))
    with output.open('x', encoding='utf-8') as target:
        json.dump(result, target, ensure_ascii=False, indent=2)
    return 1 if 'error' in result else 0
