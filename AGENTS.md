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

- **桌面端 PySide6**（`main.py` 入口，`python app.py` 或 `python main.py`），7 个视图：
  导入知识资产 / 知识模型 / 概念网络 / 阅读原文 / 教学会话 / 学习者模型 / 教师模型
- **UI 三区框架**：顶部功能栏（当前资产 + 掌握度进度 + 快捷动作 + 语言切换）+
  左侧导航区 + 中央展示区（视图 header 统一白底蓝条）
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
     双击教学、搜索定位、范围切换（全部资产/当前资产）、缩放（滚轮+按钮）、内容自适应缩放
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
   “地基不稳”信号）；出口带 `gain_stretched`/`gain_weak` 标志。
   **锚点感知调度（2026-09-29）**：无锚概念（◌，`c.locations` 为空）复习间隔
   **减半**——学习者无法跳回原文自助重温，系统侧复习是其唯一巩固通道；
   条目带 `unanchored` 标记，学习页复习卡渲染 ◌ 标签（`due_unanchored`）。
   与 `prereq_weak` 同模式：图谱/锚点信号 → interval 压缩 → 复习排序。
7. **UI 工程规则**：
   - 视图重建（`_rebuild_all_views`）必须先清旧控件引用再构建，禁止访问已删除控件
   - QGraphicsView 等大 sizeHint 控件必须设 max 高度，防挤占主内容区
   - 布局中主内容区必须 stretch（addWidget(w, 1)），避免"标题占半屏"
   - 全局 excepthook：未捕获异常写 error.log + 弹窗，禁止静默消失
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
      自动轮换讲解风格 + `incorporate_stuck_signal` 写入教师模型；
      同时驱动 `auto_harness.evolve_for_stuck` 演化 harness 结构
      （换风格+补 scene，候选再过 check_harness）；UI 教学页把候选渲染成
      建议卡，一键启用后按新 style 重讲并持久化 harness_state.json
      （per-asset，写入前再过 check_harness）；
      演化全程落 `_history` append-only 审计链（stuck/manual/steady + old→new
      摘要，save 时保留不被冲掉），教学视图渲染历史块——自动化可解释可追溯；
      预算核算用 `estimate_cost`（固定基础 + 内容规模≈token），budget_ok 感知昂贵调用；
      harness 跨资产迁移须过 `evaluate_transfer` 差分评估（目标资产上 OFF/ON
      双配置取差分 + 前提三态 eligible/mismatch/inconclusive + 成本差分；
      仿真收益不可测时用计分覆盖度差分兜底，成本 ≤ 预算 30% 才采纳），
      采纳走 `adopt_harness_for_asset`（持久化 + 审计链 reason="transfer"）；
      卡壳分支自动检测其他资产的迁移候选，UI 弹迁移建议卡（浅蓝，与演化
      琥珀卡区分），一键迁移启用后按新 style 重讲当前概念；
      演化算子三层信号源：stuck（`stuck_concepts` → O1 换风格）、regression
      （`regression_detection` 从好变差 → O2 裁守卫，UI 紫色回归卡 + 审计链
      reason="regression"）、会话报告统计（`persist_session_report` 落
      `_sessions` 有界 append-only + `aggregate_reports` + `evolve_from_sessions`
      → O2/O3；`save_harness_state` 保留 `_sessions` 不冲信号底座）；
      **安全铁律：`SAFE_GUARDS`（safe_only）永不裁**，O2 只在可裁守卫中选触发最多者；
      三层信号并发时用**联合演化**（`detect_signals` 统一检测 →
      `_o2_target_fusion` 回归假设×会话实际触发仲裁，真实数据优先 →
      `evolve_joint` 融合决策）：同算子跨源去重、候选按因果强度 O2>O1>O3、
      reason 触发家族串（stuck→regression→sessions）、diagnosis 可解释行；
      UI：多信号并发弹青色联合卡（带诊断，审计 reason 记家族串，历史块按
      "+" 拆分本地化），单信号保持琥珀/紫色卡原行为；
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

## 工程纪律

- **测试前置**：每次改进后跑 `python run_tests.py --quick`（455 用例，~23s；无 PySide6 时 UI 层整层跳过）
  —— 分层：core / data / ui（需 PySide6，缺失时整层跳过）/ llm（有 key 自动跑），
  外加常驻的 runner 回归；i18n 键完整性（三语齐全 + 字面键已定义 + 动态家族非空 + 死键零基线：新死键=回归）由 `tests/test_i18n_integrity.py` 常驻守卫（已注册进 runner core 层；
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
  `expert_anything/ui`（`views/` 7 个视图 + `view_manager.py` 编排 + pyside_graph / pyside_widgets / widgets）
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

0. ~~AutoHarness 建议卡 UI 接线~~ ✅ 2026-09-29 已全部落地：
   - 演化卡：`main._offer_harness_evolution`（stuck 信号 → `evolve_joint`
     融合演化 → 按 reason 分派琥珀/紫/青卡 → 会话级去重
     `(asset, concept, reason, candidate)`）；
   - 迁移卡：`main._offer_harness_transfer_cards`（stuck 信号 →
     `_find_transfer_candidates` 差分评估 → migrate 结论 → 浅蓝卡，
     最多 2 张/轮、`(target, source, spec)` 去重、已展示源跳过重复评估）；
   - `teach_view._display_result` 连接 `harness_adopt_requested`/
     `harness_transfer_requested` + `_attach_harness_history`（审计链渲染）；
   - 采纳审计 reason 修正：stuck 卡采纳记 `"stuck"` 而非 `"manual"`。
   端到端测试：`tests/test_ui.py::TestHarnessSuggestionUI::
   test_stuck_signal_shows_evolution_card` / `test_transfer_card_via_stuck`。

1. SourceLocation（页码/章节定位）→ 回答引用可溯源
2. LLM prompt 随 UI 语言（当前 LLM 输出保持中文）
3. ~~main.py 按视图拆包（ui/views/）~~ ✅ 已落地：`ui/views/` 7 视图 + `ui/view_manager.py`
4. 数据库持久化 + 向量/图检索（Hybrid Knowledge）
5. 会话内多轮对话沉淀到 TeacherModel 深度闭环
6. 领域包扩展：碳市场已全链路落地（模板/检测/Prompt/术语/策展解码 `decoder_carbon.py`，方案见 `docs/电力交易领域学习方案.md`）；下一域只需 模板+Prompt+解码器 三件套；演示数据重建脚本已落地为 `regen_all.py`
*（内容由AI生成，仅供参考）*
