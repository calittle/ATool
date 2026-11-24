"""Convert saved migration evidence to a readable Markdown report without Qt."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from .storage import stage_bytes


STAGE_NAMES={'preflight':'Pre-migration testing','sync':'Package sync and publishing','close':'Config closure',
             'migrate':'Migration review','awaiting_completion':'Awaiting migration completion verification',
             'postflight':'Post-migration comparison','review':'Comparison review','complete':'Results accepted'}


def text(value):
    """Escape record values as plain Markdown, including table cells."""
    value=str(value if value is not None else 'Not recorded')
    value=value.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
    value=re.sub(r'([\\`*_{}\[\]#!|])',r'\\\1',value)
    return ' / '.join(value.splitlines())


def identity(value):
    if not isinstance(value,dict):
        return str(value).strip() if value else 'Not recorded'
    name=str(value.get('displayName') or value.get('user') or '').strip()
    user=str(value.get('user') or '').strip()
    return (name+f' ({user})' if user and user!=name else name) or 'Not recorded'


def when(value):
    if not value:
        return 'Not recorded'
    try:
        stamp=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if stamp.tzinfo:
            return stamp.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    except ValueError:
        pass
    return str(value)


def evidence_link(value,base,label,source_dir=None):
    if not value:
        return 'Not recorded'
    path=Path(value)
    if not path.is_absolute():
        path=(source_dir or base)/path
    try:
        relative=os.path.relpath(path.resolve(),base).replace(os.sep,'/')
    except ValueError:  # For example, evidence on a different Windows drive.
        return text(value)
    return f'[{text(label)}]({quote(relative,safe="/._-")})'


def outcome_label(outcome):
    if not isinstance(outcome,dict) or not outcome.get('runs'):
        return 'Not recorded'
    if outcome.get('stopped'):
        return 'Stopped; not passed'
    rows=outcome['runs']
    if any(run.get('cancelled') or run.get('timed_out') for run in rows):
        return 'Cancelled or timed out; not passed'
    if any(run.get('valid') is not True or run.get('successful') is not True for run in rows):
        return 'Failed or incomplete; not passed'
    if any(run.get('failed',0) for run in rows):
        return 'Failed previews; not passed'
    if not all(run.get('passed',0)>0 for run in rows):
        return 'Incomplete; not passed'
    reviews=sum(run.get('reviews',0) for run in rows)
    return f'Previews passed; {reviews} comparison(s) flagged for review' if reviews else 'Passed'


def batch_names(items):
    return ', '.join(str(item.get('shortName') or item.get('name') or item.get('id') or 'Unknown Config')
                     for item in items if isinstance(item,dict)) or 'Not recorded'


def event_description(event):
    kind=event.get('kind','unknown')
    if kind=='created':
        return 'Migration record created'
    if kind=='resumed':
        return 'Guide resumed'
    if kind=='migration_operator_recorded':
        return 'Migration operator recorded: '+identity(event.get('operator'))
    if kind=='step_completed':
        return 'Continued to '+STAGE_NAMES.get(event.get('next_stage'),str(event.get('next_stage')))
    if kind in ('close_started','config_closed'):
        return ('Config closure attempted: ' if kind=='close_started' else 'Config closure confirmed: ')+str(event.get('config_id',''))
    if kind=='package_copied':
        return f"Copied package {event.get('package','')} {event.get('version','')}"
    if kind=='package_publish_verified':
        action='Already matched Comms' if event.get('no_changes') else 'Published to Comms'
        return f"{action}: {event.get('package','')} {event.get('version','')}, Config {event.get('config_id','')}"
    if kind=='migration_sessions_refreshed':
        return 'Sessions refreshed: '+', '.join(event.get('aliases',[]))
    if kind=='migration_batch_check_started':
        return 'Read-only migration batch check started'
    if kind=='migration_source_login_selected':
        return 'Separate migration source login: '+str(event.get('username','Not recorded'))
    if kind in ('migration_batch_review','migration_started','movement_batch_changed'):
        action={'migration_batch_review':'Eligible batch reviewed','migration_started':'Migration initiation attempted',
                'movement_batch_changed':'Movement batch changed after review'}[kind]
        return action+': '+batch_names(event.get('eligible',[]))
    if kind=='operation_failed':
        scope='remote write outcome requires checking' if event.get('remote_write') else 'no migration request submitted by this step'
        return f"{event.get('operation','Operation')} failed ({event.get('category','unspecified')}); {scope}"
    if kind=='target_migration_verified':
        return 'Target migration manually verified: '+str(event.get('verification',{}).get('note',''))
    if kind in ('movement_not_started_verified','comparison_rejected'):
        return ('Movement not started, manually verified: ' if kind=='movement_not_started_verified' else 'Comparison rejected: ')+str(event.get('note',''))
    if kind in ('preflight_result','postflight_result'):
        return ('Pre-migration test: ' if kind=='preflight_result' else 'Post-migration comparison: ')+outcome_label(event.get('outcome'))
    if kind=='handoff_sent':
        return 'Email handoff reported sent to '+', '.join(event.get('recipients',[]))
    return str(kind).replace('_',' ').capitalize()


def migration_report(data,report_dir,*,record_dir=None):
    """Render the saved state faithfully; missing historical identities stay unknown."""
    if not isinstance(data,dict) or data.get('version')!=1 or data.get('stage') not in STAGE_NAMES or not isinstance(data.get('configs'),list):
        raise ValueError('This is not a supported guided migration record.')
    base=Path(report_dir).resolve()
    record_dir=Path(record_dir).resolve() if record_dir is not None else base
    events=data.get('events',[])
    verification=data.get('completion_verification') or {}
    lines=['# Migration Report','',
           '| Item | Value |','| --- | --- |']
    summary=[('Migration operator',identity(data.get('performed_by'))),
             ('Started by',identity(data.get('created_by'))),('Created',when(data.get('created_at'))),
             ('Status',STAGE_NAMES[data['stage']]),('Source session',data.get('source')),
             ('Target session',data.get('target')),('Test suite',data.get('suite_name')),
             ('Completion verified by',identity(verification.get('verified_by'))),
             ('Results reviewed by',identity(data.get('reviewed_by'))),('Results accepted at',when(data.get('reviewed_at'))),
             ('Email handoff','Reported sent' if data.get('email_sent') else 'Not recorded as sent')]
    lines.extend(f'| {label} | {text(value)} |' for label,value in summary)
    if data.get('pending'):
        lines+=['','**Unresolved operation:** '+text(data['pending'])+'. Check its outcome before repeating a remote write.']
    lines+=['','Historical actions without a recorded user are shown as “Not recorded”.','',
            '## Configs','','| Source ID | Short name | Name | Closure confirmed in record |','| --- | --- | --- | --- |']
    for config in data['configs']:
        values=(config.get('id'),config.get('shortName'),config.get('name'),
                'Yes' if config.get('id') in data.get('closed',[]) else 'Not recorded')
        lines.append('| '+' | '.join(text(value) for value in values)+' |')
    lines+=['','## Package sync','']
    published=data.get('published')
    if published:
        result='Already matched Comms (dry run)' if published.get('no_changes') else 'Published to Comms'
        lines+=[text(f"{result}: {published.get('package','')} {published.get('version','')}; Config {published.get('config_id','')}; session {published.get('source','')}.")]
    elif data.get('sync_skipped'):
        lines+=['Operator confirmed that package sync was not required.']
    else:
        lines+=['No verified package publish or no-sync confirmation recorded.']
    if data.get('copied_target'):
        lines+=['','Copied target: '+text(data['copied_target'])]
    lines+=['','## Migration outcome','']
    if data.get('movement',{}).get('initiated'):
        lines+=['The CLI confirmed movement initiation. This receipt alone does not confirm completion.']
        lines+=['','Movement batch: '+text(batch_names(data['movement'].get('eligible',[])))+'.']
    else:
        lines+=['No CLI initiation receipt recorded. This does not establish whether an earlier attempt moved the Configs.']
    if verification:
        lines+=['','Completion was manually verified in target '+text(verification.get('target',data.get('target')))+'.',
                '', '- Verified by: '+text(identity(verification.get('verified_by'))),
                '- Verified at: '+text(when(verification.get('verified_at'))),
                '- Previous step: '+text(STAGE_NAMES.get(verification.get('previous_stage'),verification.get('previous_stage'))),
                '- Previous unresolved operation: '+text(verification.get('previous_pending') or 'None recorded'),
                '- Verification note: '+text(verification.get('note'))]
    elif data.get('completion_note'):
        lines+=['','Recorded completion verification: '+text(data['completion_note']),
                '','Verification user and time were not recorded in this older entry.']
    else:
        lines+=['','Successful completion has not been verified in this record.']
    for key,title in (('preflight','Pre-migration test'),('postflight','Post-migration comparison')):
        outcome=data.get(key)
        lines+=['','## '+title,'',text(outcome_label(outcome))]
        if isinstance(outcome,dict) and outcome.get('runs'):
            lines+=['','| Run | Passed previews | Failed previews | Comparisons flagged for review | Evidence |','| --- | --- | --- | --- | --- |']
            for run in outcome['runs']:
                cells=[text(run.get(field)) for field in ('label','passed','failed','reviews')]
                cells.append(evidence_link(run.get('report'),base,'Smoke report',record_dir))
                lines.append('| '+' | '.join(cells)+' |')
    lines+=['','## Comparison acceptance','']
    if data['stage']=='complete':
        lines+=['Results accepted by '+text(identity(data.get('reviewed_by')))+' at '+text(when(data.get('reviewed_at')))+'.',
                '', 'Acceptance note: '+text(data.get('review_note') or 'No visual differences required explanation.')]
    else:
        lines+=['Final comparison acceptance has not been recorded.']
    lines+=['','## Handoff','']
    sent=[event for event in events if event.get('kind')=='handoff_sent']
    if data.get('email_sent') and sent:
        event=sent[-1]
        lines+=['Email reported sent by '+text(identity(event.get('actor')))+' at '+text(when(event.get('at')))+'.',
                '', 'Recipients: '+text(', '.join(event.get('recipients',[])))+'.']
    else:
        lines+=['Email sending has not been recorded. ATool does not send handoff email automatically.']
    runs=(data.get('postflight') or {}).get('runs',[])
    if runs and runs[0].get('report'):
        lines+=['',evidence_link(Path(runs[0]['report']).with_name('smoke-email.eml'),base,'Smoke email draft',record_dir)]
    lines+=['','## Action history','','| Time | User | Action |','| --- | --- | --- |']
    for event in events:
        lines.append('| '+' | '.join((text(when(event.get('at'))),text(identity(event.get('actor'))),text(event_description(event))))+' |')
    lines+=['','## Evidence and reproducibility','',
            '- Saved source record: [migration.json](migration.json)',
            '- Suite snapshot: [suite.json](suite.json)',
            '- Original suite location: '+text(data.get('original_suite')),
            '- Comparison threshold (% changed pixels): '+text(data.get('settings',{}).get('comparison_threshold_percent')),
            '', '| Snapshot file | SHA-256 |','| --- | --- |']
    for path,checksum in sorted(data.get('hashes',{}).items()):
        lines.append('| '+text(path)+' | '+text(checksum)+' |')
    return '\n'.join(lines)+'\n'


def write_migration_report(source,destination=None):
    """Convert migration.json to migration-report.md (or an explicit output path)."""
    source=Path(source).expanduser().resolve()
    destination=Path(destination).expanduser().resolve() if destination else source.with_name('migration-report.md')
    if destination==source:
        raise ValueError('The report output must not overwrite the migration JSON.')
    data=json.loads(source.read_text(encoding='utf-8'))
    content=migration_report(data,destination.parent,record_dir=source.parent)
    # Snapshot and JSON links are relative to the exported report's location.
    content=content.replace('[migration.json](migration.json)',evidence_link(source,destination.parent,'migration.json'))
    content=content.replace('[suite.json](suite.json)',evidence_link(source.with_name('suite.json'),destination.parent,'suite.json'))
    temporary=stage_bytes(destination,content.encode('utf-8'))
    try:
        os.replace(temporary,destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination
