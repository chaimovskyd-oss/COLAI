"""PresetService — persist and retrieve named Print Color Presets.

Presets are stored in ~/.smart_print_prep/color_presets.json.
The service is purely static; no instance state is required.
"""

import json
import logging
from pathlib import Path

_log = logging.getLogger(__name__)

_STORE_DIR  = Path.home() / ".smart_print_prep"
_STORE_FILE = _STORE_DIR  / "color_presets.json"

# Canonical parameter set with identity values (no adjustment)
_DEFAULTS: dict = {
    "brightness":               0,
    "contrast":                 0,
    "exposure":                 0,
    "saturation":               0,
    "sharpness":                0,
    "gamma":                    1.0,
    "r_level":                  0,
    "g_level":                  0,
    "b_level":                  0,
    "color_balance_shadows":    0,
    "color_balance_midtones":   0,
    "color_balance_highlights": 0,
}


class PresetService:
    """Static helper for loading, saving, and managing named print color presets."""

    # ── Read ──────────────────────────────────────────────────────────────────

    @staticmethod
    def load_all() -> dict[str, dict]:
        """Return all saved presets as {name: values_dict}."""
        return {
            name: payload["values"]
            for name, payload in PresetService.load_all_profiles().items()
        }

    @staticmethod
    def load_all_profiles() -> dict[str, dict]:
        """Return all saved presets with metadata preserved."""
        if not _STORE_FILE.exists():
            return {}
        try:
            with _STORE_FILE.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                normalized: dict[str, dict] = {}
                for name, raw_value in data.items():
                    normalized[name] = PresetService._normalize_profile(name, raw_value)
                return normalized
        except Exception as exc:
            _log.warning("Could not load presets from %s: %s", _STORE_FILE, exc)
        return {}

    @staticmethod
    def list_names() -> list[str]:
        return sorted(PresetService.load_all().keys())

    @staticmethod
    def get(name: str) -> dict | None:
        """Return the values dict for *name*, or None if not found."""
        return PresetService.load_all().get(name)

    @staticmethod
    def get_profile(name: str) -> dict | None:
        return PresetService.load_all_profiles().get(name)

    # ── Write ─────────────────────────────────────────────────────────────────

    @staticmethod
    def save(name: str, values: dict, printer_name: str = "", paper_type: str = "") -> None:
        """Persist a preset under *name* (overwrites if it already exists)."""
        presets = PresetService.load_all_profiles()
        presets[name] = {
            "name": name,
            "printer_name": str(printer_name or ""),
            "paper_type": str(paper_type or ""),
            "values": PresetService._coerce(values),
        }
        PresetService._write(presets)

    @staticmethod
    def delete(name: str) -> None:
        presets = PresetService.load_all()
        if name in presets:
            del presets[name]
            PresetService._write(presets)
            _log.debug("Deleted preset '%s'", name)

    @staticmethod
    def rename(old: str, new: str) -> None:
        presets = PresetService.load_all_profiles()
        if old in presets:
            presets[new] = presets.pop(old)
            presets[new]["name"] = new
            PresetService._write(presets)

    @staticmethod
    def find_best_match(printer_name: str | None, paper_type: str | None = None) -> tuple[str, dict] | None:
        printer_name = str(printer_name or "").strip().lower()
        paper_type = str(paper_type or "").strip().lower()
        if not printer_name:
            return None

        profiles = PresetService.load_all_profiles()
        best_match: tuple[int, str, dict] | None = None
        for name, payload in profiles.items():
            stored_printer = str(payload.get("printer_name", "") or "").strip().lower()
            stored_paper = str(payload.get("paper_type", "") or "").strip().lower()
            if stored_printer != printer_name:
                continue
            score = 1
            if paper_type and stored_paper == paper_type:
                score = 2
            elif stored_paper and stored_paper != paper_type:
                continue
            candidate = (score, name, dict(payload.get("values", {})))
            if best_match is None or candidate[0] > best_match[0]:
                best_match = candidate
        if best_match is None:
            return None
        return best_match[1], best_match[2]

    # ── Defaults ──────────────────────────────────────────────────────────────

    @staticmethod
    def default_values() -> dict:
        """Return a fresh copy of the identity (no-op) preset values."""
        return dict(_DEFAULTS)

    @staticmethod
    def is_identity(values: dict) -> bool:
        """True when *values* are all at their neutral defaults (no visible effect)."""
        for k, default in _DEFAULTS.items():
            v = values.get(k, default)
            if isinstance(default, float):
                if abs(float(v) - default) > 0.01:
                    return False
            elif int(v) != int(default):
                return False
        return True

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _write(presets: dict) -> None:
        try:
            _STORE_DIR.mkdir(parents=True, exist_ok=True)
            with _STORE_FILE.open("w", encoding="utf-8") as f:
                json.dump(presets, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            _log.error("Could not write presets to %s: %s", _STORE_FILE, exc)

    @staticmethod
    def _coerce(values: dict) -> dict:
        """Merge against defaults so every parameter key is always present."""
        merged = dict(_DEFAULTS)
        if isinstance(values, dict):
            for k, default in _DEFAULTS.items():
                if k in values:
                    try:
                        merged[k] = type(default)(values[k])
                    except (TypeError, ValueError):
                        pass  # keep default on bad value
        return merged

    @staticmethod
    def _normalize_profile(name: str, raw_value) -> dict:
        if isinstance(raw_value, dict) and "values" in raw_value:
            return {
                "name": str(raw_value.get("name", name)),
                "printer_name": str(raw_value.get("printer_name", "") or ""),
                "paper_type": str(raw_value.get("paper_type", "") or ""),
                "values": PresetService._coerce(raw_value.get("values", {})),
            }
        return {
            "name": name,
            "printer_name": "",
            "paper_type": "",
            "values": PresetService._coerce(raw_value if isinstance(raw_value, dict) else {}),
        }
