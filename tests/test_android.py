"""The Android build shares all game code with the PC version. These check the
PC side stays as it was, and the file-copy step used on Android."""
from pathlib import Path

from game import config, device, save


def test_pc_is_not_android():
    assert device.IS_ANDROID is False


def test_pc_keeps_full_detail():
    assert config.MAX_TRAFFIC == 140
    assert config.BANDS_EACH_SIDE == 3


def test_pc_save_is_in_project_folder():
    assert save.SAVE_PATH == Path(__file__).resolve().parents[1] / 'save.json'


def test_copy_tree_from_virtual_files(tmp_path):
    """prepare_android_files copies Panda3D's virtual folder (the APK) to disk."""
    from panda3d.core import Filename, VirtualFileMountRamdisk, VirtualFileSystem
    vfs = VirtualFileSystem.getGlobalPtr()
    mount = VirtualFileMountRamdisk()
    vfs.mount(mount, Filename('/test_apk'), 0)
    try:
        vfs.makeDirectoryFull(Filename('/test_apk/assets/models'))
        vfs.writeFile(Filename('/test_apk/assets/models/car.glb'), b'glTF-bytes', False)
        vfs.writeFile(Filename('/test_apk/android_build.txt'), b'1.1.0 123', False)
        device._copy_tree(vfs, '/test_apk', tmp_path / 'game')
        assert (tmp_path / 'game' / 'assets' / 'models' / 'car.glb').read_bytes() == b'glTF-bytes'
        assert (tmp_path / 'game' / 'android_build.txt').read_text() == '1.1.0 123'
    finally:
        vfs.unmount(mount)
