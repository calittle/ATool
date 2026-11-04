"""Read cached document structure without adding resource relationships to the AT."""
from pathlib import Path

from atool_core.layout_resolver import LayoutResolver, _label


def cached_document_layouts(cache, document, at_nodes, effective_date):
    """Return a display-only merged tree and cache/version diagnostics.

    AT layout entries are often a flat catalog of settings for nested layouts.
    Keep their original editor keys when placing them in the resource tree.
    """
    root = Path(cache).expanduser()
    warnings = []
    consumed = set()

    def read(path):
        return LayoutResolver._read_json(path)

    def folder(kind, name):
        return LayoutResolver._cached_folder(root / kind, name)

    def name(node):
        return str(node['source'].get('$$Id') or node['source'].get('Name') or '').casefold()

    def warning(node, message):
        node['cache_warning'] = message
        warnings.append(message)

    def build(kind, title, relation, key, candidates, trail=(), uuid=''):
        matches = [n for n in candidates if n['kind'] == kind and name(n) == title.casefold()]
        original = matches[0] if len(matches) == 1 else None
        if original:
            consumed.add(original['key'])
            node = {**original, 'children': list(original['children']), 'origin': 'AT + Cache'}
        else:
            node = dict(kind=kind, source={'$$Id': title, **relation}, key=key,
                        state=None, rows=[], children=[], details=[], readonly=True, origin='Cache · Read only')
        node['display_key'] = key
        node['cache_source'] = {'Relationship': relation}
        always_key = 'ContentAlwaysTriggerInd' if kind == 'Content' else 'LayoutAlwaysTriggerInd'
        always = relation.get(always_key)
        node['cache_status'] = ('Always included · when parent is included' if always is True else
                                'Conditional · AT condition unavailable' if always is False else
                                'Cached relationship · trigger state unknown')
        if len(matches) > 1:
            warning(node, f'Ambiguous AT placement for {title}; AT entries remain separate.')
        if kind == 'Content':
            # Content membership remains visible even without a downloaded body.
            try:
                directory = folder('contents', title)
                masters = list(directory.glob('*_master.json'))
                if len(masters) != 1:
                    raise ValueError(f'Expected one cached content master for {title}')
                master = read(masters[0])
                version = LayoutResolver._active_version(master, 'CommunicationContentMasterVersions',
                                                        'CommunicationContentVersionConfigRec', effective_date)
                node['cache_source'].update(Path=str(masters[0]), Version=version,
                    ContentType=master.get('CommunicationContentConfigRec', {}).get('CommunicationContentConfigInfo', {}).get('ContentType', ''))
            except (ValueError, OSError, TypeError, AttributeError) as error:
                warning(node, str(error))
            return node
        if title.casefold() in trail or len(trail) >= 100:
            warning(node, f'Layout relationship cycle at {title}')
            return node
        try:
            paths = [p for p in folder('layouts', title).glob('*.json') if p.name != 'document.json']
            if len(paths) != 1:
                raise ValueError(f'Expected one cached layout record for {title}; found {len(paths)}')
            record = read(paths[0])
            config = record.get('CommunicationLayoutConfigRec', {})
            if uuid and config.get('CommunicationLayoutConfigUuid') != uuid:
                raise ValueError(f'Cached layout UUID mismatch for {title}')
            node['cache_source'].update(Path=str(paths[0]), Resource=record)
            children = []
            for group, child_kind, rel_key, info_key, index_key in (
                ('CommunicationLayoutLayouts', 'Layout', 'CommunicationLayoutConfigCommunicationLayoutConfigRelRec',
                 'CommunicationLayoutConfigCommunicationLayoutConfigRelInfo', 'LayoutRelIndex'),
                ('CommunicationLayoutContents', 'Content', 'CommunicationLayoutConfigCommunicationContentConfigRelRec',
                 'CommunicationLayoutConfigCommunicationContentConfigRelInfo', 'ContentRelIndex')):
                for index, item in enumerate(record.get(group, [])):
                    rel = item.get(rel_key, {}).get(info_key, {})
                    children.append((int(rel.get(index_key) or 0), index, child_kind, _label(item), rel))
            local = original['children'] if original else []
            node['children'] = []
            for order, index, child_kind, child_name, rel in sorted(children, key=lambda c: c[:2]):
                pool = local
                if child_kind == 'Layout' and not any(n['kind'] == 'Layout' and name(n) == child_name.casefold() for n in local):
                    pool = at_nodes
                child = build(child_kind, child_name, rel, f'{key}/{child_kind}/{index}-{order}', pool,
                              (*trail, title.casefold()), str(rel.get('RelCommunicationLayoutConfigUuid') or ''))
                node['children'].append(child)
            if original:
                node['children'].extend(n for n in original['children'] if n['key'] not in consumed)
        except (ValueError, OSError, TypeError, AttributeError, RecursionError) as error:
            warning(node, str(error))
            if original:
                node['children'] = original['children']
        return node

    try:
        directory = folder('documents', document)
        masters = list(directory.glob('*_master.json'))
        if len(masters) != 1:
            raise ValueError(f'Expected one cached document master for {document}; found {len(masters)}')
        master = read(masters[0])
        version = LayoutResolver._active_version(master, 'CommunicationDocumentMasterVersions',
                                                'CommunicationDocumentVersionConfigRec', effective_date)
        version_name = str(version.get('CommunicationDocumentVersionConfigInfo', {}).get('ShortName', ''))
        record = read(directory / 'versions' / f'{version_name}.json')
        nodes = [build('Layout', title, rel, f'cache/{index}', at_nodes, uuid=uuid)
                 for index, (title, uuid, rel) in enumerate(LayoutResolver._document_roots(record))]
        nodes.extend(n for n in at_nodes if n['key'] not in consumed)
        def placement_keys(node, parent=''):
            # Reused AT settings keep their edit key but each placement has its
            # own selection and expansion identity in the visible tree.
            node = {**node, 'display_key': node.get('display_key', parent + '/AT/' + node['key'])}
            node['children'] = [placement_keys(child, node['display_key']) for child in node['children']]
            return node
        nodes = [placement_keys(node) for node in nodes]
        status = f'Cached document {document} · version {version_name} · effective {effective_date}'
        if warnings:
            status += f' · {len(warnings)} cache warning(s)'
        return nodes, status, warnings
    except (ValueError, OSError, TypeError, AttributeError, RecursionError) as error:
        return at_nodes, f'Cached structure unavailable: {error}', [str(error)]


def cached_content_text(source):
    """Read the selected cached text body on demand; never request Comms content."""
    if 'Version' not in source:
        return 'Cached content body unavailable. Download this resource to inspect it.'
    if str(source.get('ContentType', '')).casefold() == 'image':
        return 'Image content · inspect its metadata in Cached Resource.'
    try:
        info = source['Version'].get('CommunicationContentVersionConfigInfo', {})
        directory = Path(source['Path']).parent / 'versions' / str(info.get('ShortName', ''))
        ids = [str(item.get('ContentData', {}).get('FileId', ''))
               for item in info.get('CommunicationContentVersionConfigData', {}).get('Items', [])]
        blobs = [directory / f'{identifier}.blob' for identifier in ids if identifier] or sorted(directory.glob('*.blob'))
        return '\n\n'.join(path.read_text(encoding='utf-8-sig') for path in blobs) if blobs else 'Cached content body unavailable.'
    except (OSError, UnicodeError, TypeError, AttributeError, KeyError) as error:
        return f'Cached content body unavailable: {error}'
