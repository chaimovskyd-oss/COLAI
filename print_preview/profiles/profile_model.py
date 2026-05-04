from __future__ import annotations

import base64
from dataclasses import asdict, dataclass

from ..models.print_settings import PrintSettings


@dataclass(frozen=True)
class PrintProfile:
    name: str
    settings: dict

    @classmethod
    def from_settings(cls, name: str, settings: PrintSettings) -> "PrintProfile":
        payload = asdict(settings)
        payload["native_devmode_bytes"] = cls._encode_bytes(payload.get("native_devmode_bytes", b""))
        payload["active_print_profile_name"] = name
        return cls(name=name, settings=payload)

    def to_json_dict(self) -> dict:
        return {"name": self.name, **self.settings}

    @classmethod
    def from_json_dict(cls, data: dict) -> "PrintProfile":
        if not isinstance(data, dict):
            raise TypeError("Profile payload must be a dict.")
        name = str(data.get("name", "")).strip()
        payload = dict(data)
        payload.pop("name", None)
        payload["native_devmode_bytes"] = cls._decode_bytes(payload.get("native_devmode_bytes", ""))
        payload["active_print_profile_name"] = name
        return cls(name=name, settings=payload)

    @staticmethod
    def _encode_bytes(value: bytes | str | None) -> str:
        raw = value if isinstance(value, bytes) else b""
        if not raw:
            return ""
        return base64.b64encode(raw).decode("ascii")

    @staticmethod
    def _decode_bytes(value: str | bytes | None) -> bytes:
        if not value:
            return b""
        if isinstance(value, bytes):
            return value
        try:
            return base64.b64decode(value.encode("ascii"))
        except Exception:
            return b""
