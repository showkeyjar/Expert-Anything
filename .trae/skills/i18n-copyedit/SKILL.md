---
name: i18n-copyedit
description: 小白视角的 i18n 文案去技术腔与口语化精修。Use when the user says 文案/术语/技术腔/小白视角 或要求清 i18n 表残留、改三语、跑回归、补 AGENTS.md 落地记录。Do not use for 新增 i18n 键或改键名。
---

# i18n 文案精修（小白视角）

一次完整的六步流水线，每步都要有落地产物，跳步等于隐藏回归。

## 1. 建立目标词表（动手前先锁边界）

先跑一条 grep，把候选词收敛到可执行清单，不要上来就全表改。

候选词按类分组：
- **学习统计**：覆盖、覆盖度、覆盖率、抽取、判定、命中、聚合、聚类、映射、阈值
- **产品机制**：通道、审计、确定性回退、模型服务、守卫、预算、回写、轨迹
- **内部对象**：锚点（→ 原文出处 / 证据出处）、Harness（→ 教学方式 / 本课演练）
- **接口泄漏**：环境变量名（`EXPERTANYTHING_LLM_API_KEY`）、spec 内部指标名

代码：`expert_anything/core/i18n.py` 是唯一来源；键名一律不动，只改三语值。

## 2. 三语同步改写（每对 Edit 必须原子化）

- 一个键的 zh-CN / en / ja 三语值**同时提交**一次 Edit，不要分三次改。
- 占位符（`{name}`、`{pct}`、`{covered}/{total}`）必须三语一致；写完跑一次校验：
  ```python
  import re, sys; sys.path.insert(0, '.')
  from expert_anything.core.i18n import _STRINGS
  ph = re.compile(r'{([a-zA-Z_][a-zA-Z0-9_]*)}')
  bad = [(k, {lg: set(ph.findall(v.get(lg, ''))) for lg in ('zh-CN','en','ja')})
         for k, v in _STRINGS.items()
         if len({frozenset(s.values())}) != 1]
  print('placeholder mismatch:', len(bad))
  ```
- 英文自然词（coverage / summary / trace）属正常表达，只改中文腔时保留；但中文的「学习通道」「评估得分」这类**直译接口字段名**的句子，英文/日文也要对齐（channels → 学习方式 → Channels / チャネル）。

## 3. 同步修改 tests/ 里的断言

改文案一定会改到断言。改完一个键就 grep 测试目录找它的原文，逐个同步；典型命中：
- `tests/test_ui.py::TestImportExperience`（首屏断言）
- `tests/test_report.py::test_localize_method`（方法名本地化）
- `tests/test_report.py::test_build_html_basic`（三语输出断言）

改完先用 pytest 单独跑受影响类（`pytest tests/test_ui.py::TestImportExperience -q`），过了再跑全量。

## 4. 核心回归

```
python run_tests.py --quick
```
**必须看 tail 输出里的 `Ran N tests` 和 `N failures` 数字**；后台跑的 shell 也必须显式 `Select-Object -Last 15` 抓结果，不能只等退出码。

## 5. AGENTS.md 落地记录

改完一批就给 AGENTS.md 加一条「第 N 轮，YYYY-MM-DD 落地」，格式：

```
N. **改什么（第 N 轮，YYYY-MM-DD 落地）**：一句话概括本批范围，键名不动、三语同步（英文/日文的 X 属自然表达，保留）：
    - `键 A`「旧词 A1 / A2 / A3」→「新词 B1 / B2 / B3」（与 X 口径一致）；
    - `键 B` 说明；
    回归：`tests/XX.py` 断言同步改写，quick 803 例 0 失败。
```

数字按当前最大落地记录 +1 填；**不要**改历史条目，除非是回滚。

## 6. 最后交付

把本轮改了哪些键（列键名）、哪些断言、落地记录编号列出来；说清楚哪些留了英文/日文自然词没动、理由是什么。不要只说"改完了"。

## 绝对不要

- **不要**改键名（动态家族尤其 `rel_*/kind_*/teacher_status_*/domain_template_reason_*` 严禁）
- **不要**在文案里放环境变量名或 API 路径（那是排障日志，不是 UI 文案）
- **不要**把 Python dict 的「后定义覆盖先定义」当成"特性"——这是隐患，历史上已出现 6 对重复键，`test_no_duplicate_key_definitions` 是守卫
- **不要**用"检查覆盖度"这种命令式按钮文案——按钮是"看看讲得怎么样"
- **不要**跳过占位符校验——一次漏掉，三语渲染就会炸

## 历史参考

今天（2026-11-02）完成了：第 23 轮术语扫尾 + 重复键清理守卫 + 第 24 轮文案残留 + 第 25 轮文案口语化 + 第 26 轮通道/状态去技术腔 + `auto_harness.apply_to_learner` 机制泄漏修复。每一轮的具体改动与目标词表都在 AGENTS.md 第 38–43 条。
