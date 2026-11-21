"""Biggest Highway: drive on a 1,000,000-lane highway that wraps around the Earth.

Run:  .venv\\Scripts\\python main.py
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main():
    ap = argparse.ArgumentParser(description='Biggest Highway')
    ap.add_argument('--fresh', action='store_true', help='ignore save.json and start at kilometre 0')
    ap.add_argument('--shot', help='save a screenshot to this path after --frames frames, then quit')
    ap.add_argument('--frames', type=int, default=120)
    ap.add_argument('--timescale', type=float, default=1.0, help='run the simulation faster (testing)')
    ap.add_argument('--scene', choices=['drive', 'night', 'city', 'fly', 'top', 'map', 'auto', 'traffic', 'hyper', 'mapall', 'flyover', 'citynight', 'show0', 'show1', 'show2', 'show3', 'show4', 'park', 'popup', 'signal', 'padmenu', 'padmap', 'paddrive', 'cityturn', 'citywall'],
                    help='scripted setup used with --shot for testing')
    args = ap.parse_args()

    from ursina import Ursina
    here = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    icon = here / 'assets' / 'icon.ico'
    from panda3d.core import Filename
    icon_path = Filename.fromOsSpecific(str(icon)).getFullpath()     # Panda3D wants /e/... paths
    app = Ursina(title='Biggest Highway', borderless=False, development_mode=False,
                 icon=icon_path if icon.exists() else 'textures/ursina.ico',
                 size=(1600, 900) if args.shot else None, vsync=not args.shot)

    from game.app import Game
    Game(args)
    app.run()


if __name__ == '__main__':
    main()
