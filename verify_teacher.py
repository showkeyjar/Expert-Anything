"""Headless check of the self-learning layer (Teacher Model).

Exercises: fallback (no LLM), and the LLM path with a fake client that
returns a fenced JSON response (to prove _parse_json is robust).
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
import sys
sys.path.insert(0, ".")

from expert_anything.core import config
from expert_anything.core.models import KnowledgeAsset, Concept
from expert_anything.core.extraction import extract_knowledge
from expert_anything.core.teacher import (
    build_teacher_model,
    TeacherModel,
    incorporate_learner_signal,
    anomaly_prioritized_path,
    anomaly_concept_ids,
)


class FakeLLM:
    def __init__(self, payload: str):
        self.payload = payload

    def chat(self, messages, temperature=0.3, json_mode=False, max_tokens=2000):
        return self.payload


def make_asset():
    c1 = Concept(id="c1", name="梯度下降", definition="一种优化方法", evidence=["梯度下降用于最小化损失"])
    c2 = Concept(id="c2", name="学习率", definition="步长超参", evidence=["学习率控制更新幅度"])
    return KnowledgeAsset(
        asset_id="a1", type="md", title="ML 笔记", source_name="note.md",
        created_at="2026-08-13T00:00:00+00:00",
        source_text="梯度下降用于最小化损失。学习率控制更新幅度。但文中又写学习率越大收敛越快，这与常识矛盾。",
        concepts=[c1, c2], relations=[], learning_path=["c1", "c2"],
    )


print("=== 1) fallback (no LLM) ===")
a = make_asset()
tm = build_teacher_model(a, None)
assert tm.status == "fallback", tm.status
assert len(tm.anomalies) == 1 and tm.anomalies[0].kind == "needs_llm"
print("ok: fallback status=%s, anomalies=%d" % (tm.status, len(tm.anomalies)))

print("=== 2) LLM path with fenced JSON (proves robust parse) ===")
fenced = '''```json
{
  "concept_notes": [
    {"name":"梯度下降","significance":"优化的核心","prerequisites":["微积分"],"misconceptions":["以为是随机"],"connections":["损失函数"],"external_notes":["外部：来自经典优化理论"],"note":"沿负梯度更新参数。"},
    {"name":"学习率","significance":"影响收敛","prerequisites":[],"misconceptions":[],"connections":["梯度下降"],"external_notes":[],"note":"步长。"}
  ],
  "anomalies": [
    {"kind":"contradiction","description":"文中称学习率越大收敛越快，与优化理论矛盾","location":"第二段","severity":"high"}
  ]
}
```'''
tm2 = build_teacher_model(a, FakeLLM(fenced))
assert tm2.status == "done", tm2.status
assert len(tm2.concept_notes) == 2, len(tm2.concept_notes)
assert tm2.concept_note_by_id("c1").external_notes, "external note lost"
assert len(tm2.anomalies) == 1 and tm2.anomalies[0].kind == "contradiction"
assert tm2.anomalies[0].status == "open"
print("ok: LLM path status=%s, notes=%d, anomalies=%d, external_labeled=%s" % (
    tm2.status, len(tm2.concept_notes), len(tm2.anomalies),
    bool(tm2.concept_note_by_id("c1").external_notes)))

print("=== 3) malformed LLM response degrades gracefully ===")
tm3 = build_teacher_model(a, FakeLLM("not json at all"))
assert tm3.status == "failed", tm3.status
print("ok: malformed -> status=%s (graceful)" % tm3.status)

print("=== 4) closed-loop: learner signal recorded (no LLM) ===")
base = build_teacher_model(a, None)  # fallback skeleton
updated = incorporate_learner_signal(
    a, base, "c2", "我觉得学习率越大越好，这样更快", 0.3, "未理解学习率与收敛的稳定关系", None
)
lg = [an for an in updated.anomalies if an.kind == "learner_gap"]
assert lg, "learner_gap anomaly not recorded"
assert lg[0].status == "surfaced_to_student", lg[0].status
assert lg[0].severity == "high", lg[0].severity
note_c2 = updated.concept_note_by_id("c2")
assert note_c2 and note_c2.learner_signals, "learner_signal not stored on concept note"
print("ok: learner_gap recorded (severity=%s), learner_signals=%d" % (
    lg[0].severity, len(note_c2.learner_signals)))

print("=== 5) anomaly-prioritized path reorders teaching ===")
# Give c2 an open material anomaly so it should jump to the front.
from expert_anything.core.teacher import Anomaly
base.anomalies.append(Anomaly(
    id="an-x", kind="logical_gap",
    description="学习率章节缺少对最优步长的说明", location="学习率", severity="medium", status="open",
))
p = anomaly_prioritized_path(a, base, ["c1", "c2"])
assert p[0] == "c2", "open-anomaly concept should be first: %s" % p
assert set(p) == {"c1", "c2"}, p
ids = anomaly_concept_ids(a, base)
assert "c2" in ids, ids
print("ok: prioritized path=%s, anomaly_concept_ids=%s" % (p, sorted(ids)))

print("=== 6) extraction accuracy: hallucinated concepts are dropped ===")
class ExtractFakeLLM:
    def __init__(self, payload):
        self.payload = payload
    def chat(self, messages, temperature=0.2, json_mode=False, max_tokens=2000):
        return self.payload

# Source mentions 梯度下降 but NOT 量子纠缠 (which a sloppy model might invent).
src = "梯度下降通过反向传播最小化损失。学习率控制每次更新的步长。"
payload_halluc = (
    '{"concepts":['
    '{"name":"梯度下降","definition":"一种优化算法","evidence":["梯度下降通过反向传播最小化损失。"]},'
    '{"name":"量子纠缠","definition":"一种物理现象","evidence":[]}'
    '],"relations":[],"learning_path":["梯度下降","量子纠缠"]}'
)
a6 = extract_knowledge(src, "note.md", ExtractFakeLLM(payload_halluc))
names = [c.name for c in a6.concepts]
assert "梯度下降" in names, names
assert "量子纠缠" not in names, "hallucinated concept was NOT filtered: %s" % names
# evidence must be kept verbatim when it literally appears in the source
gd = next(c for c in a6.concepts if c.name == "梯度下降")
assert gd.evidence and gd.evidence[0] in src, "grounded evidence lost"
print("ok: dropped hallucinated 量子纠缠; kept 梯度下降 with verbatim evidence")

print("=== 7) empty definition is derived from evidence, not left blank ===")
payload_nodef = (
    '{"concepts":[{"name":"梯度下降","definition":"","evidence":["梯度下降通过反向传播最小化损失。"]}],'
    '"relations":[],"learning_path":["梯度下降"]}'
)
a7 = extract_knowledge(src, "note.md", ExtractFakeLLM(payload_nodef))
c7 = a7.concepts[0]
assert c7.definition, "empty definition should be derived from evidence"
assert c7.definition == "梯度下降通过反向传播最小化损失。", c7.definition
print("ok: definition derived from evidence when model left it empty")

print("=== 8) long docs use chunked extraction with dedup (no duplicates) ===")
# Build a >9600 char doc so the chunked path triggers; each chunk returns the
# same two concepts -> they must be merged (deduped) to 2, not 4.
long_src = ("梯度下降通过反向传播最小化损失。学习率控制每次更新的步长。 " * 600)
payload_two = (
    '{"concepts":['
    '{"name":"梯度下降","definition":"一种优化算法","evidence":["梯度下降通过反向传播最小化损失。"]},'
    '{"name":"学习率","definition":"步长超参","evidence":["学习率控制每次更新的步长。"]}'
    '],"relations":[],"learning_path":["梯度下降","学习率"]}'
)
a8 = extract_knowledge(long_src, "book.md", ExtractFakeLLM(payload_two))
assert a8.method.startswith("llm_extraction_chunked"), a8.method
assert len(a8.concepts) == 2, "chunked merge should dedupe to 2, got %d" % len(a8.concepts)
print("ok: chunked method=%s, merged concepts=%d (deduped)" % (a8.method, len(a8.concepts)))

print("\nTEACHER VERIFY PASSED")

# === 9) real LLM wiring (only when EXPERTANYTHING_LLM_API_KEY is set) =======
# Guards against the silent {vary} bug that once made every teach() fall back
# to the deterministic stub, so "例子/图示" felt ineffective.
if config.has_llm():
    from expert_anything.core.llm import LLMClient
    from expert_anything.core.tutor import Tutor

    print("\n=== 9) REAL LLM: extraction + teaching styles are actually used ===")
    real_llm = LLMClient(config.LLM_API_KEY, config.LLM_BASE_URL, config.LLM_MODEL, timeout=90)
    sample = (
        "# 梯度下降\n梯度下降是一种迭代优化算法，用于最小化损失函数。"
        "它计算损失函数关于模型参数的梯度，并沿梯度的反方向更新参数。学习率决定了每次更新的步长大小。\n"
        "# 反向传播\n反向传播是一种高效计算神经网络梯度的算法。它利用链式法则，"
        "从输出层向输入层逐层传播误差，从而求出每个参数的梯度。\n"
    )
    a9 = extract_knowledge(sample, "ml.md", real_llm)
    assert a9.method.startswith("llm_extraction"), a9.method
    assert len(a9.concepts) >= 2 and all(c.definition for c in a9.concepts)
    print("ok: real-LLM extraction -> %d concepts, method=%s" % (len(a9.concepts), a9.method))

    c9 = a9.concepts[0]
    lessons = {s: Tutor(a9, real_llm).teach(c9, style=s) for s in ["例子", "图示", "拆解步骤"]}
    # The LLM must actually drive teaching, not the stub (stub example starts with
    # the literal "把" + concept name and never uses evidence-based metaphors).
    for s, les in lessons.items():
        assert les["style"] == s, "teach() dropped the requested style: %s" % les["style"]
        assert les["example"] and "把" + c9.name not in les["example"][:6], \
            "teach(%s) returned the deterministic stub, LLM not used!" % s
    assert len(lessons["拆解步骤"]["steps"]) >= 4, "拆解步骤 should yield >=4 steps"
    v0 = Tutor(a9, real_llm).teach(c9, style="例子", vary=0)["example"]
    v1 = Tutor(a9, real_llm).teach(c9, style="例子", vary=1)["example"]
    assert v0 != v1, "换一个例子 should produce a different example"

    # Requirement 4: examples/steps must differ ACROSS concepts, not just per vary.
    c9b = a9.concepts[1]
    lesA = Tutor(a9, real_llm).teach(c9, style="例子")["example"]
    lesB = Tutor(a9, real_llm).teach(c9b, style="例子")["example"]
    assert lesA != lesB, "teach() example must differ across distinct concepts"
    stA = Tutor(a9, real_llm).teach(c9, style="拆解步骤")["steps"]
    stB = Tutor(a9, real_llm).teach(c9b, style="拆解步骤")["steps"]
    assert stA != stB, "teach() steps must differ across distinct concepts"
    print("ok: 3 styles produce distinct LLM content; 换一个例子 varies; per-concept examples/steps differ; 拆解步骤 steps=%d"
          % len(lessons["拆解步骤"]["steps"]))
else:
    print("\n=== 9) skipped: no EXPERTANYTHING_LLM_API_KEY (real-LLM path) ===")

