"""Transactional local editing with history and atomic, conflict-aware saves."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path

from .session import PackageSession
from .storage import write_files
from .validation import PayloadValidation


def rebase_history_value(base, historical, refreshed):
    """Apply a historical edit delta to refreshed server data.

    Values unchanged by the historical edit retain their refreshed values. Named
    collections preserve server metadata even across additions and reordering.
    """
    if historical == base:
        return copy.deepcopy(refreshed)
    if all(isinstance(value, dict) for value in (base, historical, refreshed)):
        result = copy.deepcopy(refreshed)
        for key in base.keys() - historical.keys():
            result.pop(key, None)
        for key, value in historical.items():
            if key not in base:
                result[key] = copy.deepcopy(value)
            elif value != base[key]:
                result[key] = rebase_history_value(base[key], value, refreshed[key]) if key in refreshed else copy.deepcopy(value)
        return result
    if all(isinstance(value, list) for value in (base, historical, refreshed)):
        for key in ('$$Id', 'Name', 'Id', 'documentShortName'):
            collections = (base, historical, refreshed)
            if not all(all(isinstance(item, dict) and item.get(key) is not None for item in rows) and len({str(item[key]) for item in rows}) == len(rows) for rows in collections):
                continue
            if not any(collections):
                continue
            old, past, new = ({str(item[key]): item for item in rows} for rows in collections)
            order = list(new) if list(old) == list(past) else list(past) + [name for name in new if name not in old and name not in past]
            result = []
            for name in order:
                if name in old and name not in past:
                    continue
                if name in past and name in old and name in new:
                    result.append(rebase_history_value(old[name], past[name], new[name]))
                elif name in past and (name not in old or past[name] != old[name]):
                    result.append(copy.deepcopy(past[name]))
                elif name in new:
                    result.append(copy.deepcopy(new[name]))
            return result
        if len(base) == len(historical) == len(refreshed):
            return [rebase_history_value(old, past, new) for old, past, new in zip(base, historical, refreshed)]
    return copy.deepcopy(historical)


class PackageEditor:
    def __init__(self, session):
        self.session = session
        self.undo_stack = []
        self.redo_stack = []
        self.associations = None
        if any(doc.get("associated") is not None for doc in session.documents):
            self.associations = [{**copy.deepcopy(doc.get("association", {})), "documentShortName": doc["name"],
                                  "documentRelIndex": doc.get("order"), "documentAlwaysTriggerInd": doc.get("always_trigger", False)}
                                 for doc in session.documents if doc.get("associated")]
        self.saved = self.snapshot()
        self.file_digest = self.digest(session.source) if session.source and session.source.is_file() else None
        self.bundle_digests = {session.bundle[key]: self.digest(session.bundle[key]) if session.bundle[key].exists() else None
                               for key in ("manifest_path", "helper_path", "master_path") if session.bundle.get(key)}

    def retain_history(self, previous):
        before, fresh = previous.snapshot(), self.snapshot()
        def retained(stack):
            result = []
            for label, state in stack:
                rebased = {key: rebase_history_value(before[key], state[key], fresh[key])
                           for key in ('payload', 'clauses', 'associations')}
                rebased['bundle'] = copy.deepcopy(fresh['bundle'])
                result.append((label, rebased))
            return result
        self.undo_stack = retained(previous.undo_stack)
        self.redo_stack = retained(previous.redo_stack)

    @staticmethod
    def digest(path):
        return hashlib.sha256(Path(path).read_bytes()).digest()

    def snapshot(self):
        return copy.deepcopy({"payload": self.session.payload, "clauses": self.session.clauses,
                              "associations": self.associations, "bundle": self.session.bundle})

    @property
    def dirty(self):
        return self.snapshot() != self.saved

    def source_changed(self, source):
        """Compare source records with the saved baseline, independent of display labels."""
        if getattr(self, '_marker_baseline', None) is not self.saved:
            self._marker_baseline = self.saved
            self._saved_source_tokens = set()
            def collect(value):
                if isinstance(value, dict):
                    self._saved_source_tokens.add(self.source_token(value))
                    for child in value.values():
                        collect(child)
                elif isinstance(value, list):
                    for child in value:
                        collect(child)
            collect(self.saved['payload'])
        return self.source_token(source) not in self._saved_source_tokens

    @staticmethod
    def source_token(source):
        return json.dumps(source, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)

    def rebuild(self):
        current = self.session
        rebuilt = PackageSession.from_payload(current.payload, current.source)
        rebuilt.clauses = current.clauses
        rebuilt.bundle = current.bundle
        if self.associations is not None:
            rebuilt.incorporate_package_documents({"associations": self.associations})
        revision = current.mapping_revision
        if current.mapped:
            rebuilt.map_data(current.data, current.data_name)
        rebuilt.mapping_revision = revision
        rebuilt.notes = current.notes
        current.__dict__.update(rebuilt.__dict__)

    def restore(self, state):
        state = copy.deepcopy(state)
        self.session.payload = state["payload"]
        self.session.clauses = state["clauses"]
        self.associations = state["associations"]
        self.session.bundle = state["bundle"]
        self.rebuild()

    def change(self, label, operation):
        before = self.snapshot()
        try:
            result = operation()
            self.rebuild()
        except Exception:
            self.restore(before)
            raise
        if self.snapshot() != before:
            self.undo_stack.append((label, before))
            self.redo_stack.clear()
        return result

    def undo(self):
        if not self.undo_stack:
            return
        label, state = self.undo_stack.pop()
        self.redo_stack.append((label, self.snapshot()))
        self.restore(state)

    def redo(self):
        if not self.redo_stack:
            return
        label, state = self.redo_stack.pop()
        self.undo_stack.append((label, self.snapshot()))
        self.restore(state)

    @staticmethod
    def unique_name(records, property_name, prefix):
        existing = {str(record.get(property_name, "")) for record in records if isinstance(record, dict)}
        index = 1
        while f"{prefix}{index}" in existing:
            index += 1
        return f"{prefix}{index}"

    @staticmethod
    def touch(source):
        source["Updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def add_record(self, kind):
        key, name_key, prefix = ("Documents", "$$Id", "NewDocument") if kind == "documents" else ("Fields", "Name", "NewField")
        records = self.session.payload.setdefault(key, [])
        name = self.unique_name(records, name_key, prefix)
        source = {name_key: name, "Descr": ""}
        if kind == "documents":
            source.update(Condition="", Layouts=[])
        else:
            source.update(Path=f"$.{name}", Mandatory=False)
        self.touch(source)
        self.change("Add " + kind.rstrip("s"), lambda: records.append(source))
        return name

    def paste_fields(self, sources):
        from .data_queries import DataQueries
        records = self.session.payload.get('Fields', [])
        existing = {str(item.get('Name', '')) for item in records if isinstance(item, dict)}
        pasted = copy.deepcopy(sources)
        if not pasted:
            raise ValueError('No fields to paste.')
        for source in pasted:
            if not isinstance(source, dict) or not isinstance(source.get('Name'), str) or not source['Name'].strip():
                raise ValueError('Each copied field must have a name.')
            path = source.get('Path')
            if not isinstance(path, str) or not path.strip():
                raise ValueError('Each copied field must have a path.')
            valid, reason = DataQueries()._validate_field_path(path)
            if not valid:
                raise ValueError(reason)
            base = source['Name'].strip()
            name, index = base, 1
            while name in existing:
                name = base + '_copy' + (str(index) if index > 1 else '')
                index += 1
            source['Name'] = name
            existing.add(name)
            self.touch(source)
        self.change('Paste fields', lambda: self.session.payload.setdefault('Fields', []).extend(pasted))
        return [source['Name'] for source in pasted]

    def update_record(self, record, values, kind):
        source = record["source"]
        name_key = "$$Id" if kind == "documents" else "Name"
        name = str(values.get(name_key, source.get(name_key, ""))).strip()
        if not name:
            raise ValueError("Name cannot be empty.")
        records = self.session.payload.get("Documents" if kind == "documents" else "Fields", [])
        if any(item is not source and item.get(name_key) == name for item in records if isinstance(item, dict)):
            raise ValueError(f"A record named '{name}' already exists.")
        if kind == "fields" and not str(values.get("Path", source.get("Path", ""))).strip():
            raise ValueError("Field path cannot be empty.")
        if kind == "fields":
            from .data_queries import DataQueries
            valid, reason = DataQueries()._validate_field_path(str(values.get("Path", source.get("Path", ""))))
            if not valid:
                raise ValueError(reason)
        def apply():
            old_name = source.get(name_key)
            changed = any(source.get(key) != value for key, value in values.items())
            if not changed:
                return
            source.update(values)
            source[name_key] = name
            self.touch(source)
            # AT names are independent of Comms document identities. A rename
            # exposes a missing association until the user associates that name.
        self.change("Edit " + kind.rstrip("s"), apply)

    def remove_record(self, record, kind):
        records = self.session.payload["Documents" if kind == "documents" else "Fields"]
        source = record["source"]
        if kind == "documents":
            names = self.document_descendants(record['name'])
            self.change("Remove document and descendants", lambda: records.__setitem__(slice(None), [row for row in records if not isinstance(row, dict) or row.get('$$Id') not in names]))
        else:
            self.change("Remove field", lambda: records.remove(source))

    def document_descendants(self, name):
        # The original identifies parents by the nearest existing underscore prefix.
        return {row.get('$$Id') for row in self.session.payload.get('Documents', [])
                if isinstance(row, dict) and (row.get('$$Id') == name or str(row.get('$$Id', '')).startswith(name + '_'))}

    def layout_source(self, document, key):
        path = ["Layouts"] + key.split("/")[1:]
        current = document["source"]
        parent, slot = None, None
        for part in path:
            parent = current
            slot = int(part) if isinstance(parent, list) else part
            if isinstance(parent, dict) and slot == "Iteration" and "Iteration" not in parent:
                slot = "iteration"
            current = parent[slot]
        return current, parent, slot

    def update_layout(self, document, key, values):
        source, _, _ = self.layout_source(document, key)
        if key.endswith('/Iteration') and values.get('Type') and values['Type'] not in {'Iterator', 'Spliterator'}:
            raise ValueError("Iteration Type must be either 'Iterator' or 'Spliterator'.")
        def apply():
            if any(source.get(key) != value for key, value in values.items()):
                source.update(values)
                self.touch(document["source"])
        self.change("Edit layout item", apply)

    def add_layout_item(self, document, kind, parent_key=None):
        owner = self.layout_source(document, parent_key)[0] if parent_key else document["source"]
        if kind == "Iteration":
            if isinstance(owner.get("Iteration", owner.get("iteration")), dict):
                raise ValueError("This content already has an iteration.")
            source = {"$$Id": "NewIteration1", "Descr": "", "Condition": "", "Path": "$", "Type": "Array", "Fields": []}
            def apply():
                owner["Iteration"] = source
                self.touch(document["source"])
            self.change("Add iteration", apply)
            return parent_key + "/Iteration"
        property_name, name_key, prefix = {"Layout": ("Layouts", "$$Id", "NewLayout"),
                                          "Content": ("Contents", "$$Id", "NewContent"),
                                          "Field": ("Fields", "Name", "NewIterField")}[kind]
        existing = owner.get(property_name, [])
        source = {name_key: self.unique_name(existing, name_key, prefix), "Descr": "", "Condition": ""}
        if kind == "Layout":
            source["Contents"] = []
        if kind == "Field":
            source.update(Path="$", Mandatory=False)
        def apply():
            owner.setdefault(property_name, []).append(source)
            self.touch(document["source"])
        self.change("Add " + kind.lower(), apply)
        return (parent_key + "/" + property_name if parent_key else "layout") + f"/{len(owner[property_name]) - 1}"

    def remove_layout_item(self, document, key):
        _, parent, slot = self.layout_source(document, key)
        def apply():
            if isinstance(parent, list):
                parent.pop(slot)
            else:
                del parent[slot]
            self.touch(document["source"])
        self.change("Remove layout item", apply)

    def move_layout_item(self, document, key, direction):
        source, siblings, index = self.layout_source(document, key)
        if not isinstance(siblings, list):
            return key
        destination = index + direction
        if not 0 <= destination < len(siblings):
            return key
        def apply():
            siblings.pop(index)
            siblings.insert(destination, source)
            self.touch(document["source"])
        self.change("Move layout item", apply)
        return key.rsplit("/", 1)[0] + f"/{destination}"

    def paste_layout_items(self, document, kind, clipboard, selected_key=None):
        """Paste homogeneous items after the selected sibling or into its ancestor."""
        if kind not in {'Layout', 'Content', 'Iteration', 'Field'} or not clipboard:
            raise ValueError('Copy layout items of one kind before pasting.')
        if kind == 'Iteration' and len(clipboard) != 1:
            raise ValueError('Select one iteration to copy.')
        parent_kind = {'Content': 'Layout', 'Iteration': 'Content', 'Field': 'Iteration'}.get(kind)
        selected_source = self.layout_source(document, selected_key)[0] if selected_key else None
        ancestor = selected_key
        if kind == 'Layout':
            owner, property_name, prefix = document['source'], 'Layouts', 'layout'
            ancestor = 'layout/' + selected_key.split('/')[1] if selected_key else None
        else:
            while ancestor:
                if ((parent_kind == 'Layout' and len(ancestor.split('/')) == 2) or
                    (parent_kind == 'Content' and len(ancestor.split('/')) > 1 and ancestor.split('/')[-2] in {'Contents', 'Content', 'contents', 'content'}) or
                    (parent_kind == 'Iteration' and ancestor.endswith('/Iteration'))):
                    break
                ancestor = ancestor.rsplit('/', 1)[0] if '/' in ancestor else None
            if not ancestor:
                raise ValueError(f'Select a {parent_kind.lower()} before pasting {kind.lower()}s.')
            owner = self.layout_source(document, ancestor)[0]
            keys = {'Content': ('Contents', 'Content', 'contents', 'content'),
                    'Field': ('Fields', 'fields'), 'Iteration': ('Iteration', 'iteration')}[kind]
            property_name = next((key for key in keys if isinstance(owner.get(key), list if kind != 'Iteration' else dict)), keys[0])
            prefix = ancestor + '/' + property_name
        if kind == 'Iteration':
            if isinstance(owner.get('Iteration', owner.get('iteration')), dict):
                raise ValueError('This content already has an iteration.')
            def apply():
                owner[property_name] = copy.deepcopy(clipboard[0])
                self.touch(document['source'])
            self.change('Paste iteration', apply)
            return ancestor + '/Iteration'
        items = owner.get(property_name, [])
        if not isinstance(items, list):
            raise ValueError('The destination list is malformed.')
        insertion = len(items)
        anchor = self.layout_source(document, ancestor)[0] if kind == 'Layout' and ancestor else selected_source
        for index, item in enumerate(items):
            if item is anchor:
                insertion = index + 1
                break
        existing = {str(item.get(key, '')).strip() for item in items if isinstance(item, dict)
                    for key in ('$$Id', 'Name', 'Id') if str(item.get(key, '')).strip()}
        pasted = copy.deepcopy(clipboard)
        for item in pasted:
            identity = next((key for key in ('$$Id', 'Name', 'Id') if str(item.get(key, '')).strip()), None)
            if identity:
                base = str(item[identity]).strip()
                name, counter = base, 1
                while name in existing:
                    name = base + ' Copy' + (f' {counter}' if counter > 1 else '')
                    counter += 1
                item[identity] = name
                existing.add(name)
        def apply():
            owner.setdefault(property_name, items)[insertion:insertion] = pasted
            self.touch(document['source'])
        self.change('Paste ' + kind.lower() + 's', apply)
        return prefix + f'/{insertion}'

    def add_clause(self):
        name = self.unique_name(self.session.clauses, "name", "Clause")
        self.change("Add clause", lambda: self.session.clauses.append({"name": name, "description": "", "expression": ""}))
        return name

    def save_clause(self, old_name, name, description, expression):
        name, expression = name.strip(), expression.strip()
        if not name:
            raise ValueError("A clause needs a name.")
        if any(entry["name"] == name and entry["name"] != old_name for entry in self.session.clauses):
            raise ValueError(f"A clause named '{name}' already exists.")
        from .clauses import ClauseComposer
        proposed = copy.deepcopy(self.session.clauses)
        index = next(index for index, entry in enumerate(proposed) if entry["name"] == old_name)
        proposed[index].update(name=name, description=description, expression=expression)
        # Rename explicit references in the library without rewriting raw AT logic.
        if name != old_name:
            for entry in proposed:
                entry["expression"] = entry["expression"].replace("CLAUSE{" + old_name + "}", "CLAUSE{" + name + "}")
        if expression:
            ClauseComposer._resolve_clause_expression_by_name_from_entries(proposed, name)
        self.change("Save clause", lambda: setattr(self.session, "clauses", proposed))

    def remove_clause(self, name):
        references = [entry["name"] for entry in self.session.clauses if entry["name"] != name and
                      "CLAUSE{" + name + "}" in entry["expression"]]
        if references:
            raise ValueError("This clause is referenced by: " + ", ".join(references))
        self.change("Delete clause", lambda: setattr(self.session, "clauses", [entry for entry in self.session.clauses if entry["name"] != name]))

    def association_for(self, record):
        if not record.get("associated"):
            raise ValueError("Select a document associated with this package.")
        uuid = record.get("association", {}).get("documentConfigUuid")
        match = next((row for row in self.associations or [] if
                      (uuid and row.get("documentConfigUuid") == uuid) or
                      (not uuid and row.get("documentShortName") == record["name"])), None)
        if match is None:
            raise ValueError("The selected association could not be found.")
        return match

    def apply_trigger_proposals(self, proposals):
        sources = []
        for proposal in proposals:
            record = next((row for row in self.session.documents if row['name'] == proposal['document_name'] and row.get('in_at')), None)
            from .clauses import ClauseComposer
            canonical=ClauseComposer._canonical_condition_expression
            if record is None or canonical(record['source'].get('Condition', '')) != canonical(proposal['old_condition']):
                raise ValueError(f"The trigger for {proposal['document_name']} changed. Rebuild the proposals before applying.")
            sources.append((record['source'], proposal['new_condition']))
        def apply():
            for source, condition in sources:
                source['Condition'] = condition
                self.touch(source)
        self.change('Update document triggers', apply)

    def set_always_trigger(self, record, value):
        row = self.association_for(record)
        self.change("Set always trigger", lambda: row.update(documentAlwaysTriggerInd=bool(value)))

    def move_association(self, record, direction):
        row = self.association_for(record)
        ordered = sorted(self.associations, key=lambda item: (item.get("documentRelIndex") is None, item.get("documentRelIndex") or 0))
        index = next(index for index, candidate in enumerate(ordered) if candidate is row)
        target = index + direction
        if not 0 <= target < len(ordered):
            return
        other = ordered[target]
        if not isinstance(row.get("documentRelIndex"), int) or not isinstance(other.get("documentRelIndex"), int):
            raise ValueError("Both documents must have a numeric order.")
        def apply():
            row["documentRelIndex"], other["documentRelIndex"] = other["documentRelIndex"], row["documentRelIndex"]
        self.change("Move package document", apply)

    def reorder_associations(self, names, before_name=None):
        ordered = sorted(self.associations or [], key=lambda item: (item.get("documentRelIndex") is None, item.get("documentRelIndex") or 0))
        selected = [row for row in ordered if row["documentShortName"] in names]
        if len(selected) != len(set(names)):
            raise ValueError("Only associated documents can be reordered.")
        remaining = [row for row in ordered if row["documentShortName"] not in names]
        index = next((index for index, row in enumerate(remaining) if row["documentShortName"] == before_name), len(remaining))
        result = remaining[:index] + selected + remaining[index:]
        if any(not isinstance(row.get("documentRelIndex"), int) for row in ordered):
            raise ValueError("All documents being reordered need a numeric order.")
        orders = sorted(row["documentRelIndex"] for row in ordered)
        def apply():
            for order, row in zip(orders, result):
                row["documentRelIndex"] = order
        self.change("Reorder package documents", apply)

    def remove_association(self, record):
        row = self.association_for(record)
        self.change("Remove package association", lambda: self.associations.remove(row))

    def version_uuid(self):
        bundle = self.session.bundle
        version = bundle.get("manifest", {}).get("version", {})
        master = bundle.get("master") or {}
        for value in (version.get("uuid"), version.get("versionUuid"), master.get("CommunicationPackageVersionConfigUuid"), master.get("uuid")):
            if value:
                return str(value)
        for row in self.associations or []:
            if row.get("packageVersionConfigUuid"):
                return str(row["packageVersionConfigUuid"])
        for relation in master.get("CommunicationPackageVersionDocuments", []):
            info = relationship_info(relation)
            if info and info.get("CommunicationPackageVersionConfigUuid"):
                return str(info["CommunicationPackageVersionConfigUuid"])
        return ""

    def add_association(self, document):
        if not self.session.bundle:
            raise ValueError("Open a package bundle before adding an association.")
        uuid, name = str(document.get("uuid", "")).strip(), str(document.get("shortName", "")).strip()
        version_uuid = self.version_uuid()
        if not uuid or not name or not version_uuid:
            raise ValueError("The document UUID, short name, and package version UUID are required.")
        if any(row.get("documentConfigUuid") == uuid or row.get("documentShortName", "").casefold() == name.casefold() for row in self.associations or []):
            raise ValueError("This document is already associated with the package.")
        order = max((row.get("documentRelIndex") or 0 for row in self.associations or []), default=0) + 1
        row = {"relUuid": "", "documentConfigUuid": uuid, "documentShortName": name, "documentName": document.get("name", ""),
               "documentDescription": document.get("description", ""), "documentConfigId": document.get("configId", ""),
               "documentRelIndex": order, "documentAlwaysTriggerInd": False, "packageVersionConfigUuid": version_uuid, "configId": "", "resolved": True}
        def apply():
            if self.associations is None:
                self.associations = []
            self.associations.append(row)
            documents = self.session.payload.setdefault("Documents", [])
            if not any(source.get("$$Id", "").casefold() == name.casefold() for source in documents if isinstance(source, dict)):
                source = {"$$Id": name, "Descr": document.get("description") or document.get("name", ""), "Condition": "", "Layouts": []}
                self.touch(source)
                documents.append(source)
        self.change("Add package document", apply)
        return name

    def bundle_payloads(self):
        bundle = self.session.bundle
        helper = copy.deepcopy(bundle.get("helper") or {"schemaVersion": "occs-cli/document-associations/v1"})
        helper["associations"] = copy.deepcopy(self.associations or [])
        master = copy.deepcopy(bundle.get("master") or {})
        by_uuid = {row.get("documentConfigUuid"): row for row in self.associations or []}
        if any(not uuid for uuid in by_uuid):
            raise ValueError("A package association has no document UUID.")
        if len(by_uuid) != len(self.associations or []):
            raise ValueError("Duplicate document UUIDs must be resolved before saving package associations.")
        relations, seen = [], set()
        for relation in master.get("CommunicationPackageVersionDocuments", []):
            info = relationship_info(relation)
            if info is None:
                relations.append(relation)
                continue
            uuid = info.get("CommunicationDocumentConfigUuid")
            if not uuid:
                relations.append(relation)
                continue
            row = by_uuid.get(uuid)
            if row is None:
                continue
            info.update(DocumentRelIndex=row["documentRelIndex"], DocumentAlwaysTriggerInd=row["documentAlwaysTriggerInd"])
            relations.append(relation)
            seen.add(uuid)
        for uuid, row in by_uuid.items():
            if uuid not in seen:
                if not self.version_uuid():
                    raise ValueError("The package version UUID is required to create a document relationship.")
                relations.append({"CommunicationPackageVersionConfigCommunicationDocumentConfigRelRec": {
                    "CommunicationPackageVersionConfigCommunicationDocumentConfigRelInfo": {
                        "CommunicationPackageVersionConfigUuid": self.version_uuid(), "CommunicationDocumentConfigUuid": uuid,
                        "DocumentRelIndex": row["documentRelIndex"], "DocumentAlwaysTriggerInd": row["documentAlwaysTriggerInd"]}}})
        master["CommunicationPackageVersionDocuments"] = relations
        manifest = copy.deepcopy(bundle["manifest"])
        files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
        manifest["files"] = files
        files["documentAssociations"] = str(bundle["helper_path"].relative_to(bundle["root"]))
        files["versionMaster"] = str(bundle["master_path"].relative_to(bundle["root"]))
        return helper, master, manifest

    def save(self, path=None):
        destination = Path(path or self.session.source) if path or self.session.source else None
        if destination is None:
            raise ValueError("Choose a file to save this package.")
        same_source = self.session.source and destination.resolve() == self.session.source.resolve()
        if same_source and self.file_digest is not None and (not destination.exists() or self.digest(destination) != self.file_digest):
            raise ValueError("The file changed outside ATool. Reopen it or save to a different file.")
        payload = copy.deepcopy(self.session.payload)
        PayloadValidation._sanitize_package_text_object(payload)
        PayloadValidation._normalize_field_mandatory_defaults(payload)
        issues = PayloadValidation._payload_condition_validation_issues(payload)
        if issues:
            raise ValueError('Invalid Conditions:\n' + '\n'.join(issues[:8]))
        meta = payload.setdefault("Meta", {})
        if not isinstance(meta, dict):
            raise ValueError("Meta must be a JSON object before saving clauses.")
        if isinstance(meta.get("ATool"), dict) and "clause_library" in meta["ATool"]:
            meta["ATool"]["clause_library"] = copy.deepcopy(self.session.clauses)
        else:
            meta["clause_library"] = copy.deepcopy(self.session.clauses)
        def encoded(value):
            return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        files = {destination: encoded(payload)}
        bundle_updates = None
        if same_source and self.session.bundle and self.associations != self.saved["associations"]:
            for path, digest in self.bundle_digests.items():
                current_digest = self.digest(path) if path.exists() else None
                if digest != current_digest:
                    raise ValueError(f"{path.name} changed outside ATool. Reopen the package before saving.")
            bundle = self.session.bundle
            for key, path_key in (("helper", "helper_path"), ("master", "master_path")):
                if bundle.get(key) is None and bundle[path_key].exists():
                    raise ValueError(f"Cannot overwrite invalid metadata in {bundle[path_key].name}.")
            bundle_updates = self.bundle_payloads()
            for key, value in zip(("helper_path", "master_path", "manifest_path"), bundle_updates):
                files[bundle[key]] = encoded(value)
        write_files(files)
        if bundle_updates:
            for key, value in zip(("helper", "master", "manifest"), bundle_updates):
                self.session.bundle[key] = value
            self.bundle_digests = {path: self.digest(path) for path in self.bundle_digests}
        elif not same_source:
            self.session.bundle = {}
            self.associations = None
            self.bundle_digests = {}
            for stack in (self.undo_stack, self.redo_stack):
                for _, state in stack:
                    state["bundle"], state["associations"] = {}, None
        self.session.source = destination.resolve()
        self.session.payload = payload
        self.rebuild()
        self.file_digest = self.digest(destination)
        self.saved = self.snapshot()
        return destination


def relationship_info(relation):
    if not isinstance(relation, dict):
        return None
    rec = relation.get("CommunicationPackageVersionConfigCommunicationDocumentConfigRelRec")
    if not isinstance(rec, dict):
        return None
    info = rec.get("CommunicationPackageVersionConfigCommunicationDocumentConfigRelInfo")
    return info if isinstance(info, dict) else None
