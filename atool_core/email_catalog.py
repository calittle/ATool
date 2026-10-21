"""Read the CLI's Communication Email index without loading credentials."""
import json
from pathlib import Path


def email_session_target(alias, session_path=None):
    path = Path(session_path or Path.home() / '.occs-session.json')
    try:
        store = json.loads(path.read_text(encoding='utf-8'))
        sessions = store.get('sessions')
        if not isinstance(sessions, dict):
            key = f"{store.get('customer', '')}.{store.get('region', '')}/{store.get('tenancy', '')}"
            if alias and alias != key:
                return {}
            sessions = {key: store}
        else:
            aliases = store.get('aliases', {})
            key = aliases.get(alias, alias) if alias and isinstance(aliases, dict) else alias
            key = key or store.get('currentSessionKey') or next(iter(sessions), '')
        session = sessions.get(key, {})
        return {'sessionKey': key, 'baseUrl': str(session.get('baseUrl') or '').rstrip('/')} if session else {}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def email_catalog_profiles(payload, alias, target):
    if not isinstance(payload, dict) or payload.get('ok') is not True or not isinstance(payload.get('emails'), list):
        raise ValueError('The Communication Email list is invalid. Refresh from Comms.')
    source = payload.get('session')
    if not isinstance(source, dict):
        raise ValueError('The Communication Email list has no environment information. Refresh from Comms.')
    if target:
        matches = all(source.get(key) == value for key, value in target.items() if value)
    else:
        # Without the saved-session store, only an explicit matching alias is
        # identifiable. An unknown default session must never reuse another cache.
        matches = bool(alias) and source.get('alias') == alias
    if not matches:
        raise ValueError('The cached Communication Emails belong to another OCCS environment. Refresh from Comms.')
    profiles = []
    for email in payload['emails']:
        if not isinstance(email, dict) or not isinstance(email.get('uuid'), str) or not email['uuid'].strip():
            raise ValueError('A Communication Email has no parent UUID. Refresh from Comms.')
        short = str(email.get('shortName') or '').strip()
        name = str(email.get('name') or '').strip()
        label = f'{short} — {name}' if short and name and short != name else short or name or email['uuid']
        profiles.append({'name': label, 'uuid': email['uuid'].strip()})
    return profiles


def email_route_profiles(payload, alias, target):
    """Keep the parent UUID and transaction together; Email UUIDs aren't routes."""
    if not isinstance(payload, dict) or not isinstance(payload.get('routes'), list):
        raise ValueError('Refresh from Comms to load email distribution routes.')
    email_catalog_profiles({**payload, 'emails': []}, alias, target)
    profiles = []
    seen = set()
    for route in payload['routes']:
        if not isinstance(route, dict):
            raise ValueError('Invalid email distribution route. Refresh from Comms.')
        fields = [route.get(key, '') for key in ('uuid', 'transactionType', 'userDefinedTransactionType')]
        if not all(isinstance(value, str) for value in fields):
            raise ValueError('Invalid email distribution route. Refresh from Comms.')
        uuid, transaction, subtype = [value.strip() for value in fields]
        if not uuid or not transaction or (transaction == 'User Defined' and not subtype):
            raise ValueError('Incomplete email distribution route. Refresh from Comms.')
        key = json.dumps([uuid, transaction, subtype])
        if key in seen:
            continue
        seen.add(key)
        name = str(route.get('name') or route.get('shortName') or uuid)
        label = name if name == (subtype or transaction) else f'{name} / {subtype or transaction}'
        profiles.append({'key': key, 'uuid': uuid, 'name': label,
                         'transactionType': transaction, 'userDefinedTransactionType': subtype})
    return profiles
