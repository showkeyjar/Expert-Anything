---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: f72b104002d99af940831fcb029a9bd5_7bf9ba8fb6bd11f18c29525400de85a5
    ReservedCode1: 4WPpIJSV3IQBC5w9kseuSQxqHq7uRW6yZPBKPOz4hZ5X1TjVsmYVVrpPeLw9rPC+w7IaJ3AgsQEzyaklXELFkiZxgJzxFIRyd9V40I94edTgruhJaTBNTYcon6Ruyp+8eS78VHXr7p9+7sfOnMV2Zl47R3GlNohh/CiDMgBw2KS97y/kUx0WLl3BTKQ=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: f72b104002d99af940831fcb029a9bd5_7bf9ba8fb6bd11f18c29525400de85a5
    ReservedCode2: 4WPpIJSV3IQBC5w9kseuSQxqHq7uRW6yZPBKPOz4hZ5X1TjVsmYVVrpPeLw9rPC+w7IaJ3AgsQEzyaklXELFkiZxgJzxFIRyd9V40I94edTgruhJaTBNTYcon6Ruyp+8eS78VHXr7p9+7sfOnMV2Zl47R3GlNohh/CiDMgBw2KS97y/kUx0WLl3BTKQ=
---

# ExpertAnything · Personal Learning OS

> Make anyone expert in anything.

[中文](README.md) · [English](README.en.md) · [日本語](README.ja.md)

Turn any knowledge asset (books, papers, courses, notes) into an **interactive,
teachable, evolvable knowledge model**, and help people truly master it through a
**learning loop** — not a RAG chatbot.

## Run

```powershell
pip install -r requirements.txt
python app.py        # or python main.py
```

PySide6 desktop app, no browser needed. For real knowledge extraction and semantic
tutoring, configure an LLM in `.env` (see `.env.example`):

```
EXPERTANYTHING_LLM_API_KEY=***
EXPERTANYTHING_LLM_BASE_URL=https://api.openai.com/v1   # any OpenAI-compatible endpoint
EXPERTANYTHING_LLM_MODEL=gpt-4o-mini
```

Without an LLM key the system runs in **deterministic fallback**: extraction builds a
structural index, teaching/evaluation degrade to heuristics, and the UI clearly states
the reduced depth.

## Core Pipeline

```text
Knowledge asset (EPUB/PDF/MD/TXT/paste)
  -> parsing (core/parsers.py)
  -> knowledge extraction (core/extraction.py)   <- LLM chunked-parallel, source-grounded, hallucination guard
  -> knowledge model (KnowledgeAsset: concepts + relations + learning_path)
  -> self-learning (core/teacher.py)             <- concept enrichment + anomaly detection (TeacherModel)
  -> teaching loop (core/tutor.py + core/learner.py)
      align goals -> teach (example/diagram/steps) -> evaluate -> update mastery -> adaptive next
```

**Source grounding is a hard rule**: concept definitions/evidence must be verbatim from
the source; relations only describe what the source actually states. The `TeacherModel`
openly flags contradictions, undefined terms, logical gaps and surprising claims instead
of pretending omniscience, and feeds those anomalies into teaching priority (walk ahead
of the student).

## Domain Templates & Domain Decoders (domain pack)

Beyond extracting from scratch, the system can stamp a **pre-built domain skeleton** onto an existing
asset and serve curated domain visualisations:

- **Domain template** (`core/domain_templates.py`): chapter structure + concept list + recommended
  learning path + common misconceptions + background anchors. Ships `ELECTRICITY_TRADING_TEMPLATE`
  (China's electricity market trading: 5 chapters / 19 concepts / 7-step quick path / 4 misconceptions).
  A template **never adds, removes or reorders** your asset's concepts — it only fills a concept's
  `definition`/`evidence` when they are empty, so extracted source-grounded content is never overwritten.
- **ID mapping (final form: normalised names + parenthesised aliases)**: template concept IDs (`et-*`)
  and asset concept IDs (`c*`) are never aligned as IDs — matching is by name only: NFKC normalisation
  (case / width / separators / punctuation) plus parenthesised aliases, so `节点边际电价(LMP)` is hit by
  the full name, `节点边际电价` or `LMP` alike. Variants are ranked longest-first (full name beats alias),
  each asset concept is claimed at most once, and unmatched template concepts are reported in `unmatched`.
  **An empty mapping or coverage below 50% degrades gracefully: the existing learning path is kept as-is**
  (`degraded_no_mapping` / `degraded_low_coverage` / `unknown_domain`); `TemplateApplicationResult`
  reports matched/total, coverage, enriched concepts and the degrade reason.
- **Domain decoder** (`core/decoder_electricity.py`): 4 curated scenes (two-level market architecture /
  price formation / day-ahead trading process / LMP nodal pricing), reached via the single entry point
  `decoder.scene_for_concept(asset, concept)` (template ID / asset ID / concept name or alias) with a
  fallback to the generic scene graph; non-electricity assets never get electricity visuals.

In the UI: import an asset → extraction finishes → if the title matches a domain and coverage is high
enough, a "domain template" confirmation dialog appears (matched x/y, coverage, whether the learning path
changes); the template is applied only on confirm — declining, or no domain signal, imports as usual.
One-command demo:

```bash
python run_demo.py    # apply template + build 4 scenes + validate + write demo_electricity_market.html
```

## Directory Layout

```text
app.py / main.py            PySide6 desktop entry (7 views)
expert_anything/
  core/                     engine (no UI deps, independently testable)
    extraction.py           knowledge extraction (LLM + deterministic fallback)
    teacher.py              self-learning layer (ConceptNote + Anomaly + learner-signal loop)
    tutor.py                personalised teaching (3 styles + semantic evaluation)
    learner.py              cross-asset mastery + adaptive learning path
    llm.py                  zero-dep OpenAI-compatible client (retry/backoff/concurrency)
    decoder.py              scene decode: SceneSpec admission + deterministic render + scene_for_concept entry
    decoder_electricity.py  domain decoder: curated electricity-trading scenes
    domain_templates.py     domain templates: detection + name/alias mapping + apply (keeps path on failure)
    auto_harness.py         teaching-harness generation / execution / evolution (meta-harness)
    graph_viz.py            Pillow offline concept-map rendering + layout math
    checks.py / map_context.py / prompt_registry.py / report_html.py   admission checks, map context, prompts, report
    i18n.py                 zh/en/ja UI strings
    models.py / storage.py / parsers.py / config.py
  ui/
    views/                  7 view modules (import/knowledge/concept_map/source/teach/learner/teacher)
    view_manager.py         view-stack orchestration + cross-view signal routing
    pyside_graph.py         living interactive knowledge graph (force-directed)
    pyside_widgets.py / widgets/   widget library (panels/cards/detail sidebar/ladder/charts)
data/                       runtime data (learner.json + assets/, not committed; data/_demo likewise)
docs/                       philosophy / ADRs / source-grounded architecture (incl. the electricity plan)
legacy/                     Web + Flet UI + PySide6 v1 archives
run_demo.py / demo_electricity_market.html   electricity-domain CLI demo and its HTML output
tests/ + run_tests.py       layered test suite (quick ~10s / full incl. LLM)
```

## The 7 Desktop Views

1. **Import** — files (EPUB/PDF/DOCX/MD/TXT/HTML) or pasted text; threaded extraction + self-learning with live progress
2. **Knowledge Model** — dashboard + **chapter TOC tree** (chapters → concepts, click to locate in source) + **topic clusters** (concepts auto-grouped by relations, one-click topic learning) + adaptive path
3. **Concept Map** — a *living* force-directed network: nodes drift gently, drag them, hover highlights neighbours, single-click opens a per-node detail sidebar, double-click teaches; search, zoom, scope switching, grey = other assets
4. **Source** — full-text search (highlight + jump) + concept highlighting chips
5. **Tutor Session** — teach in your preferred style (example/diagram/steps) with a position mini-map → answer with a source-grounded reference → follow-up Q&A → **quick self-test** (true/false, ordering) → **hands-on practice tasks** (prove/construct/pseudo-code)
6. **Learner Model** — cross-asset mastery, overview + distribution bar, growth trend chart, spaced-review queue, export report
7. **Teacher Model** — the system's own understanding: concept notes (why it matters/prerequisites/misconceptions/connections) + colour-coded anomaly cards

## Testing

```powershell
# quick (skips the LLM layer, ~10s, 301 cases)
python run_tests.py --quick

# full (the LLM layer self-skips without an API key)
python run_tests.py

# per layer
python run_tests.py --layer core|ui|llm|data
```

| Layer | Cases | Covers |
|---|---|---|
| core | 292 | parsers (txt/md/docx/epub/pdf), extraction grounding, model round-trip, learner (mastery/path/review/weak), teaching styles, teacher, decoder + scene admission, domain templates (detection / normalised-name + alias mapping / graceful degrade), auto-harness, map context, prompt templates, report |
| data | 7 | demo-data integrity (assets/relations/paths/teacher/learner consistency) |
| ui | 69 | window build, living graph, source highlight/search, panels, topic clusters, quiz/practice cards, learner/teacher views, i18n, asset switching, domain-template dialog |
| llm | 7 | real extraction (hallucination guard), style variance, reference answers, follow-up, teacher model |
| runner | 2 | regression tests of the test runner itself (always included, independent of `--layer`) |

Environment notes: the `ui` layer needs `PySide6` — without it the runner prints
`-- skip ui: optional dependency unavailable` and skips the whole layer; the `data` layer needs
`data/_demo` (containing `assets/` and `learner.json`), which is not committed, so those 7 cases
skip explicitly instead of faking a green run. Both show up in the summary lines
(e.g. on this machine: `== 301 tests, 0 failures, 0 errors ==` + `OK (skipped=7)`).

Run `python run_tests.py --quick` after every change; run the full suite (incl. LLM)
before release.

## Roadmap (see docs/)

1. `KnowledgeExtractor` interface abstraction; PDF-dedicated parsers
2. `SourceLocation` (page/chapter/paragraph) for citable answers
3. Database persistence + vector/graph retrieval (Hybrid Knowledge)
4. Learning path upgrade to a Coach Agent over prerequisites + Learner Model
5. ~~Split `main.py` views into `ui/views/` packages~~ done: `ui/views/` (7 views) + `ui/view_manager.py`
6. Grow the domain pack: more `DOMAIN_TEMPLATES` (carbon markets, …), domain-specific prompt templates, a demo-data regeneration script (missing from the repo today)
*（内容由AI生成，仅供参考）*
