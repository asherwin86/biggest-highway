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


def _apk(path, stamp, files):
    import zipfile
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('assets/android_build.txt', stamp)
        z.writestr('lib/x86_64/libgame.so', b'not an asset')
        for name, data in files.items():
            z.writestr('assets/' + name, data)
    return path


def test_extract_assets_from_apk(tmp_path):
    """On the phone the game's files are unpacked from the APK (a zip) to app storage."""
    root = tmp_path / 'game'
    apk = _apk(tmp_path / 'a.apk', '1.1.0 1', {'assets/models/car.glb': b'glTF', 'ursina_data/fonts/f.ttf': b'ttf'})
    assert device.extract_assets(apk, root) == 2
    assert (root / 'assets' / 'models' / 'car.glb').read_bytes() == b'glTF'
    assert (root / 'ursina_data' / 'fonts' / 'f.ttf').read_bytes() == b'ttf'
    assert not (root / 'lib').exists()
    # same build: nothing to do. A new build (new stamp): unpacked again
    assert device.extract_assets(apk, root) == 0
    apk2 = _apk(tmp_path / 'b.apk', '1.1.0 2', {'assets/models/car.glb': b'glTF v2'})
    assert device.extract_assets(apk2, root) == 1
    assert (root / 'assets' / 'models' / 'car.glb').read_bytes() == b'glTF v2'


def test_inspect_patch_keeps_frame_info():
    import inspect
    old = inspect.stack, inspect.getframeinfo
    try:
        device.patch_inspect_for_frozen_code()
        info = inspect.getframeinfo(inspect.stack()[0][0])
        assert info.function == 'test_inspect_patch_keeps_frame_info' and info.filename.endswith('.py')
    finally:
        inspect.stack, inspect.getframeinfo = old
