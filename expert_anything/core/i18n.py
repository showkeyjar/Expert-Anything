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
    "read_source": {"zh-CN": "阅读原文", "en": "Read Source", "ja": "原文を読む"},
    "asset_tooltip": {
        "zh-CN": "{title}\n{count} 个知识实体",
        "en": "{title}\n{count} knowledge entities",
        "ja": "{title}\n{count}件のナレッジエンティティ",
    },
    "import_title": {
        "zh-CN": "导入知识资产",
        "en": "Import Knowledge",
        "ja": "ナレッジ資産をインポート",
    },
    "asset_name": {"zh-CN": "资产名称", "en": "Asset name", "ja": "資産名"},
    "no_asset": {
        "zh-CN": "请先导入一个知识资产。",
        "en": "Please import a knowledge asset first.",
        "ja": "まずナレッジ資産をインポートしてください。",
    },
    "fatal_error": {"zh-CN": "运行出错", "en": "Runtime Error", "ja": "実行時エラー"},
    "fatal_error_body": {
        "zh-CN": "发生未处理的错误：{msg}",
        "en": "An unhandled error occurred: {msg}",
        "ja": "未処理のエラーが発生しました：{msg}",
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
    "concept_notes": {
        "zh-CN": "概念深加工理解",
        "en": "Concept deep-analysis",
        "ja": "コンセプト深掘り理解",
    },
    "baseline_label": {
        "zh-CN": "现在的基础",
        "en": "Your current level",
        "ja": "現在のレベル",
    },
    "style_dd_label": {
        "zh-CN": "讲解方式（实时切换）",
        "en": "Explanation style (live switch)",
        "ja": "解説スタイル（リアルタイム切替）",
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
    "action_path": {
        "zh-CN": "用起来的行动路径",
        "en": "Action path to apply it",
        "ja": "実践への行動パス",
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
    "profile": {"zh-CN": "画像", "en": "Profile", "ja": "プロフィール"},
    "profile_text": {
        "zh-CN": "目标：{goal} ｜ 基础：{baseline} ｜ 偏好：{style}",
        "en": "Goal: {goal} ｜ Baseline: {baseline} ｜ Preference: {style}",
        "ja": "目標：{goal} ｜ 基礎：{baseline} ｜ 嗜好：{style}",
    },
    "profile_domain_item": {
        "zh-CN": "领域：{domain} ｜ 判定：{level} ｜ 依据：{reason}",
        "en": "Domain: {domain} ｜ Level: {level} ｜ Basis: {reason}",
        "ja": "分野：{domain} ｜ 判定：{level} ｜ 根拠：{reason}",
    },
    "profile_domain_item_short": {
        "zh-CN": "领域：{domain} ｜ 判定：{level}",
        "en": "Domain: {domain} ｜ Level: {level}",
        "ja": "分野：{domain} ｜ 判定：{level}",
    },
    "profile_level_novice": {
        "zh-CN": "零基础",
        "en": "Novice",
        "ja": "初心者",
    },
    "profile_level_some": {
        "zh-CN": "有基础",
        "en": "Some background",
        "ja": "基礎あり",
    },
    "profile_level_practiced": {
        "zh-CN": "专业",
        "en": "Advanced",
        "ja": "専門",
    },
    "profile_level_unknown": {
        "zh-CN": "未知",
        "en": "Unknown",
        "ja": "不明",
    },
    "profile_reason_no_data": {
        "zh-CN": "尚无学习记录，无法判定",
        "en": "No learning activity yet — cannot be judged",
        "ja": "学習記録がなく判定できません",
    },
    "profile_reason_no_template": {
        "zh-CN": "领域 {domain} 无术语模板",
        "en": "No template for domain {domain}",
        "ja": "分野 {domain} の用語テンプレートがありません",
    },
    "profile_reason_no_match": {
        "zh-CN": "尚未接触该领域 {total} 个已登记概念中的任何一个",
        "en": "None of the {total} registered concepts touched yet",
        "ja": "登録済み{total}件のいずれにも未接触",
    },
    "profile_reason_scores": {
        "zh-CN": "最近 {n} 次评估均分 {avg}",
        "en": "Average {avg} over the last {n} evaluations",
        "ja": "直近{n}回の平均 {avg}",
    },
    "profile_reason_coverage": {
        "zh-CN": "已接触 {matched}/{total} 个概念（{percent}%）",
        "en": "Covered {matched}/{total} concepts ({percent}%)",
        "ja": "{total}件中{matched}件に接触（{percent}%）",
    },
    "profile_reason_declared": {
        "zh-CN": "学习者自述基础：{baseline}",
        "en": "Self-declared baseline: {baseline}",
        "ja": "自己申告の基礎：{baseline}",
    },
    "profile_reason_mastered": {
        "zh-CN": "已掌握 {mastered}/{matched} 个已接触概念",
        "en": "Mastered {mastered} of {matched} touched concepts",
        "ja": "接触済み{matched}件中{mastered}件を習得",
    },
    "profile_hint_foundation": {
        "zh-CN": "建议从定义与原文依据起步",
        "en": "Start from definitions and original evidence",
        "ja": "定義と原文根拠から始めましょう",
    },
    "profile_hint_standard": {
        "zh-CN": "可直接进入案例与推理",
        "en": "Cases and reasoning are within reach",
        "ja": "事例と推論へ進めます",
    },
    "profile_hint_advanced": {
        "zh-CN": "可跳过基础，聚焦争议与建模",
        "en": "Skip the basics — focus on debates and modelling",
        "ja": "基礎を飛ばし、論点とモデリングへ",
    },
    "profile_hint_unknown": {
        "zh-CN": "再做一次练习即可判定",
        "en": "One more practice will settle the level",
        "ja": "もう一度演習すると判定できます",
    },
    "terminology": {
        "zh-CN": "术语对照",
        "en": "Terminology",
        "ja": "用語対応",
    },
    "terminology_self": {
        "zh-CN": "本课术语",
        "en": "Lesson term",
        "ja": "本課の用語",
    },
    "terminology_alias": {
        "zh-CN": "别名",
        "en": "Aliases",
        "ja": "別名",
    },
    "terminology_definition": {
        "zh-CN": "释义",
        "en": "Definition",
        "ja": "定義",
    },
    "terminology_key_points": {
        "zh-CN": "要点",
        "en": "Key points",
        "ja": "要点",
    },
    "terminology_related": {
        "zh-CN": "相关术语",
        "en": "Related terms",
        "ja": "関連用語",
    },
    "terminology_matched": {
        "zh-CN": "命中「{matched}」",
        "en": 'matched "{matched}"',
        "ja": "一致「{matched}」",
    },
    "terminology_none": {
        "zh-CN": "该概念未登记在领域术语表中，内容均来自原文，未作推断",
        "en": "This concept is not registered in the domain glossary; content comes from the source only",
        "ja": "この概念は用語集に未登録です（内容は原文のみに基づきます）",
    },
    "terminology_source_note": {
        "zh-CN": "术语与释义取自领域模板，未登记的术语不做推断",
        "en": "Terms and definitions come from the domain template — nothing is inferred",
        "ja": "用語と定義は分野テンプレートに基づきます（推測は行いません）",
    },
    "terminology_count": {
        "zh-CN": "已登记术语 {count} 条 / {chapters} 章",
        "en": "{count} registered terms across {chapters} chapters",
        "ja": "登録用語 {count} 件 / {chapters} 章",
    },
    "mastery": {
        "zh-CN": "概念掌握度",
        "en": "Concept mastery",
        "ja": "コンセプト習得度",
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
    "anomaly_section": {
        "zh-CN": "异常 / 待解清单（{n} 条，系统走在学生前面）",
        "en": "Anomalies / open items ({n}, system walks ahead)",
        "ja": "異常 / 未解決リスト（{n}件、システムが先を歩む）",
    },
    "global_graph_title": {
        "zh-CN": "全部资产概念图谱",
        "en": "All Assets Concept Map",
        "ja": "全アセット概念マップ",
    },
    "edge_shared": {"zh-CN": "共享概念", "en": "Shared", "ja": "共有"},
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
    "recommend_next": {
        "zh-CN": "推荐下一步",
        "en": "Recommended next",
        "ja": "次の推奨",
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
    "legend_unanchored": {
        "zh-CN": "无原文锚点",
        "en": "No source anchor",
        "ja": "原文アンカーなし",
    },
    "unanchored_tip": {
        "zh-CN": "此概念暂无原文锚点：由领域模板补全，或其证据未能在原文中定位。",
        "en": "This concept has no source anchor: filled in by a domain template, or its evidence could not be located in the source text.",
        "ja": "この概念には原文アンカーがありません。ドメインテンプレートで補完されたか、証拠を原文中に定位できませんでした。",
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
    "nav_assets": {"zh-CN": "全部资产", "en": "All Assets", "ja": "全アセット"},
    "lang": {"zh-CN": "语言", "en": "Language", "ja": "言語"},
    "app_name": {
        "zh-CN": "ExpertAnything",
        "en": "ExpertAnything",
        "ja": "ExpertAnything",
    },
    "btn_teach": {"zh-CN": "教学", "en": "Teach", "ja": "教学"},
    "btn_map": {"zh-CN": "概念地图", "en": "Map", "ja": "概念マップ"},
    "btn_source": {"zh-CN": "阅读原文", "en": "Source", "ja": "原文"},
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
    "topbar_progress": {
        "zh-CN": "已掌握 {m}/{t} · 学习中 {l} · 待复习 {r}",
        "en": "Mastered {m}/{t} · Learning {l} · Due {r}",
        "ja": "習得 {m}/{t} · 学習中 {l} · 復習待ち {r}",
    },
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
    "unknown_error": {"zh-CN": "未知错误", "en": "Unknown error", "ja": "不明なエラー"},
    "retry": {"zh-CN": "重试", "en": "Retry", "ja": "再試行"},
    "diff_easy": {"zh-CN": "易", "en": "Easy", "ja": "易"},
    "diff_medium": {"zh-CN": "中", "en": "Medium", "ja": "中"},
    "diff_hard": {"zh-CN": "难", "en": "Hard", "ja": "難"},
    "diff_label": {"zh-CN": "难度", "en": "Difficulty", "ja": "難易度"},
    "method_llm_chunked": {
        "zh-CN": "LLM 多分块并行抽取",
        "en": "LLM parallel chunk extraction",
        "ja": "LLM 並列チャンク抽出",
    },
    "method_llm": {"zh-CN": "LLM 抽取", "en": "LLM extraction", "ja": "LLM 抽出"},
    "method_fallback": {
        "zh-CN": "确定性降级",
        "en": "Deterministic fallback",
        "ja": "決定論的フォールバック",
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
    "legend_focus": {
        "zh-CN": "聚焦/推荐",
        "en": "Focus / Top pick",
        "ja": "フォーカス/おすすめ",
    },
    "legend_anomaly": {"zh-CN": "系统存疑", "en": "Anomaly", "ja": "疑義あり"},
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
        "en": 'No concept "{kw}" in the map',
        "ja": "マップに「{kw}」はありません",
    },
    "search_title": {
        "zh-CN": "搜索结果",
        "en": "Search Results",
        "ja": "検索結果",
    },
    "search_results_title": {
        "zh-CN": "跨资产搜索结果",
        "en": "Cross-asset Search Results",
        "ja": "全資産検索結果",
    },
    "search_results_hint": {
        "zh-CN": "找到 {n} 个匹配「{kw}」的概念，双击或点击打开：",
        "en": 'Found {n} concepts matching "{kw}". Double-click or press Open:',
        "ja": "「{kw}」に一致する概念が {n} 件見つかりました：",
    },
    "search_open": {
        "zh-CN": "打开",
        "en": "Open",
        "ja": "開く",
    },
    "search_field_name": {"zh-CN": "概念名", "en": "Concept", "ja": "コンセプト名"},
    "search_field_alias": {"zh-CN": "别名", "en": "Alias", "ja": "別名"},
    "search_field_definition": {
        "zh-CN": "定义",
        "en": "Definition",
        "ja": "定義",
    },
    "search_field_summary": {
        "zh-CN": "摘要",
        "en": "Summary",
        "ja": "要約",
    },
    "search_field_evidence": {
        "zh-CN": "证据",
        "en": "Evidence",
        "ja": "根拠",
    },
    "search_field_source": {
        "zh-CN": "原文",
        "en": "Source",
        "ja": "原文",
    },
    "search_fulltext_title": {
        "zh-CN": "🔎 全文搜索结果",
        "en": "🔎 Full-text Search Results",
        "ja": "🔎 全文検索結果",
    },
    "search_fulltext_hint": {
        "zh-CN": "未找到同名概念，改为按定义/证据/原文匹配「{kw}」共 {n} 处：",
        "en": 'No concept named "{kw}" — matched {n} passages in definitions/evidence/source:',
        "ja": "同名コンセプトがありません。「{kw}」の定義・根拠・原文に {n} 件一致：",
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
    "style_label": {"zh-CN": "教学风格:", "en": "Style:", "ja": "スタイル:"},
    "style_effect_title": {
        "zh-CN": "📊 教学风格效果分析",
        "en": "📊 Teaching Style Effectiveness",
        "ja": "📊 教授スタイル効果分析",
    },
    "style_count": {
        "zh-CN": "{n}次",
        "en": "{n} attempts",
        "ja": "{n}回",
    },
    "style_best": {
        "zh-CN": "最佳",
        "en": "Best",
        "ja": "ベスト",
    },
    "style_insight": {
        "zh-CN": "💡 你用「{style}」学习效果最好，系统将优先使用此风格教学",
        "en": '💡 You learn best with "{style}" — the system will prefer this style',
        "ja": "💡 「{style}」の学習効果が最も高いです。システムはこのスタイルを優先します",
    },
    "blind_spot_title": {
        "zh-CN": "⚠️ 知识盲区雷达",
        "en": "⚠️ Knowledge Blind Spots",
        "ja": "⚠️ 知識の盲点レーダー",
    },
    "blind_spot_hint": {
        "zh-CN": "以下概念被很多其他概念依赖，但你尚未学习或掌握度低——这是最大的知识风险点",
        "en": "These concepts are prerequisites for many others but you haven't learned them yet — highest risk gaps",
        "ja": "これらは多くの概念の前提ですが未習得です — 最大のリスク",
    },
    "blind_spot_fix": {
        "zh-CN": "立即学习",
        "en": "Learn Now",
        "ja": "今すぐ学習",
    },
    "plan_title": {
        "zh-CN": "📋 今日学习计划（30分钟）",
        "en": "📋 Today's Study Plan (30 min)",
        "ja": "📋 今日の学習計画（30分）",
    },
    "plan_total_time": {
        "zh-CN": "共{n}分钟 · {count}个概念",
        "en": "{n} min · {count} concepts",
        "ja": "{n}分 · {count}概念",
    },
    "plan_start": {
        "zh-CN": "开始",
        "en": "Start",
        "ja": "開始",
    },
    "export_png": {
        "zh-CN": "📷 导出图谱",
        "en": "📷 Export PNG",
        "ja": "📷 エクスポート",
    },
    "export_png_tip": {
        "zh-CN": "将当前知识图谱导出为PNG高清图片",
        "en": "Export the current knowledge graph as a high-res PNG image",
        "ja": "現在の知識グラフをPNG画像としてエクスポート",
    },
    "export_png_dialog": {
        "zh-CN": "保存图谱图片",
        "en": "Save Graph Image",
        "ja": "グラフ画像を保存",
    },
    "export_success": {
        "zh-CN": "导出成功",
        "en": "Export Successful",
        "ja": "エクスポート成功",
    },
    "export_saved_to": {
        "zh-CN": "图谱已保存到：{path}",
        "en": "Graph saved to: {path}",
        "ja": "グラフを保存しました：{path}",
    },
    "export_failed": {
        "zh-CN": "导出失败",
        "en": "Export Failed",
        "ja": "エクスポート失敗",
    },
    "export_failed_msg": {
        "zh-CN": "无法导出图谱图片，请确认图谱已加载",
        "en": "Could not export the graph. Make sure a graph is loaded.",
        "ja": "グラフをエクスポートできません。グラフが読み込まれているか確認してください。",
    },
    "efficiency_title": {
        "zh-CN": "📊 学习效率仪表盘",
        "en": "📊 Learning Efficiency Dashboard",
        "ja": "📊 学習効率ダッシュボード",
    },
    "eff_sessions": {
        "zh-CN": "学习次数",
        "en": "Sessions",
        "ja": "学習回数",
    },
    "eff_concepts": {
        "zh-CN": "已学概念",
        "en": "Concepts",
        "ja": "学習済み概念",
    },
    "eff_avg_score": {
        "zh-CN": "平均得分",
        "en": "Avg Score",
        "ja": "平均スコア",
    },
    "eff_roi": {
        "zh-CN": "掌握度ROI",
        "en": "Mastery ROI",
        "ja": "習熟度ROI",
    },
    "eff_trend_up": {
        "zh-CN": "趋势↗",
        "en": "Trend↗",
        "ja": "傾向↗",
    },
    "eff_trend_stable": {
        "zh-CN": "趋势→",
        "en": "Trend→",
        "ja": "傾向→",
    },
    "eff_trend_down": {
        "zh-CN": "趋势↘",
        "en": "Trend↘",
        "ja": "傾向↘",
    },
    "eff_trend_unknown": {
        "zh-CN": "趋势?",
        "en": "Trend?",
        "ja": "傾向?",
    },
    "edge_teach_title": {
        "zh-CN": "关系教学",
        "en": "Relation Teaching",
        "ja": "関係教育",
    },
    "edge_teach_msg": {
        "zh-CN": "检测到「{src}」与「{tgt}」之间的{rel}。\n是否开始学习「{src}」？",
        "en": 'Detected {rel} between "{src}" and "{tgt}".\nStart learning "{src}"?',
        "ja": "「{src}」と「{tgt}」の間に{rel}があります。\n「{src}」の学習を開始しますか？",
    },
    "dep_chain": {
        "zh-CN": "🔗 依赖链",
        "en": "🔗 Dep Chain",
        "ja": "🔗 依存チェーン",
    },
    "dep_chain_tip": {
        "zh-CN": "高亮当前概念的完整前提依赖链（从根到当前概念）",
        "en": "Highlight the full prerequisite chain for the focused concept (root → current)",
        "ja": "フォーカス中の概念の完全な前提依存チェーンをハイライト（ルート→現在）",
    },
    "goal_title": {
        "zh-CN": "🎯 学习目标",
        "en": "🎯 Study Goal",
        "ja": "🎯 学習目標",
    },
    "goal_set": {
        "zh-CN": "🎯 设置学习目标",
        "en": "🎯 Set Study Goal",
        "ja": "🎯 学習目標を設定",
    },
    "goal_completed": {
        "zh-CN": "✅ 已完成",
        "en": "✅ Completed",
        "ja": "✅ 完了",
    },
    "goal_expired": {
        "zh-CN": "❌ 已过期",
        "en": "❌ Expired",
        "ja": "❌ 期限切れ",
    },
    "goal_on_track": {
        "zh-CN": "🟢 进度正常",
        "en": "🟢 On Track",
        "ja": "🟢 順調",
    },
    "goal_behind": {
        "zh-CN": "🟡 需要加速",
        "en": "🟡 Need to Speed Up",
        "ja": "🟡 加速が必要",
    },
    "goal_days_left": {
        "zh-CN": "剩余 {n} 天",
        "en": "{n} days left",
        "ja": "残り{n}日",
    },
    "goal_dialog_title": {
        "zh-CN": "设置学习目标",
        "en": "Set Study Goal",
        "ja": "学習目標を設定",
    },
    "goal_target_label": {
        "zh-CN": "目标概念数：",
        "en": "Target concepts:",
        "ja": "目標概念数：",
    },
    "goal_days_label": {
        "zh-CN": "天数：",
        "en": "Days:",
        "ja": "日数：",
    },
    "recommend_next": {
        "zh-CN": "🎯 智能推荐下一个",
        "en": "🎯 Smart Recommend Next",
        "ja": "🎯 次を推奨",
    },
    "recommend_tip": {
        "zh-CN": "根据掌握度、异常检测、语义关系自动推荐最佳学习概念",
        "en": "Auto-pick the best concept based on mastery, anomalies, and relations",
        "ja": "習熟度・異常・関係に基づき最適な概念を自動推奨",
    },
    "rec_reason_anom": {
        "zh-CN": "检测到知识异常",
        "en": "Knowledge anomaly detected",
        "ja": "知識異常を検出",
    },
    "rec_reason_stuck": {
        "zh-CN": "学习卡壳",
        "en": "Learning stuck",
        "ja": "学習が停滞",
    },
    "rec_reason_weak": {
        "zh-CN": "掌握度不足",
        "en": "Low mastery",
        "ja": "習熟度不足",
    },
    "rec_reason_leverage": {
        "zh-CN": "高杠杆概念",
        "en": "High leverage",
        "ja": "高レバレッジ",
    },
    "rec_reason_ready": {
        "zh-CN": "前提已就绪",
        "en": "Prerequisites ready",
        "ja": "前提条件クリア",
    },
    "rec_reason_prereq": {
        "zh-CN": "前提薄弱需巩固",
        "en": "Prerequisite needs shoring up",
        "ja": "前提の補強が必要",
    },
    "rec_reason_unblock_stuck": {
        "zh-CN": "能解除下游卡壳",
        "en": "Unblocks stuck downstream",
        "ja": "停滞を解除",
    },
    "rec_reason_foundation": {
        "zh-CN": "基础概念",
        "en": "Foundational",
        "ja": "基礎概念",
    },
    "rec_reason_default": {
        "zh-CN": "学习路径推荐",
        "en": "Study path order",
        "ja": "学習パス順",
    },
    "rec_toast": {
        "zh-CN": "🎯 推荐学习「{name}」—— {reason}",
        "en": '🎯 Recommended: "{name}" — {reason}',
        "ja": "🎯 推奨：「{name}」— {reason}",
    },
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
    "source_provenance": {
        "zh-CN": "📚 本讲解基于以下原文证据",
        "en": "📚 This lesson is grounded in the following evidence",
        "ja": "📚 この講義は以下の原文に基づいています",
    },
    "loc_page_and_line": {
        "zh-CN": "第{page}页 · 第{line}行",
        "en": "p. {page} · line {line}",
        "ja": "{page}ページ · {line}行目",
    },
    "loc_line_only": {
        "zh-CN": "第{line}行",
        "en": "line {line}",
        "ja": "{line}行目",
    },
    "evidence_jump_tip": {
        "zh-CN": "在原文中查看此证据",
        "en": "Show this evidence in the source text",
        "ja": "原文でこの証拠を表示",
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
    "related_concepts": {
        "zh-CN": "关联概念（顺藤摸瓜）",
        "en": "Related concepts",
        "ja": "関連概念",
    },
    "minigraph_prereqs": {
        "zh-CN": "前提概念",
        "en": "Prerequisites",
        "ja": "前提概念",
    },
    "minigraph_nexts": {
        "zh-CN": "后继概念",
        "en": "Next concepts",
        "ja": "次の概念",
    },
    "eval_result": {"zh-CN": "评估结果", "en": "Evaluation", "ja": "評価結果"},
    "learn_next": {
        "zh-CN": "接下来学习",
        "en": "Learn next",
        "ja": "次を学ぶ",
    },
    "learn_retry": {
        "zh-CN": "再讲一次",
        "en": "Explain again",
        "ja": "もう一度説明",
    },
    "learn_vary": {
        "zh-CN": "换一种讲法",
        "en": "Try another angle",
        "ja": "別の角度で",
    },
    "eval_reference": {
        "zh-CN": "参考回答（基于原文证据）",
        "en": "Reference answer (source-grounded)",
        "ja": "参考回答（原文に基づく）",
    },
    "eval_gap": {"zh-CN": "与参考的差距", "en": "Gap vs reference", "ja": "参考との差"},
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
    "due_prereq_weak": {
        "zh-CN": "⚠ 前置薄弱",
        "en": "⚠ weak prerequisite",
        "ja": "⚠ 前提が弱い",
    },
    "due_tier_overdue": {
        "zh-CN": "已逾期",
        "en": "Overdue",
        "ja": "期限切れ",
    },
    "due_tier_due": {
        "zh-CN": "今日到期",
        "en": "Due today",
        "ja": "本日復習",
    },
    "due_tier_soon": {
        "zh-CN": "即将到期",
        "en": "Due soon",
        "ja": "まもなく復習",
    },
    "review_mode": {
        "zh-CN": "🔁 复习模式",
        "en": "🔁 Review Mode",
        "ja": "🔁 復習モード",
    },
    "review_all_btn": {
        "zh-CN": "⚡ 快速复习全部（{n}个）",
        "en": "⚡ Review All ({n})",
        "ja": "⚡ 一括復習（{n}件）",
    },
    "review_all_tip": {
        "zh-CN": "连续复习所有到期概念，逐个换角度重讲，直到全部刷新",
        "en": "Review all due concepts sequentially with varied angles",
        "ja": "期限切れ概念を連続復習（角度を変えて再講義）",
    },
    "review_session_title": {
        "zh-CN": "复习会话",
        "en": "Review Session",
        "ja": "復習セッション",
    },
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
    "error_book_title": {
        "zh-CN": "📒 错题本",
        "en": "📒 Error Book",
        "ja": "📒 エラーノート",
    },
    "error_book_count": {
        "zh-CN": "{n}个薄弱",
        "en": "{n} weak",
        "ja": "{n}件弱点",
    },
    "error_book_retry": {
        "zh-CN": "重学",
        "en": "Retry",
        "ja": "再学習",
    },
    "error_book_review_all": {
        "zh-CN": "复习全部错题",
        "en": "Review All Errors",
        "ja": "全エラーを復習",
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
    "detail_quick_quiz": {
        "zh-CN": "快速自测",
        "en": "Quick Quiz",
        "ja": "クイックテスト",
    },
    "detail_quick_quiz_tip": {
        "zh-CN": "30秒快速自测，检验你是否真正理解了这个概念",
        "en": "30-second self-test to check your understanding",
        "ja": "30秒で理解度を確認",
    },
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
    "compare_suggest_prereq": {
        "zh-CN": "💡 先夯实「{name}」——它是理解另一概念的前提",
        "en": "💡 Solidify 「{name}」 first — it's a prerequisite for the other",
        "ja": "💡 まず「{name}」を固めよう — もう一方の前提条件だから",
    },
    "compare_suggest_contrast": {
        "zh-CN": "💡 对比学习：列出两者的关键差异点，用表格整理更容易记忆",
        "en": "💡 Contrastive learning: list key differences in a table for better recall",
        "ja": "💡 対比学習：重要な違いを表にまとめると記憶に残りやすい",
    },
    "compare_suggest_bridge": {
        "zh-CN": "💡 以「{names}」为桥梁，从共享概念出发理解两者的关系",
        "en": "💡 Use 「{names}」 as bridges — understand both through shared concepts",
        "ja": "💡 「{names}」を橋渡しに — 共有概念から両者の関係を理解しよう",
    },
    "compare_suggest_review_weak": {
        "zh-CN": "💡 优先复习「{name}」——掌握度差距较大，补足后学习效率更高",
        "en": "💡 Review 「{name}」 first — large mastery gap; fixing it accelerates learning",
        "ja": "💡 まず「{name}」を復習 — 習得度差が大きく、補うと学習効率が上がる",
    },
    "compare_suggest_default": {
        "zh-CN": "💡 尝试用自己的话分别解释两个概念，再对比异同",
        "en": "💡 Try explaining both concepts in your own words, then compare",
        "ja": "💡 自分の言葉で両方の概念を説明してから、比較してみよう",
    },
    "compare_learn_order": {
        "zh-CN": "推荐学习顺序：{order}",
        "en": "Recommended order: {order}",
        "ja": "推奨学習順：{order}",
    },
    "compare_direct_rel": {
        "zh-CN": "直接关系：{rel}",
        "en": "Direct relation: {rel}",
        "ja": "直接の関係：{rel}",
    },
    "compare_suggestions_title": {
        "zh-CN": "学习建议",
        "en": "Learning Suggestions",
        "ja": "学習のヒント",
    },
    "detail_path_pos": {
        "zh-CN": "学习路径位置",
        "en": "Path Position",
        "ja": "学習パス位置",
    },
    "diff_easy_tip": {
        "zh-CN": "你在这个概念上表现优秀，通过率≥80%",
        "en": "You consistently score high on this concept (pass rate ≥80%)",
        "ja": "この概念は得意です（合格率80%以上）",
    },
    "diff_medium_tip": {
        "zh-CN": "这个概念有一定挑战，通过率50-80%",
        "en": "This concept is moderately challenging (pass rate 50-80%)",
        "ja": "やや難しい概念です（合格率50-80%）",
    },
    "diff_hard_tip": {
        "zh-CN": "这个概念对你来说较难，通过率<50%，建议多花时间",
        "en": "This concept is hard for you (pass rate <50%), spend more time",
        "ja": "難しい概念です（合格率50%未満）、重点的に学習を",
    },
    "diff_unknown_tip": {
        "zh-CN": "尚未有评估记录，难度未知",
        "en": "No evaluations yet, difficulty unknown",
        "ja": "評価記録なし、難易度不明",
    },
    "pred_title": {
        "zh-CN": "📊 掌握度预测",
        "en": "📊 Mastery Forecast",
        "ja": "📊 習熟度予測",
    },
    "pred_predicted": {
        "zh-CN": "预计掌握度",
        "en": "Predicted mastery",
        "ja": "予測習熟度",
    },
    "pred_will_achieve": {
        "zh-CN": "✓ 按当前趋势可达掌握",
        "en": "✓ On track to mastery",
        "ja": "✅ 習熟到達見込み",
    },
    "pred_wont_achieve": {
        "zh-CN": "⚠ 按当前趋势难以达标，需加强学习",
        "en": "⚠ Off track — needs more effort",
        "ja": "⚠ このままだと習熟困難、追加学習が必要",
    },
    "pred_already_mastered": {
        "zh-CN": "✓ 已掌握",
        "en": "✓ Already mastered",
        "ja": "✅ 習熟済み",
    },
    "pred_sessions_needed": {
        "zh-CN": "约需 {n} 次学习",
        "en": "~{n} sessions needed",
        "ja": "約{n}回の学習が必要",
    },
    "pred_no_data": {
        "zh-CN": "数据不足，学习 2 次后可预测",
        "en": "Insufficient data — learn 2× to forecast",
        "ja": "データ不足 — 2回学習後に予測可能",
    },
    "trend_rising": {
        "zh-CN": "上升趋势 ↑",
        "en": "Rising ↑",
        "ja": "上昇傾向 ↑",
    },
    "trend_falling": {
        "zh-CN": "下降趋势 ↓",
        "en": "Falling ↓",
        "ja": "下降傾向 ↓",
    },
    "trend_flat": {
        "zh-CN": "平稳 →",
        "en": "Flat →",
        "ja": "横ばい →",
    },
    "trend_unknown": {
        "zh-CN": "趋势未知",
        "en": "Trend unknown",
        "ja": "傾向不明",
    },
    "milestones_title": {
        "zh-CN": "🏅 成就里程碑",
        "en": "🏅 Milestones",
        "ja": "🏅 マイルストーン",
    },
    "ms_first_mastered": {
        "zh-CN": "初露新芽",
        "en": "First Step",
        "ja": "最初の一歩",
    },
    "ms_ten_mastered": {
        "zh-CN": "茁壮成长",
        "en": "Growing",
        "ja": "成長中",
    },
    "ms_fifty_mastered": {
        "zh-CN": "参天大树",
        "en": "Expertise",
        "ja": "大樹",
    },
    "ms_all_mastered": {
        "zh-CN": "全部掌握",
        "en": "Complete",
        "ja": "完全習得",
    },
    "ms_half_avg": {
        "zh-CN": "过半理解",
        "en": "Halfway",
        "ja": "半分理解",
    },
    "ms_high_avg": {
        "zh-CN": "深度掌握",
        "en": "Deep Mastery",
        "ja": "深い理解",
    },
    "ms_uptodate": {
        "zh-CN": "复习达人",
        "en": "Up to Date",
        "ja": "復習マスター",
    },
    "ms_active": {
        "zh-CN": "持续学习中",
        "en": "Active Learner",
        "ja": "学習継続中",
    },
    "ms_overcame": {
        "zh-CN": "攻克薄弱",
        "en": "Overcame Weakness",
        "ja": "弱点克服",
    },
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
    "tag_high_leverage": {
        "zh-CN": "高杠杆",
        "en": "High leverage",
        "ja": "高レバレッジ",
    },
    "tag_unblock_n": {
        "zh-CN": "解锁{n}个",
        "en": "Unlocks {n}",
        "ja": "{n}個をアンロック",
    },
    "decoder_card_title": {
        "zh-CN": "知识解译",
        "en": "Knowledge decoding",
        "ja": "知識の解読",
    },
    "quick_deconstruct_title": {
        "zh-CN": "知识全景",
        "en": "Knowledge Panorama",
        "ja": "知識パノラマ",
    },
    "quick_deconstruct_hint": {
        "zh-CN": "5分钟先看懂核心结构——点击分步动画，拖拽排序概念",
        "en": "5-min overview: step animation + concept sorting game",
        "ja": "5分で全体構造を把握—ステップアニメ＋並べ替えゲーム",
    },
    "rel_legend_title": {
        "zh-CN": "关系图例",
        "en": "Relation legend",
        "ja": "関係レジェンド",
    },
    "rel_is_a": {
        "zh-CN": "分类",
        "en": "is-a",
        "ja": "分類",
    },
    "rel_part_of": {
        "zh-CN": "组成",
        "en": "part-of",
        "ja": "構成",
    },
    "rel_causes": {
        "zh-CN": "因果",
        "en": "causes",
        "ja": "因果",
    },
    "rel_prereq": {
        "zh-CN": "前提",
        "en": "prerequisite",
        "ja": "前提",
    },
    "rel_contrast": {
        "zh-CN": "对比",
        "en": "contrast",
        "ja": "対比",
    },
    "rel_related": {
        "zh-CN": "关联",
        "en": "related",
        "ja": "関連",
    },
    "legend_edges_title": {
        "zh-CN": "关系类型",
        "en": "Relation types",
        "ja": "関係タイプ",
    },
    "sem_filter_tip": {
        "zh-CN": "高亮显示{type}关系",
        "en": "Highlight {type} relations",
        "ja": "{type}関係をハイライト",
    },
    "skeleton_view": {
        "zh-CN": "核心骨架",
        "en": "Core Skeleton",
        "ja": "コアスケルトン",
    },
    "skeleton_view_tip": {
        "zh-CN": "只显示最关键的概念和主干关系，快速把握知识全局",
        "en": "Show only the most important concepts and backbone relations",
        "ja": "最も重要な概念と幹の関係だけを表示",
    },
    "skeleton_exit": {
        "zh-CN": "显示全部",
        "en": "Show All",
        "ja": "すべて表示",
    },
    "density_view": {
        "zh-CN": "知识密度",
        "en": "Density Map",
        "ja": "知識密度",
    },
    "density_view_tip": {
        "zh-CN": "热力图显示知识密度（重要性×新颖性），红色=最高学习价值",
        "en": "Heatmap of knowledge density (importance × novelty), red = highest ROI",
        "ja": "知識密度ヒートマップ（重要度×新規性）、赤=学習効率最高",
    },
    "mastery_heat_view": {
        "zh-CN": "掌握度热力图",
        "en": "Mastery Heatmap",
        "ja": "習熟度ヒートマップ",
    },
    "mastery_heat_tip": {
        "zh-CN": "热力图显示掌握度：红色=薄弱，绿色=已掌握，一眼看清全局薄弱区",
        "en": "Mastery heatmap: red=weak, green=mastered — see global gaps at a glance",
        "ja": "習熟度ヒートマップ：赤=苦手、緑=習熟、全体の弱点が一目で分かる",
    },
    "concept_search_ph": {
        "zh-CN": "搜索概念名称或定义…",
        "en": "Search concept name or definition…",
        "ja": "概念名・定義を検索…",
    },
    "filter_all": {
        "zh-CN": "全部",
        "en": "All",
        "ja": "全て",
    },
    "filter_unstudied": {
        "zh-CN": "未学",
        "en": "Unstudied",
        "ja": "未学習",
    },
    "filter_weak": {
        "zh-CN": "薄弱",
        "en": "Weak",
        "ja": "苦手",
    },
    "filter_learning": {
        "zh-CN": "学习中",
        "en": "Learning",
        "ja": "学習中",
    },
    "filter_mastered": {
        "zh-CN": "已掌握",
        "en": "Mastered",
        "ja": "習得済み",
    },
    "ctx_teach": {
        "zh-CN": "进入教学",
        "en": "Teach this concept",
        "ja": "教える",
    },
    "ctx_evidence": {
        "zh-CN": "查看证据",
        "en": "View evidence",
        "ja": "証拠を見る",
    },
    "ctx_compare": {
        "zh-CN": "对比概念",
        "en": "Compare concepts",
        "ja": "概念を比較",
    },
    "ctx_focus": {
        "zh-CN": "聚焦此节点",
        "en": "Focus this node",
        "ja": "このノードにフォーカス",
    },
    "definition_label": {
        "zh-CN": "概念定义",
        "en": "Definition",
        "ja": "定義",
    },
    "evidence_label": {
        "zh-CN": "原文证据",
        "en": "Source evidence",
        "ja": "原文の証拠",
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
    "edge_prereq": {"zh-CN": "前置", "en": "prerequisite", "ja": "前提"},
    "edge_related": {"zh-CN": "关联", "en": "related", "ja": "関連"},
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
    "llm_not_ready_detail": {
        "zh-CN": "未配置模型服务；当前将使用确定性回退，仍可导入和建立基础知识图谱，但定义、关系和教师自检会较简化。配置模型服务后重新导入可获得完整体验。",
        "en": "No model service is configured; deterministic fallback is active. You can still import material and build a basic knowledge map, but definitions, relations and teacher checks will be simpler. Configure a model service and re-import for the full experience.",
        "ja": "モデルサービスが設定されていないため、決定論的フォールバックを使用します。資料のインポートと基本的な知識マップの作成はできますが、定義・関係・教師モデルのチェックは簡略化されます。完全な体験にはモデルサービスを設定して再インポートしてください。",
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
    "report_history": {
        "zh-CN": "【最近评估记录】",
        "en": "[Recent Evaluations]",
        "ja": "【最近の評価記録】",
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
    "import_failed": {
        "zh-CN": "处理失败: {msg}",
        "en": "Processing failed: {msg}",
        "ja": "処理に失敗: {msg}",
    },
    # -- domain template (领域模板) -----------------------------------------
    "domain_template_title": {
        "zh-CN": "领域模板",
        "en": "Domain template",
        "ja": "ドメインテンプレート",
    },
    "domain_template_ask": {
        "zh-CN": "检测到本资料可套用领域模板《{template}》：命中 {matched}/{total} 个模板概念（覆盖率 {pct}）。套用后将为命中的概念补充模板释义，并可能把学习路径更新为领域推荐顺序。是否套用？",
        "en": "A domain template matches this material: \u201c{template}\u201d — {matched}/{total} template concepts matched (coverage {pct}). Applying it fills in template definitions for matched concepts and may rewrite the learning path into the domain-recommended order. Apply it?",
        "ja": "この資料に適用できるドメインテンプレート「{template}」を検出しました（{matched}/{total} 概念が一致、カバレッジ {pct}）。適用すると一致した概念の定義を補完し、学習パスを領域推奨の順序に更新する場合があります。適用しますか？",
    },
    "domain_template_applied": {
        "zh-CN": "已套用领域模板《{template}》：命中 {matched}/{total} 个概念（覆盖率 {pct}），补充 {enriched} 个概念的释义，学习路径已更新为领域推荐顺序。",
        "en": "Domain template \u201c{template}\u201d applied: {matched}/{total} concepts matched (coverage {pct}), {enriched} concept(s) enriched, learning path rewritten into the domain order.",
        "ja": "ドメインテンプレート「{template}」を適用しました：{matched}/{total} 概念が一致（カバレッジ {pct}）、{enriched} 概念の定義を補完し、学習パスを領域推奨の順序に更新しました。",
    },
    "domain_template_applied_degraded": {
        "zh-CN": "已套用领域模板《{template}》：命中 {matched}/{total} 个概念（覆盖率 {pct}），补充 {enriched} 个概念的释义；学习路径保持原顺序（{reason}）。",
        "en": "Domain template \u201c{template}\u201d applied: {matched}/{total} concepts matched (coverage {pct}), {enriched} concept(s) enriched; the learning path was left untouched ({reason}).",
        "ja": "ドメインテンプレート「{template}」を適用しました：{matched}/{total} 概念が一致（カバレッジ {pct}）、{enriched} 概念の定義を補完。学習パスは元の順序のままです（{reason}）。",
    },
    "domain_template_reason_degraded_no_mapping": {
        "zh-CN": "模板概念未能与本文概念对应",
        "en": "no template concept matched this asset",
        "ja": "テンプレート概念が本資料の概念と一致しませんでした",
    },
    "domain_template_reason_degraded_low_coverage": {
        "zh-CN": "覆盖率低于阈值",
        "en": "coverage below the required threshold",
        "ja": "カバレッジが閾値未満",
    },
    "domain_template_reason_unknown_domain": {
        "zh-CN": "该领域暂无可用模板",
        "en": "no template registered for this domain",
        "ja": "この領域のテンプレートは未登録です",
    },
    "domain_template_reason_other": {
        "zh-CN": "未满足套用条件",
        "en": "apply conditions not met",
        "ja": "適用条件を満たしていません",
    },
    "domain_template_failed": {
        "zh-CN": "套用领域模板失败：{e}。本次导入将按原流程继续。",
        "en": "Applying the domain template failed: {e}. The import continues unchanged.",
        "ja": "ドメインテンプレートの適用に失敗しました：{e}。インポートはそのまま続行します。",
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
    "evaluate_failed": {
        "zh-CN": "（评估失败：{msg}）",
        "en": "(evaluation failed: {msg})",
        "ja": "（評価に失敗しました：{msg}）",
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
    "topic_progress": {
        "zh-CN": "📚 主题：{topic} · 已掌握 {done}/{total}（{pct}%）",
        "en": "📚 Topic: {topic} · {done}/{total} mastered ({pct}%)",
        "ja": "📚 トピック：{topic} · {done}/{total} 習得（{pct}%）",
    },
    "topic_next": {
        "zh-CN": "下一个：{name} →",
        "en": "Next: {name} →",
        "ja": "次：{name} →",
    },
    "learn_next": {"zh-CN": "接下来学", "en": "Up next", "ja": "次に学ぶ"},
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
    "analogy_title": {
        "zh-CN": "🧠 类比桥（用你熟悉的领域理解它）",
        "en": "🧠 Analogy Bridge (understand it via a domain you know)",
        "ja": "🧠 類比ブリッジ（知っている領域で理解）",
    },
    "topic_size": {"zh-CN": "{n} 个概念", "en": "{n} concepts", "ja": "{n} 概念"},
    "connected_title": {
        "zh-CN": "🔗 知识位置（它和什么有关）",
        "en": "🔗 Connected (where it sits)",
        "ja": "🔗 関連（どこにあるか）",
    },
    "topic_focus_hint": {
        "zh-CN": "点击在图谱中聚焦此主题",
        "en": "Click to focus this topic in the graph",
        "ja": "クリックでグラフにフォーカス",
    },
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
    "no_asset_placeholder": {
        "zh-CN": "请先导入知识资产",
        "en": "Import a knowledge asset first",
        "ja": "先に知識資産をインポートしてください",
    },
    "guide_title": {
        "zh-CN": "跟着这三步，开始学习新知识",
        "en": "Three steps to start learning something new",
        "ja": "この3ステップで新しい知識の学習を始めましょう",
    },
    "guide_step1_title": {
        "zh-CN": "导入一份学习资料",
        "en": "Import your study material",
        "ja": "学習資料をインポート",
    },
    "guide_step1_desc": {
        "zh-CN": "选择电脑里的 PDF / EPUB / Word / Markdown / TXT 文件，或直接把书摘、笔记、网页内容粘贴到下方",
        "en": "Pick a PDF / EPUB / Word / Markdown / TXT file, or paste excerpts, notes or web content below",
        "ja": "PDF / EPUB / Word / Markdown / TXT ファイルを選ぶか、抜粋・メモ・Web 内容を下に貼り付けます",
    },
    "guide_step2_title": {
        "zh-CN": "生成知识地图",
        "en": "Generate a knowledge map",
        "ja": "知識マップを生成",
    },
    "guide_step2_desc": {
        "zh-CN": "系统自动提取概念、梳理关系，构建出该知识的体系结构与推荐学习路径",
        "en": "Concepts and relations are extracted automatically into a structured map with a recommended path",
        "ja": "概念と関係を自動抽出し、体系的なマップと推奨学習パスを構築します",
    },
    "guide_step3_title": {
        "zh-CN": "从推荐概念开始学习",
        "en": "Start learning from a recommended concept",
        "ja": "推奨コンセプトから学習を開始",
    },
    "guide_step3_desc": {
        "zh-CN": "进入知识图谱，点击任意概念即可开始讲解、自测与复习，掌握度会逐步提升",
        "en": "Open the concept map and click any concept to teach, quiz and review — mastery grows step by step",
        "ja": "コンセプトマップで概念をクリックすれば、解説・自測・復習が始まり、習熟度が少しずつ上がります",
    },
    "guide_note": {
        "zh-CN": "第 2 步和第 3 步在导入完成后会自动进行，你只需要完成第 1 步。",
        "en": "Steps 2 and 3 run automatically after importing — you only need to do step 1.",
        "ja": "ステップ2と3はインポート後に自動で進みます。あなたはステップ1だけで大丈夫です。",
    },
    "map_empty_title": {
        "zh-CN": "还没有知识图谱",
        "en": "No knowledge map yet",
        "ja": "知識マップがまだありません",
    },
    "map_empty_desc": {
        "zh-CN": "导入第一份学习资料后，这里会自动生成概念图谱与推荐学习路径。",
        "en": "After importing your first material, a concept map and a recommended path will appear here.",
        "ja": "最初の資料をインポートすると、ここにコンセプトマップと推奨パスが表示されます。",
    },
    "map_empty_cta": {
        "zh-CN": "导入我的第一份资料",
        "en": "Import my first material",
        "ja": "最初の資料をインポート",
    },
    "import_status_ready": {
        "zh-CN": "已准备好，可以开始分析",
        "en": "Ready — start the analysis",
        "ja": "準備完了。分析を開始できます",
    },
    "import_status_wait": {
        "zh-CN": "请先选择文件或粘贴学习内容",
        "en": "Choose a file or paste content first",
        "ja": "先にファイルを選択するか内容を貼り付けてください",
    },
    "import_status_busy": {
        "zh-CN": "分析正在进行，请等待当前任务完成",
        "en": "Analysis in progress — please wait",
        "ja": "分析中です。しばらくお待ちください",
    },
    "import_status_file_chosen": {
        "zh-CN": "文件已选择，正在开始分析…",
        "en": "File chosen — starting the analysis…",
        "ja": "ファイルを選択しました。分析を開始します…",
    },
    "import_step_progress": {
        "zh-CN": "第 {cur} / 3 步：{msg}",
        "en": "Step {cur} of 3: {msg}",
        "ja": "ステップ {cur} / 3：{msg}",
    },
    "import_stage_parse": {
        "zh-CN": "正在解析资料并抽取知识…",
        "en": "Parsing the material and extracting knowledge…",
        "ja": "資料を解析して知識を抽出中…",
    },
    "import_stage_teacher": {
        "zh-CN": "正在构建教师模型并检查知识缺口…",
        "en": "Building the teacher model and checking gaps…",
        "ja": "教師モデルを構築し知識のギャップを確認中…",
    },
    "import_extracted_concepts": {
        "zh-CN": "已抽取 {n} 个概念，正在构建教师模型…",
        "en": "{n} concepts extracted — building the teacher model…",
        "ja": "{n} 個の概念を抽出しました。教師モデルを構築中…",
    },
    "import_done": {
        "zh-CN": "分析完成。接下来可在知识地图中选择推荐概念开始学习。",
        "en": "Analysis complete. Pick a recommended concept on the map to start learning.",
        "ja": "分析が完了しました。マップの推奨コンセプトから学習を始めましょう。",
    },
    "import_failed_state": {
        "zh-CN": "分析失败：{msg}。输入内容已保留，可直接重试。",
        "en": "Analysis failed: {msg}. Your input is kept — you can retry.",
        "ja": "分析に失敗しました：{msg}。入力は保持されています。再試行できます。",
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
