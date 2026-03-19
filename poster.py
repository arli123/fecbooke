"""
פוסטר אוטומטי לפייסבוק - עו"ד איריס מורנו
קורא פוסטים מ-Google Docs, מפרסם בפייסבוק בטפטוף קבוע.
כשנגמרים הפוסטים — מייצר 60 חדשים עם Claude ומוסיף למסמך.
"""

import os
import json
import time
import schedule
import requests
import anthropic
from datetime import datetime
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build

try:
    from plyer import notification
    NOTIFICATIONS_AVAILABLE = True
except ImportError:
    NOTIFICATIONS_AVAILABLE = False

load_dotenv()

# ─── הגדרות ───────────────────────────────────────────────────────────────────
SCOPES = ["https://www.googleapis.com/auth/documents"]
CREDENTIALS_FILE = "credentials.json"
LOG_FILE = "posted_log.json"

FB_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
FB_TOKEN = os.getenv("FACEBOOK_ACCESS_TOKEN")
DOC_ID = os.getenv("GOOGLE_DOC_ID")
POSTS_PER_DAY = int(os.getenv("POSTS_PER_DAY", 2))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", 60))
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

LAWYER_INFO = {
    "name": "איריס מורנו - עורכת דין ונוטריון",
    "phone": "052-837-2062",
    "phone2": "03-603-3013",
    "area": "חולון והסביבה",
    "website": "https://www.moreno-adv.co.il/",
    "topics": [
        "גירושין", "הסכמי ממון", "מזונות ילדים", "מזונות אישה",
        "משמורת ילדים", "הסדרי שהות", "צוואות", "ירושות",
        "ייפוי כוח מתמשך", "גישור משפחתי", "חדלות פרעון",
    ]
}


# ─── Google Docs: קריאה ───────────────────────────────────────────────────────
def get_google_service():
    credentials_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if credentials_json:
        import json as _json, base64
        raw = credentials_json.strip()
        if not raw.startswith("{"):
            raw = base64.b64decode(raw).decode("utf-8")
        creds = service_account.Credentials.from_service_account_info(
            _json.loads(raw), scopes=SCOPES
        )
    else:
        creds = service_account.Credentials.from_service_account_file(
            CREDENTIALS_FILE, scopes=SCOPES
        )
    return build("docs", "v1", credentials=creds)


def get_posts_from_doc() -> list[str]:
    """קורא את המסמך ומחזיר רשימת פוסטים (מופרדים בשורה ריקה)."""
    service = get_google_service()
    doc = service.documents().get(documentId=DOC_ID).execute()

    full_text = ""
    for element in doc.get("body", {}).get("content", []):
        paragraph = element.get("paragraph")
        if not paragraph:
            continue
        for run in paragraph.get("elements", []):
            text_run = run.get("textRun")
            if text_run:
                full_text += text_run.get("content", "")

    posts = [p.strip() for p in full_text.split("\n\n") if p.strip()]
    return posts


# ─── Google Docs: כתיבה ───────────────────────────────────────────────────────
def append_posts_to_doc(posts: list[str]):
    """מוסיף פוסטים חדשים לסוף המסמך."""
    service = get_google_service()
    doc = service.documents().get(documentId=DOC_ID).execute()

    # מצא את האינדקס האחרון במסמך
    end_index = doc["body"]["content"][-1]["endIndex"] - 1

    text_to_append = "\n\n" + "\n\n".join(posts)

    service.documents().batchUpdate(
        documentId=DOC_ID,
        body={"requests": [{"insertText": {
            "location": {"index": end_index},
            "text": text_to_append
        }}]}
    ).execute()

    print(f"[{_now()}] נוספו {len(posts)} פוסטים חדשים למסמך.")


# ─── Claude: יצירת פוסטים ─────────────────────────────────────────────────────
def generate_posts(count: int = 60) -> list[str]:
    """מייצר פוסטים חדשים לפייסבוק בעזרת Claude."""
    print(f"[{_now()}] מייצר {count} פוסטים חדשים עם Claude...")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    topics_str = "، ".join(LAWYER_INFO["topics"])

    prompt = f"""אתה עוזר שיווקי מקצועי למשרד עורכי דין.

צור בדיוק {count} פוסטים שונים לפייסבוק עבור:
**{LAWYER_INFO["name"]}**
אזור: {LAWYER_INFO["area"]}
אתר: {LAWYER_INFO["website"]}

תחומי עיסוק לפזר ביניהם: {topics_str}

הנחיות לכתיבה:
- סגנון: שילוב של מקצועי ונגיש לקהל הרחב
- טון: רגיש, אמפתי, תומך — מדברים עם אנשים בתקופה קשה
- אורך: 3-5 משפטים לפוסט
- כל פוסט חייב להסתיים בדיוק עם השורה: "לייעוץ ראשוני ללא התחייבות: {LAWYER_INFO["phone"]}"
- אין לכתוב כותרות, ממספור, או סימני פיסוק מיוחדים לפני הפוסט
- הפרד בין פוסטים עם שורה ריקה אחת בלבד
- גוון בין פוסטים שמסבירים זכויות, פוסטים שמעלים שאלות, ופוסטים שנותנים טיפ מעשי
- כתוב בעברית תקנית

כתוב את כל {count} הפוסטים ברצף."""

    message = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}]
    )

    text = message.content[0].text
    posts = [p.strip() for p in text.split("\n\n") if p.strip()]

    # ודא שיש מספיק פוסטים
    if len(posts) < count:
        print(f"[{_now()}] אזהרה: התקבלו {len(posts)} פוסטים במקום {count}")

    return posts[:count]


# ─── מעקב פרסומים ────────────────────────────────────────────────────────────
def load_log() -> dict:
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"posted_indices": [], "last_index": -1, "total_posted": 0}


def save_log(log: dict):
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


# ─── Facebook: פרסום ──────────────────────────────────────────────────────────
def publish_to_facebook(message: str) -> bool:
    url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/feed"
    response = requests.post(url, data={
        "message": message,
        "access_token": FB_TOKEN,
    })
    result = response.json()

    if "id" in result:
        print(f"[{_now()}] ✓ פורסם: {message[:70]}...")
        return True
    else:
        error_msg = result.get("error", {}).get("message", "שגיאה לא ידועה")
        print(f"[{_now()}] ✗ שגיאת פייסבוק: {error_msg}")
        return False


# ─── התראה למשתמש ────────────────────────────────────────────────────────────
def notify(title: str, message: str):
    print(f"\n{'='*50}")
    print(f"  {title}")
    print(f"  {message}")
    print(f"{'='*50}\n")

    if NOTIFICATIONS_AVAILABLE:
        try:
            notification.notify(title=title, message=message, timeout=10)
        except Exception:
            pass


# ─── לוגיקת הפרסום ────────────────────────────────────────────────────────────
def post_next():
    posts = get_posts_from_doc()
    log = load_log()
    next_index = log["last_index"] + 1

    # נגמרו הפוסטים — ייצר קבוצה חדשה
    if next_index >= len(posts):
        notify(
            "נגמרו הפוסטים!",
            f"כל {len(posts)} הפוסטים פורסמו. מייצר {BATCH_SIZE} פוסטים חדשים..."
        )

        new_posts = generate_posts(BATCH_SIZE)
        if not new_posts:
            notify("שגיאה", "לא הצלחתי לייצר פוסטים חדשים. בדוק את מפתח Claude API.")
            return

        append_posts_to_doc(new_posts)

        notify(
            "פוסטים חדשים מוכנים!",
            f"נוצרו ונוספו {len(new_posts)} פוסטים חדשים למסמך. ממשיך לפרסם..."
        )

        # טען מחדש ואפס
        posts = get_posts_from_doc()
        log["last_index"] = len(posts) - len(new_posts) - 1
        next_index = log["last_index"] + 1

    post = posts[next_index]
    success = publish_to_facebook(post)

    if success:
        log["last_index"] = next_index
        log["posted_indices"].append(next_index)
        log["total_posted"] = log.get("total_posted", 0) + 1
        save_log(log)


# ─── תזמון ───────────────────────────────────────────────────────────────────
def setup_schedule():
    times = {
        1: ["09:00"],
        2: ["09:00", "18:00"],
        3: ["09:00", "13:00", "19:00"],
        4: ["08:00", "12:00", "16:00", "20:00"],
    }

    if POSTS_PER_DAY in times:
        for t in times[POSTS_PER_DAY]:
            schedule.every().day.at(t).do(post_next)
        hours_str = " | ".join(times[POSTS_PER_DAY])
    else:
        interval = 24 // POSTS_PER_DAY
        schedule.every(interval).hours.do(post_next)
        hours_str = f"כל {interval} שעות"

    print(f"תזמון: {POSTS_PER_DAY} פוסטים ביום בשעות: {hours_str}")


# ─── כלי עזר ─────────────────────────────────────────────────────────────────
def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def print_status():
    posts = get_posts_from_doc()
    log = load_log()
    remaining = len(posts) - (log["last_index"] + 1)

    print(f"\n{'─'*40}")
    print(f"  סטטוס המערכת")
    print(f"{'─'*40}")
    print(f"  סה\"כ פוסטים במסמך: {len(posts)}")
    print(f"  פורסמו עד כה:      {log.get('total_posted', 0)}")
    print(f"  נותרו לפרסום:      {remaining}")
    print(f"  פוסטים ביום:       {POSTS_PER_DAY}")
    if remaining > 0:
        days_left = remaining // POSTS_PER_DAY
        print(f"  ימים קדימה:        ~{days_left} ימים")
    print(f"{'─'*40}\n")


# ─── הרצה ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("  פוסטר אוטומטי - עו\"ד איריס מורנו")
    print("=" * 50)

    # בדיקות ראשוניות
    print("\nבודק חיבורים...")

    try:
        posts = get_posts_from_doc()
        print(f"✓ Google Docs: {len(posts)} פוסטים")
    except Exception as e:
        print(f"✗ שגיאת Google Docs: {e}")
        exit(1)

    if not FB_TOKEN or not FB_PAGE_ID:
        print("✗ חסרים פרטי Facebook ב-.env")
        exit(1)
    else:
        print("✓ Facebook: הגדרות נמצאו")

    if not ANTHROPIC_API_KEY:
        print("⚠ מפתח Claude API חסר — יצירת פוסטים אוטומטית לא תעבוד")
    else:
        print("✓ Claude API: מפתח נמצא")

    print_status()
    setup_schedule()

    print("המערכת פועלת. לחץ Ctrl+C לעצירה.\n")

    while True:
        schedule.run_pending()
        time.sleep(30)
