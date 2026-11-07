"""Desktop launcher and scriptable, reviewable offline API."""
import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys

from .model import demo, load, save, read_json, write_json
from .commands import Session, style_from_project


def main(argv=None):
    parser = argparse.ArgumentParser(prog="sps", description="Scientific Plot Studio · offline editable plotting")
    sub = parser.add_subparsers(dest="command")
    gui = sub.add_parser("gui", help="Open the PySide6 desktop")
    gui.add_argument("project", nargs="?")
    importer=sub.add_parser('origin-import',help='Import stored graph pages, explicit references and supported styles')
    importer.add_argument('source');importer.add_argument('output')
    importer.add_argument('--probe',default=os.environ.get('SPS_ORIGIN_PROBE',''))
    importer.add_argument('--decoder',default=os.environ.get('SPS_OPJU_DECODER',''))
    batch=sub.add_parser('publication-batch',help='Import Origin files and normalize axes/typography into new native projects')
    batch.add_argument('output');batch.add_argument('sources',nargs='+')
    batch.add_argument('--profile',choices=['nature','communications_materials','nano_letters','elsevier'],default='nature')
    batch.add_argument('--size',choices=['single','double'],default='single');batch.add_argument('--font',required=True)
    batch.add_argument('--probe',default=os.environ.get('SPS_ORIGIN_PROBE',''));batch.add_argument('--decoder',default=os.environ.get('SPS_OPJU_DECODER',''))
    for command in ('figure-export','figure-office','figure-recover','office-refresh'):
        figcmd=sub.add_parser(command,help='Portable SPS figure / linked Office picture; not OLE')
        figcmd.add_argument('source');figcmd.add_argument('output')
        if command in ('figure-export','figure-office'):
            figcmd.add_argument('--page',type=int,default=0);figcmd.add_argument('--layer',type=int,default=0)
    generate = sub.add_parser("demo", help="Save synthetic demo project")
    generate.add_argument("output")
    export = sub.add_parser("export", help="Export and validate a native project")
    export.add_argument("project")
    export.add_argument("directory")
    export.add_argument("--name", default="figure")
    export.add_argument("--dpi", type=int, default=300)
    export.add_argument("--formats", nargs="+", default=["png", "svg", "pdf", "tiff"])
    export.add_argument("--opaque", action="store_true")
    export.add_argument("--overwrite", action="store_true")
    style = sub.add_parser("style", help="Extract style rules from native project")
    style.add_argument("project")
    style.add_argument("output")
    review = sub.add_parser("review", help="Dry-run allowlisted operations; write review artifact")
    review.add_argument("project")
    review.add_argument("operations")
    review.add_argument("output")
    apply = sub.add_parser("apply", help="Apply an inspected review to an explicitly named output")
    apply.add_argument("project")
    apply.add_argument("review")
    apply.add_argument("output")
    template_extract = sub.add_parser("template-extract", help="Save data-independent native single-axes template")
    template_extract.add_argument("project")
    template_extract.add_argument("output")
    template_extract.add_argument("--name")
    template_extract.add_argument("--keep-ranges", action="store_true")
    template_review = sub.add_parser("template-review", help="Review native template with explicit data bindings")
    template_review.add_argument("project")
    template_review.add_argument("template")
    template_review.add_argument("bindings", help="JSON object with bindings array and labels object")
    template_review.add_argument("output")
    for command, help_text in (("origin-analyze", "Inspect legacy OPJ styles using an optional external reader"),
                               ("origin-profile", "Summarize a directory of Origin style observations")):
        origin = sub.add_parser(command, help=help_text)
        origin.add_argument("source")
        origin.add_argument("output")
        origin.add_argument("--probe", default=os.environ.get("SPS_ORIGIN_PROBE", ""))
    for command in ("origin-style", "origin-template"):
        origin = sub.add_parser(command, help="Extract selected layer partial asset; see mapping limits")
        origin.add_argument("analysis")
        origin.add_argument("layer")
        origin.add_argument("output")
    prepare = sub.add_parser("ai-prepare", help="Create inspectable style-only request; never sends network traffic")
    prepare.add_argument("project")
    prepare.add_argument("prompt")
    prepare.add_argument("config")
    prepare.add_argument("output")
    prepare.add_argument("--style")
    prepare.add_argument("--analysis", help="Anonymous style statistics from a sealed Origin analysis/profile")
    planner = sub.add_parser("ai-plan", help="Plan with offline rules or explicitly send a prepared compatible API request")
    planner.add_argument("project")
    planner.add_argument("output")
    planner.add_argument("--offline", choices=("uniform", "reference"))
    planner.add_argument("--style")
    planner.add_argument("--request")
    planner.add_argument("--config")
    planner.add_argument("--send", action="store_true")
    planner.add_argument("--review-output")
    validate = sub.add_parser("ai-validate", help="Validate an externally generated proposal into a review; no network")
    validate.add_argument("project")
    validate.add_argument("proposal")
    validate.add_argument("output")
    validate.add_argument("--review-output")
    sub.add_parser("bridge", help="Print real Origin capability boundary")
    for command in ('office-scan','office-extract','pptx-export','pptx-recover'):
        cmd=sub.add_parser(command,help='Office transfer with explicit data and capability boundaries')
        cmd.add_argument('source'); cmd.add_argument('output')
    recover_data=sub.add_parser('origin-data',help='Recover explicitly mapped finite OPJ columns; data-only redraw')
    recover_data.add_argument('source'); recover_data.add_argument('output',help='New directory for full probe and native redraw')
    recover_data.add_argument('--probe',required=True)
    recover_data.add_argument('--pair',action='append',required=True,help='Zero-based sheet:x:y, repeatable')
    recover_data.add_argument('--xlabel',default='X'); recover_data.add_argument('--ylabel',default='Y')
    reader = sub.add_parser('origin-read', help='Headless OPJ/OPJU partial data export; no Viewer or GUI')
    reader.add_argument('source')
    reader.add_argument('output', help='New directory for CSV files and full project.json')
    reader.add_argument('--probe', default=os.environ.get('SPS_ORIGIN_PROBE'))
    reader.add_argument('--decoder', default=os.environ.get('SPS_OPJU_DECODER'))
    args = parser.parse_args(argv)
    try:
        if args.command in (None, "gui"):
            from .gui import run
            return run(getattr(args, "project", None))
        if args.command == 'origin-read':
            from .origin_reader import OriginProject
            project = OriginProject(args.source, legacy_probe=args.probe, opju_decoder=args.decoder)
            destination = project.export_csv(args.output)
            print(json.dumps({'output': str(destination), 'status': project.status,
                              'sheets': len(project.spreadsheets),
                              'columns': sum(len(s.columns) for s in project.spreadsheets),
                              'warnings': project.warnings}, ensure_ascii=False))
        elif args.command == "demo":
            save(demo(), args.output)
            print(str(Path(args.output).resolve()))
        elif args.command in ('figure-export','figure-office','figure-recover','office-refresh'):
            from . import figure_object as figure,office_figures
            if Path(args.output).exists():raise ValueError('输出已存在，请另存')
            if args.command=='office-refresh':result=office_figures.refresh(args.source,args.output)
            elif args.command in ('figure-export','figure-office'):
                p=load(args.source);p.select_context(args.page,args.layer)
                result=figure.save(p,args.output)['manifest']if args.command=='figure-export'else office_figures.export(p,args.output)
            else:
                source=Path(args.source)
                if source.suffix.lower()=='.spsfig':info=figure.load(source)
                elif source.suffix.lower()=='.png':info=figure.from_png(source.read_bytes())
                elif source.suffix.lower()=='.svg':info=figure.from_svg(source.read_bytes())
                else:
                    found=office_figures.recover(source)
                    if len(found)!=1:raise ValueError('文档含多个SPS图形，请在GUI选择对象')
                    info=found[0]['info']
                save(info['project'],args.output);result={'restored':args.output}
            print(json.dumps(result,ensure_ascii=False,indent=2))
        elif args.command == "export":
            from .render import export_bundle
            result = export_bundle(load(args.project), args.directory, args.name, args.formats,
                                   args.dpi, not args.opaque, args.overwrite)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "style":
            write_json(args.output, style_from_project(load(args.project)))
        elif args.command == "review":
            from .commands import run_operations
            from .render import preflight
            p, ops = load(args.project), read_json(args.operations)
            preflight(run_operations(p, ops), 100)
            plan = Session(p).preview(ops)
            write_json(args.output, plan)
            print(json.dumps(plan, ensure_ascii=False, indent=2))
        elif args.command == "apply":
            from .render import preflight
            session = Session(load(args.project))
            session.apply_review(read_json(args.review))
            preflight(session.project, 100)
            save(session.project, args.output)
            print(str(Path(args.output).resolve()))
        elif args.command=='publication-batch':
            from .publication import batch_import
            result=batch_import(args.sources,args.output,{'profile':args.profile,'size':args.size,'font':args.font,'scope':'all'},args.probe or None,args.decoder or None)
            print(json.dumps(result,ensure_ascii=False,indent=2))
            if any(row['status']=='failed'for row in result['files']):return 2
        elif args.command=='origin-import':
            from .origin_graphs import read_project
            if Path(args.output).exists():raise ValueError('输出已存在，请换名')
            result=read_project(args.source,args.probe or None,args.decoder or None)
            if result['project']is None:raise ValueError(result['error'])
            save(result['project'],args.output)
            print(json.dumps(result['project'].audit[-1],ensure_ascii=False))
        elif args.command in ("origin-analyze", "origin-profile"):
            from . import origin
            if not args.probe:
                raise ValueError("请用 --probe 或 SPS_ORIGIN_PROBE 明确选择独立读取器")
            if args.command == "origin-analyze":
                result = origin.inspect(args.source, args.probe)
            else:
                paths = [p for p in Path(args.source).rglob("*") if p.is_file() and not p.is_symlink()
                         and p.suffix.lower() in (".opj", ".opju", ".otp", ".otpu", ".oth")]
                if not 1 <= len(paths) <= 100:
                    raise ValueError("文件夹需包含 1–100 份 Origin 工程/模板")
                result = origin.profile(paths, args.probe)
            destination = Path(args.output)
            summary = destination.with_suffix(".md")
            if destination.exists() or summary.exists():
                raise ValueError("报告或总结已存在，请换名保存")
            write_json(destination, result)
            summary.write_text(origin.markdown(result), encoding="utf-8")
            print(json.dumps(result["counts"], ensure_ascii=False))
        elif args.command in ("origin-style", "origin-template"):
            from . import origin, templates
            if Path(args.output).exists():
                raise ValueError("资产文件已存在，请换名保存")
            analysis = read_json(args.analysis)
            if args.command == "origin-style":
                write_json(args.output, origin.layer_style(analysis, args.layer))
            else:
                templates.save(origin.layer_template(analysis, args.layer), args.output)
            print(str(Path(args.output).resolve()))
        elif args.command == "ai-prepare":
            from . import ai
            if Path(args.output).exists():
                raise ValueError("请求文件已存在，请换名保存")
            config = ai.config_from_dict(read_json(args.config))
            from .origin import style_observations
            observations = style_observations(read_json(args.analysis)) if args.analysis else None
            result = ai.prepare(load(args.project), args.prompt, config, read_json(args.style) if args.style else None, observations)
            write_json(args.output, result)
            print("待发送请求已保存；尚未联网。")
        elif args.command in ("ai-plan", "ai-validate"):
            from . import ai
            if Path(args.output).exists() or (args.review_output and Path(args.review_output).exists()):
                raise ValueError("计划或审查文件已存在，请换名保存")
            project = load(args.project)
            if args.command == "ai-validate":
                result = ai.validate_proposal(project, read_json(args.proposal))
            elif args.offline:
                if args.send or args.request or args.config:
                    raise ValueError("离线规则与联网请求不能混用")
                result = ai.offline_plan(project, args.offline, read_json(args.style) if args.style else None)
            else:
                if not args.send or not args.request or not args.config:
                    raise ValueError("联网需明确 --send、--request 和 --config；离线可用 --offline uniform")
                config = ai.config_from_dict(read_json(args.config))
                result = ai.request_plan(project, read_json(args.request), config)
            write_json(args.output, result)
            if args.review_output and result["review"]:
                write_json(args.review_output, result["review"])
            print(result["summary"])
        elif args.command in ('office-scan','office-extract','pptx-export','pptx-recover','origin-data'):
            if Path(args.output).exists(): raise ValueError('输出已存在，请换名')
            if args.command=='office-scan':
                from .office import scan
                result=scan(args.source);write_json(args.output,result);print(json.dumps(result['counts']))
            elif args.command=='office-extract':
                from .office import extract
                print(json.dumps(extract(args.source,args.output)['counts']))
            elif args.command=='pptx-export':
                from .pptx_io import export
                print(json.dumps(export(load(args.source),args.output),ensure_ascii=False))
            elif args.command=='pptx-recover':
                from .pptx_io import recover
                save(recover(args.source),args.output);print(str(Path(args.output).resolve()))
            else:
                from . import origin_data
                import tempfile
                recovery=origin_data.read(args.source,args.probe)
                pairs=[list(map(int,pair.split(':'))) for pair in args.pair]
                project=origin_data.reconstruct(recovery,pairs,args.xlabel,args.ylabel)
                destination=Path(args.output).resolve()
                with tempfile.TemporaryDirectory(prefix='.sps-data-',dir=destination.parent) as temporary:
                    stage=Path(temporary)/'result';stage.mkdir()
                    write_json(stage/'recovery.json',recovery);save(project,stage/'data-only.sps.json')
                    stage.rename(destination)
                print(str(destination))
        elif args.command == "bridge":
            from .bridge import capabilities
            print(json.dumps(capabilities(), ensure_ascii=False, indent=2))
        elif args.command == "template-extract":
            from .templates import extract, save as save_template
            save_template(extract(load(args.project), args.name, args.keep_ranges), args.output)
            print(str(Path(args.output).resolve()))
        elif args.command == "template-review":
            from .templates import load as load_template
            from .commands import run_operations
            from .render import preflight
            bindings = read_json(args.bindings)
            if not isinstance(bindings, dict) or set(bindings) != {"bindings", "labels"}:
                raise ValueError("绑定文件必须且仅包含 bindings 与 labels")
            p = load(args.project)
            op = {"op": "apply_template", "template": load_template(args.template).to_dict(), **bindings}
            preflight(run_operations(p, [op]), 100)
            plan = Session(p).preview([op])
            write_json(args.output, plan)
            print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        print(f"SPS: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
