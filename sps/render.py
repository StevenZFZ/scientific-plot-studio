"""One rendering path for desktop and all exports, with fail-closed preflight."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import platform
import tempfile
import warnings
import xml.etree.ElementTree as ET

import matplotlib as mpl
from matplotlib import font_manager
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ft2font import FT2Font
from matplotlib.text import Text
from PIL import Image
from pypdf import PdfReader

from .model import write_json

FORMATS = ("png", "svg", "pdf", "tiff")


def normalize_svg_empty_paths(path):
    """Qt rejects empty glyph paths (e.g. spaces). A move-only path has no ink.

    Glyph positions live in the surrounding use transforms; neither their advance
    nor scientific geometry is changed. Report the number of normalized paths.
    """
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    tree = ET.parse(path, parser=parser)
    count = 0
    for element in tree.getroot().iter("{http://www.w3.org/2000/svg}path"):
        if not element.get("d", "").strip():
            element.set("d", "M 0 0")
            count += 1
    if count:
        ET.register_namespace("", "http://www.w3.org/2000/svg")
        ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")
        tree.write(path, encoding="utf-8", xml_declaration=True)
    return count


def font_info(project):
    font = project.figure.font
    try:
        path = font_manager.findfont(font_manager.FontProperties(family=font), fallback_to_default=False)
    except ValueError as e:
        raise ValueError(f"字体 {font!r} 未安装；请明确选择可用字体，禁止静默替换") from e
    charmap = FT2Font(path).get_charmap()
    texts = [project.figure.title, project.figure.xlabel, project.figure.ylabel]
    texts += project.figure.xtick_labels or []
    if project.figure.xtick_dataset:
        dataset=next(d for d in project.datasets if d.id==project.figure.xtick_dataset)
        texts += [str(v)for v in dataset.columns[project.figure.xtick_column]if v is not None]
    texts += [s.label for s in project.figure.series if s.visible]
    texts += [a.text for a in project.figure.annotations]
    if project.figure.label_wrap:
        from .publication import display_text
        texts=[display_text(t)for t in texts]
    missing = sorted({c for t in texts for c in t if not c.isspace() and ord(c) not in charmap})
    if missing:
        hint = ""
        if any("\u4e00" <= c <= "\u9fff" or "\u3000" <= c <= "\u303f" or "\uff00" <= c <= "\uffef" for c in missing):
            hint = "；含中文时请改用思源黑体 / 苹方等中文字体（导出不做静默替换）"
        raise ValueError(f"字体 {font} 缺少字符 {''.join(missing)!r}；请选择覆盖这些字符的字体{hint}")
    return {"family": font, "path": str(Path(path).resolve()),
            "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def draw(project, figure=None, dpi=120, *, _rect=None, _clear=True, _view_scale=1):
    project.validate()
    if project.pages:
        return _draw_page(project,figure,dpi)
    info = font_info(project)
    f = project.figure
    settings = {"font.family": f.font, "font.size": f.font_size*_view_scale, "axes.linewidth": f.axis_width*_view_scale,
                "svg.fonttype": "path", "pdf.fonttype": 42, "ps.fonttype": 42,
                "text.usetex": False, "svg.hashsalt": "sps-v1"}
    if f.label_wrap:
        settings.update({'mathtext.fontset':'custom','mathtext.rm':f.font,'mathtext.it':f.font+':italic',
                         'mathtext.bf':f.font+':bold','mathtext.bfit':f.font+':bold:italic',
                         'mathtext.cal':f.font,'mathtext.sf':f.font,'mathtext.tt':f.font,'mathtext.fallback':None})
    with mpl.rc_context(settings):
        if figure is None:
            figure = Figure(figsize=(f.width_mm / 25.4, f.height_mm / 25.4), dpi=dpi, layout="constrained" if _rect is None else None)
            FigureCanvasAgg(figure)
        elif _clear:
            figure.clear()
            # The Qt widget owns its pixel buffer dimensions. Resetting physical size
            # here desynchronizes Agg's buffer from the widget (garbled paint on Cocoa).
            # Export creates a separate Figure with exact physical dimensions above.
            figure.set_layout_engine("constrained")
        ax = figure.add_axes(_rect) if _rect is not None else figure.add_subplot(111)
        ax.set_xscale(f.xscale,**({"nonpositive":"mask"}if f.xscale=="log"else{}))
        ax.set_yscale(f.yscale,**({"nonpositive":"mask"}if f.yscale=="log"else{}))
        from .publication import display_text
        shown=display_text if f.label_wrap else lambda value:value
        datasets = {d.id: d for d in project.datasets}
        artists = {}
        for s in f.series:
            if not s.visible:
                continue
            dataset=datasets[s.dataset];d=dataset.columns
            start,stop=s.row_range or (0,len(d[s.x]));selected=slice(start,stop)
            x=[i+start+1 if v is not None else float('nan') for i,v in enumerate(d[s.x][selected])] if s.x in dataset.text_columns else [float('nan')if v is None else v for v in d[s.x][selected]]
            y=[float('nan')if v is None else v for v in d[s.y][selected]]
            error=[float('nan')if v is None else v for v in d[s.y_error][selected]]if s.y_error else None
            shared = {"color": s.color, "alpha": s.alpha, "label": shown(s.label)}
            marker = "" if s.marker == "none" else s.marker
            if s.kind == "scatter":
                artist = ax.scatter(x, y, s=(s.marker_size*_view_scale) ** 2, marker=marker or "o", picker=5, **shared)
                if error is not None:ax.errorbar(x,y,yerr=error,fmt='none',color=s.color,alpha=s.alpha,capsize=2*_view_scale,linewidth=s.width*_view_scale)
            elif s.kind == "bar":
                valid=[i for i,(vx,vy)in enumerate(zip(x,y))if math.isfinite(vx)and math.isfinite(vy)]
                bars = ax.bar([x[i]for i in valid],[y[i]for i in valid],yerr=[error[i]for i in valid]if error else None,capsize=2*_view_scale if error else 0, **shared)
                artist = bars.patches[0] if bars.patches else None
                for patch in bars.patches:
                    patch.set_picker(True)
                    patch.set_gid(s.id)
            elif s.kind == "errorbar" or error is not None:
                artist = ax.errorbar(x, y, yerr=error, linewidth=s.width*_view_scale, marker=marker,
                                    markersize=s.marker_size*_view_scale, linestyle=s.line_style, capsize=2,
                                    picker=5, **shared).lines[0]
            else:
                artist, = ax.plot(x, y, linewidth=s.width*_view_scale, marker=marker, markersize=s.marker_size*_view_scale,
                                  linestyle=s.line_style, picker=5, **shared)
            if artist is not None:
                artist.set_gid(s.id)
                artists[s.id] = artist
        xlabel,ylabel=shown(f.xlabel),shown(f.ylabel)
        if f.label_wrap:
            from .publication import wrap_label
            renderer=figure.canvas.get_renderer()
            xlabel=wrap_label(xlabel,ax.bbox.width*.94,renderer,f.font,(f.xlabel_size or f.font_size)*_view_scale)
            ylabel=wrap_label(ylabel,ax.bbox.height*.94,renderer,f.font,(f.ylabel_size or f.font_size)*_view_scale)
        ax.set(title=shown(f.title), xlabel=xlabel, ylabel=ylabel)
        if f.xlim is not None:
            ax.set_xlim(f.xlim)
        if f.ylim is not None:
            ax.set_ylim(f.ylim)
        if f.grid:
            ax.grid(True, color="#dce2e6", linewidth=.5)
        else:
            ax.grid(False)
        from .plot_options import configure_ticks
        configure_ticks(ax, f)
        if f.xtick_dataset:
            labels=datasets[f.xtick_dataset].columns[f.xtick_column]
            pairs=[(i+1,shown(str(v)))for i,v in enumerate(labels)if v is not None]
            ax.set_xticks([i for i,_ in pairs],labels=[v for _,v in pairs])
        elif f.xtick_values is not None:ax.set_xticks(f.xtick_values,labels=[shown(v)for v in f.xtick_labels])
        ax.tick_params(which="both", direction=f.tick_direction, top=f.box, right=f.box, width=f.axis_width*_view_scale, labelsize=(f.tick_size or f.font_size)*_view_scale)
        ax.xaxis.label.set_fontsize((f.xlabel_size or f.font_size)*_view_scale)
        ax.yaxis.label.set_fontsize((f.ylabel_size or f.font_size)*_view_scale)
        for side in ("top", "right"):
            ax.spines[side].set_visible(f.box)
        if f.axis_sides is not None:
            for side,settings in f.axis_sides.items():
                ax.spines[side].set_visible(settings['spine'])
                axis='x'if side in('bottom','top')else'y'
                ax.tick_params(axis=axis,which='both',**{side:settings['ticks'],'label'+side:settings['labels']})
            if f.axis_sides['top']['labels'] and not f.axis_sides['bottom']['labels']:ax.xaxis.set_label_position('top')
            if f.axis_sides['right']['labels'] and not f.axis_sides['left']['labels']:ax.yaxis.set_label_position('right')
        if f.legend and any(s.visible for s in f.series):
            ax.legend(frameon=f.legend_frame, loc=f.legend_location, fontsize=(f.legend_size or f.font_size * .9)*_view_scale)
        for a in f.annotations:
            artist = ax.text(a.x, a.y, shown(a.text), transform=ax.transAxes, fontsize=a.size*_view_scale, color=a.color,
                             ha="left", va="top", picker=True)
            artist.set_gid(a.id)
            artist.set_in_layout(False)
            artists[a.id] = artist
        # Set concrete properties so GUI redraws outside rc_context remain stable.
        for artist in ax.findobj(Text):
            artist.set_fontfamily(f.font)
        figure.canvas.draw()
    return figure, ax, artists, info


def _draw_page(project,figure,dpi):
    from .model import Project
    page=project.pages[project.context[0]];f=project.figure
    if figure is None:
        figure=Figure(figsize=(f.width_mm/25.4,f.height_mm/25.4),dpi=dpi)
        FigureCanvasAgg(figure)
    else:figure.clear()
    from .publication import active_layers
    active=active_layers(page.layers)
    automatic=len(active)==1 and page.layers[active[0]].figure.layout_mode=='auto'
    figure.set_layout_engine('constrained'if automatic else 'none')
    scale=figure.get_figwidth()/(f.width_mm/25.4)
    axes=[];artists={};fonts=[]
    for layer in page.layers:
        child=Project(name=page.name,datasets=project.datasets,figure=layer.figure)
        _,ax,found,font=draw(child,figure,dpi,_rect=None if automatic and layer is page.layers[active[0]] else layer.rect or [.14,.16,.80,.76],_clear=False,_view_scale=scale)
        if not layer.axes_visible:ax.set_axis_off()
        axes.append(ax);artists.update(found);fonts.append(font)
    figure.canvas.draw()
    info=dict(fonts[project.context[1]]);info['layers']=fonts
    return figure,axes[project.context[1]],artists,info


def preflight(project, dpi=300):
    if type(dpi) is not int or not 72 <= dpi <= 1200:
        raise ValueError("DPI 必须是 72–1200 的整数")
    w = project.figure.width_mm / 25.4 * dpi
    h = project.figure.height_mm / 25.4 * dpi
    if w * h > 80_000_000:
        raise ValueError("导出超过 8000 万像素，请减小尺寸或 DPI")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", UserWarning)
        fig, ax, artists, font = draw(project, dpi=dpi)
    messages = sorted({str(w.message) for w in caught})
    if messages:
        raise ValueError("绘图预检失败：" + "; ".join(messages))
    renderer = fig.canvas.get_renderer()
    outside = []
    # Matplotlib keeps tick-label artists outside the visible axis interval.
    # Only labels actually drawn inside the limits participate in clipping checks.
    texts = list(fig.texts)
    for axis_plot in fig.axes:
        if not axis_plot.axison:
            texts+=list(axis_plot.texts);continue
        texts += list(axis_plot.texts)+[axis_plot.title,axis_plot.xaxis.label,axis_plot.yaxis.label,
                                     axis_plot.xaxis.offsetText,axis_plot.yaxis.offsetText]
        for axis,limits in ((axis_plot.xaxis,axis_plot.get_xlim()),(axis_plot.yaxis,axis_plot.get_ylim())):
            for tick in axis.get_major_ticks()+axis.get_minor_ticks():
                if min(limits)<=tick.get_loc()<=max(limits):texts.extend([tick.label1,tick.label2])
        if axis_plot.get_legend() is not None:texts.extend(axis_plot.get_legend().get_texts())
    for t in texts:
        if not t.get_visible() or not t.get_text().strip():
            continue
        box = t.get_window_extent(renderer)
        if box.x0 < -.5 or box.y0 < -.5 or box.x1 > fig.bbox.width + .5 or box.y1 > fig.bbox.height + .5:
            outside.append(t.get_text())
    if outside:
        raise ValueError("文字超出画布，导出已停止。请加大画布、减小字号或移动注释：" + ", ".join(outside))
    if project.figure.layout_mode=='auto':
        from .publication import readability
        collisions=readability(fig)
        if collisions:raise ValueError('刻度文字拥挤，导出已停止；请选择双栏、减少刻度或手动排版：'+'；'.join(collisions))
    # Freeze positions once. Vector backends must not rerun layout with different metrics.
    fig.set_layout_engine("none")
    return fig, {"passed": True, "text_bounds": "inside_canvas", "font": font,
                 "width_mm": project.figure.width_mm, "height_mm": project.figure.height_mm,
                 "dpi": dpi, "crop": "fixed_canvas_no_tight_crop", "warnings": []}


def _embedded_fonts(page):
    fonts = page.get("/Resources", {}).get("/Font", {})
    result = []
    for ref in fonts.values():
        font = ref.get_object()
        children = font.get("/DescendantFonts", [font])
        for child in children:
            child = child.get_object()
            descriptor = child.get("/FontDescriptor")
            descriptor = descriptor.get_object() if descriptor else {}
            result.append({"name": str(child.get("/BaseFont", "")),
                           "embedded": any(k in descriptor for k in ("/FontFile", "/FontFile2", "/FontFile3"))})
    return result


def inspect_export(path, spec, dpi, transparent):
    path = Path(path)
    fmt = path.suffix.lower()[1:]
    result = {"format": fmt, "bytes": path.stat().st_size,
              "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    if fmt in ("png", "tiff"):
        with Image.open(path) as im:
            expected = [int(spec.width_mm / 25.4 * dpi), int(spec.height_mm / 25.4 * dpi)]
            if any(abs(a - b) > 1 for a, b in zip(im.size, expected)):
                raise ValueError("栅格物理尺寸校验失败")
            alpha = im.convert("RGBA").getchannel("A")
            low, high = alpha.getextrema()
            if transparent and (low != 0 or high == 0):
                raise ValueError("透明通道校验失败或图像为空")
            if not transparent and low != 255:
                raise ValueError("不透明背景校验失败")
            result.update(pixels=list(im.size), mode=im.mode, alpha_extrema=[low, high],
                          dpi=[float(v) for v in im.info.get("dpi", ())], content_bbox=list(alpha.getbbox() or ()))
    elif fmt == "svg":
        root = ET.parse(path).getroot()
        viewbox = [float(v) for v in root.attrib["viewBox"].split()]
        expected = [spec.width_mm / 25.4 * 72, spec.height_mm / 25.4 * 72]
        if any(abs(a - b) > .02 for a, b in zip(viewbox[2:], expected)):
            raise ValueError("SVG 尺寸校验失败")
        text_count = len(root.findall(".//{http://www.w3.org/2000/svg}text"))
        if text_count:
            raise ValueError("SVG 字体轮廓化校验失败")
        result.update(viewbox=viewbox, font_policy="outlined_paths", text_elements=text_count,
                      transparency="requested; structural check only")
    elif fmt == "pdf":
        reader = PdfReader(path)
        if len(reader.pages) != 1:
            raise ValueError("PDF 页数校验失败")
        page = reader.pages[0]
        size = [float(page.mediabox.width), float(page.mediabox.height)]
        expected = [spec.width_mm / 25.4 * 72, spec.height_mm / 25.4 * 72]
        if any(abs(a - b) > .02 for a, b in zip(size, expected)):
            raise ValueError("PDF 尺寸校验失败")
        fonts = _embedded_fonts(page)
        if any(not f["embedded"] for f in fonts):
            raise ValueError("PDF 字体嵌入校验失败")
        result.update(points=size, fonts=fonts, transparency="requested; structural check only")
    result["passed"] = True
    return result


def export_bundle(project, directory, stem="figure", formats=FORMATS, dpi=300, transparent=True, overwrite=False):
    """Preflight + stage + inspect before publishing files. JSON manifest accompanies output."""
    if not isinstance(stem, str) or not stem or stem in (".", "..") or any(c in stem for c in '/\\\x00'):
        raise ValueError("导出名称必须是文件名，不能含路径")
    formats = list(formats)
    if not formats or len(set(formats)) != len(formats) or set(formats) - set(FORMATS):
        raise ValueError("请选择 PNG/SVG/PDF/TIFF（不可重复）")
    if type(transparent) is not bool:
        raise ValueError("transparent 必须是布尔值")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    targets = [directory / f"{stem}.{fmt}" for fmt in formats] + [directory / f"{stem}.export.json"]
    if not overwrite and any(p.exists() for p in targets):
        raise FileExistsError("导出文件已存在；请更换名称或明确允许覆盖")
    fig, checks = preflight(project, dpi=dpi)
    report = {"schema": "sps.export/1", "project_hash": project.fingerprint(), "preflight": checks,
              "transparent": transparent, "environment": {"os": platform.platform(), "python": platform.python_version(),
              "matplotlib": mpl.__version__, "pillow": Image.__version__}, "files": [],
              "limits": ["当前报告不能证明 Windows/Linux 像素一致性。", "SVG/PDF 透明度仅进行结构与生成策略检查，尚未完成外部阅读器栅格化对比。",
                         "SVG 文字已转路径；可编辑文字和原始数据保留在 SPS 工程。", "不自动嵌入第三方字体到 SPS 工程；目标机器仍需相同字体。"]}
    if project.pages:
        pi,_=project.context;page=project.pages[pi]
        report['target']={'page_index':pi,'page_id':page.id,'page_name':page.name,'scope':'all layers of selected graph page'}
    with tempfile.TemporaryDirectory(prefix=".sps-export-", dir=directory) as temp:
        stage = Path(temp)
        with mpl.rc_context({"svg.fonttype": "path", "pdf.fonttype": 42, "svg.hashsalt": "sps-v1", "font.family": project.figure.font}):
            for fmt in formats:
                path = stage / f"{stem}.{fmt}"
                kwargs = {}
                if fmt == "pdf":
                    kwargs["metadata"] = {"Title": project.figure.title, "Creator": "Scientific Plot Studio", "CreationDate": None, "ModDate": None}
                elif fmt == "svg":
                    kwargs["metadata"] = {"Date": None, "Creator": "Scientific Plot Studio"}
                elif fmt == "tiff":
                    kwargs["pil_kwargs"] = {"compression": "tiff_lzw"}
                fig.savefig(path, format=fmt, dpi=dpi, transparent=transparent,
                            facecolor="none" if transparent else "white", edgecolor="none",
                            bbox_inches=None, **kwargs)
                normalized = normalize_svg_empty_paths(path) if fmt == "svg" else 0
                entry = {"name": path.name, **inspect_export(path, project.figure, dpi, transparent)}
                if fmt == "svg":
                    entry["empty_paths_normalized"] = normalized
                report["files"].append(entry)
        write_json(stage / f"{stem}.export.json", report)
        for target in targets:
            os.replace(stage / target.name, target)
    return report
