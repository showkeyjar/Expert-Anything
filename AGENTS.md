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
  **禁止硬编码 UI 文本**（新增文案必须走 i18n 键表，三语齐全；扫描脚本可验证）

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
3. **可视化优先（快速学习）**：知识图谱是核心入口，必须是"活"的——
   - 力导向物理模拟（斥力+弹簧+引力），节点稳定后轻微漂浮（幅度 ≤0.5，不得干扰点击）
   - 可拖拽节点（邻居弹簧跟随）、悬停高亮邻居、单击弹详情侧栏（随节点变化）、
     双击教学、搜索定位、范围切换（全部资产/当前资产）、缩放（滚轮+按钮）、内容自适应缩放
   - 当前书彩色、其他资产灰色（grey_ids），跨资产共享概念连线
   - 图例必须解释颜色语义；初始化缩放保证节点可读（≥0.85）
4. **点击必须产生更深层细节（认知地图信息增量）**：任何可点击节点/条目都要能展开内容
   （概念面板：定义/证据/关系邻居/教师笔记/异常/动作），禁止单层死链接。
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
5. **学习闭环的可视化锚点**：路径阶梯、掌握度分布条、成长趋势图、复习队列、
   指标卡——Learning Gain（ADR-010）是功能取舍标尺。
6. **间隔效应**：复习队列 `due_for_review()`（薄弱 1 天、掌握 3-6 天），
   复习课用 vary=1 换角度讲解。
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

## 工程纪律

- **测试前置**：每次改进后跑 `python run_tests.py --quick`（226 用例，~10s）
  —— 分层：core(135) / data(7) / ui(38) / llm(7，有 key 自动跑)；
  测试用演示数据临时副本，绝不污染真实数据。
- 架构分层：`expert_anything/core`（无 UI 依赖，可独立测试）/
  `expert_anything/ui`（pyside_graph + pyside_widgets）/ `main.py`（入口+视图）。
- 数据本地优先：`data/`（gitignore），`data/_demo` 为演示数据（可用 regen 脚本重建）。
- LLM 可插拔：OpenAI 兼容端点，缺 key 自动确定性降级并明确标注。

## 模块职责

- **Librarian**（解析+抽取）：parsers / extraction —— 禁止教学
- **Teacher**（自我理解+异常）：teacher.py —— 禁止修改知识库
- **Tutor**（解释/举例/迁移/评估/追问）：tutor.py —— 禁止编造原文外内容
- **Coach**（路径+复习）：learner.py adaptive_path / due_for_review
- **Reviewer**（评估+参考回答）：tutor.evaluate（reference + gap）
- **Visualizer**（图谱/图表）：graph_viz + pyside_graph / pyside_widgets
- **AutoHarness**（教学 harness 的生成+执行+演化）：auto_harness.py —— 见设计理念第 14 条

## 长期演进（见 docs/）

1. SourceLocation（页码/章节定位）→ 回答引用可溯源
2. LLM prompt 随 UI 语言（当前 LLM 输出保持中文）
3. main.py 按视图拆包（ui/views/）
4. 数据库持久化 + 向量/图检索（Hybrid Knowledge）
5. 会话内多轮对话沉淀到 TeacherModel 深度闭环
