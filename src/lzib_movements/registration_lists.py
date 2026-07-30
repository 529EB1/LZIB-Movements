"""Registration-list loading and normalization."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REGISTRATION = re.compile(r"^[A-Z0-9]{1,3}-?[A-Z0-9]{1,7}$")


def normalize_registration(value: object, *, strict: bool = True) -> str | None:
    if not isinstance(value, str):
        if strict:
            raise ValueError("registration must be a string")
        return None
    normalized = value.strip().upper().replace("–", "-").replace("—", "-")
    normalized = re.sub(r"\s*-\s*", "-", normalized)
    if not normalized or not REGISTRATION.fullmatch(normalized):
        if strict:
            raise ValueError(f"malformed registration: {value!r}")
        return None
    return normalized


def normalize_callsign(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = re.sub(r"[^A-Z0-9]", "", value.upper())
    return normalized or None


@dataclass(frozen=True, slots=True)
class SpecialRegistration:
    registration: str
    livery: str
    notes: str = ""


@dataclass(frozen=True, slots=True)
class RegistrationLists:
    special: dict[str, SpecialRegistration]
    ignored: frozenset[str]

    @classmethod
    def load(cls, special_path: Path, ignored_path: Path) -> "RegistrationLists":
        special_raw = _read_list(special_path)
        ignored_raw = _read_list(ignored_path)
        special: dict[str, SpecialRegistration] = {}
        for index, entry in enumerate(special_raw):
            if not isinstance(entry, dict):
                raise ValueError(f"special entry {index} must be an object")
            registration = normalize_registration(entry.get("registration"))
            livery = entry.get("livery")
            notes = entry.get("notes", "")
            if not isinstance(livery, str) or not livery.strip():
                raise ValueError(f"special entry {index} requires a non-blank livery")
            if not isinstance(notes, str):
                raise ValueError(f"special entry {index} notes must be a string")
            if registration is None:  # normalize_registration(strict=True) guarantees this
                raise ValueError(f"special entry {index} has no registration")
            special[registration] = SpecialRegistration(registration, livery.strip(), notes.strip())
        ignored: set[str] = set()
        for index, entry in enumerate(ignored_raw):
            try:
                registration = normalize_registration(entry)
            except ValueError as error:
                raise ValueError(f"ignored entry {index}: {error}") from error
            if registration is None:  # normalize_registration(strict=True) guarantees this
                raise ValueError(f"ignored entry {index} has no registration")
            ignored.add(registration)
        return cls(special, frozenset(ignored))


def _read_list(path: Path) -> list[Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read valid JSON list from {path}") from error
    if not isinstance(value, list):
        raise ValueError(f"{path} must contain a JSON list")
    return value
