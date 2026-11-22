"""What kind of device the game runs on: a PC, or an Android phone/tablet.

Pure Python (no engine imports at module level), so config.py and the tests can use it.

On Android the game is packaged with Panda3D's build_apps (see setup.py). The
game's files sit inside the APK, which Panda3D mounts as a virtual folder
(/android_asset). Ursina looks for models, textures and fonts on the real disk,
so on the first start (and after every update) prepare_android_files() copies
them to the app's private storage.
"""
import os
import sys
from pathlib import Path

IS_ANDROID = (sys.platform == 'android' or hasattr(sys, 'getandroidapilevel')
              or 'ANDROID_ARGUMENT' in os.environ)

# touch-screen controls: always on Android, or with --touch on a PC (for testing)
TOUCH = IS_ANDROID

ASSET_MOUNT = '/android_asset'
BUILD_STAMP = 'android_build.txt'     # written by setup.py; a new APK has a new stamp


def enable_touch(on=True):
    global TOUCH
    TOUCH = bool(on) or IS_ANDROID


def android_data_dir() -> Path:
    """The app's private, writable folder (for example /data/user/0/<app id>)."""
    from panda3d.core import ConfigVariableFilename, Filename
    # Panda3D points model-cache-dir at the app's cache folder; its parent is the data folder
    cache = ConfigVariableFilename('model-cache-dir', Filename()).getValue()
    if not cache.empty():
        d = Path(cache.toOsSpecific()).parent
        if d.is_dir():
            return d
    for cand in (Filename.getUserAppdataDirectory().toOsSpecific(), os.environ.get('HOME', ''),
                 os.environ.get('TMPDIR', '')):
        if cand and os.path.isdir(cand) and os.access(cand, os.W_OK):
            return Path(cand)
    return Path.cwd()


def prepare_android_files() -> Path:
    """Copy the files packed in the APK to <data>/files/game (only when they changed)
    and return that folder."""
    from panda3d.core import Filename, VirtualFileSystem
    vfs = VirtualFileSystem.getGlobalPtr()
    root = android_data_dir() / 'files' / 'game'
    stamp_v = Filename(f'{ASSET_MOUNT}/{BUILD_STAMP}')
    want = vfs.readFile(stamp_v, True).decode('utf-8', 'replace') if vfs.exists(stamp_v) else 'none'
    stamp = root / BUILD_STAMP
    try:
        have = stamp.read_text(encoding='utf-8')
    except OSError:
        have = ''
    if have != want or want == 'none':
        _copy_tree(vfs, ASSET_MOUNT, root)
        stamp.write_text(want, encoding='utf-8')
    return root


def _copy_tree(vfs, src: str, dst: Path):
    from panda3d.core import Filename
    dst.mkdir(parents=True, exist_ok=True)
    listing = vfs.scanDirectory(Filename(src))
    if listing is None:
        return
    for f in listing.getFiles():
        name = f.getFilename().getBasename()
        if f.isDirectory():
            _copy_tree(vfs, f'{src}/{name}', dst / name)
        else:
            (dst / name).write_bytes(vfs.readFile(f.getFilename(), True))


def point_ursina_at(root: Path):
    """Ursina finds its own fonts/textures/models next to its package. On Android
    they were copied to <root>/ursina_data instead."""
    from panda3d.core import Filename, getModelPath
    from ursina import application
    pkg = root / 'ursina_data'
    application.package_folder = pkg
    application.asset_folder = root
    for name in ('models', 'models_compressed', 'scripts', 'textures', 'fonts', 'audio'):
        setattr(application, f'internal_{name}_folder', pkg / f'{name}/')
    application.scenes_folder = root / 'scenes/'
    application.scripts_folder = root / 'scripts/'
    application.fonts_folder = root / 'fonts/'
    application.textures_compressed_folder = root / 'textures_compressed/'
    application.models_compressed_folder = root / 'models_compressed/'
    getModelPath().prependDirectory(Filename.fromOsSpecific(str(pkg / 'fonts')))
    getModelPath().prependDirectory(Filename.fromOsSpecific(str(root)))
