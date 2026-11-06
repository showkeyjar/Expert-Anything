# 语义关系待人工复核清单

> 由 `verify_semantic_extraction.py` 自动生成。**这不是金标**：只列出现象，
> 不判断对错。请在「你的判断」列填 ✅正确 / ✖错误 / ?拿不准，并可补充说明。
> 每条都给出证据原文与字符偏移，可直接跳原文核对。

## docs/电力交易领域学习方案.md

- 模型：`qwen3.5-35b`，温度 0.0，运行 2 次
- 接受语义边：8 条；六类分布：{'prereq': 4, 'part_of': 2, 'related': 2}
- 证据形态：逐字 6 / 同句恢复 2 / 拒绝 8

| # | 状态 | source → target | type | label | 证据（前 120 字） | 位置(行/字符) | 难例类型 | 你的判断 |
|---|---|---|---|---|---|---|---|---|
| 1 | accepted | 市场架构 → 电价机制 | prereq | 学习路径中位于电价机制之前 | QUICK_PATH = ["ch-market", "ch-player", "ch-price", "ch-concept"] | L71 @2804 | 证据未点名两端 |  |
| 2 | accepted | 电价机制 → 交易流程 | prereq | 学习路径中位于交易流程之前 | QUICK_PATH = ["ch-market", "ch-player", "ch-price", "ch-concept"] | L71 @2804 | 证据未点名两端 |  |
| 3 | accepted | generate_glossary → DOMAIN_TEMPLATES | prereq | 数据来源 | 数据唯一来源为领域模板 `chapters` 下已登记概念 | L319 @10995 | 证据未点名两端 |  |
| 4 | accepted | carbon_trading → DOMAIN_TEMPLATES | part_of | 被包含于 | `DOMAIN_TEMPLATES` 现含 `electricity_trading` 与 `carbon_trading`。 | L459 @17674 | 同句恢复(别名/指代) |  |
| 5 | accepted | detect_domain_from_title → carbon_trading | related | 检测目标 | 使“碳排放权交易市场”这类标题命中碳域而不误判为电力域 | L463 @17892 | 证据未点名两端、对比/弱关联 |  |
| 6 | accepted | electricity_trading → carbon_trading | related | 并列领域 | `DOMAIN_TEMPLATES` 现含 `electricity_trading` 与 `carbon_trading`。 | L459 @17674 | 同句恢复(别名/指代)、对比/弱关联 |  |
| 7 | 被拒：原文无同句同时点名两端（别名/指代/跨段） | 领域模板 → 电力交易领域 | part_of | 包含电力领域模板 | domain_templates.py + DOMAIN_TEMPLATES（当前电力 + 碳交易两个领域） | L0 @-1 | 难例(被闸门拒绝) |  |
| 8 | 被拒：原文无同句同时点名两端（别名/指代/跨段） | 专用解码器 → 电力交易领域 | related | 为电力领域生成场景 | Phase 2 专用解码器...decoder_electricity.py 提供 4 类策展场景 | L0 @-1 | 难例(被闸门拒绝) |  |
| 9 | 被拒：原文无同句同时点名两端（别名/指代/跨段） | 用户画像识别 → 快速上手路径 | causes | 基于画像推荐路径 | 识别用户背景，推荐个性化学习路径...根据领域推荐路径 | L0 @-1 | 难例(被闸门拒绝) |  |
| 10 | 被拒：原文无同句同时点名两端（别名/指代/跨段） | detect_domain_from_title → get_domain_prompt | causes | 决定使用 | 按 `detect_domain_from_title` 选用领域 Prompt | L0 @-1 | 难例(被闸门拒绝) |  |
| 11 | 被拒：原文无同句同时点名两端（别名/指代/跨段） | detect_user_profile → Tutor.enrich | causes | 数据供给 | `Tutor.enrich` 注入术语区与难度提示... 画像识别... 产出 `difficulty_hint` | L0 @-1 | 难例(被闸门拒绝) |  |
| 12 | 被拒：端点概念未通过逐字锚定 | quick_path → learning_path | contrast | 替代 | 学习路径被改写为模板 `quick_path` | L394 @13791 | 难例(被闸门拒绝) |  |
| 13 | 被拒：原文无同句同时点名两端（别名/指代/跨段） | CARBON_TRADING_TEMPLATE → DOMAIN_TEMPLATES | part_of | 注册于 | 只需替换 `DOMAIN_TEMPLATES` 字典中的内容... `CARBON_TRADING_TEMPLATE` | L0 @-1 | 难例(被闸门拒绝) |  |
| 14 | 被拒：原文无同句同时点名两端（别名/指代/跨段） | resolve_template_concept_id → scene_for_concept | related | 复用解析逻辑 | `resolve_template_concept_id` ... 解码器侧 `get_scene_for_concept` 复用同一解析 | L0 @-1 | 难例(被闸门拒绝) |  |
| 15 | 被拒：原文无同句同时点名两端（别名/指代/跨段） | carbon_trading → DOMAIN_PROMPT_SUFFIXES | related | 配置键 | DOMAIN_PROMPT_SUFFIXES 新增 "carbon_trading": "carbon" | L0 @-1 | 难例(被闸门拒绝) |  |
| 16 | 被拒：端点概念未通过逐字锚定 | COVERAGE_SCORE_constants → Phase 4 用户引导 | prereq | 依赖阈值 | 画像判定阈值（COVERAGE_* / SCORE_* 常量）为启发式取值，尚待真实学习者数据标定 | L0 @-1 | 难例(被闸门拒绝) |  |
| 17 | accepted | domain_concept_skeleton → extraction_system_electricity | part_of | 注入于 | 注入 `domain_concept_skeleton()` 概念骨架 | L310 @10481 | 证据只点名一端 |  |
| 18 | accepted | scene_for_concept → check_scene | prereq | 依赖校验 | 生成 4 场景 → `check_scene` 准入 | L367 @12323 | 证据只点名一端 |  |

## docs/AutoHarness_Strategy.md

- 模型：`qwen3.5-35b`，温度 0.0，运行 2 次
- 接受语义边：14 条；六类分布：{'prereq': 6, 'causes': 5, 'related': 1, 'contrast': 2}
- 证据形态：逐字 7 / 同句恢复 9 / 拒绝 3

| # | 状态 | source → target | type | label | 证据（前 120 字） | 位置(行/字符) | 难例类型 | 你的判断 |
|---|---|---|---|---|---|---|---|---|
| 1 | accepted | HarnessSpec → check_harness | prereq | 需通过准入检查 | \| HarnessSpec 代码准入 `check_harness` \| ✅ 已落地 \| 与 check_scene 同构，10 种拒绝码 \| | L382 @15489 | 同句恢复(别名/指代) |  |
| 2 | accepted | regression_detection → 演化算子 | causes | 触发O2算子 | \| 演化算子信号化 \| ✅ 已落地 \| 三层信号 → 三算子：stuck（`stuck_concepts` → O1）；regression（`regression_detection` 从好变差 → O2 裁守卫，reason="r | L393 @16704 | 同句恢复(别名/指代)、长跨度 |  |
| 3 | accepted | evaluate_transfer → adopt_harness_for_asset | related | 后续 | \| 跨资产 harness 泛化 \| ✅ 已落地 \| `asset_profile` 资产画像 → `transfer_eligibility` 前提三态（eligible/mismatch/inconclusive）→ `evalu | L392 @16384 | 同句恢复(别名/指代)、长跨度、对比/弱关联 |  |
| 4 | accepted | detect_signals → _o2_target_fusion | prereq | 前置步骤 | \| 联合演化（三层信号融合） \| ✅ 已落地 \| `detect_signals` 统一信号检测 → `_o2_target_fusion` 回归假设 × 会话实际触发仲裁（真实数据优先于假设）→ `evolve_joint` 融合决 | L394 @17065 | 同句恢复(别名/指代)、长跨度 |  |
| 5 | accepted | _o2_target_fusion → evolve_joint | prereq | 前置步骤 | \| 联合演化（三层信号融合） \| ✅ 已落地 \| `detect_signals` 统一信号检测 → `_o2_target_fusion` 回归假设 × 会话实际触发仲裁（真实数据优先于假设）→ `evolve_joint` 融合决 | L394 @17065 | 同句恢复(别名/指代)、长跨度 |  |
| 6 | accepted | evolve_joint → check_harness | prereq | 依赖 | evolve_joint()          ← 候选按因果强度排序（O2 > O1 > O3），全部再过 check_harness | L316 @12889 | 同句恢复(别名/指代) |  |
| 7 | accepted | LEH → HarnessSpec | contrast | 对照 | \| LEH（评测工装） \| 任务 YAML → 模型 → 指标聚合 \| HarnessSpec → provider → report \| | L357 @14555 | 同句恢复(别名/指代)、对比/弱关联 |  |
| 8 | accepted | ToolTrust → safe_only | contrast | 对照 | - `safe_only`：ToolTrust gatekeeper——需要沙箱的工具在 sandbox=none 时 fail-closed， | L101 @4161 | 同句恢复(别名/指代)、列表项、对比/弱关联 |  |
| 9 | 被拒：端点概念未通过逐字锚定 | check_harness → build_harness | prereq | 通过后进行装配 | auto_harness.check_harness() 代码准入... → 确定性装配 build_harness() | L0 @-1 | 难例(被闸门拒绝) |  |
| 10 | 被拒：端点概念未通过逐字锚定 | build_harness → Harness.run | prereq | 装配后执行 | 确定性装配 build_harness()... → 确定性执行 Harness.run() | L0 @-1 | 难例(被闸门拒绝) |  |
| 11 | 被拒：端点概念未通过逐字锚定 | Harness.run → 轨迹 | causes | 产生轨迹 | Harness.run() 返回 append-only 事件流 | L0 @-1 | 难例(被闸门拒绝) |  |
| 12 | 被拒：原文无同句同时点名两端（别名/指代/跨段） | 轨迹 → 差分评估 | related | 提供评估数据 | compare_harnesses(control_reports, treated_reports...) | L0 @-1 | 难例(被闸门拒绝) |  |
| 13 | 被拒：原文无同句同时点名两端（别名/指代/跨段） | 轨迹 → 演化算子 | related | 提供演化证据 | evolve(spec, report, candidates_limit=3) 从轨迹证据推出下一代 harness 候选 | L0 @-1 | 难例(被闸门拒绝) |  |
| 14 | 被拒：端点概念未通过逐字锚定 | 能力接缝 → build_harness | related | 支持注入替换 | build_harness(spec, providers={...}) 支持任意槽位注入 | L0 @-1 | 难例(被闸门拒绝) |  |
| 15 | 被拒：端点概念未通过逐字锚定 | dsh → build_harness | contrast | 对照 | dsh（Agent 驾驭层） ... AutoHarness 的对应物 build_harness | L0 @-1 | 难例(被闸门拒绝) |  |
| 16 | 被拒：端点概念未通过逐字锚定 | SWE-agent → teach_styles | contrast | 对照 | SWE-agent（ACI） ... AutoHarness 的对应物 teach_styles 轮换表 | L0 @-1 | 难例(被闸门拒绝) |  |
| 17 | 被拒：端点概念未通过逐字锚定 | SceneSpec → 联合演化 | related | 前身关系 | SceneSpec → check_scene → 确定性渲染，本策略的直接前身 | L400 @17474 | 难例(被闸门拒绝) |  |
| 18 | 被拒：原文无同句同时点名两端（别名/指代/跨段） | SAFE_GUARDS → O2 裁守卫 | related | 约束关系 | O2 裁守卫... 安全铁律：`SAFE_GUARDS` 永不裁 | L0 @-1 | 难例(被闸门拒绝) |  |
| 19 | accepted | stuck_concepts → O1 | causes | 驱动 | learner.stuck_concepts ──▶ O1 换风格+补 scene | L218 @8611 | 普通 |  |
| 20 | accepted | regression_detection → O2 | causes | 驱动 | regression_detection    ──▶ O2 裁守卫 | L219 @8682 | 普通 |  |
