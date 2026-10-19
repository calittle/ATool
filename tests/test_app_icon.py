"""Native icon representations and the shared runtime window icon."""
import struct
import unittest
from unittest.mock import Mock, patch

from PySide6.QtGui import QIcon, QImage
from PySide6.QtWidgets import QApplication, QMainWindow

from atool_core.app_identity import APP_ID, icon_path, set_windows_app_id


class AppIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_png_is_high_resolution_with_transparent_exterior(self):
        image = QImage(str(icon_path()))
        self.assertEqual((image.width(), image.height()), (1024, 1024))
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        self.assertGreaterEqual(image.pixelColor(512, 512).alpha(), 250)

    def test_windows_icon_contains_decodable_frames_for_display_scales(self):
        data = icon_path('ico').read_bytes()
        reserved, kind, count = struct.unpack_from('<HHH', data)
        self.assertEqual((reserved, kind), (0, 1))
        sizes = []
        for index in range(count):
            width, height, _, _, planes, depth, length, offset = struct.unpack_from('<BBBBHHII', data, 6 + 16 * index)
            size = width or 256
            image = QImage.fromData(data[offset:offset + length], 'PNG')
            self.assertFalse(image.isNull())
            self.assertEqual((image.width(), image.height()), (size, height or 256))
            self.assertEqual((planes, depth), (1, 32))
            sizes.append(size)
        self.assertEqual(sizes, [16, 24, 32, 48, 64, 128, 256])

    def test_macos_icon_contains_standard_and_retina_representations(self):
        data = icon_path('icns').read_bytes()
        self.assertEqual(data[:4], b'icns')
        self.assertEqual(struct.unpack_from('>I', data, 4)[0], len(data))
        offset, sizes = 8, {}
        while offset < len(data):
            kind, length = struct.unpack_from('>4sI', data, offset)
            image = QImage.fromData(data[offset + 8:offset + length], 'PNG')
            self.assertFalse(image.isNull())
            sizes[kind] = image.width()
            offset += length
        self.assertEqual(offset, len(data))
        self.assertEqual(sizes[b'ic10'], 1024)
        self.assertEqual(sizes[b'ic07'], 128)
        self.assertEqual(sizes[b'ic13'], 256)
        self.assertEqual(sizes[b'ic14'], 512)

    def test_window_inherits_the_application_icon_at_small_sizes(self):
        old = self.app.windowIcon()
        self.addCleanup(self.app.setWindowIcon, old)
        self.app.setWindowIcon(QIcon(str(icon_path())))
        window = QMainWindow()
        self.addCleanup(window.close)
        for size in (16, 32, 64, 256):
            image = window.windowIcon().pixmap(size, size).toImage()
            self.assertFalse(image.isNull())
            self.assertEqual(image.width(), size)

    def test_windows_taskbar_identity_does_not_depend_on_python(self):
        import ctypes
        shell = Mock()
        with patch('atool_core.app_identity.sys.platform', 'win32'), patch.object(ctypes, 'windll', shell, create=True):
            set_windows_app_id()
        shell.shell32.SetCurrentProcessExplicitAppUserModelID.assert_called_once_with(APP_ID)
