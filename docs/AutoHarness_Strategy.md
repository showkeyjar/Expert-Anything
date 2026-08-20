# AutoHarness — 教学 Harness 的自动生成与演化策略

> 洞察（用户，2026-08）：Harness 工具的爆发说明 **Agent = Model + Harness** 已成行业共识；
> 下一步必然是 **Harness 设计本身的自动化** —— 让系统像 harness 驾驭模型那样，
> 用"开放推理 + 确定性外壳"来设计、准入、执行、评估并演化自己的教学 harness。

## 1. 背景：Harness 战争已开打

2026 年以来开源 Harness 工具密集爆发，四条主线同时成熟：

| 形态 | 代表 | 设计要点 |
|---|---|---|
| 评测工装 | lm-evaluation-harness (LEH) | 四层架构：模型接入 / 任务配置(YAML 声明式) / 执行调度 / 结果聚合，成为评测事实标准 |
| 训练工装 | NVIDIA NeMo Finetuning/Reasoning Harness | 训练全流程的工程外壳，把"跑模型"变成可复现流水线 |
| 推理工装 | 模型网关（池化调度 + 成本管控 + 可观测） | 把"调模型"抽象成服务，按预算/延迟/质量路由 |
| Agent 驾驭层 | DeepSeek Harness (dsh)、SWE-agent ACI、ToolTrust gatekeeper | 当前热点：工具调度、状态管理、安全边界、会话日志 |

关键观测：

- **DeepSeek Harness（2026-08-13 开源，一周 8.2 万 star，"一切皆插件"）**：
  Cordis 元框架（Plugin/Context/Inject/Typed Events/Reversible Effects），**无特权内核**；
  Profile + Bundle 分层组装；Turn/Step 循环切分；**会话日志为唯一真相源**
  （"Model-visible means logged"）；Capability Seam（Service Definition / Provider /
  Consumer 三角色，"一次替换处处生效"）；四种运行模式（Standard/PTC/Minimal/Creator），
  Creator 模式支持运行时自省与自我进化。
- **Harness-Bench**：同一模型换 harness 可使测量能力差 **24 点**——harness 不是透明的
  传声筒，它本身就是被测对象的一部分。OpenAI 第三方评测指南因此要求报告 harness 选择。
- **METR 时间跨度评测**（Time Horizon 1.1，从 Vivaria 迁移到 Inspect）：用"人类专家完成
  任务的时间跨度"作为模型能力的语义标尺，harness 决定任务能被推进到什么程度。
- **SWE-agent ACI（Agent-Computer Interface）**：为 LM 设计命令与反馈格式（linter 前置、
  100 行文件查看器、简化 grep 输出、空输出显式提示）——ACI 设计的迭代本身就是 harness 工程。
- **ToolTrust gatekeeper**：agent 与工具之间的策略引擎，fail-closed、四级决策
  （非二进制 allow/deny）——"Harness 工具爆发"时代另一关键设计。

**结论**：模型负责思考，harness 负责执行闭环、工具调度、状态管理、安全边界。
当 harness 本身成为可设计的产物，下一步就是**设计 harness 的 harness**（meta-harness）。

## 2. 抽象：Agent = Model + Harness，教学也不例外

Expert-Anything 的学习闭环本身就是一条 harness：`teach → quiz → practice → review`
的工具序列 + 预算 + 守卫 + 评估 + 掌握度回写。问题是这条 harness 目前是**手写的**：
风格轮换、复习间隔、守卫清单都是代码里写死的常量。AutoHarness 把它提升一个抽象层级：

```text
传统 harness（已有）：    Agent(模型思考) + 手写 Harness(工程外壳)
AutoHarness（本设计）：   Agent(模型思考) + Harness(由 meta-harness 生成并演化)
```

**目标**：对每个概念 × 学习者状态，自动设计出"用哪些工具、按什么顺序、配什么守卫、
花多少预算、用什么指标评估"的教学 harness，并在每次运行后根据轨迹证据自我演化——
卡壳换风格、误伤裁守卫、吃紧扩预算——全部走代码准入，不允许绕过。

## 3. 核心策略：开放推理 + 确定性外壳（延续 OmniScientist / decoder 铁律）

LLM 只产出 **HarnessSpec**（类型化 JSON 规范），渲染/执行/准入/评估一律由确定性代码完成：

```text
概念 + 学习者状态 + 目标
  → LLM 产出 HarnessSpec（tools/policy/loop/evaluation/meta）   ← 开放推理：只描述"harness 里有什么"
  → auto_harness.check_harness() 代码准入                        ← 确定性外壳：结构合法性强制
      （工具 ∈ 槽位、守卫 ∈ 白名单、mode/sandbox/metric 合法、
        retry/预算/步数夹紧、工具去重保序；失败带原因重试 1 次）
  → 确定性装配 build_harness()                                  ← 非法 spec 直接抛错 fail-fast
  → 确定性执行 Harness.run()                                    ← append-only 轨迹事件流
      pre 守卫（预算/沙箱 fail-closed）→ provider 调用 → post 准入
      → 带原因轮换重试（有界）→ 仍失败显式确定性降级
  → 差分评估 compare_harnesses()                                ← OFF/ON 双配置取差分，三态采纳
  → 演化 evolve()                                               ← 候选必须再过 check_harness
  → 学习闭环回写 apply_to_learner()                             ← record_evaluation(meta=harness 轨迹)
```

**铁律**：LLM 永不直接输出可执行 harness；`suggest_harness()` 返回的每个 spec 都必须
通过 `check_harness()` 才能被装配。演化也不允许绕过准入——这是"auto"的安全边界：
自动化的对象是**结构**，不是**可信度**。

## 4. HarnessSpec 规范

```json
{
  "name": "harness 名（40 字内）",
  "mode": "minimal | fast | full",              // 策略分层，对应 dsh 四种运行模式的最小对应
  "tools": ["teach", "quiz", "practice", "scene", "review"],  // 有序工具序列，去重保序
  "policy": {
    "teach_styles": ["例子", "图示", "拆解步骤"],  // 讲解风格轮换表
    "guard_ids": ["no_definition_copy", "evidence_grounded", "budget_ok", "safe_only"],
    "retry": 1,                                  // post 准入失败重试次数（≤2）
    "fallback": "deterministic"                  // 目前仅支持显式确定性降级
  },
  "loop": { "max_steps": 4 },                    // 步骤上限（1-10）
  "evaluation": { "metric": "learning_gain", "threshold": 0.6 },
  "meta": { "budget_cost": 50, "sandbox": "local", "lang": "zh-CN" }
}
```

- **工具槽位**（`TOOL_SLOTS`）：teach / scene / quiz / practice / review——每个槽位
  是**能力接缝**（见 §5），可注入外部 provider 替换实现。
- **守卫**（`GUARD_IDS`）：
  - `no_definition_copy`：讲解不得只是抄写定义（checks.explanation_is_definition 镜像）
  - `evidence_grounded`：讲解/图示必须扣住本概念（复用 checks._name_hits，anti-template）
  - `budget_ok`：预算纪律，由 run() 循环强制执行（步数 + 成本双上限）
  - `safe_only`：ToolTrust gatekeeper——需要沙箱的工具在 sandbox=none 时 fail-closed，
    非二进制 allow/deny，只拦真正要执行外部动作的工具
- **预置 mode**（`MODE_PRESETS`）：minimal（teach+quiz，最低成本）/ fast（+scene 图示）/
  full（+practice+review 完整闭环）——让 LLM 不用每次都从零拼工具列表。

## 5. 能力接缝（Capability Seam，dsh 三角色）

工具槽位 = Service Definition（接口），provider = Service Provider（实现）：
替换一个 provider 即替换该能力，其余不动。`build_harness(spec, providers={...})`
支持任意槽位注入，未注入时走确定性默认 provider（`_DEFAULT_PROVIDERS`）。

| 槽位 | 默认 provider | 有 LLM 时 |
|---|---|---|
| teach | 确定性讲解 stub（定义 + 原文证据引导） | `Tutor.teach(concept, style)`（内置 check_lesson 准入 + 降级） |
| scene | `decoder.fallback_scene`（关系图确定性生成） | 同上（LLM SceneSpec 由 decoder 独立准入） |
| quiz / practice / review | 确定性生成 + `_sim_score(mastery)` 仿真得分 | 可注入 LLM 生成 + 严格评估 |

`_sim_score` 让指标回路在无 UI、无网络、无 LLM 时仍可确定性演示；
生产接入时由真实答题得分替换。

## 6. 轨迹 = 唯一事实源（"Model-visible means logged"）

`Harness.run()` 返回 **append-only 事件流**：每步含 seq/tool/args/ok/summary/
blocked_by/skipped/cost/score。规则：

1. 模型可见的一切都在事件里；回放、审计、演化、教师模型都读轨迹而非叙述文本。
2. **预算耗尽事件本身也落轨迹**（blocked_by="budget_ok"）——轨迹是完整的，不含糊。
3. `_report()` 从轨迹汇总 metric/value/learning_gain/task_success/guard_triggers/
   blocked/cost/steps_used——报告不是独立事实源，是轨迹的投影。
4. 学习闭环回写：`apply_to_learner()` 经既有 `learner.record_evaluation` 记掌握度，
   meta 带 channel="harness" / harness 名 / 指标 / 守卫触发——卡壳检测、报告、
   教师模型继续读学习轨迹这一条真相源。
5. **演化历史审计链**：harness 自身的演化也是轨迹——`harness_state.json` 顶层
   `_history` 存 append-only 演化事件（reason=stuck/manual/steady + 时间戳 +
   old→new 一行摘要 + 新 spec 名）。`record_harness_evolution` 只追加不修改，
   `save_harness_state` 保留 `_history` 不被全量覆盖冲掉；教学视图每次构建都渲染
   最近历史（按已展示数增量去重），自动化因此可解释、可追溯——这是与"黑盒调参"
   的分水岭。

## 6.5 真实成本模型

`budget_ok` 的预算核算从固定 `TOOL_COST` 升级为
`estimate_cost(tool, args, result) = TOOL_COST 基础 + 内容规模成本`：

- 内容规模 = 输入 args 与输出 result 的字符数（≈token，中英文混合 1 字符≈1 token），
  每 `COST_CHARS_PER_UNIT`（100）字符计 1 个成本单位，向下取整。
- 短内容（最小请求、测试替身）增量≈0，既有行为不变；长讲解/长输出显著抬升成本，
  **预算耗尽更早触发**——守卫感知"昂贵的调用"，O3 扩预算的触发也更接近生产语义。
- run 循环与 post 重试全部接入 `estimate_cost`（`_report().cost` 仍从轨迹汇总，
  报告是轨迹的投影这一铁律不变）。
- 纯函数、确定性、无网络、与 LLM key 无关——成本模型本身可 headless 测试。

## 7. 差分评估（BFCL 教训代码化）

`compare_harnesses(control_reports, treated_reports, key, noise_floor=0.05)`
——**OFF/ON 双配置取差分，绝不能拿 ON 的结果直接对标准答案比**：

- 镜像/简化的自身偏差会被整个记到改动头上，量级足以让结论反号；
- 三态采纳：|diff| ≤ noise_floor → "noise"（不采纳）；treated 显著更好 → gain；
  更差 → loss；数据缺失 → inconclusive。
- 噪声底噪标尺：非确定性系统（采样温度/并发/外部服务）重跑同一配置也会翻转结果，
  先用不受改动影响的子集量底噪，再与效应量比较。

## 8. 演化算子（"auto"所在，全部必须再过准入）

`evolve(spec, report, candidates_limit=3)` 从轨迹证据推出下一代 harness 候选：

| 算子 | 触发信号 | 动作 | 对应既有闭环 |
|---|---|---|---|
| O1 卡壳换风格 | value < threshold | 换下一个讲解风格 + 补 scene 图示 | 现有 stuck 闭环（连续 3 次不达标 → 轮换风格）泛化 |
| O2 误伤裁守卫 | 可裁守卫触发次数最多（SAFE_GUARDS 安全铁律永不裁） | 裁掉该守卫（并附候选说明） | ToolTrust gatekeeper 的撤销通道 |
| O3 吃紧扩预算 | steps_used 用满上限 | 预算/步数扩容 | 资源弹性的自动决策 |

- 每个候选必须再过 `check_harness()`——演化也不允许绕过准入。
- 稳态（value ≥ threshold 且无异常触发）→ 返回 base 自身，不折腾。
- 目的不是无脑调参，而是**让卡壳检测 → 策略轮换这条人工闭环自动化**，
  与现有 stuck 信号、教师模型 incorporate_stuck_signal 形成同构的双层结构。

**卡壳自动触发（`evolve_for_stuck`，2026-08-18 落地）**：`evolve` 的输入是
一次会话报告，仍需调用方手动构造；`evolve_for_stuck(spec, learner_state, ...)`
直接读学习轨迹（history 是唯一事实源）——若某概念连续 N 次评估均未达标
（`learner.stuck_concepts` 判定，阈值优先取 spec 的 `evaluation.threshold`，
即 harness 自己的达标线），自动映射成 O1 触发的报告并调用 `evolve`：

```text
学习轨迹 (history) ──stuck_concepts──▶ 卡壳信号
    ──evolve_for_stuck──▶ evolve ──▶ 候选（再过 check_harness）
```

返回 `{evolved, source: stuck|steady, trigger, candidates}`：steady 时不产出
候选（不折腾）；stuck 时第一个候选即"换讲解风格 + 补 scene"。由此现有 stuck
闭环（Tutor.teach 轮换讲解风格 + `incorporate_stuck_signal` 记教师模型）从
"只换讲解风格"升级为"连 harness 结构一起演化"——卡壳检测与 harness 演化
真正闭环，无 LLM 也全链路确定性可跑。

**UI 采纳环节（2026-08-18 落地）**：候选产出后需要人工/半自动采纳才有意义。
教学会话页 `_on_submit_answer` 的卡壳命中分支调 `evolve_for_stuck`，把候选渲染
成建议卡（`TeachResultView.append_harness_suggestion`：摘要 + 一键启用按钮）：

```text
卡壳命中 ──▶ evolve_for_stuck ──▶ 候选卡 ──一键启用──▶ _on_adopt_harness
    ──▶ 持久化 harness_state.json（per-asset，写入前再过 check_harness）
    ──▶ 按候选 style 立即重讲当前概念（explicit style 跳过 tutor 自身轮换）
```

采纳后 `Tutor.teach(style=候选.policy.style)` 以新讲解风格重讲，形成
"卡壳 → 演化 → 新 harness 上场"的完整产品闭环；harness 状态按资产持久化
（`load_harness_state` / `save_harness_state`，标准库 json，headless 可测）。

## 8.4 演化算子信号化：O2/O3 的真实信号源（2026-08-18 落地）

`evolve` 的三个算子在演进到 8.4 之前只有 O1 有真实信号：`evolve_for_stuck`
把会话报告里的 `guard_triggers` 写死 `{}`、`steps_used` 写死 `0`，O2（裁守卫）
与 O3（扩容）在真实闭环里永远空转 —— 它们只在测试手工构造 report 时才触发。
8.4 让三个算子全部接上真实信号，三层信号 → 三算子：

```text
信号层 1  stuck（持续不达标）        learner.stuck_concepts ──▶ O1 换风格+补 scene
信号层 2  regression（从好变差）      regression_detection    ──▶ O2 裁守卫（回归=指控误伤）
信号层 3  会话报告统计（真实运行）     persist_session_report ──▶ O2/O3（guard 累计/步数满额率）
```

**信号层 2：`regression_detection(learner_state, ...)`** —— 与 `stuck_concepts`
互补的误伤早期信号。stuck = "一直讲不懂"（可能是本来就难）；regression =
"以前讲得懂、最近讲不懂"（策略变化产生负效应的强信号）。判定：最近
`attempts` 条评估全部低于阈值，而更早的窗口（默认 6 条）内存在达标记录 →
回归，按 drop（before_avg − after_avg）降序返回。`evolve_for_regression` 把
回归信号映射成 O2 可消费的报告：`guard_triggers = {budget_ok: attempts}` ——
预算守卫是最可能造成"内容变浅 → 表现回退"的约束（预算卡住长讲解），
budget_ok 不在守卫列表时无抓手，退回 steady。审计链 reason="regression"。

**信号层 3：`persist_session_report` + `aggregate_reports` + `evolve_from_sessions`** ——
`Harness.run` 产出的 `report`（含真实的 `guard_triggers` / `steps_used` / `value`）
append-only 落盘到 `harness_state.json` 顶层 `_sessions`（有界保留最近 20 条，
与 `_history` 同一纪律：`save_harness_state` 全量覆盖时同样保留，不冲掉信号
底座）。跨会话聚合得到统计信号：`pass_rate` / `avg_value` / `guard_triggers`
累计 / `steps_exhausted_rate`，`evolve_from_sessions` 据此驱动：

| 算子 | 统计信号 | 动作 |
|---|---|---|
| O1 | avg_value < threshold 或 pass_rate < 0.5 | 换风格 + 补 scene |
| O2 | 可裁守卫跨会话触发累计最多 | 裁该守卫（safe_only 永不裁） |
| O3 | steps_exhausted_rate ≥ 0.5 | 步数 +3 / 预算 +30（双上限封顶） |

**安全铁律（8.4 修正）**：守卫分三类 —— `safe_only`（安全，永不裁）、
`no_definition_copy` / `evidence_grounded`（来源约束铁律，裁掉会放宽约束，
仅生成候选、由采纳环节显式确认）、`budget_ok`（成本纪律，裁掉=不惜成本，
回归信号默认指向它）。O2 只在可裁守卫中选触发最多者；旧实现会把 safe_only
也裁掉 —— 安全不是演化参数，8.4 起硬编码保护。

**UI（2026-08-18 落地）**：卡壳命中分支在 stuck 演化卡（琥珀）之外追加
`evolve_for_regression` 检测 —— 命中时渲染第二张紫色演化卡（标题"疑似误伤：
建议裁守卫"，按钮"采纳并裁守卫"），emit 携带 `_source="regression"`，
`_on_adopt_harness` 剥离标记后持久化（不污染 HarnessSpec）并写入审计链
reason="regression"；历史块本地化标签同步支持 regression。

## 8.5 跨资产 harness 泛化（迁移效果评估，2026-08-18 落地）

一个 harness 在资产 A 上因卡壳演化/LLM 设计而变好，能否迁移到资产 B？
迁移评估回答的是「**这个 harness 搬到那边值不值**」，不是「它本身好不好」——
因此评估在**目标资产**上跑 OFF(本地默认) vs ON(待迁移) 双配置取差分：

```text
资产结构画像 asset_profile()          ← 前提特征（概念数/关系数/定义覆盖率/密度）
迁移前提检查 transfer_eligibility()   ← 三态：eligible / mismatch / inconclusive
差分迁移评估 evaluate_transfer()      ← 目标资产上 OFF/ON 双配置，逐概念取差分
迁移采纳 adopt_harness_for_asset()    ← 持久化 + 审计链 reason="transfer"
```

- **前提三态（方法论 11 代码化）**：目标资产无概念 → inconclusive（不可验证，
  返回 verify 而非结论）；full mode 但目标概念 <3 → mismatch（结构不匹配，
  直接拦截不浪费差分执行）；前提成立 → eligible。定义覆盖率为 0 只给 warning
  不阻断（teach/quiz 内容底座缺失，得分基准偏低——`_sim_score` 已内容感知，
  定义长度影响基准分，让"资产画像 → 迁移效果"有合法的跨资产差异来源）。
- **OFF/ON 差分（方法论 6b 代码化）**：OFF = 目标资产的本地默认 harness，
  ON = 待迁移 spec，在同一目标资产上逐概念跑双配置（按学习路径顺序取样，
  最多 3 概念），聚合差分 + 成本/阻塞差分。|diff| ≤ noise_floor → noise。
- **收益差分 + 覆盖度差分（两层）**：确定性仿真下 learning_gain 只由
  mastery×definition_len 决定，工具集相同时 OFF/ON 必然同分 —— 收益差分
  不可测（与 BFCL「镜像无法区分」教训同构）。此时用**计分覆盖度差分**兜底：
  一次 run 产生 score 的事件数（quiz/practice/review 槽位宽度，由工具集
  决定，非仿真噪声）。ON 若比 OFF 多验证槽位且成本可接受 → 结构性收益成立。
- **推荐动作四态**：gain → migrate；loss → keep_local；noise 且覆盖度提升、
  成本 ≤ 预算 30%（下限 5）→ migrate（结构性收益）；noise 且覆盖度更弱 →
  keep_local；其余 noise → no_change（迁移不是免费的）；前提不成立 → verify。
- **迁移采纳进审计链**：`adopt_harness_for_asset` 把 spec 写入目标资产的
  harness_state（写入前再过 check_harness，迁移也不允许绕过准入），`_history`
  追加 reason="transfer" 事件（含 source_asset_id / old→new 摘要），与
  stuck/manual/steady 事件同链 —— 跨资产迁移同样可解释、可追溯。
- **UI 接入（同轮）**：教学会话卡壳分支自动调用 `_find_transfer_candidates`
  （遍历其他资产已采纳的 harness，逐一 `evaluate_transfer`，只保留
  recommendation=migrate、按差分收益降序取最优）→ 弹浅蓝色**跨资产迁移建议卡**
  （与琥珀色演化建议卡区分，正文含源资产/差分收益/成本差）→ 一键「迁移启用」：
  `_on_transfer_harness` 调 `adopt_harness_for_asset`（审计链 transfer）→ 按
  迁移 harness 的 style 立即重讲当前概念。卡壳 → 演化 → 迁移，全链路闭环。

## 8.6 联合演化：三层信号融合成一个决策（2026-08-18 落地）

真实场景里信号是**并发**的：回归是卡壳的子集（两者都要求最近 N 次不达标，
见 8.4 信号层 1/2），会话统计也可能同时异常。三个单信号入口
（`evolve_for_stuck` / `evolve_for_regression` / `evolve_from_sessions`）各算
各的，会产出**重复候选**（stuck 与 sessions 同触发 O1 → 两个换风格方案）、
**互相矛盾的 O2 目标**（回归假设 budget_ok，会话实际触发却是
no_definition_copy），且无法解释"为什么演化成这样"。联合演化
（`evolve_joint`，推荐入口）一次算齐三层信号，做单信号入口做不到的三件事：
**去重**（同算子多信号同指只出一个候选）、**仲裁**（O2 裁守卫目标由
"回归假设 × 会话实际触发"融合决定，真实数据优先）、**诊断**（evidence 行 +
触发家族串 reason，演化决策全程可解释）。

```text
detect_signals()        ← 统一信号检测：stuck / regression / sessions 一次算齐
  ├─ stuck       = learner.stuck_concepts（最近 attempts 次全部不达标）
  ├─ regression  = regression_detection（曾经达标、最近连续不达标）
  └─ sessions    = aggregate_reports（真实会话报告，reports 非空时）
_o2_target_fusion()     ← O2 目标仲裁：回归假设 × 会话实际触发
evolve_joint()          ← 候选按因果强度排序（O2 > O1 > O3），全部再过 check_harness
```

- **焦点概念确定性选择**：concept_name 显式指定 > stuck ∩ regression 交集
  （按 drop 降序、after_avg 升序取最严重）> 纯 regression（"策略变化产生负
  效应"的因果故事更强）> 纯 stuck。focused=None 表示纯会话信号驱动。
- **O2 目标仲裁（方法论 6b/6c 代码化）**：回归的默认假设是成本纪律
  budget_ok（预算卡住长讲解 → 内容变浅 → 表现回退）。会话统计是**实际触发
  数据**，真实数据优先于假设：实际触发存在 → 以实际为准（裁累计触发最多
  的可裁守卫）；与假设同指 → 双证据（sources=[sessions, regression]）；
  不同指 → 假设被数据修正（sources=[sessions]，仲裁过程写进 diagnosis）；
  会话数据缺失 → 保留假设（弱置信）。老纪律：guard_ids ≤1 时最后一个守卫
  不裁。
- **候选顺序 = 因果强度**：回归驱动的 O2（"以前懂现在不懂"最急迫）优先，
  O1 换风格次之，O3 扩容殿后。全部候选再过 `check_harness`（演化也不允许
  绕过准入，`_admit_candidates` 统一过滤）。
- **触发家族 reason（去重保序）**：reason = 触发家族串，顺序固定
  stuck → regression → sessions，只含实际驱动了候选的家族；被数据修正的
  假设留在 diagnosis 而不进 reason（如回归被会话数据反驳时 reason=
  stuck+sessions）。同一算子被多信号同指 → 只出一个候选（O1 的跨源去重）。
- **diagnosis 可解释行**：回归事实行（before→after/drop）排最前，然后是
  融合/仲裁/会话统计/回归假设/卡壳/步数满额行 —— 演化决策的每条证据都可
  追溯到具体信号。
- **UI 接入（同轮）**：教学会话卡壳分支改调 `evolve_joint`（reports 读
  harness_state.json 的 `_sessions`，缺失即空列表不抛错）。多信号并发
  （reason 含 "+"）→ 青色**联合演化卡**（专属按钮"启用联合方案"，正文含
  reason 家族串 + 诊断首行，emit 携带 `_joint_reason`）；单信号 → 保持琥珀
  卡壳卡 / 紫色回归卡原行为。`_on_adopt_harness` 审计 reason 记录完整家族
  串（如 stuck+regression+sessions），历史块按 "+" 拆分逐个本地化 —— 审计
  链比笼统的 manual 更精确。
- **测试**：`TestJointEvolution` 12 例（stuck-only → O1；stuck+regression →
  O2 优先；sessions-only → 三算子全触发；回归假设被会话证实（融合文案）/
  被修正（仲裁文案，reason 不含 regression）；O1 跨源去重；steady 不折腾；
  concept_name 聚焦；焦点优先级；`_o2_target_fusion` 五规则）+ UI 3 例
  （青色卡渲染 + emit 携带家族串、联合采纳审计 reason、复合 reason 历史
  本地化）。全量 262 例通过。

## 9. 与四类既有 harness 的对照

| 既有 harness | 它的"执行闭环" | AutoHarness 的对应物 |
|---|---|---|
| LEH（评测工装） | 任务 YAML → 模型 → 指标聚合 | HarnessSpec → provider → report |
| dsh（Agent 驾驭层） | 插件装配 → Turn/Step → 会话日志 | build_harness → run 循环 → 轨迹事件流 |
| SWE-agent（ACI） | 命令界面 + 反馈格式迭代 | teach_styles 轮换表（讲解格式本身可演化） |
| ToolTrust（安全） | 策略引擎 fail-closed 分级 | safe_only 守卫 + budget_ok 预算纪律 |

AutoHarness 的独特点：**前四者都是"一次设计、重复执行"，AutoHarness 是
"执行一次、自动再设计"**——它的产物（HarnessSpec）本身就是下一轮执行的输入。

## 10. 与 decoder / checks 的复用映射（零重复发明）

| 既有设施 | AutoHarness 复用方式 |
|---|---|
| `decoder.check_scene` / `fallback_scene` / `scene_summary` | scene 槽位的准入、兜底、摘要 |
| `checks.check_lesson` / `_name_hits` / `explanation_is_definition` | 讲解准入 + 守卫实现 |
| `learner.record_evaluation` / `normalize` | 掌握度回写与查找键 |
| `tutor.Tutor.teach(style, vary)` | teach provider 的 LLM 路径 |
| `_FakeLLM`（tests.test_checks） | LLM 路径测试替身 |

`core/auto_harness.py` 仅依赖标准库 + core 内部模块，无网络、无 GUI、无 LLM key
时全链路确定性可跑——与 decoder 同一工程纪律。

## 11. 路线图

| 能力 | 状态 | 说明 |
|---|---|---|
| HarnessSpec 代码准入 `check_harness` | ✅ 已落地 | 与 check_scene 同构，10 种拒绝码 |
| 确定性装配与执行 `Harness.run` | ✅ 已落地 | pre/post 守卫、有界重试、显式降级 |
| 差分评估 `compare_harnesses` | ✅ 已落地 | OFF/ON 取差分，三态 + inconclusive |
| 演化算子 `evolve` | ✅ 已落地 | O1 换风格 / O2 裁守卫 / O3 扩预算 |
| 与 stuck 闭环融合 `evolve_for_stuck` | ✅ 已落地 | 卡壳信号直接触发 evolve（换风格+补 scene），而非仅轮换风格 |
| LLM 设计 `suggest_harness` | ✅ 已落地 | 普通模式 + 容错 JSON，失败带原因重试 1 次 |
| 学习闭环回写 `apply_to_learner` | ✅ 已落地 | record_evaluation meta=harness 轨迹 |
| UI 接入 | ✅ 已落地 | 教学会话页：卡壳时展示演化候选卡 + 一键启用（`_on_adopt_harness` 持久化并按新 style 重讲）；harness 状态按资产持久化 `harness_state.json` |
| 真实成本模型 | ✅ 已落地 | `estimate_cost(tool, args, result)` = 固定基础（TOOL_COST）+ 内容规模（字符数≈token，每 100 字符 1 单位）；run 循环/重试全部接入，budget_ok 感知"昂贵的长讲解" |
| 演化历史审计链 | ✅ 已落地 | `harness_state.json` 顶层 `_history` append-only 演化事件（stuck/manual/steady + 时间 + old→new 摘要）；`save_harness_state` 保留审计链不被冲掉；教学视图渲染历史块（增量去重） |
| 跨资产 harness 泛化 | ✅ 已落地 | `asset_profile` 资产画像 → `transfer_eligibility` 前提三态（eligible/mismatch/inconclusive）→ `evaluate_transfer` 目标资产上 OFF/ON 双配置差分（收益差分 + 计分覆盖度差分，gain/loss/noise/verify 四态推荐）→ `adopt_harness_for_asset` 迁移采纳（持久化 + 审计链 reason="transfer"）；`_sim_score` 内容感知（定义长度影响基准分）；UI：卡壳分支跨资产候选检测 + 迁移建议卡 + 一键迁移启用重讲 |
| 演化算子信号化 | ✅ 已落地 | 三层信号 → 三算子：stuck（`stuck_concepts` → O1）；regression（`regression_detection` 从好变差 → O2 裁守卫，reason="regression"）；会话报告统计（`persist_session_report` `_sessions` append-only 有界 + `aggregate_reports` + `evolve_from_sessions` → O2/O3）。安全铁律：`SAFE_GUARDS` 永不裁（旧实现会裁 safe_only，已修正）；`save_harness_state` 保留 `_sessions` 不冲信号底座；UI：紫色回归演化卡 + 采纳审计 reason 区分 |
| 联合演化（三层信号融合） | ✅ 已落地 | `detect_signals` 统一信号检测 → `_o2_target_fusion` 回归假设 × 会话实际触发仲裁（真实数据优先于假设）→ `evolve_joint` 融合决策：候选按因果强度 O2>O1>O3、同算子跨源去重、reason 触发家族串（stuck→regression→sessions）、diagnosis 可解释行；UI：青色联合演化卡（多信号并发，正文含诊断）+ 采纳审计 reason 记录家族串 + 历史块复合 reason 拆分本地化 |

## 12. 关联文档

- `AGENTS.md` 设计理念第 12/13 条（代码强制准入 + 知识解码铁律）
- `docs/OmniScientist_Inspiration.md`（开放推理 + 确定性外壳的来源）
- `docs/Knowledge_Decoder.md`（SceneSpec → check_scene → 确定性渲染，本策略的直接前身）
- `expert_anything/core/auto_harness.py` / `tests/test_auto_harness.py`（92 例确定性测试：准入/执行/演化/信号化/成本/审计链/跨资产迁移）；`tests/test_ui.py`（48 例，含迁移建议卡与回归演化卡）
