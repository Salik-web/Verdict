"""Google AI Studio (Gemini) provider — the real engine adapter.

Speaks the Gemini `generateContent` REST API directly (NOT the OpenAI-compatible
shape), because the thing we actually need is **Grounding with Google Search**,
which has no OpenAI-compatible equivalent. Selected from config like any other
provider (`type: gemini`).

Why grounding matters here: an ungrounded Gemini answer is training-data recall —
it tells you what the model memorised months ago and cites nothing. A grounded
answer is what a real user sees today, and it carries the source URLs that the
Diagnosis stage needs. So `measurement` runs grounded; cheap tasks don't.

Request (docs: ai.google.dev/gemini-api/docs/generate-content/google-search):

    POST {base_url}/models/{model}:generateContent
    x-goog-api-key: $GOOGLE_API_KEY
    {"contents": [{"role": "user", "parts": [{"text": "..."}]}],
     "tools": [{"google_search": {}}]}

Response grounding shape (same docs):

    "groundingMetadata": {
      "webSearchQueries": [...],
      "searchEntryPoint": {"renderedContent": "<html>"},
      "groundingChunks": [{"web": {"uri": "https://vertexaisearch.cloud.google.com/...",
                                   "title": "aljazeera.com"}}],
      "groundingSupports": [{"segment": {...}, "groundingChunkIndices": [0]}]
    }

NOTE (verified against the docs' own example): `groundingChunks[].web.uri` is a
**vertexaisearch.cloud.google.com redirect**, not the publisher's URL. The
publisher is identifiable from `.title` (a domain, e.g. "uefa.com"). We surface
the uri as the citation and the title alongside it; resolving redirects to real
publisher URLs would cost an HTTP call per citation and is deliberately not done
here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.gateway.models_config import ResolvedTarget, RetryConfig
from app.gateway.providers.base import Provider
from app.gateway.providers.http import post_with_retry, resolve_api_key
from app.gateway.providers.registry import register_provider
from app.gateway.types import Citation, Message, ProviderResult, Usage

if TYPE_CHECKING:
    from app.gateway.models_config import ModelsConfig

# Gemini uses "model" where OpenAI-style APIs use "assistant"; system prompts go
# in a dedicated systemInstruction field rather than the message list.
_ROLE_MAP = {"user": "user", "assistant": "model"}


@register_provider("gemini")
class GeminiProvider(Provider):
    def __init__(self, retry_config: RetryConfig, timeout_s: float = 60.0) -> None:
        self._retry = retry_config
        # Grounded calls run a real search before answering, so they're slower
        # than a plain completion — hence the larger default timeout.
        self._timeout = timeout_s

    @classmethod
    def from_config(cls, config: ModelsConfig) -> GeminiProvider:
        return cls(config.retry)

    def generate(
        self,
        target: ResolvedTarget,
        messages: list[Message],
        params: dict[str, Any],
    ) -> ProviderResult:
        cfg = target.provider_config
        if not cfg.base_url or not cfg.api_key_env:
            raise ValueError(
                f"provider '{target.provider}' is missing base_url/api_key_env"
            )
        api_key = resolve_api_key(cfg.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"{cfg.api_key_env} is not set — required for provider "
                f"'{target.provider}' (or run in mock mode). Put it in "
                f"services/pipeline/.env or the process environment."
            )

        payload = self._build_payload(target, messages, params)
        url = f"{cfg.base_url.rstrip('/')}/models/{target.model}:generateContent"
        resp = post_with_retry(
            url,
            headers={"x-goog-api-key": api_key, "content-type": "application/json"},
            payload=payload,
            retry=self._retry,
            timeout_s=self._timeout,
            provider=target.provider,
            model=target.model,
        )
        resp.raise_for_status()
        return self._parse(resp.json())

    # ── request ─────────────────────────────────────────────────────────
    def _build_payload(
        self,
        target: ResolvedTarget,
        messages: list[Message],
        params: dict[str, Any],
    ) -> dict[str, Any]:
        contents: list[dict[str, Any]] = []
        system_parts: list[dict[str, str]] = []
        for m in messages:
            if m.role == "system":
                system_parts.append({"text": m.content})
                continue
            contents.append({"role": _ROLE_MAP[m.role], "parts": [{"text": m.content}]})

        payload: dict[str, Any] = {"contents": contents}
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}

        # Config decides which tasks are grounded (models.yaml -> grounding: true).
        if target.grounding:
            payload["tools"] = [{"google_search": {}}]

        generation_config: dict[str, Any] = {}
        # Native JSON mode. Deliberately NOT applied to grounded calls: combining
        # structured output with built-in tools (incl. Grounding with Google
        # Search) is a Gemini-3-only preview feature, so on 2.5 the two are
        # mutually exclusive — and measurement wants prose anyway.
        # ai.google.dev/gemini-api/docs/structured-output
        if target.json_output and not target.grounding:
            generation_config["responseMimeType"] = "application/json"
        if "temperature" in params:
            generation_config["temperature"] = params["temperature"]
        if "max_tokens" in params:
            generation_config["maxOutputTokens"] = params["max_tokens"]
        if "top_p" in params:
            generation_config["topP"] = params["top_p"]
        if generation_config:
            payload["generationConfig"] = generation_config
        return payload

    # ── response ────────────────────────────────────────────────────────
    def _parse(self, data: dict[str, Any]) -> ProviderResult:
        candidates = data.get("candidates") or []
        if not candidates:
            # Safety blocks / empty candidates come back as a 200 with no answer.
            feedback = data.get("promptFeedback", {})
            raise RuntimeError(
                f"gemini returned no candidates (promptFeedback={feedback})"
            )
        candidate = candidates[0]

        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)

        usage_raw = data.get("usageMetadata") or {}
        usage = Usage(
            prompt_tokens=usage_raw.get("promptTokenCount", 0),
            completion_tokens=usage_raw.get("candidatesTokenCount", 0),
            total_tokens=usage_raw.get("totalTokenCount", 0),
        )
        return ProviderResult(
            text=text,
            usage=usage,
            raw=data,
            citations=extract_citations(candidate),
            sources=extract_sources(candidate),
        )


def extract_citations(candidate: dict[str, Any]) -> list[str]:
    """Pull source URLs out of groundingMetadata.groundingChunks[].web.uri.

    Order-preserving and de-duplicated, so cited_urls reads the way the engine
    ranked its sources. Ungrounded responses have no groundingMetadata -> [].
    """
    metadata = candidate.get("groundingMetadata") or {}
    urls: list[str] = []
    for chunk in metadata.get("groundingChunks") or []:
        uri = (chunk.get("web") or {}).get("uri")
        if uri and uri not in urls:
            urls.append(uri)
    return urls


def citation_titles(candidate: dict[str, Any]) -> list[str]:
    """The publisher domains behind the redirect URIs (groundingChunks[].web.title
    — e.g. "uefa.com"). This, not the uri, is the useful GEO signal."""
    metadata = candidate.get("groundingMetadata") or {}
    titles: list[str] = []
    for chunk in metadata.get("groundingChunks") or []:
        title = (chunk.get("web") or {}).get("title")
        if title and title not in titles:
            titles.append(title)
    return titles


def extract_sources(candidate: dict[str, Any]) -> list[Citation]:
    """groundingChunks[].web -> [{url, title}], preserving order + dedup by url.
    Keeps BOTH the redirect uri and the publisher domain so downstream can show
    'which sources the engine cited', not just opaque redirects."""
    metadata = candidate.get("groundingMetadata") or {}
    sources: list[Citation] = []
    seen: set[str] = set()
    for chunk in metadata.get("groundingChunks") or []:
        web = chunk.get("web") or {}
        uri = web.get("uri")
        if uri and uri not in seen:
            seen.add(uri)
            sources.append(Citation(url=uri, title=web.get("title")))
    return sources
