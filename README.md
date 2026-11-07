# Scientific Plot Studio · SPS

**一个面向科研的可编辑绘图工作台。**

从原始表格到论文图，往往要反复修改坐标、图例和样式。SPS 把数据和绘图设置保存在可编辑工程里，让图件能重新打开、修改和导出。希望它能帮科研同学少做重复排版，把更多时间留给实验和分析。

## 能做什么

- **编辑图件** · 调整曲线、坐标轴和图例，保存为可继续编辑的 SPS 工程。
- **复现导出** · 从同一工程导出 PNG、SVG、PDF 或 TIFF。
- **整理投稿图** · 使用模板统一版式，逐张检查后再导出。

## 五分钟跑通示例

需要 Python 3.11 或以上。以下命令适用于 macOS 和 Linux shell，Windows PowerShell 的激活命令是 `.venv\Scripts\Activate.ps1`。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
python -m sps gui examples/synthetic.sps.json
```

也可以直接用命令行生成示例工程并导出：

```bash
python -m sps demo output/demo.sps.json
python -m sps export output/demo.sps.json output/figures --name demo --formats png svg pdf
```

![合成数据导出示例](examples/synthetic.png)

图中数据由程序生成，仅演示绘图与导出。

## 欢迎测试和改进

欢迎试用，尤其欢迎分享「什么步骤最难用」「哪种图需要反复手调」。遇到问题，可以提交 **Issue**，附上系统、Python 版本、复现步骤和一份合成样例。想改代码或文档，也欢迎提交 **Pull Request**。具体步骤见 [贡献指南](CONTRIBUTING.md)。

## 当前边界

本仓库提供 Python 源码。Windows 与 Linux 的桌面体验待社区验证。Origin 支持限于部分读取和重绘，详见[说明](docs/ORIGIN_HEADLESS.md)。Word 和 PowerPoint 的可编辑工作流有宿主与操作条件，普通图片粘贴依赖宿主行为。

## 许可证

SPS 源码采用 [MIT 许可证](LICENSE)。
