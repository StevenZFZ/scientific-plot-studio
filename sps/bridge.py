"""Optional Windows adapter boundary. Does not parse or fake Origin files."""
import importlib.util
import platform
import os
from pathlib import Path


def capabilities():
    windows = platform.system() == "Windows"
    python_adapter = bool(importlib.util.find_spec("originpro")) if windows else False
    return {
        "platform": platform.system(), "windows": windows, "originpro_installed": python_adapter,
        "origin_runtime_verified": False,
        "opj_import": False, "opju_import": False, "opju_export": False,
        "legacy_opj_style_analysis": "optional external reader; configure in Origin workspace or SPS_ORIGIN_PROBE",
        "origin_style_to_sps": "partial per-layer styles; explicit review; no full layout recovery",
        "origin_partial_template": "selected pure-line layer only; explicit data binding; conversion limits retained",
        "office_origin_recovery": "PPTX embedded OLE Contents extraction; partial OPJU data via Origin data workspace and origin-read",
        "origin_data_gui": "Automatic OPJ/OPJU graph pages, explicit stored X/Y references, partial styles and raw recovery; optional readers required",
        "local_graph_import": "origin-import / GUI: partial original pages and layers, source names and record order; no full fidelity or Origin writeback",
        "headless_origin_data": "origin-read: full-precision OPJ external probe; partial OPJU SHA-pinned external primitives; no GUI/Viewer required",
        "legacy_opj_data_recovery": "optional external probe + explicitly selected finite columns; data-only redraw",
        "sps_clipboard": "full SPS project MIME + image fallback; direct Origin OLE clipboard not implemented",
        "editable_pptx": "native linear XY line chart + workbook + sealed SPS payload; Mac limited editing verified; full fidelity unverified",
        "status": "unsupported_platform" if not windows else "mapping_not_implemented",
        "message": ("本机可通过独立读取器自动读取 OPJ/OPJU 的部分数据、图页、X/Y 引用与格式，无需启动 Origin。完整格式还原与写回尚未完成。Windows Bridge 是另一项可选能力，需要 Windows、已授权安装的 Origin 和 originpro；当前未验证连接。"
                    if not windows else "Windows 适配器接口已预留，但尚未完成对象映射与真实 Origin 运行验证。"),
        "fallback": "可在“打开”中选择 OPJ/OPJU 自动导入，查看“导入详情”确认恢复范围；未支持的数据仍可通过 CSV/TSV 迁移。",
    }


def import_origin(path):
    raise NotImplementedError(capabilities()["message"] + " " + capabilities()["fallback"])


def export_origin(project, path):
    raise NotImplementedError(capabilities()["message"])
