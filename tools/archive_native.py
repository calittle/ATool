#!/usr/bin/env python3
"""Archive tested bundles while retaining the macOS app's symlinks and modes."""
import argparse
import hashlib
import shutil
import subprocess
from pathlib import Path


def archive_bundle(bundle, destination, name):
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / (name + '.zip')
    if bundle.suffix == '.app':
        subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(bundle), str(archive)], check=True)
    else:
        shutil.make_archive(str(archive.with_suffix('')), 'zip', bundle.parent, bundle.name)
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    archive.with_suffix('.zip.sha256').write_text(f'{digest}  {archive.name}\n', encoding='utf-8')
    return archive


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--destination', type=Path, default=Path('dist'))
    parser.add_argument('--name', required=True)
    args = parser.parse_args()
    print(archive_bundle(args.bundle, args.destination, args.name))
