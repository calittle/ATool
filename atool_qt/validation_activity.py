"""Keep validation detail in Activity and a compact indicator in the status bar."""
import copy
from atool_core.jsonpath_recommendations import audit_selector_paths
from .validation import PayloadValidation


class ValidationActivity:
    def show_validation_activity(self):
        # Replay on request so the indicator remains useful after Clear Activity.
        for source, messages in self.validation_messages.items():
            for message in messages:
                self.log(f'Validation · {source}: {message}')
        self.show_panel('activity')

    def set_validation_messages(self, source, messages):
        messages = tuple(dict.fromkeys(messages))
        previous = self.validation_messages.get(source, ())
        if messages:
            self.validation_messages[source] = messages
        else:
            self.validation_messages.pop(source, None)
        for message in messages:
            if message not in previous:
                self.log(f'Validation · {source}: {message}')
        self.validation_indicator.setVisible(bool(self.validation_messages))

    def refresh_validation_messages(self):
        session = self.session
        if session is not self.validation_session:
            self.validation_messages.clear()
            self.validation_session = session
        current = {}
        if session:
            payload = copy.deepcopy(session.payload)
            # Use the live clause library instead of stale embedded metadata.
            meta = payload.get('Meta')
            if isinstance(meta, dict):
                meta.pop('clause_library', None)
                meta.pop('condition_library', None)
                if isinstance(meta.get('ATool'), dict):
                    meta['ATool'].pop('clause_library', None)
            for finding in (audit_selector_paths(payload, session.data, mapped=session.mapped)
                            + audit_selector_paths(session.clauses, session.data,
                                                   mapped=session.mapped, path='$.clause_library')):
                current.setdefault(finding['path'], []).extend(finding['issues'])
            check_length = self.comms.settings.get('check_jsonpath_length', False) is True
            for issue in PayloadValidation._payload_condition_validation_issues(
                    payload, check_length_paths=check_length):
                source, _, message = issue.partition(': ')
                current.setdefault(source, []).append(message)
        for source in set(self.validation_messages) | set(current):
            self.set_validation_messages(source, current.get(source, ()))

    def panel_validation_changed(self, source, messages):
        # Forms emit changes while being populated; the package scan handles
        # those in one pass after the session and mapped data are in place.
        if not self.refreshing:
            self.set_validation_messages(source, messages)
