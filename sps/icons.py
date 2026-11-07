"""Small code-native line icons; no third-party icon assets.

Shapes follow the 1.6 px stroke, rounded-cap language of SF Symbols so the
toolbar and sidebar read as one set in both appearances.
"""
from PySide6.QtCore import QByteArray
from PySide6.QtGui import QIcon, QPixmap

PATHS = {
    "axes": '<path d="M4 4v16h16 M4 4h16v16 M4 9h3 M4 14h3 M9 20v-3 M14 20v-3"/>',
    "new": '<path d="M6 3h8l4 4v14H6z M14 3v5h4 M9 13h6 M12 10v6"/>',
    "open": '<path d="M3 7h7l2 2h9l-3 11H3z M3 7V4h7l2 3h7v2"/>',
    "save": '<path d="M4 3h14l3 3v15H3V3z M7 3v7h10V3 M7 21v-7h10v7"/>',
    "import": '<path d="M4 14v6h16v-6 M12 3v12 M7 10l5 5 5-5"/>',
    "undo": '<path d="M8 5 3 10l5 5 M3 10h11c8 0 8 10 0 10"/>',
    "redo": '<path d="m16 5 5 5-5 5 M21 10H10c-8 0-8 10 0 10"/>',
    "chart": '<path d="M4 3v17h17 M7 15l4-6 4 3 5-7"/>',
    "template": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18 M9 9v12"/>',
    "export": '<path d="M4 13v7h16v-7 M12 16V3 M7 8l5-5 5 5"/>',
    "review": '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="m7 9 2 2 3-4 M13 9h4 M7 16h10"/>',
    "data": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18 M9 4v16 M15 4v16 M3 15h18"/>',
    "text": '<path d="M5 5h14 M12 5v15 M8 20h8 M5 5v3 M19 5v3"/>',
    "trash": '<path d="M3 6h18 M9 3h6 M6 6l1 15h10l1-15 M10 10v7 M14 10v7"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 4.5 4.5"/>',
    "sidebar": '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M9.5 4v16"/>',
    "command": '<path d="M9 3a3 3 0 1 0 3 3v12a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3V6a3 3 0 1 0-3 3h12"/>',
    "sun": '<circle cx="12" cy="12" r="4.2"/><path d="M12 2v2.6 M12 19.4V22 M2 12h2.6 M19.4 12H22 M5 5l1.9 1.9 M17.1 17.1 19 19 M19 5l-1.9 1.9 M6.9 17.1 5 19"/>',
    "moon": '<path d="M20 14.5A8.5 8.5 0 0 1 9.5 4 8.5 8.5 0 1 0 20 14.5Z"/>',
    "sliders": '<path d="M4 7h10 M18 7h2 M4 17h4 M12 17h8"/><circle cx="16" cy="7" r="2.2"/><circle cx="10" cy="17" r="2.2"/>',
    "home": '<path d="M4 11 12 4l8 7v9h-5v-6H9v6H4z"/>',
    "back": '<path d="M15 5 8 12l7 7"/>',
    "forward": '<path d="m9 5 7 7-7 7"/>',
    "pan": '<path d="M12 3v18 M3 12h18 M12 3 9.5 5.5 M12 3l2.5 2.5 M12 21l-2.5-2.5 M12 21l2.5-2.5 M3 12l2.5-2.5 M3 12l2.5 2.5 M21 12l-2.5-2.5 M21 12l-2.5 2.5"/>',
    "zoom": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 4.5 4.5 M10.5 8v5 M8 10.5h5"/>',
    "plus": '<path d="M12 5v14 M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "fit": '<path d="M4 9V4h5 M20 9V4h-5 M4 15v5h5 M20 15v5h-5"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "sparkle": '<path d="M12 3.5 13.9 9 19.5 11 13.9 13 12 18.5 10.1 13 4.5 11 10.1 9Z"/><path d="M18.5 16.5 19.2 18.4 21 19 19.2 19.7 18.5 21.5 17.8 19.7 16 19 17.8 18.4Z"/>',
    "keyboard": '<rect x="2.5" y="6" width="19" height="12" rx="2.5"/><path d="M6 9.5h.01 M9 9.5h.01 M12 9.5h.01 M15 9.5h.01 M18 9.5h.01 M7 14h10"/>',
    "info": '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5 M12 8h.01"/>',
    "close": '<path d="m6 6 12 12 M18 6 6 18"/>',
}


def icon(name, color="#647792", width=1.65):
    body = PATHS.get(name, PATHS["chart"])
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
           f'<g fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round" '
           f'stroke-linecap="round">{body}</g></svg>')
    pixmap = QPixmap()
    pixmap.loadFromData(QByteArray(svg.encode()), "SVG")
    return QIcon(pixmap)
