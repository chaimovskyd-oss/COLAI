from __future__ import annotations

import json
from pathlib import Path

from ..models.print_settings import PrintSettings
from .profile_model import PrintProfile


class PrintProfileManager:
    """Persistent storage for print-preview profiles."""

    STORE_DIR = Path.home() / ".smart_print_prep"
    STORE_FILE = STORE_DIR / "print_profiles.json"

    @classmethod
    def list_profiles(cls) -> list[PrintProfile]:
        return sorted(cls._load_all().values(), key=lambda profile: profile.name.lower())

    @classmethod
    def list_names(cls) -> list[str]:
        return [profile.name for profile in cls.list_profiles()]

    @classmethod
    def get_profile(cls, name: str) -> PrintProfile | None:
        return cls._load_all().get(str(name or "").strip())

    @classmethod
    def save_profile(cls, profile: PrintProfile) -> None:
        profiles = cls._load_all()
        profiles[profile.name] = profile
        cls._write_all(profiles)

    @classmethod
    def save_from_settings(cls, name: str, settings: PrintSettings) -> PrintProfile:
        profile = PrintProfile.from_settings(name, settings)
        cls.save_profile(profile)
        return profile

    @classmethod
    def delete_profile(cls, name: str) -> None:
        profiles = cls._load_all()
        if name in profiles:
            del profiles[name]
            cls._write_all(profiles)

    @classmethod
    def _load_all(cls) -> dict[str, PrintProfile]:
        if not cls.STORE_FILE.exists():
            return {}
        try:
            data = json.loads(cls.STORE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

        profiles: dict[str, PrintProfile] = {}
        if isinstance(data, list):
            iterable = data
        elif isinstance(data, dict):
            iterable = [{"name": name, **payload} for name, payload in data.items() if isinstance(payload, dict)]
        else:
            iterable = []

        for entry in iterable:
            try:
                profile = PrintProfile.from_json_dict(entry)
            except Exception:
                continue
            if profile.name:
                profiles[profile.name] = profile
        return profiles

    @classmethod
    def _write_all(cls, profiles: dict[str, PrintProfile]) -> None:
        cls.STORE_DIR.mkdir(parents=True, exist_ok=True)
        payload = [profile.to_json_dict() for profile in sorted(profiles.values(), key=lambda item: item.name.lower())]
        cls.STORE_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
