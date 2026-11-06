"""Minimal, dependency-free OpenAI-compatible chat client.

Uses only the standard library so the desktop app has no extra network
dependency. Works with any /v1/chat/completions endpoint:
OpenAI, DeepSeek, Azure OpenAI, or a local Ollama/llama.cpp gateway.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import logging
import os
import re
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)


class LLMNotConfigured(RuntimeError):
    """Raised when no API key is set but an LLM call is attempted."""


class LLMError(RuntimeError):
    """Raised when the endpoint returns an error or is unreachable."""


def _strip_json_fences(text: str) -> str:
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    return s


def _outermost_object(s: str) -> str:
    """Return the {...} block, tolerating a truncated (unclosed) tail."""
    start = s.find("{")
    if start < 0:
        return ""
    end = s.rfind("}")
    if end >= start:
        return s[start : end + 1]
    return s[start:]


def _json_shape(s: str) -> tuple[list[str], bool]:
    """Open close-brackets (innermost last) plus "still inside a string" flag."""
    stack: list[str] = []
    in_str = False
    i = 0
    while i < len(s):
        ch = s[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]":
            if stack:
                stack.pop()
        i += 1
    return stack, in_str


def _repair_stray_quotes(s: str) -> str:
    """Escape unescaped double quotes *inside* JSON string values.

    Local models emit ``"evidence": "知识"解译"成图像…"`` — syntactically
    invalid but obviously the intended string. This only repairs quoting; it
    never rewrites the content, so evidence stays verbatim-auditable.
    """
    out: list[str] = []
    in_str = False
    i = 0
    while i < len(s):
        ch = s[i]
        if in_str and ch == "\\" and i + 1 < len(s):
            out.append(s[i : i + 2])
            i += 2
            continue
        if ch == '"':
            if not in_str:
                in_str = True
                out.append(ch)
            else:
                nxt = next((c for c in s[i + 1 :] if not c.isspace()), "")
                if nxt in ("", ",", "}", "]", ":"):
                    in_str = False
                    out.append(ch)
                else:
                    out.append('\\"')
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _strip_trailing_commas(s: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", s)


def _close_json(s: str) -> str:
    """Close a truncated JSON tail (string, arrays, objects). Syntax only."""
    stack, in_str = _json_shape(s)
    tail = '"' if in_str else ""
    tail += "".join(reversed(stack))
    return s + tail


def _try_parse_object(s: str) -> dict | None:
    try:
        data = json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def parse_llm_json_detailed(text: str) -> tuple[dict, dict]:
    """Tolerant parse plus a record of what was repaired / truncated.

    Returns ``(data, info)`` where ``info`` has ``truncated`` and ``repairs``.
    Repairs are **syntax only** (stray quotes, trailing commas, missing
    closers); string content — and therefore evidence text — is never rewritten.
    """
    info: dict = {"truncated": False, "repairs": []}
    if not text or not text.strip():
        return {}, info
    s = _strip_json_fences(text)
    data = _try_parse_object(s)
    if data is not None:
        return data, info
    block = _outermost_object(s)
    if not block:
        return {}, info
    data = _try_parse_object(block)
    if data is not None:
        info["truncated"] = not block.endswith("}")
        return data, info

    stack, in_str = _json_shape(block)
    info["truncated"] = bool(stack) or in_str

    # Cumulative repairs, tried in order of increasing structural intervention.
    working = block
    applied: list[str] = []
    steps: list[tuple[str, object]] = [("stray_quotes", _repair_stray_quotes)]
    if info["truncated"]:
        steps.append(("closed_braces", _close_json))
    steps.append(("trailing_commas", _strip_trailing_commas))
    for name, fn in steps:
        repaired = fn(working)
        if repaired != working:
            working = repaired
            applied.append(name)
        data = _try_parse_object(working)
        if data is not None and data:
            info["repairs"] = applied[:]
            return data, info
    return {}, info


def parse_llm_json(text: str) -> dict:
    """Tolerant JSON extraction from an LLM response.

    Many OpenAI-compatible endpoints wrap JSON in ```json fences or include
    prose around it. We strip fences, grab the outermost {...} block, and then
    apply syntax-only repairs (unescaped quotes / trailing commas / truncated
    tail) so a malformed response still yields the object we want.

    Single canonical implementation: extraction.py / teacher.py / tutor.py
    previously carried near-identical copies (AGENTS.md #11 - long prompts with
    json_mode can return fenced or prose-wrapped output; parse tolerantly).
    """
    return parse_llm_json_detailed(text)[0]


# Backwards-compatible alias for pre-existing internal/test references.
_parse_json = parse_llm_json


# --------------------------------------------------------------------------- #
# Endpoint capability profiles (json_mode / response_format)
# --------------------------------------------------------------------------- #
# Not every OpenAI-compatible endpoint honours response_format=
# {"type":"json_object"}. llama.cpp's JSON grammar, for instance, stops with EOS
# right after the first object (AGENTS.md #48). Round 32 probed once per TTL;
# round 33 persists what we learn so a known-bad endpoint never pays for the
# failed attempt again:
#
#   data/llm_capability_profiles.json  (env EXPERTANYTHING_LLM_PROFILE_PATH)
#   {"schema_version": 1, "profiles": {"<base_url>|<model>": {...}}}
#
# Invalidate by changing the model alias / base_url (different key), deleting the
# file, or EXPERTANYTHING_LLM_PROFILE_RESET=1. Corrupt/unreadable files degrade
# to "probe again" and never break extraction.
PROBE_TTL_SECONDS = 600.0
_PROBE_TIMEOUT_SECONDS = 15.0
PROFILE_SCHEMA_VERSION = 1
PROFILE_FILENAME = "llm_capability_profiles.json"
PROFILE_TTL_SECONDS = 7 * 24 * 3600.0
_json_mode_cache: dict[str, tuple[float, "EndpointCapability"]] = {}
_json_mode_cache_lock = threading.Lock()
_profile_lock = threading.RLock()
_profiles_cache: dict | None = None
_notice_emitted: set[str] = set()


@dataclass
class EndpointCapability:
    """Verdict of a capability lookup (persisted profile, probe, or policy)."""

    json_mode: bool
    status: str  # "supported" | "unsupported" | "timeout" | "unknown" | "policy"
    detail: str = ""
    checked_at: float = 0.0
    # persisted | probe | forced | default
    source: str = "probe"

    def as_dict(self) -> dict:
        return {
            "json_mode": self.json_mode,
            "status": self.status,
            "detail": self.detail,
            "checked_at": self.checked_at,
            "source": self.source,
        }


def reset_json_mode_probe_cache() -> None:
    """Drop cached probe verdicts (tests / endpoint restarts)."""
    with _json_mode_cache_lock:
        _json_mode_cache.clear()


def _probe_cache_key(llm: object) -> str:
    base = str(getattr(llm, "base_url", ""))
    model = str(getattr(llm, "model", ""))
    return f"{base}|{model}"


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    text = f"{type(exc).__name__}: {exc}".lower()
    return "timed out" in text or "timeout" in text


# -- profile persistence ------------------------------------------------------
def _profile_path() -> Path:
    env = os.environ.get("EXPERTANYTHING_LLM_PROFILE_PATH", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent / "data" / PROFILE_FILENAME


def _profile_ttl() -> float:
    try:
        return float(os.environ.get("EXPERTANYTHING_LLM_PROFILE_TTL", str(PROFILE_TTL_SECONDS)))
    except ValueError:
        return PROFILE_TTL_SECONDS


def _empty_store() -> dict:
    return {"schema_version": PROFILE_SCHEMA_VERSION, "profiles": {}}


def _read_profiles() -> dict:
    """Load the store once; corruption/unknown schema falls back to "empty"."""
    global _profiles_cache
    with _profile_lock:
        if _profiles_cache is not None:
            return _profiles_cache
        reset = os.environ.get("EXPERTANYTHING_LLM_PROFILE_RESET", "").strip().lower()
        if reset in ("1", "on", "true", "yes"):
            _profiles_cache = _empty_store()
            try:
                _profile_path().unlink(missing_ok=True)
            except Exception:
                pass
            return _profiles_cache
        store = _empty_store()
        fp = _profile_path()
        try:
            if fp.exists():
                raw = json.loads(fp.read_text(encoding="utf-8"))
                if (
                    isinstance(raw, dict)
                    and raw.get("schema_version") == PROFILE_SCHEMA_VERSION
                    and isinstance(raw.get("profiles"), dict)
                ):
                    store = raw
                else:
                    logger.warning(
                        "llm capability profile schema mismatch (%s); ignoring it", fp
                    )
        except Exception as exc:
            logger.warning(
                "llm capability profile unreadable (%s): %s; probing instead", fp, exc
            )
        _profiles_cache = store
        return store


def _write_profiles(store: dict) -> None:
    fp = _profile_path()
    try:
        fp.parent.mkdir(parents=True, exist_ok=True)
        tmp = fp.with_suffix(fp.suffix + ".tmp")
        tmp.write_text(
            json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp, fp)
    except Exception as exc:
        logger.warning("could not persist llm capability profile: %s", exc)


def reload_capability_profiles() -> None:
    """Drop the in-process profile cache so the file is read again."""
    global _profiles_cache
    with _profile_lock:
        _profiles_cache = None


def reset_capability_profiles() -> None:
    """Forget every learned endpoint profile (and delete the file)."""
    global _profiles_cache
    with _profile_lock:
        _profiles_cache = _empty_store()
        try:
            _profile_path().unlink(missing_ok=True)
        except Exception:
            pass
    reset_json_mode_probe_cache()
    with _profile_lock:
        _notice_emitted.clear()


def _get_profile(llm: object) -> dict | None:
    base = str(getattr(llm, "base_url", ""))
    model = str(getattr(llm, "model", ""))
    store = _read_profiles()
    prof = store["profiles"].get(f"{base}|{model}")
    if not isinstance(prof, dict):
        return None
    # A hand-edited / renamed entry must not be trusted.
    if prof.get("base_url") != base or prof.get("model") != model:
        return None
    last = prof.get("last_confirmed")
    ttl = _profile_ttl()
    if not isinstance(last, (int, float)) or (ttl >= 0 and time.time() - last > ttl):
        return None
    return prof


def _save_profile(llm: object, **updates) -> dict:
    """Merge ``updates`` into the endpoint's profile and persist atomically."""
    base = str(getattr(llm, "base_url", ""))
    model = str(getattr(llm, "model", ""))
    key = f"{base}|{model}"
    now = time.time()
    with _profile_lock:
        store = _read_profiles()
        prof = store["profiles"].get(key)
        if not isinstance(prof, dict):
            prof = {}
        prof.update(
            {
                "base_url": base,
                "model": model,
                "first_seen": prof.get("first_seen", now),
                "last_confirmed": now,
                "probe_count": int(prof.get("probe_count", 0)),
                "json_mode_supported": bool(prof.get("json_mode_supported", False)),
                "grammar_early_stop": bool(prof.get("grammar_early_stop", False)),
                "early_stop_observations": int(prof.get("early_stop_observations", 0)),
                "min_output_tokens": int(prof.get("min_output_tokens", 0)),
            }
        )
        prof.update(updates)
        store["profiles"][key] = prof
        _write_profiles(store)
        return dict(prof)


def _capability_from_profile(prof: dict) -> EndpointCapability:
    if prof.get("grammar_early_stop"):
        return EndpointCapability(
            False,
            "unsupported",
            "persisted profile: grammar early stop observed",
            float(prof.get("last_confirmed", 0.0)),
            source="persisted",
        )
    supported = bool(prof.get("json_mode_supported"))
    return EndpointCapability(
        supported,
        "supported" if supported else "unsupported",
        "persisted profile",
        float(prof.get("last_confirmed", 0.0)),
        source="persisted",
    )


def _emit_grammar_notice(llm: object) -> None:
    """Explain the persisted decision once per endpoint per process."""
    key = _probe_cache_key(llm)
    with _profile_lock:
        if key in _notice_emitted:
            return
        _notice_emitted.add(key)
    logger.info(
        "endpoint %s previously stopped early under response_format (grammar); "
        "json_mode stays off. Reset with EXPERTANYTHING_LLM_PROFILE_RESET=1.",
        key,
    )


def _profile_min_output_tokens(llm: object) -> int:
    """Budget the endpoint already proved it needs (0 = nothing learned)."""
    prof = _get_profile(llm) or {}
    try:
        return max(0, int(prof.get("min_output_tokens", 0)))
    except (TypeError, ValueError):
        return 0


def _mark_success_budget(llm: object, budget: int | None) -> None:
    """Remember the budget a schema-complete answer needed on this endpoint.

    Round 34 E2E: the local endpoint truncated a 3067-char document at 2286
    tokens under json_mode and only finished at 3886 (3369 actually used). The
    next run starts from that known-good budget instead of paying the doomed
    smaller attempt again. Monotonic: a later small success never lowers it.
    """
    if not budget:
        return
    prof = _get_profile(llm) or {}
    known = int(prof.get("min_output_tokens", 0) or 0)
    if budget > known:
        _save_profile(llm, min_output_tokens=budget)


def _mark_grammar_early_stop(llm: object) -> None:
    """Persist a grammar early-stop observation so the next run skips json_mode."""
    prof = _get_profile(llm) or {}
    was_known = bool(prof.get("grammar_early_stop"))
    _save_profile(
        llm,
        grammar_early_stop=True,
        early_stop_observations=int(prof.get("early_stop_observations", 0)) + 1,
    )
    if not was_known:
        logger.warning(
            "endpoint %s stopped after the first object under response_format; "
            "remembered in %s — future runs use the tolerant path",
            _probe_cache_key(llm),
            _profile_path(),
        )


def _looks_like_grammar_early_stop(
    content: str,
    data: dict,
    truncated: bool,
    budget: int | None,
    required: Iterable[str],
    usage: dict | None = None,
) -> bool:
    """Distinguish "grammar stopped after the first object" from real truncation.

    Rules (also in AGENTS.md #48):
      * only meaningful when the caller declared a schema (``required``) and
        a budget was sent;
      * the output must be tiny relative to the budget — completion_tokens <=
        15% of max_tokens when the endpoint reports usage, else fewer characters
        than half the budget's rough char capacity;
      * and structurally incomplete — a required key is absent, or the answer
        was truncated after a single concept.

    Observed on llama.cpp (AGENTS.md #48): the JSON grammar can close a valid
    object right after the first concept, so ``finish_reason`` is often **stop**
    while ``relations`` is missing entirely — checking only for ``length`` would
    never learn this defect. Conversely, a genuine "too long" answer fills its
    budget and keeps its schema keys, so it fails the tiny-output test and is
    never memorised. A small but schema-complete answer (e.g. a short chunk with
    one concept and an empty ``relations`` list) is also left alone.
    """
    if not budget or not tuple(required):
        return False
    chars = len(content or "")
    tokens = (usage or {}).get("completion_tokens")
    if isinstance(tokens, int) and tokens > 0:
        tiny = tokens <= max(256, int(budget * 0.15))
    else:
        tiny = chars < max(900, int(budget * 1.2 * 0.5))
    if not tiny:
        return False
    if not isinstance(data, dict) or not data:
        return truncated
    if any(k not in data for k in required):
        # Schema never completed: the grammar stopped after the first object
        # (finish_reason is "stop" on llama.cpp here, not "length").
        return True
    if not truncated:
        return False
    concepts = data.get("concepts")
    return isinstance(concepts, list) and len(concepts) <= 1


def resolve_json_mode(llm: object) -> tuple[bool, EndpointCapability | None]:
    """Decide whether to send ``response_format`` for this client.

    Policy (EXPERTANYTHING_LLM_JSON_MODE): ``on``/``off`` force the choice.
    ``auto`` (default) first consults the persisted profile for this
    (base_url, model) — a known-bad / grammar-early-stop endpoint skips the
    doomed attempt entirely — then falls back to a cached probe. Clients without
    probing support (test fakes) keep the historical json_mode=True behaviour;
    the shape-retry in :func:`chat_json` still recovers if the endpoint chokes.
    Probe failures are *fail-safe*: timeout / server error selects the tolerant
    ``response_format``-free path.
    """
    policy = os.environ.get("EXPERTANYTHING_LLM_JSON_MODE", "auto").strip().lower()
    if policy in ("1", "on", "true", "yes", "enabled"):
        return True, EndpointCapability(True, "policy", "forced on", time.time(), "forced")
    if policy in ("0", "off", "false", "no", "disabled"):
        return False, EndpointCapability(False, "policy", "forced off", time.time(), "forced")
    probe = getattr(llm, "probe_json_mode", None)
    if not callable(probe):
        return True, EndpointCapability(
            True, "unknown", "client has no probe", time.time(), "default"
        )
    try:
        cap = probe()
    except Exception as exc:  # probe must never break the normal path
        logger.warning("json_mode probe raised, using tolerant path: %s", exc)
        return False, EndpointCapability(
            json_mode=False, status="unknown", detail=str(exc)[:200],
            checked_at=time.time(), source="probe",
        )
    if cap.source == "persisted" and cap.status == "unsupported":
        _emit_grammar_notice(llm)
    return bool(cap.json_mode), cap



# --------------------------------------------------------------------------- #
# Deterministic response disk cache
# --------------------------------------------------------------------------- #
# Re-running extraction / teacher build / tutoring on the same asset should not
# re-pay the LLM. We key on a content hash of everything that influences the
# output (model, messages, temperature, json_mode, max_tokens) so any prompt or
# config change correctly produces a cache miss. Pure stdlib, works fully
# offline. Disable by setting EXPERTANYTHING_LLM_CACHE=0 (off/false/no/disabled).
LLM_CACHE_VERSION = "v1"
_llm_cache_lock = threading.Lock()
_llm_cache_dir: Path | None = None
_llm_cache_enabled = True


def configure_llm_cache(cache_dir: str | None = None, enabled: bool | None = None) -> None:
    """Point the cache at ``cache_dir`` and/or toggle it.

    ``cache_dir=None`` resets to the default location (project ``data/.llm_cache``,
    git-ignored). ``enabled`` flips the cache; the EXPERTANYTHING_LLM_CACHE env
    var still wins at call time when set to an off value.
    """
    global _llm_cache_dir, _llm_cache_enabled
    if enabled is not None:
        _llm_cache_enabled = enabled
    if cache_dir is not None:
        _llm_cache_dir = Path(cache_dir)


def _llm_cache_active() -> bool:
    if not _llm_cache_enabled:
        return False
    env = os.environ.get("EXPERTANYTHING_LLM_CACHE", "").strip().lower()
    if env in ("0", "off", "false", "no", "disabled"):
        return False
    return True


def _llm_cache_path() -> Path:
    if _llm_cache_dir is not None:
        return _llm_cache_dir
    return Path(__file__).resolve().parent.parent.parent / "data" / ".llm_cache"


def _llm_cache_key(
    model: str,
    messages: Iterable[Message],
    temperature: float,
    json_mode: bool,
    max_tokens: int | None,
    seed: int | None = None,
) -> str:
    payload = json.dumps(
        {
            "v": LLM_CACHE_VERSION,
            "model": model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
            "json_mode": json_mode,
            "max_tokens": max_tokens,
            "seed": seed,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _llm_cache_get(key: str) -> str | None:
    with _llm_cache_lock:
        fp = _llm_cache_path() / f"{key}.txt"
        if fp.exists():
            try:
                return fp.read_text(encoding="utf-8")
            except Exception:
                return None
    return None


def _llm_cache_put(key: str, content: str) -> None:
    try:
        with _llm_cache_lock:
            d = _llm_cache_path()
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{key}.txt").write_text(content, encoding="utf-8")
    except Exception:
        pass


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


class LLMClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 60.0,
        max_concurrency: int = 2,
        probe_timeout: float = _PROBE_TIMEOUT_SECONDS,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        # Cap simultaneous in-flight requests to the endpoint. Some providers
        # (e.g. agnes-ai.cn) rate-limit concurrency aggressively, and a burst of
        # parallel chunk extractions followed by the self-learn call would
        # otherwise return empty/429 bodies and silently degrade. The semaphore
        # throttles the burst while still allowing real parallelism.
        self.max_concurrency = max(1, max_concurrency)
        self._sem = threading.Semaphore(self.max_concurrency)
        # A capability probe that hangs must never delay real work.
        self.probe_timeout = probe_timeout

    @classmethod
    def from_config(
        cls,
        key: str,
        base_url: str,
        model: str,
        max_concurrency: int = 2,
        timeout: float = 60.0,
    ) -> "LLMClient":
        if not key.strip():
            raise LLMNotConfigured(
                "未配置 LLM API Key（环境变量 EXPERTANYTHING_LLM_API_KEY）。"
            )
        return cls(
            key, base_url, model, timeout=timeout, max_concurrency=max_concurrency
        )

    # -- transport ---------------------------------------------------------
    def _post_chat(self, payload: dict, timeout: float | None = None) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with self._sem:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))

    # -- endpoint capability ----------------------------------------------
    def probe_json_mode(self, *, force: bool = False) -> EndpointCapability:
        """Return the endpoint's json_mode verdict, persisted across runs.

        Order: fresh on-disk profile for (base_url, model) -> cached probe ->
        live probe. A profile hit means a known-bad endpoint is never asked with
        ``response_format`` again (that is the whole point: skip the doomed
        first attempt). ``EXPERTANYTHING_LLM_PROFILE_TTL`` (default 7 days) and
        ``EXPERTANYTHING_LLM_PROBE_TTL`` (in-memory, default 600s) bound reuse.
        The profile stores ``probe_count`` so reuse is observable.
        """
        key = _probe_cache_key(self)
        now = time.time()
        if not force:
            prof = _get_profile(self)
            if prof is not None:
                return _capability_from_profile(prof)
        ttl = float(os.environ.get("EXPERTANYTHING_LLM_PROBE_TTL", str(PROBE_TTL_SECONDS)))
        with _json_mode_cache_lock:
            hit = _json_mode_cache.get(key)
            if hit is not None and not force and (ttl < 0 or now - hit[0] < ttl):
                return hit[1]
        cap = self._probe_json_mode_once()
        cap.source = "probe"
        with _json_mode_cache_lock:
            _json_mode_cache[key] = (now, cap)
        if cap.status in ("supported", "unsupported"):
            # Only definitive verdicts are persisted. A transient timeout /
            # unknown answer must not disable json_mode for the whole profile
            # TTL; those stay in the short-lived in-memory probe cache.
            prev = _get_profile(self)
            probe_count = int((prev or {}).get("probe_count", 0)) + 1
            _save_profile(
                self,
                probe_count=probe_count,
                last_probe_status=cap.status,
                last_probe_detail=cap.detail[:200],
                json_mode_supported=bool(cap.json_mode),
            )
        return cap

    def _probe_json_mode_once(self) -> EndpointCapability:
        payload: dict = {
            "model": self.model,
            "messages": [
                Message(
                    "user",
                    'Reply with exactly this JSON object and nothing else: {"ok": true}',
                ).to_dict()
            ],
            "temperature": 0,
            "max_tokens": 32,
            "response_format": {"type": "json_object"},
        }
        timeout = min(self.probe_timeout, self.timeout) if self.timeout else self.probe_timeout
        try:
            data = self._post_chat(payload, timeout=timeout)
        except urllib.error.HTTPError as exc:  # pragma: no cover - network path
            detail = f"HTTP {exc.code}"
            try:
                detail += ": " + exc.read().decode("utf-8", errors="ignore")[:200]
            except Exception:
                pass
            status = "unsupported" if exc.code in (400, 404, 415, 422) else "unknown"
            return EndpointCapability(False, status, detail, time.time())
        except Exception as exc:  # timeout / unreachable: fail safe
            status = "timeout" if _is_timeout(exc) else "unknown"
            return EndpointCapability(False, status, str(exc)[:200], time.time())

        try:
            content = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            return EndpointCapability(
                False, "unsupported", "response has no message content", time.time()
            )
        parsed = parse_llm_json(content)
        if isinstance(parsed, dict) and parsed:
            return EndpointCapability(True, "supported", "", time.time())
        return EndpointCapability(
            False, "unsupported", f"non-JSON probe reply: {content[:120]!r}", time.time()
        )

    def chat(
        self,
        messages: Iterable[Message],
        *,
        temperature: float = 0.3,
        json_mode: bool = False,
        max_tokens: int | None = None,
        seed: int | None = None,
        meta: dict | None = None,
        timeout: float | None = None,
    ) -> str:
        """Return the assistant message content as a string.

        Responses are cached on disk by a content hash of (model, messages,
        temperature, json_mode, max_tokens, seed): re-running extraction /
        teacher build / tutoring on the same asset reuses prior outputs instead
        of re-paying the LLM. See configure_llm_cache() /
        EXPERTANYTHING_LLM_CACHE. ``meta`` is filled with ``finish_reason`` so
        callers can distinguish truncation from an unparseable answer.
        """
        if not self.api_key.strip():
            raise LLMNotConfigured("LLM 未配置，无法发起真实调用。")

        cache_miss = False
        if _llm_cache_active():
            key = _llm_cache_key(
                self.model, messages, temperature, json_mode, max_tokens, seed
            )
            cached = _llm_cache_get(key)
            if cached is not None:
                return cached
            cache_miss = True

        payload: dict = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if seed is not None:
            payload["seed"] = seed

        try:
            data = self._post_chat(payload, timeout=timeout)
        except urllib.error.HTTPError as exc:  # pragma: no cover - network path
            detail = exc.read().decode("utf-8", errors="ignore")[:500]
            raise LLMError(f"LLM 接口返回错误 {exc.code}: {detail}") from exc
        except Exception as exc:  # pragma: no cover - network path
            raise LLMError(f"调用 LLM 失败: {exc}") from exc

        try:
            choice = data["choices"][0]
            content = choice["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"LLM 返回格式异常: {data}") from exc
        if meta is not None:
            meta["finish_reason"] = choice.get("finish_reason", "")
            meta["usage"] = data.get("usage") or {}

        if cache_miss and content:
            _llm_cache_put(key, content)
        return content

    def chat_json(
        self,
        messages: Iterable[Message],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
        retries: int = 3,
        backoff: float = 1.5,
    ) -> dict:
        """Convenience wrapper: call chat_json() on this client.

        See the module-level chat_json() for the retry/parse semantics — it works
        with any object exposing a chat() method (including test fakes), so we
        delegate rather than duplicate the logic here.
        """
        return chat_json(
            self,
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            retries=retries,
            backoff=backoff,
        )


def _invoke_chat(
    llm: object,
    messages: Iterable[Message],
    *,
    temperature: float,
    json_mode: bool,
    max_tokens: int | None,
    seed: int | None,
    meta: dict,
    timeout: float | None,
) -> str:
    """Call ``llm.chat`` with only the keyword arguments it actually accepts.

    Test doubles predate ``seed``/``meta``/``timeout``; filtering keeps them
    working while real clients get the full call.
    """
    kwargs = {
        "temperature": temperature,
        "json_mode": json_mode,
        "max_tokens": max_tokens,
        "seed": seed,
        "meta": meta,
        "timeout": timeout,
    }
    chat = llm.chat
    try:
        params = inspect.signature(chat).parameters
        accepts_var_kw = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
        )
        if not accepts_var_kw:
            kwargs = {k: v for k, v in kwargs.items() if k in params}
    except (TypeError, ValueError):  # builtins / C callables
        pass
    return chat(messages, **kwargs)


def _bump_budget(budget: int | None) -> int | None:
    if not budget:
        return None
    ceiling = int(os.environ.get("EXPERTANYTHING_LLM_MAX_TOKENS_CEILING", "8192"))
    bumped = min(ceiling, int(budget * 1.7))
    return bumped if bumped > budget else None


def _shape_ok(
    data: dict, required: Iterable[str], nonempty: Iterable[str] = ()
) -> bool:
    """Structural acceptance check.

    ``required`` keys must be *present* (an empty list is still a valid answer,
    e.g. "no relations found"); ``nonempty`` keys must additionally carry
    content. Presence matters: llama.cpp's JSON grammar stopped right after
    the first field, so ``relations`` was absent entirely.
    """
    if not isinstance(data, dict) or not data:
        return False
    if any(key not in data for key in required):
        return False
    for key in nonempty:
        if data.get(key) in (None, "", [], {}):
            return False
    return True


def _call_timeout(llm: object, budget: int | None) -> float:
    """Wall-clock timeout scaled to the requested output tokens.

    A fixed 60s client timeout killed a legitimate local 2340-token generation
    (~70s at 35 tok/s), which then burned every retry and ended in a silent
    fallback. ``EXPERTANYTHING_LLM_SEC_PER_TOKEN`` (default 0.05 => 20 tok/s
    floor) gives slow endpoints head-room without waiting forever.
    """
    base = float(getattr(llm, "timeout", 60.0) or 60.0)
    if not budget:
        return base
    try:
        per_token = float(os.environ.get("EXPERTANYTHING_LLM_SEC_PER_TOKEN", "0.05"))
    except ValueError:
        per_token = 0.05
    return max(base, budget * per_token)


def chat_json(
    llm: "LLMClient | object",
    messages: Iterable[Message],
    *,
    temperature: float = 0.3,
    max_tokens: int | None = None,
    retries: int = 3,
    backoff: float = 1.5,
    json_mode: bool | None = None,
    seed: int | None = None,
    require_keys: Iterable[str] | None = None,
    require_nonempty: Iterable[str] | None = None,
    truncation_retry: bool = True,
    report: dict | None = None,
) -> dict:
    """Call ``llm.chat()`` in JSON mode and return the parsed object.

    This is the single place that decides *how* to survive a degraded endpoint,
    and it never hides that decision:

    * ``json_mode=None`` asks :func:`resolve_json_mode` (cached capability probe)
      whether ``response_format`` is usable; unsupported / timeout endpoints get
      the tolerant ``response_format``-free path instead of an empty ``{}``.
    * A truncated answer (unbalanced JSON or ``finish_reason == "length"``)
      triggers one retry with a larger ``max_tokens`` before giving up.
    * If ``response_format`` was used but the object lacks ``require_keys``
      (llama.cpp's JSON grammar can stop after the first field), we retry once
      *without* it — the concrete AGENTS.md #48 defect.
    * Every attempt is recorded in ``report`` (json_mode, budget, finish_reason,
      repairs, truncation, failure_reason) so the caller can surface provenance.

    Works with any client exposing a ``chat()`` method (real LLMClient or a test
    fake). Raises LLMError only after every attempt is exhausted.
    """
    rep = report if report is not None else {}
    explained = report is not None
    rep.setdefault("attempts", [])
    required = tuple(require_keys or ())
    nonempty = tuple(require_nonempty or ())

    capability: EndpointCapability | None = None
    if json_mode is None:
        json_mode, capability = resolve_json_mode(llm)
        rep["json_mode_capability"] = (
            capability.status if capability is not None else "policy"
        )
        rep["json_mode_source"] = capability.source if capability is not None else "default"
        if capability is not None and capability.detail:
            rep["json_mode_probe_detail"] = capability.detail
            logger.info(
                "endpoint json_mode: status=%s source=%s detail=%s",
                capability.status,
                capability.source,
                capability.detail,
            )
    rep["json_mode"] = json_mode

    budget = max_tokens
    max_attempts = 1 + max(0, retries)
    truncation_bumped = False
    shape_flipped = False
    pending_partial: dict | None = None
    last: Exception | None = None
    timeout_failures = 0
    attempt = 0
    while attempt < max_attempts:
        attempt += 1
        meta: dict = {}
        try:
            content = _invoke_chat(
                llm,
                messages,
                temperature=temperature,
                json_mode=json_mode,
                max_tokens=budget,
                seed=seed,
                meta=meta,
                timeout=_call_timeout(llm, budget),
            )
        except Exception as exc:  # network / HTTP / format errors
            last = exc
            rep["attempts"].append(
                {"json_mode": json_mode, "max_tokens": budget, "error": str(exc)[:200]}
            )
            if _is_timeout(exc):
                timeout_failures += 1
                if timeout_failures >= 2:
                    # Retrying a full-budget timeout just repeats the same
                    # multi-minute wait; fail fast and let the caller mark it.
                    rep["timeout_aborted"] = True
                    break
            if attempt < max_attempts:
                time.sleep(backoff * attempt)
            continue

        data, info = parse_llm_json_detailed(content)
        ok = _shape_ok(data, required, nonempty)
        finish = meta.get("finish_reason", "")
        usage = meta.get("usage") or {}
        truncated = bool(info["truncated"]) or finish == "length"
        rep["attempts"].append(
            {
                "json_mode": json_mode,
                "max_tokens": budget,
                "finish_reason": finish,
                "chars": len(content),
                "tokens": usage.get("completion_tokens"),
                "parsed": bool(data),
                "keys": sorted(data.keys())[:8] if isinstance(data, dict) else [],
                "repairs": info["repairs"],
                "truncated": truncated,
            }
        )
        if json_mode and _looks_like_grammar_early_stop(
            content, data, truncated, budget, required, usage
        ):
            rep["grammar_early_stop"] = True
            _mark_grammar_early_stop(llm)
        if truncated and ok and pending_partial is None:
            # A syntactically closed truncation may be missing later fields
            # (relations, learning_path). Prefer one bigger-budget retry, but
            # keep this partial answer as an explicit fallback instead of
            # degrading to an empty result.
            pending_partial = data
            if truncation_retry and not truncation_bumped:
                bumped = _bump_budget(budget)
                if bumped:
                    budget = bumped
                    truncation_bumped = True
                    rep["truncation_retries"] = 1
                    if json_mode and not shape_flipped:
                        json_mode = False
                        shape_flipped = True
                        rep["json_mode_downgraded"] = True
                    max_attempts += 1
                    continue
        elif ok:
            if required:
                # A schema-complete answer proves this budget suffices; the
                # profile remembers it so the next run skips a doomed smaller
                # attempt (round 34: 2286 truncated, 3886 fine).
                _mark_success_budget(llm, budget)
            rep["parse_repairs"] = sorted(
                {r for a in rep["attempts"] for r in a.get("repairs", [])}
            )
            return data

        if truncated and truncation_retry and not truncation_bumped:
            bumped = _bump_budget(budget)
            if bumped:
                budget = bumped
                truncation_bumped = True
                rep["truncation_retries"] = 1
                # Stopping at the budget cap *only* when response_format is on
                # is a capability smell (llama.cpp's JSON grammar ends early);
                # drop json_mode for the retry as well.
                if json_mode and not shape_flipped:
                    json_mode = False
                    shape_flipped = True
                    rep["json_mode_downgraded"] = True
                max_attempts += 1
                continue

        if json_mode and not shape_flipped:
            # Endpoint claims json_mode support but produced an unusable shape.
            json_mode = False
            shape_flipped = True
            rep["json_mode_downgraded"] = True
            max_attempts += 1
            continue

        last = LLMError(
            "LLM 返回截断的 JSON" if truncated else "LLM 返回空或非 JSON 内容"
        )
        if attempt < max_attempts:
            time.sleep(backoff * attempt)

    if pending_partial is not None:
        rep["truncated_partial"] = True
        rep["parse_repairs"] = sorted(
            {r for a in rep["attempts"] for r in a.get("repairs", [])}
        )
        logger.warning("chat_json returned a truncated (partial) JSON object")
        return pending_partial

    rep["failure_reason"] = str(last)[:300] if last else "LLM 调用失败（无错误信息）"
    if explained:
        logger.warning(
            "chat_json exhausted %d attempt(s): %s", len(rep["attempts"]), rep["failure_reason"]
        )
    raise last if isinstance(last, Exception) else LLMError(rep["failure_reason"])
