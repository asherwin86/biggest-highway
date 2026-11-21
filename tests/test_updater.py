import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game import updater
from game.version import VERSION


def test_version_compare():
    assert updater.parse_version('v1.2') == (1, 2, 0)
    assert updater.parse_version('1.10.3') == (1, 10, 3)
    assert updater.parse_version('garbage') == (0,)
    assert updater.is_newer('v1.10', '1.9.9')
    assert not updater.is_newer('v1.0', '1.1.0')
    assert not updater.is_newer(f'v{VERSION}', VERSION)


def test_pick_asset_reads_checksum():
    rel = {'assets': [
        {'name': 'notes.txt', 'browser_download_url': 'x', 'size': 1},
        {'name': 'BiggestHighway.exe', 'browser_download_url': 'https://example/exe', 'size': 123,
         'digest': 'sha256:ABCDEF'},
    ]}
    a = updater.pick_asset(rel)
    assert a == {'url': 'https://example/exe', 'size': 123, 'sha256': 'abcdef'}
    assert updater.pick_asset({'assets': []}) is None


def test_sha256_file(tmp_path):
    f = tmp_path / 'x.bin'
    f.write_bytes(b'highway' * 1000)
    assert updater.sha256_file(f) == hashlib.sha256(b'highway' * 1000).hexdigest()


def test_helper_command_quotes_paths_and_restarts_with_args():
    cmd = updater.helper_command(Path(r"C:\Games\Bob's Folder\BiggestHighway.exe"),
                                 Path(r"C:\Games\Bob's Folder\BiggestHighway.update.exe"),
                                 [111, 222], ['--fresh'])
    assert "Wait-Process -Id 111,222" in cmd
    assert "'C:\\Games\\Bob''s Folder\\BiggestHighway.exe'" in cmd     # apostrophe escaped
    assert "-ArgumentList @('--fresh')" in cmd
    assert cmd.index('Move-Item') < cmd.index('Start-Process')


def test_download_refuses_bad_checksum(tmp_path, monkeypatch):
    payload = b'not the real exe'

    class Resp:
        def __init__(self):
            self.data = [payload, b'']

        def read(self, n=-1):
            return self.data.pop(0)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(updater.urllib.request, 'urlopen', lambda *a, **k: Resp())
    exe = tmp_path / 'BiggestHighway.exe'
    exe.write_bytes(b'old')
    monkeypatch.setattr(updater.sys, 'executable', str(exe))
    u = updater.Updater()
    u.state = 'available'
    u.asset = {'url': 'https://example/exe', 'size': len(payload), 'sha256': '0' * 64}
    u._download()
    assert u.state == 'failed' and 'checksum' in u.error
    assert not (tmp_path / 'BiggestHighway.update.exe').exists()   # bad file removed
    assert exe.read_bytes() == b'old'                                # nothing replaced
    u.state = 'available'
    u.asset['sha256'] = hashlib.sha256(payload).hexdigest()
    u._download()
    assert u.state == 'ready'
    assert (tmp_path / 'BiggestHighway.update.exe').read_bytes() == payload
