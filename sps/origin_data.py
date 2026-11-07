"""Explicit data-only recovery from legacy OPJ or unified OPJ/OPJU output.

No implicit trimming, imputation, numeric text conversion, unit inference or scripts.
Optional contiguous row selection is explicit and recorded in the audit.
"""
import copy
import math
from pathlib import Path
import subprocess
import tempfile

from .model import Project, Dataset, Series, read_json, COLORS
from .origin import file_hash, raw_text


def read(path, probe, *, allow_graph_only=False):
    path, probe = Path(path).resolve(strict=True), Path(probe).resolve(strict=True)
    if not path.is_file() or path.stat().st_size > 50_000_000:
        raise ValueError('Origin 工程超过读取范围')
    header = path.open('rb')
    with header: magic = header.read(80)
    if magic.startswith(b'CPYUA '):
        raise ValueError('此旧 OPJ 重绘接口尚未实现 OPJU；请用 origin-read 和已核验的外部解码模块读取 OPJU 数据。')
    if path.suffix.lower() != '.opj' or not magic.startswith(b'CPYA '):
        raise ValueError('数据恢复只接受 CPYA 旧 OPJ')
    before = file_hash(path)
    with tempfile.TemporaryDirectory(prefix='sps-origin-data-') as directory:
        directory = Path(directory); snapshot = directory / 'source.opj'; target = directory / 'probe.json'
        snapshot.write_bytes(path.read_bytes())
        if file_hash(snapshot) != before: raise ValueError('复制期间源文件变化')
        try:
            result = subprocess.run([str(probe), str(snapshot), str(target)], cwd=directory,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        except subprocess.TimeoutExpired as error: raise ValueError('读取超时') from error
        if result.returncode: raise ValueError(f'独立读取器失败：{result.returncode}')
        if file_hash(snapshot) != before or file_hash(path) != before: raise ValueError('源文件摘要变化')
        data = read_json(target)
    if data.get('schema') != 'sps.experimental.origin-probe/1': raise ValueError('读取器输出协议无效')
    if not data.get('spreads') and not any(e.get('sheets') for e in data.get('excels', [])) and not (allow_graph_only and data.get('graphs')):
        raise ValueError('读取器没有恢复任何工作表；不能把返回成功或识别文件头当成数据读取成功')
    return {'source': {'name': path.name, 'sha256': before}, 'probe': data}


def read_any(path, probe=None, decoder=None):
    """Unified headless reader; import locally to avoid the legacy adapter cycle."""
    from .origin_reader import OriginProject
    return OriginProject(path, legacy_probe=probe, opju_decoder=decoder).to_dict()


def source_info(recovery):
    if isinstance(recovery, dict) and recovery.get('schema') == 'sps.origin-data/1':
        raw = recovery['raw']
        digest = raw.get('source_sha256') if recovery['format'] == 'opju' else raw['source']['sha256']
        return {'name': recovery['filename'], 'sha256': digest}
    return recovery['source']


def sheets(recovery):
    if isinstance(recovery, dict) and recovery.get('schema') == 'sps.origin-data/1':
        roles = {'X': 0, 'Y': 1, 'Z': 2, 'XError': 3, 'YError': 4, 'Label': 5}
        result = []
        for index, item in enumerate(recovery['spreadsheets']):
            result.append({'name_hex': item['name'].encode('utf-8').hex(),
                'columns': [{'name_hex': c['name'].encode('utf-8').hex(),
                             'type_raw': roles.get(c['role']), 'sheet_raw': index,
                             'units': c.get('units'), 'logical_rows': c.get('logical_rows'),
                             'data': c['data']} for c in item['columns']]})
        if len(result) > 1000: raise ValueError('工作表数量超出限制')
        return result
    if not isinstance(recovery, dict) or not isinstance(recovery.get('probe'), dict):
        raise ValueError('请先读取 Origin 工程，再明确选择数据列')
    data = recovery['probe']
    result = list(data.get('spreads', []))
    for excel in data.get('excels', []): result.extend(excel.get('sheets', []))
    if len(result) > 1000: raise ValueError('工作表数量超出限制')
    return result


def numeric_pair(sheet, x, y, row_range=None):
    columns = sheet['columns']
    if any(type(i) is not int or i < 0 or i >= len(columns) for i in (x, y)) or x == y:
        raise ValueError('请选择不同的有效 X/Y 列')
    a, b = columns[x], columns[y]
    if a.get('sheet_raw') != b.get('sheet_raw'): raise ValueError('所选列属于不同源工作表')
    xv, yv = a['data'], b['data']
    if row_range is not None:
        if (not isinstance(row_range, (list, tuple)) or len(row_range) != 2
                or any(type(i) is not int for i in row_range)):
            raise ValueError('行区间需为零基 [start, stop)，不接受布尔或小数')
        start, stop = row_range
        if not 0 <= start < stop <= min(len(xv), len(yv)):
            raise ValueError('行区间超出所选 X/Y 列的共同存储范围')
        xv, yv = xv[start:stop], yv[start:stop]
    if not xv or len(xv) != len(yv): raise ValueError('所选列为空或长度不同；不会自动截断')
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in xv + yv):
        raise ValueError('含缺失/文本/非有限值；不会自动过滤、填补或转换')
    return copy.deepcopy(xv), copy.deepcopy(yv)


def reconstruct(recovery, pairs, xlabel='X', ylabel='Y', row_range=None):
    if not isinstance(pairs, list) or not 1 <= len(pairs) <= 32: raise ValueError('需显式选择 1–32 组列映射')
    available = sheets(recovery); project = Project(name='Recovered Origin data')
    mappings = []; source = source_info(recovery)
    for i, mapping in enumerate(pairs):
        if not isinstance(mapping, (list, tuple)) or len(mapping) != 3:
            raise ValueError('列映射格式为 工作表索引:X列索引:Y列索引')
        si, xi, yi = mapping
        if type(si) is not int or si < 0 or si >= len(available): raise ValueError('工作表索引无效')
        sheet = available[si]; xv, yv = numeric_pair(sheet, xi, yi, row_range)
        did = f'recovered_{i+1}'; title = raw_text(sheet.get('name_hex', '')) or f'Sheet {si+1}'
        label = f'Recovered series {i+1}'
        # Display labels may use recovered bytes; axis scientific meaning remains explicit.
        project.datasets.append(Dataset(did, title, {'X': xv, 'Y': yv},
                                        source=source['name'], source_sha256=source['sha256']))
        project.figure.series.append(Series(f'curve_{i+1}', did, 'X', 'Y', label=label, color=COLORS[i % len(COLORS)]))
        mappings.append({'sheet': si, 'x': xi, 'y': yi, 'rows': len(xv), 'rows_removed': 0,
                         'x_role_raw': sheet['columns'][xi].get('type_raw'),
                         'y_role_raw': sheet['columns'][yi].get('type_raw'),
                         'row_range': list(row_range) if row_range is not None else None,
                         'source_capacities': [len(sheet['columns'][xi]['data']), len(sheet['columns'][yi]['data'])],
                         'selection_explicit': row_range is not None})
    project.figure.xlabel = xlabel; project.figure.ylabel = ylabel
    project.audit.append({'kind': 'origin_explicit_data_only_recovery', 'source': source,
                          'mappings': mappings, 'limits': '仅所选列/显式连续行重绘，无自动丢点；完整原列与元数据在读取结果中保留。轴含义需人工填写，原布局/公式/样式不恢复。'})
    return project.validate()
