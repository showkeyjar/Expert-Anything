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
    "app_tagline": {
        "zh-CN": "个人学习 OS",
        "en": "Personal Learning OS",
        "ja": "パーソナル学習OS",
    },
    "import_asset": {
        "zh-CN": "＋ 导入知识资产",
        "en": "+ Import Knowledge",
        "ja": "＋ ナレッジ資産をインポート",
    },
    "knowledge_model": {
        "zh-CN": "知识模型",
        "en": "Knowledge Model",
        "ja": "ナレッジモデル",
    },
    "teach_session": {
        "zh-CN": "教学会话",
        "en": "Tutor Session",
        "ja": "チュータリングセッション",
    },
    "learner_model": {
        "zh-CN": "学习者模型",
        "en": "Learner Model",
        "ja": "学習者モデル",
    },
    "cognitive_nav": {"zh-CN": "认知导航", "en": "Cognitive Map", "ja": "認知ナビ"},
    "read_source": {"zh-CN": "阅读原文", "en": "Read Source", "ja": "原文を読む"},
    "asset_item": {
        "zh-CN": "{title}  ·  {count} 概念",
        "en": "{title}  ·  {count} concepts",
        "ja": "{title}  ·  {count}コンセプト",
    },
    "asset_tooltip": {
        "zh-CN": "{title}\n{count} 个知识实体",
        "en": "{title}\n{count} knowledge entities",
        "ja": "{title}\n{count}件のナレッジエンティティ",
    },
    "delete_tip": {
        "zh-CN": "删除该资产",
        "en": "Delete this asset",
        "ja": "この資産を削除",
    },
    "delete": {"zh-CN": "删除", "en": "Delete", "ja": "削除"},
    "processing": {"zh-CN": "正在处理…", "en": "Processing…", "ja": "処理中…"},
    "processing_hint": {
        "zh-CN": "导入与知识分析需要一些时间，请勿关闭窗口或重复点击。",
        "en": "Import and analysis take a while. Please don't close the window or click repeatedly.",
        "ja": "インポートとナレッジ分析には時間がかかります。ウィンドウを閉じたり、繰り返しクリックしないでください。",
    },
    "progress_note": {
        "zh-CN": "处理进度会实时更新。若长时间无变化，请检查网络（LLM 接口是否可达）。",
        "en": "Progress updates live. If it stalls for long, check your network (LLM endpoint reachability).",
        "ja": "進捗はリアルタイムで更新されます。長時間変化がない場合は、ネットワーク（LLMエンドポイントの到達性）を確認してください。",
    },
    "import_title": {
        "zh-CN": "导入知识资产",
        "en": "Import Knowledge",
        "ja": "ナレッジ資産をインポート",
    },
    "import_subtitle": {
        "zh-CN": "支持 EPUB / PDF / Markdown / TXT，或直接粘贴任意知识内容。",
        "en": "Supports EPUB / PDF / Markdown / TXT, or paste any knowledge content directly.",
        "ja": "EPUB / PDF / Markdown / TXT に対応、または任意のナレッジ内容を直接貼り付け。",
    },
    "paste_label": {
        "zh-CN": "或直接粘贴内容（书摘 / 论文 / 笔记 / 网页 / 个人经验）",
        "en": "Or paste content directly (excerpts / papers / notes / web pages / personal experience)",
        "ja": "または内容を直接貼り付け（書抜き / 論文 / ノート / Webページ / 個人経験）",
    },
    "asset_name": {"zh-CN": "资产名称", "en": "Asset name", "ja": "資産名"},
    "no_llm_note": {
        "zh-CN": "（未检测到 LLM Key，将使用确定性降级抽取，深度有限）",
        "en": "(No LLM key detected; using deterministic fallback extraction with limited depth)",
        "ja": "（LLMキーが検出されません。確定論的フォールバック抽出を使用します。深さは限定的です）",
    },
    "generate": {
        "zh-CN": "生成知识包",
        "en": "Generate Knowledge Pack",
        "ja": "ナレッジパックを生成",
    },
    "no_content": {
        "zh-CN": "请提供材料内容。",
        "en": "Please provide material content.",
        "ja": "材料内容を入力してください。",
    },
    "extracting": {
        "zh-CN": "正在解析与抽取知识模型…",
        "en": "Parsing and extracting knowledge model…",
        "ja": "ナレッジモデルを解析・抽出中…",
    },
    "self_learning": {
        "zh-CN": "正在自我学习：深加工概念、扫描异常…",
        "en": "Self-learning: deepening concepts, scanning for anomalies…",
        "ja": "自己学習中：コンセプトの深掘り、異常スキャン…",
    },
    "process_error": {
        "zh-CN": "处理出错：{exc}",
        "en": "Error: {exc}",
        "ja": "処理エラー：{exc}",
    },
    "knowledge_model_header": {
        "zh-CN": "知识模型",
        "en": "Knowledge Model",
        "ja": "ナレッジモデル",
    },
    "no_asset": {
        "zh-CN": "请先导入一个知识资产。",
        "en": "Please import a knowledge asset first.",
        "ja": "まずナレッジ資産をインポートしてください。",
    },
    "fallback_warn": {
        "zh-CN": "⚠ 该资产未经过 LLM 深加工（方法={method}）：当前仅是文本结构索引，概念定义与关系可能不完整。配置 EXPERTANYTHING_LLM_API_KEY 后重新导入，可得到带证据的定义、关系与异常检测。",
        "en": "⚠ This asset was not deep-processed by the LLM (method={method}): it is only a text-structure index; concept definitions and relations may be incomplete. Re-import after setting EXPERTANYTHING_LLM_API_KEY to get evidence-backed definitions, relations and anomaly detection.",
        "ja": "⚠ この資産はLLMによる深加工が行われていません（method={method}）：現在はテキスト構造インデックスのみで、コンセプト定義と関係が不完全な場合があります。EXPERTANYTHING_LLM_API_KEY を設定して再インポートすると、証拠に基づく定義・関係・異常検出が得られます。",
    },
    "knowledge_subtitle": {
        "zh-CN": "来源：{name} ｜ 方法：{method}",
        "en": "Source: {name} ｜ Method: {method}",
        "ja": "ソース：{name} ｜ メソッド：{method}",
    },
    "mastered": {"zh-CN": "已掌握", "en": "Mastered", "ja": "習得済み"},
    "partial": {"zh-CN": "学习中", "en": "Learning", "ja": "学習中"},
    "unstudied": {"zh-CN": "未学习", "en": "New", "ja": "未学習"},
    "anomalies": {"zh-CN": "异常", "en": "Anomalies", "ja": "異常"},
    "learning_path": {
        "zh-CN": "推荐学习路径",
        "en": "Recommended learning path",
        "ja": "推奨学習パス",
    },
    "none": {"zh-CN": "（无）", "en": "(none)", "ja": "（なし）"},
    "concepts_with_evidence": {
        "zh-CN": "概念（带原文证据）",
        "en": "Concepts (with source evidence)",
        "ja": "コンセプト（原文証拠付き）",
    },
    "concept_notes": {
        "zh-CN": "概念深加工理解",
        "en": "Concept deep-analysis",
        "ja": "コンセプト深掘り理解",
    },
    "no_relations": {
        "zh-CN": "（无被确认的关系；需 LLM 推断）",
        "en": "(No confirmed relations; LLM inference needed)",
        "ja": "（確認された関係なし。LLM推論が必要）",
    },
    "enter_teach": {
        "zh-CN": "进入教学会话",
        "en": "Start Tutor Session",
        "ja": "チュータリングセッションへ",
    },
    "reader_title": {"zh-CN": "阅读原文", "en": "Read Source", "ja": "原文を読む"},
    "no_source": {
        "zh-CN": "（该资产未保存原文文本；多为早期版本或解析失败所致。重新导入可补全原文。）",
        "en": "(This asset has no saved source text, usually from an older version or a parsing failure. Re-import to restore it.)",
        "ja": "（この資産には原文テキストが保存されていません。旧バージョンまたは解析失敗によるものが多いです。再インポートで原文を復元できます。）",
    },
    "reader_subtitle": {
        "zh-CN": "来源：{name}",
        "en": "Source: {name}",
        "ja": "ソース：{name}",
    },
    "reader_full": {
        "zh-CN": "全文 · 共 {n} 段（原文，未经改写）",
        "en": "Full text · {n} paragraphs (original, unmodified)",
        "ja": "全文 · 全{n}段落（原文、改変なし）",
    },
    "reader_loc": {
        "zh-CN": "第 {i} 段 / 共 {total} 段",
        "en": "Paragraph {i} / {total}",
        "ja": "第{i}段落 / 全{total}段落",
    },
    "reader_fragment": {
        "zh-CN": "片段定位（上下文已截断）",
        "en": "Fragment located (context truncated)",
        "ja": "フラグメント位置（文脈は切り詰め済み）",
    },
    "selected_fragment": {
        "zh-CN": "选中片段",
        "en": "Selected fragment",
        "ja": "選択フラグメント",
    },
    "back_to_full": {"zh-CN": "← 阅读全文", "en": "← Full text", "ja": "← 全文を読む"},
    "back_to_km": {
        "zh-CN": "← 返回知识模型",
        "en": "← Back to Knowledge Model",
        "ja": "← ナレッジモデルに戻る",
    },
    "next_evidence": {
        "zh-CN": "下一个证据 ▶",
        "en": "Next evidence ▶",
        "ja": "次の証拠 ▶",
    },
    "no_anchor_concepts": {
        "zh-CN": "（暂无可在原文中定位的概念）",
        "en": "(No concepts can be located in the source yet)",
        "ja": "（原文で位置特定できるコンセプトはまだありません）",
    },
    "teach_title": {
        "zh-CN": "教学会话",
        "en": "Tutor Session",
        "ja": "チュータリングセッション",
    },
    "no_teach_concept": {
        "zh-CN": "该资产没有可教学的概念。",
        "en": "This asset has no teachable concepts.",
        "ja": "この資産には指導可能なコンセプトがありません。",
    },
    "align_subtitle": {
        "zh-CN": "先对齐你的目标和基础，Tutor 据此选择讲法。",
        "en": "Let's align your goal and baseline first; the Tutor picks the approach accordingly.",
        "ja": "まず目標と基礎を合わせます。チューターがそれに応じて教え方を選びます。",
    },
    "goal_label": {
        "zh-CN": "学完后你想做到什么？",
        "en": "What do you want to be able to do after learning?",
        "ja": "学習終了後にできるようになりたいことは？",
    },
    "baseline_label": {
        "zh-CN": "现在的基础",
        "en": "Your current level",
        "ja": "現在のレベル",
    },
    "default_goal": {
        "zh-CN": "理解这份知识资产",
        "en": "Understand this knowledge asset",
        "ja": "このナレッジ資産を理解する",
    },
    "lesson_subtitle": {
        "zh-CN": "基于原文证据讲解，请把概念迁移到你的目标。",
        "en": "Explanations are grounded in the source; transfer the concept to your goal.",
        "ja": "原文証拠に基づいて解説します。コンセプトをあなたの目標に転移してください。",
    },
    "priority_hint": {
        "zh-CN": "（系统优先：该概念关联待解异常，走在你前面）",
        "en": "(System priority: this concept links to an open anomaly — walking ahead of you)",
        "ja": "（システム優先：このコンセプトは未解決異常に関連。あなたより先を歩んでいます）",
    },
    "preparing": {
        "zh-CN": "Tutor 正在准备讲解…",
        "en": "The Tutor is preparing the explanation…",
        "ja": "チューターが解説を準備中…",
    },
    "style_dd_label": {
        "zh-CN": "讲解方式（实时切换）",
        "en": "Explanation style (live switch)",
        "ja": "解説スタイル（リアルタイム切替）",
    },
    "no_diagram": {
        "zh-CN": "（无法生成结构图）",
        "en": "(Could not generate the structure diagram)",
        "ja": "（構造図を生成できません）",
    },
    "doubt_matched": {
        "zh-CN": "⚠ 系统对此仍有存疑（{kind}）：{desc}",
        "en": "⚠ The system still has doubts ({kind}): {desc}",
        "ja": "⚠ システムは依然として疑問があります（{kind}）：{desc}",
    },
    "doubt_none": {
        "zh-CN": "本概念暂无待解异常，但全篇还有 {n} 个待解项（见「认知导航」）。",
        "en": "No open anomalies for this concept, but {n} remain across the text (see Cognitive Map).",
        "ja": "このコンセプトに未解決異常はありませんが、全文に{n}個の未解決項目があります（「認知ナビ」を参照）。",
    },
    "answer_label": {
        "zh-CN": "把它放进你的目标里，用一两句话回答",
        "en": "Put it into your own goal and answer in a sentence or two",
        "ja": "あなたの目標に当てはめて、一两言で答えてください",
    },
    "vary_example": {
        "zh-CN": "↻ 换一个例子",
        "en": "↻ Another example",
        "ja": "↻ 別の例に切り替え",
    },
    "evaluating": {
        "zh-CN": "Tutor 正在评估你的回答…",
        "en": "The Tutor is evaluating your answer…",
        "ja": "チューターがあなたの回答を評価中…",
    },
    "eval_score": {
        "zh-CN": "评估得分：{score} ｜ 掌握度更新为 {m}",
        "en": "Score: {score} ｜ Mastery updated to {m}",
        "ja": "評価スコア：{score} ｜ 習得度が{m}に更新されました",
    },
    "next_step": {"zh-CN": "下一步 →", "en": "Next →", "ja": "次へ →"},
    "concept_graph": {
        "zh-CN": "概念结构图",
        "en": "Concept structure map",
        "ja": "コンセプト構造図",
    },
    "explain_position": {
        "zh-CN": "讲解（概念在知识网络中的位置）",
        "en": "Explanation (where the concept sits in the knowledge network)",
        "ja": "解説（ナレッジネットワークにおける位置）",
    },
    "example_goal": {
        "zh-CN": "结合你的目标的例子",
        "en": "Examples tied to your goal",
        "ja": "あなたの目標に結びつけた例",
    },
    "action_path": {
        "zh-CN": "用起来的行动路径",
        "en": "Action path to apply it",
        "ja": "実践への行動パス",
    },
    "example_goal_focus": {
        "zh-CN": "结合你的目标的例子（重点）",
        "en": "Examples tied to your goal (key)",
        "ja": "あなたの目標に結びつけた例（重点）",
    },
    "action_path_focus": {
        "zh-CN": "用起来的行动路径（重点）",
        "en": "Action path to apply it (key)",
        "ja": "実践への行動パス（重点）",
    },
    "evidence": {"zh-CN": "原文证据", "en": "Source evidence", "ja": "原文証拠"},
    "doubt_section": {
        "zh-CN": "系统存疑 · 走在你前面",
        "en": "System doubts · walking ahead",
        "ja": "システムの疑問 · 先を歩む",
    },
    "submit_eval": {
        "zh-CN": "提交并评估",
        "en": "Submit & Evaluate",
        "ja": "提出して評価",
    },
    "learner_title": {
        "zh-CN": "学习者模型",
        "en": "Learner Model",
        "ja": "学習者モデル",
    },
    "profile": {"zh-CN": "画像", "en": "Profile", "ja": "プロフィール"},
    "profile_text": {
        "zh-CN": "目标：{goal} ｜ 基础：{baseline} ｜ 偏好：{style}",
        "en": "Goal: {goal} ｜ Baseline: {baseline} ｜ Preference: {style}",
        "ja": "目標：{goal} ｜ 基礎：{baseline} ｜ 嗜好：{style}",
    },
    "mastery": {
        "zh-CN": "概念掌握度",
        "en": "Concept mastery",
        "ja": "コンセプト習得度",
    },
    "weaknesses": {"zh-CN": "当前弱项", "en": "Current weaknesses", "ja": "現在の弱点"},
    "no_weakness": {
        "zh-CN": "（暂无明显弱项）",
        "en": "(No obvious weaknesses yet)",
        "ja": "（目立った弱点はまだありません）",
    },
    "recent": {"zh-CN": "最近回应", "en": "Recent responses", "ja": "最近の回答"},
    "history_row": {
        "zh-CN": "· {concept}：{score} － {feedback}",
        "en": "· {concept}: {score} － {feedback}",
        "ja": "· {concept}：{score} － {feedback}",
    },
    "nav_title": {"zh-CN": "认知导航", "en": "Cognitive Map", "ja": "認知ナビ"},
    "nav_no_asset": {
        "zh-CN": "请先导入一个知识资产，系统会先做自我学习。",
        "en": "Import a knowledge asset first; the system will self-learn.",
        "ja": "まずナレッジ資産をインポートしてください。システムが自己学習します。",
    },
    "nav_no_self": {
        "zh-CN": "该系统尚未生成自我认知。",
        "en": "This asset has no self-cognition yet.",
        "ja": "この資産にはまだ自己認知が生成されていません。",
    },
    "gen_self": {
        "zh-CN": "生成自我认知",
        "en": "Generate self-cognition",
        "ja": "自己認知を生成",
    },
    "why_important": {
        "zh-CN": "为什么重要：",
        "en": "Why it matters: ",
        "ja": "なぜ重要か：",
    },
    "prereq": {"zh-CN": "前提：", "en": "Prerequisites: ", "ja": "前提："},
    "connections": {"zh-CN": "连接：", "en": "Connections: ", "ja": "つながり："},
    "misconceptions": {
        "zh-CN": "常见误解：",
        "en": "Common misconceptions: ",
        "ja": "よくある誤解：",
    },
    "external_notes": {
        "zh-CN": "外部引入补充：",
        "en": "External additions: ",
        "ja": "外部からの補足：",
    },
    "learner_signals": {
        "zh-CN": "学习者真实信号：",
        "en": "Learner's real signals: ",
        "ja": "学習者のリアルシグナル：",
    },
    "not_deep": {
        "zh-CN": "（尚未深加工，需配置 LLM 后重新自检）",
        "en": "(Not deep-processed yet; re-run self-check after configuring the LLM)",
        "ja": "（まだ深加工されていません。LLM設定後に再セルフチェックしてください）",
    },
    "anomaly_section": {
        "zh-CN": "异常 / 待解清单（{n} 条，系统走在学生前面）",
        "en": "Anomalies / open items ({n}, system walks ahead)",
        "ja": "異常 / 未解決リスト（{n}件、システムが先を歩む）",
    },
    "no_anomaly": {
        "zh-CN": "（未检测到异常 / 待解项）",
        "en": "(No anomalies / open items detected)",
        "ja": "（異常 / 未解決項目は検出されません）",
    },
    "no_definition": {
        "zh-CN": "（无定义）",
        "en": "(no definition)",
        "ja": "（定義なし）",
    },
    "read_source_link": {
        "zh-CN": "阅读原文 →",
        "en": "Read source →",
        "ja": "原文を読む →",
    },
    "no_hierarchy": {
        "zh-CN": "（暂无层级关系，按学习路径顺序列出）",
        "en": "(No hierarchy yet; listed in learning-path order)",
        "ja": "（階層関係はまだありません。学習パス順に表示）",
    },
    "concept_map_net": {
        "zh-CN": "概念网络图",
        "en": "Concept network map",
        "ja": "コンセプトネットワーク図",
    },
    "concept_map_net_title": {
        "zh-CN": "概念网络图（按掌握度着色）",
        "en": "Concept network map (coloured by mastery)",
        "ja": "コンセプトネットワーク図（習得度で着色）",
    },
    "no_map": {
        "zh-CN": "（关系太少，暂无可绘制的网络图）",
        "en": "(Too few relations to draw a network map yet)",
        "ja": "（関係が少なすぎて、ネットワーク図を描画できません）",
    },
    "evidence_locations": {
        "zh-CN": "原文证据（共 {n} 处）",
        "en": "Source evidence ({n} locations)",
        "ja": "原文証拠（全{n}箇所）",
    },
    "also_referenced": {
        "zh-CN": "也被这些概念引用",
        "en": "Also referenced by",
        "ja": "これらのコンセプトからも参照",
    },
    "tree_tip": {
        "zh-CN": "（缩进表示层级，每一层是上一层的子概念）",
        "en": "(Indentation shows hierarchy; each level is a sub-concept of the one above)",
        "ja": "（インデントは階層を表します。各レベルは上位のサブコンセプトです）",
    },
    "net_tip": {
        "zh-CN": "（箭头表示概念之间的关系，节点为概念）",
        "en": "(Arrows are relations between concepts; nodes are concepts)",
        "ja": "（矢印はコンセプト間の関係、ノードはコンセプトを表します）",
    },
    "loc_concept": {
        "zh-CN": "定位：{name}",
        "en": "Located: {name}",
        "ja": "位置：{name}",
    },
    "learn_concept": {"zh-CN": "讲解", "en": "Teach me", "ja": "解説"},
    "learn_concept_full": {
        "zh-CN": "讲解此概念",
        "en": "Teach this concept",
        "ja": "このコンセプトを解説",
    },
    "concept_graph_btn": {"zh-CN": "关系图谱", "en": "Concept map", "ja": "関係マップ"},
    "concept_graph_view": {
        "zh-CN": "概念关系图谱",
        "en": "Concept relationship map",
        "ja": "コンセプト関係マップ",
    },
    "graph_focus_tip": {
        "zh-CN": "（围绕「{name}」的局部网络：高亮节点即本概念，连线为它与邻近概念的关系）",
        "en": "(Local network around \u201c{name}\u201d: the highlighted node is this concept; edges are its relations to neighbours)",
        "ja": "（「{name}」周辺のローカルネットワーク：ハイライトノードがこのコンセプト、ラインは近傍コンセプトとの関係）",
    },
    "neighbor_relations": {
        "zh-CN": "邻近关系",
        "en": "Neighbouring relations",
        "ja": "近傍関係",
    },
    "no_neighbors": {
        "zh-CN": "（该概念在模型中没有显式的关系连线；可在原文中对照理解）",
        "en": "(No explicit relation edges for this concept in the model; cross-check it in the source)",
        "ja": "（このコンセプトにはモデル内で明示的な関係ラインがありません。原文で照合してください）",
    },
    "back_to_km_from_graph": {
        "zh-CN": "← 返回知识模型",
        "en": "← Back to Knowledge Model",
        "ja": "← ナレッジモデルに戻る",
    },
    "rel_to": {
        "zh-CN": "{label} → {name}",
        "en": "{label} → {name}",
        "ja": "{label} → {name}",
    },
    "rel_from": {
        "zh-CN": "← {label} · {name}",
        "en": "← {label} · {name}",
        "ja": "← {label} · {name}",
    },
    "rel_default": {"zh-CN": "关联", "en": "linked", "ja": "関連"},
    "definition_lbl": {"zh-CN": "定义", "en": "Definition", "ja": "定義"},
    "learner_overview": {
        "zh-CN": "学习概览",
        "en": "Learning overview",
        "ja": "学習概況",
    },
    "progress_done": {
        "zh-CN": "已学 {done}/{total} 个概念",
        "en": "{done}/{total} concepts studied",
        "ja": "{done}/{total}コンセプト学習済み",
    },
    "avg_mastery": {"zh-CN": "平均掌握度", "en": "Average mastery", "ja": "平均習得度"},
    "mastery_map": {"zh-CN": "掌握度图谱", "en": "Mastery map", "ja": "習得度マップ"},
    "graph_legend_mastery": {
        "zh-CN": "节点颜色＝掌握度：绿=已掌握，橙=薄弱，灰=未学",
        "en": "Node colour = mastery: green=mastered, orange=weak, grey=not studied",
        "ja": "ノード色＝習得度：緑=習得済み、橙=弱点、灰=未学習",
    },
    "recommend_next": {
        "zh-CN": "推荐下一步",
        "en": "Recommended next",
        "ja": "次の推奨",
    },
    "recommend_reason_anom": {
        "zh-CN": "该概念关联待解异常，建议优先突破",
        "en": "Linked to an open anomaly — tackle it first",
        "ja": "このコンセプトは未解決異常に関連。優先的に突破を推奨",
    },
    "recommend_reason_weak": {
        "zh-CN": "当前掌握度最低，建议优先补习",
        "en": "Lowest mastery — review it next",
        "ja": "現在の習得度が最低。優先的に復習を推奨",
    },
    "recommend_reason_path": {
        "zh-CN": "学习路径上的下一个未掌握概念",
        "en": "Next unmastered concept on the path",
        "ja": "学習パス上の次の未習得コンセプト",
    },
    "recommend_reason_foundation": {
        "zh-CN": "基础前置概念，建议先掌握",
        "en": "Foundational prerequisite — learn it first",
        "ja": "基礎前提コンセプト。先に習得を推奨",
    },
    "recommend_reason_unblock": {
        "zh-CN": "掌握后可解锁 {n} 个下游概念",
        "en": "Unlocks {n} downstream concepts once mastered",
        "ja": "習得後に{n}個の下流コンセプトが解放されます",
    },
    "recommend_reason_ready": {
        "zh-CN": "前置概念已掌握，现在就能学",
        "en": "Prerequisites done — ready to study now",
        "ja": "前提コンセプトは習得済み。今すぐ学習できます",
    },
    "recommend_reason_blocked": {
        "zh-CN": "前置概念尚未掌握，建议先补齐",
        "en": "Prerequisites not yet mastered — review them first",
        "ja": "前提コンセプトが未習得。先に補うことを推奨",
    },
    "adaptive_path_step": {"zh-CN": "第 {n} 步", "en": "Step {n}", "ja": "ステップ{n}"},
    "adaptive_path_empty": {
        "zh-CN": "（已掌握全部概念，或暂无可推荐项）",
        "en": "(All concepts mastered, or nothing to recommend yet)",
        "ja": "（全コンセプト習得済み、または推奨項目なし）",
    },
    "click_learn": {"zh-CN": "点击学习 →", "en": "Learn →", "ja": "学習する →"},
    "weak_click_hint": {
        "zh-CN": "点击薄弱概念可前往学习",
        "en": "Click a weak concept to study it",
        "ja": "弱点コンセプトをクリックして学習へ",
    },
    "nav_hub": {"zh-CN": "认知导航图", "en": "Cognitive map", "ja": "認知ナビ図"},
    "nav_hub_tip": {
        "zh-CN": "（掌握度着色的全量概念网络，橙色描边＝待解异常。点击下方概念可前往学习）",
        "en": "(Full concept network coloured by mastery; orange outline = open anomaly. Click a concept below to study it)",
        "ja": "（習得度で着色した全コンセプトネットワーク。橙の枠線＝未解決異常。下のコンセプトをクリックして学習へ）",
    },
    "open_anomaly_concepts": {
        "zh-CN": "待解异常涉及的概念（走在你前面）",
        "en": "Concepts tied to open anomalies (walking ahead)",
        "ja": "未解決異常に関連するコンセプト（先を歩む）",
    },
    "explore_anomaly": {"zh-CN": "前往探索 →", "en": "Explore →", "ja": "探索へ →"},
    "doubt_explore": {
        "zh-CN": "系统存疑 · 走在你前面",
        "en": "System doubts · walking ahead",
        "ja": "システムの疑問 · 先を歩む",
    },
    "nav_legend": {
        "zh-CN": "图例：● 已掌握  ● 薄弱  ● 未学  ◎ 待解异常",
        "en": "Legend: ● mastered ● weak ● not studied ◎ open anomaly",
        "ja": "凡例：● 習得済み  ● 弱点  ● 未学習  ◎ 未解決異常",
    },
    "legend_partial": {"zh-CN": "部分掌握", "en": "Partial", "ja": "一部習得"},
    "legend_current": {"zh-CN": "当前概念", "en": "Current", "ja": "現在の概念"},
    "frontier_tip_prefix": {
        "zh-CN": "学习边界·点这里拓这个",
        "en": "Learning frontier · click to expand",
        "ja": "学習フロンティア・ここをクリックして開拓",
    },
    "legend_frontier": {
        "zh-CN": "学习边界",
        "en": "Learning frontier",
        "ja": "学習境界",
    },
    "legend_full": {
        "zh-CN": "图例：● 已掌握  ● 部分掌握  ● 未学  ◎ 学习边界（下一步拓展）  ◎ 待解异常",
        "en": "Legend: ● mastered ● partial ● unstudied ◎ frontier (next to expand) ◎ anomaly",
        "ja": "凡例：● 習得済み ● 学習中 ● 未学習 ◎ 学習フロンティア ◎ 疑義",
    },
    "nav_import": {
        "zh-CN": "📥 导入知识资产",
        "en": "📥 Import",
        "ja": "📥 インポート",
    },
    "nav_knowledge": {
        "zh-CN": "🌳 知识模型",
        "en": "🌳 Knowledge",
        "ja": "🌳 知識モデル",
    },
    "nav_map": {"zh-CN": "🗺️ 认知地图", "en": "🗺️ Cognitive Map", "ja": "🗺️ 認知マップ"},
    "nav_source": {"zh-CN": "📖 阅读原文", "en": "📖 Source", "ja": "📖 原文を読む"},
    "nav_teach": {"zh-CN": "🎓 教学会话", "en": "🎓 Tutor", "ja": "🎓 学習セッション"},
    "nav_learner": {
        "zh-CN": "🧠 学习者模型",
        "en": "🧠 Learner",
        "ja": "🧠 学習者モデル",
    },
    "nav_teacher": {
        "zh-CN": "👨‍🏫 教师模型",
        "en": "👨‍🏫 Teacher",
        "ja": "👨‍🏫 教師モデル",
    },
    "assets_label": {
        "zh-CN": "知识资产",
        "en": "Knowledge Assets",
        "ja": "ナレッジ資産",
    },
    "quick_teach": {"zh-CN": "🎓 开始学习", "en": "🎓 Learn", "ja": "🎓 学習を始める"},
    "quick_map": {
        "zh-CN": "🕸 概念网络",
        "en": "🕸 Concept Map",
        "ja": "🕸 概念ネットワーク",
    },
    "quick_source": {"zh-CN": "📖 阅读原文", "en": "📖 Source", "ja": "📖 原文を読む"},
    "topbar_progress": {
        "zh-CN": "已掌握 {m}/{t} · 学习中 {l} · 待复习 {r}",
        "en": "Mastered {m}/{t} · Learning {l} · Due {r}",
        "ja": "習得 {m}/{t} · 学習中 {l} · 復習待ち {r}",
    },
    "topbar_no_asset": {
        "zh-CN": "未选择资产",
        "en": "No asset selected",
        "ja": "資産未選択",
    },
    "lang_label": {"zh-CN": "语言", "en": "Language", "ja": "言語"},
    "import_subtitle2": {
        "zh-CN": "支持 PDF / EPUB / Word (.docx) / Markdown / TXT / HTML，自动提取概念并构建知识图谱",
        "en": "PDF / EPUB / Word (.docx) / Markdown / TXT / HTML — concepts and a knowledge map are extracted automatically",
        "ja": "PDF / EPUB / Word (.docx) / Markdown / TXT / HTML に対応。概念と知識マップを自動抽出します",
    },
    "choose_file": {"zh-CN": "选择文件", "en": "Choose File", "ja": "ファイル選択"},
    "start_analysis": {"zh-CN": "开始分析", "en": "Analyze", "ja": "分析開始"},
    "paste_hint": {
        "zh-CN": "或直接粘贴学习内容…",
        "en": "…or paste content here",
        "ja": "またはここに内容を貼り付け",
    },
    "analyzing": {"zh-CN": "正在分析文本…", "en": "Analyzing…", "ja": "分析中…"},
    "import_file_prompt": {
        "zh-CN": "请先选择或输入文件名",
        "en": "Choose a file or enter a path first",
        "ja": "先にファイルを選択してください",
    },
    "read_failed": {
        "zh-CN": "读取文件失败: {e}",
        "en": "Failed to read file: {e}",
        "ja": "ファイルの読み込みに失敗: {e}",
    },
    "empty_content": {
        "zh-CN": "内容为空，请提供学习材料",
        "en": "Content is empty — provide material first",
        "ja": "内容が空です。教材を提供してください",
    },
    "extract_failed_text": {
        "zh-CN": "无法从文件中提取文本。扫描版 PDF 需要 OCR，暂不支持；请确认文件不是加密或损坏的。",
        "en": "Could not extract text. Scanned PDFs need OCR (not supported yet); check the file is not encrypted or corrupt.",
        "ja": "テキストを抽出できませんでした。スキャンPDFはOCRが必要です（未対応）。暗号化や破損がないか確認してください。",
    },
    "extracted_x": {
        "zh-CN": "已抽取 {n} 个概念",
        "en": "{n} concepts extracted",
        "ja": "{n} 個の概念を抽出",
    },
    "import_done": {
        "zh-CN": "知识资产《{title}》导入完成！\n概念数: {c}\n关系数: {r}",
        "en": "Asset \u201c{title}\u201d imported!\nConcepts: {c}\nRelations: {r}",
        "ja": "資産「{title}」のインポートが完了しました！\n概念: {c} / 関係: {r}",
    },
    "section_recommend": {
        "zh-CN": "推荐下一步",
        "en": "Recommended Next",
        "ja": "次におすすめ",
    },
    "section_graph": {
        "zh-CN": "概念网络图",
        "en": "Concept Network",
        "ja": "概念ネットワーク",
    },
    "legend_mastered": {"zh-CN": "已掌握", "en": "Mastered", "ja": "習得済み"},
    "legend_learning": {"zh-CN": "学习中", "en": "Learning", "ja": "学習中"},
    "legend_weak": {"zh-CN": "薄弱", "en": "Weak", "ja": "苦手"},
    "legend_unstudied": {"zh-CN": "未学", "en": "Unstudied", "ja": "未学習"},
    "legend_other_asset": {
        "zh-CN": "其它资产概念",
        "en": "Other assets",
        "ja": "他資産の概念",
    },
    "legend_focus": {
        "zh-CN": "聚焦/推荐",
        "en": "Focus / Top pick",
        "ja": "フォーカス/おすすめ",
    },
    "legend_anomaly": {"zh-CN": "系统存疑", "en": "Anomaly", "ja": "疑義あり"},
    "legend_hover": {
        "zh-CN": "悬停节点高亮邻居",
        "en": "Hover highlights neighbours",
        "ja": "ホバーで隣接を強調",
    },
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
    "search_placeholder": {
        "zh-CN": "🔍 搜索概念并定位（回车）",
        "en": "🔍 Search concepts (Enter)",
        "ja": "🔍 概念を検索（Enter）",
    },
    "reset_map": {"zh-CN": "复位全图", "en": "Reset View", "ja": "全体表示に戻す"},
    "scope_all": {"zh-CN": "全部资产", "en": "All assets", "ja": "全資産"},
    "scope_current": {
        "zh-CN": "仅当前资产",
        "en": "Current asset",
        "ja": "現在の資産のみ",
    },
    "map_back": {"zh-CN": "返回上层", "en": "Back", "ja": "上の階層へ"},
    "map_back_tip": {
        "zh-CN": "返回上一个钻取位置",
        "en": "Go back one drill level",
        "ja": "1つ上の階層に戻る",
    },
    "drill_hint": {
        "zh-CN": "点击节点查看其上下位概念",
        "en": "Click a node to see its broader/narrower concepts",
        "ja": "ノードをクリックすると上位・下位概念を表示",
    },
    "drill_current_prefix": {
        "zh-CN": "当前位置：",
        "en": "Current: ",
        "ja": "現在位置: ",
    },
    "drill_all": {"zh-CN": "全部知识", "en": "All knowledge", "ja": "全知識"},
    "drill_continue": {
        "zh-CN": "（点击节点继续钻取）",
        "en": "(click a node to keep drilling)",
        "ja": "（ノードをクリックして続ける）",
    },
    "svg_unsupported": {
        "zh-CN": "（当前环境不支持内嵌 SVG，请点击右上角打开互动演示。）",
        "en": "(Inline SVG is not supported here. Click the top-right button to open the interactive demo.)",
        "ja": "（この環境ではインラインSVGはサポートされていません。右上のボタンからインタラクティブデモを開いてください。）",
    },
    "zoom_fit": {"zh-CN": "适应", "en": "Fit", "ja": "フィット"},
    "zoom_in_tip": {"zh-CN": "放大", "en": "Zoom in", "ja": "拡大"},
    "zoom_out_tip": {"zh-CN": "缩小", "en": "Zoom out", "ja": "縮小"},
    "not_found_in_map": {
        "zh-CN": "图谱中没有名为「{kw}」的概念",
        "en": "No concept \u201c{kw}\u201d in the map",
        "ja": "マップに「{kw}」はありません",
    },
    "source_subtitle": {
        "zh-CN": "查看原始学习材料",
        "en": "Read the original material",
        "ja": "元の教材を読む",
    },
    "teach_hint": {
        "zh-CN": "选择概念 · 学习 · 答题 · 追问",
        "en": "Pick a concept · Learn · Answer · Ask",
        "ja": "概念を選ぶ · 学ぶ · 答える · 質問する",
    },
    "select_concept": {
        "zh-CN": "选择要学习的概念:",
        "en": "Choose a concept:",
        "ja": "学ぶ概念を選択:",
    },
    "style_label": {"zh-CN": "教学风格:", "en": "Style:", "ja": "スタイル:"},
    "start_teach": {"zh-CN": "开始教学", "en": "Start", "ja": "開始"},
    "pick_concept_first": {
        "zh-CN": "请先选择一个概念",
        "en": "Pick a concept first",
        "ja": "先に概念を選択してください",
    },
    "concept_not_found": {
        "zh-CN": "未找到概念: {name}",
        "en": "Concept not found: {name}",
        "ja": "概念が見つかりません: {name}",
    },
    "generating_lesson": {
        "zh-CN": "正在生成教学内容...",
        "en": "Generating lesson…",
        "ja": "レッスンを生成中…",
    },
    "lesson_ready": {
        "zh-CN": "选择一个概念开始学习",
        "en": "Pick a concept to begin",
        "ja": "概念を選んで学習を開始",
    },
    "harness_suggest_title": {
        "zh-CN": "Harness 演化建议",
        "en": "Harness Evolution Suggestion",
        "ja": "ハーネス進化の提案",
    },
    "harness_regress_title": {
        "zh-CN": "疑似误伤：建议裁守卫",
        "en": "Possible Collateral: Trim Guard",
        "ja": "誤傷の疑い：ガード削減を提案",
    },
    "harness_regress_body": {
        "zh-CN": "概念「{concept}」近期表现回退（平均 {before} → {after}，连续 {attempts} 次未达标）。预算守卫可能卡住了讲解深度，系统建议裁掉 budget_ok 守卫重新教学。",
        "en": "\u201c{concept}\u201d regressed recently ({before} → {after}, {attempts} straight fails). The budget guard may be throttling explanations; the system suggests trimming budget_ok and re-teaching.",
        "ja": "「{concept}」の成績が後退しています（{before} → {after}、{attempts} 回連続未達）。予算ガードが説明の深さを制限している可能性があるため、budget_ok を削減して再講義することを提案します。",
    },
    "harness_adopt_regress": {
        "zh-CN": "采纳并裁守卫",
        "en": "Trim & Adopt",
        "ja": "削減して採用",
    },
    "harness_reason_regression": {
        "zh-CN": "误伤裁守卫（回归驱动）",
        "en": "Regression-driven guard trim",
        "ja": "誤傷ガード削減（後退駆動）",
    },
    "harness_joint_title": {
        "zh-CN": "联合演化：多信号融合建议",
        "en": "Joint Evolution: Multi-Signal Plan",
        "ja": "統合進化：複数シグナルの提案",
    },
    "harness_joint_body": {
        "zh-CN": "概念「{concept}」触发多信号（{reason}），系统融合判定后设计新 Harness：{summary}。诊断：{diag}。启用后将立即以新讲解风格重讲本概念。",
        "en": "\u201c{concept}\u201d triggered multiple signals ({reason}); the system fused them into one decision. New harness: {summary}. Diagnosis: {diag}. Adopting re-teaches this concept right away.",
        "ja": "「{concept}」が複数シグナル（{reason}）を発火、統合判定で新ハーネスを設計しました：{summary}。診断：{diag}。採用すると新しいスタイルで即座に再講義します。",
    },
    "harness_adopt_joint": {
        "zh-CN": "启用联合方案",
        "en": "Adopt Joint Plan",
        "ja": "統合案を採用",
    },
    "harness_reason_joint": {
        "zh-CN": "联合演化（多信号融合）",
        "en": "Joint evolution (multi-signal)",
        "ja": "統合進化（複数シグナル）",
    },
    "harness_reason_sessions": {
        "zh-CN": "会话统计驱动",
        "en": "Session-stats driven",
        "ja": "セッション統計駆動",
    },
    "harness_suggest_body": {
        "zh-CN": "概念「{concept}」连续 {attempts} 次未达标，当前教学策略已失效。系统自动设计了新 Harness：{summary}。启用后将立即以新讲解风格重讲本概念。",
        "en": "\u201c{concept}\u201d failed {attempts} times in a row, so the current teaching strategy is stale. A new harness was designed automatically: {summary}. Adopting it re-teaches this concept with the new style right away.",
        "ja": "概念「{concept}」が {attempts} 回連続で未達のため、現在の戦略は失効しています。新ハーネスを自動設計しました：{summary}。採用すると、新しいスタイルで即座に再講義します。",
    },
    "harness_adopt": {
        "zh-CN": "启用新 Harness",
        "en": "Adopt New Harness",
        "ja": "新ハーネスを採用",
    },
    "harness_adopted": {
        "zh-CN": "已启用新 Harness：{name}，正在以新讲解风格重讲「{concept}」。",
        "en": "Adopted harness: {name}. Re-teaching \u201c{concept}\u201d with the new style.",
        "ja": "ハーネスを採用しました：{name}。新しいスタイルで「{concept}」を再講義します。",
    },
    "harness_none": {
        "zh-CN": "当前教学由默认 Harness 驱动（teach + quiz）",
        "en": "Teaching runs on the default harness (teach + quiz)",
        "ja": "現在はデフォルトハーネスで駆動中（teach + quiz）",
    },
    "harness_history": {
        "zh-CN": "演化历史（审计链）",
        "en": "Evolution History (audit trail)",
        "ja": "進化履歴（監査記録）",
    },
    "harness_reason_stuck": {
        "zh-CN": "卡壳自动演化",
        "en": "Stuck-driven evolution",
        "ja": "行き詰まり自動進化",
    },
    "harness_reason_manual": {
        "zh-CN": "手动采纳",
        "en": "Manual adoption",
        "ja": "手動採用",
    },
    "harness_reason_steady": {
        "zh-CN": "稳态复核",
        "en": "Steady-state check",
        "ja": "安定状態の確認",
    },
    "harness_reason_transfer": {
        "zh-CN": "跨资产迁移",
        "en": "Cross-asset transfer",
        "ja": "アセット間移行",
    },
    "harness_transfer_title": {
        "zh-CN": "跨资产 Harness 迁移建议",
        "en": "Cross-Asset Harness Migration",
        "ja": "アセット間ハーネス移行の提案",
    },
    "harness_transfer_body": {
        "zh-CN": "资产「{source}」的 Harness「{name}」在本资产上差分收益 +{gain}（成本差分 {cost}）。启用后将以新讲解风格重讲当前概念。",
        "en": "Harness \u201c{name}\u201d from \u201c{source}\u201d gains {gain} on this asset (cost diff {cost}). Adopting it re-teaches the current concept with the new style.",
        "ja": "「{source}」のハーネス「{name}」は本アセットで差分 {gain}（コスト差分 {cost}）。採用すると新しいスタイルで即座に再講義します。",
    },
    "harness_transfer_adopt": {
        "zh-CN": "迁移启用",
        "en": "Migrate",
        "ja": "移行して採用",
    },
    "harness_transfer_adopted": {
        "zh-CN": "已迁移启用 Harness：{name}（来自「{source}」），正在以新讲解风格重讲「{concept}」。",
        "en": "Migrated harness: {name} (from \u201c{source}\u201d). Re-teaching \u201c{concept}\u201d with the new style.",
        "ja": "ハーネスを移行しました：{name}（「{source}」より）。新しいスタイルで「{concept}」を再講義します。",
    },
    "explanation": {"zh-CN": "讲解", "en": "Explanation", "ja": "解説"},
    "example": {"zh-CN": "示例", "en": "Example", "ja": "例"},
    "steps_title": {"zh-CN": "学习步骤", "en": "Steps", "ja": "ステップ"},
    "practice": {"zh-CN": "练习", "en": "Practice", "ja": "練習"},
    "answer_placeholder": {
        "zh-CN": "请用自己的话回答这个问题...",
        "en": "Answer in your own words…",
        "ja": "自分の言葉で答えてください…",
    },
    "submit_answer": {"zh-CN": "提交答案", "en": "Submit", "ja": "回答を送信"},
    "evidence_label": {
        "zh-CN": "原文证据（来源约束）",
        "en": "Source evidence",
        "ja": "原文の根拠",
    },
    "followup_title": {
        "zh-CN": "还有疑问？追问导师（基于原文证据回答）",
        "en": "Questions? Ask the tutor (grounded in the source)",
        "ja": "質問は？チューターに聞く（原文に基づいて回答）",
    },
    "followup_placeholder": {
        "zh-CN": "例如：这个概念和刚才讲的另一个概念有什么区别？",
        "en": "e.g. How does this differ from the previous concept?",
        "ja": "例：前の概念とどう違いますか？",
    },
    "ask": {"zh-CN": "追问", "en": "Ask", "ja": "質問"},
    "no_llm_followup": {
        "zh-CN": "（未接入 LLM，无法追问。配置 API Key 后可进行对话式追问。）",
        "en": "(No LLM configured — configure an API key for follow-up.)",
        "ja": "（LLM未設定のため質問できません。APIキーを設定してください。）",
    },
    "related_concepts": {
        "zh-CN": "关联概念（顺藤摸瓜）",
        "en": "Related concepts",
        "ja": "関連概念",
    },
    "eval_result": {"zh-CN": "评估结果", "en": "Evaluation", "ja": "評価結果"},
    "eval_reference": {
        "zh-CN": "参考回答（基于原文证据）",
        "en": "Reference answer (source-grounded)",
        "ja": "参考回答（原文に基づく）",
    },
    "eval_gap": {"zh-CN": "与参考的差距", "en": "Gap vs reference", "ja": "参考との差"},
    "eval_mastered": {"zh-CN": "已掌握", "en": "Mastered", "ja": "習得済み"},
    "eval_keep_going": {"zh-CN": "需继续努力", "en": "Keep going", "ja": "もう少し"},
    "no_answer": {
        "zh-CN": "请先输入你的回答",
        "en": "Enter an answer first",
        "ja": "回答を入力してください",
    },
    "no_submittable": {
        "zh-CN": "当前没有可提交的教学内容，请重新开始教学。",
        "en": "No lesson to submit — start a lesson first.",
        "ja": "送信できるレッスンがありません。先にレッスンを開始してください。",
    },
    "learner_subtitle": {
        "zh-CN": "跨资产累积掌握度 | {n} 个概念",
        "en": "Cross-asset mastery | {n} concepts",
        "ja": "資産横断の習得度 | {n} 概念",
    },
    "stat_mastered": {
        "zh-CN": "已掌握 (≥60%)",
        "en": "Mastered (≥60%)",
        "ja": "習得 (≥60%)",
    },
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
    "overview_weak": {
        "zh-CN": "较薄弱的是：{names}。",
        "en": "Weakest: {names}.",
        "ja": "苦手なのは：{names}。",
    },
    "overview_all": {
        "zh-CN": "全部掌握，非常棒！",
        "en": "Everything mastered — great!",
        "ja": "すべて習得、素晴らしい！",
    },
    "due_title": {
        "zh-CN": "待复习（{n} 个概念 · 基于遗忘曲线）",
        "en": "Due for review ({n} · spacing-based)",
        "ja": "復習待ち（{n} 概念 · 忘却曲線ベース）",
    },
    "due_hint": {
        "zh-CN": "间隔复习：薄弱概念 1 天、掌握概念 3-6 天到期——在遗忘前重温效果最好。",
        "en": "Spaced review: weak concepts due in 1 day, mastered in 3-6 — revisit before forgetting.",
        "ja": "間隔反復：苦手は1日、習得済みは3〜6日で復習時期。忘れる前に復習するのが効果的。",
    },
    "due_days": {"zh-CN": "距上次 {d} 天", "en": "{d} days ago", "ja": "{d}日前"},
    "group_fmt": {
        "zh-CN": "📚 {title}（{n} 个概念）",
        "en": "📚 {title} ({n} concepts)",
        "ja": "📚 {title}（{n} 概念）",
    },
    "all_concepts": {
        "zh-CN": "所有概念掌握度",
        "en": "All concepts",
        "ja": "全概念の習得度",
    },
    "history_title": {
        "zh-CN": "学习历史记录",
        "en": "Learning History",
        "ja": "学習履歴",
    },
    "history_col_time": {"zh-CN": "时间", "en": "Time", "ja": "日時"},
    "history_col_concept": {"zh-CN": "概念", "en": "Concept", "ja": "概念"},
    "history_col_score": {"zh-CN": "得分", "en": "Score", "ja": "スコア"},
    "history_col_feedback": {"zh-CN": "反馈", "en": "Feedback", "ja": "フィードバック"},
    "history_empty": {
        "zh-CN": "暂无学习历史记录。开始学习并答题后将显示记录。",
        "en": "No history yet — it appears after your first evaluated answer.",
        "ja": "履歴はまだありません。最初の評価後に表示されます。",
    },
    "export_report": {
        "zh-CN": "导出学习报告",
        "en": "Export Report",
        "ja": "レポートをエクスポート",
    },
    "teacher_subtitle": {
        "zh-CN": "系统自己的理解和学习反馈",
        "en": "The system's own understanding",
        "ja": "システム自身の理解",
    },
    "teacher_explain_title": {
        "zh-CN": "这个视图是什么？",
        "en": "What is this view?",
        "ja": "このビューとは？",
    },
    "teacher_explain_body": {
        "zh-CN": "教师模型 = 系统对这本书自己的理解（不是你的学习记录）。它深读材料后，为每个概念标注「为什么重要 / 前置知识 / 常见误解 / 外部连接」，并标出材料中矛盾、未定义、逻辑断点等可疑点（待解项）。「重新自检」= 让系统再深读一遍材料并更新理解（需要 LLM）。下方「概念笔记」逐条对应书中的概念，点击笔记可查看概念详情并开始学习。",
        "en": "The Teacher Model is the system's own understanding of this book (not your study record). It reads deeply and marks each concept with \u201cwhy it matters / prerequisites / misconceptions / connections\u201d, plus suspicious points in the material (anomalies). \u201cRe-check\u201d = re-read the material and update the model (needs LLM). The concept notes below map one-to-one to the book's concepts — click one to see details and start learning.",
        "ja": "教師モデルは、この本に対するシステム自身の理解です（あなたの学習記録ではありません）。各概念に「なぜ重要か/前提知識/よくある誤解/関連」を付け、資料の矛盾や未定義用語などの疑義（未解決項目）も示します。「再チェック」= 資料を読み直して理解を更新（LLMが必要）。下の「概念ノート」は本の概念に対応しており、クリックで詳細と学習を開始できます。",
    },
    "teacher_status_done": {
        "zh-CN": "状态: 完成",
        "en": "Status: done",
        "ja": "状態: 完了",
    },
    "teacher_status_fallback": {
        "zh-CN": "状态: 降级（未配置 LLM）",
        "en": "Status: fallback (no LLM)",
        "ja": "状態: フォールバック（LLM未設定）",
    },
    "teacher_status_failed": {
        "zh-CN": "状态: 自检失败（已降级）",
        "en": "Status: failed (degraded)",
        "ja": "状態: 失敗（縮退）",
    },
    "teacher_method": {"zh-CN": "方法: {m}", "en": "Method: {m}", "ja": "方法: {m}"},
    "teacher_time": {
        "zh-CN": "生成时间: {t}",
        "en": "Generated: {t}",
        "ja": "生成: {t}",
    },
    "recheck": {"zh-CN": "重新自检", "en": "Re-check", "ja": "再チェック"},
    "recheck_needs_llm": {
        "zh-CN": "（需要配置 LLM 才能重新自检）",
        "en": "(configure an LLM key to re-check)",
        "ja": "（再チェックにはLLMキーが必要）",
    },
    "anomaly_label": {
        "zh-CN": "待解项（{n} 条）— 系统对材料的怀疑点：",
        "en": "Open anomalies ({n}) — what the system doubts:",
        "ja": "未解決項目（{n}件）— システムが疑問視している点：",
    },
    "kind_contradiction": {"zh-CN": "矛盾", "en": "Contradiction", "ja": "矛盾"},
    "kind_undefined_term": {
        "zh-CN": "未定义术语",
        "en": "Undefined term",
        "ja": "未定義の用語",
    },
    "kind_logical_gap": {"zh-CN": "逻辑断点", "en": "Logical gap", "ja": "論理の飛躍"},
    "kind_surprising_claim": {
        "zh-CN": "反常主张",
        "en": "Surprising claim",
        "ja": "意外な主張",
    },
    "kind_learner_gap": {
        "zh-CN": "学习者信号",
        "en": "Learner signal",
        "ja": "学習者シグナル",
    },
    "kind_needs_llm": {"zh-CN": "需要 LLM", "en": "Needs LLM", "ja": "LLMが必要"},
    "sev_high": {"zh-CN": "高", "en": "high", "ja": "高"},
    "sev_medium": {"zh-CN": "中", "en": "medium", "ja": "中"},
    "sev_low": {"zh-CN": "低", "en": "low", "ja": "低"},
    "sev_info": {"zh-CN": "信息", "en": "info", "ja": "情報"},
    "anomaly_loc": {
        "zh-CN": "位置：{loc}",
        "en": "Location: {loc}",
        "ja": "場所: {loc}",
    },
    "notes_label": {
        "zh-CN": "概念笔记 ({n} 条):",
        "en": "Concept notes ({n}):",
        "ja": "概念ノート（{n}件）:",
    },
    "notes_hint": {
        "zh-CN": "{n} 个概念的理解笔记——点击任意一条，查看该概念的证据、关系与教师理解。",
        "en": "{n} concept notes — click any entry to see evidence, relations and the teacher's understanding.",
        "ja": "{n} 件の概念ノート — クリックで根拠・関係・教師の理解を表示します。",
    },
    "panel_title": {"zh-CN": "概念详情", "en": "Concept Details", "ja": "概念の詳細"},
    "panel_mastery": {
        "zh-CN": "掌握度 {m:.0%}",
        "en": "Mastery {m:.0%}",
        "ja": "習得度 {m:.0%}",
    },
    "panel_evidence": {
        "zh-CN": "原文证据（{n} 条）",
        "en": "Source evidence ({n})",
        "ja": "原文の根拠（{n}件）",
    },
    "panel_position": {
        "zh-CN": "知识网络中的位置",
        "en": "Position in the network",
        "ja": "知識ネットワーク上の位置",
    },
    "panel_teacher_notes": {
        "zh-CN": "教师笔记",
        "en": "Teacher notes",
        "ja": "教師ノート",
    },
    "panel_anomalies": {
        "zh-CN": "相关待解项",
        "en": "Related anomalies",
        "ja": "関連する未解決項目",
    },
    "panel_why": {"zh-CN": "为什么重要", "en": "Why it matters", "ja": "なぜ重要か"},
    "panel_prereq": {"zh-CN": "前置知识", "en": "Prerequisites", "ja": "前提知識"},
    "panel_miscon": {"zh-CN": "常见误解", "en": "Misconceptions", "ja": "よくある誤解"},
    "panel_conn": {"zh-CN": "外部连接", "en": "Connections", "ja": "関連"},
    "panel_ext": {
        "zh-CN": "外部补充（非原文）",
        "en": "External notes (not in source)",
        "ja": "外部補足（原文外）",
    },
    "panel_understanding": {
        "zh-CN": "系统理解",
        "en": "System's understanding",
        "ja": "システムの理解",
    },
    "panel_teach": {"zh-CN": "开始教学", "en": "Start teaching", "ja": "学習を開始"},
    "panel_focus": {
        "zh-CN": "在图谱中聚焦",
        "en": "Focus in map",
        "ja": "マップでフォーカス",
    },
    "panel_not_exist": {
        "zh-CN": "（概念不存在）",
        "en": "(concept does not exist)",
        "ja": "（概念が存在しません）",
    },
    "detail_click_hint": {
        "zh-CN": "点击左侧节点 - 查看它的定义、关系与教师理解",
        "en": "Click a node to see its definition, relations and teacher notes",
        "ja": "ノードをクリックして定義・関係・教師ノートを表示",
    },
    "detail_relations": {
        "zh-CN": "关系 · 点击继续游走",
        "en": "Relations · click to roam",
        "ja": "関係 · クリックで移動",
    },
    "detail_evidence": {
        "zh-CN": "原文依据",
        "en": "Source evidence",
        "ja": "原文の根拠",
    },
    "detail_teacher": {"zh-CN": "教师理解", "en": "Teacher notes", "ja": "教師ノート"},
    "detail_full": {"zh-CN": "完整详情", "en": "Full details", "ja": "詳細を開く"},
    "detail_why": {"zh-CN": "为什么重要：{s}", "en": "Why: {s}", "ja": "重要性：{s}"},
    "detail_miscon": {
        "zh-CN": "常见误解：{s}",
        "en": "Misconception: {s}",
        "ja": "誤解：{s}",
    },
    "detail_siblings": {
        "zh-CN": "同级要点 · 与它并列",
        "en": "Peers · alongside it",
        "ja": "同級の要点 · 並ぶ概念",
    },
    "detail_next_level": {
        "zh-CN": "下一级要点 · 它通向哪里",
        "en": "Next level · where it leads",
        "ja": "次レベルの要点 · 繋がる先",
    },
    "detail_pill_roam": {
        "zh-CN": "单击游走",
        "en": "Click to roam",
        "ja": "クリックで移動",
    },
    "detail_pill_teach": {
        "zh-CN": "直接开教",
        "en": "Teach directly",
        "ja": "直接レッスン",
    },
    "detail_dbl_teach": {
        "zh-CN": "单击游走 · 双击开教",
        "en": "Click to roam · Double-click to teach",
        "ja": "クリックで移動・ダブルクリックでレッスン",
    },
    "detail_compare": {"zh-CN": "对比", "en": "Compare", "ja": "比較"},
    "detail_compare_with": {"zh-CN": "对比…", "en": "Compare…", "ja": "比較…"},
    "detail_peers_empty": {
        "zh-CN": "（暂无同级要点）",
        "en": "(no peers)",
        "ja": "（同級なし）",
    },
    "detail_next_empty": {
        "zh-CN": "（暂无下一级要点）",
        "en": "(no next level)",
        "ja": "（次レベルなし）",
    },
    "compare_title": {
        "zh-CN": "概念对比",
        "en": "Concept Comparison",
        "ja": "概念比較",
    },
    "compare_teach": {
        "zh-CN": "学习「{name}」",
        "en": "Study 「{name}」",
        "ja": "「{name}」を学ぶ",
    },
    "compare_select": {
        "zh-CN": "选择对比对象",
        "en": "Compare against",
        "ja": "比較対象を選択",
    },
    "compare_definition": {"zh-CN": "定义", "en": "Definition", "ja": "定義"},
    "compare_evidence": {
        "zh-CN": "原文依据（{n} 条）",
        "en": "Evidence ({n})",
        "ja": "根拠（{n}件）",
    },
    "compare_relations": {"zh-CN": "关系", "en": "Relations", "ja": "関係"},
    "compare_notes": {"zh-CN": "教师笔记", "en": "Teacher notes", "ja": "教師ノート"},
    "compare_similarity": {
        "zh-CN": "定义相似度 {pct}",
        "en": "Definition similarity {pct}",
        "ja": "定義の類似度 {pct}",
    },
    "compare_sim_high": {"zh-CN": "高度相似", "en": "highly similar", "ja": "高い類似"},
    "compare_sim_low": {
        "zh-CN": "差异显著",
        "en": "clearly different",
        "ja": "明確な差異",
    },
    "compare_shared": {
        "zh-CN": "共享邻居 {n} 个：{names}",
        "en": "Shared neighbours ({n}): {names}",
        "ja": "共通の隣接 {n}件：{names}",
    },
    "compare_only_a": {
        "zh-CN": "仅前者有：{rel}",
        "en": "Only first: {rel}",
        "ja": "前者のみ：{rel}",
    },
    "compare_only_b": {
        "zh-CN": "仅后者有：{rel}",
        "en": "Only second: {rel}",
        "ja": "後者のみ：{rel}",
    },
    "compare_chapter_diff": {
        "zh-CN": "章节不同：前者在「{a}」，后者在「{b}」",
        "en": "Different chapters: 「{a}」 vs 「{b}」",
        "ja": "章が異なる：「{a}」と「{b}」",
    },
    "compare_prereq_only_a": {
        "zh-CN": "前者独有前置：{names}",
        "en": "Prereqs only first: {names}",
        "ja": "前者のみ前提：{names}",
    },
    "compare_prereq_only_b": {
        "zh-CN": "后者独有前置：{names}",
        "en": "Prereqs only second: {names}",
        "ja": "後者のみ前提：{names}",
    },
    "compare_miscon_only_a": {
        "zh-CN": "前者独有误解：{names}",
        "en": "Misconceptions only first: {names}",
        "ja": "前者のみ誤解：{names}",
    },
    "compare_miscon_only_b": {
        "zh-CN": "后者独有误解：{names}",
        "en": "Misconceptions only second: {names}",
        "ja": "後者のみ誤解：{names}",
    },
    "compare_no_points": {
        "zh-CN": "两者无直接关系、无共享邻居，属于独立知识点。",
        "en": "No direct relation or shared neighbour — independent points.",
        "ja": "直接の関係・共通隣接なし — 独立した知識点です。",
    },
    "compare_hint_gap": {
        "zh-CN": "学习建议：先攻「{name}」（掌握度低 {diff}），再回来巩固另一边。",
        "en": "Study 「{name}」 first (mastery lower by {diff}), then consolidate the other.",
        "ja": "「{name}」を先に（習得度 {diff} 低い）→ もう一方を固める。",
    },
    "compare_hint_shared": {
        "zh-CN": "衔接点：两者都连接「{name}」，可以从它出发串联记忆。",
        "en": "Bridge: both link to 「{name}」 — chain your memory from it.",
        "ja": "接点：「{name}」に両方が接続 — そこから記憶を繋げよう。",
    },
    "compare_hint_default": {
        "zh-CN": "对照两边定义与关系，找出各自独特的边界。",
        "en": "Compare both definitions and relations to spot each side's boundary.",
        "ja": "両方の定義と関係を見比べて、それぞれの境界を見つけよう。",
    },
    "compare_incorporate": {
        "zh-CN": "沉淀到教师模型",
        "en": "Sink into Teacher Model",
        "ja": "教師モデルに反映",
    },
    "compare_incorporated": {
        "zh-CN": "✓ 已沉淀：共享锚点与掌握度差距将参与教学排序",
        "en": "✓ Sunk in: anchors & mastery gap now shape teaching order",
        "ja": "✓ 反映済み：共有アンカーと習得度差が授業順に反映",
    },
    "compare_chapter_same": {
        "zh-CN": "同属「{ch}」",
        "en": "Both in 「{ch}」",
        "ja": "ともに「{ch}」",
    },
    "no_records": {"zh-CN": "暂无记录", "en": "No records", "ja": "記録なし"},
    "path_empty": {
        "zh-CN": "暂无推荐——所有概念已掌握或模型为空。",
        "en": "Nothing to recommend — all mastered or the model is empty.",
        "ja": "おすすめはありません — すべて習得済みかモデルが空です。",
    },
    "trend_empty": {
        "zh-CN": "暂无评估记录——完成答题后这里会显示你的成长曲线",
        "en": "No evaluations yet — your growth curve appears after answering",
        "ja": "評価記録がありません — 回答後に成長曲線が表示されます",
    },
    "graph_path_edge": {"zh-CN": "路径相邻", "en": "path", "ja": "経路"},
    "confirm_delete_title": {
        "zh-CN": "确认删除知识资产？",
        "en": "Delete this knowledge asset?",
        "ja": "この知識資産を削除しますか？",
    },
    "confirm_delete_body": {
        "zh-CN": "将永久删除《{title}》及其抽取的概念、关系、教师模型与学习记录，此操作不可恢复。",
        "en": "Permanently delete \u201c{title}\u201d, its concepts, relations, teacher model and learning records. This cannot be undone.",
        "ja": "「{title}」とその概念・関係・教師モデル・学習記録を完全に削除します。元に戻せません。",
    },
    "delete_confirm_btn": {"zh-CN": "删除", "en": "Delete", "ja": "削除"},
    "cancel": {"zh-CN": "取消", "en": "Cancel", "ja": "キャンセル"},
    "app_error": {
        "zh-CN": "程序错误",
        "en": "Application error",
        "ja": "アプリケーションエラー",
    },
    "app_error_body": {
        "zh-CN": "发生未处理的错误：\n{exc}\n\n详情已写入 error.log（{log}）。您可以继续使用，但建议反馈此问题。",
        "en": "An unhandled error occurred:\n{exc}\n\nDetails were written to error.log ({log}). You may continue, but please report this.",
        "ja": "未処理のエラーが発生しました:\n{exc}\n\n詳細は error.log（{log}）に記録されました。続行できますが、報告をお勧めします。",
    },
    "stat_total": {"zh-CN": "总概念", "en": "Concepts", "ja": "総概念"},
    "stat_unstudied": {"zh-CN": "未学习", "en": "Unstudied", "ja": "未学習"},
    "stat_anomaly": {"zh-CN": "异常", "en": "Anomalies", "ja": "疑義"},
    "tab_concepts": {"zh-CN": "概念掌握度", "en": "Concepts", "ja": "概念の習得度"},
    "tab_history": {"zh-CN": "学习历史", "en": "History", "ja": "履歴"},
    "dash_subtitle": {
        "zh-CN": "来源：{title} | 概念数：{concepts} | 方法：{method}",
        "en": "Source: {title} | Concepts: {concepts} | Method: {method}",
        "ja": "出典: {title} | 概念: {concepts} | 方法: {method}",
    },
    "method_llm": {"zh-CN": "LLM 抽取", "en": "LLM extraction", "ja": "LLM抽出"},
    "method_fallback": {
        "zh-CN": "确定性模式（未深度加工）",
        "en": "Deterministic mode (not deep-processed)",
        "ja": "決定論モード（未深処理）",
    },
    "method_unknown": {"zh-CN": "未知方法", "en": "Unknown method", "ja": "不明な方法"},
    "dash_fallback_warn": {
        "zh-CN": "⚠ 该资产未经 LLM 深加工（{method}）：概念定义与关系可能不完整。配置 LLM Key 后重新导入可得带证据的定义、关系与异常检测。",
        "en": "⚠ This asset was not deep-processed by the LLM ({method}): concept definitions and relations may be incomplete. Re-import after configuring an LLM key to get evidence-backed definitions, relations and anomaly detection.",
        "ja": "⚠ この資産はLLMで深処理されていません（{method}）：概念定義と関係が不完全な可能性があります。LLMキー設定後に再インポートすると、証拠付き定義・関係・異常検出が得られます。",
    },
    "dash_loading": {
        "zh-CN": "加载知识数据...",
        "en": "Loading knowledge data…",
        "ja": "知識データを読み込み中…",
    },
    "tag_cross": {"zh-CN": "跨资产", "en": "Cross-asset", "ja": "資産横断"},
    "tag_stuck": {
        "zh-CN": "卡壳·换策略重讲",
        "en": "Stuck·retry new strategy",
        "ja": "停滞・別戦略で再講義",
    },
    "decoder_card_title": {
        "zh-CN": "知识解译",
        "en": "Knowledge decoding",
        "ja": "知識の解読",
    },
    "decoder_overview_hint": {
        "zh-CN": "全景视图 · 先整体看清结构；需要逐步讲解时再点击「分步讲解」",
        "en": "Overview · see the whole structure first; start the step-by-step walkthrough when you need it",
        "ja": "全景ビュー · まず全体構造を把握し、必要なら「ステップ解説」を再生",
    },
    "decoder_step_btn": {
        "zh-CN": "分步讲解",
        "en": "Step-by-step",
        "ja": "ステップ解説",
    },
    "decoder_overview_btn": {
        "zh-CN": "返回全景",
        "en": "Back to overview",
        "ja": "全景に戻る",
    },
    "decoder_overview_pill": {
        "zh-CN": "全景 · 静态结构图",
        "en": "Overview · static map",
        "ja": "全景・静的構造図",
    },
    "decoder_step_pill": {
        "zh-CN": "分步讲解 · 逐步揭示",
        "en": "Step-by-step · gradual reveal",
        "ja": "ステップ解説・順次表示",
    },
    "decoder_prev": {"zh-CN": "上一步", "en": "Prev", "ja": "前へ"},
    "decoder_next": {"zh-CN": "下一步", "en": "Next", "ja": "次へ"},
    "decoder_play": {"en": "Autoplay", "zh-CN": "自动播放", "ja": "自動再生"},
    "decoder_open_html": {
        "zh-CN": "打开互动演示",
        "en": "Open interactive demo",
        "ja": "インタラクティブデモを開く",
    },
    "decoder_game_title": {
        "zh-CN": "动手排一排",
        "en": "Order it yourself",
        "ja": "並べ替えゲーム",
    },
    "decoder_game_check": {"zh-CN": "检查", "en": "Check", "ja": "確認"},
    "decoder_game_retry": {"zh-CN": "再试一次", "en": "Try again", "ja": "もう一度"},
    "decoder_game_correct": {"zh-CN": "答对了！", "en": "Correct!", "ja": "正解！"},
    "decoder_game_wrong": {
        "zh-CN": "还不对，再想想",
        "en": "Not yet — think again",
        "ja": "まだです、もう一度",
    },
    "decoder_game_answer": {
        "zh-CN": "正确顺序",
        "en": "Correct order",
        "ja": "正しい順序",
    },
    "decoder_your_order": {
        "zh-CN": "你的排序（点击下方条目按正确顺序加入；点已选项可移除）",
        "en": "Your order (click items below in the correct order; click a chosen one to remove)",
        "ja": "あなたの並び（正しい順にクリック、選択済みはクリックで取消）",
    },
    "decoder_game_hint": {
        "zh-CN": "把步骤按正确顺序点出来，检验你是否真的理解了",
        "en": "Pick the steps in the right order to prove you understood",
        "ja": "正しい順に選んで理解を確かめよう",
    },
    "decoder_badge": {
        "zh-CN": "知识解码",
        "en": "KNOWLEDGE DECODING",
        "ja": "知識デコード",
    },
    "decoder_stage_hint": {
        "zh-CN": "← → 切换步骤 · 空格自动播放 · 点击数字跳转",
        "en": "← → step · Space autoplay · click a number to jump",
        "ja": "← → ステップ · スペース自動再生 · 番号クリックでジャンプ",
    },
    "decoder_game_partial": {
        "zh-CN": "答对 {ok}/{n} 个位置，绿色是正确的，再调整一下",
        "en": "{ok}/{n} positions right — green ones are correct, adjust the rest",
        "ja": "{ok}/{n} が正位置（緑が正解）、残りを調整しよう",
    },
    "audit_title": {"zh-CN": "轨迹审计", "en": "Trace Audit", "ja": "軌跡監査"},
    "audit_hint": {
        "zh-CN": "每个掌握度数字都能追到下方记录的学习轨迹行——记录即事实源，不采信叙述性文本。",
        "en": "Every mastery number traces to the recorded attempt rows below — the record, not narrative text, is the source of truth.",
        "ja": "各習得度の数値は下記の学習軌跡まで遡れます — 記録こそが唯一の事実源です。",
    },
    "audit_col_attempts": {"zh-CN": "作答次数", "en": "Attempts", "ja": "回答回数"},
    "audit_col_avg": {"zh-CN": "平均分", "en": "Avg score", "ja": "平均スコア"},
    "audit_col_mastery": {"zh-CN": "掌握度", "en": "Mastery", "ja": "習得度"},
    "audit_col_channels": {"zh-CN": "学习通道", "en": "Channels", "ja": "チャネル"},
    "audit_channel_answer": {"zh-CN": "答题", "en": "Answer", "ja": "回答"},
    "audit_channel_quiz": {"zh-CN": "自测", "en": "Self-test", "ja": "自己テスト"},
    "audit_channel_practice": {"zh-CN": "实践", "en": "Practice", "ja": "実践"},
    "audit_rotated_n": {
        "zh-CN": "策略轮换 {n} 次",
        "en": "{n} style rotations",
        "ja": "戦略転換 {n} 回",
    },
    "audit_arbitrated_n": {
        "zh-CN": "双裁判复核 {n} 次",
        "en": "{n} cross-judge arbitrations",
        "ja": "双判定レビュー {n} 回",
    },
    "audit_stuck_label": {
        "zh-CN": "卡壳概念（{n} 个）",
        "en": "Stuck concepts ({n})",
        "ja": "停滞概念（{n}件）",
    },
    "audit_stuck_none": {
        "zh-CN": "无卡壳概念",
        "en": "No stuck concepts",
        "ja": "停滞概念なし",
    },
    "audit_no_trace": {
        "zh-CN": "暂无学习轨迹记录——完成答题、自测或实践后，这里会显示每个掌握度数字的可追溯轨迹。",
        "en": "No trace yet — after your first answer / self-test / practice, every mastery number becomes traceable here.",
        "ja": "軌跡はまだありません — 回答・自己テスト・実践後に各習得度の軌跡が表示されます。",
    },
    "group_unknown": {"zh-CN": "未知资产", "en": "Unknown asset", "ja": "不明な資産"},
    "group_other": {"zh-CN": "其他来源", "en": "Other sources", "ja": "その他の出典"},
    "share_concept": {"zh-CN": "共享概念", "en": "shared", "ja": "共有概念"},
    "edge_prereq": {"zh-CN": "前置", "en": "prerequisite", "ja": "前提"},
    "edge_related": {"zh-CN": "关联", "en": "related", "ja": "関連"},
    "global_map_title": {
        "zh-CN": "全局知识图谱",
        "en": "Global Knowledge Map",
        "ja": "グローバル知識マップ",
    },
    "hint": {"zh-CN": "提示", "en": "Notice", "ja": "通知"},
    "error": {"zh-CN": "错误", "en": "Error", "ja": "エラー"},
    "done": {"zh-CN": "完成", "en": "Done", "ja": "完了"},
    "teach_error": {
        "zh-CN": "教学失败: {msg}",
        "en": "Teaching failed: {msg}",
        "ja": "学習の生成に失敗: {msg}",
    },
    "followup_failed": {
        "zh-CN": "（追问失败：{msg}）",
        "en": "(follow-up failed: {msg})",
        "ja": "（質問に失敗: {msg}）",
    },
    "score_line": {
        "zh-CN": "得分: {s:.2f}",
        "en": "Score: {s:.2f}",
        "ja": "スコア: {s:.2f}",
    },
    "feedback_line": {
        "zh-CN": "反馈: {fb}",
        "en": "Feedback: {fb}",
        "ja": "フィードバック: {fb}",
    },
    "start_teach_first": {
        "zh-CN": "请先开始教学会话",
        "en": "Start a lesson first",
        "ja": "先にレッスンを開始してください",
    },
    "paste_placeholder": {
        "zh-CN": "在这里粘贴你的学习材料...",
        "en": "Paste your learning material here…",
        "ja": "ここに学習教材を貼り付け…",
    },
    "llm_ready": {
        "zh-CN": "✓ LLM 已配置",
        "en": "✓ LLM configured",
        "ja": "✓ LLM 設定済み",
    },
    "llm_not_ready": {
        "zh-CN": "✗ LLM 未配置（使用确定性回退）",
        "en": "✗ No LLM (deterministic fallback)",
        "ja": "✗ LLM未設定（決定論的フォールバック）",
    },
    "filter_supported": {
        "zh-CN": "支持的文件",
        "en": "Supported files",
        "ja": "対応ファイル",
    },
    "teacher_empty": {
        "zh-CN": "教师模型数据尚未生成\n请先完成知识资产导入和自学习过程",
        "en": "Teacher model not generated yet\nImport an asset and run the self-learning pass first",
        "ja": "教師モデルはまだ生成されていません\n先に資産のインポートと自己学習を実行してください",
    },
    "teacher_build_now": {
        "zh-CN": "立即生成教师模型",
        "en": "Generate now",
        "ja": "今すぐ生成",
    },
    "rechecking": {
        "zh-CN": "正在重新自检，请稍候...",
        "en": "Re-checking…",
        "ja": "再チェック中…",
    },
    "recheck_failed": {
        "zh-CN": "自检失败: {e}",
        "en": "Re-check failed: {e}",
        "ja": "再チェックに失敗: {e}",
    },
    "recheck_done": {
        "zh-CN": "自检完成: {n} 条待解项",
        "en": "Re-check done: {n} open anomalies",
        "ja": "再チェック完了: 未解決 {n} 件",
    },
    "build_needs_llm": {
        "zh-CN": "需要配置 LLM 才能生成教师模型",
        "en": "An LLM key is required to build the teacher model",
        "ja": "教師モデルの生成にはLLMキーが必要です",
    },
    "building_teacher": {
        "zh-CN": "正在生成教师模型，请稍候...",
        "en": "Building the teacher model…",
        "ja": "教師モデルを生成中…",
    },
    "build_failed": {
        "zh-CN": "生成失败: {e}",
        "en": "Build failed: {e}",
        "ja": "生成に失敗: {e}",
    },
    "build_done": {
        "zh-CN": "教师模型生成完成: {n} 条待解项",
        "en": "Teacher model built: {n} open anomalies",
        "ja": "教師モデル生成完了: 未解決 {n} 件",
    },
    "report_title": {
        "zh-CN": "ExpertAnything 学习报告",
        "en": "ExpertAnything Learning Report",
        "ja": "ExpertAnything 学習レポート",
    },
    "report_generated": {
        "zh-CN": "生成时间: {t}",
        "en": "Generated: {t}",
        "ja": "生成: {t}",
    },
    "report_assets": {
        "zh-CN": "【知识资产】",
        "en": "[Knowledge Assets]",
        "ja": "【知識資産】",
    },
    "report_concepts": {
        "zh-CN": "概念数: {c}, 关系数: {r}",
        "en": "Concepts: {c}, Relations: {r}",
        "ja": "概念: {c}, 関係: {r}",
    },
    "report_mastery": {
        "zh-CN": "【概念掌握度】",
        "en": "[Concept Mastery]",
        "ja": "【概念の習得度】",
    },
    "report_sources": {"zh-CN": "来源: {s}", "en": "Sources: {s}", "ja": "出典: {s}"},
    "report_history": {
        "zh-CN": "【最近评估记录】",
        "en": "[Recent Evaluations]",
        "ja": "【最近の評価記録】",
    },
    "report_score_fb": {
        "zh-CN": "得分: {s:.2f} | 反馈: {fb}",
        "en": "Score: {s:.2f} | Feedback: {fb}",
        "ja": "スコア: {s:.2f} | フィードバック: {fb}",
    },
    "report_done": {
        "zh-CN": "报告生成完毕",
        "en": "Report generated",
        "ja": "レポート生成完了",
    },
    "save_report": {
        "zh-CN": "保存学习报告",
        "en": "Save learning report",
        "ja": "学習レポートを保存",
    },
    "report_filename": {
        "zh-CN": "学习报告_{ts}.txt",
        "en": "report_{ts}.txt",
        "ja": "レポート_{ts}.txt",
    },
    "report_saved": {
        "zh-CN": "学习报告已保存到:\n{filename}",
        "en": "Report saved to:\n{filename}",
        "ja": "レポートを保存しました:\n{filename}",
    },
    "report_failed": {
        "zh-CN": "导出失败: {e}",
        "en": "Export failed: {e}",
        "ja": "エクスポートに失敗: {e}",
    },
    "no_mastery_yet": {
        "zh-CN": "（还没有学习记录，先去「教学会话」学几个概念吧）",
        "en": "(No learning records yet — learn a few concepts in the Tutor Session first)",
        "ja": "（学習記録はまだありません。先に学習セッションで概念を学びましょう）",
    },
    "total_concepts": {"zh-CN": "概念数", "en": "Concepts", "ja": "概念数"},
    "relations": {"zh-CN": "关系数", "en": "Relations", "ja": "関係数"},
    "method_label": {"zh-CN": "方法", "en": "Method", "ja": "方法"},
    "export_html": {
        "zh-CN": "导出可视化 HTML 报告",
        "en": "Export HTML Report",
        "ja": "HTMLレポートをエクスポート",
    },
    "save_report_html": {
        "zh-CN": "保存可视化报告",
        "en": "Save visual report",
        "ja": "可視化レポートを保存",
    },
    "report_html_filename": {
        "zh-CN": "学习报告_{ts}.html",
        "en": "report_{ts}.html",
        "ja": "レポート_{ts}.html",
    },
    "report_html_saved": {
        "zh-CN": "可视化报告已保存到:\n{filename}\n（双击即可在浏览器中打开）",
        "en": "Visual report saved to:\n{filename}\n(Double-click to open in a browser)",
        "ja": "可視化レポートを保存しました:\n{filename}\n（ブラウザで開けます）",
    },
    "html_overview": {
        "zh-CN": "掌握度概览",
        "en": "Mastery Overview",
        "ja": "習得度概要",
    },
    "html_avg": {"zh-CN": "平均掌握度", "en": "Average mastery", "ja": "平均習得度"},
    "html_network": {
        "zh-CN": "概念网络图（按掌握度着色）",
        "en": "Concept Network (coloured by mastery)",
        "ja": "概念ネットワーク（習得度で色分け）",
    },
    "html_concepts": {"zh-CN": "概念详情", "en": "Concept Details", "ja": "概念の詳細"},
    "html_mastery": {"zh-CN": "掌握度", "en": "Mastery", "ja": "習得度"},
    "html_legend": {"zh-CN": "图例", "en": "Legend", "ja": "凡例"},
    "html_no_relations": {
        "zh-CN": "（该资产关系太少，仅展示概念节点）",
        "en": "(Too few relations — showing concept nodes only)",
        "ja": "（関係が少ないため概念ノードのみ表示）",
    },
    "html_no_concepts": {
        "zh-CN": "（暂无可展示的概念数据）",
        "en": "(No concept data to display yet)",
        "ja": "（表示する概念データがありません）",
    },
    "html_trend": {"zh-CN": "掌握度趋势", "en": "Mastery Trend", "ja": "習得度の推移"},
    "trend_avg_score": {"zh-CN": "平均得分", "en": "Avg Score", "ja": "平均スコア"},
    "trend_mastered": {"zh-CN": "已掌握", "en": "Mastered", "ja": "習得済み"},
    "priority_fmt": {
        "zh-CN": "优先级 {s:.2f}",
        "en": "priority {s:.2f}",
        "ja": "優先度 {s:.2f}",
    },
    "focus_title": {
        "zh-CN": "聚焦：{name}（概念结构图）",
        "en": "Focus: {name} (concept map)",
        "ja": "フォーカス: {name}（概念図）",
    },
    "concept_structure": {"zh-CN": "概念结构图", "en": "Concept Map", "ja": "概念図"},
    "import_success_title": {
        "zh-CN": "导入成功",
        "en": "Import succeeded",
        "ja": "インポート成功",
    },
    "import_failed": {
        "zh-CN": "处理失败: {msg}",
        "en": "Processing failed: {msg}",
        "ja": "処理に失敗: {msg}",
    },
    "selflearning": {
        "zh-CN": "正在自我学习...",
        "en": "Self-learning…",
        "ja": "自己学習中…",
    },
    "selflearning_done": {
        "zh-CN": "自我学习完成: {n} 条待解项",
        "en": "Self-learning done: {n} open anomalies",
        "ja": "自己学習完了: 未解決 {n} 件",
    },
    "quiz_title": {
        "zh-CN": "⚡ 快速自测",
        "en": "⚡ Quick Self-Test",
        "ja": "⚡ クイック自習",
    },
    "quiz_hint": {
        "zh-CN": "让导师针对本概念出一道判断题或排序题，检验是否真正掌握",
        "en": "The tutor generates a true/false or ordering question to check your grasp",
        "ja": "チューターが真偽または並べ替え問題を出して理解度を確認",
    },
    "quiz_start": {"zh-CN": "生成自测题", "en": "Generate", "ja": "問題を生成"},
    "quiz_failed": {
        "zh-CN": "（自测题生成失败，请重试）",
        "en": "(self-test generation failed — try again)",
        "ja": "（問題の生成に失敗しました。再試行してください）",
    },
    "quiz_true_false": {"zh-CN": "判断正误", "en": "True / False", "ja": "正誤判定"},
    "quiz_ordering": {"zh-CN": "步骤排序", "en": "Ordering", "ja": "順序並べ替え"},
    "quiz_true": {"zh-CN": "✓ 正确", "en": "✓ True", "ja": "✓ 正しい"},
    "quiz_false": {"zh-CN": "✗ 错误", "en": "✗ False", "ja": "✗ 誤り"},
    "quiz_check": {"zh-CN": "检查顺序", "en": "Check", "ja": "確認"},
    "quiz_correct": {"zh-CN": "答对了", "en": "Correct", "ja": "正解"},
    "quiz_wrong": {"zh-CN": "答错了", "en": "Wrong", "ja": "不正解"},
    "quiz_correct_order": {
        "zh-CN": "正确顺序",
        "en": "Correct order",
        "ja": "正しい順序",
    },
    "search_in_source": {
        "zh-CN": "🔍 搜索原文（回车定位）",
        "en": "🔍 Search the source (Enter)",
        "ja": "🔍 原文を検索（Enter）",
    },
    "search_btn": {"zh-CN": "搜索", "en": "Search", "ja": "検索"},
    "search_hits": {
        "zh-CN": "找到 {n} 处",
        "en": "{n} matches",
        "ja": "{n} 件見つかりました",
    },
    "topics_title": {"zh-CN": "🧩 主题聚合", "en": "🧩 Topics", "ja": "🧩 トピック"},
    "topics_hint": {
        "zh-CN": "概念按知识关系自动聚类——每个主题是一组互相联系的概念，点击「学习主题」从头学起",
        "en": "Concepts cluster automatically by relation — each topic is a group of linked ideas; click to learn it from the start",
        "ja": "概念は関係性で自動クラスタリングされます。トピックをクリックして最初から学べます",
    },
    "learn_topic": {"zh-CN": "学习主题", "en": "Learn topic", "ja": "トピックを学ぶ"},
    "learn_next": {"zh-CN": "接下来学", "en": "Up next", "ja": "次に学ぶ"},
    "learn_start": {
        "zh-CN": "开始学习 →",
        "en": "Start learning →",
        "ja": "学習を始める →",
    },
    "learn_mastery": {
        "zh-CN": "当前掌握度 {pct}%",
        "en": "Current mastery {pct}%",
        "ja": "現在の習熟度 {pct}%",
    },
    "learn_after": {"zh-CN": "然后", "en": "Then", "ja": "次に"},
    "browse_all": {
        "zh-CN": "▸ 浏览全部概念 / 总览",
        "en": "▸ Browse all concepts / overview",
        "ja": "▸ すべての概念 / 概要",
    },
    "browse_all_hint": {
        "zh-CN": "完整概念列表、主题簇、知识图谱与掌握度统计都在这里，需要时再展开。",
        "en": "The full concept list, topic clusters, knowledge graph and mastery stats live here — expand only when you need them.",
        "ja": "完全な概念リスト・トピック・知識グラフ・習熟度統計はここに。必要な時だけ展開してください。",
    },
    "no_asset_hint": {
        "zh-CN": "还没有知识资产。先在左侧「导入」里加一本书或一份资料，我们马上开始。",
        "en": "No knowledge asset yet. Import a book or document from the sidebar to begin.",
        "ja": "まだ知識アセットがありません。サイドバーの「导入」から本や資料を追加してください。",
    },
    "explore_group": {"zh-CN": "探索", "en": "Explore", "ja": "探索"},
    "swap_concept": {
        "zh-CN": "换一个概念:",
        "en": "Switch concept:",
        "ja": "概念を変更:",
    },
    "practice_title": {"zh-CN": "🛠 动手实践", "en": "🛠 Hands-On", "ja": "🛠 実践演習"},
    "practice_hint": {
        "zh-CN": "技术学习的最终检验是动手：让导师针对本概念出证明/构造/伪代码/复现任务",
        "en": "The real test is doing it — the tutor designs a prove/construct/pseudo-code/reproduce task for this concept",
        "ja": "学びの最終確認は実践。概念に合わせて証明・構築・擬似コード・再現タスクを出します",
    },
    "practice_start": {
        "zh-CN": "生成实践任务",
        "en": "Generate task",
        "ja": "タスクを生成",
    },
    "practice_failed": {
        "zh-CN": "（实践任务生成失败，请重试）",
        "en": "(task generation failed — try again)",
        "ja": "（タスク生成に失敗しました。再試行してください）",
    },
    "practice_badge": {"zh-CN": "实践任务", "en": "Practice Task", "ja": "実践タスク"},
    "practice_hint_label": {"zh-CN": "提示：", "en": "Hint: ", "ja": "ヒント: "},
    "practice_answer_ph": {
        "zh-CN": "在这里写下你的解答（证明/构造/伪代码/步骤）...",
        "en": "Write your solution here (proof / construction / pseudo-code / steps)…",
        "ja": "ここに解答を書いてください（証明・構築・擬似コード・手順）…",
    },
    "practice_submit": {"zh-CN": "提交实践", "en": "Submit", "ja": "提出"},
    "edge_external": {"zh-CN": "外部", "en": "external", "ja": "外部"},
    "external_title": {
        "zh-CN": "外部概念 · ",
        "en": "External concept · ",
        "ja": "外部概念 · ",
    },
    "external_no_llm": {
        "zh-CN": "「{name}」是外部概念（来自大模型知识，不在本书中）。配置 LLM 后可点击查看解释。",
        "en": "\u201c{name}\u201d is an external concept (from the model's knowledge, not in this book). Configure an LLM to see its explanation.",
        "ja": "「{name}」は外部概念です（本にはなく、モデルの知識に由来）。LLMを設定すると説明を表示できます。",
    },
    "badge_hot": {
        "zh-CN": "高价值·未学",
        "en": "high-value, unlearned",
        "ja": "高価値・未学習",
    },
    "badge_important": {"zh-CN": "核心概念", "en": "core", "ja": "核心概念"},
    "badge_new": {"zh-CN": "新概念", "en": "new", "ja": "新概念"},
    "crosslink_title": {
        "zh-CN": "📎 与你已学的「{name}」相关（{asset}）",
        "en": "📎 Related to \u201c{name}\u201d you already learned ({asset})",
        "ja": "📎 既に学んだ「{name}」と関連（{asset}）",
    },
    "external_tag": {"zh-CN": "外部", "en": "EXT", "ja": "外部"},
    "analogy_title": {
        "zh-CN": "🧠 类比桥（用你熟悉的领域理解它）",
        "en": "🧠 Analogy Bridge (understand it via a domain you know)",
        "ja": "🧠 類比ブリッジ（知っている領域で理解）",
    },
    "practice_evaluating": {
        "zh-CN": "正在评估你的实践...",
        "en": "Evaluating your work…",
        "ja": "実践を評価中…",
    },
    "topic_size": {"zh-CN": "{n} 个概念", "en": "{n} concepts", "ja": "{n} 概念"},
    "search_none": {"zh-CN": "未找到匹配", "en": "No matches", "ja": "一致なし"},
    "toc_title": {"zh-CN": "📑 章节目录", "en": "📑 Contents", "ja": "📑 目次"},
    "toc_other": {
        "zh-CN": "其他/未标注章节",
        "en": "Other / unassigned",
        "ja": "その他/未割当",
    },
    "chapter_label": {
        "zh-CN": "所属章节：{ch}",
        "en": "Chapter: {ch}",
        "ja": "章: {ch}",
    },
    "loc_line": {
        "zh-CN": "原文第 {n} 行",
        "en": "source line {n}",
        "ja": "原文 {n} 行目",
    },
    "loc_page": {"zh-CN": "第 {n} 页", "en": "p. {n}", "ja": "{n}ページ"},
    "toc_hint": {
        "zh-CN": "点击章节查看概念分布，点击概念直接进入详情",
        "en": "Click a chapter to see its concepts; click a concept for details",
        "ja": "章をクリックで概念を表示、概念をクリックで詳細へ",
    },
    "chapter_empty": {
        "zh-CN": "（本资产暂无章节信息）",
        "en": "(no chapter info for this asset)",
        "ja": "（この資産に章情報はありません）",
    },
    "asset_label": {
        "zh-CN": "知识资产",
        "en": "Knowledge Assets",
        "ja": "ナレッジ資産",
    },
    "asset_deleted": {
        "zh-CN": "已删除资产",
        "en": "Asset deleted",
        "ja": "資産を削除しました",
    },
    "no_asset_placeholder": {
        "zh-CN": "请先导入知识资产",
        "en": "Import a knowledge asset first",
        "ja": "先に知識資産をインポートしてください",
    },
    "graph_hint": {
        "zh-CN": "拖拽平移 · 滚轮缩放 · 点击概念查看详情",
        "en": "Drag to pan · scroll to zoom · click a concept for details",
        "ja": "ドラッグで移動 · ホイールでズーム · コンセプトをクリックで詳細",
    },
    "no_concepts": {
        "zh-CN": "（无可绘制概念）",
        "en": "(No concepts to draw)",
        "ja": "（描画可能なコンセプトなし）",
    },
    "baseline_novice": {"zh-CN": "陌生", "en": "Novice", "ja": "未経験"},
    "baseline_some": {
        "zh-CN": "了解一些",
        "en": "Some familiarity",
        "ja": "多少知っている",
    },
    "baseline_practiced": {"zh-CN": "已有实践", "en": "Practiced", "ja": "実践あり"},
    "style_example": {"zh-CN": "例子", "en": "Examples", "ja": "例"},
    "style_diagram": {"zh-CN": "图示", "en": "Diagram", "ja": "図解"},
    "style_steps": {"zh-CN": "拆解步骤", "en": "Step breakdown", "ja": "ステップ分解"},
    "ext_analyzing": {
        "zh-CN": "正在分析文本，抽取概念、关系与学习路径…",
        "en": "Analyzing text, extracting concepts, relations and learning path…",
        "ja": "テキストを分析中、概念・関係・学習経路を抽出…",
    },
    "ext_llm_failed": {
        "zh-CN": "LLM 返回无法解析为 JSON",
        "en": "LLM returned unparseable JSON",
        "ja": "LLMの応答がJSONとして解析できません",
    },
    "ext_done": {
        "zh-CN": "已抽取 {n} 个概念、{r} 条关系",
        "en": "Extracted {n} concepts, {r} relations",
        "ja": "{n}個の概念、{r}個の関係抽出完了",
    },
    "ext_chunks_start": {
        "zh-CN": "开始逐段分析（共 {n} 段，并行处理）…",
        "en": "Starting section analysis ({n} chunks, parallel)…",
        "ja": "セクション分析開始（{n}チャンク、並列処理）…",
    },
    "ext_chunk_progress": {
        "zh-CN": "已分析 {d}/{t} 段，累计 {n} 个概念…",
        "en": "Analyzed {d}/{t} chunks, {n} concepts so far…",
        "ja": "{d}/{t}チャンク分析済み、{n}個の概念…",
    },
    "teacher_no_llm_skip": {
        "zh-CN": "未配置 LLM，跳过自我学习（可在认知导航页重新自检）",
        "en": "No LLM configured — skipping self-learning (re-run from the cognitive map)",
        "ja": "LLM未設定—自己学習をスキップ（認知マップから再実行可）",
    },
    "teacher_no_llm_anomaly": {
        "zh-CN": "未配置 LLM（EXPERTANYTHING_LLM_API_KEY）。自我学习层（概念深加工与异常检测）无法运行。配置 key 后点击「重新自检」即可生成。",
        "en": "No LLM configured (EXPERTANYTHING_LLM_API_KEY). The self-learning layer (concept enrichment & anomaly detection) cannot run. Set the key and click 'Re-check' to generate it.",
        "ja": "LLM未設定（EXPERTANYTHING_LLM_API_KEY）。自己学習層（概念深加工・異常検出）が実行できません。key設定後「再チェック」をクリックで生成されます。",
    },
    "teacher_self_learning": {
        "zh-CN": "正在自我学习：深加工每个概念、扫描矛盾/未定义/反常…",
        "en": "Self-learning in progress: enriching concepts and scanning for anomalies…",
        "ja": "自己学習中：各概念を深加工、矛盾/未定義/異常をスキャン…",
    },
    "teacher_self_learning_done": {
        "zh-CN": "自我学习完成：{n} 条待解项",
        "en": "Self-learning done: {n} open items",
        "ja": "自己学習完了：{n}個の未解決項目",
    },
    "teacher_batch_progress": {
        "zh-CN": "自我学习批次 {b}/{t}",
        "en": "Self-learning batch {b}/{t}",
        "ja": "自己学習バッチ {b}/{t}",
    },
    "teacher_self_learn_fail": {
        "zh-CN": "自我学习出错，已降级为确定性模式",
        "en": "Self-learning failed — falling back to deterministic mode",
        "ja": "自己学習エラー—決定的モードにフォールバック",
    },
    "ext_chunks_failed": {
        "zh-CN": "所有分块都未能解析为 JSON",
        "en": "All chunks failed to parse as JSON",
        "ja": "全チャンクがJSON解析に失敗しました",
    },
    "ext_chunks_done": {
        "zh-CN": "已完成抽取：{n} 个概念、{r} 条关系",
        "en": "Extraction complete: {n} concepts, {r} relations",
        "ja": "抽出完了：{n}個の概念、{r}個の関係",
    },
    "ext_no_content": {
        "zh-CN": "请提供材料内容",
        "en": "Please provide content to analyze",
        "ja": "分析する内容を入力してください",
    },
    "ext_llm_fallback": {
        "zh-CN": "LLM 抽取失败，已降级为确定性结构索引",
        "en": "LLM extraction failed — falling back to deterministic indexing",
        "ja": "LLM抽出失敗、決定論的インデックスにフォールバック",
    },
    "ext_no_llm": {
        "zh-CN": "未配置 LLM，使用确定性结构索引（无需联网）",
        "en": "No LLM configured — using deterministic indexing (no network required)",
        "ja": "LLM未設定—決定論的インデックスを使用（ネットワーク不要）",
    },
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
        key = {
            "novice": "baseline_novice",
            "some": "baseline_some",
            "practiced": "baseline_practiced",
        }.get(code)
    else:
        key = {
            "example": "style_example",
            "diagram": "style_diagram",
            "steps": "style_steps",
        }.get(code)
    return t(key) if key else code
