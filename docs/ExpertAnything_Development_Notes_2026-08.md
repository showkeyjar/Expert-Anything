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
| P0 | 差距分析落地：章节目录树 + 抽取升级（概念 12→40、章节归属）+ 概念↔章节定位；teacher 分批自检（json_mode 关闭 + 单批容错，33/33 笔记 + 9 真实异常） |
| P1 | 快速自测（判断正误/步骤排序）、原文全文搜索、主题聚合（连通分量聚类）、LLM 输出随 UI 语言（调用时拼接语言指令） |
| P1-1 | ✅ LLM prompt 多语言化：prompt_registry.py（27KB 三语注册表，extraction/teacher/tutor/practice/quiz/reflect 全覆盖）；规范风格码（example/diagram/steps）；调用时读取以防 i18n 模块级冻结 |
| P1-2 | ✅ generate_practice/generate_quiz/evaluate_practice 接入注册表（6 新键，格式对齐 checks）；tutor_scene_system/teacher_reflect_system 已迁移 |
| P1-3 | ✅ 规范风格码全链路：TeachView 风格下拉稳定映射 + 保存 profile.style + 恢复偏好；AutoHarness adopt/transfer 风格传导 |
| P1-4 | ✅ 语言切换教学视图：`_rebuild_style_combo` 重建下拉 items + 恢复 profile |
| P2 | ✅ 动手实践闭环完整：PracticeWorker + QuizWorker；practice 全链路（generate→show→evaluate→record）+ quiz 全链路（generate→show→local score→record）；TeachResultView 信号全部接线 |
| 测试 | 套件扩展至 75 用例（quick ~9s，含主题/自测/实践回归） |
| 测试 | 统一套件 run_tests.py：71 用例（core 30 / data 7 / ui 27 / llm 7），quick ~9s |
| R15 | **认知地图信息增量**：点击概念不再孤点——`core/map_context.py`（同级要点 siblings：同章节优先/主题 cluster 兜底；下一级要点 next_level：关系邻居带方向+路径后继兜底；概念对比 compare_concepts：相似度/独有关系/共享邻居/章节/掌握度/教师笔记差异 → 差异点+学习建议）；UI：NodeDetailCard 与 ConceptDetailPanel 增同级/下一级区块（可点击游走）+ 对比按钮，新增 ConceptCompareDialog 双栏对比弹窗；图谱 focus 模式无关系/无路径时拉入同章节兄弟作 context（graph_viz._select_nodes） |
| R16 | **地图→教学闭环（游走不设终点）**：同级/下一级要点 1 步开教（NodeDetailCard pill ▶ 按钮 + ConceptDetailPanel 列表双击 → `_start_teach_by_name`）；对比沉淀回教师模型（`teacher.incorporate_comparison`：共享邻居写入双方 connections 作对比锚点、掌握度差 ≥0.2 对弱方挂 learner_gap anomaly 进 anomaly_prioritized_path，幂等去重，纯函数无 LLM）——认知地图的"看到"真正变成"学到"，系统认知随读者游走同步加深 |
| **P0-1** | **main.py 单体拆分**：main.py 3605 行 → 瘦身近 380 行 + ui/views/（7 视图类）+ ui/view_manager.py（统一路由）+ ui/widgets/（6 组件模块）+ ui/widgets/shared.py（卡片/指标卡）；视图通过 `self._main` 引用访问共享状态，通过 Signal 向上通信；pyside_widgets.py 保留完整；ADR-007 记录架构原则 |
| **P1-1** | **LLM prompt 多语言化**：新建 `prompt_registry.py`（27KB 三语注册表），extraction/teacher/tutor/practice/quiz/reflect 各 prompt 键三语齐全；`get_prompt(key)` 调用时读取当前语言，优雅回退；规范风格码（example/diagram/steps）替代中文风格键值（避免 i18n 切换后键不匹配）；tutor._teach_system 等在调用时读取注册表以防模块级冻结 |
| **P1-2** | **generate_practice / generate_quiz / evaluate_practice 接入注册表**：6 个新键（tutor_practice_system/user、tutor_quiz_truefalse_*/ordering_*_system/user）格式对齐 checks 校验逻辑；占位符统一（name/defn/evidence）；EN/JA 区同步翻译；evaluate_practice 用 registry 评估动手任务 |
| **P2** | **动手实践闭环完整**：teach_view.py 新增 PracticeWorker + QuizWorker；`_on_practice_requested` → generate → show_practice → `_on_practice_submit` → evaluate_practice → record_evaluation(channel=practice)；`_on_quiz_requested` → generate → show_quiz → local scoring → `quiz_result.emit` → `_on_quiz_result` → record_evaluation(channel=quiz)；TeachResultView 的 practice_requested/practice_submit/quiz_requested/quiz_result 信号全部接线 |

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
    map_context.py         认知地图上下文：同级/下一级要点推导 + 概念对比（纯函数）
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

1. ~~LLM 输出固定中文~~ ✅ P1-1 完成：prompt_registry 三语化，LLM 输出随 UI 语言
2. ~~无 SourceLocation~~ ✅ P3-1 完成：`char_start`/`char_end`/`line`/`chapter` 已记录；`page` 字段（PDF 1-based 页码，按页边界 char 偏移映射）已落地；`_stamp_locations` 绑定 evidence+页码；`scroll_to_concept` 按章节搜索；HTML 报告与概念详情面板均显示页码
3. ~~`main.py` 单体~~ ✅ P0-1 完成：拆分为 ui/views/ + ui/view_manager.py
4. 扫描版 PDF 无 OCR；docx 仅正文段落（表格/批注忽略）
5. 数据持久化为 JSON 文件，未上数据库
6. ~~学习报告导出为纯文本~~ ✅ P3-2 完成：HTML 报告含内联 SVG 趋势图+跨资产掌握度概览+历史+网络图+概念详情
7. practice/quiz 工具信号未接线 → ✅ P2 完成：完整闭环

## 下一步优先级

- ~~P1-3~~ ✅ 规范风格码全链路：TeachView 风格下拉 `_CODE_TO_IDX`/`_IDX_TO_CODE` 映射稳定；`_on_style_changed` 保存到 learner.profile.style；`_restore_style_combo` 恢复偏好；AutoHarness adopt/transfer 时按 spec.policy.style 重新教学
- ~~P1-4~~ ✅ 语言切换教学视图：`_apply_language` → `_rebuild_all_views` → `ViewManager.refresh_current` → TeachView.refresh()` → `_rebuild_style_combo` 重建下拉 items + 恢复 profile
- ~~P2-1~~ ✅ 动手实践（practice）+ quiz 接入 AutoHarness：`_check_harness_for` 统一在 practice_submit 和 quiz_result 后运行 stuck 检测 + evolve_joint；TeachResultView.append_harness_suggestion 显示联合推荐
- ~~P3-1~~ ✅ SourceLocation 页码锚点：`models.SourceLocation.page`（PDF 1-based）落地；`parsers.pdf_page_offsets` 记录每页 char 偏移；`extraction._stamp_locations` 按偏移映射页码；`ExtractWorker` 仅 PDF 传 page_offsets；`report_html` 与 `ConceptDetailPanel` 均显示「第 N 页」
- ~~P3-2~~ ✅ HTML 报告可视化：`_build_mastery_trend` 内联 SVG 双线图（平均得分+已掌握数，按日期聚合）；资产表/历史/掌握度概览跨资产；`_on_export_html` 修复为传全部 assets + 当前语言；新增 `html_trend`/`trend_avg_score`/`trend_mastered` i18n 键

## 6. 测试与验证

```powershell
python run_tests.py --quick   # 240 用例（无 LLM）—— 每次改进后必跑
python run_tests.py           # 全量（含真实 LLM 端到端）
python run_tests.py --layer ui|core|llm|data
```

测试纪律：测试用 `data/_demo` 的临时副本（tests/util.ensure_demo），
绝不读写真实数据；LLM 用例无 key 自动跳过。
