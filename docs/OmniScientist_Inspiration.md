# OmniScientist 设计思想借鉴 → ExpertAnything 落地映射

> 来源：`docs/OmniScientist.pdf`（OmniScientist: An Omni-Modal Omni-Discipline
> AI Scientist, arXiv:2608.13558, 2026-08）。本文记录其可迁移的设计思想，
> 以及每一项在 ExpertAnything 中的具体落地点（模块 / 函数 / 测试）。

## 1. OmniScientist 核心设计思想速览

OmniScientist 是一个端到端全模态 AI 科学家：感知层 + 3 个自主 agent
（ideation / experiment / writeup）跑在一条**确定性管道**里，从原始证据
直接产出可验证的论文。抛开领域差异，它的架构思想有五条特别值得借鉴：

1. **开放推理 + 确定性外壳**（thin deterministic pipeline around open-ended
   agents）：阶段内 LLM 自由推理（ReAct），但阶段转换与输出准入由**代码强制
   校验**（code-enforced checks：idea check / rigour check / claim check）。
   "Reasoning inside a stage stays open-ended, and the process around it
   stays predictable."
2. **执行记录是唯一事实源**（execution record as the source of truth）：
   所有审计（数字溯源、claim 支持）对照执行记录，而不是对照 agent 写的文本。
3. **感知优先 / 生命周期感知**（perception-first, lifecycle-wide）：
   "The decisive issue is which relations survive the interface"——原始证据
   必须影响每个阶段（选题/设计/检查/结论），而不是被预压缩成摘要后喂给模型。
4. **空结果 → 回退重构思**（null result → re-ideate）：实验失败或零结果时
   管道回退到 ideation（上限 2 次），换问题而不是硬闯。
5. **反过度自信**（tempering）：有界搜索不能证明"首创"，于是系统自动把
   "first / never explored" 改写为 "appears under-explored"；同时对重复检验、
   HARKing、无支持的 claim 全部在代码层拦截。

## 2. 逐条映射到 ExpertAnything

ExpertAnything 是学习操作系统（Knowledge Runtime），其"科研闭环"的类比物
是"学习闭环"。两者结构同构：**开放生成（LLM）+ 确定性准入 + 可审计记录**。

| OmniScientist 思想 | ExpertAnything 落地 | 位置 |
|---|---|---|
| code-enforced checks：阶段输出必须过代码校验才能准入 | `core/checks.py`：讲解/自测/实践/评估四类 LLM 生成物的准入检查（结构完整性、讲解非定义复制、讲解必须扣住本概念、anti-template 相似度拦截） | `checks.check_lesson / check_quiz / check_practice / check_evaluation` |
| 有界重试预算（max 2 fallbacks） | `Tutor.teach / generate_quiz / generate_practice`：第一次未过检查 → 带"失败原因"重试一次 → 仍失败则降级到确定性回退（明确标注，绝不崩溃） | `core/tutor.py` |
| 执行记录是唯一事实源 | 学习轨迹：`record_evaluation(meta=...)` 记录每次作答的通道（answer/quiz/practice）、教学风格、是否轮换过策略；卡壳检测、报告、教师模型全部读这份记录 | `core/learner.py` |
| null result → re-ideate（换策略而非重复） | **卡壳闭环**：`stuck_concepts()` 从轨迹中识别"连续 N 次评估不达标"的概念 → `adaptive_path` 加 `stuck` 标签并提优先级 → `Tutor.teach` 对卡壳概念**自动轮换讲解风格**（例子→图示→拆解步骤）→ `incorporate_stuck_signal` 把卡壳写入教师模型成为可见异常 | `learner.py / tutor.py / teacher.py / main.py` |
| tempering：绝对化措辞软化 | `checks.temper_claims()`：对生成的讲解/类比做"肯定能/唯一的方法/第一次提出 → 往往能/常用的方法之一/较早提出"式改写 | `core/checks.py` |
| 数字溯源（每个数字都能追到真实输出） | 评估得分强制 clamp 到 [0,1]、feedback 不允许为空串（UI 永远有明确反馈）；历史行带 meta 轨迹 | `checks.check_evaluation` |

## 3. 为什么这些借鉴与本项目理念同源

- AGENTS.md 设计理念 1（来源约束是硬规则）：原来"铁律"只写在 prompt 里，
  是**请求**；`checks.py` 把它变成**强制**。OmniScientist 的原话恰好说明
  为什么要这样做：prompt 约束依赖模型自觉，code-enforced check 才是保证。
- 设计理念 2（教师模型走在学习者前面）：卡壳信号反哺教师模型
  （`incorporate_stuck_signal`），使"换策略重讲"成为系统可见、可追踪的
  决策，而不是无声重试。
- 模块职责（Tutor 禁止编造原文外内容）：anti-template 检查直接把
  tutor.py prompt 里的"每一个概念都必须独一无二"落成代码拦截。

## 4. 使用说明（开发者）

- 新增一类 LLM 生成物时，在 `core/checks.py` 加一个 `check_*` 函数，在
  调用处套用 **2 次尝试 + 显式降级** 的模式；重试 prompt 必须引用
  `CheckResult.reason`（让模型知道要修什么）。
- 卡壳检测参数：`stuck_concepts(state, attempts=3, threshold=None)`，
  threshold 默认取 `config.WEAKNESS_THRESHOLD`。
- UI 上卡壳概念在路径阶梯显示深红色 `卡壳·换策略重讲` 标签（i18n 键
  `tag_stuck`，三语齐全）。
- 测试：`tests/test_checks.py`（27 例），`python run_tests.py --quick` 自动包含。

## 5. 尚未落地 / 后续候选

- ~~**多评判交叉评估**~~ ✅ 已落地（2026-08-18 第二轮）：`Tutor.evaluate` 的
  LLM 路径在首轮得分落入边界区间 `[0.4, 0.6)` 时，调用第二位独立裁判
  （`ARBITER_SYSTEM`，不同视角 prompt + temperature 0.1）重新评分并取两分
  均值；明确通过/明确未通过的评分不再付费复核（预算约束）。第二裁判失败或
  返回不可解析分数时首轮结论独立成立（`judges=1`），绝不重试循环阻塞评估。
  裁判数记入学习轨迹 `meta.judges`（`main.py` 答题通道）。测试：
  `tests/test_checks.py::TestCrossJudgeArbitration`（6 例）。
- **感知层预算**（image budget）：教学中的"图示"风格生成结构图已确定性化；
  若未来接多模态模型，应引入预算约束（何时值得渲染图）。
- ~~**claim-level 审计报告**~~ ✅ 已落地（2026-08-18 第二轮）：
  `report_html._build_trace_audit` 在离线 HTML 报告新增"轨迹审计"一节——
  每个掌握度数字对应可追溯的轨迹行（概念 × 作答次数 × 平均分 × 掌握度 ×
  学习通道），并统计策略轮换次数、双裁判复核次数、卡壳概念清单；全部从
  `learner.history` 的记录行（含 `meta` 轨迹）生成，不采信任何叙述性文本，
  对应 OmniScientist 的 claim check 页。i18n 键 `audit_*` 三语齐全。测试：
  `tests/test_report.py`（+3 例）。
