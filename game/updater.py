"""Auto-updater for the .exe.

1. On start (exe only) a background thread asks GitHub for the latest release.
2. If it is newer than this build, the game shows an "Update available" pop-up.
3. "Update now" downloads the new BiggestHighway.exe next to the current one,
   checks its size and SHA-256 against what GitHub reports, and only then
4. starts a tiny hidden PowerShell helper that waits for the game to close,
   swaps the files and starts the new version with the same arguments.

Nothing personal is sent: just an anonymous request to the public GitHub API.
Network problems are ignored (the game simply doesn't offer an update)."""
import hashlib
import json
import os
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

from .version import EXE_NAME, REPO, VERSION

API = f'https://api.github.com/repos/{REPO}/releases/latest'
HEADERS = {'User-Agent': 'BiggestHighway-Updater', 'Accept': 'application/vnd.github+json'}


def parse_version(tag: str):
    """'v1.2' / '1.2.3' -> (1, 2, 0) / (1, 2, 3). Unknown -> (0,)."""
    t = tag.strip().lstrip('vV').split('-')[0]
    try:
        parts = [int(p) for p in t.split('.')]
    except ValueError:
        return (0,)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def is_newer(tag: str, current: str = VERSION) -> bool:
    return parse_version(tag) > parse_version(current)


def pick_asset(release: dict):
    """The exe asset of a release (name, url, size, sha256 or None), or None."""
    for a in release.get('assets', []):
        if a.get('name') == EXE_NAME:
            digest = a.get('digest') or ''
            sha = digest.split(':', 1)[1].lower() if digest.startswith('sha256:') else None
            return {'url': a.get('browser_download_url'), 'size': a.get('size'), 'sha256': sha}
    return None


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def is_frozen() -> bool:
    return bool(getattr(sys, 'frozen', False))


def log(msg: str):
    """update.log next to the exe, to see what happened if an update goes wrong."""
    if not is_frozen():
        return
    try:
        path = Path(sys.executable).resolve().with_name('update.log')
        with open(path, 'a', encoding='utf-8') as f:
            f.write(msg.rstrip() + '\n')
    except OSError:
        pass


def helper_command(old_exe: Path, new_exe: Path, pids, args, log_path=None) -> str:
    """PowerShell that waits for the game to exit, swaps the exe and restarts it."""
    q = lambda p: "'" + str(p).replace("'", "''") + "'"
    note = (lambda m: f"Add-Content -LiteralPath {q(log_path)} -Value {q(m)}; ") if log_path else (lambda m: '')
    pid_list = ','.join(str(int(p)) for p in pids)
    arg_list = ','.join(q(a) for a in args)
    start = f'Start-Process -FilePath {q(old_exe)}'
    if args:
        start += f' -ArgumentList @({arg_list})'
    return (
        note('helper: waiting for the game to close')
        + f'Wait-Process -Id {pid_list} -ErrorAction SilentlyContinue; '
        + f'$ok = $false; for ($i = 0; $i -lt 40; $i++) {{ '
        + f'try {{ Move-Item -LiteralPath {q(new_exe)} -Destination {q(old_exe)} -Force -ErrorAction Stop; $ok = $true; break }} '
        + f'catch {{ Start-Sleep -Milliseconds 500 }} }}; '
        + (f"if ($ok) {{ Add-Content -LiteralPath {q(log_path)} -Value 'helper: swapped in the new exe' }} "
           f"else {{ Add-Content -LiteralPath {q(log_path)} -Value 'helper: could not replace the exe' }}; "
           if log_path else '')
        + f'{start}'
    )


class Updater:
    """state: idle -> checking -> (none | available | error) -> downloading -> ready -> restarting"""

    def __init__(self):
        self.state = 'idle'
        self.latest = None          # tag of the newer release
        self.notes = ''
        self.asset = None
        self.progress = 0.0
        self.error = ''
        self._lock = threading.Lock()

    # ---------------------------------------------------------- check
    def check_async(self):
        if self.state in ('checking', 'downloading'):
            return
        self.state = 'checking'
        threading.Thread(target=self._check, daemon=True).start()

    def _check(self):
        try:
            req = urllib.request.Request(API, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=8) as r:
                rel = json.loads(r.read().decode('utf-8'))
            tag = rel.get('tag_name', '')
            asset = pick_asset(rel)
            if is_newer(tag) and asset and asset['url']:
                self.latest, self.asset = tag, asset
                self.notes = (rel.get('name') or tag)
                self.state = 'available'
            else:
                self.state = 'none'
        except Exception as e:                       # offline, rate-limited, ...
            self.error = str(e)
            self.state = 'error'

    # ---------------------------------------------------------- download + install
    def download_async(self):
        if self.state != 'available':
            return
        self.state = 'downloading'
        self.progress = 0.0
        threading.Thread(target=self._download, daemon=True).start()

    def _target_paths(self):
        exe = Path(sys.executable).resolve()
        return exe, exe.with_name(exe.stem + '.update' + exe.suffix)

    def _download(self):
        exe, new = self._target_paths()
        try:
            req = urllib.request.Request(self.asset['url'], headers={'User-Agent': HEADERS['User-Agent']})
            size = self.asset.get('size') or 0
            got = 0
            with urllib.request.urlopen(req, timeout=30) as r, open(new, 'wb') as f:
                while True:
                    chunk = r.read(1 << 18)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if size:
                        self.progress = min(1.0, got / size)
            if size and got != size:
                raise IOError(f'download incomplete ({got} of {size} bytes)')
            if self.asset.get('sha256') and sha256_file(new) != self.asset['sha256']:
                raise IOError('download failed the checksum check')
            self.progress = 1.0
            self.state = 'ready'
            log(f'downloaded and verified {self.latest} ({got} bytes)')
        except Exception as e:
            try:
                new.unlink()
            except OSError:
                pass
            self.error = str(e)
            self.state = 'failed'
            log(f'download failed: {e}')

    def install_and_restart(self):
        """Start the swap helper. The caller must quit the game right after."""
        if self.state != 'ready':
            return False
        exe, new = self._target_paths()
        pids = [os.getpid()]
        if is_frozen():
            pids.append(os.getppid())     # the one-file launcher that holds the exe open
        cmd = helper_command(exe, new, pids, sys.argv[1:], exe.with_name('update.log'))
        flags = 0
        if os.name == 'nt':
            # its own process group, no console window, and not killed along with the game
            flags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x08000000 | 0x01000000   # NO_WINDOW, BREAKAWAY_FROM_JOB
        try:
            proc = subprocess.Popen(['powershell', '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden',
                                     '-Command', cmd], creationflags=flags, close_fds=True)
        except OSError:
            # breaking away from a job is not always allowed: try again without it
            proc = subprocess.Popen(['powershell', '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden',
                                     '-Command', cmd], creationflags=flags & ~0x01000000, close_fds=True)
        log(f'started the swap helper (pid {proc.pid}); quitting the game')
        self.state = 'restarting'
        return True
