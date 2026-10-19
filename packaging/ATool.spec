"""Native bundles; tools/build_native.py prepares only public runtime inputs."""
import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parent
stage = Path(os.environ['ATOOL_NATIVE_STAGE'])
node = Path(os.environ['ATOOL_NATIVE_NODE'])
datas = collect_data_files('atool_qt') + [
    (str(stage / 'occs-cli'), 'runtime/occs-cli'),
    (str(stage / 'BUILD_INFO.txt'), '.'),
    (str(stage / 'RUNTIME_INFO.json'), '.'),
    (str(stage / 'licenses'), 'licenses'),
]
a = Analysis([str(root / 'ATool_Qt.py')], pathex=[str(root)],
             binaries=[(str(node), 'runtime/node')], datas=datas,
             hiddenimports=[], hookspath=[], runtime_hooks=[],
             excludes=['tkinter', 'webview'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ATool',
          debug=False, strip=False, upx=False, console=False, icon=str(root / 'atool_qt' / 'assets' / 'atool.ico'))
collection = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ATool')
if sys.platform == 'darwin':
    app = BUNDLE(collection, name='ATool.app',
                 icon=str(root / 'atool_qt' / 'assets' / 'atool.icns'),
                 bundle_identifier='com.calittle.ATool',
                 info_plist={'CFBundleName': 'ATool', 'CFBundleDisplayName': 'ATool',
                             'NSHighResolutionCapable': True})
