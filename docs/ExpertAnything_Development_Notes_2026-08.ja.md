# ExpertAnything 開発メモ（2026-08）

> 2026年8月のMVPから現在の安定基盤までの反復履歴・アーキテクチャ決定・開発規約。
> 目的：新規参画者（AI協作者含む）の迅速なオンボーディング。

## 1. 反復タイムライン

| フェーズ | 内容 |
|---|---|
| 基盤 | Flet Webプロトタイプ + 決定論的ルールエンジン（core層） |
| R1 | PySide6移行：入口統一（`python app.py`）、`get_asset()` クラッシュ修正、グラフ強化、requirements、README、初コミット |
| R2 | 可視化ライブラリ：原文ハイライトリーダー（SourceTextView）、概念パネル（ConceptDetailPanel）、パスラダー（PathLadderView）、ダッシュボード生グラフ |
| R3 | 構造化レッスンカード（TeachResultView）、履歴テーブル、Flet UIを legacy/ へ |
| R4 | 理解ファースト三本柱：教学位置ミニグラフ、間隔反復キュー（due_for_review）、参考回答比較（reference+gap） |
| R5 | 出典準拠のフォローアップQA（tutor.follow_up + FollowUpWorker）、復習モード（vary=1） |
| R6 | 関連概念ナビ（隣接チップ）、質問をTeacherModelへ沈殿（record_learner_question） |
| R7 | 学習ゲイン可視化：指標カード + 成長トレンドチャート（TrendChartView） |
| R8 | クラッシュ修正（ビュー再構築の参照順）+ バイナリインポート（pdf/epub/docx、ExtractWorkerバイト化）+ ファイルフィルタ |
| R9 | 三ゾーン配置（上部機能バー + 統一ヘッダ）、グローバルマップ（grey_ids + 共有概念エッジ）、クリックでパネル、プログレスバー廃止、教師説明カード |
| R10 | マップツールバー（検索/範囲/ズーム）、教師ノート補完エッジ（前置/関連、関係8→37）、概念ノートのリスト化 |
| R11 | **生きた力学グラフ**：物理シミュレーション + 浮遊 + ドラッグ + ホバー強調、スリム教学ヘッダ |
| R12 | コンテンツフィットズーム（≥0.85）、ノードラベル拡大、定義ツールチップ、ズームボタン |
| R13 | 教学レイアウト修正（グラフsizeHintがレッスン領域を圧迫 → maxHeight、スプリッターstretch） |
| R14 | **多言語**：zh/en/ja を `t()` で全面適用、ライブ言語切替、ハードコード中国語166箇所をゼロへ |
| テスト | 統合スイート `run_tests.py`：71ケース（core 30 / data 7 / ui 27 / llm 7）、quick ~9秒 |

## 2. 現在のアーキテクチャ（安定基盤）

```text
main.py                    PySide6入口 + 7ビュー + トップバー/サイドバー
expert_anything/
  core/                    UI非依存
    extraction.py          抽出（LLM並列チャンク + 幻覚ガード + ノイズフィルタ）
    teacher.py             教師モデル（ConceptNote + Anomaly + 学習者シグナルループ）
    tutor.py               教学（3スタイル / 評価 reference+gap / フォローアップ）
    learner.py             資産横断習得度 + adaptive_path + due_for_review
    llm.py                 ゼロ依存 OpenAI互換クライアント
    graph_viz.py           レイアウト + PNG描画（力学初期散布）
    i18n.py                3言語キーテーブル + t()/set_lang/save_lang
    parsers.py             txt/md/docx/epub/pdf/html 抽出
    models.py/storage.py/config.py
  ui/
    pyside_graph.py        生きたグラフ（浮遊/ドラッグ/ホバー/ズーム/グレーノード）
    pyside_widgets.py      ウィジェット群（パネル/カード/サイドバー/ラダー/トレンド/分布）
tests/                     unittest レイヤ（util がデモデータのコピーを隔離）
run_tests.py               ワンコマンド入口（--quick / --llm / --layer）
data/_demo                 デモデータ（2資産 + 模擬学習、再生成可）
legacy/                    Web + Flet UI + PySide6 v1 アーカイブ
```

## 3. 主要エンジニアリング決定（ADR補足）

- **出典厳守**：概念・根拠は原文から逐語。`_ground_evidence` 検証、幻覚概念は破棄。
  関係が疎な場合、学習パスの「経路隣接」エッジを補完しグラフに骨格を保証。
- **教師ノート補完エッジ**：prerequisites → 「前置」エッジ、connections が概念に一致 →
  「関連」エッジ。グラフ密度 8→37 関係。
- **力学モデルの初期レイアウトは円形散布**：層状レイアウトは4600pxの縦長帯を生成し
  どのズームでも読めなかった。コンパクトな散布は即読め、物理が自然なネットワークへ展開。
- **QGraphicsView の sizeHint 罠**：sizeHint がシーンキャンバス由来（1000px超になり得る）。
  QVBoxLayout 内では `setMaximumHeight` 必須。でないと主コンテンツ領域を圧迫。
- **ビュー再構築ライフサイクル**：`_rebuild_all_views` は古い参照を*再構築前*にクリア。
  言語切替はトップバー+サイドバー+全ビューを再構築。
- **i18n モジュール評価の罠**：`TAG_LABELS = {"weak": _t(...)}` はインポート時に言語が
  固定される。レンダリング時参照関数（`_tag_label()`）を使う。

## 4. i18n 規約

- 全UIテキストは `core/i18n.py` の `t(key)` 経由。キーテーブルは3言語（zh-CN/en/ja）。
- 学習教材（概念名・根拠）は翻訳しない。LLM生成の異常テキストは生成言語のまま。
- 言語ドロップダウンは言語自称（中文/English/日本語）を表示。
- 新規UI文言：キー追加 → 3言語翻訳 → 呼び出し置換。静的スキャン + ENモード動的スキャンで
  残存ゼロを検証。
- LLMプロンプトの言語追従（UI言語に応じた抽出・教学出力）は次ステップ。

## 5. 既知の制限と次のステップ

1. LLM出力は中国語固定（プロンプトが言語非対応）→ 次：言語別プロンプトテンプレート
2. `SourceLocation` なし：根拠アンカーはテキスト一致のみ、ページ/章IDなし
3. `main.py` 約2100行のモノリス → `ui/views/` 分割待ち
4. スキャンPDFはOCRなし；docx は本文段落のみ
5. JSONファイル永続化、DB未導入
6. 学習レポートはプレーンテキスト、HTML可視化版は今後

## 6. テストワークフロー

```powershell
python run_tests.py --quick   # 71ケース（LLMなし）約9秒 — 変更のたびに実行
python run_tests.py           # フル（実LLM E2E）
python run_tests.py --layer ui|core|llm|data
```

規約：テストは `data/_demo` の一時コピーを使用（tests/util.ensure_demo）。
実データには触れない。LLMケースはキーなしで自動スキップ。
