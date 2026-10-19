"""Prepare ebill and notification email data without changing mapped input."""
import copy
import json
import tempfile
from pathlib import Path


def email_payload(payload):
    if not isinstance(payload, dict):
        raise ValueError('Mapped JSON must be an object to send email.')
    info = payload.get('CommunicationInfo')
    data = info.get('CommunicationData') if isinstance(info, dict) else None
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError as error:
            raise ValueError('CommunicationData must contain a JSON object.') from error
        if not isinstance(data, dict):
            raise ValueError('CommunicationData must contain a JSON object.')
    return data if isinstance(data, dict) else payload


def email_elements(payload):
    value = email_payload(payload)
    if 'sendDetail' in value:
        detail = value['sendDetail']
        delivery = detail.get('deliveryInfo') if isinstance(detail, dict) else None
        if not isinstance(delivery, dict):
            raise ValueError('Mapped JSON must contain a sendDetail.deliveryInfo object to send email.')
        return delivery
    path = []
    for key in ('billPrint', 'billDetails', 'cmElements'):
        path.append(key)
        value = value.get(key)
        if not isinstance(value, dict):
            raise ValueError('Mapped JSON must contain a ' + '.'.join(path) + ' object to send email.')
    return value


def email_recipients(payload):
    try:
        elements = email_elements(payload)
        if 'sendDetail' in email_payload(payload):
            address = elements.get('contactValue')
            return [address.strip()] if isinstance(address, str) and address.strip() else []
        bill = elements.get('eBill')
        values = bill.get('recipientEmails') if isinstance(bill, dict) else None
    except ValueError:
        return []
    return [str(item.get('email', '')).strip() for item in values if isinstance(item, dict) and str(item.get('email', '')).strip()] if isinstance(values, list) else []


def prepare_email_input(payload, source, recipients):
    """Return input path plus an owned temporary directory, if one is needed."""
    elements = email_elements(payload)
    notification = 'sendDetail' in email_payload(payload)
    bill = elements.get('eBill')
    if not notification and isinstance(bill, dict) and isinstance(bill.get('recipientEmails'), list):
        return Path(source), None
    addresses = [value.strip() for value in recipients.split(',') if value.strip()]
    if not addresses:
        raise ValueError('Recipient email is required.')
    prepared = copy.deepcopy(email_payload(payload))
    elements = email_elements(prepared)
    if notification:
        if len(addresses) != 1:
            raise ValueError('sendDetail email requires exactly one recipient address.')
        elements['contactValue'] = addresses[0]
    else:
        if not isinstance(elements.get('eBill'), dict):
            elements['eBill'] = {}
        elements['eBill']['recipientEmails'] = [{'email': value} for value in addresses]
    temporary = tempfile.TemporaryDirectory(prefix='atool-email-')
    path = Path(temporary.name) / 'input.json'
    try:
        path.write_text(json.dumps(prepared, ensure_ascii=False), encoding='utf-8')
    except OSError:
        temporary.cleanup()
        raise
    return path, temporary
