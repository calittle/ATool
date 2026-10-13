#!/usr/bin/env python3
"""Build a native distribution on its target OS with PyInstaller."""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

# Permit both direct execution and imports from tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_artifact import git_value


def stage_cli(source, destination):
    """Use an allowlist so credentials, local outputs and Git files never ship."""
    required = ('bin', 'lib', 'node_modules', 'package.json', 'package-lock.json', 'LICENSE', 'README.md')
    for name in required:
        path = source / name
        if not path.exists():
            raise ValueError(f'OCCS CLI runtime is missing {name}; run npm ci in the CLI checkout.')
    destination.mkdir(parents=True)
    for name in required:
        path = source / name
        if path.is_dir():
            shutil.copytree(path, destination / name, ignore=shutil.ignore_patterns('.git', '.env', '.env.*', '__pycache__'))
        else:
            shutil.copy2(path, destination / name)


def build(root, cli, node, node_license, dist):
    if sys.platform not in ('darwin', 'win32'):
        raise RuntimeError('Native releases must be built on macOS or Windows.')
    work = root / 'build' / 'native'
    stage = work / 'stage'
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    stage_cli(cli, stage / 'occs-cli')
    licenses = stage / 'licenses'
    licenses.mkdir()
    shutil.copy2(root / 'LICENSE', licenses / 'ATool-GPL-3.0.txt')
    shutil.copy2(cli / 'LICENSE', licenses / 'OCCS-CLI-GPL-3.0.txt')
    shutil.copy2(node_license, licenses / 'Node-LICENSE.txt')
    for name in ('Python-LICENSE.txt', 'Qt-LGPL-3.0.txt'):
        shutil.copy2(node_license.parent / name, licenses / name)
    shutil.copy2(root / 'packaging' / 'THIRD_PARTY.md', licenses / 'THIRD_PARTY.md')
    commit = git_value(root, 'rev-parse', 'HEAD', default='local')
    (stage / 'BUILD_INFO.txt').write_text(
        f'source=native bundle\ncommit={commit}\nrelease_tag={git_value(root, "describe", "--tags", "--exact-match", "HEAD")}\n'
        f'dirty={str(bool(git_value(root, "status", "--porcelain"))).lower()}\n', encoding='utf-8')
    runtime_info = {
        'atool_commit': commit,
        'occs_commit': git_value(cli, 'rev-parse', 'HEAD', default='local'),
        'occs_version': json.loads((cli / 'package.json').read_text())['version'],
        'node_version': subprocess.check_output([str(node), '--version'], text=True).strip(),
        'python_version': platform.python_version(),
        'pyside6_version': __import__('PySide6').__version__,
        'architecture': platform.machine(),
    }
    (stage / 'RUNTIME_INFO.json').write_text(json.dumps(runtime_info, indent=2) + '\n', encoding='utf-8')
    environment = dict(os.environ, ATOOL_NATIVE_STAGE=str(stage), ATOOL_NATIVE_NODE=str(node),
                       PYINSTALLER_CONFIG_DIR=str(work / 'cache'))
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                    '--distpath', str(dist), '--workpath', str(work / 'pyinstaller'),
                    str(root / 'packaging' / 'ATool.spec')], cwd=root, env=environment, check=True)
    return dist / ('ATool.app' if sys.platform == 'darwin' else 'ATool')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--occs-dir', type=Path, required=True)
    parser.add_argument('--node', type=Path, required=True)
    parser.add_argument('--node-license', type=Path, required=True)
    parser.add_argument('--dist-dir', type=Path, default=Path('dist/native'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    bundle = build(root, args.occs_dir.resolve(), args.node.resolve(), args.node_license.resolve(), args.dist_dir.resolve())
    print(f'Built {bundle}')


if __name__ == '__main__':
    main()
