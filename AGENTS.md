---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: f72b104002d99af940831fcb029a9bd5_7a83e182b6bd11f19825525400cd780f
    ReservedCode1: +F/oTTe63yWWc7bgmkzJ34oeJ4wVbcBDpNiufsPe6OBLIRhIzHkEeZDjkG65BeZCqXi7mmYyGZOOIuv9ovo4oBq3I7tyZ2ckfJGgpaocU3ix2bCXoHKY5a9ovr/OzUYQSsXXLn23Zkkl4qg5470CAQ7u0Xoxb0ZCDbgQOAHCwqYB9VqeMQVLTntkeog=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: f72b104002d99af940831fcb029a9bd5_7a83e182b6bd11f19825525400cd780f
    ReservedCode2: +F/oTTe63yWWc7bgmkzJ34oeJ4wVbcBDpNiufsPe6OBLIRhIzHkEeZDjkG65BeZCqXi7mmYyGZOOIuv9ovo4oBq3I7tyZ2ckfJGgpaocU3ix2bCXoHKY5a9ovr/OzUYQSsXXLn23Zkkl4qg5470CAQ7u0Xoxb0ZCDbgQOAHCwqYB9VqeMQVLTntkeog=
---

# AGENTS.md

# Project: ExpertAnything — Knowledge Decoder & Learning OS

## Vision
> Make anyone expert in anything — by decoding knowledge into what the learner can see, play and master.

本系统不仅是一个辅助学习系统，更是一个**知识解码与生成系统（Knowledge Decoder & Generator）**：
把书籍/论文/文档中的抽象知识"解译"为图像、动画、互动演示与小游戏，
配合教学-评估-复习闭环，**直到用户完全理解**。

- 知识链路：知识资产 → 知识模型 → 知识解码（多模态表征）→ 学习闭环 → 能力成长
- 解码链路（2026-08 落地）：概念+证据+关系 → **SceneSpec**（LLM 生成的类型化场景规范）
  → `check_scene` 代码准入校验 → 确定性渲染器（分步动画 SVG / 互动 HTML 演示+排序游戏）
  → 理解验证（游戏得分记入掌握度）。见 `core/decoder.py` 与 `docs/Knowledge_Decoder.md`。
- 解码铁律（延续来源约束）：场景中的节点/步骤必须源于概念证据与关系，
  LLM 只产出结构规范，**渲染由确定性代码完成**（开放推理 + 确定性外壳）。

Core principle: optimize for **"Does the user learn?"**, not "Can the AI answer?".
Do not build a simple RAG chatbot.

## 当前产品形态（2026-08 稳定基线）

- **桌面端 PySide6**（`main.py` 入口，`python app.py` 或 `python main.py`），8 个视图：
  导入知识资产 / 知识模型 / 概念网络 / 阅读原文 / 教学会话 / 学习者模型 / 教师模型 / 项目全景
- **UI 三区框架**：顶部细条（仅「当前资产 + 掌握度进度 + 语言切换」，**不放导航**）+
  左侧浅色导航区（4 个主入口 + 进阶折叠 + 资产列表）+ 中央展示区；
  导航只有一个入口（侧栏），视图页头统一 `PageHeader`（标题 + 灰细线，无彩色条）；
  全部视觉 token 来自 `expert_anything/ui/theme.py`（唯一色板/字号/圆角/尺寸真相源，
  由 `theme.apply_theme(app)` 在 `MainWindow.setup_ui` 一次性装入）
- **多语言**：中文 / English / 日本語，`core/i18n.py` 的 `t()` 全量接入，
  **禁止硬编码 UI 文本**（新增文案必须走 i18n 键表，三语齐全；
  完整性由 `tests/test_i18n_integrity.py` 常驻守卫）。
  **动态键家族陷阱**：f-string/拼接构造的键（`rel_*`/`trend_*`/`kind_*`/
  `teacher_status_*`/`domain_template_reason_*` 前缀家族与 `{kind}_failed` 后缀家族）
  其成员键名只出现在 i18n.py 内，静态扫描无法识别引用——清理"死键"时**必须先排除这些家族**
  （测试文件中的 `DYNAMIC_PREFIXES`/`DYNAMIC_SUFFIXES` 是权威清单，新增家族须同步登记）

## 学习闭环（产品核心链路）

```text
知识资产 (EPUB/PDF/DOCX/MD/TXT/HTML/粘贴)
  → 解析 (core/parsers.py，零依赖 docx 解包)
  → 知识抽取 (core/extraction.py：LLM 多分块并行 / 确定性降级)
  → 知识模型 (KnowledgeAsset: concepts + relations + learning_path)
  → 自我学习 (core/teacher.py：TeacherModel 概念深加工 + 异常检测)
  → 教学闭环 (core/tutor.py + core/learner.py)
      对齐 → 教学(例子/图示/拆解步骤) → 答题 → 参考回答对照 → 掌握度 → 到期复习(换角度重讲)
```

## 设计理念（历轮沉淀，必须遵守）

1. **来源约束是硬规则**：概念 name/definition/evidence 必须逐字出自原文；
   `_ground_evidence` 校验 + 幻觉概念丢弃；关系只描述原文确实存在的关系；
   TeacherModel 对矛盾/未定义/逻辑断点/反常主张保持"存疑"而非假装全知。
2. **教师模型 = 系统的自我理解层**：站在学习者前面（walk ahead）——
   significance / prerequisites / misconceptions / connections / external_notes（标注来源），
   异常纳入教学优先级；学习者答题与追问（learner_signals）反哺系统认知。
   **存疑条（2026-09-29 已接线）**：教学结果页渲染「系统存疑 · 走在你前面」条——
   `teacher.concept_anomalies`（本概念关联的可行动异常，severity 排序，≤3 条，
   匹配规则与 `anomaly_concept_ids` 同源）命中则逐条展示（kind 经 `kind_*` 键本地化）；
   本概念干净但全篇有待解项 → 提示全篇计数（`doubt_none`）；全篇已解 → 不渲染。
   链路：`teach_view._attach_doubt_strip` → `teach_widgets.append_doubt_strip`，
   异常时静默降级（存疑条是增强，不阻断教学）。
3. **可视化优先（快速学习）**：知识图谱是核心入口，必须是"活"的——
   - 力导向物理模拟（斥力+弹簧+引力），节点稳定后轻微漂浮（幅度 ≤0.5，不得干扰点击）
   - 可拖拽节点（邻居弹簧跟随）、悬停高亮邻居、单击弹详情侧栏（随节点变化）、
     双击下钻（以该节点为中心重建子图，顶部面包屑逐级回退）、搜索定位、
     范围切换（全部资产/当前资产）、缩放（滚轮+按钮）、内容自适应缩放；
     教学入口留在详情卡 ▶ 与右键菜单（主图双击已让位给下钻）
   - 当前书彩色、其他资产灰色（grey_ids），跨资产共享概念连线
   - 图例必须解释颜色语义；初始化缩放保证节点可读（≥0.85）
   - **来源约束可视化**：无原文锚点的概念（模板补全/证据未定位，`locations`
     为空）节点左上角叠加小空心环 ◌（`QGraphicsEllipseItem`，**父子挂载**于
     node item——跟随拖拽/漂浮动画，独立 addItem 会被漂浮动画甩脱），
     tooltip 尾部附 `unanchored_tip` 说明；图例加白底灰虚线 chip
     （`legend_unanchored`）。视觉通道与 frontier 橙虚线环、anomaly 粗边
     正交——三个语义三个通道，禁止复用虚线环。
4. **点击必须产生更深层细节（认知地图信息增量）**：任何可点击节点/条目都要能展开内容
   （概念面板：定义/证据/关系邻居/教师笔记/异常/动作），禁止单层死链接。
   **证据必须可溯源到原文**：概念抽取时 `_stamp_locations` 为每条 evidence 打
   `SourceLocation` 锚点（char/line/page，PDF 按页偏移换算，60 字符前缀容错）；
   教学页证据条与图谱概念卡片（NodeDetailCard，全部证据而非仅第一条）均带页/行
   徽标（`Concept.location_for_evidence` 前缀+省略号容错匹配，无锚点时徽标静默缺省），
   点击经 `evidence_jump_requested(concept_id, evidence)` 信号链
   （TeachResultView/NodeDetailCard → TeachView/ConceptMapView →
   main `_on_teach_evidence_jump`）跳转阅读原文视图并精确定位到该证据段落
   （`SourceTextView.scroll_to_concept`）；**跨资产徽标**：全局图谱概念 id 带
   `asset_id:` 前缀，main 解析前缀→非当前资产先切换资产再跳转（阅读器显示正确原文），
   载荷用 id 而非 name（同名概念跨资产不串）；
   **反向锚点（原文→概念）**：阅读视图 `_render` 按行渲染，锚定行行首插
   `evidence://<cid>` 边注标记（🏷 概念名，浅蓝小胶囊，同行同概念去重），
   点击经 `_on_anchor` 走 `concept_anchor_clicked` 同信号跳概念面板——
   读者在原文里能看到"此段是哪个概念的证据"并能一跳回概念；
   **锚点覆盖率可见**：教师视图在状态/时间行后显示证据锚定率
   （`teacher_anchor_rate`：pct + n/total，≥80% 绿 / ≥50% 橙 / 更低红），
   覆盖不满时灰字列出无锚概念名（`teacher_unanchored_list`，前 5 个 + …，
   与图谱 ◌ 角标同一套 `c.locations` 真相源）——教师模型页能直接看出
   "这份资产里有多少概念是模板补全/证据未定位的"；
   **锚点状态接入学习闭环**：无锚概念在教师模型构建时确定性生成
   `unanchored_source` 异常（`teacher._unanchored_anomalies`，severity=low，
   description 含概念名 → 既有名字匹配规则自动命中），`_assemble`（LLM 路径）
   与 `_fallback`（无 LLM 路径）都汇入——于是无锚概念自动流入
   `anomaly_prioritized_path` 提入教学排序、概念面板异常区与教师页异常板
   （`kind_unanchored_source` 徽标），**无需任何新管道**；教学页（TeachResultView）
   对无锚概念的解释卡后渲染橙色告诫条（`teach_unanchored_warn`：
   "讲解基于关系网络与模板骨架，非逐字源自当前资产"）——来源约束的
   最后一公里：读者在信任讲解之前就知道它的证据地位。
   演示数据由 regen_all 生成时 evidence 必须逐字切片自 source_text
   （模板 evidence 是改写句，不得进入资产——`_stamp_locations` 永远可锚定）。
   **点击一个概念必须给读者"位置感"，绝不孤点**——详情侧栏/面板须展示：
   - **同级要点**（`core/map_context.py::siblings`：同章节兄弟优先，无章节时用
     主题 cluster 兜底）与**下一级要点**（`next_level`：关系邻居带方向+学习路径后继，
     无关系时路径前后项兜底），均可点击游走；
   - **概念对比**（`compare_concepts` + `ConceptCompareDialog`）：定义相似度、
     各自独有关系、共享邻居、章节异同、掌握度差、教师笔记差异 → 可读差异点 +
     学习建议；图谱 focus 模式（`graph_viz._select_nodes`）在无关系/无路径时
     拉入同章节兄弟作 context，保证永远 ≥1 个伴随节点。
   **地图游走必须通向学习，不设终点**：同级/下一级要点项带 1 步开教入口
   （`NodeDetailCard` pill 的 ▶ 按钮、`ConceptDetailPanel` 列表双击），
   直接进入教学会话；对比弹窗可「沉淀到教师模型」（`teacher.incorporate_comparison`）——
   共享邻居写入双方 connections 作衔接锚点，掌握度差 ≥0.2 对弱方挂 learner_gap
   anomaly（进 `anomaly_prioritized_path` 提入教学排序），幂等去重，沉淀即闭环。
   **行动路径（2026-09-29 已接线）**：概念详情卡新增「用起来的行动路径」段
   （`node_detail._append_action_path`，`_append_path_position` 之后）——学习路径中
   本概念之后的后继序列即"按什么顺序用起来"；存在薄弱后继（掌握度 <0.6）时切
   **重点版**（`action_path_focus`，⚠ + 掌握度%，只列薄弱项），全部掌握列普通
   编号版（`action_path`）；路径末尾概念不渲染（不硬造行动路径）；每项 pill 复用
   roam/teach 双按钮，1 步开教。数据确定性：learning_path + learner_state，无 LLM。
5. **学习闭环的可视化锚点**：路径阶梯、掌握度分布条、成长趋势图、复习队列、
   指标卡——Learning Gain（ADR-010）是功能取舍标尺。
6. **间隔效应**：复习队列 `due_for_review()`（薄弱 1 天、掌握 3-6 天），
   复习课用 vary=1 换角度讲解。**复习入口必须带 review 语义**（2026-09 修复断链）：
   批量复习 `_on_review_all_request` → `start_topic_teach(..., review=True)` 整包 vary=1、
   队列推进 `_on_topic_next` 按包语义保持/复位；复习单卡 `review_requested` 信号 →
   `_on_review_one_request` → `start_teach_by_name(review=True)`，一次调用直接进复习教学，
   禁止复用 `_on_teach_request` 再补调（会双开课）；普通主题包永远 review=False。
   **评估轨迹必须带复习语义**：三通道 meta 均记 `review`（answer/practice 用会话级
   `_review_mode`；quiz 用发起时快照 `_quiz_vary`，独立快速自测无课上下文恒 False，
   不得继承上次课的残留标志）——首次学习与复习巩固的掌握度轨迹从此可区分。
   **复习增益可视化**：`core/learner.py::review_gain(state)` 度量间隔效应实际效果
   （每概念：基线 = 首次学习最高分，增益 = 复习均分 − 基线；无 meta.review 的老数据
   按首次学习计，优雅降级），学习者模型页渲染「复习巩固增益」卡（i18n 键
   `review_gain_*` 五键三语）：有数据显均值+Top5 概念行（正绿负红），
   无复习记录显教育性提示而非隐藏——Learning Gain 锚点必须可发现（§5）。
   **负增益反哺教学**：复习均分低于首次基线 0.1 以上（换角度讲解没生效）时，
   `teacher.incorporate_review_gain_signal` 挂 `learner_gap` 异常 + learner_signals
   （幂等去重），经 `anomaly_prioritized_path` 提入教学优先级——重教换风格，
   而不是排更多同类复习；teach_view 三通道（answer/practice 按 `_review_mode`、
   quiz 按 `_quiz_vary` 快照）评估落轨迹后自动检查。
   **双向间隔调度**：`due_for_review` 读 `review_gain` 增益调节间隔——
   正增益（≥0.15 且复习 ≥2 次）间隔 ×1.5（上限 60 天，证据挣来的扩展）；
   负增益（≤-0.1）间隔压 1 天且排序与 `prereq_weak` 同级提前（两个都是
   “地基不稳”信号）；出口带 `gain_stretched`/`gain_weak` 标志，
   学习者模型页复习队列卡渲染对应调度原因标签（i18n 键 `due_gain_weak`/
   `due_gain_stretched`，与 prereq_weak/unanchored 标签同列）——调度可解释。
   **归因分离**：`style_effectiveness` 把 `meta.review` 记录剥出教学风格统计，
   按复习风格单列 `review` 子桶（avg/count）——复习高分是“记住了”的证据，
   不是“教得好”的证据（复习样本偏高分：只有掌握过的概念才进复习），
   混入会稀释教学风格归因；只有复习记录的风格以 count=0 + review 桶保留。
   学习者模型页风格效果卡渲染复习巩固标签（i18n `style_review_bucket`，
   青色小标签「复习巩固 N 次 · 均分 X%」）——教学 avg 与复习保持度并排可见。
   掌握预测卡（`mastery_prediction` 接线，i18n `prediction_*`）展示每概念
   趋势/预测值/还需会话数，下滑概念排最前，行内「继续学」直达教学——
   复习凹陷已被剔除，遗忘不会被误报为下滑。
   学习计划卡同样接入教师模型：`generate_study_plan(asset, state, minutes,
   teacher=)` 内部真正调用 `anomaly_concept_ids`（此前 import 后从未调用，
   anomaly_ids 恒空集——异常提权在学习计划入口整段失效），UI 传当前资产
   还原的 TeacherModel；无 teacher 时保持路径原序（兼容旧调用）。
   stuck 风格轮换同时感知复习保持度：`style_rotation_hint(state, current,
   fallback_next)` 读 style_effectiveness 的 review 桶（每风格 ≥2 条才可信），
   仅当盲循环下一站的保持度比当前风格差 0.15 以上、且存在保持度不低于当前
   的替代风格时才改道（默认保持盲循环不变，样本不足不干预——保守降级）；
   lesson 落 `rotated_style` + `rotation_reason="retention"`（LLM 分支与
   deterministic 分支都落，教学轨迹可追溯改道原因）。
   auto_harness 的 `Harness._rotate_args` 同构接入：候选池限定 spec 声明的
   `policy.teach_styles` 子集（改道永不越出 spec 结构约束），中文风格名
   （例子/图示/拆解步骤）与轨迹桶 key 同源可直接查表；异常静默回落盲循环。
   演化 O1（`_candidate_o1` 换风格候选）第三处同构接入：`evolve` /
   `evolve_from_sessions` 加可选 `learner_state` 透传（默认 None 保持盲选，
   向后兼容），`evolve_for_stuck` / `evolve_for_regression` / `evolve_joint`
   把手头 state 传入——演化候选同样不把学习者推向已知保持度差的风格；
   候选池取 STYLE_CYCLE 全集（演化允许引入新风格，仍过 check_harness）。
   **锚点感知调度（2026-09-29）**：无锚概念（◌，`c.locations` 为空）复习间隔
   **减半**——学习者无法跳回原文自助重温，系统侧复习是其唯一巩固通道；
   条目带 `unanchored` 标记，学习页复习卡渲染 ◌ 标签（`due_unanchored`）。
   与 `prereq_weak` 同模式：图谱/锚点信号 → interval 压缩 → 复习排序。
7. **UI 工程规则**：
   - 视图重建（`_rebuild_all_views`）必须先清旧控件引用再构建，禁止访问已删除控件
   - QGraphicsView 等大 sizeHint 控件必须设 max 高度，防挤占主内容区
   - 布局中主内容区必须 stretch（addWidget(w, 1)），避免"标题占半屏"
   - 全局 excepthook：未捕获异常写 error.log + 弹窗，禁止静默消失
   - **QTreeWidgetItem 角色陷阱（2026-10 踩坑）**：PySide6 里 `item.setData(0, 2, ...)`
     的 **int role 2 会落到 display 槽位**——写入后 `text(0)` 与 `data(0,0)` 都变成该
     载荷值，而 PyObject 转字符串为空，于是**整行渲染成空白**（章节目录的概念行就
     这样空白了多轮无人察觉）。载荷一律放 `Qt.UserRole` 起（当前约定：
     `knowledge_view._ROLE_PAYLOAD / _ROLE_DIFF / _ROLE_CAPTION`），DisplayRole 只留给
     读者要看的标题；回归由 `test_ui.py::TestRound10Drilldowns::test_toc_rows_keep_their_caption`
     守住（断言 caption 非空 + 载荷可解析）。同族坑还有 DeferredDelete 计数（见工程纪律）。
   - **死链接零容忍**：凡渲染出"可点击"外观的统计 chip / 徽标 / 卡片，必须接线到
     真实动作（下钻、切视图、定位、开教），否则降级为纯文本标签——数字本身不是
     交互。反例修复见设计理念第 20 条。
8. **多语言**：所有用户可见文本走 `t(key)`；语言切换重建 topbar/sidebar/views 并
   持久化 lang.json；模块级 `_t()` 求值的常量会导致切语言失效（用渲染时查表函数）。

8. **章节目录与主题是结构入口**：技术人员学习先看结构——知识模型页必须有
   章节目录树（章节→概念，点击定位原文）与主题聚合（按关系连通分量聚类，
   一键按学习路径顺序学整个主题）。概念必须有章节归属（SourceLocation 轻量版，
   用证据位置确定性匹配章节标题，不依赖 LLM）。
9. **多形式验证闭环**：答题（参考对照）之外，教学流程必须提供
   - 快速自测（判断正误 / 步骤排序，基于证据出题，得分记入掌握度）
   - 动手实践任务（证明/构造/伪代码/复现：生成→作答→严格评估→参考解答→记入掌握度）
10. **LLM 输出语言跟随 UI**：教学/评估/追问/自测/实践的 prompt 按当前界面语言
    追加语言指令（必须在**调用时**拼接，模块级常量拼接会在 import 时冻结语言）。
11. **LLM 长输出稳定性**：单次输出超过端点限制（如 33 概念一次自检）必须分批
    （≤12/批）；长 prompt + json_mode 在部分端点返回空——优先用普通模式 +
    容错 JSON 解析；单批失败不得丢弃已成功批次。
12. **代码强制准入 + 卡壳回退（OmniScientist 借鉴，见 docs/OmniScientist_Inspiration.md）**：
    - LLM 生成的讲解/自测/实践/评估必须通过 `core/checks.py` 的代码校验
      （结构完整、讲解非定义复制、扣住本概念、anti-template 相似度），
      失败带原因重试 1 次，仍失败显式降级——prompt 里的铁律是请求，检查才是强制；
    - 学习轨迹（`record_evaluation(meta=...)`）是唯一事实源：通道/风格/策略
      轮换全部落轨迹，卡壳检测、报告、教师模型都读它而非叙述文本；
    - 卡壳闭环：连续 3 次评估不达标 → `stuck` 标签提优先级 + `Tutor.teach`
      自动轮换讲解风格 + `incorporate_stuck_signal` 写入教师模型
      （教学侧聚合器**只看教学通道**：`stuck_concepts`/
      `regression_detection`/`mastery_prediction` 跳过 `meta.review`
      记录——复习低分是间隔效应的正常遗忘/巩固失败，归 gain_weak 管道
      处置，混入会误触发风格轮换/O1/O2 演化/趋势误报并与 learner_gap
      异常双重信号污染一个根因；错题本/难度标签/ROI 统计/间隔计数是
      学习者视角总量语义，混通道合理）；
      同时驱动 `auto_harness.evolve_for_stuck` 演化 harness 结构
      （换风格+补 scene，候选再过 check_harness）；**机制不外露**：卡壳时
      系统静默采纳演化候选（`main._adapt_teaching_silently` →
      `_apply_harness_silently` 持久化 harness_state.json per-asset + 审计链），
      并把实时讲解风格切到候选 style（`_nudge_style`，blockSignals 不污染
      学习者偏好）——学习者看不到演化卡/守卫裁剪/预算/回归等技术措辞，
      下一次「换个讲法」自然落到新风格；
      演化全程落 `_history` append-only 审计链（stuck/manual/steady + old→new
      摘要，save 时保留不被冲掉）——自动化可解释可追溯（审计链只落数据，不渲染）；
      预算核算用 `estimate_cost`（固定基础 + 内容规模≈token），budget_ok 感知昂贵调用；
      harness 跨资产迁移须过 `evaluate_transfer` 差分评估（目标资产上 OFF/ON
      双配置取差分 + 前提三态 eligible/mismatch/inconclusive + 成本差分；
      仿真收益不可测时用计分覆盖度差分兜底，成本 ≤ 预算 30% 才采纳），
      采纳走 `adopt_harness_for_asset`（持久化 + 审计链 reason="transfer"）；
      本地无演化候选时，卡壳分支静默采纳其他资产的迁移候选
      （`_adopt_transfer_silently`，每 (target, source, spec) 一次、已展示源
      跳过重复差分评估，同样只切 style 不弹卡）；
      演化算子三层信号源：stuck（`stuck_concepts` → O1 换风格）、regression
      （`regression_detection` 从好变差 → O2 裁守卫，审计链 reason="regression"；
      **只看教学通道**——`meta.review` 记录跳过，
      复习低分是遗忘证据归 gain_weak 管道，混入会误触发 O2 裁守卫）、
      会话报告统计（`persist_session_report` 落
      `_sessions` 有界 append-only + `aggregate_reports` + `evolve_from_sessions`
      → O2/O3；`save_harness_state` 保留 `_sessions` 不冲信号底座）；
      **安全铁律：`SAFE_GUARDS`（safe_only）永不裁**，O2 只在可裁守卫中选触发最多者；
      三层信号并发时用**联合演化**（`detect_signals` 统一检测 →
      `_o2_target_fusion` 回归假设×会话实际触发仲裁，真实数据优先 →
      `evolve_joint` 融合决策）：同算子跨源去重、候选按因果强度 O2>O1>O3、
      reason 触发家族串（stuck→regression→sessions）、diagnosis 可解释行；
      多信号并发时同样走静默采纳（reason 记家族串、审计链可拆分）；不同信号
      来源（单信号/联合/迁移）对学习者一律无差别——只体现为讲解风格变化
      （第 22 轮小白视角：内部机制卡片整体下线）；
    - 生成文本中绝对化措辞必须经 `checks.temper_claims` 软化。
13. **知识解码：多模态表征生成（见 docs/Knowledge_Decoder.md）**：
    - LLM 只产出 **SceneSpec**（类型化 JSON 场景规范：nodes/edges/steps/game），
      渲染一律由确定性代码完成（`core/decoder.py`），LLM 永不直接输出 SVG/HTML；
    - SceneSpec 必须过 `decoder.check_scene` 代码准入（节点数 3-8、边引用存在、
      步骤 2-6 且引用节点存在、游戏答案为合法排列），失败带原因重试 1 次，
      仍失败降级为基于概念关系的确定性场景（结构图仍在，动画/游戏缺省）；
    - 场景内容必须源于概念定义/证据/关系（来源约束延伸到多模态）；
    - 互动游戏的得分经既有 quiz 通道记入掌握度——解码产物必须回到学习闭环，
      不做"看完就走"的展示品。
14. **AutoHarness：教学 harness 的自动生成与演化（meta-harness，见 docs/AutoHarness_Strategy.md）**：
    - 洞察：**Agent = Model + Harness** 已成行业共识（dsh/LEH/SWE-agent ACI/ToolTrust），
      下一步是 **harness 设计本身的自动化**；把既有手写教学闭环提升一个抽象层级；
    - LLM 只产出 **HarnessSpec**（类型化 JSON：tools/policy/loop/evaluation/meta），
      执行/准入/评估一律由确定性代码完成（`core/auto_harness.py`），LLM 永不直接输出可执行 harness；
    - HarnessSpec 必须过 `check_harness` 代码准入（工具 ∈ 槽位、守卫 ∈ 白名单、
      mode/sandbox/metric 合法、retry/预算/步数夹紧），失败带原因重试 1 次，
      仍失败确定性兜底 `fallback_harness`；
    - 工具槽位 = 能力接缝（dsh 三角色）：teach/scene/quiz/practice/review 均可注入
      provider 替换实现，默认走确定性 provider；
    - `Harness.run` 产出 **append-only 轨迹事件流**（"Model-visible means logged"）——
      预算耗尽事件本身也落轨迹；报告是轨迹的投影，不是独立事实源；
    - pre 守卫（预算/沙箱 fail-closed，ToolTrust gatekeeper）→ provider → post 准入
      → 带原因轮换重试（有界）→ 仍失败显式确定性降级；
    - **差分评估** `compare_harnesses`：OFF/ON 双配置取差分（绝不拿 ON 直接对标准答案比），
      |diff| ≤ noise_floor → noise 不采纳，三态 gain/loss/noise + inconclusive；
    - **演化算子** `evolve`：卡壳换风格+补 scene / 误伤裁守卫 / 吃紧扩预算，
      每个候选必须再过 `check_harness`——"auto"的安全边界是结构而非可信度；
    - 学习闭环回写 `apply_to_learner`：经 record_evaluation 记掌握度，meta 带
      channel="harness" / harness 名 / 指标 / 守卫触发——卡壳检测与教师模型
      继续读学习轨迹这一条真相源。

15. **领域模板与领域专用解码（domain pack，见 docs/电力交易领域学习方案.md）**：
    - **领域模板**（`core/domain_templates.py`）预置领域知识骨架：章节结构 + 概念清单
      （name/definition/evidence/aliases）+ 推荐学习路径 `quick_path` + 常见误解 + 背景锚点。
      当前内置 `ELECTRICITY_TRADING_TEMPLATE`（`domain_id="electricity_trading"`，
      5 章节 / 19 概念 / 7 步 quick_path / 4 条误解 / 4 个锚点）；`DOMAIN_TEMPLATES` 是唯一注册表，
      未注册领域走 `unknown_domain`；
    - **模板只供骨架，不改来源约束**：模板**不新增、不删除、不重排**资产概念；
      命中概念仅在 `definition`/`evidence` 为空时写入模板文本，**已抽取的来源约束内容永不被覆盖**；
    - **套用入口（确定性，无 LLM）**：`detect_domain_from_title(title)` 标题关键词判定领域 →
      `build_concept_mapping(asset, template)` 干跑给出命中/覆盖率 →
      `apply_domain_template(asset, domain_id, min_coverage=...)` 落盘。
      UI 在导入抽取完成后自动弹「领域模板」确认框（`ui/views/import_view.py::_offer_domain_template`），
      **确认后才套用**；标题无领域信号、领域无模板或用户拒绝则不套用，导入照常完成；
    - **ID 映射机制（最终形态 = 归一化名称 + 括号别名）**：模板概念 ID（`et-*`）与资产概念 ID（`c*`）
      两个 ID 空间**永不做 ID 对齐**，只按名称匹配：
      `_normalize_name`（NFKC → 小写 → 折叠空白/分隔符 → 去标点，与 `learner.normalize` 同源）
      + `concept_name_variants`（「节点边际电价(LMP)」同时产出全称 / 去括号名 / 括号内别名，
      括号别名 ≥2 字符才参与，避免单字母误配，并叠加模板概念声明的 `aliases`）；
      变体按长度降序匹配（全称优先于别名），每个资产概念最多被认领一次，
      未命中的模板概念记入 `unmatched` 而非静默丢弃；`resolve_template_concept_id`
      提供三路解析：模板 ID → 资产 ID（经其名称）→ 概念名（任意变体拼写）；
    - **映射失败即降级、保留原路径**：`learning_path_applied=False` + `reason`
      （`degraded_no_mapping` / `degraded_low_coverage`（覆盖率 < `DEFAULT_MIN_COVERAGE`=0.5）/
      `unknown_domain`）时，**资产原有学习路径保持不变**；重写路径前每个 ID 都回查 `asset.concepts`；
      enrich 写入模板 evidence 后**立即补跑 `_stamp_locations`**（幂等）——原文确实逐字包含
      该句则锚定出徽标，paraphrase 不在原文则静默无锚（降级不报错，enrich 语义不变）；
    - **领域专用解码器**（`core/decoder_electricity.py`）：6 个模板概念 ID → 4 类策展 SceneSpec
      （市场架构 / 电价形成 / 交易流程 / LMP 节点电价），`scene_for_concept_id` 取场景，
      `get_scene_for_concept(concept_ref, asset)` 支持与模板同源的三路解析，
      `domain_scene_for(asset, concept, domain=None)` 再加**领域闸门**——非电力资产不会
      因概念重名而套用电力视觉；
    - **第二领域解码器**（`core/decoder_carbon.py`，carbon_trading）：10 个模板概念 ID
      （ct-001..010，quick_path 全覆盖）→ 4 类策展 SceneSpec（总量与配额分配 / 碳市场与碳价形成 /
      履约周期与 MRV 流程 / 抵消机制），与电力解码器同契约：生成器内过 `check_scene`、
      `domain_scene_for` 资产标题闸门、`resolve_template_concept_id` 三路解析但
      **必须显式传 `domain_id`**（默认值是 electricity_trading，不传会解析失败——已踩坑）；
    - **分发注册表**：`decoder.scene_for_concept` 不再硬编码 electricity 模块——
      按标题检测领域 → 查 `DOMAIN_DECODERS` 注册表 → 懒加载模块调 `domain_scene_for`；
      新增领域解码器只需注册一行，不改动入口函数；解析/导入异常一律降级 `fallback_scene`；
    - **统一入口 `decoder.scene_for_concept(asset, concept)`**：领域策展场景优先，否则回落
      确定性 `fallback_scene`（教学/阅读链路只认这一个入口；领域模块导入或解析异常一律降级，
      绝不让课程中断）。领域模板与专用解码器全程确定性：无 GUI、无网络、无 LLM；
    - **领域专用 Prompt（`core/prompt_registry.py`，Phase 3）**：LLM 链路（抽取
      `_extract_with_llm`、教师 `build_teacher_model`）在检测到领域时改用领域 Prompt，其余逻辑不变。
      键名 = 通用键 + 领域后缀（`DOMAIN_PROMPT_SUFFIXES`：`electricity_trading` → `electricity`，
      即 `extraction_system_electricity` / `extraction_user_electricity` /
      `teacher_system_electricity` / `teacher_user_electricity`，zh-CN/en/ja 三语必须齐全）；
      **选择与回退**：`get_domain_prompt(base_key, domain_id, lang)` 在无领域、领域未注册或键缺失时
      返回通用 Prompt，`domain_id=""` 显式禁用领域 Prompt；未检测到领域时渲染结果与通用路径逐字符一致；
      **骨架只作对齐导引**：`domain_concept_skeleton(domain_id)` 渲染的模板概念骨架（含 `et-*`）
      注入 user prompt 帮助输出与模板对齐，但 `_assemble` 的逐字证据校验与幻觉概念丢弃**一律不放宽**——
      引导与来源约束冲突时，以来源约束为准（同第 15 条）。

16. **项目全景 = 跨材料认知投影（UI 第 8 视图，`ui/views/panorama_view.py`）**：
    单份材料只能回答"它讲了什么"；多份材料合看才能回答"项目由哪些部分组成、瓶颈在哪、
    哪些说法还没被验证"（Project Sensemaking）。这一页是**只读投影**——聚合现有真相源
    （`main._build_global_asset` 合并图 / `teacher_models[aid]["anomalies"]` /
    `asset.concepts[].locations` 锚定率 / `learner["concepts"][].mastery`），
    渲染「认知规模 / 材料清单 / 关键未知（严重度 high→info 排序）/ 断点前沿（◌无锚 + 薄弱掌握）」
    四段，**不含任何新推断、无 LLM**（投影而非新事实源）。
    交互：材料「查看」切资产但**停留在全景页**（`main._switch_asset_quiet` 不强制跳走）；
    点概念跳转切资产并开概念详情面板，匹配不到则回落学习者模型。
    新增/重命名视图必须同步三处：`view_manager.py` 的 `VIEW_*` 常量与名称映射 /
    `main.py` 的 `VIEW_MAP` / 测试 `content_stack.count()` 断言（现为 8）。

17. **学习现场捕获：★收藏 + 📝费曼笔记必须出现在学习发生的地方（2026-10 落地）**：
    学习者在「教学结果页」或「阅读原文」里的那一刻洞察才是真洞察——只在图谱
    卡片上有入口等于让他换个页面再记一遍。规则：教学结果页 header 与阅读页概念
    工具条都要有 ★/📝（阅读页工具条 = 概念下拉 + ★收藏 + 📝笔记 + 🔍聚焦，
    未选概念时三者禁用），有笔记时按钮显「📝 我的笔记 ✓」；
    编辑器统一走 `ui/widgets/_helpers.py::open_note_editor`（模态，
    保存即 `learner.set_note` + `learner.save`，local-first，与图谱卡片同源）；
    凭证 UI 走 i18n `note_edit` / `note_edit_has` / `fav_toggle_tip`。
    **复述自检（2026-10-21 落地）**：教学结果页 header 与阅读页工具条再加
    🗣 复述自检按钮——学习者用自己的话复述概念，`core/feynman.coverage`
    确定性对照（要点二元组覆盖 + 领域术语命中，零 LLM），渲染覆盖度/漏掉要点/
    可再提术语；结果可一键存为笔记。入口 widget 为
    `ui/widgets/feynman.py::FeynmanDialog`，两入口共用
    `_helpers.open_feynman_check`。

18. **概念聚焦阅读 = source_text + c.locations 的确定性投影（2026-10 落地）**：
    `SourceTextView.set_focus_concept(cid)` 只渲染**提到该概念的行 + 其证据锚点行
    （`c.location_for_evidence(ev).line`）各 ±1 行**，行间断处插 `⋯`（让读者知道
    有内容被折叠，且**一句话都没被改写**）；顶部卡 = 定义 + 命中行数/锚点数徽标 +
    `▶ 开教`（`teach:///名称`）/ `🎬 看解码`（`decode:///cid`）/ `↩ 回全文`
    （`fulltext:///`）三个链接（`_on_anchor` 新增三个 scheme 分支）。
    铁律：**无 LLM、不改写原文**；概念在原文无逐字出现（模板补全/证据未定位）时，
    **如实回退全文并在卡上说明**（`focus_no_match`），不假装聚焦；
    退出聚焦恢复阅读位置（聚焦期间 `_position_armed=False` 防止把投影的滚动偏移
    写回存档）。`看解码` 弹窗复用 `teach_widgets.DecoderSceneCard`，
    游戏得分经既有 quiz 通道 `record_evaluation(meta.channel="quiz")` 记回掌握度——
    解码产物必须回到学习闭环（同第 13 条）。

19. **章节/主题综合测验：单概念自测测"回忆"，组合测验测"结构"（2026-10 落地）**：
    入口在知识模型页——章节行 `📚`（`chapter_quiz_btn`）与主题卡「📚 综合测验」
    （`topic_quiz_btn`），信号 `KnowledgeView.group_quiz_requested(concept_ids, title)`
    → `main._on_group_quiz_request` 开模态 `GroupQuizDialog`（`ui/widgets/group_quiz.py`），
    关闭后 `_refresh_all_views()` 同步掌握度配色。
    题目按组内概念逐条生成（`GroupQuizWorker`，**上限 5 题**、判断正误/排序交替，
    复用 `Tutor.generate_quiz` 既有准入；**生成在 worker 线程**，无 LLM 自动确定性降级），
    判分与小结在确定性代码里：逐概念 `record_evaluation(..., meta={"channel":"quiz"})`
    （≥0.6 记 `mark_completed`），结束渲染组内平均分 + 逐概念得分 + 薄弱提示卡。
    UI 测试注意：入口按钮**连着 main 的真实 handler（会开模态）**——headless 测试
    点击前必须先 `disconnect` 再临时接自己的 lambda，`finally` 里接回，否则测试会
    永久阻塞在模态事件循环（已踩坑）。

20. **统计 chip 必须下钻（消灭死链接，2026-10 落地）**：项目全景的 5 个规模 chip
    （[_ScaleChip](expert_anything/ui/views/panorama_view.py)）此前只是"显示数字、
    点了没反应"的裸卡——**能点的外观必须给真实动作**：概念数/关系数 →
    `view_switch_requested("concept_map")`（main 接 `on_nav_click`）切到概念网络；
    资产数/未知数 → `_scroll_to()` 定位到材料清单卡/关键未知卡；
    **共享概念 → `_show_shared()` 弹出跨材料共享概念清单**（`_collect()` 为此产出
    `shared_list`：展示名 + 出现材料标题，每行可 `concept_jump_requested` 一跳进概念）。
    每个 chip 带 tooltip 说明"点了去哪"；数字是事实，下钻才是学习入口。

21. **概念卡的双向位置感：前置链 + 「学会它解锁什么」（2026-10 落地）**：
    只有"前置依赖链"（上游）是半张地图——学习者答不出"我为什么要学它"。
    `node_detail._append_unlocks` 反向遍历 `prereq/causes` 关系
    （`r.source == 本概念` → 下游 `r.target`），列出**解锁概念 + 各自当前掌握度**，
    pill 复用既有 roam/开教双按钮；无下游时整段不渲染（不硬造"解锁"）。
    确定性（纯关系反查，零 LLM），与本卡既有 前置链/同级要点/下一级要点/行动路径
    组成完整位置感；因果与前置同权（源文确说的依赖才算）。

22. **学习者自己的输出必须能回看（2026-10 落地）**：费曼笔记/收藏写完就沉底
    等于白写——知识模型页掌握度过滤下拉新增「📝 有笔记」（`filter_note`，
    复用既有 `filter_favorite` 机制），命中行**内联渲染笔记摘要**（60 字截断，
    存于 `_ROLE_CAPTION` 以便清空过滤时还原），清空过滤即恢复原行。
    规则：凡是让学习者"产出"的功能（笔记、收藏、答案、实践），都必须有一个
    聚合入口能把自己的输出重新读回来（笔记在 TOC、收藏在过滤、答案在错题本）。

23. **领域术语对照表（术语表）面板（2026-10 落地）**：`core.terminology.glossary/stats`
    与 `terminology_count`/`terminology_source_note` 三语键早已就绪却**无 UI**——
    注意这类"有数据没展示"的键曾被测试文件"影子引用"，静态死键守卫**察觉不到**
    （排查手段：找仅出现在 tests 里的 i18n 键）。补齐入口而非重建数据：
    知识模型页过滤器行新增「🔤 术语表」按钮（`KnowledgeView.glossary_requested` 信号 →
    `main._on_open_glossary`），**仅在 `detect_domain_from_title(asset.title)` 命中领域时渲染**
    （无术语可列则不渲染按钮，死链接零容忍）；模态 `ui/widgets/glossary.py::GlossaryDialog`
    按章节渲染 `glossary()` 行（术语名 / 别名 chips / 定义 / 要点），头部 `terminology_count`
    覆盖数字 + `terminology_source_note` 来源说明；**行级跳转**靠
    `build_concept_mapping(asset, template)["mapping"]`（模板 ID → 资产概念 ID），
    命中才给 ▶（`concept_jump_requested`）；跳转前 `dialog.accept()` 先关模态
    （否则后台地图被模态事件循环挡住，跳了也点不到）。术语全部来自已注册领域模板，
    未登记不推断（来源约束）；确定性、零 LLM。

24. **统计 chip 必须下钻（收尾：topbar 进度条，2026-10 落地）**：第 20 条针对裸统计的
    规则此前只覆盖项目全景 5 个 chip；topbar 的「已掌握 m/t · 学习中 l · 待复习 r」
    （`MainWindow._update_topbar`）仍是不可点的纯文本——现改用 **rich-text 锚点**渲染：
    `_topbar_progress_html` 用哨兵字符（`_DRILL_SENTINEL = "\x01"`）标记 i18n 模板
    （`topbar_progress`）的数值槽位再替换为 `<a href="drill:*">`，**不改 i18n 模板**
    （译文重排/加空格也能正确链接，且绝不泄漏控制字符；测试断言渲染文本不含 `\x01`）；
    `_on_topbar_drill`：已掌握/学习中 → `on_nav_click("knowledge")` 后
    `_mastery_filter.setCurrentIndex(4/3)`（`refresh()` 会重建下拉，**必须先切视图再设索引**），
    待复习 → `on_nav_click("learner")` 复习队列；锚点 `title` 复用
    `filter_mastered`/`filter_learning`/`due_title` 键（点了去哪必须说清楚）。

25. **领域术语双入口：概念卡 + 原文悬停（2026-10-21 落地）**：术语表只在
    知识模型页有入口不够——学习者点概念、读原文时也要即见官方术语。
    - **概念卡「领域术语」段**（`node_detail._append_terminology`，在
      `_append_action_path` 之后）：`terminology.get_term(concept.name, domain)`
      渲染 别名/释义/要点（前 2 条）+ 相关术语（`term.prerequisites` 经
      `term_by_id` 解析名，≤3 个，用 `terminology_related` 键作前缀）；
      未登记显 `terminology_none`（来源约束，不猜）；资产无可检测领域整段不渲染。
      至此 `terminology_*` 影子键全部清零。
    - **原文悬停释义**（`pyside_widgets.SourceTextView._term_tooltips` +
      `_highlight` 改实例方法）：概念高亮锚点挂 `title="正名 · 别名 — 释义"`，
      边读边懂；`_term_tip_cache` 按资产缓存，无领域时为空映射（零开销）。
      术语内容全部来自已注册领域模板（确定性，零 LLM）。

26. **领域包必须端到端可跑通：演示资产 + 默认当前资产稳定（2026-10-21 落地）**：
    `renewable_forecasting` / `distributed_energy` 的模板、策展解码器、领域 Prompt
    早已注册（`DOMAIN_TEMPLATES` / `DOMAIN_DECODERS` / `DOMAIN_PROMPT_SUFFIXES`），
    但 `regen_all.py` 只生成 electricity + carbon 两个演示资产——无演示资产 = 无入口
    = 死代码。现补齐 4 个演示资产（新增 `a20260908-004` 新能源、`a20260908-005` 分布式）。
    **排序陷阱**：`main.load_data` 按文件名 sorted 读入、取第一个为当前资产——
    新增资产 id 必须大于 `a20260908-002`（如 -004/-005），否则默认当前资产被挤走，
    大量假设"当前资产=电力"的 UI 测试会静默失效。资产标题必须能触发
    `detect_domain_from_title`：DER 标题（"分布式能源…微电网与虚拟电厂"）不得含
    `_DER_DOMINANT_GUARD` 里的词（电力/电价/功率预测/forecast…），否则被抢走。

27. **主动回忆证据必须进学习闭环，且归因分离（2026-10-21 落地）**：费曼复述自检
    此前只在对话框里展示覆盖率，从不 `record_evaluation`——"讲了却不算数"，
    违反"学习轨迹是唯一事实源"。现在：
    - 对话框结果卡下给「记入学习轨迹」按钮（`recall_record_btn`，**显式同意才记**，
      反复检查不得刷分），写入 `record_evaluation(..., score=coverage,
      meta={"channel": "recall"})`——复述覆盖度成为掌握度证据，与教学得分一起
      参与复习调度；`feynman._resolve_asset_id` 处理全局图谱资产
      （`asset_id == "global"`）时从概念 id 前缀/既有轨迹解析真实文档 id；
    - **归因分离**（同 review 的规则）：`learner.RECALL_CHANNEL` / `is_recall_record`；
      `stuck_concepts`、`mastery_prediction`、`style_effectiveness`、
      `auto_harness.regression_detection` 一律跳过 recall 记录——复述低分说明
      "表达不完整"，不是"教学策略失败"，混入会误触发风格轮换/O1/O2 演化；
      错题本/难度标签/ROI/间隔计数是学习者视角总量语义，混 channel 合理（同 §6）；
    - **概念卡回报状态**（`node_detail._append_recall_status`）：最近一次复述
      覆盖率 + 漏掉要点数（用存下的 answer 重跑 `feynman.coverage` 确定性重建）
      +「再复述一次」按钮（`open_feynman_check`），主动回忆形成可重试的闭环。
    - **掌握度构成可见**（`learner.mastery_breakdown` +
      `node_detail._append_mastery_breakdown`）：按通道
      （`CHANNEL_ORDER`：answer/quiz/practice/flashcard/recall/harness）投影
      history 的 `meta.channel`，概念卡渲染「通道 N× 均分」（`breakdown_*` 六键，
      静态映射、非动态键家族），旧记录无 meta 归 `answer`——掌握度不再是黑盒数字。

28. **教师模型必须向学习者回显"它记住了你的困惑"（2026-10-21 落地）**：
    `teacher.incorporate_learner_signal` / `record_learner_question` /
    `incorporate_comparison` 持续写入 `learner_signals`（低分作答片段、追问、
    对比发现），但桌面端 UI 零引用——系统在学习者身上学到的东西，学习者自己看不到。现在：
    - 概念卡教师段（`NodeDetailCard.set_concept` 的 teacher 分支）在
      significance/misconceptions 之外渲染:系统综合理解 `note`（`detail_system_note`）、
      学习者真实信号（`learner_signals_title`，最近 3 条，`• ` 前缀）、
      材料外补充（`external_notes_title` + `external_source_tag` 来源徽标，
      最近 2 条）——外部补充必须显式标注"来源：材料之外"，来源约束不因展示而放松；
    - 教师模型页笔记列表项追加 `notes_signal_n`（`· N 条学习者信号`）计数；
    - **同族陷阱修复**：该列表原先 `item.setData(2, concept_id)` —— int role 2
      即 DisplayRole，整个笔记行会被载荷覆盖成空白（AGENTS 工程纪律 §7 记录过
      的同族坑）。载荷已改 `Qt.ItemDataRole.UserRole`，`item.data()` 同步。

29. **最高优先级教学信号必须可行动：教师异常板接「查看概念 / 去学它」（2026-10-22 落地）**：
    异常经 `anomaly_prioritized_path` 提入教学排序，但教师页异常板此前只渲染
    kind/severity/描述/位置——学习者看到"矛盾/未定义"却无处可去。
    `teacher_view._match_anomaly_concept` 用与 `teacher.anomaly_concept_ids` 同源的
    名称在文本中匹配规则（desc + location），**最长名优先**（短名不得抢匹配）；
    命中则卡片加「查看概念」（`open_concept_panel`，跳概念面板）与「去学它」
    （`teach_requested`，main 接 `_on_teach_request` 直接开课）两个真实按钮，
    **未命中保持只读（绝不臆造目标）**。演示 teacher 模型只有 needs_llm 异常
    （不含概念名），所以 UI 测试须注入概念绑定异常后再断言按钮——别把
    "无按钮"误读成死链接。

30. **错题要能看到"我当时写了什么"；复述要看趋势而非单点（2026-10-22 落地）**：
    - 错题本此前只显示概念/分数/反馈——`weak_history` 返回的 `answer`
    从未展示，学习者无法回答"我错在哪"。现在每行第二行渲染
    `error_book_your_answer`（学习者原话，90 字截断，浅黄底
    `error_book_answer_lbl`），与反馈并排形成"我的答案 vs 系统评价"；
    - 概念卡复述段增 `learner.recall_trend`（最近 5 次覆盖率，旧→新纯函数）
    + 字符柱 `▁▂▃▄▅▆▇█`（`recall_trend_lbl`，≥2 次才渲染——单点是噪声）；
    最近 3 次最大值未比 3 次前高出 0.05 → `recall_stagnant` 提示换策略
    （先列全部要点再逐条展开），把"覆盖率停滞"变成可执行建议而非沉默数字。
    两者都是 history 的确定性投影，零 LLM。

31. **学习者的输出必须完整可回看：错题不截断、自测能看到"错在哪"、笔记浮在阅读现场（2026-10-22 落地）**：
    - **错题本不静默截断**：此前只渲染 `weak_entries[:5]`，第 6 条起永远看不到。
      现在默认 5 条 + 有更多时渲染「查看全部 N 条」（`error_book_show_all_btn`），
      展开后全部条目在限高 360 的滚动区（`error_book_scroll`），再点收起——
      每行是独立 `error_book_entry` QWidget（`_build_weak_entry`），
      隐藏用 `setVisible` 而非不渲染（测试可精确断言可见条数）；
    - **「我的作答」聚合回看卡**（`learner_view._build_my_answers_card`，
      `my_answers_card`）：错题本只留失败、且按概念去重——学习者写对的话就此消失。
      这里按 `history` 倒序取最近 6 条带 `answer` 的记录，渲染概念 + 通道 chip
      （复用 `breakdown_*` 静态键映射，`_channel_text` 渲染时查表）+ 分数 +
      90 字原话 + 「再答」（`my_answers_open` → `teach_requested`）。
      **纯 history 投影，零新存储**；无作答记录整卡不渲染（不硬造空卡）；
    - **自测题目可回看**：quiz 通道此前只记一个分数，学习者看不到"题目是什么、
      我选了什么、正确的是什么"。`teach_widgets.TeachResultView._check_quiz` 落
      `_quiz_last`（kind/question/given/expected），代码**语言中立**
      （`true`/`false`、1 起的选项序号 → `3 → 1 → 2`），换界面语言不改写历史；
      `teach_view._on_quiz_result` 把四字段平铺进 `record_evaluation(meta=...)`
      （`quiz_kind`/`quiz_question`/`quiz_given`/`quiz_expected`）；
      概念卡 `node_detail._append_quiz_miss`（`quiz_miss_title`）渲染最近一次
      带题目的自测错题对照（`quiz_miss_lbl`：题目 / 你的作答 / 正确答案），
      最近一次自测**通过则不渲染**（错题已解，不再反复提醒）；
      `_quiz_choice_label` 把 `true`/`false` 映射回当前语言按钮文案；
    - **阅读现场可见笔记**：`source_view` 概念工具条下新增笔记摘要带
      （`reader_note_box` / `reader_note_summary_lbl`）：选中概念时用
      `get_note` 渲染 `reader_note_summary`（70 字截断），超长给
      「展开/收起」（`reader_note_more`/`reader_note_less`，`reader_note_more_btn`）；
      无笔记整带隐藏；编辑保存后立即刷新（`_edit_reader_note` 调
      `_update_reader_note_summary`）——笔记不再"写完就消失"。
    规则：凡是学习者**产出**的内容（答案/实践/自测/笔记），都必须在产出地或
    聚合入口能原样回看；只显示分数等于让学习者无法回答"我错在哪/我写过什么"。

32. **死链接零容忍（第 16 轮扫描的收官口径，2026-10-23 落地）**：全仓库业务信号
    必须"有 emit 有 connect"，否则删除或接线——本轮修掉三处真实断路：
    - **答题/追问闭环（最严重）**：`TeachResultView.submit_requested` /
      `followup_requested` 只在 `_display_result` 内可达，而当初**忘了在那里接线**，
      `TeachView.on_submit_answer` / `on_followup` 全仓库零调用者——「提交答案」
      「追问」是画出来的死按钮，核心「答题→评估→掌握度」在 GUI 上整条断掉
      （测试全绿只因只覆盖 `practice_submit` 与 quiz 通道）。修复：`_display_result`
      两处创建点（普通课 + 快速自测）都接 `submit_requested` / `followup_requested`
      / `evidence_jump_requested`；答案经 **live view** 读取（`_on_submit_requested(view)`
      读 `view.answer_input`，绝不读缓存 QTextEdit——`setWidget` 会删旧控件）；
    - **图谱右键「查看证据」**：原复用 `concept_drilldown`，而该信号同时承担单击语义
      （`_handle_node_click` 也 emit），接线即劫持每次单击 → 新建专用
      `KnowledgeGraphView.evidence_requested`，`main._wire_graph` 统一为三处图实例
      （`_graph_view_ref`/`_teach_graph_ref`/`_dash_graph_ref`）接线，新增图面
      不可能再漏接；
    - **TOC 双击跳证据**：`knowledge_view.jump_evidence` 原是死声明 → 概念行
      `itemDoubleClicked` 触发（单击已开概念图，双击是显式"给我看原文出处"，
      行 tooltip `toc_row_tip` 说明）；main 接 `_on_jump_to_evidence`。
      **配套修复陈旧指针**：`on_nav_click("source")` 会 `SourceView.refresh()` 换新
      reader，而 `main._source_view_widget` 只在 `_build_source_view` 赋值一次——
      跳转落在已 `deleteLater` 的旧控件上（看着有反应、实际滚不动）。改为每次
      跳转后从 `source_view._source_widget` 重新绑定；
    - **删干净**：`teacher_rebuilt`（recheck 后各视图 refresh 时自读
      `main.teacher_models`，无需跨视图通知）、`favorite_toggled`（★ 已即时
      `toggle_favorite` + `save`，消费方本就直读 learner 状态）、`concept_drilldown`
      ——三者"有 emit 无消费者"，按仓库规则直接删除（不留兼容壳）。
      排查手段：grep 每个 `Signal(` 名字的 `.connect` 计数（PowerShell 5 的 `**`
      递归通配不可用，改用 Grep 工具）；回归 `tests/test_round16.py`（7 例）。

33. **资产生命周期闭环 + 标签单一事实源（第 17 轮扫描，2026-10-26 落地）**：
    - **资产删除入口（真实功能缺口）**：PySide 桌面端此前只能导入不能删除——
      `storage.delete_asset` 在 main.py 导入却零调用，仅 legacy flet 端有删除。
      侧边栏资产列表每行加 🗑（`_refresh_asset_list` 行容器化：资产按钮 stretch +
      删除按钮定宽 30，objectName `asset_delete_<aid>`，tooltip `asset_delete_tip`），
      确认框（`asset_delete_title`/`asset_delete_confirm`，含标题）后
      `_on_delete_asset`：storage.delete_asset（资产+教师模型文件）→
      `assets`/`teacher_models` pop → `learner.unregister_asset`（学习路径 /
      概念 sources / history 全清）→ save_learner_state → 当前资产被删时切换
      幸存者（空则 None）→ `_rebuild_all_views`。知识索引按签名自愈
      （`_assets_signature` 感知增删），无需显式维护；
    - **死信号第二轮**：`import_view.asset_selected`（`current_asset_id` 已直接
      赋值，信号冗余）、`group_quiz.completed`（关闭后 `_refresh_all_views` 已
      兜底）、`pyside_graph.view_changed`（有 emit 无消费者）、`view_manager` 的
      `concept_panel_requested`/`focus_graph_requested`（零发射零连接）与
      `refresh_requested`（有连接零发射）——按 §32 口径全删，不留兼容壳；
    - **异常类型标签归一**：此前同一组 kind 标签三处各自为政——
      `teacher._KIND_LABELS` 硬编码中文（仅 legacy 使用）、teacher_view 与
      panorama_view 各自重复 7 项 `kind_*` 字典、存疑条走内联动态查表。现统一为
      `teacher.kind_label(kind)`：**调用时**查 `i18n.t(f"kind_{kind}")`（模块级
      常量拼接会冻结语言，§8），未知 kind 回落原始码保持可读；教师页异常板 /
      全景关键未知 / 存疑条 / legacy 共用一处真相，新增异常类型只需加 i18n 键。
    回归 `tests/test_round17.py`（9 例）。
34. **异常状态闭环 + 死公共面持续出清（第 18 轮扫描，2026-10-26 落地）**：
    - **异常自动消解（证据驱动）**：`Anomaly.status` 四态词表（open/investigating/
      resolved/surfaced_to_student）此前"只进不出"——全库没有任何代码把异常置为
      resolved，已闭合的 learner_gap 会永远在存疑条/教学排序/coach 主张里喊狼来了。
      新增 `teacher.resolve_satisfied_anomalies(asset, teacher, state)`：掌握度回升至
      0.6（`GAP_RESOLVE_MASTERY`）的 learner_gap、证据已补齐锚点的 unanchored_source
      标记 resolved；材料级存疑（contradiction/logical_gap/surprising_claim）**永不自动
      消解**（系统不得自我说服）；概念匹配复用 `anomaly_concept_ids` 同名规则。
      接线两处：teach_view 三通道评估后的 `_check_review_gain_for`（与
      incorporate_review_gain_signal 同一同步点），`main.load_data` 启动懒修复
      （旧存档自愈，有变更才落盘）。resolved 自动退出 anomaly_concept_ids /
      concept_anomalies / 存疑条 / coach 异常主张——消费者本就按 status 过滤，
      零管道改动；
    - **术语表原文覆盖维度**：`terminology.terms_for_text`（公开后零生产调用）接入
      GlossaryDialog——对当前资产 source_text 做注册拼写匹配，每行标注
      「原文出现/原文未出现」（`glossary_occ_*` 键族，`t(occ_key)` 变量拼接，
      已登记 `DYNAMIC_PREFIXES`），未出现行降灰（模板条目仅供参考）；顶部增
      `glossary_occ_summary` 覆盖行（hit/total）。术语表从静态领域字典变成
      这份资产的词汇覆盖图；无领域/无原文时不标注（保持旧行为）；
    - **死公共面第三轮**：graph_viz 光栅导出管线（concept_map_png/_render/_arrowhead/
      _font/_wrap/_mastery_fill/_node_border + PIL 可选导入，约 180 行——现行导出走
      QGraphicsView 截图，HTML 报告自带 SVG，legacy flet 自绘 canvas 亦未调用）、
      prompt_registry.get_system_prompt/get_user_prompt（get_prompt 的零调用别名）、
      llm._llm_cache_stats 计数器与 llm_cache_stats()（零调用）——按 §32 口径全删；
      graph_viz 保留布局几何（_select_nodes/_layered_layout/_radial_layout/
      _border_point/hierarchy_neighbors + 盒型常量），pyside_graph 与 legacy 不受影响。
    回归 `tests/test_round18.py`（13 例）。
35. **消解可见 + coach 永不消失 + 死公共面第四轮（第 19 轮扫描，2026-10-27 落地）**：
    - **已消解异常上板**：r18 的 `resolve_satisfied_anomalies` 把异常置 resolved 后，
      教师视图异常板仍把它们当 open 卡渲染（`teacher_data['anomalies']` 是全量列表）——
      消解成果不可见且误导。现按 status 分区：open/investigating 保持可行动卡片
      （查看概念/去学它），resolved 移入「已消解 · N 条（教学已生效）」灰卡区——
      只读、灰徽标（`teacher_resolved_badge`）、消解原因按 kind 确定性派生
      （learner_gap→`teacher_resolved_reason_mastery` 掌握度回升，
      unanchored_source→`teacher_resolved_reason_anchor` 锚点补齐，其余 generic），
      与 resolve 函数的判定规则同源——正反馈环路闭合（§5 可发现性）；
    - **coach explore 边缘态修通**：全部掌握/无复习/无异常时 `_select` 兜底发
      `explore` 主张（无 concept_name），但 guide_bar 只放行 `import` 种无名主张——
      explore 被静默隐藏，违反 coach「可以降低音量，绝不消失」（§49）；且
      `_on_guide_start` 把无名主张一律路由导入页。现 guide_bar 放行
      import/explore 两种资产级主张，main 按 kind 路由（explore→概念网络，
      import→导入页），`coach_why_explore` 文案与动作对齐（去概念网络温故知新）；
    - **死公共面第四轮**（文本级全仓扫描，仅 def 行命中即删）：llm.clear_llm_cache、
      ViewManager.set_current/current_name/current_index/refresh_current/navigate_to
      + teach_requested 信号（main 只用 register_views + navigate_requested，
      r17 死信号审计漏网）、DomainTemplate.get_chapter_by_id、
      learner.get_study_goal（set_study_goal/study_goal_progress 在线）、
      i18n.init_lang/translate_option、MasteryDistributionBar.set_counts
      （重建式更新，无需 setter）、SourceTextView.scroll_to_text
      （scroll_to_concept 在线）、parsers.extract_from_base64（连带 base64 import）。
      另查明 legacy/ 4 处陈旧 import（expert_anything.ui.app 等）为历史遗留断链，
      非历轮删除引入，legacy 冻结不动。
    回归 `tests/test_round19.py`（13 例）。
36. **可读性优先：SVG 禁拉伸 + 下钻恒可用 + 首屏折叠 + 教学轻量化（第 20 轮 UX 修复，2026-10-28 落地）**：
    - **SVG 渲染铁律**：禁止裸用 `QSvgWidget` 直接展示图解——`QSvgRenderer` 默认
      `IgnoreAspectRatio`，会把 720×380 的 viewBox 拉伸填满 340×150 的控件矩形，
      文字被非均匀缩放压扁且有效字号约 6px（截图铁证）。统一用
      `_helpers.SvgScenePreview`：load 时设 `KeepAspectRatio` + `setHeightForWidth`
      （`heightForWidth = w/aspect`，布局永不压扁）+ 点击弹 `SvgZoomDialog`
      （尺寸不低于原生 viewBox，滚动查看）；`decoder` 场景文字最小字号托底
      （边标签 12px、类型徽标 10px）。三处嵌入面（概念详情迷你预览 / 节点卡预览 /
      教学分步播放器）全部改用该类，新增嵌入面照此办理。
    - **下钻恒可用**：旧 `drill_down` 只对有层级子节点的概念生效，绝大多数节点
      静默返回 False，用户感知为「只能看到相邻节点」。现 `drill_down` 对任意
      存在的概念恒成功（重建 2-hop 子图），`enable_drill_down()` 是主图的 opt-in
      （嵌入式小图保留双击开教），`drill_to(level)` 支撑可点击面包屑逐级回退；
      单击走 `QTimer.singleShot(0)` 与双击顺序安全共存。
    - **首屏折叠纪律**：一个视图首屏只留 2-3 个核心项，次级卡片进共享
      `CollapsibleSection`（▸/▾，隐藏非删除，一键可开）。已落地：概念图工具栏
      「更多工具」第二行、知识全景（快速拆解/主题簇/仪表盘图）、教师视图
      （已消解异常/笔记）、导入页指南卡（有资产时默认收起）、教学「想深入」。
      折叠区内的滚动目标先 `set_expanded(True)`（panorama `_scroll_to`）。
    - **教学轻量化**：工具定位是「快速阅读与理解」。教学页首屏 = 一页卡
      （核心定义 + 一个例子）+ 一张图解；完整讲解/术语/类比/步骤/测验/练习
      收进「想深入」。测验、练习、评估结果插入折叠区，且 `_expand_deep()`
      在用户主动要测验/练习/反馈时自动展开（防止块渲染在收起区里看不到）。
    回归 `tests/test_round20.py`（10 例）。
37. **小白视角减负：4 主入口 + 工具栏 5 控件 + 详情卡三折叠 + 首访提示条（第 21 轮，2026-10-30 落地）**：
    - **侧边栏只留 4 个核心入口**：认知地图 / 教学会话 / 导入 / 阅读原文常驻；目录大纲、
      学习者模型、教师模型、项目全景收进「进阶功能」`CollapsibleSection`（默认收起）。
      教师模型是系统内部自我理解层，不该与「开始学习」争夺同等视觉权重。
      **导航文案自带 emoji，代码禁止再拼图标**（曾渲染出「📊 🌳 目录大纲」双图标）。
    - **认知地图首行 ≤6 控件**：搜索 / 缩放组合（− 适应 ＋ 三连为视觉一组）/
      「展开子图」/ 面包屑 / 更多工具。`重置`、`返回上层`、范围切换（全部/当前资产）
      全部下移到「更多工具」第二行；删除常驻「双击节点 / 点击展开子图」醒目胶囊
      （它与显式按钮重复，且常驻提示属于信息噪声，discoverability 改由首访提示条承担）。
    - **节点详情卡首屏三折叠**：`NodeDetailCard.set_concept` 原平铺 14+ 段
      （关系/同级/下一级/难度/得分轨迹/错题/掌握度构成/复述/路径位置/前置/解锁/
      行动路径/术语/笔记/重放/证据/教师笔记），现首屏只留
      **标题+掌握度、定义、图解、操作按钮**，次级内容进三个折叠区：
      「关系与认知位置」「学习进展」「参考资料」。实现手法：折叠区内 `_append_*`
      共用同一 `self._layout`，故进入折叠区时临时把 `self._layout` 指向
      `CollapsibleSection.body_layout()` 再还原（隐藏非删除，全部能力一键可达）。
    - **首访提示条**：首次打开认知地图（有概念且 `data/.cm_onboarding_seen` 未写过）
      在工具栏下插入一条可关闭提示（搜索定位 / 单击看详情 · 双击深入子图 / 选中后开教），
      关掉即落盘标记不再弹。**刻意不用模态遮罩**：遮挡打断视线、测试里还会阻塞点击。
    - **术语去黑话**：`stat_unanchored` 无锚概念→无原文出处；`stat_anomaly` 异常→待澄清疑点；
      `llm_ready` LLM 已配置→智能分析已开启；`nav_knowledge` 知识模型→目录大纲
      （与「认知地图」区分：地图=概念网络，大纲=目录/清单）。
    回归 `tests/test_ui.py::TestRound21BeginnerSimplify`（5 例）。
38. **系统内部机制下线 + 领域模板说人话（第 22 轮，2026-10-30 落地）**：
    - **AutoHarness 卡片整体下线**：演化卡（琥珀/紫/青）、跨资产迁移卡（浅蓝）、
      演化历史审计块全部从教学结果视图移除（`teach_widgets.append_harness_*`、
      `TeachView.harness_adopted/harness_transferred`、`_attach_harness_history` 删除）。
      学习者路径改为**静默执行**：卡壳信号仍跑 `evolve_joint`（或迁移候选差分评估），
      命中的候选直接持久化 harness_state.json + 落审计链，并把实时讲解风格
      切到候选 style（`_nudge_style`，`blockSignals` 避免覆盖学习者偏好）——
      无弹窗、无技术措辞，唯一可见效果是下一次「换个讲法」落到新风格。
      会话级去重保留：联合 `(asset, concept, reason, candidate)`、迁移
      `(target, source, spec)`，已展示源跳过重复差分评估。
    - **领域模板确认框去技术腔**：标题「领域模板」→「专业知识包」；提问不再报
      「命中 10/19 个模板概念（覆盖率 53%）」，改为「收录了该领域 N 个标准概念，
      可补充专业释义、学习路径更贴合这一领域」；结果不再报命中数/覆盖率，
      只报「为几个概念补充了释义」+ 降级原因人话版（对不上/太少/暂无/条件不满足）。
      三语同步；`domain_template_reason_*` 属动态家族，改名不改键。
    回归：`tests/test_ui.py::TestLessonResultUI`（静默采纳/去重 2 例）+
    `TestImportExperience` 文案断言 2 例改写。
39. **术语去技术腔扫尾（第 23 轮，2026-11-02 落地）**：学习者可见文案里的
    工程词全量替换，三语同步，键名不动：
    - 「锚点」→「原文出处/证据出处」：`legend_unanchored`、`unanchored_tip`、
      `panorama_frontier_unanchored/none`、`teacher_anchor_rate`（证据锚定率→
      证据定位率）、`teacher_unanchored_list/anomaly`、`teach_unanchored_warn`、
      `kind_unanchored_source`、`due_unanchored`、`reader_focus_hint`、
      `focus_badge/no_match`、`teacher_resolved_reason_anchor`。
    - 「LLM」→「智能分析」：`method_llm(_chunked)`、`kind_needs_llm`、
      `teacher_status_fallback/failed`、`teacher_explain_body`、`recheck_needs_llm`、
      `dash_fallback_warn`、`build_needs_llm`、`external_no_llm`、`ext_llm_failed`、
      `teacher_no_llm_skip/anomaly`（保留环境变量名 EXPERTANYTHING_LLM_API_KEY）、
      `ext_llm_fallback/no_llm`、`ext_chunks_failed`；core 层答题反馈
      「未接入 LLM」→「智能分析未开启」（tutor.py 两处兜底评估语）。
    - 其他：`method_fallback`「确定性降级/确定性模式」→「基础模式」；
      `breakdown_harness`「harness」→「教学方式」；`audit_title`「轨迹审计」→
      「学习轨迹明细」；「领域模板」残留（terminology_source_note、glossary_empty、
      glossary_occ_no_tip、profile_reason_no_template）→「专业知识包」；
      teacher.py 对比沉淀「对比锚点」→「对比关联」（数据内容，同步 test_core）。
    回归：`tests/test_report.py` 4 例断言改写 + `test_core.py` 4 例断言改写，
    quick 802 例 0 失败。
40. **i18n 重复键清理（2026-11-02 落地）**：`_STRINGS` 表历史累积 6 对重复定义
    （Python dict 后定义静默覆盖先定义——运行时零影响，但先定义是误导翻译与
    评审的死文本）：`recommend_next`、`method_llm`、`method_fallback`、
    `import_done`、`evidence_label`、`learn_next`。逐对核对两版内容后删除
    先定义（保留实际生效的后定义），键表 851→845。
    `tests/test_i18n_integrity.py` 新增 `test_no_duplicate_key_definitions`
    常驻守卫（AST 解析 `_STRINGS` 字面量，兼容 Assign/AnnAssign，
    重复键=回归），防复发。
41. **文案残留收尾 + 文档对齐（第 24 轮，2026-11-02 落地）**：第 23 轮漏网的
    3 处技术腔清理（键名不动、三语同步）：
    - `compare_incorporated`「共享锚点/anchors/共有アンカー」→「共享关联点 /
      shared links / 共通のつながり」（与 teacher.py「对比关联」口径一致）；
    - `llm_not_ready_detail`「未配置模型服务 + 确定性回退 + 教师自检」→
      「未开启智能分析 + 简单处理」，三语去掉 deterministic fallback 说法；
    - `teacher_no_llm_anomaly` 不再向学习者暴露环境变量名
      `EXPERTANYTHING_LLM_API_KEY`（异常文本留排障信息，UI 文案不带）；
    - 顺带统一 `llm_ready` / `teacher_no_llm_skip` 的英/日术语为全表口径
      （AI analysis / AI 分析）。
    文档对齐：AGENTS.md 长期演进第 1/2/5 条划掉（SourceLocation、Prompt 三语、
    追问沉淀均已落地，注明落点），第 6 条更新为四个领域包（电力交易 / 碳市场 /
    可再生能源预测 / 分布式能源）；`docs/Knowledge_Decoder.md` 删除
    「待 SourceLocation 落地后补强」的过期括号。
    回归：`tests/test_ui.py::TestImportExperience` 首屏断言同步改写
    （「确定性 / 配置」→「智能分析 / 仍可导入」），quick 803 例 0 失败。
42. **文案口语化（第 25 轮，2026-11-02 落地）**：把剩余的书面/统计腔改成人话，
    键名不动、三语同步（英文/日文的 coverage / カバー率 属自然表达，保留）：
    - 学习者画像：`profile_domain_item(_short)`「判定 / 依据」→「水平 / 原因」；
      `profile_reason_no_data`「无法判定」→「暂时看不出来」；
      `profile_hint_unknown`「即可判定」→「就知道了」。
    - 术语表：`terminology_matched`「命中」→「对应」；
      `glossary_occ_summary`「原文覆盖」→「原文里提到」。
    - 复述自检：`recall_btn_tip/hint/coverage/all_covered/record_tip/status/trend_tip`
      的「覆盖度/覆盖了多少」→「讲到了多少 / 讲到了 {pct}% 的要点 / 复述成绩」；
      按钮 `recall_check`「检查覆盖度」→「看看讲得怎么样」（`recall_empty` 同步）。
    - 导入：`import_stage_parse`、`import_extracted_concepts`、`ext_analyzing`、
      `ext_done`、`ext_chunks_done`「抽取」→「整理 / 提取」；
      `ext_llm_fallback`「智能分析抽取失败」→「智能分析没有成功」；
      `method_llm`「智能分析抽取」→「智能分析」；`method_llm_chunked`「分段抽取」
      →「（分段处理）」。
    - 其他：`topics_title`「主题聚合」→「主题分组」、`topics_hint`「聚类」→「分组」；
      `focus_badge`「命中 / 证据出处」→「找到 / 原文出处」。
    回归：`tests/test_report.py::test_localize_method` 断言同步为「智能分析」，
    core + report + i18n 154 例通过；三语占位符校验 0 不一致。
    顺带堵住一处机制泄漏：`auto_harness.apply_to_learner` 回写学习轨迹时不再写
    `answer="harness 会话"`（自动演练不是学习者手写回答，会混进「我的回答」卡片），
    改为空回答；feedback 兜底文案从「AutoHarness 会话完成（spec/metric=value）」
    改为「本课演练完成（掌握度 N%）」——内部指标仍完整保留在 meta 审计字段。
43. **通道/状态文案去技术腔（第 26 轮，2026-11-02 落地）**：
    `mastery_breakdown_tip`「按学习通道拆解」→「掌握度从哪来的」；
    `score_trail_tip`「历次评估得分（复习通道）」→「历次成绩（↺ = 复习那次）」；
    `audit_col_channels`「学习通道」→「学习方式」；通道/评估/得分三语对齐，
    内部 `channel` 字段名不改。回归：core + report + i18n 154 例通过；
    三语占位符 0 不一致。全量 quick 803 例 0 失败。
44. **统一视觉语言（第 27 轮，2026-11-03 落地）**：界面从"传统桌面软件"收敛为
    扁平现代风格，规则对新代码是硬约束——
    - `expert_anything/ui/theme.py` 是**唯一色板/字号/圆角/尺寸真相源**；
      新增语义色先进 theme（禁止在视图里新写 `#RRGGBB`），视图只引用 token
      或 `primary_button_style()/secondary_button_style()/page_header_style()`。
    - Qt 的 `#RRGGBBAA` 会被读成 `#AARRGGBB`（旧 `{color}20` 写法会渲染成随机绿色），
      半透明一律用 `theme.rgba(hex, alpha)`。
    - `border-left: 3px solid <彩色>` 在本 Qt 版本会把颜色刷满整圈四边——
      语义用标题/徽标色表达，卡片一律中性 1px 边框。
    - 页头统一 `PageHeader`（`QSizePolicy.Vertical Fixed`，否则被 QVBoxLayout
      拉伸成"标题占半屏"）；导航只留侧栏，顶栏不再重复放快捷入口（三重入口是拥挤根因）。
    - 侧栏浅色（`SURFACE` + `BORDER` 右边框），导航文字左对齐、无装饰 emoji
      （`_nav_label` 语义：i18n 文案仍可带 emoji，壳层剥掉）。
    - 滚动/资产列表等动态布局结束必须 `addStretch(1)`，否则行被均匀撑开；
      卡片内禁止 `addStretch()`（富余空间会把卡片撑成空心大框）。
    回归：全量 quick 通过（含 5 例新增 UI 断言）；截图自检脚本只在临时目录，
    不写入工作区。
45. **关系语义可读性（第 28 轮，2026-11-03 落地）**：把图谱从"一堆连线"推进到
    "每条线可解释、可验证、可追溯"，三个改动是同一条链路的不同环节——
    - **关系证据恢复（core/extraction.py）**：`_recover_relation_evidence` 在 LLM
      证据非逐字时，只接受"同一句同时点名两端"的句子作为证据；找不到仍丢弃
      （来源约束不放松）。`_canonical_relation_type` 把自由 type（prerequisite/
      causes…）收敛进六类；跨块重叠按 (源,目标,语义) 去重，contrast 视为无向
      （A↔B 与 B↔A 只留一条）。痛点：分块抽取的重复边与轻微改写的证据会让图谱
      变稀疏或重复，六类语义退化成"全是前提"。
    - **边方向（ui/pyside_graph.py）**：`_place_edge_head` 按 `REL_SEMANTICS["arrow"]`
      在目标端画标记（normal 三角 / diamond 菱形贴整体端 / none 无向），颜色与
      方向共用同一份语义表；context/path/focus 覆盖色只改颜色、不改方向。图例
      新增 `legend_direction` 解释。痛点：主图边此前是无向直线，方向只能靠猜；
      教学小图早就有箭头，两处不一致。
    - **边详情卡（ui/widgets/node_detail.py::set_relation）**：点边不再弹
      "要不要教"，右侧卡显示 源→目标、六类徽标、白话方向句（`rel_gloss_*`）、
      逐字原文证据 + 行号 + 「在原文里确认」（复用 evidence_jump_requested）；
      无证据时区分"路径相邻"与"模型归纳"；两端都可一键开教。痛点：Relation.evidence
      此前从未在 UI 露出，§4「点击必须产生更深层细节 + 证据可溯源」在关系层缺失。
    回归：全量 quick **807 例 0 失败**（core 643 + data 7 + ui 155 + runner 2；
    完整含 llm 为 819）。
46. **演示关系证据逐字化（第 29 轮，2026-11-03 落地）**：演示资产的关系从"模板说明"
    升级为"可切回原文的证据"，生成器与守卫同轮落地——
    - **生成器（regen_all.py::build_asset_from_template）**：先写 `source_text`，再取证据。
      概念章节之后追加两段——`## 学习顺序`（quick_path 相邻概念，每边一句
      `学习顺序上，先掌握「A」，再进入「B」。`）与 `## 关系速览`（`_SEMANTIC_HINTS`
      精选语义句，每句逐字点名两端）。每条 `Relation.evidence` 就是这两段中的**整行**，
      不再出现"模板推荐学习路径……"之类说明；`created_at` 固定为 `DEMO_CREATED_AT`，
      method 升 v2，重复生成结果确定。teacher 文件另把 `synthesized_at` 与 uuid 异常 id
      归一化为固定值（`teacher_dict_for`），因此连续两次 `regen_all.py` 的所有 JSON
      逐字节相同（已实测）。
    - **定位规则**：`core/extraction.py::_stamp_locations` 为每条关系写入
      `Relation.location = SourceLocation(char_start, char_end, line, snippet, page)`；
      关系卡优先读 `relation.location`（行号/偏移即生成期记录），仅对旧资产回退
      `source_text.find(evidence)`。`models.Relation` 的 `location` 随 to_dict/from_dict 持久化。
    - **语义与可读性**：保留 prereq 主线，每个资产至少再覆盖两类语义（本轮实际为
      prereq + part_of + contrast + causes，DER 为 prereq + is_a + contrast + causes）；
      contrast 无向；同一端点对只保留一条边（与前置链撞对的候选直接舍弃，避免双线重叠）。
    - **生成期断言**：概念 id 必须存在、证据必须是 `source_text` 的唯一整行、标签必须
      单独可读出声明语义（`classify_relation(label, "") == type`）、类型数 ≥3 且含 prereq；
      不满足即抛错，跳过的 hint 会打印原因（不静默降级）。
    - **守卫（tests/test_demo_data.py 新增 4 例）**：证据是整行且不含模板/演示说明；
      `location` 切片必须等于证据且行号与偏移自洽；每资产 prereq + ≥2 语义且标签可读；
      端点对唯一。`tests/test_core.py` 追加断言：关系锚点可切片、可序列化往返；
      `tests/test_ui.py::TestSource.test_unanchored_concept_mark` 显式关闭 skeleton 模式
      （全局全景会把骨架态带进单资产视图，旧断言依赖 c002 恰好被骨架选中）。
    - **改动范围**：`regen_all.py`（生成器 + 常量 + hints）、`data/_demo/assets/*.json`
      （4 资产重生成：002 19 概念/10 关系、003 13/9、004 14/10、005 14/10）、
      `expert_anything/core/models.py`（Relation.location）、
      `expert_anything/core/extraction.py`（关系锚点）、
      `expert_anything/ui/widgets/node_detail.py`（优先用 location）、
      `tests/test_demo_data.py`（+4）、`tests/test_core.py`（断言补充）、
      `tests/test_ui.py`（skeleton 前置）。QUICKSTART 的手写导入样例
      `data/_demo/electricity_trading_asset.json` 不参与重生成（其 name-mapping /
      场景契约另有测试），本轮不改。
    - **样本地位（勿误读）**：`data/_demo` 资产的 `source_text` 由 `regen_all.py`
      生成，不是真实语料；其「逐字证据」只证明**溯源机制自洽**，不等同于真实文档
      抽取质量已被验证。真实语料结论见第 47 条。
    回归：全量 quick **811 例 0 失败**（core 643 + data 11 + ui 155 + runner 2；
    完整含 llm 为 823）；i18n 完整性守卫 5 例通过。
47. **真实文档抽取质量实测与三项修复（第 30 轮，2026-11-03 落地）**：首次把抽取
    质量指标落在**仓库内的真实文档**上（不是演示资产）。可复现口径：
    `python verify_extraction_quality.py`（确定性，不需要 LLM；本机 Vulkan 端点的
    语义层实测见第 48 条）。真实样本 6 份：
    `docs/电力交易领域学习方案.md`、`docs/AutoHarness_Strategy.md`、
    `docs/Knowledge_Decoder.md`、`docs/OmniScientist_Inspiration.md`、`README.md`、
    `docs/_omniscientist_text.txt`（PDF 抽取文本）；另有真实 EPUB
    `docs/Embodied-Intelligence.epub`（446K 字符）。
    - **三指标实测（修复前 → 修复后）**：结构边召回 **0/61 → 61/61**（修复后精确率
      同为 61/61；修复前仅有 6 条结构边，且全部来自伪标题，精确率 0）；概念证据
      可定位 **88/98 = 89.8% → 76/76 = 100%**；唯一锚点 **77/98 = 78.6% →
      76/76 = 100%**；伪标题概念 **16 → 0**；六类语义单元命中 **26/27 → 27/27**
      （旧代码唯一错分：`属于…的一部分` 被判成 is_a）。EPUB 唯一锚点
      493/532 → 523/532（结构边数原本已由「第 N 章」+语义标题产生，不受影响）。
    - **根因与规则（三条，均不放松来源约束）**：
      1. **标题识别与层级保真**：旧代码把 `#`/`##`/`###` 一律当 level 0，文档树被
         抹平 → 结构边永远为 0（`.md` 最常见导入格式）。改为 `level = #数量 - 1`；
         并排除三类"假标题"——代码围栏内的 `#`（shell 注释曾变成 13+3 个伪概念）、
         以冒号结尾的引导行（`关键观测：`/`**分层覆盖**：`）、纯标点分隔行（`---`）
         与 `>`/`|` 引用表格行。结构关系的 `evidence` = 产生该边的**标题整行原文**
         （如 `## 细节`），不再用剥掉 `#` 的标题名（后者与正文撞词，锚点会指到正文行）。
         证据仍是逐字原文，未放松。
      2. **证据必须是逐字且唯一的切片**：无标题文本（PDF 抽取）旧代码把 3 句用
         空格 join 成块 → `text.find` 全部失败（`_omniscientist_text.txt` 0/10
         可定位）；改为按句子字符偏移从 `text` 直接切片。标题后证据行若全文多次
         出现（README 的 `python run_tests.py` 6 次、` ```powershell ` 围栏行），
         跳过围栏标记并向下扩 1–3 行直到切片唯一；仍不唯一时保留首个切片（不造证据）。
      3. **语义分类最长模式优先**：`classify_relation` 旧逻辑按类别顺序返回首个
         命中，"属于…的一部分"先命中 `属于`(is_a) → 改为最长匹配优先，长短语
         不再被短词遮蔽。仅此一处改动。
    - **取舍（明确未做）**：① 结构边字段仍写 `type="contains"`（非六类）——它是
      父→子专用的结构标记，`graph_viz.structural_only` / `hierarchy_neighbors` /
      learner in-degree 都依赖该方向；六类里的 `part_of` 是子→父，改名须翻转方向
      并同改 5 处消费点，属连带重构、收益只是字段洁癖，本轮不做
      （`classify_relation` 已把它归一为 `part_of`，展示层 100% 六类）。
      ② LLM 闸门 `_recover_relation_evidence` 对结构边实测 **0/61**：它要求同一句
      点明两端，而标题层级天然只有子标题；要恢复只能新增"文档树结构验证"第二条
      规则，违反"能一条解决的不用两条"，留作已知缺口（确定性路径不经该闸门，
      不受影响）。③ 真实 EPUB 仍无 h1–h3 层级信息（parser 只保留文本块），
      其结构边来自「第 N 章」而非 HTML 标题级别——需要 parser 编码标题级别才能
      继续提高，本轮不动。
    - **测试**：`tests/test_core.py` +7（md 层级 / 结构证据整行可切片 / 围栏 `#`
      非标题 / 纯文本证据逐字可锚定 / 重复行扩到唯一切片 / 证据不可是围栏标记 /
      冒号引导行非标题）；`tests/test_decoder.py` +3（最长模式优先 / 六类直通 /
      自由 type 折叠）。
    回归：全量 quick **821 例 0 失败**（core 653 + data 11 + ui 155 + runner 2；
    完整含 llm 为 833）；i18n 完整性守卫 5 例通过。
48. **本机 Vulkan 端点接入与语义层实测（第 31 轮，2026-11-03 落地）**：本轮不再需要
    外部 key——把 `EXPERTANYTHING_LLM_*` 指向本机 llama.cpp，**实测语义关系产出、
    证据通过率、闸门漏边形态与稳定性**；全部数字与第 47 条（结构层）**分开**统计。
    - **端点与后端确认（如实）**：`Test-NetConnection` 扫 1234/8000/8080/8081/8083/
      8090/11434 均无监听，唯一在听的是 **8082**。该 llama-server（build
      `b11583-988015788`）进程已加载 `ggml-vulkan.dll` + `vulkan-1.dll`，
      `llama-server --list-devices` 输出 `Vulkan0: Radeon 8060S Graphics
      (48971 MiB, 46522 MiB free)` → **确实是 Vulkan 后端**，不是 CUDA/CPU。
      机器上另有旧 CPU 进程（`--device none -ngl 0`，8085，未监听），与本轮无关。
    - **模型与参数**（`/v1/models` + `/props`）：`Qwen3.6-35B-A3B-Q4_K_M`，alias
      **`qwen3.5-35b`**（客户端固定名，勿改），量化 `Q4_K - Medium`（19.71 GB），
      `n_ctx=16384`，`total_slots=1`。启动用 `-rea off` 关思考链
      （`--reasoning-budget 0` 在本机版本报 `invalid type: string "true", expected
      a boolean`；不关则思考链吃满 `max_tokens`，返回空 content）。
    - **性能**（`verify_semantic_extraction.py --benchmark`）：短请求 TTFT
      0.18–0.24s，生成 32–43 tok/s，流式 decode 60.7 tok/s；3946 prompt tokens 的
      9000 字符 chunk 端到端 147s / 4354 输出 tokens（≈29.6 tok/s）。
    - **可复现命令**：`python verify_semantic_extraction.py --benchmark`；
      `--runs 2`（默认 2 份真实文档：`docs/电力交易领域学习方案.md`、
      `docs/AutoHarness_Strategy.md`）。脚本强制 `EXPERTANYTHING_LLM_CACHE=0`
      （否则稳定性恒为 1.0）、温度 0、`max_concurrency=1`，并 monkeypatch
      `_call_extract`（温度/上限）与 `_assemble`（包裹后只做审计，不改生产代码）。
    - **四项测量（真实文档，第 1 轮 vs 第 2 轮）**：
      * 产出量与六类分布：电力交易 28681 字符 → 37 概念 / **8 条语义边**
        （prereq 4、part_of 2、related 2）；AutoHarness 30504 字符 → 40 概念 /
        **14 条**（prereq 6、causes 5、contrast 2、related 1）。**没有退化成全
        prereq**（prereq 占 50% / 43%），但绝对量稀疏（≈4.5 条/9000 字符 chunk）。
      * 证据通过率（`_recover_relation_evidence` 之前的逐字校验 + 同句恢复）：
        电力 8/18 = **44.4%**（逐字 6 + 同句恢复 2）；AutoHarness 16/26 = **61.5%**
        （逐字 7 + 同句恢复 9）。
      * 闸门拒绝形态：`no_span_names_both`（原文无同句同时点名两端：别名/指代/
        跨段）电力 **8** / AH **3**；`endpoint_not_grounded`（端点概念未通过逐字
        锚定）电力 **2** / AH **7**；重复 **0/2**；空证据 **0/0**；自环 **0/0**；
        类型不合法 **0/0**（`classify_relation` 六类归一后无越界，LLM 原始
        `type` 也 0 条 off-schema、0 条缺失）。
      * 稳定性（Jaccard，温度 0、同一文档 2 次）：AutoHarness 边 **1.00** / 概念
        **1.00**；电力交易边 **0.11** / 概念 **0.54**（8 边 vs 12 边）。同一 prompt
        在本机 Vulkan 上重复调用得到 381/403/6579/8951 字符不等 → **后端推理本身
        不确定**，温度 0 不等于可复现；该文档的语义图在两次运行间几乎不重叠。
    - **自洽性指标（不需要金标）**：闸门放行的 24 条候选中，证据点名两端 16、
      只点一端 4、两端都不点 4；最终接受 22 条（2 条同 `(source,target,type)`
      重复被去掉）。接受边的证据**全部可唯一定位**（非唯一锚点 0/22），类型合法率
      **100%**。但电力文档 8 条接受边里有 4 条证据是 `QUICK_PATH = [...]` 这类
      代码行——锚定成立、**并不支撑该边**。这些都只证明"内部自洽"，**不是准确率**。
    - **端点缺陷（实测，未改生产代码）**：① `response_format={"type":"json_object"}`
      （llama.cpp JSON grammar）使本模型在**第一个概念后即 EOS**：163 tokens、
      无 `relations` 键，mt 4096/2048/不限 3 次一致；生产 `chat_json` 恒设
      `json_mode=True` → `_call_extract` 返回 `{}` → `extract_knowledge` 静默降级
      `llm_failed_fallback_v1`（1/1 复现）。测量改走 `json_mode=False` + 容错解析
      （`VERIFY_JSON_MODE=1` 可复现生产行为）。② 模型会在字符串内输出未转义引号
      （`知识"解译"成图像`），`json.loads` 在第 213 字符失败，生产 `parse_llm_json`
      不修复；测量只做**引号转义修复**（不改写内容，证据仍逐字可核），
      `Knowledge_Decoder` 因此解析出 16 概念 / 9 关系。③ 生产 `max_tokens=1500`
      对 9000 字符 chunk 不足（实测 3734 字符处被截断，JSON 不完整），测量用 8192。
    - **待人工复核清单（非金标）**：`docs/semantic_relation_review.md`（脚本自动
      生成），电力 18 条（8 接受 + 10 被拒）、AutoHarness 20 条（8 接受 + 12 被拒），
      覆盖别名/指代、跨段/跨行、列表项、长跨度、被闸门拒绝的难例；每条给类型、
      label、证据前 120 字、行号与字符偏移，判断列留空给人填。**没有人工标注前
      不得声称"准确率"**。
    - **仍未解决**：语义边总量偏低（模型每 chunk 只给 4–5 条关系）；电力文档
      Jaccard 0.11 说明本机 Vulkan 下语义图不可复现；`json_mode` 与 `max_tokens`
      两项生产默认值在本机端点上不可用（需按端点做能力探测后才能安全改写）；
      `no_span_names_both` 的 11 条漏边需要"跨句/别名解析"第二条规则，本轮不做。
    - **本轮修复（第 32 轮，2026-11-03）——消除静默降级**：三个候选落地两个半：
      ①端点能力探测 + 显式降级（完整）、②按长度动态 `max_tokens` + 截断重试（完整）、
      ③容错解析 + 确定性（解析与 seed/并发落地，**「每次跑两遍取并集」未做**——
      成本翻倍，仅在第 31 轮做过一次性稳定性实验，不作为默认）。
      * **探测**：`LLMClient.probe_json_mode()` 发一次极小请求判定
        `supported / unsupported / timeout / unknown`，结果按 `(base_url, model)`
        缓存 `EXPERTANYTHING_LLM_PROBE_TTL` 秒（默认 600；0=每次探、负=永久）；
        超时/异常一律 fail-safe 走不带 `response_format` 的容错路径，
        **探测本身绝不阻塞正常请求**；`EXPERTANYTHING_LLM_JSON_MODE=on|off` 可强制。
      * **禁止静默 fallback（三处可见）**：`logger.warning` 带原因、
        `asset.method="llm_failed_fallback_v1"`、新增 `KnowledgeAsset.provenance`
        （随资产持久化，含 `source/llm/explicit_fallback/fallback_reason`），
        UI 降级提示条追加「降级原因：…」（新 i18n 键 `dash_fallback_reason`，三语）。
        正常路径同样写 provenance：`source=llm_extraction(_chunked)_v1`、`json_mode`、
        `json_mode_capability`、`attempts`、`finish_reasons`、`parse_repairs`、
        `truncation_retries`、`truncated_partial`、`temperature`、`seed`；
        chunk 路径另有 `chunks_total/chunks_failed/chunk_failures[].reason`。
      * **动态预算**：`_output_budget = clamp(len(chunk)*0.55 + 600, 1024, 8192)`
        （9000 字符 chunk ≈5550，取代固定 1500）。截断（`finish_reason=length`
        或括号未闭合）触发一次 ×1.7 重试（上限 8192），**同时把 `json_mode` 关掉**
        ——第 31 轮实测该端点 `response_format` 会让长输出提前停；重试仍失败则保留
        已闭合并通过形状校验的部分结果（标 `truncated_partial`），绝不返回空。
      * **超时随预算放大**：`timeout = max(client.timeout, budget*0.05)`（默认 20 tok/s
        下限）。第 31 轮的固定 60s 会掐死合法的 2340-token 生成（实测 ≈70s），
        导致 5 次重试全超时后才降级——本轮 E2E 复现并修掉（同属端点能力问题）。
      * **容错解析**：`parse_llm_json` 拆出 `parse_llm_json_detailed`，依次尝试
        去围栏 → 取最外层对象 → **未转义引号转义** → 补齐截断的 `"`/闭括号 →
        去尾随逗号；只改语法，不改字符串内容（证据仍逐字可核）。
      * **确定性**：抽取温度默认 0（`EXPERTANYTHING_EXTRACT_TEMPERATURE`）、固定
        `seed=0`（`EXPERTANYTHING_LLM_SEED`）、默认 `max_concurrency=1`
        （`EXPERTANYTHING_LLM_MAX_CONCURRENCY`），chunk 池随之串行；
        可复现性元信息（temperature/seed/并发效果）写进 provenance。
    - **六类降级情形测试**：`tests/test_llm_endpoint.py`（离线、无需 key、16 例）——
      ①json_mode 可用 ②不可用（HTTP 400）③探测超时 ④JSON 截断后加预算重试
      ⑤非 JSON 显式报错（不再伪造 `{}`）⑥未转义引号修复且内容逐字不变；
      另含探测缓存、形状降级、动态预算、成功/降级两条 provenance 契约。
    - **端到端验证（生产路径，本机 8082，非测量脚本）**：
      `docs/Knowledge_Decoder.md` 3067 字符 → `method=llm_extraction_v1`、
      **13 概念 / 3 关系**（causes 1、prereq 2），证据逐字 **3/3**；
      provenance：`llm=true, explicit_fallback=false, json_mode_capability=supported,
      attempts=2, finish_reasons=["length","stop"], truncation_retries=1,
      json_mode_downgraded=true, temperature=0, seed=0`。
      `docs/电力交易领域学习方案.md` 19333 字符（3 chunk）→
      `method=llm_extraction_chunked_v1`、**26 概念 / 8 关系**
      （related 4、prereq 2、part_of 1、contrast 1），证据逐字 **8/8**，556s；
      provenance：`attempts=5, max_tokens=8192, finish_reasons=["length","stop"×4],
      parse_repairs=["closed_braces","stray_quotes"], chunks_failed=0,
      truncated_partial=false`。第 31 轮那条「必掉 `llm_failed_fallback_v1`」的路径
      在两份文档上都不再发生：第一次带 `response_format` 的调用被 `length` 截断后，
      同一次抽取内自动降级并完成。
    - **本轮仍未解决**：探测只能证明端点「接受」`response_format`，无法证明长输出
      语义质量——本机端点上它仍会因 grammar 提前停（所以首调要浪费一次截断重试，
      约 30–60s）；想要更快可显式设 `EXPERTANYTHING_LLM_JSON_MODE=off`。语义边仍
      稀疏（chunk 级 3–5 条），固定 seed + 并发 1 只能**减少**不能消除 Vulkan 后端
      非确定性（Jaccard 抖动仍在）；没有人工金标，仍不声称准确率。

    - **本轮修复（第 34 轮，2026-11-03）——端点能力从「每次探测」升级为持久化档案**：
      三个候选全部落地，并根据 E2E 实测补了一项「预算记忆」（见下，不是无关扩展：
      本机端点那次必败的重试实际是预算不足，不是 grammar）。
      * **能力档案（核心）**：`data/llm_capability_profiles.json`
        （`EXPERTANYTHING_LLM_PROFILE_PATH` 可改路径），原子写（`.tmp` + `os.replace`）。
        格式 `{"schema_version": 1, "profiles": {"<base_url>|<model>": {...}}}`，每条含
        `base_url/model/first_seen/last_confirmed/probe_count/last_probe_status/
        last_probe_detail/json_mode_supported/grammar_early_stop/early_stop_observations/
        min_output_tokens`。命中顺序：**档案 → 进程内探测缓存（600s）→ 实探**；
        命中时不发探测请求，`EndpointCapability.source="persisted"`。
        TTL `EXPERTANYTHING_LLM_PROFILE_TTL`（默认 7 天，按 `last_confirmed`）；
        `base_url`/`model` 变化即换 key（旧条目自然失效）；`schema_version` 不匹配、
        JSON 损坏、不可读一律 `logger.warning` 后按空档案继续探测——**绝不因缓存
        损坏让抽取失败**。**只有 definitively supported/unsupported 的探测结果才落盘**，
        超时/unknown 只进内存缓存，避免一次网络抖动把 json_mode 关 7 天。
        探测次数 `probe_count` 每次落盘 +1。
      * **重置方式**：①删文件；②`EXPERTANYTHING_LLM_PROFILE_RESET=1`（进程启动时
        清空并删文件）；③代码 `reset_capability_profiles()`。**何时该重置**：更换
        推理后端/量化/启动参数（如换 build、开/关思考链）、升级模型但 alias 没变、
        端点为云服务且其能力升级、或档案里出现陈旧的 `grammar_early_stop` 而实测
        已正常——换 alias 或 base_url 更干净（等于新 key）。
      * **grammar 提前停识别规则（写死在这里）**：仅当调用方声明了 `require_keys`
        且带预算时判定；满足「**输出极小**」——有 usage 时 `completion_tokens ≤
        max(256, 15%×max_tokens)`，无 usage 时字符数 `< max(900, 50%×预算字符容量)`
        ——并且「**结构不完整**」：缺任一 required 键（**不看 `finish_reason`**：
        llama.cpp 的 grammar 常常产出合法 JSON 后以 `finish_reason="stop"` 结束，
        只看 `length` 会永远学不到），或截断后只完成 1 个 concept。反例：真正
        「输出太长」的截断会**用满预算**（`tokens≈max_tokens`）且保留 `concepts/
        relations` 键 → 不记忆；小而**schema 完整**的回答（1 个概念 + `relations: []`）
        也不记忆。命中后写 `grammar_early_stop=true`、`early_stop_observations+1`，
        下一次同一端点 `resolve_json_mode` 直接返回 `json_mode=False`（`source=persisted`）。
      * **一次性说明**：首次记录时 `logger.warning` 一条；之后 `resolve_json_mode`
        命中 grammar 档案时 `logger.info` **每端点每进程仅一次**（`_notice_emitted`），
        不刷屏；日志里给出重置方式。provenance 另含 `grammar_early_stop`。
      * **预算记忆（E2E 驱动）**：schema 完整成功时把当时的 `max_tokens`
        记入 `min_output_tokens`（单调不减），`_call_extract` 起始预算 =
        `max(动态估计, min_output_tokens)`。`EXPERTANYTHING_LLM_MAX_TOKENS_CEILING`
        仍封顶 8192；来源逐字约束、六类闸门完全不受影响（只改请求预算）。
      * **可观测**：`KnowledgeAsset.provenance.json_mode_source =
        persisted|probe|forced|default`，另新增 `attempt_details`
        （每次尝试的 json_mode/max_tokens/finish_reason/chars/tokens/keys），
        不重跑也能区分「grammar 提前停」与「预算用满被截断」。
      * **测试**：`tests/test_llm_endpoint.py` 16 → **25 例**（+9）：档案命中（0 网络调用）、
        档案失效（换 model → 仍探测）、档案文件损坏（坏 JSON → 回退探测且不失败）、
        重置清档、成功预算记忆、grammar 特征（含 `stop` + 缺 `relations` 的真实形态）、
        真实截断不误判（2200 tokens/8 概念，且无 usage 时字符启发式同样拒绝）、
        小但 schema 完整不误判；六类原有情形全部保留。
      * **端到端验证（8082，连续两次、独立进程、`EXPERTANYTHING_LLM_CACHE=0`）**：
        `docs/Knowledge_Decoder.md` 3067 字符。
        第 1 次（冷，档案已删）：**167.57s**，16 概念 / 2 关系，`attempts=2`，
        `finish_reasons=["length","stop"]`，首调 `json_mode` 在 2286 tokens 用满被截断
        （5809 字符、只有 `concepts`），关 json_mode 后 3886 预算成功（3335 tokens）；
        `json_mode_source=probe`、`truncation_retries=1`、无 fallback；
        档案写入 `probe_count=1, json_mode_supported=true, min_output_tokens=3886`。
        第 2 次（热，同一进程外新进程）：**105.47s**，16 概念 / 2 关系，
        `attempts=1`，`finish_reasons=["stop"]`，首调即 3886 预算成功（3487 tokens），
        `json_mode_source=persisted`、`truncation_retries=0`、无探测请求、无 fallback。
        **省 62.1s（−37%）**，正是第 32 轮遗留的「首调必浪费一次截断重试」那 60s 左右。
        注：本次实测端点的失败形态是**真截断**（tokens 用满预算），不是 163-token
        grammar 特征；grammar 判定仍按上规则保留并由单测覆盖（本机未复现该形态，
        可能随 build/采样抖动）。
      * **本轮仍未解决**：`min_output_tokens` 是单调全局下限，不对「输入长度/文档
        类型」细分——极大文档的 chunk 仍受 8192 上限约束；不同文档共用一个预算下限
        可能让短文档多给预算（不增加实际生成时间，只放宽上限）；grammar 形态在本机
        不可稳定复现，规则只能覆盖「观察到即记忆」，无法预先证明；探测通过不等于
        长输出语义可靠（仍是第 32 轮的结论）。
49. **Coach 主动引导：单一主张 + 反馈回写（2026-10 落地）**：产品标尺从「功能罗列」转向
    「主动引导」——智能早已算出（`adaptive_path` 的 score/tags/downstream），缺的是替
    学习者做决定的声音。四块落地：
    - **单一主张裁决器**（`core/coach.py`，纯确定性、无 LLM/UI）：把既有信号按
      `anomaly > stuck > prereq > review > focus > path > explore > import` 收成**一个**
      主张（kind/concept/why_key/why_args/urgency/alternatives）。**不新增算法**，只做
      既有信号的优先级裁决；每个信号独立护栏，坏信号降级而非抛错（coaching 绝不阻断
      外壳）。
      * **地基优先（goal-directed, not substitution）**：榜首被 `blocked/prereq_shaky`
        卡住时，主张指向**真正的瓶颈**（kind=prereq，「要学 X 得先补前置，当前只有
        N%」），而非悄悄换成更容易的概念；前置已掌握的陈旧阻塞不覆盖排名。
      * **理由可核验**：focus 主张除传递解锁数（`unblock:N`）外附**解锁了谁**
        （`_unlocked_names`，传递 BFS 最近优先、上限 3、`coach_unlocks_names` 以
        「如 …」呈现示例）——只列直接边会与传递计数自相矛盾。
      * **复习语义是契约**：`is_review(rec)` 为真时 UI 必须走 review 入口（vary=1），
        绝不按首学开课（§6 铁律延伸）。
    - **顶部常驻引导条**（`ui/widgets/guide_bar.py`，topbar 第二行、content stack
      之外）：所有视图可见「现在 · 概念 — 理由 [开始] [换一个] [✕ 先跳过]」；
      **被动、永不自动开课**；无名主张仅 import/explore 放行并按 kind 路由（§35）；
      渲染失败静默隐藏。
    - **反馈回写**（`record_coach_feedback`：start/swap/dismiss；learner.json
      `coach.events` 有界 40 条 newest-first）：同一 kind **连续** dismiss ≥3
      （`FATIGUE_THRESHOLD`）→ 降级让位（`coach_fatigue`），接受即重置；降级**只推迟
      不删除**（被让位主张仍留在 alternatives，全疲劳时仍返回最高优先级——**音量可降，
      绝不消失**）；`fatigue_note` 明说「已连续跳过 N 次同类建议」——降级必须可解释。
      **安全豁免**：anomaly/stuck 永不被疲劳降级——已知矛盾与重复失败被点掉就消失，
      等于「假装全知」（§1/§2 禁止）。swap 记录的是**被拒绝的**主张而非去向，否则
      信号反向。
    - **卡片墙收敛**：learner_view 的分析类卡片（效率/里程碑/风格效果/复习增益/
      掌握预测）折进「📊 更多分析」默认收起（隐藏不删除，`_helpers.py` 已泛化为
      通用折叠）；主线 = 一个主张 + 复习 + 计划。
    - **测试**：`TestCoachRecommendation` / `TestCoachPrerequisiteAwareness` /
      `TestCoachFeedback` / `TestCoachUnlockNames`（core）+ `TestGuideBar` /
      `TestGuideBarFeedback` / `TestGuideBarSwapLabel` / `TestAnalysisFold`（ui）；
      负向对照验证守卫真实（review 语义丢失、prereq 失明、备选重名、疲劳误伤
      anomaly、swap 记错方向、直接边与计数矛盾等回归均可捕获）。
      i18n：`coach_*` 键家族三语齐全（死键守卫曾据此抓到「换一个」按钮无文本的真 bug）。

## 工程纪律

- **测试前置**：每次改进后跑 `python run_tests.py --quick`（**846 用例基线 = core 678 + data 11 +
  ui 155 + runner 2**（quick 不含 llm 12；完整跑为 858），~7-8 分钟；无 PySide6 时 UI 层整层跳过；
  基线口径 = `run_tests.LAYERS` 逐模块 `TestLoader.loadTestsFromName().countTestCases()` 之和
  ——总数或任一层明显变化时按该口径重算并同步此处。注意 `--layer X` 的输出额外含
  常驻 runner 2 例（故单跑 data 层显示 13，而基线里记 11），别把差 2 误当回归）
  —— 分层：core / data / ui（需 PySide6，缺失时整层跳过）/ llm（有 key 自动跑），
  外加常驻的 runner 回归；i18n 键完整性（三语齐全 + 字面键已定义 + 动态家族非空 + 重复键零容忍 + 死键零基线：新死键=回归）由 `tests/test_i18n_integrity.py` 常驻守卫（已注册进 runner core 层；
  2026-09-29 二轮清理：修正语料规则（包内 `_` 前缀模块如 `ui/widgets/_helpers.py` 误排除，
  复活 tag_stuck 等 4 键）后删除 104 个被现行键族取代的死键，键表 718→614，
  `KNOWN_DEAD_BASELINE` 清零，仅 `doubt_*`/`action_path*` 5 键挂 `PENDING_WIRING` 待功能落地）；
  **测试纪律（防静默遮蔽）**：unittest 同名方法后定义者覆盖前者——曾把 `test_save_load_delete`
  误改名撞上既有 `test_load_asset_reads_single_file`，旧断言静默失活一轮才被发现；
  测试类内新增方法前先 grep 同名方法。
  **UI 断言口径（DeferredDelete）**：视图 `_rebuild` 用 `deleteLater()`，旧控件在
  `processEvents()` 后仍留在对象树（DeferredDelete 事件默认不被处理）——`findChildren`
  精确计数断言前必须 `QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)`
  先 flush，否则数到已摘除的旧控件；
  `data/_demo` 缺 `assets/` 或 `learner.json` 时 data 层模块内自动跳过；
  测试用演示数据临时副本，绝不污染真实数据。
- **依赖缺失的表现**：`pypdf`（`requirements.txt` 已声明 `>=4.0`）缺失时
  `parsers._pdf_pages` 静默返回空文本，`tests/test_core.py::test_pdf_extraction`
  会以 `PDF text content not found in ''` 失败——根因是环境缺依赖，**不是**解析或测试缺陷；
  `pip install -r requirements.txt` 即恢复（本机 2026-09-22 实测）。此用例不得跳过或放宽断言。
- 架构分层：`expert_anything/core`（无 UI 依赖，可独立测试）/
  `expert_anything/ui`（`views/` 8 个视图 + `view_manager.py` 编排 + pyside_graph / pyside_widgets / widgets）
  / `main.py`（入口 + MainWindow 外壳，把视图构建与信号路由委托给 `ui/views`、`ui/view_manager.py`）。
- 数据本地优先：`data/`（gitignore），`data/_demo` 为演示数据，**不入库**；
  用仓库根目录 `python regen_all.py` 重建（确定性、离线、幂等，从内置领域模板
  生成 2 个资产 + teacher 模型 + learner.json；落盘前对每个资产
  `_stamp_locations`——演示资产自带锚点，load 时回填只是安全网；
  缺 `assets/` 与 `learner.json` 时 data 层用例自动跳过，重建后转通过）。
  **存量资产锚点回填**：`storage.load_assets()`/`load_asset` 对 concepts 全无
  locations 的旧资产调 `_ensure_locations` 保守回填（重新 stamp）；已有锚点
  （含 PDF 页码）一律不动——页码无法离线重算，覆盖即数据丢失。
- LLM 可插拔：OpenAI 兼容端点，缺 key 自动确定性降级并明确标注。

## 模块职责

- **Librarian**（解析+抽取）：parsers / extraction —— 禁止教学
- **Teacher**（自我理解+异常）：teacher.py —— 禁止修改知识库
- **Tutor**（解释/举例/迁移/评估/追问）：tutor.py —— 禁止编造原文外内容
- **Coach**（路径+复习）：learner.py adaptive_path / due_for_review
- **Reviewer**（评估+参考回答）：tutor.evaluate（reference + gap）
- **Visualizer**（图谱/图表）：graph_viz + pyside_graph / pyside_widgets
- **AutoHarness**（教学 harness 的生成+执行+演化）：auto_harness.py —— 见设计理念第 14 条
- **Domain Pack**（领域模板 + 领域专用解码 + 领域专用 Prompt）：domain_templates.py /
  decoder_electricity.py / decoder_carbon.py / prompt_registry.py 的领域键
  —— 只补骨架与策展场景，**禁止覆盖来源约束内容、禁止在映射失败时改写学习路径**；
  统一出口是 `decoder.scene_for_concept`，领域解析失败必须降级到通用场景 —— 见设计理念第 15 条

## 长期演进（见 docs/）

0. ~~AutoHarness 建议卡 UI 接线~~ ✅ 2026-09-29 落地，**2026-10-30 第 22 轮下线**：
   机制改静默执行（演化/迁移候选直接持久化 + 切讲解风格，不弹卡、不渲染审计块，
   见设计理念 §12 + 落地记录第 38 条）。核心 `core/auto_harness.py` 与
   `_find_transfer_candidates` 差分评估保留；UI 层入口全部移除。
   回归：`tests/test_ui.py::TestLessonResultUI::test_stuck_adapts_silently_and_dedupes`
   / `test_transfer_adopted_silently_without_local_evolution`。

1. ~~SourceLocation（页码/章节定位）→ 回答引用可溯源~~ ✅ 已落地：证据逐条打页/行锚点，
   阅读原文 ↔ 概念双向跳转、图谱与教学页页行徽标、存量资产 load 时保守回填
   （见设计理念 §4；`core/extraction._stamp_locations` + `storage._ensure_locations`）
2. ~~LLM prompt 随 UI 语言（当前 LLM 输出保持中文）~~ ✅ 已落地：
   `core/prompt_registry.py` 按语言维护模板，`get_prompt()` 读当前 UI 语言、
   缺语言/缺键回退 zh-CN；领域 Prompt 走 `get_domain_prompt` 同套查找
3. ~~main.py 按视图拆包（ui/views/）~~ ✅ 已落地：`ui/views/` 8 视图 + `ui/view_manager.py`
4. ~~数据库持久化 + 向量/图检索（Hybrid Knowledge）~~ 部分落地：
  `core/knowledge_index.py` 提供 sqlite 持久索引 + `indexed_search`，已接入图谱搜索
  （`ui/views/concept_map_view.py`）；资产/学习者仍是 JSON local-first（见 `core/storage.py`）
5. ~~会话内多轮对话沉淀到 TeacherModel 深度闭环~~ ✅ 已落地：
   `teacher.record_learner_question` 把追问写入概念 `learner_signals`（保留最近 8 条，
   教师模型页可见），确定性、无需 LLM；配合答题/卡壳/复习增益信号构成反哺闭环
6. 领域包扩展：已全链路落地四个领域 —— 电力交易、碳市场、可再生能源预测
   （`decoder_renewable.py`）、分布式能源（`decoder_distributed_energy.py`），
   每个均为「模板 + Prompt + 解码器 + 术语/测试」组合；新增一域只需这三件套，
   统一出口仍是 `decoder.scene_for_concept`（领域解析失败降级通用场景）；
   演示数据重建脚本为 `regen_all.py`（方案见 `docs/电力交易领域学习方案.md`）
*（内容由AI生成，仅供参考）*
