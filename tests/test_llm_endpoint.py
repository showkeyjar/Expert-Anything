"""Endpoint-capability / degradation tests (offline, no API key required).

Covers the six degradation paths requested for AGENTS.md item 48:

1. json_mode supported        -> response_format is sent, answer parsed
2. json_mode unsupported      -> HTTP 400 -> tolerant path, no empty result
3. probe timeout              -> fail safe, tolerant path, normal request still runs
4. truncated JSON             -> one retry with a larger max_tokens
5. illegal (non-JSON) answer  -> explicit LLMError with a recorded reason
6. unescaped quotes           -> repaired syntactically, content preserved

Plus: dynamic token budget, probe verdict caching, shape-based json_mode
downgrade, and the "fallback is always explicit" provenance contract.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
import urllib.request as _urllib
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from expert_anything.core import extraction
from expert_anything.core.llm import (
    EndpointCapability,
    LLMClient,
    LLMError,
    Message,
    chat_json,
    parse_llm_json,
    parse_llm_json_detailed,
    reload_capability_profiles,
    reset_capability_profiles,
    reset_json_mode_probe_cache,
    resolve_json_mode,
    _get_profile,
    _looks_like_grammar_early_stop,
    _profile_min_output_tokens,
    _profile_path,
    _save_profile,
)


class _FakeResponse:
    def __init__(self, raw: bytes):
        self._raw = raw

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Endpoint:
    """Stub transport: ``handler(payload)`` returns a dict, bytes or raises."""

    def __init__(self, handler):
        self.handler = handler
        self.requests: list[dict] = []

    def __call__(self, req, timeout=None):
        payload = json.loads(req.data.decode("utf-8"))
        self.requests.append(payload)
        result = self.handler(payload)
        if isinstance(result, Exception):
            raise result
        if isinstance(result, (bytes, str)):
            raw = result.encode() if isinstance(result, str) else result
            return _FakeResponse(raw)
        return _FakeResponse(json.dumps(result).encode())


def _content(body: str, finish_reason: str = "stop", usage: dict | None = None) -> dict:
    return {
        "choices": [{"message": {"content": body}, "finish_reason": finish_reason}],
        "usage": usage or {},
    }


class _Base(unittest.TestCase):
    def setUp(self):
        os.environ.pop("EXPERTANYTHING_LLM_JSON_MODE", None)
        os.environ.pop("EXPERTANYTHING_LLM_PROFILE_RESET", None)
        os.environ["EXPERTANYTHING_LLM_CACHE"] = "0"
        # Isolate learned capability profiles from the real data/ directory.
        self._tmpdir = tempfile.mkdtemp(prefix="ea_llm_profile_")
        os.environ["EXPERTANYTHING_LLM_PROFILE_PATH"] = os.path.join(
            self._tmpdir, "profiles.json"
        )
        reset_json_mode_probe_cache()
        reset_capability_profiles()
        self.orig_urlopen = _urllib.urlopen

    def tearDown(self):
        _urllib.urlopen = self.orig_urlopen
        reset_capability_profiles()
        shutil.rmtree(self._tmpdir, ignore_errors=True)
        os.environ.pop("EXPERTANYTHING_LLM_CACHE", None)
        os.environ.pop("EXPERTANYTHING_LLM_JSON_MODE", None)
        os.environ.pop("EXPERTANYTHING_LLM_PROFILE_PATH", None)
        os.environ.pop("EXPERTANYTHING_LLM_PROFILE_RESET", None)
        reset_json_mode_probe_cache()

    def client(self, endpoint, **kw) -> LLMClient:
        _urllib.urlopen = endpoint
        return LLMClient(
            api_key="sk-test",
            base_url="http://example.invalid/v1",
            model=f"stub-{id(endpoint)}",
            timeout=30,
            **kw,
        )


class TestCapabilityProbe(_Base):
    def test_json_mode_supported(self):
        """Case 1: endpoint answers the probe with JSON -> response_format sent."""

        def handler(payload):
            self.assertTrue(payload.get("response_format"))
            return _content('{"ok": true}')

        ep = _Endpoint(handler)
        c = self.client(ep)
        cap = c.probe_json_mode()
        self.assertEqual(cap.status, "supported")
        self.assertTrue(cap.json_mode)

    def test_json_mode_unsupported_http_400(self):
        """Case 2: HTTP 400 -> unsupported, tolerant path, no empty result."""
        state = {"probe": 0}

        def handler(payload):
            if payload.get("response_format"):
                if state["probe"] == 0:
                    state["probe"] += 1
                    raise urllib.error.HTTPError(
                        "http://example.invalid", 400, "bad request", {},
                        io.BytesIO(b'{"error":"response_format unsupported"}'),
                    )
                return _content("not json")
            return _content('{"concepts": [{"name": "A", "evidence": ["A"]}]}')

        ep = _Endpoint(handler)
        c = self.client(ep)
        report: dict = {}
        data = chat_json(c, [Message("user", "extract")], report=report, retries=0)
        self.assertEqual(report["json_mode_capability"], "unsupported")
        self.assertFalse(report["json_mode"])
        self.assertTrue(data["concepts"])
        # The follow-up request must NOT carry response_format.
        self.assertFalse(ep.requests[-1].get("response_format"))

    def test_probe_timeout_is_fail_safe(self):
        """Case 3: a hanging probe never blocks the real request."""
        def handler(payload):
            if payload.get("response_format"):
                raise TimeoutError("probe timed out")
            return _content('{"concepts": [{"name": "X", "evidence": ["X"]}]}')

        ep = _Endpoint(handler)
        c = self.client(ep)
        report: dict = {}
        data = chat_json(c, [Message("user", "extract")], report=report, retries=0)
        self.assertEqual(report["json_mode_capability"], "timeout")
        self.assertTrue(data["concepts"], "normal path must still produce a result")
        self.assertFalse(ep.requests[-1].get("response_format"))

    def test_probe_verdict_is_cached(self):
        """A cached verdict avoids probing on every call."""
        calls = {"n": 0}

        def handler(payload):
            if payload.get("response_format"):
                calls["n"] += 1
                return _content('{"ok": true}')
            return _content('{"concepts": []}')

        ep = _Endpoint(handler)
        c = self.client(ep)
        c.probe_json_mode()
        c.probe_json_mode()
        self.assertEqual(calls["n"], 1)


class TestCapabilityProfile(_Base):
    def test_profile_hit_skips_probe_and_json_mode(self):
        """A persisted grammar verdict is used without touching the network."""
        calls = {"n": 0}

        def endpoint(req, timeout=None):
            calls["n"] += 1
            return _FakeResponse(json.dumps(_content('{"ok": true}')).encode())

        c = self.client(endpoint)
        _save_profile(c, json_mode_supported=True, grammar_early_stop=True)
        data = resolve_json_mode(c)
        self.assertEqual(calls["n"], 0, "profile hit must not probe")
        self.assertFalse(data[0])
        self.assertEqual(data[1].source, "persisted")
        self.assertEqual(data[1].status, "unsupported")
        self.assertTrue(_profile_path().exists())

    def test_profile_invalidated_by_model_change(self):
        """A different model alias is a different key -> probe again."""
        calls = {"n": 0}

        def handler(payload):
            calls["n"] += 1
            if payload.get("response_format"):
                return _content('{"ok": true}')
            return _content('{"concepts": []}')

        ep = _Endpoint(handler)
        old = self.client(ep)
        _save_profile(old, json_mode_supported=True, grammar_early_stop=True)

        new = LLMClient(api_key="sk-test", base_url=old.base_url, model="other-model")
        _urllib.urlopen = ep
        mode, cap = resolve_json_mode(new)
        self.assertEqual(calls["n"], 1)
        self.assertEqual(cap.source, "probe")
        self.assertTrue(mode)

    def test_corrupt_profile_falls_back_to_probe(self):
        """A damaged profile file must never break extraction."""
        _profile_path().parent.mkdir(parents=True, exist_ok=True)
        _profile_path().write_text("{ this is not json", encoding="utf-8")
        reload_capability_profiles()  # simulate a fresh process reading the file
        ep = _Endpoint(lambda payload: _content('{"ok": true}'))
        c = self.client(ep)
        mode, cap = resolve_json_mode(c)
        self.assertTrue(mode)
        self.assertEqual(cap.source, "probe")
        self.assertTrue(_profile_path().exists())

    def test_reset_clears_profile(self):
        c = self.client(_Endpoint(lambda payload: _content('{"ok": true}')))
        _save_profile(c, json_mode_supported=True)
        self.assertIsNotNone(_get_profile(c))
        reset_capability_profiles()
        self.assertIsNone(_get_profile(c))
        self.assertFalse(_profile_path().exists())

    def test_successful_budget_is_remembered(self):
        """A schema-complete answer stores the budget that actually worked."""

        def handler(payload):
            if "Reply with exactly" in payload["messages"][0]["content"]:
                return _content('{"ok": true}')
            return _content(
                '{"concepts": [{"name": "A", "evidence": ["A"]}], "relations": []}'
            )

        ep = _Endpoint(handler)
        c = self.client(ep)
        report: dict = {}
        chat_json(
            c, [Message("user", "q")], report=report, retries=0,
            max_tokens=3886, require_keys=("concepts", "relations"),
        )
        self.assertEqual(_profile_min_output_tokens(c), 3886)


class TestGrammarEarlyStopDetection(_Base):
    def test_grammar_signature_is_recognised(self):
        """163 tokens / one concept / no relations => grammar early stop."""
        self.assertTrue(
            _looks_like_grammar_early_stop(
                '{"concepts": [{"name": "A", "evidence": ["A"]}]}',
                {"concepts": [{"name": "A"}]},
                True,
                2287,
                ("concepts", "relations"),
                {"completion_tokens": 163},
            )
        )
        # Observed on the local llama.cpp endpoint: the grammar closes a valid
        # object with finish_reason="stop" but never emits "relations".
        self.assertTrue(
            _looks_like_grammar_early_stop(
                '{"concepts": [{"name": "A", "evidence": ["A"]}]}',
                {"concepts": [{"name": "A"}]},
                False,
                2287,
                ("concepts", "relations"),
                {"completion_tokens": 163},
            )
        )

    def test_real_truncation_is_not_misclassified(self):
        """A long answer that actually filled its budget is NOT grammar."""
        data = {"concepts": [{"name": str(i)} for i in range(8)], "relations": []}
        content = "x" * 4000
        self.assertFalse(
            _looks_like_grammar_early_stop(
                content, data, True, 2287, ("concepts", "relations"),
                {"completion_tokens": 2200},
            )
        )
        # Without usage data, the character heuristic still rejects it.
        self.assertFalse(
            _looks_like_grammar_early_stop(
                content, data, True, 2287, ("concepts", "relations"), None
            )
        )

    def test_small_but_complete_answer_is_not_grammar(self):
        """A genuinely short, schema-complete answer must be left alone."""
        data = {"concepts": [{"name": "A"}], "relations": []}
        self.assertFalse(
            _looks_like_grammar_early_stop(
                '{"concepts": [{"name": "A"}], "relations": []}',
                data, False, 1024, ("concepts", "relations"),
                {"completion_tokens": 40},
            )
        )
        # No declared schema => capability is not judged at all.
        self.assertFalse(
            _looks_like_grammar_early_stop("", {}, False, 1024, ())
        )

    def test_grammar_observation_is_persisted_and_reused(self):
        """First run learns the defect; the next resolution uses the profile."""

        def handler(payload):
            if "Reply with exactly" in payload["messages"][0]["content"]:
                return _content('{"ok": true}')
            if payload.get("response_format"):
                return _content(
                    '{"concepts": [{"name": "A", "evidence": ["A"]}]',
                    finish_reason="length",
                    usage={"completion_tokens": 163},
                )
            return _content(
                '{"concepts": [{"name": "A", "evidence": ["A"]}], "relations": []}'
            )

        ep = _Endpoint(handler)
        c = self.client(ep)
        report: dict = {}
        data = chat_json(
            c,
            [Message("user", "q")],
            report=report,
            retries=0,
            max_tokens=2287,
            require_keys=("concepts", "relations"),
            require_nonempty=("concepts",),
        )
        self.assertTrue(data["concepts"])
        self.assertTrue(report.get("grammar_early_stop"))
        prof = _get_profile(c)
        self.assertIsNotNone(prof)
        self.assertTrue(prof["grammar_early_stop"])
        self.assertEqual(prof["early_stop_observations"], 1)

        mode, cap = resolve_json_mode(c)
        self.assertFalse(mode, "next run must skip response_format")
        self.assertEqual(cap.source, "persisted")


class TestDegradedAnswers(_Base):
    def test_truncated_json_retries_with_bigger_budget(self):
        """Case 4: finish_reason=length -> one retry with raised max_tokens."""
        seen_budgets: list[int] = []

        def handler(payload):
            if "Reply with exactly" in payload["messages"][0]["content"]:
                return _content('{"ok": true}')
            seen_budgets.append(payload.get("max_tokens"))
            if len(seen_budgets) == 1:
                return _content('{"concepts": [{"name": "A"', finish_reason="length")
            return _content('{"concepts": [{"name": "A", "evidence": ["A"]}]}')

        ep = _Endpoint(handler)
        c = self.client(ep)
        report: dict = {}
        data = chat_json(
            c, [Message("user", "q")], report=report, retries=0, max_tokens=1000,
            require_keys=("concepts",),
        )
        self.assertTrue(data["concepts"])
        self.assertEqual(report.get("truncation_retries"), 1)
        self.assertGreater(seen_budgets[-1], seen_budgets[0])

    def test_illegal_json_raises_with_reason(self):
        """Case 5: non-JSON answers end in an explicit error, never a fake {}."""
        def handler(payload):
            return _content("I cannot help with that.")

        ep = _Endpoint(handler)
        c = self.client(ep)
        report: dict = {}
        with self.assertRaises(LLMError):
            chat_json(
                c, [Message("user", "q")], report=report, retries=1, backoff=0,
                require_keys=("concepts",),
            )
        self.assertIn("failure_reason", report)
        self.assertTrue(report["failure_reason"])

    def test_unescaped_quotes_repaired_without_rewriting_text(self):
        """Case 6: quote repair is syntax-only; evidence stays verbatim."""
        body = '{"concepts": [{"name": "解码", "evidence": ["知识"解译"成图像"]}]}'
        ep = _Endpoint(lambda payload: _content(body))
        c = self.client(ep)
        report: dict = {}
        data = chat_json(c, [Message("user", "q")], report=report, retries=0)
        self.assertEqual(data["concepts"][0]["evidence"], ['知识"解译"成图像'])
        self.assertIn("stray_quotes", report["parse_repairs"])

    def test_json_mode_shape_downgrade(self):
        """A valid-but-empty json_mode answer retries without response_format."""
        def handler(payload):
            if payload.get("response_format"):
                return _content('{"concepts": []}')
            return _content('{"concepts": [{"name": "A", "evidence": ["A"]}]}')

        ep = _Endpoint(handler)
        c = self.client(ep)
        report: dict = {}
        data = chat_json(
            c, [Message("user", "q")], report=report, retries=0,
            require_keys=("concepts",), require_nonempty=("concepts",),
        )
        self.assertTrue(data["concepts"])
        self.assertTrue(report.get("json_mode_downgraded"))


class TestTolerantParser(unittest.TestCase):
    def test_trailing_commas_and_fences(self):
        raw = '```json\n{"concepts": [{"name": "A",},],}\n```'
        self.assertEqual(parse_llm_json(raw)["concepts"][0]["name"], "A")

    def test_truncated_tail_is_flagged_and_closed(self):
        data, info = parse_llm_json_detailed('{"concepts": [{"name": "A"')
        self.assertTrue(info["truncated"])
        self.assertIn("closed_braces", info["repairs"])
        self.assertEqual(data["concepts"][0]["name"], "A")

    def test_prose_wrapped_object(self):
        raw = 'Here you go:\n{"concepts": []}\nDone.'
        self.assertEqual(parse_llm_json(raw), {"concepts": []})


class TestBudgetAndProvenance(unittest.TestCase):
    def test_dynamic_budget_scales_with_chunk_size(self):
        small = extraction._output_budget("x" * 100)
        large = extraction._output_budget("x" * 9000)
        self.assertGreater(small, 0)
        self.assertGreater(large, 1500, "9000-char chunk must exceed old 1500 cap")
        self.assertLessEqual(large, 8192)

    def test_call_extract_uses_dynamic_budget(self):
        seen: list[int] = []

        class FakeLLM:
            def chat(self, messages, temperature=0.3, json_mode=False, max_tokens=500):
                seen.append(max_tokens)
                return '{"concepts": [{"name": "A", "evidence": ["A"]}], "relations": []}'

        extraction._call_extract(FakeLLM(), "x" * 9000)
        self.assertGreater(seen[-1], 1500)

    def test_llm_failure_fallback_is_explicit(self):
        class BrokenLLM:
            def chat(self, messages, **kw):
                raise LLMError("endpoint down")

        with mock.patch("expert_anything.core.llm.time.sleep", lambda *_: None):
            asset = extraction.extract_knowledge("一些正文内容。" * 20, "a.md", llm=BrokenLLM())
        self.assertEqual(asset.method, "llm_failed_fallback_v1")
        self.assertTrue(asset.provenance.get("explicit_fallback"))
        self.assertIn("endpoint down", asset.provenance.get("fallback_reason", ""))
        # provenance survives persistence
        restored = type(asset).from_dict(asset.to_dict())
        self.assertTrue(restored.provenance.get("explicit_fallback"))

    def test_llm_success_records_llm_provenance(self):
        class GoodLLM:
            def chat(self, messages, **kw):
                return json.dumps(
                    {
                        "concepts": [
                            {"name": "概念甲", "definition": "概念甲", "evidence": ["概念甲"]},
                        ],
                        "relations": [],
                        "learning_path": ["概念甲"],
                    },
                    ensure_ascii=False,
                )

        asset = extraction.extract_knowledge("概念甲。概念甲很重要。", "a.md", llm=GoodLLM())
        self.assertEqual(asset.method, "llm_extraction_v1")
        self.assertTrue(asset.provenance.get("llm"))
        self.assertEqual(asset.provenance.get("source"), "llm_extraction_v1")


class TestEndpointCapabilityObject(unittest.TestCase):
    def test_as_dict_roundtrip(self):
        cap = EndpointCapability(False, "timeout", "timed out", 0.0)
        self.assertEqual(cap.as_dict()["status"], "timeout")


if __name__ == "__main__":
    unittest.main(verbosity=2)
