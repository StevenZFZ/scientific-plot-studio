"""Strict numeric CSV/TSV import with explicit column selection and provenance."""
import csv
import hashlib
from pathlib import Path

from .model import Dataset, uid, Project


def import_table(path):
    path = Path(path)
    raw = path.read_bytes()
    if len(raw) > 50_000_000:
        raise ValueError("MVP 数据文件上限为 50 MB")
    content = raw.decode("utf-8-sig")
    dialect = csv.excel_tab if path.suffix.lower() in (".tsv", ".txt") else csv.excel
    rows = list(csv.reader(content.splitlines(), dialect=dialect))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < 2 or len(rows[0]) < 2:
        raise ValueError("需要表头与至少一行数据、两列数值")
    names = [c.strip() for c in rows[0]]
    if len(set(names)) != len(names) or any(not n for n in names):
        raise ValueError("表头不能为空或重复")
    columns = {n: [] for n in names}
    for index, row in enumerate(rows[1:], 2):
        if len(row) != len(names):
            raise ValueError(f"第 {index} 行列数不一致")
        for name, value in zip(names, row):
            try:
                columns[name].append(float(value))
            except ValueError as e:
                raise ValueError(f"第 {index} 行，{name} 不是数值：{value!r}") from e
    d = Dataset(uid("data"), path.stem, columns, str(path.resolve()), hashlib.sha256(raw).hexdigest())
    Project(datasets=[d]).validate()
    return d
