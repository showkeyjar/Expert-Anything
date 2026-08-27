# P1-2: generate_practice / generate_quiz / evaluate_practice i18n — 完成

**日期**: 2026-08-20（晚）
**状态**: ✅ 完成
**测试**: 236/237（仅 `test_pdf_extraction` 既有失败）

---

## 目标
将 `generate_practice`、`generate_quiz`、`evaluate_practice` 三个 LLM 调用从硬编码中文迁移到 `prompt_registry.py` 三语注册表，实现语言切换时题目语言同步切换。

## 完成的工作

### 1. Registry 格式纠错（关键）
发现 `prompt_registry.py` 中 practice/quiz 的 registry 键**格式错误**（错误字段名 `task/type/hint` 多了一层包裹、`{{` 转义错误、malformed JSON 结构），且 tutor.py 根本没有调用这些键。

已重写三语（ZH/EN/JA）的四个键格式：
- `tutor_practice_system` + `tutor_practice_user` → 输出 `{"task","hint","reference"}`
- `tutor_quiz_truefalse_system` + `tutor_quiz_truefalse_user` → 输出 `{"type","question","correct","explanation"}`
- `tutor_quiz_ordering_system` + `tutor_quiz_ordering_user` → 输出 `{"type","question","options","correct_order","explanation"}`

### 2. `tutor.py` 三方法迁移

| 方法 | 改动 |
|------|------|
| `generate_practice` | 删除 inline 中文 `sys_prompt`+`user`；改用 `get_prompt("tutor_practice_system/user")`；`_lang_instruction()` 移入 system prompt 末尾 |
| `generate_quiz` | 删除 inline 中文 `sys_prompt`（ordering/true_false 两分支）；改用 `get_prompt("tutor_quiz_*_system/user")`；`_lang_instruction()` 移入 system prompt 末尾 |
| `evaluate_practice` | 删除 inline 中文 `sys_prompt`+`user`；改用 `get_prompt("tutor_evaluate_system/user")` |

保留 `checks.check_practice` / `checks.check_quiz` 校验逻辑不变。

### 3. 同步修复
- 删除 `ui/widgets/teach_widgets_raw.py`（800行未引用死文件）
- 清理所有临时扫描脚本（9个）

---

## 技术细节

### Registry 格式 vs checks.py 期望
`checks.check_quiz` 期望字段：
```
true_false: {"type":"true_false","question":"...","correct":bool,"explanation":"..."}
ordering:   {"type":"ordering","question":"...","options":[...],"correct_order":[...],"explanation":"..."}
```
旧 registry 输出 `{{"quizzes":[...]}}` 多层包裹 → `checks.check_quiz` 返回 `CheckResult(ok=False, ...)` → 2次重试后返回 None，测试无法覆盖真实 LLM 路径。

### _lang_instruction() 拼接位置
所有调用点统一：`_lang_instruction()` 追加到 system prompt 末尾（而非 user prompt），避免用户看到语言指令。

---

## 验证
- `py_compile tutor.py` → OK
- `run_tests.py --quick` → 236/237（仅 PDF 既有失败）
