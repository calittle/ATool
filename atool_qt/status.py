"""The original package mode indicators and their explanations."""
from pathlib import Path
from .shared_packages import bundle_hashes, names


def differs_from_comms(root, value):
    source = value.get('sourceHashes')
    if not isinstance(source, dict) or not source:
        return False
    current = bundle_hashes(root, value)
    return any(key in current and current[key] != str(digest) for key, digest in source.items())


class WorkspaceStatus:
    def update_package_status(self):
        if not hasattr(self, 'package_label'):
            return
        session = self.session
        if session is None:
            self.package_label.setText('Package: (none)')
            self.package_label.setToolTip('')
            self.data_label.setText('Data: (none)')
            self.data_label.setToolTip('')
            self.editable_label.setText('Mode: (none)')
            self.editable_label.setToolTip('No package is open.')
            return
        value = session.bundle.get('manifest', {})
        package, version = names(value)
        label = f'{package} [{version or "(unknown)"}]' if package else session.name
        self.package_label.setText(f'Package: {label}')
        self.package_label.setToolTip(str(session.bundle.get('root') or session.source or ''))
        self.data_label.setText(f'Data: {session.data_name}' if session.mapped else 'Data: (none)')
        self.data_label.setToolTip(str(self.settings.value('lastDataFile', '')) if session.mapped else '')
        owned, sync = False, ''
        verification_error = ''
        root = session.bundle.get('root')
        try:
            entry = None
            if self.shared_package_dir:
                store = self.shared_store()
                entry = store.entry(self.shared_package_dir)
                owned = bool(entry and store.owned(entry.get('lock'), store.owner))
            if root and value:
                local_differs = differs_from_comms(root, value)
                if entry and not entry.get('unavailable_reason'):
                    shared_differs = differs_from_comms(entry['published_dir'], entry['manifest'])
                    changed = bundle_hashes(root, portable=True) != bundle_hashes(entry['published_dir'], entry['manifest'], portable=True)
                    sync = ('➡️' if changed else '') + ('☁️' if shared_differs or local_differs else '')
                else:
                    sync = '☁️' if local_differs else ''
        except (ValueError, OSError, TypeError) as error:
            verification_error = f'Could not verify package sync: {error}'
        editable = self.shared_mode in {'local', 'edit'}
        editor = self.editor
        unsaved = bool(editor and (session.payload != editor.saved['payload'] or session.clauses != editor.saved['clauses']))
        associations = bool(editor and editor.associations != editor.saved['associations'])
        icons = ['🔒' if owned else '🔓', '✏️' if editable else '👁',
                 '🟡' if unsaved else '', '⬆️' if associations else '', sync]
        self.editable_label.setText(' '.join(icon for icon in icons if icon))
        tips = ['You hold the shared edit lock.' if owned else 'No shared edit lock is held.',
                'Package is editable.' if editable else 'Package is open for testing/viewing.']
        if unsaved:
            tips.append('Assembly-template edits are unsaved.')
        if associations:
            tips.append('Package-association changes are unpublished.')
        if sync:
            tips.append({'➡️☁️': 'Update shared storage, then publish to Comms.',
                         '➡️': 'Update shared storage.', '☁️': 'Publish the shared package to Comms.'}[sync])
        if verification_error:
            tips.append(verification_error)
        self.editable_label.setToolTip('\n'.join(tips))
