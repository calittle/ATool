"""Embedded HTML editing, with source retained byte-for-byte until an edit."""
import json
from pathlib import Path

from PySide6.QtCore import QObject, Slot, QUrl
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView


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
