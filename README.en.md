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
    graph_viz.py            Pillow offline concept-map rendering + layout math
    i18n.py                 zh/en/ja UI strings
    models.py / storage.py / parsers.py / config.py
  ui/
    pyside_graph.py         living interactive knowledge graph (force-directed)
    pyside_widgets.py       widget library (panels/cards/detail sidebar/ladder/charts)
data/                       runtime data (learner.json + assets/, not committed)
docs/                       philosophy / ADRs / source-grounded architecture / dev notes
legacy/                     Web + Flet UI + PySide6 v1 archives
tests/ + run_tests.py       layered test suite (quick ~9s / full incl. LLM)
```

## The 7 Desktop Views

1. **Import** — files (EPUB/PDF/DOCX/MD/TXT/HTML) or pasted text; threaded extraction + self-learning with live progress
2. **Knowledge Model** — dashboard + adaptive path (mastery/anomaly/leverage/position four-signal ranking)
3. **Concept Map** — a *living* force-directed network: nodes drift gently, drag them, hover highlights neighbours, single-click opens a per-node detail sidebar, double-click teaches; search, zoom, scope switching, grey = other assets
4. **Source** — read the original material with concept highlighting & jump chips
5. **Tutor Session** — align goals → teach in your preferred style (example/diagram/steps) → answer → semantic evaluation with a source-grounded reference answer → follow-up Q&A grounded in the source
6. **Learner Model** — cross-asset mastery, overview + distribution bar, growth trend chart, spaced-review queue, export report
7. **Teacher Model** — the system's own understanding: concept notes (why it matters/prerequisites/misconceptions/connections) + colour-coded anomaly cards

## Testing

```powershell
# quick (no LLM, ~9s, 71 cases)
python run_tests.py --quick

# full (incl. real-LLM end-to-end, ~90s)
python run_tests.py

# per layer
python run_tests.py --layer core|ui|llm|data
```

| Layer | Cases | Covers |
|---|---|---|
| core | 30 | parsers (txt/md/docx/epub/pdf), extraction grounding, model round-trip, learner (mastery/path/review/weak), teaching styles, teacher |
| data | 7 | demo-data integrity (assets/relations/paths/teacher/learner consistency) |
| ui | 27 | window build, living graph, source highlight, panels, learner/teacher views, dirty payloads, i18n switching |
| llm | 7 | real extraction (hallucination guard), style variance, reference answers, follow-up, teacher model |

Run `python run_tests.py --quick` after every change; run the full suite (incl. LLM)
before release.

## Roadmap (see docs/)

1. `KnowledgeExtractor` interface abstraction; PDF-dedicated parsers
2. `SourceLocation` (page/chapter/paragraph) for citable answers
3. Database persistence + vector/graph retrieval (Hybrid Knowledge)
4. Learning path upgrade to a Coach Agent over prerequisites + Learner Model
5. Split `main.py` views into `ui/views/` packages
