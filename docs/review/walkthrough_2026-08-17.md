# ExpertAnything 真实用户路径走查（2026-08-17）

> P0 走查：导入一本书 → 教学 → 评估 → 导出报告。
> 方式：无头跑通 UI 处理器调用的同一条核心链路（extract → teacher → teach → evaluate → export），
> 逐环节核查交互细节与 LLM 输出质量，并产出改进清单。
> 真实数据未被改动（未调用 save_learner；临时资产未落盘）。

## 环境

- LLM：已配置（`agnes-2.0-flash`，`api.agnes-ai.cn`）。直连 chat 正常。
- 走查样本：自包含数学文本《数学归纳法》（约 600 字，含基例/归纳步/良序原理/强归纳）。
- 验证：`python run_tests.py --quick` → **75 用例，0 失败**（修复前后均绿）。

## 路径验证结果

| 阶段 | 调用 | 结果 | 说明 |
|---|---|---|---|
| A 导入 | `extract_knowledge` | ✅ 修复后 `llm_extraction_v1`，6 概念 / 4 关系 | 修复前静默降级为确定性回退 |
| B 教师 | `build_teacher_model` | ✅ `status=done`，6 笔记 / 0–2 异常 | 笔记含 significance / prerequisites / misconceptions，质量高 |
| C 教学 | `Tutor.teach` × 3 风格 | ⚠️ `例子`/`拆解步骤` 的「讲解」仅 15 字 = 定义原文 | `图示` 讲解含图谱上下文（77 字） |
| D 评估 | `Tutor.evaluate` 强/弱答 | ✅ 强 1.00 / 弱 0.00，反馈合理 | 评分区分度正常 |
| E 导出 | `_on_export_report` 内容 | ✅ 含 16 概念掌握度概览 | 纯文本，功能可用 |

## 发现与改进清单（按优先级）

### 🔴 P0 — 导入链路静默崩溃（已修复）

- **现象**：`extract_knowledge` 在 LLM 返回的 JSON 中某字段为**列表而非字符串**（如 `"name": ["A","B"]`）时，
  `_assemble` 里 `(c.get("name") or "").strip()` 抛 `AttributeError: 'list' object has no attribute 'strip'`。
  因为 `extract_knowledge` 吞掉**所有**异常，导入静默降级为 `llm_failed_fallback_v1`（确定性标题抽取），
  用户拿到的是规则抽取的占位概念，而非 LLM 抽取结果——且仅有进度条一行小字提示。
- **复现**：可稳定复现（这是代码缺陷，非偶发网络抖动）。
- **已修复**：`extraction.py` 新增 `_as_str` / `_as_str_list` 类型强转，覆盖 concepts/relations/learning_path/chapters
  的所有字段；`_assemble` 与分块合并路径均改用之。验证：列表型字段现被安全扁平化（`"数学归纳法 归纳证明"`），不再崩溃；75 测试仍绿。
- **仍建议（UX）**：
  1. 给 `_extract_with_llm` 加**单次重试**（瞬时段错误也能救回，无需用户重导）。
  2. 导入结果页/仪表盘用**明确的「确定性模式」横幅**告知用户 LLM 暂不可用，而非仅显示原始 `method` 字符串
     （当前 `dash_subtitle` 直接渲染 `llm_failed_fallback_v1`，无 i18n 键，对用户是天书）。

### 🟠 P1 — 教学「讲解」在 例子/拆解步骤 风格下为空壳

- **现象**：`Tutor.teach` 的 `explanation` 字段在 `例子`、`拆解步骤` 风格下恒等于概念定义原文（15 字），
  真正教学内容落在 `example` / `steps`。根因：`STYLE_HINT` 显式要求这两种风格「把重点放在 example/steps 字段」，
  模型据此把 `explanation` 留空，触发回退到 `concept.definition`（`tutor.py:235`）。
- **影响**：教学会话「讲解」卡片看起来很单薄，与别处显示的定义重复，用户会怀疑「这教学没讲东西」。
- **建议**（二选一或都做）：
  1. Prompt：三种风格都要求 `explanation` 给出 **1–2 句直觉/为什么重要**，避免空字段。
  2. UI：`TeachResultView` 当 `explanation == concept.definition` 时**隐藏冗余讲解卡**，直接呈现 example/steps。

### 🟠 P1 — 仪表盘方法字符串未本地化

- `dash_subtitle`（`main.py:1031`）直接渲染 `asset.method`（如 `llm_extraction_chunked_v1` / `llm_failed_fallback_v1`），
  无对应 i18n 键，用户看到的是内部标识符。建议映射为可读标签（「LLM 抽取」/「确定性模式」）。

### 🟡 P2 — 报告中无页面/章节锚点（已知路线图项）

- `Concept.evidence` 仅是原文片段，无页码/章节定位。路线图已列 SourceLocation（P1），建议在抽取升级时一并落地。

### 🟡 P2 — 报告导出仍为纯文本（已知路线图项）

- 路线图已列「HTML 可视化报告导出」，与「能力成长」叙事匹配，可作为下一增量。

## LLM 质量评估

- **教学 example / practice**：具体、紧扣原文证据、因概念而异，质量良好。
- **教学 图示**：能讲清概念在知识网络中的位置与关系，符合风格预期。
- **评估**：强答 `score=1.00 understood=True`、弱答 `score=0.00 understood=False`，反馈与差距点评合理。
- **教师笔记**：significance / prerequisites / misconceptions 覆盖到位，异常检测有两例（非确定性，可接受）。
- **一致性**：同一资产多次教师自检的异常数量有波动（2 ↔ 0），属 LLM 采样正常；如需稳定可降温度或多数投票。

## 人工仍需在 GUI 点击确认的项（无头无法覆盖）

1. 导入一本真实 PDF/EPUB，确认进度条、落盘、自动跳转到知识模型页的体感。
2. 概念网络图拖拽/悬停高亮/双击教学是否顺手（力导向物理手感）。
3. 教学会话三种风格切换、答题提交后掌握度是否实时刷新并持久化。
4. 语言切换（中/英/日）全量无残留硬编码。
5. 导出报告弹窗保存路径与文件内容可读性。

## 证据

- 修复文件：`expert_anything/core/extraction.py`（`_as_str` / `_as_str_list` + `_assemble` / 分块合并路径）。
- 走查脚本：`.workbuddy/walkthrough.py`（可复跑）。
- 回归：`python run_tests.py --quick` → 75/75 通过。
