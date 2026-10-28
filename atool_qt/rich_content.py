"""Embedded HTML editing, with source retained byte-for-byte until an edit."""
import json
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, Slot, QUrl
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QMenu

from .context_menus import command, copy_action


class ContentBridge(QObject):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    @Slot()
    def ready(self):
        self.editor.ready = True
        self.editor.send_context()
        self.editor.send_html()

    @Slot(int, str)
    def changed(self, generation, html):
        if generation == self.editor.generation:
            self.editor.update_source(html)

    @Slot(str)
    def contextMenu(self, value):
        self.editor.show_context_menu(json.loads(value))


class RichContentEditor(QWebEngineView):
    def __init__(self, panel):
        super().__init__(panel)
        self.panel, self.ready, self.updating_source = panel, False, False
        self.generation = 0
        self.html = panel.source.toPlainText()
        self.context = {'fields': [], 'iterations': []}
        # A private profile avoids persistent browser state and remote content scripts.
        self.profile = QWebEngineProfile(self)
        self.setPage(QWebEnginePage(self.profile, self))
        self.profile.setParent(self.page())
        self.channel = QWebChannel(self.page())
        self.bridge = ContentBridge(self)
        self.channel.registerObject('content', self.bridge)
        self.page().setWebChannel(self.channel)
        template = Path(__file__).with_name('content_editor.html').read_text(encoding='utf-8')
        chips = Path(__file__).with_name('content_chip_editors.js').read_text(encoding='utf-8')
        self.setHtml(template.replace('/* CHIP_EDITORS */', chips), QUrl('qrc:///'))

    def context_menu(self, target):
        """Build from the actual DOM target, retaining its selection and revision."""
        menu = QMenu(self)
        revision, request = target['generation'], target['request']
        menu._context_valid = lambda: revision == self.generation and self.isEnabled()

        def run(name):
            script = 'runContextCommand(' + ','.join(json.dumps(value) for value in (name, revision, request)) + ')'
            self.page().runJavaScript(script)

        def native(name):
            if target.get('chipKind') and name in ('Cut', 'Copy'):
                QApplication.clipboard().setText(target['chipMarkup'])
                if name == 'Cut':
                    run('removeChip')
                return
            script = f'restoreContext({revision},{request})'
            self.page().runJavaScript(script, lambda valid: self.page().triggerAction(getattr(QWebEnginePage.WebAction, name)) if valid else None)

        command(menu, 'Undo', lambda: run('undo'), target['undo'])
        command(menu, 'Redo', lambda: run('redo'), target['redo'])
        menu.addSeparator()
        for title in ('Cut', 'Copy', 'Paste', 'SelectAll'):
            command(menu, 'Select All' if title == 'SelectAll' else title, lambda title=title: native(title),
                    target['selection'] if title in ('Cut', 'Copy') else True)
        menu.addSeparator()
        if target.get('chipKind'):
            name = {'data': 'Field', 'cond': 'Condition', 'loop': 'Loop'}[target['chipKind']]
            command(menu, 'Edit ' + name + '…', lambda: run('editChip'))
            copy_action(menu, 'Copy ' + name + ' Markup', target['chipMarkup'])
            command(menu, 'Remove ' + name + ' Chip', lambda: run('removeChip'))
        else:
            for title, name in (('Bold', 'bold'), ('Italic', 'italic'), ('Underline', 'underline'),
                                ('Format…', 'format'), ('Insert Field…', 'insertField')):
                command(menu, title, lambda name=name: run(name))
        if target.get('link'):
            menu.addSeparator()
            copy_action(menu, 'Copy Link Address', target['link'])
            command(menu, 'Edit Link…', lambda: run('editLink'))
        if target['cell']:
            table = menu.addMenu('Table')
            table._context_valid = menu._context_valid
            for title, name in (('Insert Row Above', 'rowAbove'), ('Insert Row Below', 'rowBelow'),
                                ('Insert Column Left', 'columnLeft'), ('Insert Column Right', 'columnRight'),
                                ('Split Horizontally', 'splitHorizontal'), ('Split Vertically', 'splitVertical')):
                command(table, title, lambda name=name: run(name))
            for direction in ('left', 'right', 'up', 'down'):
                command(table, 'Merge ' + direction.title(), lambda direction=direction: run('merge' + direction.title()), target['merge'][direction])
            table.addSeparator()
            command(table, 'Cell Style…', lambda: run('cellStyle'))
            command(table, 'Table Style…', lambda: run('tableStyle'))
        return menu

    def show_context_menu(self, target):
        if target.get('generation') != self.generation or not self.isEnabled():
            return
        previous = getattr(self, '_context_menu', None)
        if previous:
            previous.close()
        menu = self.context_menu(target)
        self._context_menu = menu
        menu.aboutToHide.connect(menu.deleteLater)
        menu.destroyed.connect(lambda: setattr(self, '_context_menu', None) if self._context_menu is menu else None)
        menu.popup(self.mapToGlobal(QPoint(round(target['x']), round(target['y']))))

    def set_html(self, html):
        self.generation += 1
        self.html = html
        self.send_html()

    def send_html(self):
        if self.ready:
            self.page().runJavaScript('loadHtml(' + json.dumps(self.html) + ',' + str(self.generation) + ')')

    def set_context(self, fields, iterations):
        self.context = {'fields': fields, 'iterations': iterations,
            'contents': [self.panel.browser.topLevelItem(index).text(0) for index in range(self.panel.browser.topLevelItemCount())], 'fontFamily': self.panel.workspace.comms.settings.section('content_editor').get('font_family') or ''}
        self.send_context()

    def send_context(self):
        if self.ready:
            self.page().runJavaScript('context(' + json.dumps(self.context) + ')')

    def update_source(self, html):
        if not isinstance(html, str):
            return
        self.html = html
        self.updating_source = True
        try:
            self.panel.source.setPlainText(html)
        finally:
            self.updating_source = False

    def capture(self, callback):
        if not self.ready:
            # Source remains authoritative while the rich page initializes.
            callback()
            return
        generation = self.generation
        def captured(html):
            if generation == self.generation:
                self.update_source(html)
            callback()
        self.page().runJavaScript('snapshot()', captured)

    def insert_markup(self, markup):
        if self.ready:
            self.page().runJavaScript('insertMarkup(' + json.dumps(markup) + ')')
