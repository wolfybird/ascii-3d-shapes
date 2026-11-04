# -*- mode: python ; coding: utf-8 -*-
# Builds the app for the OS it runs on: pyinstaller ASCII3DShapes.spec
#   Windows  dist/ASCII3DShapes/ASCII3DShapes.exe (window) and
#            ASCII3DShapes-terminal.exe (terminal mode, opens a console)
#   macOS    dist/ASCII3DShapes.app
#   Linux    dist/ASCII3DShapes/ASCII3DShapes
import os
import stat
import sys

APP = 'ASCII3DShapes'
SCRIPT = 'shapes_v10.py'
VERSION = '10.0'


a = Analysis(
    [SCRIPT],
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


def make_exe(name, console):
    return EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=name,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=console,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )


exes = [make_exe(APP, console=False)]
if sys.platform == 'win32':
    exes.append(make_exe(APP + '-terminal', console=True))

# Folders under OneDrive can turn read-only, and Windows won't delete a
# read-only folder, so COLLECT's removal of the previous build fails with
# "Access is denied". Clear the flag on the old build first.
for dirpath, _, filenames in os.walk(os.path.join(DISTPATH, APP)):
    for path in [dirpath] + [os.path.join(dirpath, f) for f in filenames]:
        os.chmod(path, os.stat(path).st_mode | stat.S_IWRITE)

coll = COLLECT(
    *exes,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP,
)

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name=APP + '.app',
        bundle_identifier='io.github.wolfybird.ascii3dshapes',
        version=VERSION,
        info_plist={
            'CFBundleDisplayName': 'ASCII 3D Shapes',
            'NSHighResolutionCapable': True,
            # without this macOS stops the app when audio mode opens the mic
            'NSMicrophoneUsageDescription':
                'Audio mode makes the shapes react to sound from your microphone.',
        },
    )
