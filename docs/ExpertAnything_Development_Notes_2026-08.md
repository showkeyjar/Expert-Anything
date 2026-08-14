# ExpertAnything 开发纪要（2026-08）

> 记录 2026-08 期间从 MVP 到当前稳定基线的迭代历程、架构决策与工程约定。
> 定位：给后来者（含 AI 协作者）快速建立上下文。

## 1. 迭代时间线

| 阶段 | 内容 |
|---|---|
| 基线 | Flet Web 原型 + 确定性规则引擎（core 层雏形） |
| R1 | PySide6 迁移收尾：入口统一（app.py → main.py）、补 `get_asset()` 崩溃、图谱升级（分层/径向/异常高亮）、requirements、README、git 首提交 |
| R2 | 可视化组件库：原文高亮阅读器（SourceTextView）、概念面板（ConceptDetailPanel）、路径阶梯（PathLadderView）、仪表盘真图谱 |
| R3 | 教学卡片（TeachResultView）、学习历史表格、Flet UI 归档 legacy/ |
| R4 | 理解优先三件套：教学联动图、复习队列（due_for_review）、参考回答对比（reference+gap） |
| R5 | 连续追问（tutor.follow_up + FollowUpWorker）、复习模式（vary=1） |
| R6 | 关联概念导航（邻居 chips）、追问沉淀到 TeacherModel（record_learner_question） |
| R7 | Learning Gain 可视化：指标卡 + 成长趋势图（TrendChartView） |
| R8 | 崩溃修复（视图重建引用顺序）+ 二进制导入（pdf/epub/docx，ExtractWorker bytes 化）+ 文件过滤器 |
| R9 | 三区布局（顶部功能栏 + 统一 header）、全局图谱（grey_ids + 共享概念边）、单击弹面板、卡片去进度条、教师说明卡 |
| R10 | 图谱工具条（搜索/范围/缩放）、教师笔记补边（前置/关联，关系 8→37）、概念笔记列表化 |
| R11 | **力导向活图谱**：物理模拟 + 漂浮 + 拖拽 + 悬停高亮；教学迷你 header |
| R12 | 内容自适应缩放（≥0.85）、节点字号加大、tooltip 带定义、缩放按钮 |
| R13 | 教学布局修复（图谱 sizeHint 挤占 → maxHeight；splitter stretch） |
| R14 | **多语言**：zh/en/ja 全量 t() 接入、语言切换即重建、166 处硬编码中文清零 |
| 测试 | 统一套件 run_tests.py：71 用例（core 30 / data 7 / ui 27 / llm 7），quick ~9s |

## 2. 当前架构（稳定基线）

```text
main.py                    PySide6 入口 + 7 视图 + 顶栏/侧栏
expert_anything/
  core/                    无 UI 依赖
    extraction.py          知识抽取（LLM 多分块并行 + 幻觉防护 + 噪音过滤）
    teacher.py             教师模型（ConceptNote + Anomaly + 学习者信号闭环）
    tutor.py               教学（三风格/评估 reference+gap/追问）
    learner.py             跨资产掌握度 + adaptive_path + due_for_review
    llm.py                 零依赖 OpenAI 兼容客户端
    graph_viz.py           布局算法 + PNG 渲染（力导向初始散布）
    i18n.py                三语键表 + t()/set_lang/save_lang
    parsers.py             txt/md/docx/epub/pdf/html 提取
    models.py/storage.py/config.py
  ui/
    pyside_graph.py        力导向活图谱（漂浮/拖拽/悬停/缩放/灰色节点）
    pyside_widgets.py      组件库（面板/卡片/侧栏/阶梯/趋势图/分布条）
tests/                     unittest 分层套件（util 隔离演示数据副本）
run_tests.py               一键入口（--quick / --llm / --layer）
data/_demo                 演示数据（双资产 + 模拟学习轨迹，可重建）
legacy/                    Web 版 + Flet UI + PySide6 v1 存档
```

## 3. 关键工程决策（ADR 补充）

- **来源约束**：概念/证据逐字出自原文；`_ground_evidence` 校验；幻觉概念丢弃；
  关系稀疏时用学习路径补"路径相邻"边（图谱永远有骨架）。
- **教师笔记补边**：prerequisites → "前置"边、connections 命中概念 → "关联"边，
  显著提升图谱密度（8 → 37 条）。
- **力导向初始布局用圆形散布**：分层布局在关系密集时会生成 4600px 高长条（不可读）；
  圆形散布紧凑可读，物理模拟自然展开成网络。
- **QGraphicsView sizeHint 陷阱**：其 sizeHint 基于场景尺寸（可超 1000px），
  放入 QVBoxLayout 必须 setMaximumHeight，否则挤占主内容区。
- **视图重建生命周期**：`_rebuild_all_views` 先清引用再重建；语言切换 = 重建三件套
  （topbar/sidebar/views）。
- **i18n 模块级求值陷阱**：`TAG_LABELS = {"weak": _t(...)}` 在 import 时冻结语言 →
  必须用渲染时查表函数（`_tag_label()`）。

## 4. 多语言约定

- 所有 UI 文本走 `core/i18n.py` 的 `t(key)`，键表三语齐全（zh-CN/en/ja）。
- 学习材料原文（概念名/证据）不翻译；LLM 生成的异常描述按生成语言保留。
- 语言下拉展示语言自身名称（中文/English/日本語）。
- 新增 UI 文案：加键 → 三语翻译 → 替换调用；可用
  `scan` 脚本 + EN 模式动态扫描验证零残留。
- LLM prompt 语言化（随 UI 语言切换抽取/教学输出语言）列为下一步。

## 5. 已知限制与下一步

1. LLM 输出固定中文（prompt 未随语言切换）——下一步：prompt 模板按语言选择
2. 无 SourceLocation：证据定位只有文本匹配，无页码/章节锚点
3. `main.py` ~2100 行单体，按视图拆分 `ui/views/` 待做
4. 扫描版 PDF 无 OCR；docx 仅正文段落（表格/批注忽略）
5. 数据持久化为 JSON 文件，未上数据库
6. 学习报告导出为纯文本，未做 HTML 可视化版

## 6. 测试与验证

```powershell
python run_tests.py --quick   # 71 用例（无 LLM），~9s —— 每次改进后必跑
python run_tests.py           # 全量（含真实 LLM 端到端）
python run_tests.py --layer ui|core|llm|data
```

测试纪律：测试用 `data/_demo` 的临时副本（tests/util.ensure_demo），
绝不读写真实数据；LLM 用例无 key 自动跳过。
