"""Readable CLI diagnostics without credential headers or embedded input data."""
import json
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


HTTP_TRACE_PREFIX = '@OCCS_HTTP@'


def _safe_url(match):
    try:
        parts = urlsplit(match.group())
        path = re.sub(r'/p/[^/]+(?=/n/)', '/p/[redacted]', parts.path)
        return urlunsplit((parts.scheme, parts.netloc.rsplit('@', 1)[-1], path,
                           urlencode([(key, '[redacted]') for key, _ in parse_qsl(parts.query, keep_blank_values=True)]), ''))
    except ValueError:
        return '[invalid URL]'


def mask_email_address(value):
    if value is None:
        return None
    if isinstance(value, list):
        return [mask_email_address(item) for item in value]
    if not isinstance(value, str):
        return '[invalid address: ' + ('boolean' if isinstance(value, bool) else 'number' if isinstance(value, (int, float)) else 'object') + ']'
    if not value.strip():
        return '[empty address]'
    if re.fullmatch(r'\[(?:invalid address: .*|empty address|redacted)\]', value):
        return value
    parts = re.split(r'([,;])', value)
    masked = []
    for part in parts:
        if part in (',', ';'):
            masked.append(part)
            continue
        text = part.strip()
        if not text:
            masked.append('[empty address]')
            continue
        local, separator, domain = text.rpartition('@')
        if not separator:
            local = text
        if re.fullmatch(r'.{1,2}\*{3}', local) and re.fullmatch(r'[^\s@]+\.[^\s@]+', domain):
            masked.append(text)
            continue
        prefix = local[:min(2, max(1, len(local) - 1))]
        if re.fullmatch(r'[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+', text):
            masked.append(prefix + '***@' + domain)
        else:
            masked.append(f'[invalid address: {len(text)} chars, starts {json.dumps(prefix)}, ' + ('contains @]' if separator else 'no @]'))
    return ''.join(masked)


def masked_scalar(value):
    if value is None:
        return None
    if isinstance(value, str):
        if re.fullmatch(r'\[(?:masked: (?:string|number|boolean), \d+ chars|redacted)\]', value):
            return value
        if re.fullmatch(r'[^\s@,;]+@[^\s@,;]+\.[^\s@,;]+', value):
            return mask_email_address(value)
    kind = 'string' if isinstance(value, str) else 'boolean' if isinstance(value, bool) else 'number'
    return f'[masked: {kind}, {len(str(value))} chars]'


def sanitized_http_value(value, key='', *, mapped_input=False):
    """Keep useful routing/address context while masking customer data and credentials."""
    if re.search(r'authorization|cookie|password|credential|token|secret|api.?key|private.?key', key, re.I):
        return '[redacted]'
    if re.fullmatch(r'contactValue|email|emailAddress|recipient|recipients|to|cc|bcc', key, re.I):
        return mask_email_address(value)
    if not mapped_input and re.fullmatch(r'firstName|lastName|fullName|customerName|phone|telephone|address|accountNumber|accountId|acctId|personId|contactId|customerId|customerContactId|phoneNumber|postalCode|username', key, re.I):
        return '[redacted]'
    if key in ('CommunicationData', 'AssemblyData'):
        if isinstance(value, str):
            try:
                data = json.loads(value)
            except ValueError:
                return '[redacted: input data]'
            return json.dumps(sanitized_http_value(data, mapped_input=True), ensure_ascii=False, separators=(',', ':'))
        mapped_input = True
    if key in ('AssemblyRenderOutput', 'html', 'htmlBody', 'documentContent', 'fileContent', 'contentBase64'):
        return '[omitted: rendered/file content]'
    if isinstance(value, dict):
        return {name: sanitized_http_value(item, str(name), mapped_input=mapped_input) for name, item in value.items()}
    if isinstance(value, list):
        return [sanitized_http_value(item, mapped_input=mapped_input) for item in value]
    if mapped_input and isinstance(value, str) and re.fullmatch(r'templateName|deliveryType|language|key', key, re.I):
        return activity_text(value)
    if mapped_input:
        return masked_scalar(value)
    if isinstance(value, str):
        return activity_text(value)
    return value


def activity_text(text):
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', str(text)).replace('\r', '\n')
    text = re.sub(r'''https?://[^\s"'<>]+''', _safe_url, text)
    text = re.sub(r'(?im)((?:authorization|proxy-authorization)\s*[:=]\s*)(?:Bearer|Basic)\s+[^\s,\'"}]+',
                  r'\1[redacted]', text)
    text = re.sub(r'(?im)((?:set-cookie|cookie)\s*:\s*)[^\n]+', r'\1[redacted]', text)
    keys = r'authorization|proxy-authorization|password|passwordEnc|access[_-]?token|refresh[_-]?token|token|client[_-]?secret|CommunicationData|AssemblyData|firstName|lastName|fullName|customerName|phoneNumber|accountNumber|accountId|personId|contactId|customerId'
    value = r'''(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;}]+)'''
    text = re.sub(r'''(?i)(["']?(?:''' + keys + r''')["']?\s*[:=]\s*)''' + value,
                  r'\1[redacted]', text)
    if '@' in text:
        text = re.sub(r'[A-Z0-9._%+-]{1,64}@[A-Z0-9.-]{1,253}\.[A-Z]{2,63}', lambda match: mask_email_address(match.group()), text, flags=re.I)
    return text.strip()
