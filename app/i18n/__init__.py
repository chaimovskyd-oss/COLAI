"""app/i18n/__init__.py — Minimal runtime translation engine.

Usage:
    from app.i18n import tr, set_language, current_language

    tr('Import')          → 'ייבוא'  (in Hebrew mode)
    tr('Hello {name}', name='Bob') → formatted string

Language codes:  'en'  |  'he'
"""
from __future__ import annotations

import json
import os
from typing import Dict

# ── Current state ─────────────────────────────────────────────────────────────
_lang: str = 'en'
_strings: Dict[str, str] = {}          # populated by set_language()

# Persistent preference file (next to the package)
_PREF_FILE = os.path.join(os.path.dirname(__file__), 'lang_pref.json')


# ── Public API ─────────────────────────────────────────────────────────────────

def current_language() -> str:
    return _lang


def set_language(lang: str) -> None:
    """Switch active language. 'en' = English, 'he' = Hebrew."""
    global _lang, _strings
    _lang = lang
    if lang == 'he':
        from app.i18n import strings_he
        _strings = dict(strings_he.STRINGS)
    else:
        _strings = {}          # English: fall back to key itself
    _save_preference(lang)


def tr(key: str, **kwargs) -> str:
    """Return the translated string for *key*, formatting with **kwargs."""
    text = _strings.get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return text


def is_rtl() -> bool:
    """True when the active language uses right-to-left layout."""
    return _lang == 'he'


# ── Preference persistence ────────────────────────────────────────────────────

def load_preference() -> str:
    """Read saved language code; return 'en' on any error."""
    try:
        with open(_PREF_FILE, 'r', encoding='utf-8') as f:
            return json.load(f).get('lang', 'en')
    except Exception:
        return 'en'


def _save_preference(lang: str) -> None:
    try:
        with open(_PREF_FILE, 'w', encoding='utf-8') as f:
            json.dump({'lang': lang}, f)
    except Exception:
        pass


# Initialise with saved preference on first import
set_language(load_preference())
