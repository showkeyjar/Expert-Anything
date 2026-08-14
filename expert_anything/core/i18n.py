"""Minimal i18n layer for ExpertAnything.

All user-facing strings live in the ``_STRINGS`` table below, keyed by a stable
identifier. ``t(key, **kwargs)`` returns the string for the active language,
formatting any ``{placeholder}`` with the supplied kwargs. Unknown keys return
the key itself so missing translations are visible rather than silent.

The active language is persisted to ``data/lang.json`` so it survives restarts.
"""
from __future__ import annotations

import json
from pathlib import Path

from expert_anything.core import config

LANGS = {
    "zh-CN": "中文",
    "en": "English",
    "ja": "日本語",
}
DEFAULT_LANG = "zh-CN"
_LANG_FILE = config.DATA_DIR / "lang.json"

# Values used as canonical, language-neutral option keys (stored in learner.json).
# Their display text is translated via the *_opt keys below.
BASELINE_OPTS = ["novice", "some", "practiced"]
STYLE_OPTS = ["example", "diagram", "steps"]

_STRINGS: dict[str, dict[str, str]] = {
    "app_tagline": {"zh-CN": "个人学习 OS", "en": "Personal Learning OS"},
    "import_asset": {"zh-CN": "＋ 导入知识资产", "en": "+ Import Knowledge"},
    "knowledge_model": {"zh-CN": "知识模型", "en": "Knowledge Model"},
    "teach_session": {"zh-CN": "教学会话", "en": "Tutor Session"},
    "learner_model": {"zh-CN": "学习者模型", "en": "Learner Model"},
    "cognitive_nav": {"zh-CN": "认知导航", "en": "Cognitive Map"},
    "read_source": {"zh-CN": "阅读原文", "en": "Read Source"},
    "assets_label": {"zh-CN": "知识资产", "en": "Knowledge Assets"},
    "asset_item": {"zh-CN": "{title}  ·  {count} 概念", "en": "{title}  ·  {count} concepts"},
    "delete_tip": {"zh-CN": "删除该资产", "en": "Delete this asset"},
    "confirm_delete_title": {"zh-CN": "确认删除知识资产？", "en": "Delete this knowledge asset?"},
    "confirm_delete_body": {
        "zh-CN": "将永久删除《{title}》及其抽取的概念、关系、教师模型与学习记录，此操作不可恢复。",
        "en": "This permanently deletes \u201c{title}\u201d and all extracted concepts, relations, teacher model and learning records. This cannot be undone.",
    },
    "cancel": {"zh-CN": "取消", "en": "Cancel"},
    "delete": {"zh-CN": "删除", "en": "Delete"},
    "processing": {"zh-CN": "正在处理…", "en": "Processing…"},
    "processing_hint": {
        "zh-CN": "导入与知识分析需要一些时间，请勿关闭窗口或重复点击。",
        "en": "Import and analysis take a while. Please don't close the window or click repeatedly.",
    },
    "progress_note": {
        "zh-CN": "处理进度会实时更新。若长时间无变化，请检查网络（LLM 接口是否可达）。",
        "en": "Progress updates live. If it stalls for long, check your network (LLM endpoint reachability).",
    },
    "import_title": {"zh-CN": "导入知识资产", "en": "Import Knowledge"},
    "import_subtitle": {
        "zh-CN": "支持 EPUB / PDF / Markdown / TXT，或直接粘贴任意知识内容。",
        "en": "Supports EPUB / PDF / Markdown / TXT, or paste any knowledge content directly.",
    },
    "paste_label": {
        "zh-CN": "或直接粘贴内容（书摘 / 论文 / 笔记 / 网页 / 个人经验）",
        "en": "Or paste content directly (excerpts / papers / notes / web pages / personal experience)",
    },
    "asset_name": {"zh-CN": "资产名称", "en": "Asset name"},
    "no_llm_note": {
        "zh-CN": "（未检测到 LLM Key，将使用确定性降级抽取，深度有限）",
        "en": "(No LLM key detected; using deterministic fallback extraction with limited depth)",
    },
    "choose_file": {"zh-CN": "选择文件…", "en": "Choose file…"},
    "generate": {"zh-CN": "生成知识包", "en": "Generate Knowledge Pack"},
    "no_content": {"zh-CN": "请提供材料内容。", "en": "Please provide material content."},
    "extracting": {"zh-CN": "正在解析与抽取知识模型…", "en": "Parsing and extracting knowledge model…"},
    "self_learning": {"zh-CN": "正在自我学习：深加工概念、扫描异常…", "en": "Self-learning: deepening concepts, scanning for anomalies…"},
    "import_done": {
        "zh-CN": "完成：{title}（{n_concepts} 概念，方法={method}；自我学习={status}，异常 {n_anom} 条）",
        "en": "Done: {title} ({n_concepts} concepts, method={method}; self-learning={status}, {n_anom} anomalies)",
    },
    "process_error": {"zh-CN": "处理出错：{exc}", "en": "Error: {exc}"},
    "import_failed": {"zh-CN": "导入失败：{exc}", "en": "Import failed: {exc}"},
    "knowledge_model_header": {"zh-CN": "知识模型", "en": "Knowledge Model"},
    "no_asset": {"zh-CN": "请先导入一个知识资产。", "en": "Please import a knowledge asset first."},
    "fallback_warn": {
        "zh-CN": "⚠ 该资产未经过 LLM 深加工（方法={method}）：当前仅是文本结构索引，概念定义与关系可能不完整。配置 EXPERTANYTHING_LLM_API_KEY 后重新导入，可得到带证据的定义、关系与异常检测。",
        "en": "⚠ This asset was not deep-processed by the LLM (method={method}): it is only a text-structure index; concept definitions and relations may be incomplete. Re-import after setting EXPERTANYTHING_LLM_API_KEY to get evidence-backed definitions, relations and anomaly detection.",
    },
    "knowledge_subtitle": {"zh-CN": "来源：{name} ｜ 方法：{method}", "en": "Source: {name} ｜ Method: {method}"},
    "total_concepts": {"zh-CN": "总概念", "en": "Total"},
    "mastered": {"zh-CN": "已掌握", "en": "Mastered"},
    "partial": {"zh-CN": "学习中", "en": "Learning"},
    "unstudied": {"zh-CN": "未学习", "en": "New"},
    "anomalies": {"zh-CN": "异常", "en": "Anomalies"},
    "learning_path": {"zh-CN": "推荐学习路径", "en": "Recommended learning path"},
    "none": {"zh-CN": "（无）", "en": "(none)"},
    "concepts_with_evidence": {"zh-CN": "概念（带原文证据）", "en": "Concepts (with source evidence)"},
    "relations": {"zh-CN": "关系", "en": "Relations"},
    "concept_notes": {"zh-CN": "概念深加工理解", "en": "Concept deep-analysis"},
    "no_relations": {"zh-CN": "（无被确认的关系；需 LLM 推断）", "en": "(No confirmed relations; LLM inference needed)"},
    "enter_teach": {"zh-CN": "进入教学会话", "en": "Start Tutor Session"},
    "reader_title": {"zh-CN": "阅读原文", "en": "Read Source"},
    "no_source": {
        "zh-CN": "（该资产未保存原文文本；多为早期版本或解析失败所致。重新导入可补全原文。）",
        "en": "(This asset has no saved source text, usually from an older version or a parsing failure. Re-import to restore it.)",
    },
    "reader_subtitle": {"zh-CN": "来源：{name}", "en": "Source: {name}"},
    "reader_full": {"zh-CN": "全文 · 共 {n} 段（原文，未经改写）", "en": "Full text · {n} paragraphs (original, unmodified)"},
    "reader_loc": {"zh-CN": "第 {i} 段 / 共 {total} 段", "en": "Paragraph {i} / {total}"},
    "reader_fragment": {"zh-CN": "片段定位（上下文已截断）", "en": "Fragment located (context truncated)"},
    "selected_fragment": {"zh-CN": "选中片段", "en": "Selected fragment"},
    "back_to_full": {"zh-CN": "← 阅读全文", "en": "← Full text"},
    "back_to_km": {"zh-CN": "← 返回知识模型", "en": "← Back to Knowledge Model"},
    "next_evidence": {"zh-CN": "下一个证据 ▶", "en": "Next evidence ▶"},
    "no_anchor_concepts": {"zh-CN": "（暂无可在原文中定位的概念）", "en": "(No concepts can be located in the source yet)"},
    "teach_title": {"zh-CN": "教学会话", "en": "Tutor Session"},
    "no_teach_concept": {"zh-CN": "该资产没有可教学的概念。", "en": "This asset has no teachable concepts."},
    "align_subtitle": {
        "zh-CN": "先对齐你的目标和基础，Tutor 据此选择讲法。",
        "en": "Let's align your goal and baseline first; the Tutor picks the approach accordingly.",
    },
    "goal_label": {"zh-CN": "学完后你想做到什么？", "en": "What do you want to be able to do after learning?"},
    "baseline_label": {"zh-CN": "现在的基础", "en": "Your current level"},
    "style_label": {"zh-CN": "更容易通过什么理解", "en": "How do you learn best"},
    "start_teach": {"zh-CN": "开始教我", "en": "Start teaching me"},
    "default_goal": {"zh-CN": "理解这份知识资产", "en": "Understand this knowledge asset"},
    "lesson_subtitle": {
        "zh-CN": "基于原文证据讲解，请把概念迁移到你的目标。",
        "en": "Explanations are grounded in the source; transfer the concept to your goal.",
    },
    "priority_hint": {
        "zh-CN": "（系统优先：该概念关联待解异常，走在你前面）",
        "en": "(System priority: this concept links to an open anomaly — walking ahead of you)",
    },
    "preparing": {"zh-CN": "Tutor 正在准备讲解…", "en": "The Tutor is preparing the explanation…"},
    "style_dd_label": {"zh-CN": "讲解方式（实时切换）", "en": "Explanation style (live switch)"},
    "no_diagram": {"zh-CN": "（无法生成结构图）", "en": "(Could not generate the structure diagram)"},
    "doubt_matched": {"zh-CN": "⚠ 系统对此仍有存疑（{kind}）：{desc}", "en": "⚠ The system still has doubts ({kind}): {desc}"},
    "doubt_none": {
        "zh-CN": "本概念暂无待解异常，但全篇还有 {n} 个待解项（见「认知导航」）。",
        "en": "No open anomalies for this concept, but {n} remain across the text (see Cognitive Map).",
    },
    "answer_label": {"zh-CN": "把它放进你的目标里，用一两句话回答", "en": "Put it into your own goal and answer in a sentence or two"},
    "vary_example": {"zh-CN": "↻ 换一个例子", "en": "↻ Another example"},
    "evaluating": {"zh-CN": "Tutor 正在评估你的回答…", "en": "The Tutor is evaluating your answer…"},
    "eval_score": {"zh-CN": "评估得分：{score} ｜ 掌握度更新为 {m}", "en": "Score: {score} ｜ Mastery updated to {m}"},
    "next_step": {"zh-CN": "下一步 →", "en": "Next →"},
    "concept_graph": {"zh-CN": "概念结构图", "en": "Concept structure map"},
    "explain_position": {"zh-CN": "讲解（概念在知识网络中的位置）", "en": "Explanation (where the concept sits in the knowledge network)"},
    "example_goal": {"zh-CN": "结合你的目标的例子", "en": "Examples tied to your goal"},
    "action_path": {"zh-CN": "用起来的行动路径", "en": "Action path to apply it"},
    "explanation": {"zh-CN": "讲解", "en": "Explanation"},
    "example_goal_focus": {"zh-CN": "结合你的目标的例子（重点）", "en": "Examples tied to your goal (key)"},
    "action_path_focus": {"zh-CN": "用起来的行动路径（重点）", "en": "Action path to apply it (key)"},
    "evidence": {"zh-CN": "原文证据", "en": "Source evidence"},
    "doubt_section": {"zh-CN": "系统存疑 · 走在你前面", "en": "System doubts · walking ahead"},
    "practice": {"zh-CN": "练习", "en": "Practice"},
    "submit_eval": {"zh-CN": "提交并评估", "en": "Submit & Evaluate"},
    "learner_title": {"zh-CN": "学习者模型", "en": "Learner Model"},
    "learner_subtitle": {"zh-CN": "跨资产累积的概念掌握度与弱项。", "en": "Cross-asset concept mastery and weaknesses."},
    "profile": {"zh-CN": "画像", "en": "Profile"},
    "profile_text": {"zh-CN": "目标：{goal} ｜ 基础：{baseline} ｜ 偏好：{style}", "en": "Goal: {goal} ｜ Baseline: {baseline} ｜ Preference: {style}"},
    "mastery": {"zh-CN": "概念掌握度", "en": "Concept mastery"},
    "no_records": {"zh-CN": "（还没有学习记录）", "en": "(No learning records yet)"},
    "weaknesses": {"zh-CN": "当前弱项", "en": "Current weaknesses"},
    "no_weakness": {"zh-CN": "（暂无明显弱项）", "en": "(No obvious weaknesses yet)"},
    "recent": {"zh-CN": "最近回应", "en": "Recent responses"},
    "history_row": {"zh-CN": "· {concept}：{score} － {feedback}", "en": "· {concept}: {score} － {feedback}"},
    "nav_title": {"zh-CN": "认知导航", "en": "Cognitive Map"},
    "nav_no_asset": {"zh-CN": "请先导入一个知识资产，系统会先做自我学习。", "en": "Import a knowledge asset first; the system will self-learn."},
    "nav_no_self": {"zh-CN": "该系统尚未生成自我认知。", "en": "This asset has no self-cognition yet."},
    "gen_self": {"zh-CN": "生成自我认知", "en": "Generate self-cognition"},
    "why_important": {"zh-CN": "为什么重要：", "en": "Why it matters: "},
    "prereq": {"zh-CN": "前提：", "en": "Prerequisites: "},
    "connections": {"zh-CN": "连接：", "en": "Connections: "},
    "misconceptions": {"zh-CN": "常见误解：", "en": "Common misconceptions: "},
    "external_notes": {"zh-CN": "外部引入补充：", "en": "External additions: "},
    "learner_signals": {"zh-CN": "学习者真实信号：", "en": "Learner's real signals: "},
    "not_deep": {"zh-CN": "（尚未深加工，需配置 LLM 后重新自检）", "en": "(Not deep-processed yet; re-run self-check after configuring the LLM)"},
    "anomaly_section": {"zh-CN": "异常 / 待解清单（{n} 条，系统走在学生前面）", "en": "Anomalies / open items ({n}, system walks ahead)"},
    "no_anomaly": {"zh-CN": "（未检测到异常 / 待解项）", "en": "(No anomalies / open items detected)"},
    "recheck": {"zh-CN": "重新自检", "en": "Re-run self-check"},
    "lang_label": {"zh-CN": "语言", "en": "Language"},
    "evidence_label": {"zh-CN": "原文证据：", "en": "Source evidence: "},
    "no_definition": {"zh-CN": "（无定义）", "en": "(no definition)"},
    "read_source_link": {"zh-CN": "阅读原文 →", "en": "Read source →"},
    "concept_structure": {"zh-CN": "概念结构（层级 / 网状）", "en": "Concept structure (hierarchy / network)"},
    "no_hierarchy": {"zh-CN": "（暂无层级关系，按学习路径顺序列出）", "en": "(No hierarchy yet; listed in learning-path order)"},
    "concept_map_net": {"zh-CN": "概念网络图", "en": "Concept network map"},
    "concept_map_net_title": {"zh-CN": "概念网络图（按掌握度着色）", "en": "Concept network map (coloured by mastery)"},
    "no_map": {"zh-CN": "（关系太少，暂无可绘制的网络图）", "en": "(Too few relations to draw a network map yet)"},
    "evidence_locations": {"zh-CN": "原文证据（共 {n} 处）", "en": "Source evidence ({n} locations)"},
    "also_referenced": {"zh-CN": "也被这些概念引用", "en": "Also referenced by"},
    "tree_tip": {"zh-CN": "（缩进表示层级，每一层是上一层的子概念）", "en": "(Indentation shows hierarchy; each level is a sub-concept of the one above)"},
    "net_tip": {"zh-CN": "（箭头表示概念之间的关系，节点为概念）", "en": "(Arrows are relations between concepts; nodes are concepts)"},
    "loc_concept": {"zh-CN": "定位：{name}", "en": "Located: {name}"},
    # --- per-concept learning / graph (issues 2 & 3) ---
    "learn_concept": {"zh-CN": "讲解", "en": "Teach me"},
    "learn_concept_full": {"zh-CN": "讲解此概念", "en": "Teach this concept"},
    "concept_graph_btn": {"zh-CN": "关系图谱", "en": "Concept map"},
    "concept_graph_view": {"zh-CN": "概念关系图谱", "en": "Concept relationship map"},
    "graph_focus_tip": {"zh-CN": "（围绕「{name}」的局部网络：高亮节点即本概念，连线为它与邻近概念的关系）", "en": "(Local network around \u201c{name}\u201d: the highlighted node is this concept; edges are its relations to neighbours)"},
    "neighbor_relations": {"zh-CN": "邻近关系", "en": "Neighbouring relations"},
    "no_neighbors": {"zh-CN": "（该概念在模型中没有显式的关系连线；可在原文中对照理解）", "en": "(No explicit relation edges for this concept in the model; cross-check it in the source)"},
    "back_to_km_from_graph": {"zh-CN": "← 返回知识模型", "en": "← Back to Knowledge Model"},
    "rel_to": {"zh-CN": "{label} → {name}", "en": "{label} → {name}"},
    "rel_from": {"zh-CN": "← {label} · {name}", "en": "← {label} · {name}"},
    "rel_default": {"zh-CN": "关联", "en": "linked"},
    "definition_lbl": {"zh-CN": "定义", "en": "Definition"},
    # --- learner model upgrade (issue 5) ---
    "learner_overview": {"zh-CN": "学习概览", "en": "Learning overview"},
    "progress_done": {"zh-CN": "已学 {done}/{total} 个概念", "en": "{done}/{total} concepts studied"},
    "avg_mastery": {"zh-CN": "平均掌握度", "en": "Average mastery"},
    "mastery_map": {"zh-CN": "掌握度图谱", "en": "Mastery map"},
    "graph_legend_mastery": {"zh-CN": "节点颜色＝掌握度：绿=已掌握，橙=薄弱，灰=未学", "en": "Node colour = mastery: green=mastered, orange=weak, grey=not studied"},
    "recommend_next": {"zh-CN": "推荐下一步", "en": "Recommended next"},
    "recommend_reason_anom": {"zh-CN": "该概念关联待解异常，建议优先突破", "en": "Linked to an open anomaly — tackle it first"},
    "recommend_reason_weak": {"zh-CN": "当前掌握度最低，建议优先补习", "en": "Lowest mastery — review it next"},
    "recommend_reason_path": {"zh-CN": "学习路径上的下一个未掌握概念", "en": "Next unmastered concept on the path"},
    "recommend_reason_foundation": {"zh-CN": "基础前置概念，建议先掌握", "en": "Foundational prerequisite — learn it first"},
    "recommend_reason_unblock": {"zh-CN": "掌握后可解锁 {n} 个下游概念", "en": "Unlocks {n} downstream concepts once mastered"},
    "recommend_reason_ready": {"zh-CN": "前置概念已掌握，现在就能学", "en": "Prerequisites done — ready to study now"},
    "recommend_reason_blocked": {"zh-CN": "前置概念尚未掌握，建议先补齐", "en": "Prerequisites not yet mastered — review them first"},
    "adaptive_path_step": {"zh-CN": "第 {n} 步", "en": "Step {n}"},
    "adaptive_path_empty": {"zh-CN": "（已掌握全部概念，或暂无可推荐项）", "en": "(All concepts mastered, or nothing to recommend yet)"},
    "click_learn": {"zh-CN": "点击学习 →", "en": "Learn →"},
    "no_mastery_yet": {"zh-CN": "（还没有学习记录，先去「教学会话」学几个概念吧）", "en": "(No learning records yet — learn a few concepts in the Tutor Session first)"},
    "weak_click_hint": {"zh-CN": "点击薄弱概念可前往学习", "en": "Click a weak concept to study it"},
    # --- cognitive nav upgrade (issue 5) ---
    "nav_hub": {"zh-CN": "认知导航图", "en": "Cognitive map"},
    "nav_hub_tip": {"zh-CN": "（掌握度着色的全量概念网络，橙色描边＝待解异常。点击下方概念可前往学习）", "en": "(Full concept network coloured by mastery; orange outline = open anomaly. Click a concept below to study it)"},
    "open_anomaly_concepts": {"zh-CN": "待解异常涉及的概念（走在你前面）", "en": "Concepts tied to open anomalies (walking ahead)"},
    "explore_anomaly": {"zh-CN": "前往探索 →", "en": "Explore →"},
    "doubt_explore": {"zh-CN": "系统存疑 · 走在你前面", "en": "System doubts · walking ahead"},
    "nav_legend": {"zh-CN": "图例：● 已掌握  ● 薄弱  ● 未学  ◎ 待解异常", "en": "Legend: ● mastered ● weak ● not studied ◎ open anomaly"},
    # --- interactive graph widget ---
    "legend_mastered": {"zh-CN": "已掌握", "en": "Mastered"},
    "legend_partial": {"zh-CN": "部分掌握", "en": "Partial"},
    "legend_weak": {"zh-CN": "薄弱", "en": "Weak"},
    "legend_unstudied": {"zh-CN": "未学", "en": "Not studied"},
    "legend_anomaly": {"zh-CN": "待解异常", "en": "Open anomaly"},
    "legend_focus": {"zh-CN": "当前聚焦", "en": "Focused"},
    # ================= UI (PySide6) =================
    "nav_import": {"zh-CN": "📥 导入知识资产", "en": "📥 Import", "ja": "📥 インポート"},
    "nav_knowledge": {"zh-CN": "🌳 知识模型", "en": "🌳 Knowledge", "ja": "🌳 知識モデル"},
    "nav_map": {"zh-CN": "🗺️ 概念网络", "en": "🗺️ Concept Map", "ja": "🗺️ 概念ネットワーク"},
    "nav_source": {"zh-CN": "📖 阅读原文", "en": "📖 Source", "ja": "📖 原文を読む"},
    "nav_teach": {"zh-CN": "🎓 教学会话", "en": "🎓 Tutor", "ja": "🎓 学習セッション"},
    "nav_learner": {"zh-CN": "🧠 学习者模型", "en": "🧠 Learner", "ja": "🧠 学習者モデル"},
    "nav_teacher": {"zh-CN": "👨‍🏫 教师模型", "en": "👨‍🏫 Teacher", "ja": "👨‍🏫 教師モデル"},
    "assets_label": {"zh-CN": "知识资产", "en": "Knowledge Assets", "ja": "ナレッジ資産"},
    "quick_teach": {"zh-CN": "🎓 开始学习", "en": "🎓 Learn", "ja": "🎓 学習を始める"},
    "quick_map": {"zh-CN": "🕸 概念网络", "en": "🕸 Concept Map", "ja": "🕸 概念ネットワーク"},
    "quick_source": {"zh-CN": "📖 阅读原文", "en": "📖 Source", "ja": "📖 原文を読む"},
    "topbar_progress": {
        "zh-CN": "已掌握 {m}/{t} · 学习中 {l} · 待复习 {r}",
        "en": "Mastered {m}/{t} · Learning {l} · Due {r}",
        "ja": "習得 {m}/{t} · 学習中 {l} · 復習待ち {r}",
    },
    "topbar_no_asset": {"zh-CN": "未选择资产", "en": "No asset selected", "ja": "資産未選択"},
    "lang_label": {"zh-CN": "语言", "en": "Language", "ja": "言語"},
    "import_subtitle2": {
        "zh-CN": "支持 PDF / EPUB / Word (.docx) / Markdown / TXT / HTML，自动提取概念并构建知识图谱",
        "en": "PDF / EPUB / Word (.docx) / Markdown / TXT / HTML — concepts and a knowledge map are extracted automatically",
        "ja": "PDF / EPUB / Word (.docx) / Markdown / TXT / HTML に対応。概念と知識マップを自動抽出します",
    },
    "choose_file": {"zh-CN": "选择文件", "en": "Choose File", "ja": "ファイル選択"},
    "start_analysis": {"zh-CN": "开始分析", "en": "Analyze", "ja": "分析開始"},
    "paste_hint": {"zh-CN": "或直接粘贴学习内容…", "en": "…or paste content here", "ja": "またはここに内容を貼り付け"},
    "analyzing": {"zh-CN": "正在分析文本…", "en": "Analyzing…", "ja": "分析中…"},
    "import_file_prompt": {"zh-CN": "请先选择或输入文件名", "en": "Choose a file or enter a path first", "ja": "先にファイルを選択してください"},
    "read_failed": {"zh-CN": "读取文件失败: {e}", "en": "Failed to read file: {e}", "ja": "ファイルの読み込みに失敗: {e}"},
    "empty_content": {"zh-CN": "内容为空，请提供学习材料", "en": "Content is empty — provide material first", "ja": "内容が空です。教材を提供してください"},
    "extract_failed_text": {
        "zh-CN": "无法从文件中提取文本。扫描版 PDF 需要 OCR，暂不支持；请确认文件不是加密或损坏的。",
        "en": "Could not extract text. Scanned PDFs need OCR (not supported yet); check the file is not encrypted or corrupt.",
        "ja": "テキストを抽出できませんでした。スキャンPDFはOCRが必要です（未対応）。暗号化や破損がないか確認してください。",
    },
    "extracted_x": {"zh-CN": "已抽取 {n} 个概念", "en": "{n} concepts extracted", "ja": "{n} 個の概念を抽出"},
    "import_done": {
        "zh-CN": "知识资产《{title}》导入完成！\n概念数: {c}\n关系数: {r}",
        "en": "Asset \u201c{title}\u201d imported!\nConcepts: {c}\nRelations: {r}",
        "ja": "資産「{title}」のインポートが完了しました！\n概念: {c} / 関係: {r}",
    },
    "section_recommend": {"zh-CN": "推荐下一步", "en": "Recommended Next", "ja": "次におすすめ"},
    "section_graph": {"zh-CN": "概念网络图", "en": "Concept Network", "ja": "概念ネットワーク"},
    "legend_mastered": {"zh-CN": "已掌握", "en": "Mastered", "ja": "習得済み"},
    "legend_learning": {"zh-CN": "学习中", "en": "Learning", "ja": "学習中"},
    "legend_weak": {"zh-CN": "薄弱", "en": "Weak", "ja": "苦手"},
    "legend_unstudied": {"zh-CN": "未学", "en": "Unstudied", "ja": "未学習"},
    "legend_other_asset": {"zh-CN": "其它资产概念", "en": "Other assets", "ja": "他資産の概念"},
    "legend_focus": {"zh-CN": "聚焦/推荐", "en": "Focus / Top pick", "ja": "フォーカス/おすすめ"},
    "legend_anomaly": {"zh-CN": "系统存疑", "en": "Anomaly", "ja": "疑義あり"},
    "legend_hover": {"zh-CN": "悬停节点高亮邻居", "en": "Hover highlights neighbours", "ja": "ホバーで隣接を強調"},
    "map_info": {
        "zh-CN": "当前书 {c} 个概念（彩色）+ 其它资产 {g} 个概念（灰色）。单击节点查看概念详情，双击开始学习；滚轮缩放，拖拽平移。",
        "en": "{c} concepts here (coloured) + {g} from other assets (grey). Click a node for details, double-click to learn; wheel to zoom, drag to pan.",
        "ja": "この本の {c} 概念（色付き）+ 他資産の {g} 概念（グレー）。クリックで詳細、ダブルクリックで学習、ホイールでズーム、ドラッグで移動。",
    },
    "map_subtitle": {
        "zh-CN": "可视化概念之间的关系和层次结构",
        "en": "Visualise how concepts relate and build on each other",
        "ja": "概念間の関係と階層を可視化",
    },
    "search_placeholder": {"zh-CN": "🔍 搜索概念并定位（回车）", "en": "🔍 Search concepts (Enter)", "ja": "🔍 概念を検索（Enter）"},
    "reset_map": {"zh-CN": "复位全图", "en": "Reset View", "ja": "全体表示に戻す"},
    "scope_all": {"zh-CN": "全部资产", "en": "All assets", "ja": "全資産"},
    "scope_current": {"zh-CN": "仅当前资产", "en": "Current asset", "ja": "現在の資産のみ"},
    "zoom_fit": {"zh-CN": "适应", "en": "Fit", "ja": "フィット"},
    "zoom_in_tip": {"zh-CN": "放大", "en": "Zoom in", "ja": "拡大"},
    "zoom_out_tip": {"zh-CN": "缩小", "en": "Zoom out", "ja": "縮小"},
    "not_found_in_map": {"zh-CN": "图谱中没有名为「{kw}」的概念", "en": "No concept \u201c{kw}\u201d in the map", "ja": "マップに「{kw}」はありません"},
    "source_subtitle": {"zh-CN": "查看原始学习材料", "en": "Read the original material", "ja": "元の教材を読む"},
    "teach_hint": {"zh-CN": "选择概念 · 学习 · 答题 · 追问", "en": "Pick a concept · Learn · Answer · Ask", "ja": "概念を選ぶ · 学ぶ · 答える · 質問する"},
    "select_concept": {"zh-CN": "选择要学习的概念:", "en": "Choose a concept:", "ja": "学ぶ概念を選択:"},
    "style_label": {"zh-CN": "教学风格:", "en": "Style:", "ja": "スタイル:"},
    "style_example": {"zh-CN": "例子", "en": "Example", "ja": "例え"},
    "style_diagram": {"zh-CN": "图示", "en": "Diagram", "ja": "図解"},
    "style_steps": {"zh-CN": "拆解步骤", "en": "Steps", "ja": "ステップ"},
    "start_teach": {"zh-CN": "开始教学", "en": "Start", "ja": "開始"},
    "pick_concept_first": {"zh-CN": "请先选择一个概念", "en": "Pick a concept first", "ja": "先に概念を選択してください"},
    "concept_not_found": {"zh-CN": "未找到概念: {name}", "en": "Concept not found: {name}", "ja": "概念が見つかりません: {name}"},
    "generating_lesson": {"zh-CN": "正在生成教学内容...", "en": "Generating lesson…", "ja": "レッスンを生成中…"},
    "lesson_ready": {"zh-CN": "选择一个概念开始学习", "en": "Pick a concept to begin", "ja": "概念を選んで学習を開始"},
    "explanation": {"zh-CN": "讲解", "en": "Explanation", "ja": "解説"},
    "example": {"zh-CN": "示例", "en": "Example", "ja": "例"},
    "steps_title": {"zh-CN": "学习步骤", "en": "Steps", "ja": "ステップ"},
    "practice": {"zh-CN": "练习", "en": "Practice", "ja": "練習"},
    "answer_placeholder": {"zh-CN": "请用自己的话回答这个问题...", "en": "Answer in your own words…", "ja": "自分の言葉で答えてください…"},
    "submit_answer": {"zh-CN": "提交答案", "en": "Submit", "ja": "回答を送信"},
    "evidence_label": {"zh-CN": "原文证据（来源约束）", "en": "Source evidence", "ja": "原文の根拠"},
    "followup_title": {"zh-CN": "还有疑问？追问导师（基于原文证据回答）", "en": "Questions? Ask the tutor (grounded in the source)", "ja": "質問は？チューターに聞く（原文に基づいて回答）"},
    "followup_placeholder": {"zh-CN": "例如：这个概念和刚才讲的另一个概念有什么区别？", "en": "e.g. How does this differ from the previous concept?", "ja": "例：前の概念とどう違いますか？"},
    "ask": {"zh-CN": "追问", "en": "Ask", "ja": "質問"},
    "no_llm_followup": {"zh-CN": "（未接入 LLM，无法追问。配置 API Key 后可进行对话式追问。）", "en": "(No LLM configured — configure an API key for follow-up.)", "ja": "（LLM未設定のため質問できません。APIキーを設定してください。）"},
    "related_concepts": {"zh-CN": "关联概念（顺藤摸瓜）", "en": "Related concepts", "ja": "関連概念"},
    "eval_result": {"zh-CN": "评估结果", "en": "Evaluation", "ja": "評価結果"},
    "eval_reference": {"zh-CN": "参考回答（基于原文证据）", "en": "Reference answer (source-grounded)", "ja": "参考回答（原文に基づく）"},
    "eval_gap": {"zh-CN": "与参考的差距", "en": "Gap vs reference", "ja": "参考との差"},
    "eval_mastered": {"zh-CN": "已掌握", "en": "Mastered", "ja": "習得済み"},
    "eval_keep_going": {"zh-CN": "需继续努力", "en": "Keep going", "ja": "もう少し"},
    "no_answer": {"zh-CN": "请先输入你的回答", "en": "Enter an answer first", "ja": "回答を入力してください"},
    "no_submittable": {"zh-CN": "当前没有可提交的教学内容，请重新开始教学。", "en": "No lesson to submit — start a lesson first.", "ja": "送信できるレッスンがありません。先にレッスンを開始してください。"},
    "learner_subtitle": {"zh-CN": "跨资产累积掌握度 | {n} 个概念", "en": "Cross-asset mastery | {n} concepts", "ja": "資産横断の習得度 | {n} 概念"},
    "stat_mastered": {"zh-CN": "已掌握 (≥60%)", "en": "Mastered (≥60%)", "ja": "習得 (≥60%)"},
    "stat_learning": {"zh-CN": "学习中", "en": "Learning", "ja": "学習中"},
    "stat_due": {"zh-CN": "待复习", "en": "Due review", "ja": "復習待ち"},
    "stat_cross": {"zh-CN": "跨资产概念", "en": "Cross-asset", "ja": "資産横断の概念"},
    "overview_title": {"zh-CN": "学习总览", "en": "Overview", "ja": "学習概要"},
    "overview_summary": {
        "zh-CN": "你共接触 {total} 个概念：已掌握 {m} 个（{pct:.0%}），平均掌握度 {avg:.0%}。",
        "en": "You have met {total} concepts: {m} mastered ({pct:.0%}), average mastery {avg:.0%}.",
        "ja": "合計 {total} 概念に触れました：{m} 習得（{pct:.0%}）、平均習得度 {avg:.0%}。",
    },
    "overview_due": {
        "zh-CN": "有 {n} 个概念到了复习时间（如「{first}」），现在复习效果最好。",
        "en": "{n} concepts are due for review (e.g. \u201c{first}\u201d) — review now for best retention.",
        "ja": "{n} 個の概念が復習時期です（例：「{first}」）。今復習するのが効果的です。",
    },
    "overview_weak": {"zh-CN": "较薄弱的是：{names}。", "en": "Weakest: {names}.", "ja": "苦手なのは：{names}。"},
    "overview_all": {"zh-CN": "全部掌握，非常棒！", "en": "Everything mastered — great!", "ja": "すべて習得、素晴らしい！"},
    "due_title": {"zh-CN": "待复习（{n} 个概念 · 基于遗忘曲线）", "en": "Due for review ({n} · spacing-based)", "ja": "復習待ち（{n} 概念 · 忘却曲線ベース）"},
    "due_hint": {
        "zh-CN": "间隔复习：薄弱概念 1 天、掌握概念 3-6 天到期——在遗忘前重温效果最好。",
        "en": "Spaced review: weak concepts due in 1 day, mastered in 3-6 — revisit before forgetting.",
        "ja": "間隔反復：苦手は1日、習得済みは3〜6日で復習時期。忘れる前に復習するのが効果的。",
    },
    "due_days": {"zh-CN": "距上次 {d} 天", "en": "{d} days ago", "ja": "{d}日前"},
    "group_fmt": {"zh-CN": "📚 {title}（{n} 个概念）", "en": "📚 {title} ({n} concepts)", "ja": "📚 {title}（{n} 概念）"},
    "all_concepts": {"zh-CN": "所有概念掌握度", "en": "All concepts", "ja": "全概念の習得度"},
    "history_title": {"zh-CN": "学习历史记录", "en": "Learning History", "ja": "学習履歴"},
    "history_col_time": {"zh-CN": "时间", "en": "Time", "ja": "日時"},
    "history_col_concept": {"zh-CN": "概念", "en": "Concept", "ja": "概念"},
    "history_col_score": {"zh-CN": "得分", "en": "Score", "ja": "スコア"},
    "history_col_feedback": {"zh-CN": "反馈", "en": "Feedback", "ja": "フィードバック"},
    "history_empty": {"zh-CN": "暂无学习历史记录。开始学习并答题后将显示记录。", "en": "No history yet — it appears after your first evaluated answer.", "ja": "履歴はまだありません。最初の評価後に表示されます。"},
    "export_report": {"zh-CN": "导出学习报告", "en": "Export Report", "ja": "レポートをエクスポート"},
    "teacher_subtitle": {"zh-CN": "系统自己的理解和学习反馈", "en": "The system's own understanding", "ja": "システム自身の理解"},
    "teacher_explain_title": {"zh-CN": "这个视图是什么？", "en": "What is this view?", "ja": "このビューとは？"},
    "teacher_explain_body": {
        "zh-CN": "教师模型 = 系统对这本书自己的理解（不是你的学习记录）。它深读材料后，为每个概念标注「为什么重要 / 前置知识 / 常见误解 / 外部连接」，并标出材料中矛盾、未定义、逻辑断点等可疑点（待解项）。「重新自检」= 让系统再深读一遍材料并更新理解（需要 LLM）。下方「概念笔记」逐条对应书中的概念，点击笔记可查看概念详情并开始学习。",
        "en": "The Teacher Model is the system's own understanding of this book (not your study record). It reads deeply and marks each concept with \u201cwhy it matters / prerequisites / misconceptions / connections\u201d, plus suspicious points in the material (anomalies). \u201cRe-check\u201d = re-read the material and update the model (needs LLM). The concept notes below map one-to-one to the book's concepts — click one to see details and start learning.",
        "ja": "教師モデルは、この本に対するシステム自身の理解です（あなたの学習記録ではありません）。各概念に「なぜ重要か/前提知識/よくある誤解/関連」を付け、資料の矛盾や未定義用語などの疑義（未解決項目）も示します。「再チェック」= 資料を読み直して理解を更新（LLMが必要）。下の「概念ノート」は本の概念に対応しており、クリックで詳細と学習を開始できます。",
    },
    "teacher_status_done": {"zh-CN": "状态: 完成", "en": "Status: done", "ja": "状態: 完了"},
    "teacher_status_fallback": {"zh-CN": "状态: 降级（未配置 LLM）", "en": "Status: fallback (no LLM)", "ja": "状態: フォールバック（LLM未設定）"},
    "teacher_status_failed": {"zh-CN": "状态: 自检失败（已降级）", "en": "Status: failed (degraded)", "ja": "状態: 失敗（縮退）"},
    "teacher_method": {"zh-CN": "方法: {m}", "en": "Method: {m}", "ja": "方法: {m}"},
    "teacher_time": {"zh-CN": "生成时间: {t}", "en": "Generated: {t}", "ja": "生成: {t}"},
    "recheck": {"zh-CN": "重新自检", "en": "Re-check", "ja": "再チェック"},
    "recheck_needs_llm": {"zh-CN": "（需要配置 LLM 才能重新自检）", "en": "(configure an LLM key to re-check)", "ja": "（再チェックにはLLMキーが必要）"},
    "anomaly_label": {"zh-CN": "待解项（{n} 条）— 系统对材料的怀疑点：", "en": "Open anomalies ({n}) — what the system doubts:", "ja": "未解決項目（{n}件）— システムが疑問視している点："},
    "kind_contradiction": {"zh-CN": "矛盾", "en": "Contradiction", "ja": "矛盾"},
    "kind_undefined_term": {"zh-CN": "未定义术语", "en": "Undefined term", "ja": "未定義の用語"},
    "kind_logical_gap": {"zh-CN": "逻辑断点", "en": "Logical gap", "ja": "論理の飛躍"},
    "kind_surprising_claim": {"zh-CN": "反常主张", "en": "Surprising claim", "ja": "意外な主張"},
    "kind_learner_gap": {"zh-CN": "学习者信号", "en": "Learner signal", "ja": "学習者シグナル"},
    "kind_needs_llm": {"zh-CN": "需要 LLM", "en": "Needs LLM", "ja": "LLMが必要"},
    "sev_high": {"zh-CN": "高", "en": "high", "ja": "高"},
    "sev_medium": {"zh-CN": "中", "en": "medium", "ja": "中"},
    "sev_low": {"zh-CN": "低", "en": "low", "ja": "低"},
    "sev_info": {"zh-CN": "信息", "en": "info", "ja": "情報"},
    "anomaly_loc": {"zh-CN": "位置：{loc}", "en": "Location: {loc}", "ja": "場所: {loc}"},
    "notes_label": {"zh-CN": "概念笔记 ({n} 条):", "en": "Concept notes ({n}):", "ja": "概念ノート（{n}件）:"},
    "notes_hint": {
        "zh-CN": "{n} 个概念的理解笔记——点击任意一条，查看该概念的证据、关系与教师理解。",
        "en": "{n} concept notes — click any entry to see evidence, relations and the teacher's understanding.",
        "ja": "{n} 件の概念ノート — クリックで根拠・関係・教師の理解を表示します。",
    },
    "panel_title": {"zh-CN": "概念详情", "en": "Concept Details", "ja": "概念の詳細"},
    "panel_mastery": {"zh-CN": "掌握度 {m:.0%}", "en": "Mastery {m:.0%}", "ja": "習得度 {m:.0%}"},
    "panel_evidence": {"zh-CN": "原文证据（{n} 条）", "en": "Source evidence ({n})", "ja": "原文の根拠（{n}件）"},
    "panel_position": {"zh-CN": "知识网络中的位置", "en": "Position in the network", "ja": "知識ネットワーク上の位置"},
    "panel_teacher_notes": {"zh-CN": "教师笔记", "en": "Teacher notes", "ja": "教師ノート"},
    "panel_anomalies": {"zh-CN": "相关待解项", "en": "Related anomalies", "ja": "関連する未解決項目"},
    "panel_why": {"zh-CN": "为什么重要", "en": "Why it matters", "ja": "なぜ重要か"},
    "panel_prereq": {"zh-CN": "前置知识", "en": "Prerequisites", "ja": "前提知識"},
    "panel_miscon": {"zh-CN": "常见误解", "en": "Misconceptions", "ja": "よくある誤解"},
    "panel_conn": {"zh-CN": "外部连接", "en": "Connections", "ja": "関連"},
    "panel_ext": {"zh-CN": "外部补充（非原文）", "en": "External notes (not in source)", "ja": "外部補足（原文外）"},
    "panel_understanding": {"zh-CN": "系统理解", "en": "System's understanding", "ja": "システムの理解"},
    "panel_teach": {"zh-CN": "开始教学", "en": "Start teaching", "ja": "学習を開始"},
    "panel_focus": {"zh-CN": "在图谱中聚焦", "en": "Focus in map", "ja": "マップでフォーカス"},
    "panel_not_exist": {"zh-CN": "（概念不存在）", "en": "(concept does not exist)", "ja": "（概念が存在しません）"},
    "detail_click_hint": {"zh-CN": "点击左侧节点 - 查看它的定义、关系与教师理解", "en": "Click a node to see its definition, relations and teacher notes", "ja": "ノードをクリックして定義・関係・教師ノートを表示"},
    "detail_relations": {"zh-CN": "关系 · 点击继续游走", "en": "Relations · click to roam", "ja": "関係 · クリックで移動"},
    "detail_evidence": {"zh-CN": "原文依据", "en": "Source evidence", "ja": "原文の根拠"},
    "detail_teacher": {"zh-CN": "教师理解", "en": "Teacher notes", "ja": "教師ノート"},
    "detail_full": {"zh-CN": "完整详情", "en": "Full details", "ja": "詳細を開く"},
    "detail_why": {"zh-CN": "为什么重要：{s}", "en": "Why: {s}", "ja": "重要性：{s}"},
    "detail_miscon": {"zh-CN": "常见误解：{s}", "en": "Misconception: {s}", "ja": "誤解：{s}"},
    "no_records": {"zh-CN": "暂无记录", "en": "No records", "ja": "記録なし"},
    "path_empty": {"zh-CN": "暂无推荐——所有概念已掌握或模型为空。", "en": "Nothing to recommend — all mastered or the model is empty.", "ja": "おすすめはありません — すべて習得済みかモデルが空です。"},
    "trend_empty": {"zh-CN": "暂无评估记录——完成答题后这里会显示你的成长曲线", "en": "No evaluations yet — your growth curve appears after answering", "ja": "評価記録がありません — 回答後に成長曲線が表示されます"},
    "graph_path_edge": {"zh-CN": "路径相邻", "en": "path", "ja": "経路"},
    "confirm_delete_title": {"zh-CN": "确认删除知识资产？", "en": "Delete this knowledge asset?", "ja": "この知識資産を削除しますか？"},
    "confirm_delete_body": {
        "zh-CN": "将永久删除《{title}》及其抽取的概念、关系、教师模型与学习记录，此操作不可恢复。",
        "en": "Permanently delete \u201c{title}\u201d, its concepts, relations, teacher model and learning records. This cannot be undone.",
        "ja": "「{title}」とその概念・関係・教師モデル・学習記録を完全に削除します。元に戻せません。",
    },
    "delete_confirm_btn": {"zh-CN": "删除", "en": "Delete", "ja": "削除"},
    "cancel": {"zh-CN": "取消", "en": "Cancel", "ja": "キャンセル"},
    "asset_deleted": {"zh-CN": "已删除资产", "en": "Asset deleted", "ja": "資産を削除しました"},
    "no_asset_placeholder": {"zh-CN": "请先导入知识资产", "en": "Import a knowledge asset first", "ja": "先に知識資産をインポートしてください"},

    "graph_hint": {"zh-CN": "拖拽平移 · 滚轮缩放 · 点击概念查看详情", "en": "Drag to pan · scroll to zoom · click a concept for details"},
    "no_concepts": {"zh-CN": "（无可绘制概念）", "en": "(No concepts to draw)"},
    # canonical option display text
    "baseline_novice": {"zh-CN": "陌生", "en": "Novice"},
    "baseline_some": {"zh-CN": "了解一些", "en": "Some familiarity"},
    "baseline_practiced": {"zh-CN": "已有实践", "en": "Practiced"},
    "style_example": {"zh-CN": "例子", "en": "Examples"},
    "style_diagram": {"zh-CN": "图示", "en": "Diagram"},
    "style_steps": {"zh-CN": "拆解步骤", "en": "Step breakdown"},
}

_lang = DEFAULT_LANG


def init_lang() -> str:
    """Load the persisted language choice (if any) into the active language."""
    global _lang
    try:
        if _LANG_FILE.exists():
            data = json.loads(_LANG_FILE.read_text(encoding="utf-8"))
            code = data.get("lang")
            if code in LANGS:
                _lang = code
    except Exception:
        pass
    return _lang


def get_lang() -> str:
    return _lang


def set_lang(code: str) -> None:
    global _lang
    if code in LANGS:
        _lang = code


def save_lang() -> None:
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _LANG_FILE.write_text(
            json.dumps({"lang": _lang}, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


def t(key: str, **kwargs) -> str:
    table = _STRINGS.get(key)
    if table is None:
        return key
    s = table.get(_lang, table.get(DEFAULT_LANG, key))
    if kwargs:
        try:
            return s.format(**kwargs)
        except Exception:
            return s
    return s


def translate_option(kind: str, code: str) -> str:
    """Translate a canonical option code (baseline_*/style_*) to display text."""
    if kind == "baseline":
        key = {"novice": "baseline_novice", "some": "baseline_some", "practiced": "baseline_practiced"}.get(code)
    else:
        key = {"example": "style_example", "diagram": "style_diagram", "steps": "style_steps"}.get(code)
    return t(key) if key else code
