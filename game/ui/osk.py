"""On-screen keyboard so the map search works with a controller."""
from ursina import Button, Color, Entity, Quad, Text, camera

ACCENT = Color(0.22, 0.52, 1.0, 1)
KEY = Color(0.16, 0.17, 0.21, 1)
ROWS = ['1234567890', 'QWERTYUIOP', "ASDFGHJKL'", 'ZXCVBNM-.,']
SPECIAL = ['SPACE', 'DELETE', 'CLEAR', 'DONE']
KW, KH = 0.052, 0.05


class OnScreenKeyboard:
    def __init__(self, parent, position, on_done=None):
        self.root = Entity(parent=parent, position=position, enabled=False)
        w = KW * 10 + 0.03
        h = KH * 5 + 0.07
        Entity(parent=self.root, model=Quad(radius=0.012, aspect=w / h), scale=(w, h),
               color=Color(0.07, 0.08, 0.1, 0.98), z=0.01)
        Text('A type   X delete   Y space   B done', parent=self.root, position=(0, h / 2 - 0.022, -0.01),
             scale=0.62, origin=(0, 0), color=Color(0.6, 0.63, 0.68, 1))
        self.grid = []
        y0 = h / 2 - 0.065
        for r, row in enumerate(ROWS):
            line = []
            for c, ch in enumerate(row):
                b = Button(ch, parent=self.root, scale=(KW - 0.005, KH - 0.006),
                           position=(-KW * 4.5 + c * KW, y0 - r * KH, -0.01), color=KEY,
                           on_click=(lambda r=r, c=c: self._press(r, c)))
                line.append(b)
            self.grid.append(line)
        line = []
        for c, name in enumerate(SPECIAL):
            b = Button(name, parent=self.root, scale=(KW * 2.5 - 0.006, KH - 0.006),
                       position=(-KW * 3.75 + c * KW * 2.5, y0 - 4 * KH, -0.01), color=KEY,
                       on_click=(lambda c=c: self._press(4, c)))
            b.text_entity.scale *= 0.75
            line.append(b)
        self.grid.append(line)
        self.field = None
        self.on_done = on_done
        self.r, self.c = 1, 0

    @property
    def is_open(self):
        return self.root.enabled

    def open(self, field):
        self.field = field
        self.root.enabled = True
        self.r, self.c = 1, 0
        self._highlight()

    def close(self):
        self.root.enabled = False
        if self.on_done:
            self.on_done()

    def _type(self, s):
        if self.field is None:
            return
        t = self.field.text
        if s == '\b':
            t = t[:-1]
        elif s == '\x00':
            t = ''
        elif len(t) < 40:
            t += s
        self.field.text = t

    def _press(self, r, c):
        self.r, self.c = r, c
        if r < 4:
            self._type(ROWS[r][c].lower())
        else:
            name = SPECIAL[c]
            if name == 'SPACE':
                self._type(' ')
            elif name == 'DELETE':
                self._type('\b')
            elif name == 'CLEAR':
                self._type('\x00')
            else:
                self.close()
        self._highlight()

    def move(self, d):
        if d in ('left', 'right'):
            n = len(self.grid[self.r])
            self.c = (self.c + (1 if d == 'right' else -1)) % n
        else:
            old_n = len(self.grid[self.r])
            self.r = (self.r + (1 if d == 'down' else -1)) % len(self.grid)
            new_n = len(self.grid[self.r])
            self.c = min(new_n - 1, int(self.c * new_n / old_n))
        self._highlight()

    def handle(self, key):
        if key == 'gamepad a':
            self._press(self.r, self.c)
        elif key == 'gamepad x':
            self._type('\b')
        elif key == 'gamepad y':
            self._type(' ')
        elif key in ('gamepad b', 'gamepad start', 'escape'):
            self.close()
        return True

    def _highlight(self):
        for r, line in enumerate(self.grid):
            for c, b in enumerate(line):
                b.color = ACCENT if (r, c) == (self.r, self.c) else KEY
