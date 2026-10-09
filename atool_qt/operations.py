"""Visible, cancellable Comms operations for menu workflows."""
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout


class OperationDialog(QDialog):
    def __init__(self, workspace, title, args, callback=None, *, require_json=False, on_failure=None, channel='regular', accept_result=None, timeout_ms=None, close_on_success=True):
        super().__init__(workspace)
        self.setWindowTitle(title)
        self.resize(480, 120) if close_on_success else self.resize(720, 430)
        self.close_on_success = close_on_success
        self.auto_closed = False
        self.callback, self.require_json = callback, require_json
        self.on_failure = on_failure
        self.accept_result = accept_result
        layout = QVBoxLayout(self)
        self.status = QLabel(title + '…')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output, 1)
        self.output.setVisible(not close_on_success)
        row = QHBoxLayout()
        row.addStretch()
        self.cancel_button = QPushButton('Cancel Operation')
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        command_args = list(args)
        if require_json and '--json' not in command_args:
            command_args.append('--json')
        self.job = workspace.comms.submit(command_args, self.finished_command, channel=channel, timeout_ms=timeout_ms)
        self.job.output.connect(self.output.insertPlainText)
        self.cancel_button.clicked.connect(self.job.cancel)
        self.finished.connect(lambda: self.job.cancel() if not self.job.done else None)

    def finished_command(self, result):
        self.cancel_button.setEnabled(False)
        if result.cancelled and self.close_on_success:
            self.auto_closed = True
            self.reject()
            return
        if not result.successful and not (self.accept_result and self.accept_result(result)):
            self.show_failure(result.message)
            if self.on_failure and not result.cancelled:
                self.on_failure(result.message)
        elif self.require_json and not isinstance(result.value, dict):
            self.show_failure('The Comms command did not return a valid JSON object.')
            if self.on_failure:
                self.on_failure(self.status.text())
        else:
            self.status.setText('Completed.')
            if self.callback:
                try:
                    self.callback(result)
                except (ValueError, OSError) as error:
                    self.show_failure(str(error))
                    if self.on_failure:
                        self.on_failure(str(error))
                    return
            if self.close_on_success:
                self.auto_closed = True
                self.accept()

    def show_failure(self, message):
        self.status.setText(message)
        self.output.show()
        self.resize(720, 430)



class OperationActions:
    def run_comms_operation(self, title, args, callback=None, *, require_json=False, on_failure=None, channel='regular', accept_result=None, timeout_ms=None, close_on_success=True):
        dialog = OperationDialog(self, title, args, callback, require_json=require_json, on_failure=on_failure, channel=channel, accept_result=accept_result, timeout_ms=timeout_ms, close_on_success=close_on_success)
        self.operation_dialog = dialog
        if not dialog.auto_closed:
            dialog.show()
        return dialog.job
