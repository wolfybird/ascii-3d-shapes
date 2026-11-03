# -*- mode: python ; coding: utf-8 -*-
import os
import stat


a = Analysis(
    ['shapes_v9-6.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ASCII3DShapes',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# Folders under OneDrive can turn read-only, and Windows won't delete a
# read-only folder, so COLLECT's removal of the previous build fails with
# "Access is denied". Clear the flag on the old build first.
for dirpath, _, filenames in os.walk(os.path.join(DISTPATH, 'ASCII3DShapes')):
    for path in [dirpath] + [os.path.join(dirpath, f) for f in filenames]:
        os.chmod(path, os.stat(path).st_mode | stat.S_IWRITE)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='ASCII3DShapes',
)
