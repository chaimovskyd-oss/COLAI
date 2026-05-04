from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton, QToolButton, QCheckBox, QWidget


LANG_EN = "en"
LANG_HE = "he"


HEBREW: dict[str, str] = {
    "Smart Image Editor / Color Lab": "עורך תמונות חכם / מעבדת צבע",
    "Smart Image Editor": "עורך תמונות חכם",
    "Color Lab | Print Safe | Embeddable Engine": "מעבדת צבע | בטוח להדפסה | מנוע להטמעה",
    "File": "קובץ",
    "Edit": "עריכה",
    "View": "תצוגה",
    "Language": "שפה",
    "English": "English",
    "Hebrew": "עברית",
    "Tips / Improve Photo": "טיפים / שיפור תמונה",
    "AI Tools": "כלי AI",
    "Presets": "פריסטים",
    "Open": "פתח",
    "Save Copy": "שמור עותק",
    "Quick Save": "שמירה מהירה",
    "Quick Save Copy": "שמור עותק מהיר",
    "Exit": "יציאה",
    "Undo": "בטל",
    "Redo": "בצע שוב",
    "Reset": "אפס",
    "Reset All": "אפס הכל",
    "Delete": "מחק",
    "Edited": "ערוך",
    "Before": "לפני",
    "Split": "מפוצל",
    "Side by Side": "זה לצד זה",
    "Open Tips Panel": "פתח פאנל טיפים",
    "Smart Auto Fix": "תיקון חכם אוטומטי",
    "Detect Faces": "זהה פנים",
    "Import LUT": "ייבא LUT",
    "Toggle AI Tools Panel": "הצג/הסתר פאנל כלי AI",
    "Cartoon": "קריקטורה",
    "Sketch": "סקיצה",
    "Coloring Page": "דף צביעה",
    "Posterize": "פוסטריזציה",
    "Anime Style (AI)": "סגנון אנימה (AI)",
    "Clear AI Effect": "נקה אפקט AI",
    "Preset Intensity": "עוצמת פריסט",
    "Apply Preset": "החל פריסט",
    "Histogram": "היסטוגרמה",
    "Tips": "טיפים",
    "History": "היסטוריה",
    "Mouse wheel: zoom": "גלגל עכבר: זום",
    "No image loaded": "לא נטענה תמונה",
    "Open an image to start": "פתח תמונה כדי להתחיל",
    "Clipping: -": "חיתוך: -",
    "Clipping": "חיתוך",
    "shadows": "צללים",
    "highlights": "אזורים בהירים",
    "Custom": "מותאם אישית",
    "Segment": "סגמנטציה",
    "fallback": "גיבוי",
    "AI detected": "AI זיהה",
    "face(s)": "פנים",
    "Preset selected": "פריסט נבחר",
    "Active Adjustments": "התאמות פעילות",
    "Timeline": "ציר זמן",
    "No active adjustments": "אין התאמות פעילות",
    "No actions yet": "עדיין אין פעולות",
    "on": "פעיל",
    "off": "כבוי",
    "custom": "מותאם",
    "Smart Photo Tips": "טיפים חכמים לתמונה",
    "Apply Suggested Fix": "החל תיקון מוצע",
    "Problem": "בעיה",
    "How to identify": "איך לזהות",
    "Recommended correction order": "סדר תיקון מומלץ",
    "Warnings": "אזהרות",
    "Composition": "קומפוזיציה",
    "Faces": "פנים",
    "Photo is too dark": "התמונה כהה מדי",
    "Photo is too bright": "התמונה בהירה מדי",
    "Flat photo / low depth": "תמונה שטוחה / מעט עומק",
    "Contrast is too strong": "הקונטרסט חזק מדי",
    "Photo is too red": "התמונה אדומה מדי",
    "Photo is too blue or cold": "התמונה כחולה או קרה מדי",
    "Colors are weak or faded": "הצבעים חלשים או דהויים",
    "Colors are too strong": "הצבעים חזקים מדי",
    "Faces are too dark": "הפנים כהות מדי",
    "Skin is too red": "העור אדום מדי",
    "Faces are soft or blurry": "הפנים רכות או מטושטשות",
    "Photo is too soft": "התמונה רכה מדי",
    "Photo is noisy or grainy": "התמונה רועשת או גרעינית",
    "Photo is too small for print": "התמונה קטנה מדי להדפסה",
    "Subject is not centered": "נושא התמונה אינו ממורכז",
    "Photo is crooked": "התמונה עקומה",
    "Emphasize the subject": "הדגש את הנושא",
    "Add depth / bokeh feel": "הוסף עומק / תחושת בוקה",
    "Cinematic / professional look": "מראה קולנועי / מקצועי",
    "Print comes out too dark": "ההדפסה יוצאת כהה מדי",
    "Skin prints too red": "העור מודפס אדום מדי",
    "Colors print too weak": "הצבעים מודפסים חלש מדי",
    "Prepare for canvas": "הכנה לקנבס",
    "Prepare for sublimation": "הכנה לסובלימציה",
    "The image lacks light and important subject details are hidden in shadows.": "לתמונה חסר אור ופרטים חשובים בנושא מוסתרים בצללים.",
    "Bright regions are too dominant and may lose detail.": "האזורים הבהירים דומיננטיים מדי ועלולים לאבד פרטים.",
    "The image has weak separation between dark, midtone, and bright areas.": "יש הפרדה חלשה בין אזורים כהים, גווני ביניים ואזורים בהירים.",
    "The image feels harsh, with blocked shadows or clipped highlights.": "התמונה מרגישה קשה, עם צללים חסומים או אזורים בהירים חתוכים.",
    "The image is too warm or skin tones are too red/orange.": "התמונה חמה מדי או שגווני העור אדומים/כתומים מדי.",
    "The image feels cold and lacks natural warmth.": "התמונה מרגישה קרה וחסרה חמימות טבעית.",
    "The photo lacks color energy.": "לתמונה חסרה חיות צבע.",
    "Colors look unnatural or neon.": "הצבעים נראים לא טבעיים או זרחניים.",
    "People are underexposed compared with the rest of the image.": "אנשים בתמונה כהים מדי ביחס לשאר התמונה.",
    "Skin tones are red/orange and need a softer correction.": "גווני העור אדומים/כתומים ודורשים תיקון עדין יותר.",
    "Facial details lack crispness.": "פרטי הפנים אינם חדים מספיק.",
    "Overall detail lacks crispness.": "הפרטים הכלליים אינם חדים מספיק.",
    "Noise is visible, usually in shadows or high ISO photos.": "רעש נראה לעין, לרוב בצללים או בתמונות ISO גבוה.",
    "The image resolution may be too low for high-quality print.": "ייתכן שרזולוציית התמונה נמוכה מדי להדפסה איכותית.",
    "The important subject placement feels accidental.": "מיקום הנושא החשוב מרגיש מקרי.",
    "The horizon or vertical lines are tilted.": "קו האופק או הקווים האנכיים מוטים.",
    "The subject needs more attention than the background.": "הנושא צריך לקבל יותר תשומת לב מהרקע.",
    "The image would benefit from stronger subject-background separation.": "התמונה תרוויח מהפרדה חזקה יותר בין הנושא לרקע.",
    "The image needs a stylized, polished finish.": "התמונה צריכה גימור מעוצב ומלוטש.",
    "The screen preview looks fine but printed output loses shadow detail.": "התצוגה על המסך נראית טוב, אבל בהדפסה פרטי הצללים הולכים לאיבוד.",
    "Printed skin tones become too warm or red.": "גווני העור בהדפסה נהיים חמים או אדומים מדי.",
    "Printed output looks less vivid than screen preview.": "הפלט המודפס נראה פחות חי מהתצוגה על המסך.",
    "Canvas needs softer contrast, protected highlights, and enough shadow lift.": "קנבס צריך קונטרסט רך יותר, הגנת אזורים בהירים והרמת צללים מספקת.",
    "Sublimation often needs stronger color and a mirror-output warning.": "סובלימציה לרוב דורשת צבע חזק יותר ואזהרה לגבי פלט מראה.",
    "Quick": "מהיר",
    "Light": "אור",
    "Color": "צבע",
    "Portrait": "פורטרט",
    "Effects": "אפקטים",
    "Print": "הדפסה",
    "Advanced": "מתקדם",
    "Fast fixes, auto cleanup, and recent tools.": "תיקונים מהירים, ניקוי אוטומטי וכלים אחרונים.",
    "Fast fixes, recent tools and one-click corrections.": "תיקונים מהירים, כלים אחרונים ותיקונים בלחיצה אחת.",
    "Exposure, tone recovery, contrast, and gamma.": "חשיפה, שחזור טונים, קונטרסט וגאמה.",
    "Shape exposure, shadow detail and tonal depth.": "עיצוב חשיפה, פרטי צללים ועומק טונאלי.",
    "White balance, saturation, HSL, LUTs, and color targeting.": "איזון לבן, רוויה, HSL, LUT ובחירת צבע יעד.",
    "Adjust color temperature, saturation and HSL channels.": "כוונון טמפרטורת צבע, רוויה וערוצי HSL.",
    "Face, skin, and subject-aware enhancement.": "שיפור פנים, עור ונושא התמונה.",
    "Face, skin and subject-aware AI controls.": "בקרות AI לפנים, עור ונושא התמונה.",
    "Blur, vignette, grain, and creative finish.": "טשטוש, וינייט, גרעיניות וגימור יצירתי.",
    "Blur, vignette, grain and visual focus tools.": "כלי טשטוש, וינייט, גרעיניות ומיקוד חזותי.",
    "Print-safe tonal controls and output preparation.": "בקרות טון בטוחות להדפסה והכנת פלט.",
    "Print-safe corrections and output compensation.": "תיקונים בטוחים להדפסה ופיצוי פלט.",
    "Detail, sharpening, denoise, and high-end processing.": "פרטים, חידוד, ניקוי רעש ועיבוד מתקדם.",
    "Detail, noise reduction and deeper controls.": "פרטים, הפחתת רעש ובקרות עמוקות יותר.",
    "Auto Enhance": "שיפור אוטומטי",
    "Auto Levels": "איזון רמות אוטומטי",
    "Auto Contrast": "קונטרסט אוטומטי",
    "Auto Color": "צבע אוטומטי",
    "Print Safe": "בטוח להדפסה",
    "Reset Detail": "אפס פרטים",
    "Smart Auto": "אוטומטי חכם",
    "Recently Used": "בשימוש לאחרונה",
    "Quick Fixes": "תיקונים מהירים",
    "Tone": "טון",
    "Basic Color": "צבע בסיסי",
    "Dynamic HSL": "HSL דינמי",
    "Target Color": "צבע יעד",
    "Face": "פנים",
    "Subject": "נושא",
    "Blur": "טשטוש",
    "Finish": "גימור",
    "Print Setup": "הגדרות הדפסה",
    "Detail": "פרטים",
    "Upscale": "הגדלה",
    "AI Styles": "סגנונות AI",
    "Artistic Effects": "אפקטים אמנותיים",
    "Controls": "פקדים",
    "Strength": "עוצמה",
    "Edge Thickness": "עובי קצה",
    "Apply": "החל",
    "Clear Effect": "נקה אפקט",
    "Coming soon": "בקרוב",
    "·soon·": "·בקרוב·",
    "Make this effect active (non-destructive)": "הפוך אפקט זה לפעיל (לא הרסני)",
    "Remove the active effect": "הסר את האפקט הפעיל",
    "Exposure": "חשיפה",
    "Exposure x100": "חשיפה x100",
    "Brightness": "בהירות",
    "Contrast": "קונטרסט",
    "Highlights": "אזורים בהירים",
    "Shadows": "צללים",
    "Whites": "לבנים",
    "Blacks": "שחורים",
    "Gamma": "גאמה",
    "Temperature": "טמפרטורה",
    "Tint": "גוון",
    "Saturation": "רוויה",
    "Vibrance": "חיות צבע",
    "Black and White": "שחור לבן",
    "Print Mode": "מצב הדפסה",
    "LUT Amount": "עוצמת LUT",
    "Pick Color": "בחר צבע",
    "+ Add Sample": "+ הוסף דגימה",
    "- Remove Sample": "- הסר דגימה",
    "Range Width": "רוחב טווח",
    "Softness": "רכות",
    "Hue Shift": "הסטת גוון",
    "Hue": "גוון",
    "Luminance": "בהיקות",
    "Face Brighten": "הבהרת פנים",
    "Face Restore": "שחזור פנים",
    "Skin Tone Protection": "הגנת גוון עור",
    "Reduce Red Skin": "הפחתת אדמומיות עור",
    "Subject Enhance": "שיפור נושא",
    "Gaussian Blur": "טשטוש גאוסי",
    "Motion Blur": "טשטוש תנועה",
    "Motion Angle": "זווית תנועה",
    "Radial Blur": "טשטוש רדיאלי",
    "Background Blur": "טשטוש רקע",
    "Darken Background": "הכהיית רקע",
    "Vignette": "וינייט",
    "Vignette Feather": "רכות וינייט",
    "Vignette Midpoint": "נקודת אמצע וינייט",
    "Grain": "גרעיניות",
    "Grain Size": "גודל גרעיניות",
    "Boost Shadows": "חיזוק צללים",
    "Protect Highlights": "הגנת אזורים בהירים",
    "Print Sharpness": "חידוד להדפסה",
    "Sharpness": "חידוד",
    "Noise Reduction": "הפחתת רעש",
    "Color Noise": "רעש צבע",
    "Texture": "טקסטורה",
    "Clarity": "צלילות",
    "Upscale Factor": "מקדם הגדלה",
    "Upscale Strength": "עוצמת הגדלה",
    "Anime Style": "סגנון אנימה",
    "Soft Cartoon": "קריקטורה רכה",
    "Comic Style": "סגנון קומיקס",
    "Smooth colours with bold outlines": "צבעים חלקים עם קווי מתאר חזקים",
    "Pencil drawing on white paper": "ציור עיפרון על נייר לבן",
    "Clean black outlines for hand-colouring": "קווי מתאר שחורים נקיים לצביעה ידנית",
    "Reduce colour levels for a poster look": "הפחתת רמות צבע למראה פוסטר",
    "AnimeGAN neural style transfer": "העברת סגנון עצבית AnimeGAN",
    "Red": "אדום",
    "Orange": "כתום",
    "Yellow": "צהוב",
    "Green": "ירוק",
    "Aqua": "אקווה",
    "Blue": "כחול",
    "Purple": "סגול",
    "Magenta": "מג'נטה",
    "No recent tools yet": "עדיין אין כלים אחרונים",
    "Show Range & Softness ▼": "הצג טווח ורכות ▼",
    "Hide Range & Softness ▲": "הסתר טווח ורכות ▲",
    "Shows which parts of the image this color slider affects.": "מציג אילו אזורים בתמונה מושפעים מסליידר הצבע הזה.",
    "Open image": "פתח תמונה",
    "Image not found": "התמונה לא נמצאה",
    "Could not find": "לא ניתן למצוא",
    "Open failed": "פתיחה נכשלה",
    "No image": "אין תמונה",
    "Open an image before importing a LUT.": "פתח תמונה לפני ייבוא LUT.",
    "Open an image before applying a preset.": "פתח תמונה לפני החלת פריסט.",
    "Open an image before applying a suggested fix.": "פתח תמונה לפני החלת תיקון מוצע.",
    "Open an image before applying an effect.": "פתח תמונה לפני החלת אפקט.",
    "Pick a target color from the preview": "בחר צבע יעד מתוך התצוגה המקדימה",
    "Tips panel focused": "פאנל הטיפים בפוקוס",
    "No image to save.": "אין תמונה לשמירה.",
    "Save copy": "שמור עותק",
    "Export failed": "הייצוא נכשל",
    "Saved": "נשמר",
    "Saved successfully": "נשמר בהצלחה",
    "Previewing affected color": "תצוגת אזורי צבע מושפעים",
    "Previewing targeted color range": "תצוגת טווח צבע יעד",
}


_REVERSE: dict[str, str] = {value: key for key, value in HEBREW.items()}


class Translator:
    def __init__(self, language: str = LANG_EN):
        self.language = language if language in {LANG_EN, LANG_HE} else LANG_EN

    def set_language(self, language: str) -> None:
        self.language = language if language in {LANG_EN, LANG_HE} else LANG_EN

    def text(self, source: str) -> str:
        return translate_text(source, self.language)

    @property
    def is_rtl(self) -> bool:
        return self.language == LANG_HE


def translate_text(text: str, language: str) -> str:
    if "\n" in text:
        return "\n".join(translate_text(part, language) for part in text.split("\n"))
    if not text or language == LANG_EN and text not in _REVERSE:
        return _REVERSE.get(text, text) if language == LANG_EN else text
    source = _REVERSE.get(text, text)
    if language == LANG_EN:
        return source
    if source in HEBREW:
        return HEBREW[source]
    for prefix in ("▶ ", "▼ "):
        if source.startswith(prefix):
            return prefix + translate_text(source[len(prefix):], language)
    if ": " in source:
        head, tail = source.split(": ", 1)
        translated_head = translate_text(head, language)
        translated_tail = translate_text(tail, language)
        if translated_head != head or translated_tail != tail:
            return f"{translated_head}: {translated_tail}"
    parts = source.split(" ", 1)
    if len(parts) == 2 and len(parts[0]) <= 2:
        translated_tail = translate_text(parts[1], language)
        if translated_tail != parts[1]:
            return f"{parts[0]} {translated_tail}"
    return source


def translate_widget_tree(root: QWidget, translator: Translator) -> None:
    for widget in root.findChildren(QWidget):
        _translate_widget(widget, translator)
    _translate_widget(root, translator)


def _translate_widget(widget: QWidget, translator: Translator) -> None:
    if isinstance(widget, (QLabel, QPushButton, QToolButton, QCheckBox)):
        current = widget.text()
        translated = translator.text(current)
        if translated != current:
            widget.setText(translated)
    tooltip = widget.toolTip()
    if tooltip:
        translated_tooltip = translator.text(tooltip)
        if translated_tooltip != tooltip:
            widget.setToolTip(translated_tooltip)
