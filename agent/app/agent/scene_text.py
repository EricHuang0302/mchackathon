"""Turn one typed scene report into unconfirmed proposals.

This is the offline-friendly counterpart to the Live audio path: same prompt,
same schema, same allowlist. It exists because speech recognition is the least
reliable link at a noisy scene, and a rescuer must still be able to hand the
Agent what they know. Tool actions are returned, never executed; the user
drives AED and helper dispatch from explicit controls.
"""
from __future__ import annotations

import os
from threading import Lock
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.agent import scene_extraction
from app.agent.scene_extraction import SceneExtraction
from app.api.errors import unavailable


class SceneTextResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    observations: list[tuple[str, bool | str]] = Field(default_factory=list)
    steps: list[dict[str, str]] = Field(default_factory=list)


class SceneTextAnalyzer(Protocol):
    def analyze(self, report: str) -> SceneTextResult: ...


class GeminiSceneTextAnalyzer:
    def __init__(self, model: str):
        self.model = model
        self._client = None
        self._lock = Lock()

    def _client_for_requests(self):
        # The client owns an HTTP connection pool and closes it when collected,
        # so a temporary built inline can be torn down mid-request. Keep one.
        with self._lock:
            if self._client is None:
                from google import genai

                self._client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))
            return self._client

    def analyze(self, report: str) -> SceneTextResult:
        try:
            from google.genai import types
        except ImportError:
            raise unavailable() from None

        try:
            response = self._client_for_requests().models.generate_content(
                model=self.model,
                contents=scene_extraction.extraction_prompt(report),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=SceneExtraction,
                    temperature=0,
                ),
            )
        except Exception as exc:
            # Provider details are intentionally not exposed to the caller or logs.
            raise unavailable() from exc

        parsed = response.parsed
        if isinstance(parsed, SceneExtraction):
            payload = parsed.model_dump(mode="json", exclude_none=True)
        elif isinstance(parsed, dict):
            payload = parsed
        else:
            payload = scene_extraction.payload_from_text(response.text or "")
        if payload is None:
            raise unavailable()

        return SceneTextResult(
            model=self.model,
            observations=scene_extraction.observation_values(payload),
            steps=scene_extraction.plan_steps(payload),
        )


class UnavailableSceneTextAnalyzer:
    def analyze(self, report: str) -> SceneTextResult:
        raise unavailable()


def default_scene_text_analyzer() -> SceneTextAnalyzer:
    model = os.getenv("GEMINI_TEXT_MODEL")
    return GeminiSceneTextAnalyzer(model) if model else UnavailableSceneTextAnalyzer()
