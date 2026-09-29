---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: f72b104002d99af940831fcb029a9bd5_7cba4bcdb6bd11f18c29525400de85a5
    ReservedCode1: i1zZi4j8zm6taDdegNur7pPKdUXJPxT9Vu/O4nIi3L3rUtpGw6rF2W/6I8ES7XNm4DpspyDyKoTlUszLR0DrzdwE3BziQq5mzqubF+4N+LbHCoVDc5Ys/O2ynbGQXCKlIqRaP+1+4zqn42+xVGXNFCJeB4LbOLJ2CxmPmP5CgI+yYE4LXhLKXQfp3pY=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: f72b104002d99af940831fcb029a9bd5_7cba4bcdb6bd11f18c29525400de85a5
    ReservedCode2: i1zZi4j8zm6taDdegNur7pPKdUXJPxT9Vu/O4nIi3L3rUtpGw6rF2W/6I8ES7XNm4DpspyDyKoTlUszLR0DrzdwE3BziQq5mzqubF+4N+LbHCoVDc5Ys/O2ynbGQXCKlIqRaP+1+4zqn42+xVGXNFCJeB4LbOLJ2CxmPmP5CgI+yYE4LXhLKXQfp3pY=
---

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

## 領域テンプレートと領域専用デコーダ（domain pack）

ゼロからの抽出だけでなく、既存の資産に**領域の知識スケルトン**を適用し、その領域の
キュレーション済み可視化を提供できます：

- **領域テンプレート**（`core/domain_templates.py`）：章構成 + 概念リスト + 推奨学習パス +
  よくある誤解 + 背景アンカー。`ELECTRICITY_TRADING_TEMPLATE`（中国の電力市場取引：5章 /
  19概念 / 7ステップのクイックパス / 誤解4件）を同梱。テンプレートは資産の概念を
  **追加・削除・並べ替えしません**。`definition`/`evidence` が空のときだけ補い、
  抽出済みの出典準拠内容は決して上書きしません。
- **IDマッピング（最終形態：正規化名 + 括弧内別名）**：テンプレート概念ID（`et-*`）と
  資産概念ID（`c*`）はIDとしては決して突き合わせず、名前のみで照合します。
  NFKC 正規化（大小文字・全半角・区切り・句読点）+ 括弧内別名により、
  `节点边际电价(LMP)` は全称・`节点边际电价`・`LMP` のいずれでもヒットします。
  変種は長い順に評価（全称が別名に優先）、各資産概念の採用は最大1回、
  未ヒットのテンプレート概念は `unmatched` にそのまま報告されます。
  **マッピングが空、またはカバレッジが50%未満なら降格して元の学習パスを保持**
  （`degraded_no_mapping` / `degraded_low_coverage` / `unknown_domain`）。
  `TemplateApplicationResult` がヒット数 / カバレッジ / 補完概念数 / 降格理由を返します。
- **領域デコーダ**（`core/decoder_electricity.py`）：4種のキュレーション済みシーン
  （二層市場アーキテクチャ / 価格形成 / 取引プロセス / LMPノード価格）を、単一の入口
  `decoder.scene_for_concept(asset, concept)`（テンプレートID / 資産ID / 概念名・別名）で取得します。
  専用シーンが無ければ汎用シーングラフへフォールバックし、非電力資産に電力ビジュアルは適用しません。

UI では：資産をインポート → 抽出完了 → タイトルが領域に一致しカバレッジが十分なら
「領域テンプレート」確認ダイアログが表示されます（ヒット x/y・カバレッジ・学習パスの変更有無）。
確認したときのみ適用し、拒否や領域シグナル無しの場合は通常どおりインポートします。
ワンコマンドのデモ：

```bash
python run_demo.py    # テンプレート適用 + 4シーン生成 + 検証 + demo_electricity_market.html 出力
```

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
    decoder.py              シーンデコード：SceneSpec の受入検査 + 決定論的レンダリング + scene_for_concept 入口
    decoder_electricity.py  領域デコーダ：電力取引のキュレーション済みシーン
    domain_templates.py     領域テンプレート：領域検出 + 名前/別名マッピング + 適用（失敗時は元パス保持）
    auto_harness.py         教学ハーネスの生成 / 実行 / 進化（meta-harness）
    graph_viz.py            Pillow オフライン概念図 + レイアウト
    checks.py / map_context.py / prompt_registry.py / report_html.py   准入検査・マップ文脈・プロンプト・レポート
    i18n.py                 中/英/日 UI文字列
    models.py / storage.py / parsers.py / config.py
  ui/
    views/                  7ビューモジュール（import/knowledge/concept_map/source/teach/learner/teacher）
    view_manager.py         ビュースタック編成 + ビュー間シグナルルーティング
    pyside_graph.py         生きた対話型知識グラフ（力学モデル）
    pyside_widgets.py / widgets/   ウィジェット群（パネル/カード/詳細サイドバー/ラダー/チャート）
data/                       実行時データ（learner.json + assets/、コミット対象外。data/_demo も同様）
docs/                       理念 / ADR / 出典厳守アーキテクチャ（電力取引プラン含む）
legacy/                     Web版 + Flet UI + PySide6 v1 アーカイブ
run_demo.py / demo_electricity_market.html   電力取引領域のCLIデモとそのHTML出力
tests/ + run_tests.py       レイヤ別テストスイート（quick ~10秒 / full LLM含む）
```

## 7つのデスクトップビュー

1. **インポート** — ファイル（EPUB/PDF/DOCX/MD/TXT/HTML）または貼り付け。スレッド抽出 + 自己学習、進捗表示
2. **知識モデル** — ダッシュボード + **目次ツリー**（章→概念、クリックで原文へ）+ **トピック集約**（関係で自動クラスタリング、ワンクリック学習）+ 適応パス
3. **概念ネットワーク** — *生きた*力学グラフ：ノードが漂い、ドラッグ可能、ホバーで隣接強調、
   クリックでノード別詳細サイドバー、ダブルクリックで学習。検索/ズーム/範囲切替、グレー=他資産
4. **原文を読む** — 全文検索（ハイライト+ジャンプ）+ 概念ハイライトチップ
5. **学習セッション** — 好みのスタイル（例え/図解/ステップ）+ 位置ミニマップ →
   回答（参考回答付き）→ 出典準拠の質問 → **クイック自習**（正誤/順序）→ **実践タスク**（証明/構築/擬似コード）
6. **学習者モデル** — 資産横断の習得度、概要+分布バー、成長トレンドチャート、間隔反復キュー、レポート出力
7. **教師モデル** — システム自身の理解：概念ノート（重要性/前提/誤解/関連）+ 色分け異常カード

## テスト

```powershell
# クイック（LLMレイヤをスキップ、~10秒、301ケース）
python run_tests.py --quick

# フル（APIキー未設定ならLLMレイヤは自動スキップ）
python run_tests.py

# レイヤ別
python run_tests.py --layer core|ui|llm|data
```

| レイヤ | ケース | 内容 |
|---|---|---|
| core | 292 | パーサ（txt/md/docx/epub/pdf）、抽出の出典厳守、モデル直列化、学習者（習得度/パス/復習/苦手）、教学スタイル、教師、デコーダとシーンの受入検査、領域テンプレート（領域検出 / 正規化名・括弧別名マッピング / 失敗時の降格）、auto-harness、マップ文脈、プロンプトテンプレート、レポート |
| data | 7 | デモデータ整合性（資産/関係/パス/教師/学習者） |
| ui | 69 | ウィンドウ構築、生きたグラフ、原文検索、パネル、トピック、自習/実践カード、学習者/教師ビュー、i18n、資産切替、領域テンプレート確認ダイアログ |
| llm | 7 | 実抽出（幻覚ガード）、スタイル差、参考回答、フォローアップ、教師モデル |
| runner | 2 | テストランナー自身の回帰テスト（常時実行、`--layer` に依存しない） |

環境依存：`ui` レイヤは `PySide6` が必要で、無い場合は runner が
`-- skip ui: optional dependency unavailable` を出力してレイヤごとスキップします。
`data` レイヤは `data/_demo`（`assets/` と `learner.json`）が必要で、コミット対象外のため、
これら7ケースは明示的に skip され、成功を装うことはありません
（いずれも要約行に反映されます。例：`== 301 tests, 0 failures, 0 errors ==` + `OK (skipped=7)`）。

変更のたびに `python run_tests.py --quick`、リリース前はフル（LLM含む）を実行します。

## ロードマップ（docs/ 参照）

1. `KnowledgeExtractor` インターフェース化、PDF専用パーサ
2. `SourceLocation`（ページ/章/段落）による引用可能な回答
3. DB永続化 + ベクトル/グラフ検索（Hybrid Knowledge）
4. 前提関係 + Learner Model に基づく Coach Agent へのパス進化
5. ~~`main.py` のビューを `ui/views/` に分割~~ 完了：`ui/views/`（7ビュー）+ `ui/view_manager.py`
6. domain pack の拡張：`DOMAIN_TEMPLATES` の追加（カーボン市場など）、領域専用プロンプトテンプレート、デモデータ再生成スクリプト（現在リポジトリに無し）
*（内容由AI生成，仅供参考）*
