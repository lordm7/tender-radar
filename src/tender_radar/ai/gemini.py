"""Google Gemini implementation of the provider interface (free tier).

We ask Gemini for JSON that follows our Pydantic schema, then validate it
ourselves. Gemini errors are translated into our own AIError / RateLimited, so
the rest of the app never depends on Google's SDK.
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel, ValidationError

from tender_radar.ai.provider import AIError, RateLimited

T = TypeVar("T", bound=BaseModel)
REQUEST_TIMEOUT_MS = 60_000  # give up on one AI call after 60 seconds


class GeminiProvider:
    def __init__(self, api_key: str, model: str):
        self._api_key = api_key
        self._model = model
        self._client = None  # created on first use, so importing needs no key

    def _get_client(self):
        if self._client is None:
            from google import genai
            from google.genai import types

            # Without a time limit an overloaded model can hang the app forever.
            self._client = genai.Client(
                api_key=self._api_key, http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS)
            )
        return self._client

    def generate_json(self, prompt: str, schema: type[T]) -> T:
        from google.genai import errors

        try:
            response = self._get_client().models.generate_content(
                model=self._model,
                contents=prompt,
                config={"response_mime_type": "application/json", "response_schema": schema},
            )
        except errors.APIError as exc:
            if exc.code == 429:
                raise RateLimited(str(exc)) from exc
            raise AIError(str(exc)) from exc
        except Exception as exc:  # network problems, timeouts
            raise AIError(str(exc)) from exc

        try:
            return schema.model_validate_json(response.text or "")
        except ValidationError as exc:
            raise AIError(f"AI returned JSON that does not match {schema.__name__}: {exc}") from exc
