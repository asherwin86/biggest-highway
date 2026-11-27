"""Android build of Biggest Highway (Panda3D build_apps). Not needed to play on a PC.

Use android\\build_apk.ps1, which sets everything up and runs:
    .venv-android\\Scripts\\python setup.py bdist_apps
and then turns the .aab bundle into an installable APK with bundletool.
"""
import os
import shutil
import time
from pathlib import Path

from setuptools import setup

from direct.dist.commands import build_apps

from game.version import VERSION

ROOT = Path(__file__).resolve().parent
APP_ID = 'io.github.asherwin86.biggesthighway'

# 1.1.0 -> 10100: Android needs a bigger number for every new version
_v = [int(p) for p in VERSION.split('.')] + [0, 0]
VERSION_CODE = _v[0] * 10000 + _v[1] * 100 + _v[2]

PRC = """
load-display pandagles2
notify-level warning
default-directnotify-level warning
framebuffer-multisample 0
sync-video true
"""

# testing builds (BH_DEBUGGABLE=1): say more about graphics in `adb logcat`
DEBUG_PRC = """
notify-level-display info
notify-level-gles2gsg info
notify-level-android info
gl-check-errors true
"""

# Ursina's own fonts, textures and models (it looks for them on disk, see game/device.py)
URSINA_DATA = ('fonts', 'textures', 'models_compressed', 'audio')


class AndroidBuildApps(build_apps):
    def build_binaries(self, platform, binary_dir, *args, **kwargs):
        super().build_binaries(platform, binary_dir, *args, **kwargs)
        if platform.startswith('android'):
            self._fix_python_modules(platform, binary_dir)

    def _fix_python_modules(self, platform, binary_dir):
        """Python on Android loads extension modules as lib/<abi>/libpy.<name>.so.
        Built on a Windows PC, build_apps leaves some with their long CPython names
        (libpy.math.cpython-313-....so, which Android can't find) and misses others
        for some ABIs. Put every module from the Panda3D wheel there, named right."""
        import re
        import zipfile
        whl_dir = Path(self.build_base) / '__whl_cache__' / f'{platform}_cp313'
        whl = next(whl_dir.glob('panda3d-*.whl'))
        out = Path(binary_dir)
        with zipfile.ZipFile(whl) as z:
            for name in z.namelist():
                if not (name.startswith('deploy_libs/') and name.endswith('.so')):
                    continue
                base = name.rsplit('/', 1)[1]
                if base.startswith('lib'):                 # libssl_python.so etc.: needed by the modules
                    if base in ('libdeploy-stubw.so', 'libsqlite3_python.so'):
                        continue
                    target = out / base
                else:
                    mod = base.split('.', 1)[0]
                    if mod.startswith(('_test', '_xxtest', '_ctypes_test', '_sqlite3')):
                        continue
                    target = out / f'libpy.{mod}.so'
                if not target.exists() and base != 'libdeploy-stubw.so':
                    target.write_bytes(z.read(name))
        for f in out.iterdir():
            m = re.match(r'libpy\.(.+?)\.cpython-\d+-.+\.so$', f.name)
            if m or re.match(r'libpy\._test', f.name):
                short = out / f'libpy.{m.group(1)}.so' if m else None
                if short is not None and not short.exists():
                    f.rename(short)
                else:
                    f.unlink()

    def generate_android_manifest(self, path):
        super().generate_android_manifest(path)
        import xml.etree.ElementTree as ET
        ns = 'http://schemas.android.com/apk/res/android'
        ET.register_namespace('android', ns)
        tree = ET.parse(path)
        for act in tree.getroot().iter('activity'):
            act.set(f'{{{ns}}}screenOrientation', 'sensorLandscape')    # a driving game: landscape only
        for app in tree.getroot().iter('application'):
            # compressed native libraries: about half the download (they're unpacked on install)
            app.set(f'{{{ns}}}extractNativeLibs', 'true')
        tree.write(path, encoding='utf-8', xml_declaration=True)

    def build_assets(self, platform, data_dir):
        super().build_assets(platform, data_dir)
        import ursina
        src = Path(ursina.__file__).resolve().parent
        dst = Path(data_dir) / 'ursina_data'
        for name in URSINA_DATA:
            if (src / name).is_dir():
                shutil.copytree(src / name, dst / name, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns('*.py', '*.pyc', '__pycache__', '*.blend*'))
        # a new stamp makes the app copy its files out of the APK again after an update
        (Path(data_dir) / 'android_build.txt').write_text(f'{VERSION} {time.time():.0f}', encoding='utf-8')


setup(
    name='Biggest Highway',
    version=VERSION,
    options={
        'build_apps': {
            'application_id': APP_ID,
            'android_version_code': VERSION_CODE,
            # 35+ forces edge-to-edge: the status bar stays on top and Panda3D's touch
            # positions come out shifted by its height. 34 keeps a real fullscreen window.
            'android_target_sdk_version': 34,
            'android_debuggable': os.environ.get('BH_DEBUGGABLE') == '1',      # lets adb run-as look inside (testing)
            # BH_ABIS=x86_64 makes a quicker build for the emulator only
            'android_abis': os.environ.get('BH_ABIS', 'arm64-v8a,armeabi-v7a,x86_64').split(','),
            'gui_apps': {'BiggestHighway': 'main.py'},
            'platforms': ['android'],
            'plugins': ['pandagles2', 'p3openal_audio'],
            'requirements_path': str(ROOT / 'android' / 'requirements.txt'),
            'include_patterns': ['assets/models/*.glb', 'assets/icon.png'],
            'bam_model_extensions': [],          # keep the .glb car models; Ursina loads them itself
            'include_modules': {'*': ['game.*', 'game.ui.*', 'game.world.*', 'ursina.*', 'ursina.prefabs.*',
                                      'ursina.shaders.*', 'ursina.scripts.*', 'gltf', 'gltf.*',
                                      'screeninfo', 'screeninfo.*']},
            'exclude_modules': {'*': ['tkinter', 'PIL', 'numpy', 'pytest', '_pytest', 'PyInstaller']},
            'extra_prc_data': PRC + (DEBUG_PRC if os.environ.get('BH_DEBUGGABLE') == '1' else ''),
            'icons': {'*': ['assets/icon.png']},
            'build_base': str(ROOT / 'build-android' / 'build'),
        },
        'bdist_apps': {
            'dist_dir': str(ROOT / 'build-android' / 'dist'),
        },
    },
    cmdclass={'build_apps': AndroidBuildApps},
    classifiers=['Topic :: Games/Entertainment'],
)
