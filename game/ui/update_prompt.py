"""'Update available' pop-up for the auto-updater."""
from ursina import Button, Color, Entity, Quad, Text, camera, color

from ..updater import is_frozen
from ..version import VERSION

ACCENT = Color(0.22, 0.52, 1.0, 1)
BTN = Color(0.16, 0.17, 0.21, 1)
DIM = Color(0.65, 0.68, 0.72, 1)
W, H = 0.66, 0.2


class UpdatePrompt:
    def __init__(self, game):
        self.g = game
        self.root = Entity(parent=camera.ui, enabled=False, z=-7, y=0.2)
        Entity(parent=self.root, model=Quad(radius=0.015, aspect=W / H), scale=(W, H),
               color=Color(0.07, 0.08, 0.1, 0.97))
        self.title = Text('Update available', parent=self.root, position=(-W / 2 + 0.03, 0.065, -0.01), scale=1.15)
        self.body = Text('', parent=self.root, position=(-W / 2 + 0.03, 0.02, -0.01), scale=0.75, color=DIM,
                         origin=(-0.5, 0.5))
        self.go = Button('Update now', parent=self.root, scale=(0.2, 0.045), position=(-0.1, -0.06, -0.01),
                         color=ACCENT, on_click=self.accept)
        self.later = Button('Later', parent=self.root, scale=(0.2, 0.045), position=(0.12, -0.06, -0.01),
                            color=BTN, on_click=self.dismiss)
        for b in (self.go, self.later):
            b.text_entity.scale *= 0.8
        self.dismissed = None
        self.accepted = False
        self.manual = False

    @property
    def is_open(self):
        return self.root.enabled

    def check_now(self):
        """Menu: 'Check for updates'."""
        u = self.g.updater
        self.manual = True
        self.dismissed = None
        u.check_async()
        self.g.toast('Checking for updates...', 2)

    def accept(self):
        u = self.g.updater
        if not is_frozen():
            self.g.toast('Running from source: use git pull to update', 3)
            self.dismiss()
            return
        if u.state == 'available':
            self.accepted = True
            u.download_async()
        elif u.state == 'failed':
            self.dismiss()

    def dismiss(self):
        u = self.g.updater
        if u.state == 'downloading':
            return                       # let the download finish quietly; it is harmless
        self.dismissed = u.latest
        self.root.enabled = False

    def handle(self, key):
        if key in ('gamepad a', 'enter'):
            self.accept()
        elif key in ('gamepad b', 'escape'):
            self.dismiss()
        return True

    def update(self, dt):
        u = self.g.updater
        if u.state == 'available' and self.dismissed != u.latest and not self.root.enabled:
            self.root.enabled = True
            self.manual = False
            if self.g.args.auto_update:
                self.accept()
        if self.manual and u.state in ('none', 'error'):
            self.manual = False
            self.g.toast(f'You have the latest version (v{VERSION})' if u.state == 'none'
                         else "Couldn't reach GitHub to check for updates", 3)
        if not self.root.enabled:
            return
        pad = self.g.pad.using_pad
        self.go.text = 'Update now  (A)' if pad else 'Update now'
        self.later.text = 'Later  (B)' if pad else 'Later'
        if u.state == 'available':
            self.title.text = f'Update available: {u.latest}'
            self.body.text = (f'You have v{VERSION}. The game downloads the new version,\n'
                              'checks it, and restarts by itself. Your save is kept.')
            self.go.enabled = True
        elif u.state == 'downloading':
            self.title.text = f'Downloading {u.latest}...'
            self.body.text = f'{u.progress * 100:.0f}%   (you can keep playing)'
            self.go.enabled = False
        elif u.state == 'ready' and self.accepted:
            self.title.text = 'Installing update...'
            self.body.text = 'Restarting the game'
            self.go.enabled = self.later.enabled = False
            self.g.finish_update()
        elif u.state == 'failed':
            self.title.text = 'Update failed'
            self.body.text = f'{u.error}\nNothing was changed. Try again later.'
            self.go.enabled = False
            self.later.text = 'Close'
