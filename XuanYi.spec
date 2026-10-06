# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

ROOT = Path(SPECPATH).resolve()

a = Analysis(
    [str(ROOT / 'XuanYi.py')], pathex=[str(ROOT)], binaries=[],
    datas=[(str(ROOT / name), '.') for name in ('LICENSE', 'NOTICE.md', 'README.md', 'XuanYi.ico')],
    hiddenimports=['win32crypt', 'win32timezone'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    # No main-tool automation, launcher, navigation or combat-extension packages.
    excludes=['src', 'wizwalker.extensions', 'wizlaunch', 'kinif', 'pypresence',
              'numpy', 'shapely', 'katsuba', 'wiztype', 'tkinter', 'OpenSSL', 'cryptography'],
    noarchive=False, optimize=1,
)

# Do not ship editor/Codex private runtime DLLs selected from the build environment.
for collection_name in ('binaries', 'datas'):
    collection = getattr(a, collection_name)
    collection[:] = [entry for entry in collection if not any(
        marker in str(Path(entry[1]).resolve()).replace('/', '\\').casefold()
        for marker in ('\\.cache\\codex-runtimes\\', '\\.codex\\tmp\\'))]

pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='XuanYi',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False, uac_admin=True,
    manifest=str(ROOT / 'XuanYi.manifest'), icon=str(ROOT / 'XuanYi.ico'))
