#!/usr/bin/env python3
"""Convert the master app artwork to PNG, Windows ICO and macOS ICNS assets."""
from pathlib import Path
import struct

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage


def build_icons(directory):
    source = QImage(str(directory / 'atool-source.png'))
    if source.isNull() or source.width() != source.height():
        raise ValueError('The app icon master must be a square image.')

    def png(size):
        scaled = source.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not scaled.save(buffer, 'PNG'):
            raise RuntimeError('Could not encode the app icon.')
        return bytes(data)

    (directory / 'atool.png').write_bytes(png(1024))
    # PNG-compressed ICO frames preserve alpha at every Windows display size.
    frames = [(size, png(size)) for size in (16, 24, 32, 48, 64, 128, 256)]
    offset = 6 + 16 * len(frames)
    entries = []
    for size, data in frames:
        entries.append(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0,
                                   1, 32, len(data), offset))
        offset += len(data)
    (directory / 'atool.ico').write_bytes(
        struct.pack('<HHH', 0, 1, len(frames)) + b''.join(entries)
        + b''.join(data for _, data in frames))
    # Native ICNS PNG representations, including Retina variants.
    chunks = []
    for kind, size in ((b'icp4', 16), (b'icp5', 32), (b'icp6', 64),
                       (b'ic07', 128), (b'ic08', 256), (b'ic09', 512),
                       (b'ic10', 1024), (b'ic11', 32), (b'ic12', 64),
                       (b'ic13', 256), (b'ic14', 512)):
        data = png(size)
        chunks.append(kind + struct.pack('>I', len(data) + 8) + data)
    body = b''.join(chunks)
    (directory / 'atool.icns').write_bytes(b'icns' + struct.pack('>I', len(body) + 8) + body)


if __name__ == '__main__':
    build_icons(Path(__file__).resolve().parents[1] / 'atool_qt' / 'assets')
