אני רוצה להוסיף לתוכנת Smart Image Editor מודול חדש בשם:

Smart Tips / Improve Photo Guide

המטרה:
לבנות בתוך התוכנה מדריך חכם למשתמשים מתחילים ועובדים חדשים, שמסביר לפי סיטואציה איך לשפר תמונה, באילו כלים להשתמש, ובאיזה סדר.

חשוב:
זה לא AI אוטומטי בשלב ראשון, אלא מדריך מובנה + תשתית עתידית לכפתור Apply Suggested Fix.

---

מבנה UI רצוי:

בתפריט העליון הוסף:

Tips / Improve Photo

בלחיצה ייפתח חלון או פאנל צד בשם:

Smart Photo Tips

הפאנל יכלול קטגוריות:

1. תאורה
2. צבעים
3. פנים ואנשים
4. חדות ואיכות
5. קומפוזיציה
6. אפקטים
7. הדפסה

בכל קטגוריה יהיו סיטואציות נפוצות.

---

מבנה נתונים מומלץ:

צור קובץ:

image_editor/data/photo_tips.json

או לחלופין:

image_editor/core/photo_tips.py

כל טיפ צריך להיות במבנה כזה:

{
  "id": "dark_photo",
  "category": "תאורה",
  "title": "תמונה חשוכה מדי",
  "symptoms": [
    "התמונה נראית כהה",
    "הפנים לא ברורות",
    "ההיסטוגרמה נוטה שמאלה"
  ],
  "recommended_steps": [
    {
      "tool": "Exposure",
      "action": "העלה בעדינות",
      "suggested_range": "+0.2 עד +0.8"
    },
    {
      "tool": "Shadows",
      "action": "פתח אזורים כהים",
      "suggested_range": "+10 עד +40"
    },
    {
      "tool": "Brightness",
      "action": "הוסף רק אם עדיין כהה",
      "suggested_range": "+5 עד +20"
    },
    {
      "tool": "Contrast",
      "action": "הוסף מעט אם התמונה נהיית שטוחה",
      "suggested_range": "+5 עד +15"
    }
  ],
  "warnings": [
    "לא לשרוף אזורים בהירים",
    "לא לפתוח צללים עד שהתמונה נראית אפורה"
  ],
  "future_auto_fix": {
    "enabled": false,
    "params": {
      "exposure": 0.35,
      "shadows": 25,
      "contrast": 8
    }
  }
}

---

נא לבנות מערכת גמישה כך שניתן יהיה להוסיף טיפים חדשים בלי לשנות את ה־UI.

---

רשימת טיפים התחלתית:

קטגוריה: תאורה

1. תמונה חשוכה מדי
כלים:
- Exposure ↑
- Shadows ↑
- Brightness ↑ בעדינות
- Contrast ↑ מעט אם נהיה שטוח

2. תמונה בהירה מדי
כלים:
- Exposure ↓
- Highlights ↓
- Whites ↓
- Contrast ↑ מעט אם צריך

3. תמונה שטוחה / חסרת עומק
כלים:
- Contrast ↑
- Blacks ↓
- Whites ↑
- Clarity ↑ בעדינות

4. קונטרסט חזק מדי
כלים:
- Contrast ↓
- Shadows ↑
- Highlights ↓
- Blacks ↑ מעט

---

קטגוריה: צבעים

5. תמונה אדומה מדי
כלים:
- Temperature ↓
- Tint לכיוון ירוק
- Saturation ↓ מעט
- HSL Red/Orange Saturation ↓

6. תמונה כחולה או קרה מדי
כלים:
- Temperature ↑
- Tint לכיוון מג׳נטה מעט
- Vibrance ↑ בעדינות

7. צבעים חלשים / דהויים
כלים:
- Vibrance ↑
- Saturation ↑ מעט
- Contrast ↑ מעט

8. צבעים חזקים מדי / זרחניים
כלים:
- Saturation ↓
- Vibrance ↓
- HSL לפי צבע בעייתי

---

קטגוריה: פנים ואנשים

9. פנים כהות
כלים:
- Shadows ↑
- Exposure ↑ מעט
- בעתיד Face Enhance

10. עור אדום מדי
כלים:
- HSL Orange Saturation ↓
- HSL Red Saturation ↓
- Temperature ↓ מעט
- Reduce Red Skin preset אם קיים

11. פנים רכות או מטושטשות
כלים:
- Sharpen ↑ בעדינות
- Texture ↑ מעט
- Clarity ↑ מעט
- בעתיד Face Restoration

---

קטגוריה: חדות ואיכות

12. תמונה רכה מדי
כלים:
- Sharpen ↑
- Texture ↑
- Clarity ↑ מעט

13. תמונה מרעישה / גרעינית
כלים:
- Noise Reduction ↑
- Color Noise Reduction ↑
- Sharpen ↓ מעט

14. תמונה קטנה מדי להדפסה
כלים:
- Upscale בעתיד
- כרגע להציג אזהרה שאין מספיק רזולוציה

---

קטגוריה: קומפוזיציה

15. תמונה לא ממורכזת
כלים:
- Crop
- Grid overlay
- Rule of thirds

16. תמונה עקומה
כלים:
- Straighten
- Rotate

---

קטגוריה: אפקטים

17. הבלטת נושא
כלים:
- Vignette ↓
- Contrast ↑ מעט
- Background Blur בעתיד

18. אפקט עומק / Bokeh
כלים:
- Background Blur בעתיד
- Radial Blur עדין
- Lens Blur בעתיד

19. מראה קולנועי / מקצועי
כלים:
- LUT / Preset
- Vignette
- Contrast
- Temperature

---

קטגוריה: הדפסה

20. תמונה יוצאת כהה בהדפסה
כלים:
- Exposure ↑ מעט
- Shadows ↑
- Saturation ↑ מעט
- Print Safe preset

21. עור אדום מדי בהדפסה
כלים:
- Reduce Red Skin
- HSL Orange/Red Saturation ↓
- Temperature ↓ מעט

22. צבעים חלשים בהדפסה
כלים:
- Saturation ↑ מעט
- Contrast ↑ מעט
- Print Boost preset

23. הכנה לקנבס
כלים:
- Canvas Print Boost
- Soft Contrast
- Print-safe Sharpening
- Protect Highlights

24. הכנה לסובלימציה
כלים:
- Sublimation Boost
- Saturation Compensation
- Mirror warning
- Brightness compensation

---

דרישות UI:

1. בפאנל הטיפים תהיה רשימת קטגוריות.
2. לחיצה על קטגוריה תציג את הטיפים שלה.
3. לחיצה על טיפ תציג:
   - מה הבעיה
   - איך לזהות אותה
   - שלבי תיקון מומלצים
   - אזהרות
   - כפתור עתידי: Apply Suggested Fix
4. בשלב ראשון הכפתור Apply Suggested Fix יכול להיות disabled או ניסיוני.
5. אם יש כבר מערכת presets או adjustment params, הכפתור העתידי צריך לדעת להחיל params מוגדרים מראש.

---

דרישות קוד:

1. אל תערבב את הטיפים ישירות בתוך קוד ה־UI.
2. צור data model נפרד.
3. צור service בשם PhotoTipsService:
   - load_tips()
   - get_categories()
   - get_tips_by_category(category)
   - get_tip_by_id(id)
   - get_suggested_params(id)
4. צור widget/panel בשם SmartTipsPanel.
5. הקוד צריך להיות מודולרי כדי שנוכל להשתמש באותו מדריך גם בתוכנת הקולאז׳ וגם ב־Smart Print Prep.

---

תשתית עתידית:

הכן מקום ל:
- זיהוי אוטומטי של בעיות בתמונה לפי histogram
- זיהוי פנים כהות
- זיהוי צבע אדום/צהוב מוגזם בעור
- הצגת המלצה אוטומטית:
  “נראה שהתמונה חשוכה. לפתוח מדריך תיקון?”
- Apply Suggested Fix אוטומטי

---

חשוב מאוד:
לא להרוס קוד קיים.
לבנות את המודול בנפרד ולחבר אותו בעדינות לתפריט העליון.
אם קיימת כבר מערכת תפריטים, להשתמש בה.
אם לא, להוסיף בצורה מינימלית.
בסיום להציג לי:
1. אילו קבצים נוספו
2. אילו קבצים שונו
3. איך להפעיל
4. איך להוסיף טיפ חדש