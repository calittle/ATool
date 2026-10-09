"""Original ATool build identity without loading its Tkinter interface."""
from pathlib import Path
import subprocess

APP_NAME = 'ATool for OCCS'
CONTACT_EMAIL = 'andy.little@oracle.com'


def build_info(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parent.parent
    values = {}
    try:
        for line in (root / 'BUILD_INFO.txt').read_text(encoding='utf-8').splitlines():
            key, separator, value = line.partition('=')
            if separator and key.strip():
                values[key.strip()] = value.strip()
    except OSError:
        pass
    if not values:
        def git_value(*args, default=''):
            try:
                result = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                                        text=True, encoding='utf-8', errors='replace', timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                return default
            return result.stdout.strip() or default if result.returncode == 0 else default
        values = dict(source='local worktree', commit=git_value('rev-parse', '--short', 'HEAD', default='local'),
                      release_tag=git_value('describe', '--tags', '--exact-match', 'HEAD'))
        if git_value('status', '--short'):
            values['dirty'] = 'true'
    commit = values.get('commit', '').strip()
    release = values.get('release_tag', '').strip()
    label = release or (commit[:7] if commit != 'local' else commit) or 'local'
    if values.get('dirty') == 'true' and label != 'local':
        label += '-dirty'
    values.update(build_label=label, build_label_name='Release' if release else 'Commit')
    return values


def about_text(root=None):
    info = build_info(root)
    lines = [APP_NAME, 'Qt workspace', f"{info['build_label_name']}: {info['build_label']}"]
    for key, label in (('source', 'Source'), ('built_at', 'Built'), ('artifact', 'Artifact')):
        if info.get(key):
            lines.append(f'{label}: {info[key]}')
    return '\n'.join(lines + ['', 'Contact: ' + CONTACT_EMAIL])
