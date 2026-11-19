"""Conservative metadata classification without exposing sample values."""
from html.parser import HTMLParser


class RenderShape(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.structure, self.text = [], []
        self.data_depth = 0
        self.fields = 0
        self.ambiguous = False
        self.barcodes = []

    def handle_starttag(self, tag, attrs):
        if tag == 'comms-data':
            self.data_depth += 1
            self.fields += 1
            self.barcodes.append(any(key == 'barcodetype' for key, _ in attrs))
            attrs = [(key, value) for key, value in attrs if key != 'value']
        elif self.data_depth:
            if tag == 'comms-cond':
                self.ambiguous = True
            if tag == 'img' and any(self.barcodes):
                attrs = [(key, value) for key, value in attrs if key not in ('src', 'alt')]
        self.structure.append(('start', tag, tuple(sorted(attrs))))

    def handle_endtag(self, tag):
        if tag == 'comms-data':
            if self.data_depth:
                self.data_depth -= 1
                self.barcodes.pop()
            else:
                self.ambiguous = True
        self.structure.append(('end', tag))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data):
        if not self.data_depth and data.strip():
            self.text.append((len(self.structure), data))

    def handle_comment(self, data):
        if not self.data_depth:
            self.text.append((len(self.structure), data))


def render_change_kind(before, after):
    try:
        left, right = RenderShape(), RenderShape()
        left.feed(before); left.close()
        right.feed(after); right.close()
        if left.data_depth or right.data_depth or left.ambiguous or right.ambiguous:
            return 'unclassified'
        if left.structure != right.structure:
            return 'structural'
        if left.text != right.text:
            return 'unclassified'
        return 'data' if left.fields and right.fields else 'unclassified'
    except (ValueError, TypeError):
        return 'unclassified'


def classified_metadata_changes(before, after):
    result = {'structural': [], 'data': [], 'unclassified': []}
    def visit(left, right, path, field_values=False):
        if type(left) is not type(right):
            result['structural'].append(f'{path}: changed type')
        elif isinstance(left, dict):
            for key in sorted(left.keys() | right.keys()):
                child = f'{path} / {key}'
                if key not in left:
                    result['structural'].append(f'{child}: added')
                elif key not in right:
                    result['structural'].append(f'{child}: removed')
                elif key == 'Render' and isinstance(left[key], str) and isinstance(right[key], str) and left[key] != right[key]:
                    result[render_change_kind(left[key], right[key])].append(f'{child}: changed')
                else:
                    visit(left[key], right[key], child, key == 'Fields' or (field_values and key not in ('Name', 'Type', 'Path', 'Format')))
        elif isinstance(left, list):
            if all(isinstance(item, dict) and item.get('Name') for item in left + right):
                def named(items):
                    counts, named_items = {}, {}
                    for item in items:
                        name = str(item['Name'])
                        counts[name] = counts.get(name, 0) + 1
                        named_items[f'{name} [{counts[name]}]'] = item
                    return named_items
                a, b = named(left), named(right)
                visit(a, b, path, field_values)
                if list(a) != list(b) and set(a) == set(b):
                    result['structural'].append(f'{path}: order changed')
            else:
                for i in range(max(len(left), len(right))):
                    child = f'{path} [{i + 1}]'
                    if i >= len(left):
                        result['structural'].append(f'{child}: added')
                    elif i >= len(right):
                        result['structural'].append(f'{child}: removed')
                    else:
                        visit(left[i], right[i], child, field_values)
        elif left != right:
            result['data' if field_values else 'structural'].append(f'{path}: changed')
    visit(before, after, 'document')
    return result
