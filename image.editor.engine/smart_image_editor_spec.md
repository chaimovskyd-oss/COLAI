# אפיון מלא — Smart Image Editor / Color Lab

## 1. מטרת המערכת

המטרה היא לבנות כלי עריכת תמונות עצמאי, מודולרי ולא הרסני, שיכול לרוץ גם כ־standalone לצורך בדיקות ופיתוח, וגם להשתלב בתוך תוכנות אחרות כמו:

- תוכנת הקולאז׳ים
- Smart Print Prep
- כלי הכנה למוצרים מודפסים
- כלים עתידיים לעיבוד תמונות, הדפסה, קטלוגים או עיצוב

הכלי לא נועד להיות Photoshop מלא, אלא שילוב חכם של:

- Lightroom קטן ונוח
- כלי תיקון צבע ותאורה
- כלי הכנה להדפסה
- כלי שיפור תמונות אוטומטי
- תשתית עתידית ל־AI, upscale, face restoration ו־background blur

היעד המרכזי: לתת למשתמשים מתחילים חוויית עריכה פשוטה וברורה, ולמשתמשים מתקדמים שליטה עמוקה יותר — בלי לסבך את הממשק.

---

## 2. עקרונות יסוד

### 2.1 עריכה לא הרסנית

התמונה המקורית לעולם לא משתנה.

כל עריכה נשמרת כסט פרמטרים, לדוגמה:

```json
{
  "exposure": 0.25,
  "contrast": 12,
  "temperature": -4,
  "saturation": 8,
  "vignette_amount": -20,
  "preset": "Canvas Soft Boost"
}
```

המנוע מחשב preview/export לפי הפרמטרים בלבד.

### 2.2 הפרדה בין מנוע לממשק

המערכת חייבת להיות מחולקת לשלושה חלקים:

1. Core Engine — מנוע עיבוד תמונה
2. Standalone App — תוכנת בדיקה עצמאית
3. Integration API — שכבת שילוב בתוכנות אחרות

אסור שהלוגיקה של העריכה תהיה תלויה ישירות ב־UI.

### 2.3 התאמה להדפסה

הכלי צריך להיות שימושי במיוחד לעסקי הדפסה:

- תיקון תמונות כהות לפני הדפסה
- פריסטים לפי סוג חומר / מדפסת / מוצר
- שמירה על גווני עור
- מניעת שריפת לבנים
- הכנה לסובלימציה, קנבס, נייר מבריק, נייר מט ועוד

### 2.4 פשטות לפני עומס

בגרסה הראשונה לא בונים Photoshop מלא.

לא להתחיל עם:

- שכבות מלאות
- RAW מתקדם
- Healing brush
- Generative AI
- מסכות ידניות מורכבות
- Liquify

כן לבנות תשתית שתוכל להכיל את הדברים האלה בעתיד.

---

## 3. מבנה מערכת מומלץ

```text
image_editor/
│
├─ core/
│  ├─ image_state.py
│  ├─ adjustment_pipeline.py
│  ├─ adjustments_basic.py
│  ├─ adjustments_light.py
│  ├─ adjustments_color.py
│  ├─ adjustments_detail.py
│  ├─ adjustments_blur.py
│  ├─ adjustments_vignette.py
│  ├─ adjustments_print.py
│  ├─ presets.py
│  ├─ histogram.py
│  ├─ export_service.py
│  └─ cache_manager.py
│
├─ ai/
│  ├─ segmentation_service.py
│  ├─ face_detection_service.py
│  ├─ background_blur_service.py
│  ├─ upscaler_service.py
│  └─ face_restore_service.py
│
├─ ui/
│  ├─ editor_window.py
│  ├─ preview_canvas.py
│  ├─ adjustment_panel.py
│  ├─ histogram_widget.py
│  ├─ preset_browser.py
│  ├─ before_after_view.py
│  ├─ crop_tool.py
│  ├─ checklist_panel.py
│  └─ settings_dialog.py
│
├─ integration/
│  ├─ editor_api.py
│  ├─ embedded_editor_dialog.py
│  └─ result_contract.py
│
├─ standalone.py
└─ README.md
```

---

## 4. Core Engine

### 4.1 ImageState

אובייקט מרכזי שמחזיק:

- נתיב תמונה מקורית
- גודל מקורי
- preview cache
- פרמטרי עריכה
- preset פעיל
- היסטוריית Undo/Redo
- metadata בסיסי
- מידע על export אחרון

### 4.2 Adjustment Pipeline

המנוע מפעיל את כל העריכות לפי סדר קבוע וברור.

סדר מומלץ:

1. Load image
2. Orientation / EXIF fix
3. Crop / straighten
4. White balance
5. Exposure / tone
6. Contrast / highlights / shadows
7. Color / HSL
8. Local / AI effects
9. Blur / vignette / grain
10. Sharpen / noise reduction
11. Print correction
12. Output transform

### 4.3 Preview מול Export

יש להפריד בין:

- Preview מהיר ברזולוציה נמוכה/בינונית
- Export איכותי ברזולוציה מלאה

Preview צריך להיות מהיר מאוד, גם אם פחות מדויק.

Export צריך להיות איכותי, גם אם לוקח יותר זמן.

---

## 5. כלים בסיסיים למתחילים

פאנל פשוט ונקי בשם Basic.

### 5.1 כלים

- Auto Enhance
- Brightness
- Exposure
- Contrast
- Warm / Cool
- Saturation
- Vibrance
- Sharpness
- Black & White
- Reset

### 5.2 דרישות UX

- סליידרים גדולים וברורים
- כפתור reset ליד כל פרמטר
- כפתור reset all
- ערכים מספריים ליד כל סליידר
- דאבל קליק על סליידר מחזיר לברירת מחדל

---

## 6. Light / תאורה

פאנל מתקדם יותר לשליטה באור.

### 6.1 כלים

- Exposure
- Brightness
- Contrast
- Highlights
- Shadows
- Whites
- Blacks
- Gamma
- Tone Curve בסיסית
- Auto Levels
- Auto Contrast

### 6.2 הערות חשובות

- Exposure אינו זהה ל־Brightness.
- Highlights צריך לטפל בעיקר באזורים בהירים.
- Shadows צריך לפתוח אזורים כהים בלי להרוס את כל התמונה.
- Whites/Blacks משמשים לקביעת נקודות קצה.

---

## 7. Color / צבע

פאנל צבע מתקדם בהשראת Lightroom ו־Darktable.

### 7.1 כלים כלליים

- Temperature
- Tint
- Saturation
- Vibrance
- Color Balance בסיסי
- Selective Color בסיסי

### 7.2 HSL

לכל צבע:

- Hue
- Saturation
- Luminance

צבעים:

- Red
- Orange
- Yellow
- Green
- Aqua
- Blue
- Purple
- Magenta

### 7.3 Color Equalizer עתידי/מתקדם

כלי גרפי עם נקודות שליטה לצבעים:

- Hue curve
- Saturation curve
- Brightness/Luminance curve

הכלי צריך להיות מבודד כווידג׳ט עצמאי כדי שניתן יהיה לשפר אותו בהמשך.

---

## 8. Detail / חדות וניקוי

### 8.1 Sharpen

- Amount
- Radius
- Detail
- Threshold

### 8.2 Noise Reduction

- Luminance noise reduction
- Color noise reduction
- Detail preservation

### 8.3 Texture / Clarity

- Texture
- Clarity
- Local Contrast

### 8.4 הערה חשובה להדפסה

לא להגזים בחדות. צריך להוסיף preset בטוח להדפסה שלא מייצר קצוות מוגזמים או artifacts.

---

## 9. Blur מתקדם

מודול Blur נפרד ולא רק סליידר אחד.

### 9.1 סוגי Blur

- Gaussian Blur
- Lens Blur
- Motion Blur
- Radial Blur
- Background Blur / Bokeh Blur עתידי

### 9.2 Gaussian Blur

פרמטרים:

- Radius
- Strength
- Preview quality

### 9.3 Motion Blur

פרמטרים:

- Strength
- Direction / angle
- Distance

### 9.4 Radial Blur

לשימוש בטשטוש מהקצה למרכז או אפקט תנועה.

פרמטרים:

- Center point
- Radius
- Strength
- Falloff
- Direction:
  - outward
  - inward
  - spin
  - zoom

### 9.5 Lens Blur

פרמטרים:

- Amount
- Radius
- Blade simulation בסיסי בעתיד
- Highlight bloom אופציונלי

---

## 10. Vignette

מודול חובה.

### 10.1 פרמטרים

- Amount
- Midpoint
- Feather
- Roundness
- Highlights protection
- Center point

### 10.2 סוגים

- Dark Vignette
- Bright Vignette
- Soft Portrait Vignette
- Product Focus Vignette

### 10.3 דרישות

- לא לשרוף אזורים בהירים.
- לא להשחיר פינות בצורה אגרסיבית מדי כברירת מחדל.
- לאפשר reset מהיר.

---

## 11. Grain / Film Effect

### 11.1 פרמטרים

- Amount
- Size
- Roughness
- Monochrome / Color grain

### 11.2 שימושים

- תמונות משפחתיות
- סגנון וינטג׳
- ריכוך תמונות דיגיטליות חדות מדי

---

## 12. Crop / Straighten / Transform

### 12.1 Crop

יחסי גובה־רוחב מובנים:

- Free
- Original
- 1:1
- 3:2
- 4:3
- 4:5
- 5:7
- 16:9
- Custom

### 12.2 Straighten

- Rotate fine adjustment
- Grid overlay
- Auto straighten עתידי

### 12.3 Transform בסיסי

- Rotate 90°
- Flip horizontal
- Flip vertical

---

## 13. Presets

### 13.1 מערכת Presets

כל preset הוא אוסף פרמטרים שנשמר כ־JSON.

צריך לאפשר:

- Apply preset
- Save current as preset
- Rename preset
- Delete preset
- Export preset
- Import preset
- Favorite presets

### 13.2 Preset Intensity

פיצ׳ר חשוב מאוד:

- Apply preset
- Amount: 0–100%

כך המשתמש יכול להחיל פריסט בעדינות.

### 13.3 פריסטים התחלתיים

- Auto Clean
- Portrait Soft
- Family Photo Clean
- Product Bright
- Warm Indoor Fix
- Phone Photo Fix
- Underexposed Fix
- Black & White Classic
- Vintage Soft
- Canvas Soft Boost
- Sublimation Strong
- Photo Paper Glossy
- Matte Paper Soft
- Skin Tone Safe
- Old Photo Restore Basic

---

## 14. Print Correction / התאמה להדפסה

זה אחד החלקים הכי חשובים ומבדלים במערכת.

### 14.1 מצבי הדפסה

- General Print Safe
- Canvas Print Boost
- Sublimation Boost
- Glossy Photo Paper
- Matte Photo Paper
- Mitsubishi D80 Correction
- Epson Inkjet Correction
- Laser Transfer Basic

### 14.2 כלים

- Boost shadows for print
- Reduce red skin
- Protect highlights
- Soft contrast for canvas
- Saturation compensation
- Sublimation mirror warning
- Print-safe sharpness

### 14.3 פרופילי הדפסה עתידיים

בהמשך, לאפשר למשתמש ליצור פרופיל:

```json
{
  "profile_name": "D80 Glossy Family Photos",
  "brightness": 4,
  "contrast": -2,
  "saturation": 6,
  "skin_red_reduction": 8,
  "sharpen": 10
}
```

---

## 15. Histogram

### 15.1 תצוגה

- RGB histogram
- Luminance histogram
- Clipping warning:
  - שריפת לבן
  - איבוד פרטים בשחור

### 15.2 שימושים

- Auto Levels
- Auto Contrast
- זיהוי תמונה כהה מדי
- זיהוי תמונה שטוחה מדי

---

## 16. Before / After

חובה לחוויית משתמש.

### 16.1 מצבים

- Toggle before/after
- Hold key to view original
- Split view
- Side by side
- Compare presets by hover

### 16.2 דרישות

- לא לאבד zoom/pan בזמן השוואה.
- המעבר צריך להיות מיידי.

---

## 17. Undo / Redo

### 17.1 דרישות

- Undo לכל שינוי סליידר משמעותי
- Redo
- Reset current section
- Reset all
- History panel אופציונלי

### 17.2 שמירת היסטוריה

לא צריך לשמור כל פיקסל, רק snapshots של פרמטרים.

---

## 18. Cache / Performance

### 18.1 Preview Cache

- שמירת preview מוקטן
- invalidation רק כשהפרמטרים משתנים
- cache לפי גודל תצוגה

### 18.2 ביצועים

- שימוש ב־NumPy/OpenCV
- throttling לסליידרים
- preview מהיר בזמן גרירה
- quality גבוהה אחרי שחרור סליידר

### 18.3 הגדרות Cache

- Clear cache
- Max cache size
- Use disk cache / memory cache
- Preview resolution

---

## 19. AI / Smart Tools

פיצ׳רים מתקדמים בשלבים עתידיים.

### 19.1 Face Detection

שימושים:

- שמירה על גווני עור
- אזהרה אם פנים נחתכות
- התאמה חכמה לקולאז׳
- הגדלת חשיבות תמונות עם אנשים
- brightening faces

### 19.2 Person Segmentation

שימושים:

- Background blur
- Bokeh effect
- Subject enhancement
- Darken background
- Separate subject/background adjustments

### 19.3 Background Blur / Bokeh

שלבים:

1. זיהוי אדם/נושא
2. יצירת mask
3. feather edges
4. blur לרקע בלבד
5. שליטה בעוצמה

פרמטרים:

- Blur amount
- Edge feather
- Subject protection
- Depth simulation strength

### 19.4 Smart Auto Fix

המערכת תזהה בעיות ותציע תיקון:

- התמונה חשוכה
- התמונה שטוחה
- הפנים כהות
- יותר מדי אדום בעור
- saturation נמוך מדי
- highlights שרופים
- רעש גבוה

### 19.5 Face Restoration

פיצ׳ר עתידי.

כלים אפשריים:

- GFPGAN
- CodeFormer

מצבים:

- Natural
- Balanced
- Strong

חובה להוסיף אזהרה: תיקון פנים חזק מדי עלול לשנות מראה טבעי.

### 19.6 Upscaler

פיצ׳ר עתידי.

כלי עיקרי:

- Real-ESRGAN

אפשרויות:

- 2x
- 4x
- Face enhance on/off
- Tile mode למחשבים חלשים

שימושים:

- תמונות וואטסאפ
- תמונות קטנות להדפסה
- תמונות ישנות
- הכנה לקנבס/בלוקים/הגדלות

---

## 20. LUTs / Color Grading

### 20.1 תמיכה ב־LUT

- Import .cube
- Apply LUT
- LUT intensity 0–100%

### 20.2 קטגוריות LUT

- Cinematic
- Warm
- Cool
- Vintage
- Clean Product
- Portrait
- Print Safe

---

## 21. Batch Processing

פיצ׳ר עתידי קרוב.

### 21.1 יכולות

- החלת preset על תיקייה שלמה
- Auto Enhance לכל התמונות
- Resize
- Convert format
- Export with suffix
- שמירת עותקים בלי לדרוס מקור

### 21.2 שימושים עסקיים

- תיקון סט תמונות לקוח
- הכנה לקולאז׳
- הכנה להדפסה
- תיקון תמונות מוצרים לאתר

---

## 22. Integration API

המטרה היא שכל תוכנה תוכל לפתוח את העורך ולקבל בחזרה תוצאה.

### 22.1 API בסיסי

```python
result = open_image_editor(
    image_path="path/to/image.jpg",
    initial_params=None,
    mode="standalone_or_embedded",
    output_mode="params_and_preview"
)
```

### 22.2 Result Contract

העורך מחזיר:

```python
{
    "accepted": True,
    "source_path": "...",
    "edited_preview_path": "...",
    "exported_path": "...",
    "edit_params": {...},
    "preset_name": "Portrait Soft"
}
```

### 22.3 שילוב בקולאז׳

- עריכת תמונה מתוך תא
- שמירת פרמטרים לכל תמונה בנפרד
- לא להרוס את crop/fill של הקולאז׳
- אפשרות Auto Enhance לכל התמונות בקולאז׳

### 22.4 שילוב ב־Smart Print Prep

- עריכת תמונה לפני הכנסה לעמוד
- פריסטים לפי מדפסת/חומר
- batch correction לפני הדפסה
- שמירת תיקוני הדפסה בפרופיל

---

## 23. UI מומלץ

### 23.1 מבנה חלון

```text
Top Bar:
Open | Save Copy | Export | Before/After | Reset | Settings

Left Panel:
Presets / History / Histogram

Center:
Image Preview Canvas
Zoom / Pan / Split View

Right Panel:
Basic
Light
Color
Detail
Blur
Vignette
Crop
Print
AI Tools

Bottom Bar:
Zoom | Image Size | Color Space | Warnings
```

### 23.2 עקרונות עיצוב

- מודרני ונקי
- סליידרים רחבים
- פאנלים מתקפלים
- תמיכה בעברית/אנגלית
- מצב כהה/בהיר
- קיצורי מקלדת
- tooltips קצרים וברורים

---

## 24. Settings

### 24.1 General

- Language
- Theme
- Accent color
- Default export folder
- Confirm before overwrite

### 24.2 Performance

- Preview quality
- Max preview size
- Use GPU if available בעתיד
- Cache size
- Clear cache

### 24.3 Editing

- Default preset
- Auto apply print-safe correction
- Preserve metadata
- Default color space

### 24.4 AI Models עתידי

- Model folder
- Enable/disable AI tools
- Upscaler model path
- Face restoration model path
- Segmentation model path

---

## 25. פורמטים

### 25.1 קלט

גרסה ראשונה:

- JPG
- PNG
- TIFF
- WEBP אופציונלי

עתידי:

- RAW
- HEIC

### 25.2 פלט

- JPG quality control
- PNG
- TIFF
- WEBP אופציונלי

### 25.3 Metadata

- לשמר EXIF כברירת מחדל אם אפשר
- לתקן orientation לפי EXIF
- לא לשנות מקור

---

## 26. ספריות מומלצות

### 26.1 חובה

- PySide6 / PyQt6 — ממשק
- OpenCV — עיבוד תמונה
- Pillow — טעינה/שמירה
- NumPy — חישובים

### 26.2 אופציונלי

- scikit-image — עיבוד מתקדם
- rawpy — RAW בעתיד
- onnxruntime — מודלים מקומיים
- realesrgan — upscaler
- gfpgan / codeformer — face restoration
- mediapipe / YOLO segmentation — זיהוי אנשים/פנים

---

## 27. גרסאות פיתוח מומלצות

## v1 — בסיס חזק ושימושי

- Standalone app
- Load image
- Preview canvas
- Basic sliders
- Light sliders
- Color sliders בסיסיים
- Sharpness בסיסי
- Vignette
- Gaussian blur
- Crop בסיסי
- Presets
- Before/After
- Save copy
- Integration API בסיסי

## v1.5 — כלי עריכה עשיר

- HSL מלא
- Histogram
- Auto levels
- Auto contrast
- Grain
- Motion blur
- Radial blur
- Preset intensity
- Undo/Redo מלא
- Cache settings
- Print presets בסיסיים

## v2 — הדפסה וקולאז׳

- Print Correction panel
- פרופילי מדפסות/חומרים
- שילוב עם Smart Print Prep
- שילוב עם תוכנת הקולאז׳
- Auto Enhance לכל התמונות
- אזהרות הדפסה

## v3 — AI חכם

- Face detection
- Person segmentation
- Background blur / bokeh
- Subject enhancement
- Skin tone protection מתקדם
- Smart Auto Fix

## v4 — שיפור תמונה מתקדם

- Real-ESRGAN upscale
- Face restoration
- Batch processing
- LUT import
- RAW / HEIC אופציונלי

---

# 28. צ׳ק־ליסט ביצוע

סמן ידנית סטטוס לכל סעיף:

סטטוסים מומלצים:

- ⬜ לא בוצע
- 🟡 בוצע חלקית / דורש שיפור
- ✅ בוצע

---

## 28.1 ארכיטקטורה

| סעיף | סטטוס | הערות |
|---|---|---|
| יצירת תיקיית image_editor | ⬜ |  |
| הפרדה בין core / ui / integration / ai | ⬜ |  |
| ImageState בסיסי | ⬜ |  |
| Adjustment Pipeline | ⬜ |  |
| Preview מול Export נפרדים | ⬜ |  |
| עריכה לא הרסנית | ⬜ |  |
| שמירת edit_params כ־JSON | ⬜ |  |
| API לשילוב חיצוני | ⬜ |  |

## 28.2 Standalone App

| סעיף | סטטוס | הערות |
|---|---|---|
| חלון עצמאי | ⬜ |  |
| טעינת תמונה | ⬜ |  |
| תצוגת preview | ⬜ |  |
| Zoom / Pan | ⬜ |  |
| Save Copy | ⬜ |  |
| Export | ⬜ |  |
| Reset All | ⬜ |  |
| תמיכה בעברית/אנגלית | ⬜ |  |

## 28.3 Basic Tools

| סעיף | סטטוס | הערות |
|---|---|---|
| Auto Enhance | ⬜ |  |
| Brightness | ⬜ |  |
| Exposure | ⬜ |  |
| Contrast | ⬜ |  |
| Warm / Cool | ⬜ |  |
| Saturation | ⬜ |  |
| Vibrance | ⬜ |  |
| Sharpness בסיסי | ⬜ |  |
| Black & White | ⬜ |  |

## 28.4 Light Tools

| סעיף | סטטוס | הערות |
|---|---|---|
| Highlights | ⬜ |  |
| Shadows | ⬜ |  |
| Whites | ⬜ |  |
| Blacks | ⬜ |  |
| Gamma | ⬜ |  |
| Tone Curve בסיסית | ⬜ |  |
| Auto Levels | ⬜ |  |
| Auto Contrast | ⬜ |  |

## 28.5 Color Tools

| סעיף | סטטוס | הערות |
|---|---|---|
| Temperature | ⬜ |  |
| Tint | ⬜ |  |
| Saturation מתקדם | ⬜ |  |
| Vibrance מתקדם | ⬜ |  |
| Color Balance | ⬜ |  |
| Selective Color בסיסי | ⬜ |  |
| HSL Red | ⬜ |  |
| HSL Orange | ⬜ |  |
| HSL Yellow | ⬜ |  |
| HSL Green | ⬜ |  |
| HSL Aqua | ⬜ |  |
| HSL Blue | ⬜ |  |
| HSL Purple | ⬜ |  |
| HSL Magenta | ⬜ |  |
| Color Equalizer גרפי | ⬜ |  |

## 28.6 Detail Tools

| סעיף | סטטוס | הערות |
|---|---|---|
| Sharpen Amount | ⬜ |  |
| Sharpen Radius | ⬜ |  |
| Sharpen Detail | ⬜ |  |
| Noise Reduction | ⬜ |  |
| Color Noise Reduction | ⬜ |  |
| Texture | ⬜ |  |
| Clarity | ⬜ |  |
| Local Contrast | ⬜ |  |

## 28.7 Blur / Vignette / Grain

| סעיף | סטטוס | הערות |
|---|---|---|
| Gaussian Blur | ⬜ |  |
| Motion Blur | ⬜ |  |
| Radial Blur | ⬜ |  |
| Lens Blur | ⬜ |  |
| Background Blur תשתיתי | ⬜ |  |
| Vignette Amount | ⬜ |  |
| Vignette Feather | ⬜ |  |
| Vignette Midpoint | ⬜ |  |
| Vignette Roundness | ⬜ |  |
| Bright Vignette | ⬜ |  |
| Grain Amount | ⬜ |  |
| Grain Size | ⬜ |  |

## 28.8 Crop / Transform

| סעיף | סטטוס | הערות |
|---|---|---|
| Crop Free | ⬜ |  |
| Crop ratios | ⬜ |  |
| Straighten | ⬜ |  |
| Rotate 90° | ⬜ |  |
| Flip horizontal | ⬜ |  |
| Flip vertical | ⬜ |  |
| Grid overlay | ⬜ |  |

## 28.9 Presets

| סעיף | סטטוס | הערות |
|---|---|---|
| Apply preset | ⬜ |  |
| Save preset | ⬜ |  |
| Delete preset | ⬜ |  |
| Import preset | ⬜ |  |
| Export preset | ⬜ |  |
| Favorite presets | ⬜ |  |
| Preset intensity slider | ⬜ |  |
| Presets התחלתיים | ⬜ |  |

## 28.10 Print Correction

| סעיף | סטטוס | הערות |
|---|---|---|
| General Print Safe | ⬜ |  |
| Canvas Print Boost | ⬜ |  |
| Sublimation Boost | ⬜ |  |
| Glossy Photo Paper | ⬜ |  |
| Matte Photo Paper | ⬜ |  |
| Mitsubishi D80 Correction | ⬜ |  |
| Reduce Red Skin | ⬜ |  |
| Protect Highlights | ⬜ |  |
| Boost Shadows for Print | ⬜ |  |
| Print-safe sharpness | ⬜ |  |
| פרופילי הדפסה מותאמים | ⬜ |  |

## 28.11 UX

| סעיף | סטטוס | הערות |
|---|---|---|
| Before/After toggle | ⬜ |  |
| Split View | ⬜ |  |
| Side by Side | ⬜ |  |
| Compare preset on hover | ⬜ |  |
| Undo | ⬜ |  |
| Redo | ⬜ |  |
| History Panel | ⬜ |  |
| Histogram | ⬜ |  |
| Clipping warnings | ⬜ |  |
| Tooltips | ⬜ |  |
| Keyboard shortcuts | ⬜ |  |

## 28.12 AI עתידי

| סעיף | סטטוס | הערות |
|---|---|---|
| Face Detection | ⬜ |  |
| Person Segmentation | ⬜ |  |
| Background Blur / Bokeh | ⬜ |  |
| Subject Enhancement | ⬜ |  |
| Skin Tone Protection מתקדם | ⬜ |  |
| Smart Auto Fix | ⬜ |  |
| Real-ESRGAN Upscaler | ⬜ |  |
| Face Restoration | ⬜ |  |
| Batch AI correction | ⬜ |  |

## 28.13 Integration

| סעיף | סטטוס | הערות |
|---|---|---|
| open_image_editor API | ⬜ |  |
| Result Contract | ⬜ |  |
| Embedded dialog | ⬜ |  |
| שילוב בקולאז׳ | ⬜ |  |
| שמירת עריכה לכל תמונה בקולאז׳ | ⬜ |  |
| שילוב ב־Smart Print Prep | ⬜ |  |
| Auto Enhance לכל התמונות | ⬜ |  |
| Batch export | ⬜ |  |

---

# 29. Adjustment Behavior & Safe Ranges (מוכן ליישום בקודקס)

הגדרה אחידה לכל כלי:
- UI Range: טווח הסליידר
- Safe Range: טווח שימוש מומלץ כברירת מחדל
- Default: ערך התחלתי
- Core Logic: לוגיקה כללית (לא קוד מדויק)
- Guardrails: מה אסור שיקרה
- Print Notes: התאמות להדפסה
- Test: איך לוודא שהמימוש טוב
- Fallback: אם לא בטוח — אפשר להיעזר ב־Darktable כהשראה להתנהגות

---

## Exposure
- UI: -2.0 → +2.0
- Safe: -1.0 → +1.2
- Default: 0
- Core Logic: שינוי gain גלובלי במרחב לינארי (עדיף לפני gamma)
- Guardrails: לא לשרוף highlights מהר מדי
- Print: נטייה קלה ל+0.1–0.2
- Test: שמיים לא נשרפים, פנים לא "מתפוצצות"
- Fallback: Darktable exposure module

## Brightness
- UI: -100 → +100
- Safe: -40 → +40
- Default: 0
- Core Logic: shift עדין במידטונים (לא scaling)
- Guardrails: לא לשנות קצוות (whites/blacks)
- Print: שימוש עדין בלבד
- Test: blacks נשארים שחורים, whites לבנים

## Contrast
- UI: -100 → +100
- Safe: -35 → +35
- Default: 0
- Core Logic: S-curve סביב midpoint
- Guardrails: מניעת clipping בקצוות
- Print: להעדיף עדין
- Test: עור שומר פרטים
- Fallback: Darktable tone curve / contrast

## Highlights
- UI: -100 → +100
- Safe: -60 → +40
- Default: 0
- Core Logic: דחיסת טווח בהיר
- Guardrails: לא ליצור halo
- Print: חשוב מאוד
- Test: עננים חוזרים לפרטים

## Shadows
- UI: -100 → +100
- Safe: -40 → +60
- Default: 0
- Core Logic: הרמת אזורים כהים
- Guardrails: לא להפוך לשטוח
- Print: +10–20 מומלץ
- Test: אזורים כהים נפתחים בלי רעש מוגזם

## Whites / Blacks
- UI: -100 → +100
- Safe: -30 → +30
- Core Logic: קביעת נקודות קצה
- Guardrails: clipping control
- Test: histogram לא נחתך

## Temperature / Tint
- Temp UI: -100 → +100
- Tint UI: -50 → +50
- Core Logic: white balance shift
- Guardrails: לא צבעים לא טבעיים
- Print: חשוב לתיקון תאורה

## Vibrance
- UI: -100 → +100
- Safe: -30 → +40
- Core Logic: הגברת צבעים חלשים בלבד
- Guardrails: שמירה על עור
- Test: עור לא נהיה כתום

## Saturation
- UI: -100 → +100
- Safe: -40 → +35
- Core Logic: scale גלובלי
- Guardrails: למנוע neon
- Print: להיזהר

## HSL
- UI: -100 → +100 לכל פרמטר
- Safe: -40 → +40
- Core Logic: channel-wise adjustments
- Guardrails: לא לפגוע בעור (בעיקר Orange)

## Sharpen
- Amount: 0–100 (Safe 0–40)
- Radius: 0.5–2.0
- Core Logic: unsharp mask
- Guardrails: למנוע halos
- Print: פחות חדות
- Test: קצוות לא זוהרים

## Noise Reduction
- Luminance: 0–100 (Safe 0–40)
- Core Logic: smoothing מבוקר
- Guardrails: לא למחוק פרטים

## Clarity / Texture
- UI: -100 → +100
- Safe: -30 → +30
- Core Logic: local contrast
- Guardrails: עור לא מלוכלך

## Vignette
- Amount: -100 → +100 (Safe -40 → +30)
- Feather: 0–100
- Core Logic: radial gradient
- Guardrails: לא קצוות שחורים מדי

## Blur (Gaussian)
- Radius: 0–50 (Safe 0–15)
- Core Logic: gaussian convolution
- Guardrails: לא להרוס פרטים מרכזיים

## Motion / Radial Blur
- Strength: 0–100 (Safe 0–40)
- Core Logic: directional / radial convolution

## Grain
- Amount: 0–100 (Safe 0–30)
- Core Logic: noise overlay
- Guardrails: לא דיגיטלי מדי

---

# 30. סיכום החלטה

המערכת תיבנה קודם ככלי standalone עם מנוע נקי, ורק לאחר שהוא יציב תחובר לתוכנות האחרות.

היעד לגרסה הראשונה הוא לא לבנות Photoshop, אלא לבנות עורך תמונות מודרני, מהיר, נוח, לא הרסני, עם יתרון ברור לעולם ההדפסה.

החזון הרחב:

Smart Image Editor יהיה מודול העריכה המרכזי לכל התוכנות העתידיות — קולאז׳ים, הכנה להדפסה, מוצרים, שיפור תמונות, תיקוני צבע, upscale, ושיפור אוטומטי חכם.

