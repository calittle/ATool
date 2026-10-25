#!/usr/bin/env python3
"""Notarize a signed app and staple its ticket before the final archive is made."""
import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path


def staple_ticket(bundle):
    for attempt in range(4):
        try:
            subprocess.run(['xcrun', 'stapler', 'staple', str(bundle)], check=True)
            return
        except subprocess.CalledProcessError as error:
            # Apple's CloudKit ticket service can lose the connection even
            # after notarization is Accepted. Retry only that service error.
            if error.returncode != 68 or attempt == 3:
                raise
            delay = 15 * (attempt + 1)
            print(f'Apple ticket service failed; retrying stapling in {delay}s.', flush=True)
            time.sleep(delay)


def notarize(bundle, keychain):
    if not bundle.is_dir() or bundle.suffix != '.app':
        raise ValueError('Expected an existing .app bundle.')
    subprocess.run(['codesign', '--verify', '--deep', '--strict', '--verbose=2', str(bundle)], check=True)
    with tempfile.TemporaryDirectory(prefix='atool-notary-') as directory:
        archive = Path(directory) / 'ATool-notarize.zip'
        subprocess.run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(bundle), str(archive)], check=True)
        submission = subprocess.run(
            ['xcrun', 'notarytool', 'submit', str(archive), '--keychain-profile', 'ATool-notary',
             '--keychain', str(keychain), '--wait', '--timeout', '25m', '--output-format', 'json'],
            capture_output=True, text=True)
        if submission.returncode:
            raise RuntimeError('Apple notarization submission failed: ' + submission.stderr.strip())
        result = json.loads(submission.stdout)
        print(f"Notarization {result.get('id')}: {result.get('status')}", flush=True)
        if result.get('status') != 'Accepted':
            if result.get('id'):
                subprocess.run(['xcrun', 'notarytool', 'log', result['id'], '--keychain-profile',
                                'ATool-notary', '--keychain', str(keychain)], check=False)
            raise RuntimeError('Apple did not accept this application; it must not be published.')
    staple_ticket(bundle)
    subprocess.run(['xcrun', 'stapler', 'validate', str(bundle)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', '--verbose=2', str(bundle)], check=True)
    subprocess.run(['spctl', '--assess', '--type', 'execute', '--verbose=2', str(bundle)], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--keychain', type=Path, required=True)
    args = parser.parse_args()
    notarize(args.bundle, args.keychain)
