import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from xuanyi.api import protect_api_key, unprotect_api_key
from xuanyi.settings import Settings


class SettingsTests(unittest.TestCase):
    def test_new_brand_reads_legacy_standalone_settings_without_overwriting_them(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'APPDATA': directory}):
            legacy = Path(directory) / 'Wizard101ChatTranslator' / 'settings.json'
            legacy.parent.mkdir()
            legacy.write_text(json.dumps({'chat_translation_model': 'legacy-test-model',
                                          'chat_translation_api_key_protected': 'encrypted-test-dummy'}), encoding='utf-8')
            original = legacy.read_bytes()
            settings = Settings()
            self.assertEqual(settings.path, Path(directory) / 'XuanYi' / 'settings.json')
            self.assertEqual(settings.data['chat_translation_model'], 'legacy-test-model')
            self.assertEqual(settings.data['chat_translation_api_key_protected'], 'encrypted-test-dummy')
            settings.save({'chat_translation_model': 'new-test-model'})
            self.assertEqual(legacy.read_bytes(), original)
            self.assertEqual(Settings().data['chat_translation_model'], 'new-test-model')

    def test_explicit_test_path_never_reads_legacy_settings(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'APPDATA': directory}):
            settings = Settings(Path(directory) / 'isolated' / 'settings.json')
            self.assertEqual(settings.data['chat_translation_api_key_protected'], '')

    def test_new_config_empty_key_and_no_auto_translation_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            settings = Settings(path)
            self.assertEqual(settings.data['chat_translation_api_key_protected'], '')
            self.assertFalse(path.exists())

    def test_dummy_key_round_trip_is_encrypted_and_independent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            key = 'dummy-key-for-local-test-only'
            # Unit test with mocked OS crypto. Real user-scope DPAPI is checked
            # separately because the terminal sandbox has no usable master key.
            crypto = patch('win32crypt.CryptProtectData', return_value=b'unit-encrypted-blob')
            uncrypto = patch('win32crypt.CryptUnprotectData', return_value=('test', key.encode('utf-8')))
            with crypto:
                protected = protect_api_key(key)
            self.assertNotEqual(protected, key)
            settings = Settings(path)
            settings.save({'chat_translation_api_key_protected': protected, 'unrelated': 'ignored'})
            self.assertNotIn(key, path.read_text(encoding='utf-8'))
            self.assertNotIn('unrelated', json.loads(path.read_text(encoding='utf-8')))
            loaded = Settings(path)
            with uncrypto:
                self.assertEqual(unprotect_api_key(loaded.data['chat_translation_api_key_protected']), key)
            loaded.save({'chat_translation_api_key_protected': ''})
            self.assertEqual(Settings(path).data['chat_translation_api_key_protected'], '')

    def test_corrupt_and_non_object_config_defaults_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'settings.json'
            for payload in ('{bad', '[]', '{"chat_translation_model": 4}'):
                path.write_text(payload, encoding='utf-8')
                self.assertEqual(Settings(path).data['chat_translation_model'], 'deepseek-flash')
