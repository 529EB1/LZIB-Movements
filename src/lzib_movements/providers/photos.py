"""Optional photo lookup abstraction; alerts never depend on photographs."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Photo:
    thumbnail_url: str
    source_url: str
    photographer: str


class PhotoProvider(Protocol):
    async def lookup(self, registration: str) -> Photo | None: ...


class NoPhotoProvider:
    async def lookup(self, registration: str) -> Photo | None:
        return None
