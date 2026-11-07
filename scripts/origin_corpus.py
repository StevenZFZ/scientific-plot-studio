"""Read-only local Origin sample evaluation; no production import promises.

Run with explicit roots/output. Private copies and extracted data belong outside
source releases. Optional GPL probe is a standalone experiment, not SPS runtime.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

EXTENSIONS = {'.opj', '.opju', '.otp', '.otpu', '.oth', '.otw', '.otwu', '.otm', '.otmu'}
MAX_BYTES = 50 * 1024 * 1024


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def signature(path):
    with Path(path).open('rb') as source:
        header = source.read(80).split(b'\n', 1)[0]
    if header.startswith(b'CPYA '):
        family = 'legacy_opj'
    elif header.startswith(b'CPYUA '):
        family = 'unicode_opju'
    else:
        family = 'unknown'
    return {'family': family, 'header_hex': header.hex(),
            'header_ascii': header.decode('ascii', errors='backslashreplace')}


def summarize_probe(data):
    if data.get('schema') != 'sps.experimental.origin-probe/1':
        raise ValueError('Unexpected probe schema')
    cells = Counter()
    columns = 0
    spreads = data['spreads'] + [sheet for excel in data.get('excels', []) for sheet in excel['sheets']]
    for spread in spreads:
        for column in spread['columns']:
            columns += 1
            for value in column['data']:
                if value is None:
                    cells['missing_or_nonfinite'] += 1
                elif isinstance(value, dict) and set(value) == {'text_hex'}:
                    bytes.fromhex(value['text_hex'])
                    cells['text'] += 1
                elif type(value) in (int, float):
                    import math
                    if not math.isfinite(value):
                        raise ValueError('Nonfinite JSON cell')
                    cells['numeric'] += 1
                else:
                    raise ValueError('Unknown probe cell')
    layers = [layer for graph in data['graphs'] for layer in graph['layers']]
    return {'counts': data['counts'], 'columns_dumped': columns,
            'cells': dict(cells), 'layers': len(layers),
            'curves': sum(len(layer['curves']) for layer in layers),
            'multi_layer_graphs': sum(len(graph['layers']) > 1 for graph in data['graphs']),
            'plot_types_raw': dict(Counter(str(c['type_raw']) for layer in layers for c in layer['curves'])),
            'status': 'experimental_objects_extracted_not_origin_verified',
            'fidelity': 'unverified; no original Origin rendering or numeric reference export'}


def evaluate(roots, output, probe=None):
    from sps.bridge import import_origin, capabilities
    roots = [Path(root).resolve(strict=True) for root in roots]
    if not roots or any(not root.is_dir() for root in roots):
        raise ValueError('Each input root must be a directory')
    output = Path(output).resolve()
    if any(output.is_relative_to(root) or root.is_relative_to(output) for root in roots):
        raise ValueError('Output and source roots must be separate')
    output.mkdir(parents=True, exist_ok=False)
    if probe:
        probe = Path(probe).resolve(strict=True)
    report = {'schema': 'sps.origin-corpus/1', 'created_at': datetime.now(timezone.utc).isoformat(),
              'roots': [str(root) for root in roots], 'bridge': capabilities(),
              'probe_executable': str(probe) if probe else None,
              'probe_sha256': sha256(probe) if probe else None,
              'scope': 'private local feasibility evaluation; not production import or template conversion',
              'groups': [], 'files': []}
    try:
        for root in roots:
            files = sorted(f for f in root.rglob('*') if f.is_file() and not f.is_symlink() and f.suffix.lower() in EXTENSIONS)
            report['groups'].append({'root': str(root), 'name': root.name,
                                     'count': len(files), 'extensions': dict(Counter(f.suffix.lower() for f in files))})
            for source in files:
                before = sha256(source)
                entry = {'source': str(source), 'group': root.name, 'relative_path': str(source.relative_to(root)),
                         'extension': source.suffix.lower(), 'bytes': source.stat().st_size,
                         'sha256_before': before, 'signature': signature(source)}
                report['files'].append(entry)
                try:
                    import_origin(source)
                    entry['sps_import'] = {'status': 'unexpected_success_requires_review'}
                except NotImplementedError as error:
                    entry['sps_import'] = {'status': 'unsupported', 'message': str(error)}
                entry['native_probe'] = {'status': 'not_run'}
                if entry['bytes'] > MAX_BYTES:
                    entry['native_probe'] = {'status': 'file_size_limit'}
                elif probe and entry['signature']['family'] == 'legacy_opj' and entry['extension'] == '.opj':
                    folder = output / f"sample-{len(report['files']):02d}-{before[:10]}"
                    folder.mkdir()
                    snapshot = folder / 'source.opj'
                    shutil.copy2(source, snapshot)
                    entry['snapshot'] = str(snapshot.relative_to(output))
                    if sha256(snapshot) != before:
                        raise RuntimeError('Source changed during snapshot')
                    target = folder / 'probe.json'
                    try:
                        result = subprocess.run([str(probe), str(snapshot), str(target)], cwd=folder,
                                                capture_output=True, timeout=15, check=False)
                        (folder / 'stdout.log').write_bytes(result.stdout)
                        (folder / 'stderr.log').write_bytes(result.stderr)
                        if result.returncode != 0:
                            entry['native_probe'] = {'status': 'parser_failed', 'returncode': result.returncode}
                        else:
                            data = json.loads(target.read_text())
                            entry['native_probe'] = summarize_probe(data)
                            entry['native_probe']['output'] = str(target.relative_to(output))
                            entry['native_probe']['output_sha256'] = sha256(target)
                    except subprocess.TimeoutExpired:
                        entry['native_probe'] = {'status': 'timeout'}
                    except (ValueError, KeyError) as error:
                        entry['native_probe'] = {'status': 'invalid_probe_output', 'error': str(error)}
                    entry['snapshot_unchanged'] = sha256(snapshot) == before
                elif entry['signature']['family'] == 'unicode_opju':
                    entry['native_probe'] = {'status': 'unsupported_opju_not_sent_to_legacy_parser'}
                entry['sha256_after'] = sha256(source)
                entry['source_unchanged'] = entry['sha256_after'] == before
        report['summary'] = {'files': len(report['files']),
                             'extensions': dict(Counter(e['extension'] for e in report['files'])),
                             'sps_import': dict(Counter(e['sps_import']['status'] for e in report['files'])),
                             'native_probe': dict(Counter(e['native_probe']['status'] for e in report['files'])),
                             'all_sources_unchanged': all(e['source_unchanged'] for e in report['files'])}
    finally:
        (output / 'corpus.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    if not report['summary']['all_sources_unchanged']:
        raise RuntimeError('Source hash changed; inspect report')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--probe', type=Path)
    args = parser.parse_args()
    result = evaluate(args.root, args.output, args.probe)
    print(json.dumps(result['summary'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    main()
