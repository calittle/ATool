"""Durable guided-migration evidence and immutable smoke-suite inputs."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .smoke_tests import smoke_plan
from .storage import stage_bytes


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def eligible_batch(configs, value):
    """The movement API migrates all eligible Configs, not just --config-id."""
    items=value.get('eligible')
    if not isinstance(items,list) or not items or not all(isinstance(item,dict) for item in items):
        raise ValueError('The migration dry run did not return an eligible Config batch.')
    def tokens(item):
        return {str(item.get(key) or '').strip().casefold() for key in ('id','uuid','shortName','name')} - {''}
    matches=[{index for index,config in enumerate(configs) if tokens(config)&tokens(item)} for item in items]
    if any(len(match)!=1 for match in matches) or set.union(*matches)!=set(range(len(configs))) or len(items)!=len(configs):
        raise ValueError('The eligible migration batch differs from the selected Configs. '
                         'Movement includes every eligible Config. Start a new migration record with the full intended batch, '
                         'or resolve the extra/missing Configs before retrying.')
    return items


class MigrationRecord:
    def __init__(self,path,data):
        self.path=Path(path)
        self.data=data
        self.original=self.path.read_bytes() if self.path.exists() else None

    @classmethod
    def load(cls,path):
        path=Path(path)
        encoded=path.read_bytes()
        data=json.loads(encoded.decode('utf-8'))
        if (not isinstance(data,dict) or data.get('version')!=1 or
                data.get('stage') not in ('preflight','sync','close','migrate','awaiting_completion','postflight','review','complete') or
                not isinstance(data.get('configs'),list) or not data['configs'] or
                not all(isinstance(c,dict) and c.get('id') for c in data['configs']) or
                not isinstance(data.get('settings'),dict) or not isinstance(data.get('hashes'),dict) or
                not isinstance(data.get('events'),list)):
            raise ValueError('This is not a supported guided migration record.')
        record=cls(path,data)
        record.original=encoded
        return record

    @classmethod
    def create(cls,root,settings,suite_path,configs,source,target,source_package='CLP_bills',target_package='print_bulk'):
        if not source or not target or source.casefold()==target.casefold():
            raise ValueError('Choose different source and target session aliases.')
        if not configs or len({c['id'] for c in configs})!=len(configs):
            raise ValueError('Select the Configs to migrate.')
        plan=smoke_plan(settings,True,False,suite_path=suite_path)
        suite=copy.deepcopy(plan['suite'])
        option,target_value=plan['runs'][0]['args'][:2]
        suite['session' if option=='--session' else 'tenancy']=target_value
        folder=Path(root)/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8])
        folder.mkdir(parents=True)
        try:
            hashes={}
            for index,test in enumerate(suite['tests']):
                input_path=Path(test['input'])
                relative=Path('inputs')/(str(index+1)+input_path.suffix)
                destination=folder/relative
                destination.parent.mkdir(exist_ok=True)
                shutil.copyfile(input_path,destination)
                test['input']=relative.as_posix()
                hashes[relative.as_posix()]=digest(destination)
            suite_path=folder/'suite.json'
            suite_path.write_text(json.dumps(suite,ensure_ascii=False,indent=2),encoding='utf-8')
            hashes['suite.json']=digest(suite_path)
            frozen=copy.deepcopy(settings)
            frozen.update(suite_dir=str(folder),output_dir=str(folder/'reports'),
                          comparison_source_session=source,comparison_target_session=target)
            record=cls(folder/'migration.json',dict(version=1,created_at=timestamp(),stage='preflight',
                original_suite=str(plan['source']),suite_name=suite.get('name',plan['source'].stem),
                configs=copy.deepcopy(configs),source=source,target=target,settings=frozen,hashes=hashes,
                source_package=source_package,target_package=target_package,events=[],closed=[],pending=None))
            record.event('created')
            return record
        except BaseException:
            shutil.rmtree(folder)
            raise

    @property
    def folder(self):
        return self.path.parent

    def verify_inputs(self):
        for relative,expected in self.data['hashes'].items():
            path=(self.folder/relative).resolve()
            if not path.is_relative_to(self.folder.resolve()) or digest(path)!=expected:
                raise ValueError('The saved smoke suite or inputs changed. Start a new migration record and rerun pre-migration tests.')

    def save(self):
        current=self.path.read_bytes() if self.path.exists() else None
        if current!=self.original:
            raise ValueError('This migration record changed in another window. Reopen it before continuing.')
        encoded=(json.dumps(self.data,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
        temporary=stage_bytes(self.path,encoded)
        try:
            os.replace(temporary,self.path)
        finally:
            temporary.unlink(missing_ok=True)
        self.original=encoded

    def event(self,kind,**details):
        self.data['events'].append(dict(at=timestamp(),kind=kind,**details))
        self.save()

    def advance(self,stage,**details):
        self.data.update(stage=stage,pending=None,**details)
        self.event('step_completed',next_stage=stage)
