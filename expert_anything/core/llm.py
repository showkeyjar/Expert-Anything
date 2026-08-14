"""Minimal, dependency-free OpenAI-compatible chat client.

Uses only the standard library so the desktop app has no extra network
dependency. Works with any /v1/chat/completions endpoint:
OpenAI, DeepSeek, Azure OpenAI, or a local Ollama/llama.cpp gateway.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from dataclasses import dataclass
from typing import Iterable


class LLMNotConfigured(RuntimeError):
    """Raised when no API key is set but an LLM call is attempted."""


class LLMError(RuntimeError):
    """Raised when the endpoint returns an error or is unreachable."""


def _parse_json(text: str) -> dict:
    """Tolerant JSON extraction from an LLM response.

    Many OpenAI-compatible endpoints wrap JSON in ```json fences or include
    prose around it. We strip fences and grab the outermost {...} block before
    parsing so a fenced/verbose response still yields the object we want.
    """
    if not text:
        return {}
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", s, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return {}
    return {}


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
        self._sem = threading.Semaphore(max(1, max_concurrency))

    @classmethod
    def from_config(
        cls, key: str, base_url: str, model: str, max_concurrency: int = 2
    ) -> "LLMClient":
        if not key.strip():
            raise LLMNotConfigured(
                "未配置 LLM API Key（环境变量 EXPERTANYTHING_LLM_API_KEY）。"
            )
        return cls(key, base_url, model, max_concurrency=max_concurrency)

    def chat(
        self,
        messages: Iterable[Message],
        *,
        temperature: float = 0.3,
        json_mode: bool = False,
        max_tokens: int | None = None,
    ) -> str:
        """Return the assistant message content as a string."""
        if not self.api_key.strip():
            raise LLMNotConfigured("LLM 未配置，无法发起真实调用。")

        payload: dict = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if max_tokens:
            payload["max_tokens"] = max_tokens

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
        try:
            with self._sem:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # pragma: no cover - network path
            detail = exc.read().decode("utf-8", errors="ignore")[:500]
            raise LLMError(f"LLM 接口返回错误 {exc.code}: {detail}") from exc
        except Exception as exc:  # pragma: no cover - network path
            raise LLMError(f"调用 LLM 失败: {exc}") from exc

        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"LLM 返回格式异常: {data}") from exc

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


def chat_json(
    llm: "LLMClient | object",
    messages: Iterable[Message],
    *,
    temperature: float = 0.3,
    max_tokens: int | None = None,
    retries: int = 3,
    backoff: float = 1.5,
) -> dict:
    """Call llm.chat() with json_mode forced on, then retry on transient failures.

    Some endpoints (e.g. under a burst of concurrent requests) intermittently
    return an empty body or a non-JSON string instead of a 5xx. That used to
    silently degrade the whole self-learning pass. Here we retry on any
    network/HTTP error and on empty/unparseable JSON, with a growing backoff so a
    rate-limited endpoint gets breathing room. Works with any client exposing a
    chat() method (real LLMClient or a test fake). Raises LLMError only after
    every attempt is exhausted.
    """
    last: Exception | None = None
    for attempt in range(1 + retries):
        try:
            content = llm.chat(
                messages,
                temperature=temperature,
                json_mode=True,
                max_tokens=max_tokens,
            )
        except Exception as exc:  # network / HTTP / format errors
            last = exc
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
                continue
            break
        data = _parse_json(content)
        if data:
            return data
        last = LLMError("LLM 返回空或非 JSON 内容")
        if attempt < retries:
            time.sleep(backoff * (attempt + 1))
            continue
        break
    raise last if last else LLMError("LLM 调用失败（无错误信息）")
