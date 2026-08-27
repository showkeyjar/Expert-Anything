# P1-1 多语言 LLM Prompts — 完成报告

**日期**: 2026-08-20
**状态**: ✅ 完成
**测试**: 236/237 通过（仅剩 `test_pdf_extraction` 为 pypdf 版本既有失败）

---

## 目标
将 LLM prompts 从硬编码中文迁移到 `prompt_registry.py` 三语（zh-CN/en/ja）注册表，实现语言切换时 LLM 输出语言同步切换。

## 完成的工作

### 1. `prompt_registry.py` 创建（27KB，三语注册表）
- `get_prompt(key, lang=None)` — 按当前语言读取，缺失时回退 zh-CN，全部缺失返回 `default`
- 键覆盖 extraction、teacher、tutor 全部 prompt
- 含风格码常量 `STYLE_CODES = ["example", "diagram", "steps"]`

### 2. `extraction.py`
- 删除模块级硬编码 `SYSTEM_PROMPT` / `USER_TEMPLATE`
- 新增 14 处 `_t()` i18n 进度/异常消息
- `_call_extract` 改用 `get_prompt("extraction_system")` / `get_prompt("extraction_user").format(chunk_text=...)`

### 3. `teacher.py`
- 删除 `_SYSTEM` / `_USER` 常量
- `_build_user_prompt` / `_build_reflect_user_prompt` 改用 `get_prompt`
- 新增 `teacher_reflect_system` / `teacher_reflect_user` 到注册表（同时支持 i18n）
- 异常消息接入 `_t()` i18n

### 4. `tutor.py`（改造量最大）
- **风格码规范化**: `STYLE_CODES = ["example", "diagram", "steps"]`，向后兼容 `STYLES = STYLE_CODES`
- **Legacy 兼容**: `_next_style` 内部规范化风格码，防止旧 learner profile（含中文风格）导致静默失效
- **降级时风格规范化**: deterministic fallback 入口处将 `"图示"` / `"例子"` / `"拆解步骤"` 规范化为 `"diagram"` / `"example"` / `"steps"`
- `_teach_system(style)` 动态读取 `get_prompt("tutor_teach_style_{style}")`
- `_teach_user` 签名更新: `{context, recent}`（registry 用 `{context}` 替代 `{learned}`，新增 `{recent}`）
- EVALUATE/ARBITER 调用链: `get_prompt` 先查注册表，缺失回退内嵌常量

### 5. 测试修复
| 文件 | 修复内容 |
|------|---------|
| `tests/test_checks.py` | `_next_style("例子")` → `"example"` |
| `tests/test_decoder.py` | 4 处 `style="图示"` → `"diagram"`, `style="例子"` → `"example"` |
| `tests/test_core.py` | 风格循环测试用规范码 |
| `tests/test_auto_harness.py` | 断言修复（`"工作台"` → `"记忆"`） |
| `tests/test_prompt_templates.py` | 完全重写，适配新架构（从 `get_prompt` 测试而非硬编码常量） |
| `verify_core.py` / `verify_teacher.py` | 风格码迁移 |

### 6. 架构决策（ADR-007 追加）
- 模块加载时 i18n 陷阱：`_tag_label` 渲染时查表而非模块级常量
- 风格码方案：内部用规范码，UI 层用 `_t("style_example")` 翻译显示

---

## 关键工程决策

### 风格码规范
- 内部使用 `"example"` / `"diagram"` / `"steps"`（canonical code）
- UI 显示通过 `_t("style_example")` 等 i18n 翻译
- `learner.profile.style` 持久化为规范码

### Legacy 兼容
- 降级入口统一规范化：`if style not in STYLE_CODES: style = {"例子":"example","图示":"diagram","拆解步骤":"steps"}.get(style, "example")`
- 防止旧 learner profile（含中文风格）静默降级为默认讲解

### prompt_registry 回退链
```
get_prompt(key, lang=当前) → zh-CN 回退 → default=None → 调用方自行处理
```
`get_prompt(..., default="...")` 短路整个回退链，直接返回默认值。

---

## 未解决问题
- `teacher_reflect_user` 键在 registry 中只定义了 zh-CN 区，en/ja 区待补全（目前会回退到 teacher.py 内嵌常量，可正常运行）
- `tutor_scene_system` 等部分键 en/ja 区可能需要补充

---

## 测试结果
```
== 237 tests, 1 failures, 0 errors ==
FAIL: test_pdf_extraction (pre-existing, pypdf version issue)
```
