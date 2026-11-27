"""Biggest Highway: drive on a 1,000,000-lane highway that wraps around the Earth.

Run:  .venv\\Scripts\\python main.py
The same file is the entry point of the Android app (see setup.py).
"""
import argparse
import os
import sys
from pathlib import Path

_here = globals().get('__file__')
if _here:
    sys.path.insert(0, str(Path(_here).resolve().parent))


def _android_start():
    """On Android: copy the game files out of the APK, then make Ursina look there."""
    from game import device
    if not device.IS_ANDROID:
        return None
    device.patch_inspect_for_frozen_code()
    root = device.prepare_android_files()
    os.chdir(root)
    sys.argv = [str(root / 'main.py')]        # Ursina finds its asset folder from this
    return root


def main():
    android_root = _android_start()

    ap = argparse.ArgumentParser(prog='BiggestHighway', description='Biggest Highway')
    ap.add_argument('--fresh', action='store_true', help='ignore save.json and start at kilometre 0')
    ap.add_argument('--shot', help='save a screenshot to this path after --frames frames, then quit')
    ap.add_argument('--frames', type=int, default=120)
    ap.add_argument('--no-update-check', action='store_true', help="don't check GitHub for a newer version")
    ap.add_argument('--check-update', action='store_true', help='check for updates even when run from source')
    ap.add_argument('--auto-update', action='store_true', help='install an available update without asking (testing)')
    ap.add_argument('--timescale', type=float, default=1.0, help='run the simulation faster (testing)')
    ap.add_argument('--touch', action='store_true', help='show the phone touch controls (testing)')
    ap.add_argument('--size', help='window size for --shot, for example 2400x1080 (testing)')
    ap.add_argument('--scene', choices=['drive', 'night', 'city', 'fly', 'top', 'map', 'auto', 'traffic', 'hyper', 'mapall', 'flyover', 'citynight', 'show0', 'show1', 'show2', 'show3', 'show4', 'park', 'popup', 'signal', 'padmenu', 'padmap', 'paddrive', 'cityturn', 'citywall', 'onramp', 'offramp', 'citynav', 'airnav', 'touch', 'touchmap', 'touchmenu'],
                    help='scripted setup used with --shot for testing')
    args = ap.parse_args(sys.argv[1:])

    from game import device
    if args.touch or (args.scene or '').startswith('touch'):
        device.enable_touch()

    from ursina import Ursina
    if android_root is not None:
        device.point_ursina_at(android_root)
        device.patch_ursina_shaders_for_gles()
        device.patch_ursina_transparency_for_gles()
        device.patch_ursina_meshes_for_gles()
        here = android_root
    else:
        here = Path(getattr(sys, '_MEIPASS', Path(_here).resolve().parent))
    icon = here / 'assets' / 'icon.ico'
    from panda3d.core import Filename
    icon_path = Filename.fromOsSpecific(str(icon)).getFullpath()     # Panda3D wants /e/... paths
    size = None
    if args.shot:
        size = tuple(int(v) for v in args.size.split('x')) if args.size else (1600, 900)
    app = Ursina(title='Biggest Highway', borderless=False, development_mode=False,
                 icon=icon_path if icon.exists() and not device.IS_ANDROID else 'textures/ursina.ico',
                 size=size, vsync=not args.shot)

    from game.app import Game
    Game(args)
    if android_root is not None:
        print(f'[biggest-highway] replaced {device.replace_old_shaders()} desktop shaders')
        device.install_white_default_texture()
        print(f'[biggest-highway] switched {device.fix_dual_transparency()} models to alpha blending')
    app.run()


if __name__ == '__main__':
    main()
