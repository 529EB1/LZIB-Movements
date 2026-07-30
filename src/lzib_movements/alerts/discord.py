"""Safe Discord incoming-webhook delivery."""

import asyncio
import logging
from typing import Any
from urllib.parse import urlsplit

import httpx

LOGGER = logging.getLogger(__name__)


def redact_webhook(value: str) -> str:
    if "/api/webhooks/" not in value:
        return value
    parsed = urlsplit(value)
    return f"{parsed.scheme}://{parsed.netloc}/api/webhooks/[REDACTED]"


class DiscordWebhook:
    def __init__(self, url: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._url = url
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5))
        self._owned = client is None

    async def close(self) -> None:
        if self._owned:
            await self._client.aclose()

    async def send(self, embed: dict[str, Any]) -> None:
        for attempt in range(3):
            try:
                response = await self._client.post(self._url, json={"embeds": [embed]})
            except httpx.HTTPError as error:
                if attempt == 2:
                    raise RuntimeError(
                        "Discord webhook transport failure (URL redacted)"
                    ) from error
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code in {200, 204}:
                return
            if (response.status_code == 429 or response.status_code >= 500) and attempt < 2:
                retry = min(float(response.headers.get("Retry-After", 2**attempt)), 10)
                await asyncio.sleep(max(retry, 1))
                continue
            raise RuntimeError(
                f"Discord webhook returned HTTP {response.status_code} (URL redacted)"
            )
        raise RuntimeError("Discord webhook delivery retries exhausted (URL redacted)")
