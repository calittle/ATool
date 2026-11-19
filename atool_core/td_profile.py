"""Business cases and their explicitly mapped Comms documents."""
from copy import deepcopy


def normalize_plan(profile):
    rows = profile.get('baselines', [])
    if not isinstance(rows, list) or not rows:
        raise ValueError('Define at least one business-case baseline.')
    cases, owners = [], {}
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise ValueError(f'Baseline {index} must be an object.')
        case = str(row.get('case') or row.get('document') or '').strip()
        documents = row.get('documents', [row['document']] if row.get('document') else [])
        if not isinstance(documents, list) or not documents or any(not isinstance(d, str) or not d.strip() for d in documents):
            raise ValueError(f'Case {case or index} needs a list of expected Comms documents.')
        documents = list(dict.fromkeys(d.strip() for d in documents))
        if not case or any(item['case'] == case for item in cases):
            raise ValueError('Each business case needs a unique case ID.')
        value = deepcopy(row)
        value.pop('document', None)
        value.update(case=case, documents=documents)
        cases.append(value)
        for document in documents:
            owners.setdefault(document, []).append(case)
    references = profile.get('document_references', {})
    if not isinstance(references, dict):
        raise ValueError('document_references must map Comms document names to business-case IDs.')
    if set(references) - set(owners):
        raise ValueError('A document reference is not mapped by any business case: ' + ', '.join(sorted(set(references) - set(owners))))
    resolved = {}
    modes = profile.get('document_comparisons', {})
    if not isinstance(modes, dict) or set(modes) - set(owners) or any(mode not in ('compare', 'document_only') for mode in modes.values()):
        raise ValueError('document_comparisons must map known documents to compare or document_only.')
    for document, candidates in owners.items():
        if modes.get(document, 'compare') == 'document_only':
            resolved[document] = None
            continue
        reference = references.get(document)
        if not reference and len(candidates) == 1:
            reference = candidates[0]
        if reference not in candidates:
            raise ValueError(f'Choose a reference case for {document} from: {", ".join(candidates)}.')
        resolved[document] = reference
    return cases, resolved


def group_document_plans(case_plans, references):
    """Keep one structure per Comms document and every case's own baseline."""
    grouped = {}
    for plan in case_plans:
        grouped.setdefault(plan['spec']['document'], []).append(plan)
    result = []
    for document, cases in grouped.items():
        reference = next((item for item in cases if item['spec']['case'] == references[document]), cases[0])
        result.append({**reference, 'cases': cases, 'comparison': 'document_only' if references[document] is None else 'compare'})
    return result
