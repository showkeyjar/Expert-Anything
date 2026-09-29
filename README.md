---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: f72b104002d99af940831fcb029a9bd5_7b47b91fb6bd11f19825525400cd780f
    ReservedCode1: ob1Jb8E0NqVjHDXu1jb7tuon5NJmaSGEw0M/DMsnsFR1o/Pn4jMXDDw1jAPZQj18rdMuDLmU55AKpwZ0T1GlzqLUaDWSWOE05S/ynPdBItpma99PqITw6N/Oeyk+GtOnp158wE+XKUMPVtF/xCGKrZHAYSZpP7ZDRazo8R2yIsV6T/bZwNn4lglt+PQ=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: f72b104002d99af940831fcb029a9bd5_7b47b91fb6bd11f19825525400cd780f
    ReservedCode2: ob1Jb8E0NqVjHDXu1jb7tuon5NJmaSGEw0M/DMsnsFR1o/Pn4jMXDDw1jAPZQj18rdMuDLmU55AKpwZ0T1GlzqLUaDWSWOE05S/ynPdBItpma99PqITw6N/Oeyk+GtOnp158wE+XKUMPVtF/xCGKrZHAYSZpP7ZDRazo8R2yIsV6T/bZwNn4lglt+PQ=
---

# ExpertAnything · 个人学习 OS

> Make anyone expert in anything.

[中文](README.md) · [English](README.en.md) · [日本語](README.ja.md)

把任何知识资产（书、论文、课程、笔记）转化为**可交互、可教学、可进化的知识模型**，通过「学习闭环」帮人真正掌握，而不是做一个 RAG 聊天机器人。

## 运行

```powershell
pip install -r requirements.txt
python app.py        # 或 python main.py
```

PySide6 桌面应用，无需浏览器。首次使用建议在 `.env` 中配置 LLM（见 `.env.example`）：

```
EXPERTANYTHING_LLM_API_KEY=...
EXPERTANYTHING_LLM_BASE_URL=https://api.openai.com/v1   # 任意 OpenAI 兼容端点
EXPERTANYTHING_LLM_MODEL=gpt-4o-mini
```

未配置 LLM 时系统以「确定性降级」运行：抽取概念结构索引、教学与评估退化为启发式，UI 会明确提示深度受限。

## 核心链路

```text
知识资产 (EPUB/PDF/MD/TXT/粘贴文本)
  -> 格式解析 (core/parsers.py)
  -> 知识抽取 (core/extraction.py)   ← LLM 多分块并行，来源约束，幻觉防护
  -> 知识模型 (KnowledgeAsset: concepts + relations + learning_path)
  -> 自我学习 (core/teacher.py)      ← 概念深加工 + 异常检测 (TeacherModel)
  -> 教学闭环 (core/tutor.py + core/learner.py)
      对齐目标 → 教学(例子/图示/拆解) → 答题评估 → 更新掌握度 → 自适应下一步
```

**来源约束是硬规则**：概念的 definition/evidence 必须逐字出自原文，关系只标原文存在的联系；`TeacherModel` 对原文的矛盾、未定义术语、逻辑断点、反常主张保持「存疑」而非假装全知，并把异常纳入教学优先级（walk ahead of the student）。

## 领域模板与领域专用解码（domain pack）

除了"从零抽取"，系统还能为**已有领域**套用预置知识骨架，并给出该领域的策展可视化：

- **领域模板**（`core/domain_templates.py`）：章节结构 + 概念清单 + 推荐学习路径 + 常见误解 + 背景锚点。
  当前内置 `ELECTRICITY_TRADING_TEMPLATE`（中国电力市场交易体系：5 章节 / 19 概念 / 7 步快速路径 / 4 条常见误解）。
  模板**不新增、不删除、不重排**资产概念，只在概念 `definition` / `evidence` 为空时补模板释义
  —— 已抽取的来源约束内容永不被模板文本覆盖。
- **ID 映射机制（最终形态：归一化名称 + 括号别名）**：模板概念 ID（`et-*`）与资产概念 ID（`c*`）
  两个 ID 空间永不做 ID 对齐，只按名称匹配——NFKC 归一化（大小写/全半角/分隔符/标点）叠加
  括号别名，「节点边际电价(LMP)」可用全称、`节点边际电价` 或 `LMP` 任意一种写法命中；
  变体按长度降序（全称优先于别名），每个资产概念最多被认领一次，未命中的模板概念如实进入 `unmatched`。
  **映射为空或覆盖率低于 50% 即降级：学习路径保持原样**
  （`degraded_no_mapping` / `degraded_low_coverage` / `unknown_domain`），
  `TemplateApplicationResult` 会把命中数 / 覆盖率 / 富化概念数 / 降级原因一并交出。
- **领域专用解码器**（`core/decoder_electricity.py`）：4 类策展场景
  （两级市场架构 / 电价形成机制 / 日前市场交易流程 / LMP 节点电价），统一入口
  `decoder.scene_for_concept(asset, concept)` 按概念（模板 ID / 资产 ID / 概念名或括号别名）自动选用，
  无策展场景时回落通用场景图；非电力资产不会被套用电力视觉。

在 UI 里：导入资料 → 抽取完成 → 标题命中领域且覆盖率达标时自动弹出「领域模板」确认框
（显示命中 x/y、覆盖率、是否改写学习路径），确认才套用，拒绝或无领域信号则照常导入。
命令行一键演示：

```bash
python run_demo.py    # 套用模板 + 生成 4 类场景 + 准入校验 + 输出 demo_electricity_market.html
```

## 目录结构

```text
app.py / main.py            PySide6 桌面入口（7 个视图）
expert_anything/
  core/                     核心引擎（无 UI 依赖，可单独测试）
    extraction.py           知识抽取（LLM + 确定性回退）
    teacher.py              自我学习层（ConceptNote + Anomaly + 学习者信号闭环）
    tutor.py                个性化教学（3 种风格 + 语义评估）
    learner.py              跨资产掌握度 + 自适应学习路径
    llm.py                  零依赖 OpenAI 兼容客户端（重试/退避/并发限流）
    decoder.py              知识解码：SceneSpec 准入 + 确定性渲染 + scene_for_concept 统一入口
    decoder_electricity.py  领域专用解码器：电力交易策展场景（架构/电价/流程/LMP）
    domain_templates.py     领域模板：领域检测 + 名称/别名映射 + 套用（映射失败保留原路径）
    auto_harness.py         教学 harness 的生成 / 执行 / 演化（meta-harness）
    graph_viz.py            Pillow 离线概念图渲染 + 布局算法
    checks.py / map_context.py / prompt_registry.py / report_html.py   准入校验、地图上下文、prompt 模板、报告
    i18n.py                 中/英/日三语
    models.py / storage.py / parsers.py / config.py
  ui/
    views/                  7 个视图模块（import / knowledge / concept_map / source / teach / learner / teacher）
    view_manager.py         视图栈编排 + 跨视图信号路由
    pyside_graph.py         PySide6 交互式知识图谱（复用 graph_viz 布局）
    pyside_widgets.py / widgets/   控件库（面板 / 卡片 / 详情侧栏 / 阶梯 / 图表）
data/                       运行时数据（learner.json + assets/，不入库；演示数据 data/_demo 亦不入库）
docs/                       设计理念 / ADR / 来源约束架构（含 电力交易领域学习方案.md）
legacy/                     Web 版、Flet UI 与 PySide6 v1 存档
run_demo.py / demo_electricity_market.html   电力交易领域命令行演示及其 HTML 产物
verify_core.py / verify_teacher.py / verify_domain_template_ui.py   无头验证脚本
```

## 桌面端 7 个视图

1. **导入知识资产** — 文件（EPUB/PDF/DOCX/MD/TXT/HTML）或粘贴文本，后台线程抽取 + 自我学习，实时进度
2. **知识模型** — 仪表盘 + **章节目录树**（章节→概念，点击定位原文）+ **主题聚合**（概念按关系自动聚类，一键学习主题）+ 自适应学习路径
3. **概念网络图** — 力导向"活"图谱：节点漂浮、可拖拽、悬停高亮邻居、单击弹详情侧栏（随节点变化）、双击教学；搜索定位、范围切换、缩放；当前书彩色、其他资产灰色
4. **阅读原文** — 全文搜索（高亮定位）+ 概念高亮 chips
5. **教学会话** — 三风格教学（例子/图示/拆解步骤）+ 位置迷你图谱 + 答题（参考回答对照）+ 连续追问 + **快速自测**（判断正误/步骤排序）+ **动手实践任务**（证明/构造/伪代码）
6. **学习者模型** — 学习总览（分布条）+ 成长趋势图 + 待复习队列（间隔效应）+ 跨资产掌握度 + 导出报告
7. **教师模型** — 系统自我理解（概念笔记：重要性/前置/误解/连接 + 彩色异常卡），可重新自检

## 测试

```powershell
# 快速（跳过 LLM 层，~10s，301 个用例）
python run_tests.py --quick

# 全量（无 API key 时 LLM 层自动跳过）
python run_tests.py

# 单层
python run_tests.py --layer core
python run_tests.py --layer ui
python run_tests.py --layer llm
```

**分层覆盖**：

| 层 | 用例数 | 内容 |
|---|---|---|
| core | 292 | 解析器 (txt/md/docx/epub/pdf)、抽取 (来源约束)、模型序列化、学习者 (掌握度/路径/复习/薄弱)、教学 (三风格/评估)、教师 (异常/信号)、解码器与场景准入、领域模板 (领域检测 / 归一化名称与括号别名映射 / 失败降级)、auto-harness、地图上下文、prompt 模板、报告 |
| data | 7 | 演示数据完整性 (资产/关系/路径/教师模型/learner 一致性) |
| ui | 69 | 窗口构建、活图谱、原文高亮/搜索、概念面板、主题聚合、自测/实践卡、学习者/教师视图、i18n、资产切换、领域模板确认框 |
| llm | 7 | 真实抽取 (幻觉防护)、三风格差异化、评估参考回答、追问、教师模型 |
| runner | 2 | 测试入口自身的回归用例（常驻，不随 --layer 切换） |

环境依赖：`ui` 层需要 `PySide6`，缺失时 runner 打印
`-- skip ui: optional dependency unavailable` 整层跳过；`data` 层需要 `data/_demo`
（内含 `assets/` 与 `learner.json`），该目录不入库，缺失时这 7 例显式 skip，不会伪装成通过。
两种情况都会如实体现在汇总行（如本机：`== 301 tests, 0 failures, 0 errors ==` + `OK (skipped=7)`）。

每次改进后跑 `python run_tests.py --quick` 即可确认核心无回归；
发布前跑全量含 LLM 验证端到端链路。

旧版独立验证脚本（`verify_core.py` / `verify_teacher.py`）仍保留可用，
但推荐使用 `run_tests.py` 作为统一入口。

## 验证

```powershell
python verify_core.py      # 核心学习闭环（无 LLM）
python verify_teacher.py   # 教师模型 + 真实 LLM 路径（需配置 key）
python verify_domain_template_ui.py   # 领域模板 GUI 集成（静态校验，未装 PySide6 也可运行）
```

## 后续演进（见 docs/）

1. 抽取层抽象为 `KnowledgeExtractor` 接口（LLM / PDF 专用解析器）
2. 引入 `SourceLocation`（页码/章节/段落）并升级结构化抽取
3. 持久化升级为数据库；接入向量检索 + 图数据库（Hybrid Knowledge）
4. 学习路径从线性列表升级为基于前置关系与 Learner Model 的 Coach Agent
5. ~~PySide6 单文件 `main.py` 按视图拆分为包（`ui/views/`）~~ 已落地：`ui/views/` 7 视图 + `ui/view_manager.py`
6. 领域包继续扩展：更多 `DOMAIN_TEMPLATES`（碳市场等）、领域专用 Prompt 模板、演示数据重建脚本（当前仓库缺失）
*（内容由AI生成，仅供参考）*
