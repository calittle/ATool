"""Isolate single-resource CLI exports from the shared resource cache."""
from pathlib import Path
from tempfile import TemporaryDirectory


SINGLE_RESOURCE_COMMANDS = frozenset({
    'get-package', 'get-style', 'get-layout', 'get-content',
    'get-font', 'get-document', 'get-chart',
})


class ResourceDownload:
    """The CLI clears its output directory, so export into a private sibling."""

    def __init__(self, args):
        self.args = list(args)
        self.temporary = None
        self.destination = None
        if not args or args[0] not in SINGLE_RESOURCE_COMMANDS or '--output' not in args:
            return
        index = args.index('--output') + 1
        self.destination = Path(args[index]).expanduser().resolve()
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        self.temporary = TemporaryDirectory(prefix='.atool-resource-', dir=self.destination.parent)
        self.root = Path(self.temporary.name)
        self.output = self.root / 'download'
        self.args[index] = str(self.output)

    def commit(self, stdout='', stderr=''):
        if self.temporary is None:
            return
        # Some CLI versions report failed artifact requests but still exit 0.
        if 'Artifact download failures (' in stdout + stderr:
            raise ValueError('The resource download reported artifact failures; the cache was preserved.\n' + stderr.strip())
        resources = list(self.output.iterdir()) if self.output.is_dir() else []
        if len(resources) != 1 or not resources[0].is_dir() or not any(path.is_file() for path in resources[0].rglob('*')):
            raise ValueError('The single-resource download did not produce one resource folder; the cache was preserved.')
        resource = resources[0]
        self.destination.mkdir(parents=True, exist_ok=True)
        target = self.destination / resource.name
        backup = self.root / 'previous'
        if target.exists():
            target.rename(backup)
        try:
            resource.rename(target)
        except OSError:
            if backup.exists():
                backup.rename(target)
            raise

    def cleanup(self):
        if self.temporary is not None:
            self.temporary.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cleanup()
