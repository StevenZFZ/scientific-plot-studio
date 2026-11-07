"""Versioned clipboard payload: full native project plus generic image fallback."""
import hashlib
import json

from .model import canonical, from_dict

MIME = 'application/x-sps-project+json'
SCHEMA = 'sps.clipboard/1'
MAX_BYTES = 50_000_000


def encode(project):
    project.validate()
    body = project.to_dict()
    payload = canonical({'schema': SCHEMA, 'project': body,
                         'sha256': hashlib.sha256(canonical(body).encode()).hexdigest()}).encode()
    if len(payload) > MAX_BYTES: raise ValueError('复制的工程超过 50 MB 限制')
    return payload


def decode(payload):
    if len(payload) > MAX_BYTES: raise ValueError('剪贴板工程超过 50 MB 限制')
    data = json.loads(payload)
    if not isinstance(data, dict) or set(data) != {'schema', 'project', 'sha256'} or data['schema'] != SCHEMA:
        raise ValueError('不是受支持的 SPS 剪贴板工程')
    if hashlib.sha256(canonical(data['project']).encode()).hexdigest() != data['sha256']:
        raise ValueError('剪贴板工程摘要不一致')
    return from_dict(data['project'])


def mime_data(project):
    from PySide6.QtCore import QMimeData, QByteArray
    from PySide6.QtGui import QImage
    from .render import draw
    import io
    figure, _, _, _ = draw(project, dpi=180)
    png, svg = io.BytesIO(), io.BytesIO()
    figure.savefig(png, format='png', transparent=True, dpi=180)
    figure.savefig(svg, format='svg', transparent=True)
    result = QMimeData()
    result.setData(MIME, QByteArray(encode(project)))
    result.setData('image/svg+xml', QByteArray(svg.getvalue()))
    result.setImageData(QImage.fromData(png.getvalue(), 'PNG'))
    # No textual data fallback: pasting into an arbitrary app should not disclose
    # all research data as text by accident. Compatible SPS explicitly reads MIME.
    return result
