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
