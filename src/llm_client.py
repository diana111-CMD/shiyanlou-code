"""LLM 客户端封装 — 统一调用 OpenAI 兼容接口，支持 Chain of Thought 推理。"""

from __future__ import annotations

import json
import uuid
from typing import Any, Generator

from openai import OpenAI

from src.config import settings
from src.logger import setup_logger

logger = setup_logger("llm_client", "LLM")


class LLMClient:
    """封装 LLM 对话，支持结构化 JSON 输出和思维链。"""

    def __init__(self) -> None:
        self.client = OpenAI(
            api_key=settings.llm.api_key,
            base_url=settings.llm.base_url,
        )

    # ── 基础对话 ──

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """普通对话，返回文本。"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        kwargs: dict[str, Any] = {
            "model": settings.llm.model,
            "messages": messages,
            "temperature": temperature or settings.llm.temperature,
            "max_tokens": max_tokens or settings.llm.max_tokens,
        }
        # 如果模型支持 thinking 模式（如 Claude），可以传入
        if settings.llm.thinking_budget > 0:
            kwargs["extra_body"] = {
                "thinking": {
                    "type": "enabled",
                    "budget_tokens": settings.llm.thinking_budget,
                }
            }

        resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    # ── 结构化 JSON 输出 ──

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        *,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """要求模型输出符合指定 JSON Schema 的结构化数据。"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        kwargs: dict[str, Any] = {
            "model": settings.llm.model,
            "messages": messages,
            "temperature": temperature or 0.2,
            "max_tokens": settings.llm.max_tokens,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "output",
                    "schema": schema,
                },
            },
        }
        resp = self.client.chat.completions.create(**kwargs)
        raw = resp.choices[0].message.content or "{}"
        logger.debug(f"JSON response length: {len(raw)} chars")
        return json.loads(raw)

    # ── 流式输出 ──

    def chat_stream(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> Generator[str, None, None]:
        """流式对话，逐 chunk yield 文本。"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        stream = self.client.chat.completions.create(
            model=settings.llm.model,
            messages=messages,
            temperature=settings.llm.temperature,
            max_tokens=settings.llm.max_tokens,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
