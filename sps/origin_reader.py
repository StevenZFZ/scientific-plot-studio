"""Headless, explicit Origin data API. Core plotting has no Origin dependency.

The optional OPJU module is external, reviewed and SHA-pinned. Its GUI is never
imported. No script, formula, Viewer or Office application is activated here.
"""
import copy
import csv
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from . import origin_data
from .origin import raw_text
from .model import read_json


@dataclass
class Column:
    name: str
    data: list
    role: str | None = None
    long_name: str | None = None
    units: str | None = None
    logical_rows: int | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def rows(self):
        return len(self.data)


@dataclass
class Spreadsheet:
    name: str
    columns: list = field(default_factory=list)
    structure_source: str = 'dataset identifiers; worksheet display name unverified'

    @property
    def max_rows(self):
        return max((c.rows for c in self.columns), default=0)

    def to_dict(self):
        names = [c.name for c in self.columns]
        if len(names) != len(set(names)):
            raise ValueError('重复列名不能无损转换为普通字典')
        return {c.name: copy.deepcopy(c.data) for c in self.columns}

    def to_dataframe(self):
        # Object dtype preserves None, signed zero, literal strings and doubles.
        # Unequal column capacities must not be silently padded by pandas.
        if len({c.rows for c in self.columns}) > 1:
            raise ValueError('列容量不同；请用 to_dict() 保留原始长度，不自动填充')
        try:
            import pandas as pd
        except ImportError as error:
            raise ImportError('DataFrame 需要可选 pandas；to_dict/CSV 不需要它') from error
        return pd.DataFrame(self.to_dict(), dtype=object)

    def to_csv(self, path):
        # Companion project.json retains exact lengths, missing cells and text.
        with Path(path).open('x', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow([c.name for c in self.columns])
            for i in range(self.max_rows):
                writer.writerow([c.data[i] if i < c.rows else '' for c in self.columns])


def read_opju(path, decoder, timeout=40, *, allow_graph_only=False):
    path, decoder = Path(path).resolve(strict=True), Path(decoder).resolve(strict=True)
    if not path.is_file() or path.stat().st_size > 50_000_000:
        raise ValueError('OPJU 需为不超过 50 MB 的文件')
    data = path.read_bytes()
    before = hashlib.sha256(data).hexdigest()
    if not data.startswith(b'CPYUA '):
        raise ValueError('需要 CPYUA OPJU 文件头')
    # Run only the reviewed primitive module through our own headless worker.
    # Private copy and working directory protect source-side exporter behavior.
    with tempfile.TemporaryDirectory(prefix='sps-opju-') as directory:
        directory = Path(directory)
        snapshot, output = directory / 'source.opju', directory / 'decoded.json'
        snapshot.write_bytes(data)
        try:
            result = subprocess.run([sys.executable, str(Path(__file__).with_name('opju_worker.py')),
                                     str(snapshot), str(output), '--decoder', str(decoder)],
                                    cwd=directory, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise ValueError('OPJU 后台解码超时') from error
        if result.returncode:
            detail = result.stderr.decode(errors='replace').strip().splitlines()
            raise ValueError('OPJU 读取失败：' + (detail[-1] if detail else str(result.returncode)))
        if hashlib.sha256(path.read_bytes()).hexdigest() != before or snapshot.read_bytes() != data:
            raise ValueError('读取期间源文件摘要变化')
        decoded = read_json(output)
    if decoded.get('schema') != 'sps.experimental.opju-probe/1' or decoded.get('source_sha256') != before:
        raise ValueError('OPJU 读取器协议或摘要无效')
    if not decoded.get('datasets') and not (allow_graph_only and decoded.get('graphs')):
        raise ValueError('没有成功解码的数据列；不能把名称扫描当作读取成功')
    return decoded


class OriginProject:
    """Unified personal-use facade; reports partial data coverage explicitly."""
    def __init__(self, filepath, *, legacy_probe=None, opju_decoder=None, allow_graph_only=False):
        path = Path(filepath).resolve(strict=True)
        if not path.is_file() or path.stat().st_size > 50_000_000:
            raise ValueError('Origin 文件需不超过 50 MB')
        with path.open('rb') as stream:
            header = stream.read(80)
        self.filename = path.name
        self.version = header.split(b'\n', 1)[0].decode('ascii', errors='replace')
        self.spreadsheets = []
        self.warnings = []
        if header.startswith(b'CPYUA '):
            decoder = opju_decoder or os.environ.get('SPS_OPJU_DECODER')
            if not decoder:
                raise ValueError('OPJU 需用 opju_decoder 或 SPS_OPJU_DECODER 明确选择外部解码模块')
            self.format = 'opju'
            self.raw = read_opju(path, decoder,allow_graph_only=allow_graph_only)
            groups = {}
            roles = {0: 'Y', 1: None, 2: 'YError', 3: 'X', 4: 'Label', 5: 'Z', 6: 'XError'}
            for item in sorted(self.raw['datasets']+self.raw.get('resolved_columns',[]),key=lambda d:d['dataset_id']):
                key = (item['book_identifier'], item['sheet_suffix'] or '1')
                sheet = groups.setdefault(key, Spreadsheet(f'{key[0]}@{key[1]}'))
                props = item.get('metadata')
                valid = props and not props.get('conflict')
                sheet.columns.append(Column(item['column_identifier'], copy.deepcopy(item['values']),
                    roles.get(props['designation_code']) if valid else None,
                    props['long_name'] if valid else None, props['units'] if valid else None,
                    item.get('logical_rows'), copy.deepcopy(item)))
            self.spreadsheets = list(groups.values())
            counts = self.raw['counts']
            self.warnings = [
                '样本范围内的部分数据解码；不是完整 Origin 工程/图形/分析恢复。',
                '保留完整存储容量；逻辑行数仅作元数据，不自动删除尾部空值。',
                '工作表以数据标识符分组；不冒充原始显示名称。',
                '尚无 Origin 数值导出金标准；不宣称覆盖所有 OPJU 版本。',
                '外部字符串解码将零长度字符串表示为 None；空文本与原生缺失语义尚未独立校准。',
            ]
            if counts['rejected']:
                self.warnings.append(f"{counts['rejected']} 列未支持；详情见 raw.rejected，不计作成功列。")
            if counts['metadata'] != counts['datasets']:
                self.warnings.append('部分列的单位、角色和逻辑行数未知；不会默认设为 Y。')
        elif header.startswith(b'CPYA '):
            probe = legacy_probe or os.environ.get('SPS_ORIGIN_PROBE')
            if not probe:
                raise ValueError('旧 OPJ 需用 legacy_probe 或 SPS_ORIGIN_PROBE 选择完整精度读取器')
            self.format = 'opj'
            self.raw = origin_data.read(path, probe,allow_graph_only=allow_graph_only)
            roles = {0: 'X', 1: 'Y', 2: 'Z', 3: 'XError', 4: 'YError', 5: 'Label', 6: None}
            for index, item in enumerate(origin_data.sheets(self.raw)):
                name = raw_text(item.get('name_hex', '')) or f'Sheet {index+1}'
                # A legacy spread can carry multiple sheet_raw values.
                groups = {}
                for c in item['columns']:
                    ordinal = c.get('sheet_raw', 0)
                    sheet = groups.setdefault(ordinal, Spreadsheet(f'{name}@{ordinal+1}', structure_source='legacy probe sheet_raw'))
                    sheet.columns.append(Column(raw_text(c.get('name_hex', '')), copy.deepcopy(c['data']),
                        roles.get(c.get('type_raw')), raw_text(c.get('long_name_hex', '')),
                        raw_text(c.get('units_hex', '')), None, copy.deepcopy(c)))
                self.spreadsheets.extend(groups.values())
            self.warnings = ['旧 OPJ 数据与部分元数据；完整图形、公式和分析语义未恢复。']
        else:
            raise ValueError('无法识别的 Origin 文件头；不按扩展名猜测格式')
        self.status = 'partial_data_recovery'

    def to_dict(self):
        return {'schema': 'sps.origin-data/1', 'filename': self.filename, 'format': self.format,
                'version': self.version, 'status': self.status, 'warnings': self.warnings[:],
                'spreadsheets': [{'name': s.name, 'structure_source': s.structure_source,
                    'max_rows': s.max_rows, 'columns': [{'name': c.name, 'role': c.role,
                        'long_name': c.long_name, 'units': c.units, 'logical_rows': c.logical_rows,
                        'capacity': c.rows, 'data': copy.deepcopy(c.data)} for c in s.columns]}
                    for s in self.spreadsheets], 'raw': copy.deepcopy(self.raw)}

    def export_csv(self, output_dir):
        destination = Path(output_dir).resolve()
        if destination.exists():
            raise ValueError('输出目录已存在；请换名，避免覆盖')
        # Numeric filenames prevent arbitrary source names becoming paths.
        with tempfile.TemporaryDirectory(prefix='.sps-origin-', dir=destination.parent) as temporary:
            stage = Path(temporary) / 'result'
            stage.mkdir()
            for i, sheet in enumerate(self.spreadsheets, 1):
                sheet.to_csv(stage / f'sheet-{i:03d}.csv')
            result = self.to_dict()
            result['csv_files'] = [{'file': f'sheet-{i:03d}.csv', 'sheet': s.name}
                                   for i, s in enumerate(self.spreadsheets, 1)]
            result['csv_note'] = 'CSV 空单元格可能表示缺失/空文本/短列填充；精确语义以完整 project.json 为准。'
            with (stage / 'project.json').open('x', encoding='utf-8') as stream:
                json.dump(result, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stage.rename(destination)
        return destination
