# PyInstaller build for Biggest Highway.
#   .venv\Scripts\pyinstaller BiggestHighway.spec --noconfirm
# Set ONEDIR=1 to get a folder build instead of a single .exe (faster to start).
import os

from PyInstaller.utils.hooks import collect_all

datas = [('assets', 'assets')]
binaries = []
hiddenimports = []
for pkg in ('ursina', 'panda3d', 'gltf', 'simplepbr', 'direct', 'screeninfo'):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=['pytest', 'tkinter', 'unittest', 'pydoc_data'],
    noarchive=False,
)
pyz = PYZ(a.pure)
onedir = os.environ.get('ONEDIR') == '1'
console = os.environ.get('CONSOLE') == '1'

if onedir:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='BiggestHighway',
              icon='assets/icon.ico', console=console, upx=False)
    coll = COLLECT(exe, a.binaries, a.datas, name='BiggestHighway', upx=False)
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='BiggestHighway',
              icon='assets/icon.ico', console=console, upx=False, runtime_tmpdir=None)
