from __future__ import annotations

from typing import Any

import requests
from fastapi import HTTPException

from app.settings import (
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    OPENROUTER_HTTP_REFERER,
    OPENROUTER_MAX_TOKENS,
    OPENROUTER_MODEL,
    OPENROUTER_TEMPERATURE,
    OPENROUTER_TIMEOUT_SECONDS,
    OPENROUTER_TOOL_CHOICE,
    OPENROUTER_X_TITLE,
)


class OpenRouterClient:
    def __init__(
        self,
        *,
        api_key: str = OPENROUTER_API_KEY,
        model: str = OPENROUTER_MODEL,
        base_url: str = OPENROUTER_BASE_URL,
        timeout_seconds: float = OPENROUTER_TIMEOUT_SECONDS,
        http_referer: str = OPENROUTER_HTTP_REFERER,
        x_title: str = OPENROUTER_X_TITLE,
        temperature: float = OPENROUTER_TEMPERATURE,
        max_tokens: int = OPENROUTER_MAX_TOKENS,
        default_tool_choice: str = OPENROUTER_TOOL_CHOICE,
    ) -> None:
        self.api_key = (api_key or "").strip()
        self.model = (model or OPENROUTER_MODEL).strip()
        self.base_url = (base_url or OPENROUTER_BASE_URL).rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.http_referer = (http_referer or "").strip()
        self.x_title = (x_title or "").strip()
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.default_tool_choice = (default_tool_choice or "auto").strip() or "auto"

    def _build_headers(self) -> dict[str, str]:
        if not self.api_key:
            raise HTTPException(
                status_code=503,
                detail="Assistant is unavailable: OPENROUTER_API_KEY is not configured.",
            )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if self.http_referer:
            headers["HTTP-Referer"] = self.http_referer
        if self.x_title:
            headers["X-Title"] = self.x_title
        return headers

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = (
                (tool_choice or "").strip() or self.default_tool_choice
            )

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=self._build_headers(),
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise HTTPException(
                status_code=503,
                detail="Assistant request failed while contacting model provider.",
            ) from exc

        if not response.ok:
            detail = f"Assistant model request failed ({response.status_code})."
            try:
                parsed = response.json()
                if isinstance(parsed, dict):
                    provider_message = parsed.get("error") or parsed.get("message")
                    if isinstance(provider_message, dict):
                        provider_message = provider_message.get("message")
                    if isinstance(provider_message, str) and provider_message.strip():
                        detail = (
                            f"{detail} {provider_message.strip()[:180]}"
                        )
            except ValueError:
                pass
            raise HTTPException(status_code=503, detail=detail)

        try:
            parsed_body = response.json()
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail="Assistant model returned an invalid response format.",
            ) from exc

        if not isinstance(parsed_body, dict):
            raise HTTPException(
                status_code=502,
                detail="Assistant model returned an unexpected response payload.",
            )
        return parsed_body
