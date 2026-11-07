"""Explicit data-only reconstruction for local corpus acceptance, not an importer.

No cleaning, numeric text conversion, missing-row filtering, formula execution,
unit inference or Origin layout/style migration. All selected vectors must be
finite numeric, of equal lengths, and have explicit native X/Y roles.
"""
from __future__ import annotations
import argparse
import copy
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sps.model import Dataset, Project, Series, Annotation, save, load
from sps.commands import Session
from sps import templates
from sps.render import export_bundle
try:
    from .origin_corpus import sha256
except ImportError:
    from origin_corpus import sha256


def numeric_pair(spread, x_index, y_index):
    if any(type(i) is not int or i < 0 or i >= len(spread['columns']) for i in (x_index, y_index)):
        raise ValueError('Column index out of range')
    x, y = spread['columns'][x_index], spread['columns'][y_index]
    if x['type_raw'] != 0 or y['type_raw'] != 1:
        raise ValueError('Requires explicit native X/Y roles')
    if x['sheet_raw'] != y['sheet_raw']:
        raise ValueError('Columns belong to different sheets')
    xv, yv = x['data'], y['data']
    if not xv or len(xv) != len(yv):
        raise ValueError('Unequal or empty vectors; no implicit truncation')
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in xv + yv):
        raise ValueError('Missing/text/nonfinite values require explicit future policy; no filtering')
    return copy.deepcopy(xv), copy.deepcopy(yv)


def reconstruct(corpus_path, source_name, pairs, output):
    corpus_path, output = Path(corpus_path).resolve(), Path(output).resolve()
    report = json.loads(corpus_path.read_text())
    entries = [entry for entry in report['files'] if Path(entry['source']).name == source_name]
    if len(entries) != 1:
        raise ValueError('Source name must identify exactly one corpus entry')
    entry = entries[0]
    if any(output.is_relative_to(Path(root)) or Path(root).is_relative_to(output) for root in report['roots']):
        raise ValueError('Output must be separate from source directories')
    source = Path(entry['source'])
    if sha256(source) != entry['sha256_before'] or not entry['source_unchanged']:
        raise ValueError('Original source changed since evaluation')
    probe_path = corpus_path.parent / entry['native_probe']['output']
    if sha256(probe_path) != entry['native_probe']['output_sha256']:
        raise ValueError('Probe dump changed since evaluation')
    probe = json.loads(probe_path.read_text())
    project = Project(name='Origin data-only acceptance fixture')
    mappings = []
    for index, (sheet, xi, yi) in enumerate(pairs):
        if type(sheet) is not int or sheet < 0 or sheet >= len(probe['spreads']):
            raise ValueError('Spread index out of range')
        spread = probe['spreads'][sheet]
        xv, yv = numeric_pair(spread, xi, yi)
        xc, yc = spread['columns'][xi], spread['columns'][yi]
        # No uncertain legacy encoding is silently decoded into the product.
        xn = bytes.fromhex(xc['name_hex']).decode('ascii')
        yn = bytes.fromhex(yc['name_hex']).decode('ascii')
        sn = bytes.fromhex(spread['name_hex']).decode('ascii')
        did = f'recovered_{index+1}'
        project.datasets.append(Dataset(did, f'{sn}: {xn}, {yn}', {'X': xv, 'Y': yv},
                                        source=str(source), source_sha256=entry['sha256_before'], synthetic=False))
        project.figure.series.append(Series(f'curve_{index+1}', did, 'X', 'Y', label=f'{sn}: {xn} -> {yn}'))
        mappings.append({'dataset': did, 'spread_index': sheet, 'x_column_index': xi, 'y_column_index': yi,
                         'source_x_column': xn, 'source_y_column': yn, 'source_sheet': sn, 'rows': len(xv),
                         'rows_discarded_from_selected_vectors': 0, 'numeric_text_converted': False,
                         'column_metadata_preserved_in_probe': True,
                         'has_stored_formula_x': bool(xc['command_hex']), 'has_stored_formula_y': bool(yc['command_hex'])})
    if not 1 <= len(pairs) <= 2:
        raise ValueError('Fixture currently supports one or two explicit pairs')
    project.figure.title = 'OPJ data-only reconstruction'
    project.figure.xlabel = 'Source X (units unverified)'
    project.figure.ylabel = 'Source Y (units unverified)'
    project.figure.annotations.append(Annotation('scope', 'Data only; original layout not migrated', .03, .95, 8))
    project.audit.append({'actor': 'local acceptance script', 'event': 'explicit data-only reconstruction',
                          'source_sha256': entry['sha256_before'], 'mapping': mappings,
                          'not_migrated': ['Origin figure layout', 'Original labels and units', 'fonts', 'analysis semantics']})
    project.validate()
    output.mkdir(parents=True, exist_ok=False)
    save(project, output/'recovered-data.sps.json')
    assert load(output/'recovered-data.sps.json').to_dict() == project.to_dict()
    before = copy.deepcopy(project.datasets)
    session = Session(project)
    template = templates.builtin_templates()[1 if len(pairs) == 2 else 0]
    bindings = [{'slot': slot.id, 'dataset': d.id, 'x': 'X', 'y': 'Y', 'y_error': '',
                 'legend': project.figure.series[i].label} for i,(slot,d) in enumerate(zip(template.slots, project.datasets))]
    labels = {'title': 'SPS style on extracted OPJ data', 'x_label': project.figure.xlabel, 'y_label': project.figure.ylabel}
    review = session.preview([{'op':'apply_template','template':template.to_dict(),'bindings':bindings,'labels':labels}])
    (output/'template-review.json').write_text(json.dumps(review,ensure_ascii=False,indent=2)+'\n')
    assert session.project.datasets == before
    session.apply_review(review, actor='local acceptance script')
    assert session.project.datasets == before
    session.undo(); assert session.project.datasets == before
    session.redo(); assert session.project.datasets == before
    save(session.project, output/'restyled-data.sps.json')
    exported = export_bundle(session.project, output/'exports', stem='recovered-data', dpi=150)
    assert sha256(source) == entry['sha256_before']
    result = {'scope': 'two explicit complete numeric pairs from experimental liborigin output; not full Origin project migration',
              'source':str(source),'source_sha256':entry['sha256_before'],'source_unchanged':True,
              'mappings':mappings,'datasets_equal_to_selected_probe_vectors':True,'original_origin_numeric_reference_verified':False,
              'native_save_reopen':True,'template_review_apply_undo_redo':True,'export_files_passed':len(exported['files']),
              'all_probe_and_other_columns_retained_in':str(probe_path),'original_plot_fidelity':'not evaluated'}
    (output/'fixture-checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus', type=Path, required=True)
    parser.add_argument('--source-name', required=True)
    parser.add_argument('--pair', required=True, action='append', help='zero-based spread:x_column:y_column')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(reconstruct(args.corpus,args.source_name,[tuple(map(int,p.split(':'))) for p in args.pair],args.output),ensure_ascii=False,indent=2))
