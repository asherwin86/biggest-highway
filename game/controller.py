"""Game controller support (Xbox-style layout; PlayStation and other XInput /
HID gamepads map to the same buttons through Panda3D).

Ursina already turns pad buttons into input events ('gamepad a', 'gamepad
dpad up', ...) and the sticks/triggers into held_keys. This module adds:
  * hot-plugging (plug a controller in while the game runs)
  * dead zones and response curves for steering/pedals
  * menu navigation events with key repeat from the D-pad and left stick
  * rumble
  * tracking whether the player last used the keyboard or a controller,
    so the screen can show the right button hints
"""
from ursina import application, held_keys, input_handler

NAV_DELAY, NAV_REPEAT = 0.38, 0.11
STICK_NAV = 0.6

PAD_BUTTONS = ('a', 'b', 'x', 'y', 'left shoulder', 'right shoulder', 'left stick', 'right stick',
               'back', 'start', 'dpad up', 'dpad down', 'dpad left', 'dpad right')


def is_pad_key(key: str) -> bool:
    return key.startswith('gamepad')


def button(key: str):
    """'gamepad dpad up' -> 'dpad up'; release events return None."""
    if not key.startswith('gamepad '):
        return None
    name = key[len('gamepad '):]
    if name.endswith(' up') and name != 'dpad up':
        return None
    return name


def _dead(v, dz=0.15):
    if abs(v) < dz:
        return 0.0
    s = 1 if v > 0 else -1
    return s * (abs(v) - dz) / (1 - dz)


class Pad:
    def __init__(self, on_change=None):
        self.on_change = on_change
        self.using_pad = False
        self._nav_held = {}
        self._rumble_t = 0.0
        self.names = []
        base = application.base
        base.accept('connect-device', self._device_event, extraArgs=['connected'])
        base.accept('disconnect-device', self._device_event, extraArgs=['disconnected'])
        self._refresh()

    # ---------------------------------------------------------- devices
    def _refresh(self):
        from panda3d.core import InputDevice
        base = application.base
        try:
            input_handler.gamepads = base.devices.getDevices(InputDevice.DeviceClass.gamepad)
        except Exception as e:          # e.g. a platform without controller support
            print('no controller support:', e)
            input_handler.gamepads = []
        try:
            from ursina import gamepad as ursina_gamepad
            ursina_gamepad.connect_all()
        except Exception as e:          # never let controller trouble crash the game
            print('gamepad connect failed:', e)
        self.names = [d.name for d in input_handler.gamepads]

    def _device_event(self, what, device):
        from panda3d.core import InputDevice
        if device.device_class != InputDevice.DeviceClass.gamepad:
            return
        self._refresh()
        if self.on_change:
            self.on_change(f'Controller {what}: {device.name}')

    @property
    def connected(self):
        return bool(input_handler.gamepads)

    # ---------------------------------------------------------- analog
    @staticmethod
    def axis(name):
        return held_keys[f'gamepad {name}']

    def steer(self):
        x = _dead(self.axis('left stick x'), 0.12)
        return x * abs(x) ** 0.6           # gentler around the centre

    def throttle(self):
        return _dead(self.axis('right trigger'), 0.05)

    def brake(self):
        return _dead(self.axis('left trigger'), 0.05)

    def right_stick(self):
        return _dead(self.axis('right stick x')), _dead(self.axis('right stick y'))

    def left_stick(self):
        return _dead(self.axis('left stick x')), _dead(self.axis('left stick y'))

    def any_analog(self):
        lx, ly = self.left_stick()
        rx, ry = self.right_stick()
        return any(abs(v) > 0.3 for v in (lx, ly, rx, ry, self.throttle(), self.brake()))

    # ---------------------------------------------------------- menus
    def nav_events(self, dt):
        """D-pad / left stick as repeating up/down/left/right presses for menus."""
        lx, ly = self.left_stick()
        wanted = {
            'up': held_keys['gamepad dpad up'] or ly > STICK_NAV,
            'down': held_keys['gamepad dpad down'] or ly < -STICK_NAV,
            'left': held_keys['gamepad dpad left'] or lx < -STICK_NAV,
            'right': held_keys['gamepad dpad right'] or lx > STICK_NAV,
        }
        out = []
        for d, on in wanted.items():
            if not on:
                self._nav_held.pop(d, None)
                continue
            if d not in self._nav_held:
                self._nav_held[d] = NAV_DELAY
                out.append(d)
            else:
                self._nav_held[d] -= dt
                if self._nav_held[d] <= 0:
                    self._nav_held[d] = NAV_REPEAT
                    out.append(d)
        return out

    def reset_nav(self):
        """Call when a menu opens so the press that opened it does not repeat."""
        self._nav_held = {d: 10.0 for d in ('up', 'down', 'left', 'right')
                          if held_keys[f'gamepad dpad {d}']}

    # ---------------------------------------------------------- rumble
    def rumble(self, low=0.6, high=0.6, secs=0.15):
        for dev in input_handler.gamepads:
            try:
                dev.set_vibration(low, high)
            except Exception:
                pass
        self._rumble_t = max(self._rumble_t, secs)

    def update(self, dt):
        if self._rumble_t > 0:
            self._rumble_t -= dt
            if self._rumble_t <= 0:
                for dev in input_handler.gamepads:
                    try:
                        dev.set_vibration(0, 0)
                    except Exception:
                        pass
        if self.any_analog():
            self.using_pad = True
