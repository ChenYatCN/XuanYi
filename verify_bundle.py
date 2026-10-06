"""Read-only audit of a standalone PyInstaller bundle; do not extract/run it."""
import json
import sys
import struct
from pathlib import Path

import pefile
from PyInstaller.archive.readers import CArchiveReader


def inspect(path):
    reader = CArchiveReader(str(path))
    names = set(reader.toc)
    archive = next(name for name in names if name.endswith('.pyz'))
    pyz = reader.open_embedded_archive(archive)
    modules = set(pyz.toc)
    forbidden_prefixes = ('src', 'chattranslator', 'wizwalker.extensions', 'wizlaunch', 'kinif', 'pypresence', 'numpy', 'shapely', 'katsuba', 'wiztype')
    forbidden_modules = sorted(module for module in modules if any(
        module == prefix or module.startswith(prefix + '.') for prefix in forbidden_prefixes))
    forbidden_files = sorted(name for name in names if any(
        marker in name.replace('\\', '/').casefold() for marker in ('settings.json', '.env', 'chat_native_', 'xuanshu.py')))
    required = {'xuanyi.reader', 'xuanyi.sender', 'xuanyi.api', 'xuanyi.ui',
                'xuanyi.backend', 'xuanyi.chat_log', 'xuanyi.settings',
                'xuanyi.window_text'}
    missing = sorted(required - modules)
    # Embedded default credentials must be empty, regardless of user's settings.
    import marshal
    settings_code = marshal.loads(pyz.extract('xuanyi.settings', raw=True))
    namespace = {'__name__': 'xuanyi.settings', '__package__': 'xuanyi'}
    exec(settings_code, namespace)
    empty_default = namespace['DEFAULTS']['chat_translation_api_key_protected'] == ''
    crypto_native = any(Path(name).name.casefold() == 'win32crypt.pyd' for name in names)
    pe = pefile.PE(str(path))
    icon_data = (Path(__file__).resolve().parent / 'XuanYi.ico').read_bytes()
    reserved, kind, count = struct.unpack_from('<HHH', icon_data)
    assert reserved == 0 and kind == 1 and count > 0, 'Invalid application icon'
    expected_icons = []
    for index in range(count):
        size, offset = struct.unpack_from('<II', icon_data, 6 + index * 16 + 8)
        expected_icons.append(icon_data[offset:offset + size])
    actual_icons = []
    manifests = []
    for kind in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if kind.id == pefile.RESOURCE_TYPE['RT_ICON']:
            for entry in kind.directory.entries:
                for language in entry.directory.entries:
                    data = language.data.struct
                    actual_icons.append(pe.get_data(data.OffsetToData, data.Size))
        if kind.id == pefile.RESOURCE_TYPE['RT_MANIFEST']:
            for entry in kind.directory.entries:
                for language in entry.directory.entries:
                    data = language.data.struct
                    manifests.append(pe.get_data(data.OffsetToData, data.Size).decode('utf-8'))
    pe.close()
    admin_manifest = any('level="requireAdministrator"' in value for value in manifests)
    exe_icon_matches = sorted(actual_icons) == sorted(expected_icons)
    bundled_icon_matches = 'XuanYi.ico' in names and reader.extract('XuanYi.ico') == icon_data
    result = {'file': str(Path(path).resolve()), 'bytes': Path(path).stat().st_size,
              'private_settings_bundled': bool(forbidden_files), 'forbidden_modules': forbidden_modules,
              'missing_required_modules': missing, 'embedded_key_default_empty': empty_default,
              'native_crypto_bundled': crypto_native, 'administrator_manifest': admin_manifest,
              'exe_icon_matches': exe_icon_matches, 'bundled_icon_matches': bundled_icon_matches}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if forbidden_modules or forbidden_files or missing or not empty_default or not crypto_native or not admin_manifest or not exe_icon_matches or not bundled_icon_matches:
        raise SystemExit('Standalone bundle audit failed')


if __name__ == '__main__':
    inspect(sys.argv[1])
