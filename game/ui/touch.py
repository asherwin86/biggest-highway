"""On-screen touch controls for phones and tablets (also on a PC with --touch).

Android only reports one finger at a time, so driving uses a single stick:
drag up to accelerate, down to brake (hold to reverse), left/right to steer.
Big buttons on the left open the menu and the map and switch self-driving,
Auto Park and flying. Everything else is on the car's screen or in the menu."""
from ursina import Button, Circle, Color, Entity, Text, camera, held_keys, mouse, window

ACCENT = Color(0.22, 0.52, 1.0, 0.92)
BTN = Color(0.1, 0.11, 0.14, 0.78)
GREEN = Color(0.16, 0.62, 0.34, 0.92)
DEAD = 0.12          # stick dead zone (fraction of its radius)

HELP_TOUCH = """<white>TOUCH CONTROLS<default>   1,000,000 lanes around the whole Earth

Stick (right)     drag up to drive, down to brake (hold to reverse), sideways to steer
Self-drive        full self-driving in the city, on the highway and in the air
Map               search any destination, then tap Navigate
Park              Auto Park in the nearest lot (or tap a P on the car's screen)
Fly               Volt Roadster only (Car button on the screen): Up / Down buttons
Car's screen      signals, cruise speed, car, warp, camera, traffic
Menu              everything else, including Quit
City              green ENTRANCE ramps go up to the highway, EXIT ramps come down

Tap anywhere to close this help.
"""


class TouchControls:
    def __init__(self, game):
        self.g = game
        self.root = Entity(parent=camera.ui, z=-1)
        r = self.root
        self.R = 0.15
        self.base = Entity(parent=r, model=Circle(48), scale=self.R * 2, color=Color(1, 1, 1, 0.08))
        self.rim = Entity(parent=self.base, model=Circle(48, mode='line', thickness=3), color=Color(1, 1, 1, 0.35),
                          z=-0.01)
        self.knob = Entity(parent=r, model=Circle(32), scale=0.11, color=Color(1, 1, 1, 0.55), z=-0.02)
        self.lbl_go = Text('GO', parent=r, scale=0.75, origin=(0, 0), color=Color(1, 1, 1, 0.6), z=-0.03)
        self.lbl_brake = Text('BRAKE', parent=r, scale=0.75, origin=(0, 0), color=Color(1, 1, 1, 0.6), z=-0.03)

        self.buttons = {}
        for name, fn in (('Menu', game.menu.open), ('Map', game.toggle_map), ('Self-drive', game.toggle_autopilot),
                         ('Park', self._park), ('Fly', game.toggle_flight)):
            b = Button(name, parent=r, scale=(0.17, 0.075), color=BTN, radius=0.25, on_click=fn)
            b.text_entity.scale *= 0.9
            self.buttons[name] = b
        self.up_btn = Button('Up', parent=r, scale=(0.12, 0.1), color=BTN, radius=0.25)
        self.down_btn = Button('Down', parent=r, scale=(0.12, 0.1), color=BTN, radius=0.25)

        self.fake = None           # (x, y) stick position for scripted tests
        self.grab = None           # what the finger started on: 'stick', 'up', 'down' or 'other'
        self.sx = self.sy = 0.0    # stick deflection, -1..1
        self._aspect = None
        self.layout()

    # ------------------------------------------------------------------ layout
    def layout(self):
        a = window.aspect_ratio
        self._aspect = a
        # the car's screen: as big as the window allows (it was made for 16:9)
        dash = self.g.dashboard.root
        s = max(1.0, min(1.3, a * 0.98 / 1.66))
        dash.scale = s
        dash.y = -0.495 + 0.49 * s
        top = dash.y - 0.18 * s                       # top edge of the car's screen
        self.cx, self.cy = a / 2 - 0.2, top + 0.08 + self.R + 0.06
        self.base.position = (self.cx, self.cy, 0)
        self.knob.position = (self.cx, self.cy, -0.02)
        self.lbl_go.position = (self.cx, self.cy + self.R + 0.025, -0.03)
        self.lbl_brake.position = (self.cx, self.cy - self.R - 0.025, -0.03)
        x = -a / 2 + 0.11
        for i, b in enumerate(self.buttons.values()):
            b.position = (x, 0.43 - i * 0.09, 0)
        self.up_btn.position = (self.cx - self.R - 0.13, self.cy + 0.06, 0)
        self.down_btn.position = (self.cx - self.R - 0.13, self.cy - 0.06, 0)

    # ------------------------------------------------------------------ values for the car
    def steer(self):
        return self._axis(self.sx)

    def throttle(self):
        return max(0.0, self._axis(self.sy))

    def brake(self):
        return max(0.0, -self._axis(self.sy))

    def up(self):
        return 1.0 if self.grab == 'up' else 0.0

    def down(self):
        return 1.0 if self.grab == 'down' else 0.0

    @property
    def active(self):
        return self.grab in ('stick', 'up', 'down') and (self.grab != 'stick' or abs(self.sx) + abs(self.sy) > DEAD)

    @staticmethod
    def _axis(v):
        if abs(v) < DEAD:
            return 0.0
        return (abs(v) - DEAD) / (1 - DEAD) * (1 if v > 0 else -1)

    def _park(self):
        g = self.g
        if g.autopark.active:
            g.cancel_autopark()
        else:
            g.open_nearest_parking()

    # ------------------------------------------------------------------ per frame
    def update(self):
        g = self.g
        if window.aspect_ratio != self._aspect:
            self.layout()
        show = not g.menus_open
        self.root.enabled = show
        flying = g.player.flying
        self.up_btn.enabled = self.down_btn.enabled = flying
        self.buttons['Self-drive'].color = GREEN if g.autopilot.enabled else BTN
        self.buttons['Fly'].color = ACCENT if flying else BTN
        self.buttons['Park'].color = ACCENT if g.autopark.active else BTN

        held = held_keys['left mouse'] and show
        if self.fake is not None:
            self.grab, (self.sx, self.sy) = 'stick', self.fake
        elif not held:
            self.grab = None
            self.sx = self.sy = 0.0
        else:
            mx, my = mouse.x, mouse.y
            if self.grab is None:               # the finger just touched the screen
                if g.help.enabled:
                    g.help.enabled = False
                if (mx - self.cx) ** 2 + (my - self.cy) ** 2 < (self.R * 1.35) ** 2:
                    self.grab = 'stick'
                elif flying and self._inside(self.up_btn, mx, my):
                    self.grab = 'up'
                elif flying and self._inside(self.down_btn, mx, my):
                    self.grab = 'down'
                else:
                    self.grab = 'other'
            if self.grab == 'stick':
                dx, dy = (mx - self.cx) / self.R, (my - self.cy) / self.R
                n = (dx * dx + dy * dy) ** 0.5
                if n > 1:
                    dx, dy = dx / n, dy / n
                self.sx, self.sy = dx, dy
        self.knob.position = (self.cx + self.sx * self.R, self.cy + self.sy * self.R, -0.02)
        self.knob.color = Color(1, 1, 1, 0.85 if self.grab == 'stick' else 0.55)
        self.up_btn.color = ACCENT if self.grab == 'up' else BTN
        self.down_btn.color = ACCENT if self.grab == 'down' else BTN

    @staticmethod
    def _inside(b, mx, my):
        return abs(mx - b.x) < b.scale_x / 2 and abs(my - b.y) < b.scale_y / 2


def install_tap_fix():
    """A finger jumps straight to where it touches, without moving there first like a
    mouse does. Ursina only works out which button is under the pointer once per
    frame, so a tap could hit the button touched last time. Re-check right before
    every press is handled."""
    from ursina import application
    base = application.base

    def button_down(key):
        if key == 'mouse1':
            mouse.update()
        base.input(key)

    base.ignore('buttonDown')
    base.accept('buttonDown', button_down)
