"""Quick menu (controller Back button, or Esc on the keyboard). Every action in
the game is reachable from here with just a D-pad and A, so a controller can
do everything a keyboard and mouse can."""
from ursina import Button, Color, Entity, Quad, Text, application, camera, color

from .. import coords
from ..vehicles import CARS
from ..version import VERSION

ACCENT = Color(0.22, 0.52, 1.0, 1)
ROW = Color(0.13, 0.14, 0.18, 1)
DIM = Color(0.6, 0.63, 0.68, 1)
W, ROW_H = 0.62, 0.046


class QuickMenu:
    def __init__(self, game):
        self.g = game
        self.root = Entity(parent=camera.ui, enabled=False, z=-6)
        Entity(parent=self.root, model='quad', scale=(4, 2), color=Color(0, 0, 0, 0.55), z=0.02)
        self.items = self._items()
        h = len(self.items) * ROW_H + 0.16
        self.top = h / 2
        Entity(parent=self.root, model=Quad(radius=0.02, aspect=W / h), scale=(W, h),
               color=Color(0.06, 0.07, 0.09, 0.97), z=0.01)
        Text('MENU', parent=self.root, position=(-W / 2 + 0.03, self.top - 0.04, -0.01), scale=1.3)
        self.rows = []
        for i, item in enumerate(self.items):
            y = self.top - 0.1 - i * ROW_H
            b = Button('-', parent=self.root, scale=(W - 0.05, ROW_H - 0.006), position=(0, y, -0.01),
                       color=ROW, text_origin=(-0.5, 0), on_click=(lambda i=i: self._click(i)))
            b.text_entity.scale *= 0.8
            b.text_entity.x = -0.47
            self.rows.append(b)
        self.hint = Text('', parent=self.root, position=(0, -self.top + 0.03, -0.01), scale=0.7, color=DIM,
                         origin=(0, 0))
        self.i = 0
        self.confirm_quit = False

    # label function, select action, adjust action (left/right) or None
    def _items(self):
        g = self.g
        on = lambda b: 'ON' if b else 'OFF'
        return [
            (lambda: 'Resume', self.close, None),
            (lambda: f'Self-driving: {on(g.autopilot.enabled)}', g.toggle_autopilot, None),
            (lambda: f'Cruise speed:  [ {g.autopilot.cruise * 3.6:.0f} km/h ]', None, lambda d: g.cruise_delta(10 * d)),
            (lambda: 'Auto Park at the nearest lot', self._park, None),
            (lambda: f'Car:  [ {g.player.spec.name} ]', g.next_car,
             lambda d: g.select_car(CARS.index(g.player.spec) + d)),
            (lambda: f'Fly (Volt Roadster): {on(g.player.flying)}', g.toggle_flight, None),
            (lambda: f'Warp: {on(g.player.warp)}', g.toggle_warp, None),
            (lambda: f'Camera:  [ {g.camera_mode} ]', g.cycle_camera, lambda d: g.cycle_camera(d)),
            (lambda: (f'Traffic: Auto-adapt ({g.density.value * 100:.0f}%)' if g.density.auto
                      else f'Traffic: manual  [ {g.density.manual * 100:.0f}% ]'),
             g.toggle_traffic_auto, self._traffic),
            (lambda: 'Jump 1,000 lanes  [ left / right ]', None, lambda d: g.lane_jump(1000 * d)),
            (lambda: 'Back to the highway deck', self._then(g.return_to_highway), None),
            (lambda: 'Map and search', self._then(g.toggle_map), None),
            (lambda: f'Screen: {"shown" if g.dashboard.root.enabled else "hidden"}', g.dashboard.toggle, None),
            (lambda: 'Controls help', self._then(g.show_help), None),
            (lambda: f'Check for updates  (you have v{VERSION})', self._then(lambda: g.update_prompt.check_now()), None),
            (lambda: 'Quit game  (press again to confirm)' if self.confirm_quit else 'Quit game', self._quit, None),
        ]

    def _then(self, fn):
        def run():
            self.close()
            fn()
        return run

    def _park(self):
        self.close()
        self.g.open_nearest_parking()

    def _traffic(self, d):
        dens = self.g.density
        dens.auto = False
        dens.manual = max(0.0, min(1.0, round(dens.manual + 0.1 * d, 2)))

    def _quit(self):
        if self.confirm_quit:
            self.g.save()
            application.quit()
        self.confirm_quit = True

    # ---------------------------------------------------------- control
    @property
    def is_open(self):
        return self.root.enabled

    def open(self):
        self.root.enabled = True
        self.i = 0
        self.confirm_quit = False
        self.g.pad.reset_nav()
        self.refresh()

    def close(self):
        self.root.enabled = False

    def toggle(self):
        self.close() if self.is_open else self.open()

    def _click(self, i):
        self.i = i
        self.select()

    def select(self):
        _, act, adj = self.items[self.i]
        if act is not None:
            act()
        elif adj is not None:
            adj(1)
        if self.items[self.i][2] is None or act is not None:
            pass
        if self.i != len(self.items) - 1:
            self.confirm_quit = False
        self.refresh()

    def move(self, d):
        self.i = (self.i + d) % len(self.items)
        self.confirm_quit = False
        self.refresh()

    def adjust(self, d):
        adj = self.items[self.i][2]
        if adj is not None:
            adj(d)
            self.refresh()

    def handle(self, key):
        """Keyboard / controller keys while the menu is open. Returns True if used."""
        if key in ('escape', 'gamepad back', 'gamepad b', 'gamepad start'):
            self.close()
        elif key in ('up arrow', 'w'):
            self.move(-1)
        elif key in ('down arrow', 's'):
            self.move(1)
        elif key in ('left arrow', 'a'):
            self.adjust(-1)
        elif key in ('right arrow', 'd'):
            self.adjust(1)
        elif key in ('enter', 'space', 'gamepad a'):
            self.select()
        return True

    def nav(self, events):
        for e in events:
            if e == 'up':
                self.move(-1)
            elif e == 'down':
                self.move(1)
            else:
                self.adjust(-1 if e == 'left' else 1)

    def refresh(self):
        for i, (b, item) in enumerate(zip(self.rows, self.items)):
            b.text = item[0]()
            b.text_entity.x = -0.47
            b.color = ACCENT if i == self.i else ROW
        pad = self.g.pad.using_pad
        self.hint.text = ('D-pad move   left/right adjust   A select   B close' if pad
                          else 'Arrows move   left/right adjust   Enter select   Esc close')
