# Smart Image Editor / Color Lab — Skeleton

שלד ראשוני לכלי עריכת תמונות מודולרי, מודרני ולא הרסני.

## מה יש כאן

- Standalone app להרצה ובדיקות
- Core engine בסיסי לעריכה לא הרסנית
- UI מודרני כהה עם צבעים ייחודיים
- Smart Tips / Improve Photo Guide
- Presets בסיסיים
- Integration API לשילוב עתידי בקולאז׳ וב־Smart Print Prep

## התקנה

```bash
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt
python standalone.py
```

## מבנה כללי

```text
smart_image_editor/
├─ core/          מנוע עריכה, state, presets, pipeline
├─ ui/            ממשק PySide6
├─ integration/   API לשילוב בתוכנות אחרות
├─ data/          tips ו-presets
├─ ai/            מקום למודלים עתידיים
└─ assets/        themes/resources
```

## הערות

זהו שלד בסיסי שנועד להתרחב בשלבים. כרגע פעולות העריכה בסיסיות ומיועדות להדגמת מבנה נכון, לא כמנוע צבע סופי.
