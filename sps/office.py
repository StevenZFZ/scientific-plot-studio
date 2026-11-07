"""Read Office packages without activating OLE, fetching links or running scripts.

This recovers embedded Origin file bytes. It does NOT decode CPYUA/OPJU.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import io
from pathlib import Path, PurePosixPath
import posixpath
import tempfile
import xml.etree.ElementTree as ET
import zipfile

import olefile

from .model import write_json
from .origin import file_hash

MAX_PART = 50_000_000
CFB = bytes.fromhex('d0cf11e0a1b11ae1')
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
R = 'http://schemas.openxmlformats.org/package/2006/relationships'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def origin_format(data):
    if data.startswith(b'CPYUA '): return 'opju'
    if data.startswith(b'CPYA '): return 'opj'
    return None


def xml(data):
    if len(data) > 5_000_000 or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('Office XML 超出限制或含不支持的实体声明')
    class NoDoctype(ET.TreeBuilder):
        def doctype(self, *args): raise ValueError('Office XML 不接受文档类型/实体声明')
    return ET.fromstring(data, parser=ET.XMLParser(target=NoDoctype()))


@contextmanager
def package(path):
    path = Path(path)
    if path.stat().st_size > 300_000_000:
        raise ValueError('Office 文件超过 300 MB 限制')
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 40000 or sum(e.file_size for e in entries) > 2_000_000_000:
            raise ValueError('Office 压缩包展开大小超出限制')
        names = [e.filename for e in entries]
        if len(set(names)) != len(names): raise ValueError('Office 包含重复部件名')
        for e in entries:
            if '\\' in e.filename or e.filename.startswith('/') or '..' in PurePosixPath(e.filename).parts:
                raise ValueError('Office 部件路径无效')
        yield archive


def read_part(archive, name, limit=MAX_PART):
    entry = archive.getinfo(name)
    if entry.file_size > limit or entry.file_size > 1000 * max(1, entry.compress_size):
        raise ValueError('Office 部件超出大小/压缩比限制')
    return archive.read(entry)


def relationships(archive, part):
    directory, filename = posixpath.split(part)
    relname = posixpath.join(directory, '_rels', filename + '.rels')
    if relname not in archive.namelist(): return {}
    result = {}
    for element in xml(read_part(archive, relname, 5_000_000)):
        target = element.get('Target', '')
        external = element.get('TargetMode') == 'External'
        resolved = posixpath.normpath(posixpath.join(directory, target)) if not target.startswith('/') else target[1:]
        if not external and (resolved.startswith('../') or '\\' in resolved or ':' in resolved):
            raise ValueError('Office 内部关系路径无效')
        result[element.get('Id')] = {'part': resolved if not external else None, 'external': external,
                                     'type': element.get('Type', '')}
    return result


def ole_origin(data):
    """Inspect only the Contents stream; never guess data from cached previews."""
    if not data.startswith(CFB): return None
    with olefile.OleFileIO(io.BytesIO(data), raise_defects=olefile.DEFECT_INCORRECT) as compound:
        if not compound.exists('Contents'): return None
        if compound.get_size('Contents') > MAX_PART:
            raise ValueError('Origin OLE Contents 超过 50 MB')
        payload = compound.openstream('Contents').read(MAX_PART + 1)
    fmt = origin_format(payload)
    return (fmt, payload) if fmt else None


def _scan(path, archive):
    names = set(archive.namelist())
    presentation = 'ppt/presentation.xml'
    if presentation not in names:
        raise ValueError('需要 PPTX；旧 PPT、普通图片和 PDF 不能按此恢复数据')
    rels = relationships(archive, presentation)
    slides = []
    for element in xml(read_part(archive, presentation, 5_000_000)).iter(f'{{{P}}}sldId'):
        rel = rels.get(element.get(f'{{{REL}}}id'), {})
        if rel.get('part'): slides.append(rel['part'])
    uses, external = {}, []
    for index, slide in enumerate(slides, 1):
        rels = relationships(archive, slide)
        for element in xml(read_part(archive, slide, 5_000_000)).iter(f'{{{P}}}oleObj'):
            rel = rels.get(element.get(f'{{{REL}}}id'), {})
            info = {'slide': index, 'slide_part': slide, 'shape_id': element.get('spid', ''),
                    'prog_id': element.get('progId', '')}
            if rel.get('external'): external.append(info)
            elif rel.get('part'):
                # AlternateContent can repeat the same shape in Choice/Fallback.
                locations=uses.setdefault(rel['part'], [])
                if info not in locations: locations.append(info)
    objects, ignored = [], []
    for name in sorted(n for n in names if n.startswith('ppt/embeddings/') and not n.endswith('/')):
        data = read_part(archive, name)
        try: extracted = ole_origin(data)
        except (OSError, ValueError) as error:
            ignored.append({'part': name, 'reason': str(error)}); continue
        if not extracted:
            ignored.append({'part': name, 'reason': '没有可识别的 Origin Contents；未从图片猜测数据'}); continue
        fmt, payload = extracted
        objects.append({'part': name, 'format': fmt, 'bytes': len(payload), 'sha256': sha(payload),
                        'ole_sha256': sha(data), 'uses': uses.get(name, []),
                        'status': 'legacy_opj_optional_reader' if fmt == 'opj' else 'opju_preserved_not_decoded'})
    return {'schema': 'sps.office-origin/1', 'source': {'name': Path(path).name, 'sha256': file_hash(path)},
            'slides': len(slides), 'objects': objects, 'external_links': external, 'ignored': ignored,
            'counts': {'origin_objects': len(objects), 'opj': sum(o['format'] == 'opj' for o in objects),
                       'opju': sum(o['format'] == 'opju' for o in objects),
                       'unique_origin_payloads': len({o['sha256'] for o in objects}),
                       'external_links': len(external)},
            'limits': ['仅恢复嵌入对象中实际保存的工程字节，不代表完整原始实验工程。',
                       '普通图片/EMF/SVG 没有可恢复的原始表格；外链不跟随。',
                       'OPJU 只完整提取保存，尚未解析；不激活 OLE 或执行宏、公式、脚本。']}


def scan(path):
    before = file_hash(path)
    with package(path) as archive: report = _scan(path, archive)
    if file_hash(path) != before or report['source']['sha256'] != before:
        raise ValueError('扫描期间源文件变化，结果拒绝')
    return report


def extract(path, destination):
    """Write into a NEW folder atomically, retaining exact OLE and Origin bytes."""
    path, destination = Path(path).resolve(strict=True), Path(destination).resolve()
    if destination.exists(): raise ValueError('恢复目录已存在，请选择新目录')
    if not destination.parent.is_dir(): raise ValueError('恢复目录的父目录必须存在')
    before = file_hash(path)
    with tempfile.TemporaryDirectory(prefix='.sps-recovery-', dir=destination.parent) as temporary:
        stage = Path(temporary) / 'recovered'; stage.mkdir()
        with package(path) as archive:
            report = _scan(path, archive)
            for item in report['objects']:
                data = read_part(archive, item['part']); fmt, payload = ole_origin(data)
                if sha(payload) != item['sha256']: raise ValueError('恢复流摘要不一致')
                stem = item['sha256']
                item['file'] = stem + '.' + fmt
                item['ole_file'] = 'ole-' + sha(data) + '.bin'
                (stage / item['file']).write_bytes(payload)
                (stage / item['ole_file']).write_bytes(data)
        if file_hash(path) != before or report['source']['sha256'] != before:
            raise ValueError('恢复期间源文件变化，结果拒绝')
        report['source']['unchanged'] = True
        write_json(stage / 'recovery.json', report)
        stage.rename(destination)
    return report
