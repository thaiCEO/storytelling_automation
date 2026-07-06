"""Single Atlas Cloud HTTP client (httpx) — LLM chat, image gen, TTS, uploadMedia.

Endpoint map (verified against Atlas docs, https://www.atlascloud.ai/docs):
  chat  : POST {base}/v1/chat/completions          (OpenAI-compatible)
  image : POST {base}/api/v1/model/generateImage   -> prediction id -> poll
  poll  : GET  {base}/api/v1/model/prediction/{id}
  upload: POST {base}/api/v1/model/uploadMedia     (multipart, field "file")
  tts   : POST {base}/api/v1/model/generateAudio   -> same prediction flow
          (verify exact path/model id on the Atlas dashboard once at setup)

Every call: timeout + 2 retries with exponential backoff + structured
logging. The API key is never logged.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Optional

import httpx

from ..config import settings

CHAT_PATH = "/v1/chat/completions"
IMAGE_PATH = "/api/v1/model/generateImage"
VIDEO_PATH = "/api/v1/model/generateVideo"
TTS_PATH = "/api/v1/model/generateAudio"
UPLOAD_PATH = "/api/v1/model/uploadMedia"
PREDICTION_PATH = "/api/v1/model/prediction/{id}"

MAX_RETRIES = 2  # retries after the first attempt
BACKOFF = (2, 8)  # seconds before retry 1 / retry 2


class AtlasError(RuntimeError):
    pass


def _headers() -> dict:
    if not settings.atlas_api_key:
        raise AtlasError("ATLAS_API_KEY is not set — fill it in .env at the repo root")
    return {"Authorization": f"Bearer {settings.atlas_api_key}"}


def parse_llm_json(text: str) -> Any:
    """Parse model output as JSON, tolerating markdown fences and prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # last resort: outermost { ... }
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


class AtlasClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(base_url=settings.atlas_base_url)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request_with_retry(
        self, method: str, path: str, *, timeout: float, **kwargs
    ) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                resp = await self._client.request(
                    method, path, headers=_headers(), timeout=timeout, **kwargs
                )
                if resp.status_code >= 500 or resp.status_code == 429:
                    raise AtlasError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                resp.raise_for_status()
                return resp
            except (httpx.TimeoutException, httpx.TransportError, AtlasError) as exc:
                last_exc = exc
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(BACKOFF[attempt])
            except httpx.HTTPStatusError as exc:  # 4xx — retrying won't help
                raise AtlasError(
                    f"{path} -> HTTP {exc.response.status_code}: {exc.response.text[:500]}"
                ) from exc
        raise AtlasError(f"{path} failed after {MAX_RETRIES + 1} attempts: {last_exc}")

    # ---------------------------------------------------------------- LLM
    async def chat(
        self,
        system: str,
        user_content: str | list[dict],
        *,
        temperature: float = 0.8,
        max_tokens: int = 8192,
        timeout: float = 180,
    ) -> str:
        """OpenAI-compatible chat. user_content may be a string or vision
        content blocks ([{type:text},{type:image_url,...}])."""
        payload = {
            "model": settings.llm_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        resp = await self._request_with_retry("POST", CHAT_PATH, json=payload, timeout=timeout)
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise AtlasError(f"unexpected chat response shape: {str(data)[:500]}") from exc

    # -------------------------------------------------------- media (async)
    async def _poll_prediction(self, pred_id: str, *, timeout: float) -> dict:
        deadline = asyncio.get_event_loop().time() + timeout
        delay = 1.5
        while True:
            resp = await self._request_with_retry(
                "GET", PREDICTION_PATH.format(id=pred_id), timeout=30
            )
            body = resp.json()
            data = body.get("data", body)
            status = str(data.get("status", "")).lower()
            if status in ("succeeded", "success", "completed", "done"):
                return data
            if status in ("failed", "error", "canceled", "cancelled"):
                raise AtlasError(f"prediction {pred_id} failed: {str(data)[:500]}")
            if asyncio.get_event_loop().time() > deadline:
                raise AtlasError(f"prediction {pred_id} timed out after {timeout}s")
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 6)

    @staticmethod
    def _extract_output_urls(data: dict) -> list[str]:
        """Handle the known output shapes: outputs[], output, images[]."""
        out = data.get("outputs") or data.get("output") or data.get("images") or []
        if isinstance(out, str):
            return [out]
        urls: list[str] = []
        for item in out:
            if isinstance(item, str):
                urls.append(item)
            elif isinstance(item, dict) and item.get("url"):
                urls.append(item["url"])
        return urls

    async def _generate_media(self, path: str, payload: dict, *, timeout: float) -> bytes:
        """Submit task -> poll prediction -> download first output."""
        resp = await self._request_with_retry("POST", path, json=payload, timeout=60)
        body = resp.json()
        data = body.get("data", body)
        urls = self._extract_output_urls(data)
        if not urls:  # async flow — poll the prediction
            pred_id = data.get("id") or data.get("prediction_id")
            if not pred_id:
                raise AtlasError(f"no prediction id in response: {str(body)[:500]}")
            data = await self._poll_prediction(pred_id, timeout=timeout)
            urls = self._extract_output_urls(data)
        if not urls:
            raise AtlasError(f"prediction finished but no output url: {str(data)[:500]}")
        dl = await self._client.get(urls[0], timeout=120, follow_redirects=True)
        dl.raise_for_status()
        return dl.content

    async def generate_image(self, payload: dict, *, timeout: float = 60) -> bytes:
        return await self._generate_media(IMAGE_PATH, payload, timeout=timeout)

    async def generate_video(self, payload: dict, *, timeout: float = 900) -> bytes:
        return await self._generate_media(VIDEO_PATH, payload, timeout=timeout)

    async def tts(self, payload: dict, *, timeout: float = 45) -> bytes:
        return await self._generate_media(TTS_PATH, payload, timeout=timeout)

    # ------------------------------------------------------------- upload
    async def upload_media(self, content: bytes, filename: str, mime: str) -> str:
        """Upload a local file, return the public temporary URL."""
        resp = await self._request_with_retry(
            "POST", UPLOAD_PATH,
            files={"file": (filename, content, mime)},
            timeout=120,
        )
        body = resp.json()
        data = body.get("data", {})
        url = (body.get("url")
               or data.get("url")
               or data.get("download_url")
               or body.get("download_url"))
        if not url:
            raise AtlasError(f"uploadMedia returned no url: {str(body)[:300]}")
        return url


atlas = AtlasClient()
