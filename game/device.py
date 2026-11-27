"""What kind of device the game runs on: a PC, or an Android phone/tablet.

Pure Python (no engine imports at module level), so config.py and the tests can use it.

On Android the game is packaged with Panda3D's build_apps (see setup.py). The
game's files sit in the APK's assets/ folder. Ursina looks for models, textures
and fonts on the real disk, so on the first start (and after every update)
prepare_android_files() unpacks them from the APK (a zip file) to the app's
private storage. (Android's asset API can't list folders, so Panda3D's virtual
/android_asset folder can't be used to find them.)
"""
import os
import sys
from pathlib import Path

IS_ANDROID = (sys.platform == 'android' or hasattr(sys, 'getandroidapilevel')
              or 'ANDROID_ARGUMENT' in os.environ)

# touch-screen controls: always on Android, or with --touch on a PC (for testing)
TOUCH = IS_ANDROID

BUILD_STAMP = 'android_build.txt'     # written by setup.py; a new APK has a new stamp


def enable_touch(on=True):
    global TOUCH
    TOUCH = bool(on) or IS_ANDROID


def android_data_dir() -> Path:
    """The app's private, writable folder (for example /data/user/0/<app id>)."""
    from panda3d.core import ConfigVariableFilename, Filename
    # Panda3D points model-cache-dir at the app's cache folder; its parent is the data folder
    cache = ConfigVariableFilename('model-cache-dir', Filename()).getValue()
    if not cache.empty():
        d = Path(cache.toOsSpecific()).parent
        if d.is_dir():
            return d
    for cand in (Filename.getUserAppdataDirectory().toOsSpecific(), os.environ.get('HOME', ''),
                 os.environ.get('TMPDIR', '')):
        if cand and os.path.isdir(cand) and os.access(cand, os.W_OK):
            return Path(cand)
    return Path.cwd()


def apk_path():
    """Path of the installed APK (a zip file)."""
    from panda3d.core import ExecutionEnvironment
    # with uncompressed native libraries this is '.../base.apk!/lib/<abi>/lib<app>.so'
    name = ExecutionEnvironment.getBinaryName()
    if '.apk!' in name:
        return name.split('!', 1)[0]
    try:
        with open('/proc/self/maps', encoding='utf-8', errors='replace') as f:
            for line in f:
                p = line.split()[-1] if line.split() else ''
                if p.endswith('.apk') and os.path.isfile(p):
                    return p
    except OSError:
        pass
    return None


def prepare_android_files() -> Path:
    """Unpack the APK's assets/ to <data>/files/game (only when they changed) and
    return that folder."""
    root = android_data_dir() / 'files' / 'game'
    apk = apk_path()
    n = extract_assets(apk, root)
    print(f'[biggest-highway] APK {apk}: ' + (f'unpacked {n} files to {root}' if n else 'files up to date'))
    return root


def extract_assets(apk, root: Path) -> int:
    """Copy every file under assets/ in the zip `apk` to `root`, unless the build
    stamp there already matches. Returns how many files were copied."""
    import zipfile
    stamp = root / BUILD_STAMP
    with zipfile.ZipFile(apk) as z:
        want = z.read('assets/' + BUILD_STAMP).decode('utf-8', 'replace').strip()
        try:
            if stamp.read_text(encoding='utf-8').strip() == want:
                return 0
        except OSError:
            pass
        n = 0
        for info in z.infolist():
            rel = info.filename[len('assets/'):]
            if not info.filename.startswith('assets/') or info.is_dir() or rel == BUILD_STAMP:
                continue
            dst = root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(z.read(info))
            n += 1
    stamp.write_text(want, encoding='utf-8')     # last, so a cut-off copy is redone next time
    return n


def patch_inspect_for_frozen_code():
    """Ursina calls inspect.stack() / getframeinfo() to name its shaders. In the
    packaged app modules have no source files, and those calls raise. Return the
    same frame records without looking up source code."""
    import inspect

    def getframeinfo(frame, context=1):
        if hasattr(frame, 'tb_frame'):
            frame, lineno = frame.tb_frame, frame.tb_lineno
        else:
            lineno = frame.f_lineno
        return inspect.Traceback(frame.f_code.co_filename, lineno, frame.f_code.co_name, None, None)

    def stack(context=1):
        out, f = [], sys._getframe(1)
        while f is not None:
            out.append(inspect.FrameInfo(f, f.f_code.co_filename, f.f_lineno, f.f_code.co_name, None, None))
            f = f.f_back
        return out

    inspect.getframeinfo = getframeinfo
    inspect.stack = stack


GLES_HEADER = ('#version 300 es\n'
               'precision highp float;\nprecision highp int;\nprecision highp sampler2D;\n')


def to_gles(src: str) -> str:
    """Desktop GLSL (#version 130-430, as Ursina writes it) -> GLSL ES 3.00 for phones."""
    if not src or not src.strip():
        return src
    import re
    body = re.sub(r'^\s*#version[^\n]*\n', '', src, count=1, flags=re.M)
    body = body.replace('texture2D(', 'texture(').replace('textureCube(', 'texture(')
    if 'gl_FragColor' in body:
        body = 'out vec4 bh_frag_color;\n' + body.replace('gl_FragColor', 'bh_frag_color')
    return GLES_HEADER + body


touch_y_offset = 0       # pixels; see fix_touch_offset()
content_insets = (0, 0, 0, 0)    # left, top, right, bottom pixels covered by system bars


def read_content_rect():
    """Panda3D measures touches from the top of the app's 'content rect' (below the
    status bar), but draws from the top of the screen, so a tap lands that many
    pixels too high. Panda only reports the rect in its log; apps may read their
    own log lines, so look there. Returns (left, top, right, bottom) or None."""
    import re
    import subprocess
    try:
        out = subprocess.run(['logcat', '-d', '-s', 'threaded_app:V'], capture_output=True, text=True,
                             timeout=4).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    found = re.findall(r'ContentRectChanged: l=(-?\d+),t=(-?\d+),r=(-?\d+),b=(-?\d+)', out)
    return tuple(int(v) for v in found[-1]) if found else None


def fix_touch_offset():
    """Add the content rect's top back to Ursina's pointer position."""
    from ursina import application, mouse, window
    M = type(mouse)
    if getattr(M, '_bh_offset_patch', False):
        return
    real_y = M.y

    def get_y(self):
        p = application.base.win.get_pointer(0)
        if not p.in_window:
            return 0
        return -(((p.get_y() + touch_y_offset) / window.size.y) - .5)

    M.y = property(get_y, real_y.fset)
    M._bh_offset_patch = True


def refresh_touch_offset():
    """Returns True when the system bars moved (so the touch controls can re-layout)."""
    global touch_y_offset, content_insets
    rect = read_content_rect()
    if rect is None:
        return False
    from ursina import application
    w, h = application.base.win.getXSize(), application.base.win.getYSize()
    l, t, r, b = rect
    insets = (max(0, l), max(0, t), max(0, w - r), max(0, h - b))
    if insets == content_insets and t == touch_y_offset:
        return False
    touch_y_offset, content_insets = t, insets
    print(f'[biggest-highway] system bars cover {insets} px (left, top, right, bottom)')
    return True


def patch_ursina_transparency_for_gles():
    """Ursina gives every model 'dual' transparency, which relies on an alpha test.
    OpenGL ES has none to fall back on with custom shaders, so the first pass draws
    see-through things (like Ursina's full-screen fade overlay, transparent black)
    as solid black and covers the whole screen. Use plain alpha blending instead."""
    import types
    from panda3d.core import TransparencyAttrib
    from ursina import entity as uentity
    shim = types.SimpleNamespace(**{k: getattr(TransparencyAttrib, k) for k in dir(TransparencyAttrib)
                                    if not k.startswith('__')})
    shim.M_dual = TransparencyAttrib.M_alpha
    uentity.TransparencyAttrib = shim


def patch_ursina_meshes_for_gles():
    """Ursina draws rounded quads and circles as triangle fans, which came out
    invisible on OpenGL ES. Split fans and strips into plain triangles."""
    from ursina import mesh as umesh
    original = umesh.Mesh.generate

    def generate(self):
        result = original(self)
        if getattr(self, 'mode', 'triangle') in ('ngon', 'tristrip'):
            gn = self.geomNode
            for i in range(gn.getNumGeoms()):
                gn.modifyGeom(i).decomposeInPlace()
        return result

    umesh.Mesh.generate = generate


def fix_dual_transparency():
    """For anything made before the patch above."""
    from panda3d.core import TransparencyAttrib
    from ursina import application, camera
    n = 0
    for root in (application.base.render, camera.ui):
        for np in [root] + list(root.findAllMatches('**')):
            if np.hasTransparency() and np.getTransparency() == TransparencyAttrib.M_dual:
                np.setTransparency(TransparencyAttrib.M_alpha)
                n += 1
    return n


def patch_ursina_shaders_for_gles():
    """Phones use OpenGL ES, which doesn't accept desktop GLSL. Translate every
    Ursina shader just before Panda3D compiles it."""
    from ursina import shader as ushader
    original = ushader.Shader.compile

    def compile(self, shader_includes=True):
        if self.language == ushader.Shader.GLSL and not getattr(self, '_gles', False):
            if shader_includes:
                self.vertex = ushader.do_shader_includes(self.vertex)
                self.fragment = ushader.do_shader_includes(self.fragment)
            self.vertex, self.fragment = to_gles(self.vertex), to_gles(self.fragment)
            self.geometry = ''              # no geometry shaders in GLSL ES 3.00
            self._gles = True
        return original(self, shader_includes=False)

    ushader.Shader.compile = compile
    # some are compiled while Ursina is imported, before this patch: redo those
    # (replace_old_shaders() then swaps them on anything that already uses them)
    for s in list(ushader.imported_shaders.values()):
        if getattr(s, 'compiled', False):
            old = s._shader
            s.compile()
            _old_shaders.append((old, s))


_old_shaders = []


def white_texture():
    """A 1x1 white texture with ONE channel (luminance). Colour textures are uploaded
    as BGRA, which some OpenGL ES drivers (the Android emulator's, for one) draw as
    black, and Ursina's shaders sample a texture even on untextured objects."""
    from panda3d.core import PNMImage, SamplerState
    from panda3d.core import Texture as PandaTexture
    img = PNMImage(1, 1, 1)
    img.fill(1)
    t = PandaTexture('bh_white')
    t.load(img)
    t.setMinfilter(SamplerState.FT_nearest)
    t.setMagfilter(SamplerState.FT_nearest)
    return t


def install_white_default_texture():
    """Objects without a texture of their own get the one-channel white one."""
    from ursina import application, camera
    t = white_texture()
    for root in (application.base.render, camera.ui):
        root.setTexture(t)


def replace_old_shaders():
    """Put the translated shaders on every node that still has a desktop one."""
    if not _old_shaders:
        return 0
    from ursina import application, camera
    base = application.base
    n = 0
    roots = [base.render, base.render2d, base.aspect2d, camera.ui, camera]
    for root in roots:
        for np in [root] + list(root.findAllMatches('**')):
            sh = np.getShader()
            if sh is None:
                continue
            for old, new in _old_shaders:
                if sh == old:
                    np.setShader(new._shader)
                    n += 1
                    break
    return n


def point_ursina_at(root: Path):
    """Ursina finds its own fonts/textures/models next to its package. On Android
    they were copied to <root>/ursina_data instead."""
    from panda3d.core import Filename, getModelPath
    from ursina import application
    pkg = root / 'ursina_data'
    application.package_folder = pkg
    application.asset_folder = root
    for name in ('models', 'models_compressed', 'scripts', 'textures', 'fonts', 'audio'):
        setattr(application, f'internal_{name}_folder', pkg / f'{name}/')
    application.scenes_folder = root / 'scenes/'
    application.scripts_folder = root / 'scripts/'
    application.fonts_folder = root / 'fonts/'
    application.textures_compressed_folder = root / 'textures_compressed/'
    application.models_compressed_folder = root / 'models_compressed/'
    getModelPath().prependDirectory(Filename.fromOsSpecific(str(pkg / 'fonts')))
    getModelPath().prependDirectory(Filename.fromOsSpecific(str(root)))
