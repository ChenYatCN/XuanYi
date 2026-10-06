"""Independent user settings; no import of the full tool's saved credentials."""
import json
import os
import tempfile
from pathlib import Path

from .api import DEFAULT_API_URL, DEFAULT_API_MODEL


DEFAULTS = {
    'chat_translation_api_url': DEFAULT_API_URL,
    'chat_translation_model': DEFAULT_API_MODEL,
    'chat_translation_api_key_protected': '',
}


class Settings:
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(os.environ.get('APPDATA') or Path.home()) / 'XuanYi' / 'settings.json'
        self.data = dict(DEFAULTS)
        load_path = self.path
        if path is None and not self.path.exists():
            # Keep old standalone settings usable, without modifying/deleting
            # them or reading any settings belonging to the full XuanShu app.
            load_path = self.path.parent.parent / 'Wizard101ChatTranslator' / 'settings.json'
        try:
            loaded = json.loads(load_path.read_text(encoding='utf-8'))
            if isinstance(loaded, dict):
                self.data.update({key: value for key, value in loaded.items()
                                  if key in DEFAULTS and isinstance(value, str)})
        except (OSError, ValueError):
            pass

    def save(self, values):
        updated = {**self.data, **{key: value for key, value in values.items() if key in DEFAULTS}}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=self.path.parent,
                                             prefix='settings-', suffix='.tmp', delete=False) as target:
                temporary_path = Path(target.name)
                json.dump(updated, target, ensure_ascii=False, indent=2)
            os.replace(temporary_path, self.path)
            self.data = updated
        finally:
            if temporary_path and temporary_path.exists():
                temporary_path.unlink()
