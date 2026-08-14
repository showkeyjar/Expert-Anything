# ExpertAnything · パーソナル学習OS

> Make anyone expert in anything.

[中文](README.md) · [English](README.en.md) · [日本語](README.ja.md)

あらゆる知識資産（本・論文・コース・メモ）を**対話型・教育可能・進化する知識モデル**へ変換し、
「学習ループ」を通じて本当の習得を支援します。RAGチャットボットではありません。

## 起動方法

```powershell
pip install -r requirements.txt
python app.py        # または python main.py
```

PySide6 デスクトップアプリ（ブラウザ不要）。本格的な知識抽出と対話型チュータリングには
`.env` に LLM を設定してください（`.env.example` 参照）：

```
EXPERTANYTHING_LLM_API_KEY=***
EXPERTANYTHING_LLM_BASE_URL=https://api.openai.com/v1   # OpenAI互換エンドポイント
EXPERTANYTHING_LLM_MODEL=gpt-4o-mini
```

LLMキー未設定時は**決定論的フォールバック**で動作します（構造インデックスの抽出、
ヒューリスティックな教学・評価。UIに深度制限を明示）。

## コアパイプライン

```text
知識資産 (EPUB/PDF/MD/TXT/貼り付け)
  -> パース (core/parsers.py)
  -> 知識抽出 (core/extraction.py)   <- LLM並列チャンク・出典厳守・幻覚ガード
  -> 知識モデル (KnowledgeAsset: concepts + relations + learning_path)
  -> 自己学習 (core/teacher.py)      <- 概念の深掘り + 異常検出 (TeacherModel)
  -> 学習ループ (core/tutor.py + core/learner.py)
      目標合わせ → 教学(例え/図解/ステップ) → 評価 → 習得度更新 → 適応的な次へ
```

**出典厳守はハードルール**：概念の定義・根拠は原文から逐語的に取ります。関係は原文が
実際に述べているものだけ。TeacherModelは矛盾・未定義用語・論理の飛躍・意外な主張を
「疑義」として明示し、教学優先度に反映します（walk ahead of the student）。

## ディレクトリ構成

```text
app.py / main.py            PySide6 デスクトップ入口（7ビュー）
expert_anything/
  core/                     エンジン（UI非依存、単体テスト可）
    extraction.py           知識抽出（LLM + 決定論的フォールバック）
    teacher.py              自己学習層（ConceptNote + Anomaly + 学習者シグナルループ）
    tutor.py                個別教学（3スタイル + 意味評価）
    learner.py              資産横断の習得度 + 適応学習パス
    llm.py                  ゼロ依存 OpenAI互換クライアント
    graph_viz.py            Pillow オフライン概念図 + レイアウト
    i18n.py                 中/英/日 UI文字列
    models.py / storage.py / parsers.py / config.py
  ui/
    pyside_graph.py         生きた対話型知識グラフ（力学モデル）
    pyside_widgets.py       ウィジェット群（パネル/カード/詳細サイドバー/ラダー/チャート）
data/                       実行時データ（learner.json + assets/、コミット対象外）
docs/                       理念 / ADR / 出典厳守アーキテクチャ / 開発メモ
legacy/                     Web版 + Flet UI + PySide6 v1 アーカイブ
tests/ + run_tests.py       レイヤ別テストスイート（quick ~9秒 / full LLM含む）
```

## 7つのデスクトップビュー

1. **インポート** — ファイル（EPUB/PDF/DOCX/MD/TXT/HTML）または貼り付け。スレッド抽出 + 自己学習、進捗表示
2. **知識モデル** — ダッシュボード + 適応パス（習得度/疑義/レバレッジ/位置の4シグナル）
3. **概念ネットワーク** — *生きた*力学グラフ：ノードが漂い、ドラッグ可能、ホバーで隣接強調、
   クリックでノード別詳細サイドバー、ダブルクリックで学習。検索/ズーム/範囲切替、グレー=他資産
4. **原文を読む** — 概念ハイライト + ジャンプチップ付き原文表示
5. **学習セッション** — 目標合わせ → 好みのスタイル（例え/図解/ステップ）で教学 →
   回答 → 出典に基づく参考回答付き意味評価 → 出典に基づく質問（フォローアップ）
6. **学習者モデル** — 資産横断の習得度、概要+分布バー、成長トレンドチャート、間隔反復キュー、レポート出力
7. **教師モデル** — システム自身の理解：概念ノート（重要性/前提/誤解/関連）+ 色分け異常カード

## テスト

```powershell
# クイック（LLMなし、~9秒、71ケース）
python run_tests.py --quick

# フル（実LLMのE2E含む、~90秒）
python run_tests.py

# レイヤ別
python run_tests.py --layer core|ui|llm|data
```

| レイヤ | ケース | 内容 |
|---|---|---|
| core | 30 | パーサ（txt/md/docx/epub/pdf）、抽出の出典厳守、モデル直列化、学習者（習得度/パス/復習/苦手）、教学スタイル、教師 |
| data | 7 | デモデータ整合性（資産/関係/パス/教師/学習者） |
| ui | 27 | ウィンドウ構築、生きたグラフ、原文ハイライト、パネル、学習者/教師ビュー、不正データ、i18n切替 |
| llm | 7 | 実抽出（幻覚ガード）、スタイル差、参考回答、フォローアップ、教師モデル |

変更のたびに `python run_tests.py --quick`、リリース前はフル（LLM含む）を実行します。

## ロードマップ（docs/ 参照）

1. `KnowledgeExtractor` インターフェース化、PDF専用パーサ
2. `SourceLocation`（ページ/章/段落）による引用可能な回答
3. DB永続化 + ベクトル/グラフ検索（Hybrid Knowledge）
4. 前提関係 + Learner Model に基づく Coach Agent へのパス進化
5. `main.py` のビューを `ui/views/` に分割
