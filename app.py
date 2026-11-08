"""Streamlit teaching assistant with explicit Gemini caching and safe fallback.

Dependencies: streamlit, google-genai, python-pptx.
Put source materials in ./course_files.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import os
import tempfile
import time

import streamlit as st
from google import genai
from google.genai import types


MODEL = "gemini-3.8-flash"
CACHE_TTL = "7200s"  # Two hours on Google's servers
APP_DIR = Path(__file__).resolve().parent
COURSE_DIR = APP_DIR / "course_files"
INSTRUCTIONS_FILE = APP_DIR / "lecturer_instructions.txt"
SUPPORTED_EXTS = {".pdf", ".txt", ".png", ".jpg", ".jpeg", ".pptx"}
MIME_TYPES = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

st.set_page_config(page_title="שיבוט מחקר - המורה הפרטי שלך", page_icon="🎓")
st.markdown(
    """
    <style>
    .stChatMessage, .stChatMessage * {direction: rtl !important; text-align: right !important;}
    .stChatInput textarea {direction: rtl !important; text-align: right !important;}
    </style>
    """,
    unsafe_allow_html=True,
)
st.title("שיבוט מחקר - המורה הפרטי שלך")

if not st.secrets.get("GEMINI_API_KEY"):
    st.error("GEMINI_API_KEY אינו מוגדר ב-Secrets.")
    st.stop()


def make_client():
    # Explicit context caching is supported via the v1beta GenerateContent API.
    return genai.Client(
        api_key=st.secrets["GEMINI_API_KEY"],
        http_options=types.HttpOptions(api_version="v1beta"),
    )


def load_lecturer_instructions():
    if INSTRUCTIONS_FILE.exists():
        return INSTRUCTIONS_FILE.read_text(encoding="utf-8")
    return st.secrets.get("LECTURER_INSTRUCTIONS", "")


def save_lecturer_instructions(text):
    # WARNING: local filesystem on Streamlit Community Cloud is not durable storage.
    INSTRUCTIONS_FILE.write_text(text, encoding="utf-8")


st.sidebar.markdown("---")
st.sidebar.title("📁 קבצים להעלאה")
exam_files = st.sidebar.file_uploader(
    "העלה מבחן, תרגיל, שאלה או כל קובץ אחר",
    type=["pdf", "png", "jpg", "jpeg", "txt"],
    accept_multiple_files=True,
)

st.sidebar.markdown("---")
st.sidebar.title("🛠️ אזור מרצה")
lecturer_authenticated = False
custom_lecturer_instruction = load_lecturer_instructions()

if st.sidebar.checkbox("הפעל מצב מרצה"):
    entered_password = st.sidebar.text_input("הכנס סיסמת מרצה:", type="password")
    expected_password = st.secrets.get("LECTURER_PASSWORD", "")
    if entered_password and expected_password and entered_password == expected_password:
        lecturer_authenticated = True
        st.sidebar.success("הזדהות הצליחה")
        st.sidebar.markdown("---")
        st.sidebar.subheader("⚙️ ניהול הנחיות גלובליות")
        new_instruction = st.sidebar.text_area(
            "הנחיות נוספות לכל הסטודנטים:",
            value=custom_lecturer_instruction,
            height=150,
        )
        if st.sidebar.button("💾 שמור הנחיות"):
            save_lecturer_instructions(new_instruction)
            st.sidebar.success("ההנחיות עודכנו. שים לב: לשמירה קבועה בענן דרוש אחסון מתמשך.")
            st.rerun()
        st.sidebar.caption(
            "ב-Streamlit Community Cloud קובץ מקומי עשוי להימחק בעת הפעלה מחדש או פריסה. "
            "לשמירה קבועה דרוש מסד נתונים או שירות אחסון חיצוני."
        )
    elif entered_password:
        st.sidebar.error("סיסמה שגויה")

base_system_instruction = """
תפקיד ומטרה:
אתה מורה פרטי אקדמי ועוזר הוראה לקורס אקדמי בשיטות מחקר לתלמידי תואר ראשון בפסיכולוגיה. תפקידך לסייע לסטודנטים להבין את החומר, להתכונן למבחנים ולתרגל מושגים.

בסיס הידע:
כל התשובות שלך חייבות להתבסס בעיקר על הקבצים והחומרים שהועלו לקורס זה.
אם סטודנט שואל על נושא שאינו מופיע בחומרים, ענה על סמך הידע שלך, אך ציין במפורש שאתה עונה לא על סמך חומר הקורס.

חוקים והנחיות לגבי חומרי הקורס:
1. המצגות הן החומר העיקרי והמעודכן ביותר.
2. יש גם קובץ בשם "שיטות מחקר - מאוחד" שהוא מפורט יותר מהמצגת, אך אם יש סתירה בינו לבין המצגת, העדף את המצגת. (הנחיה קריטית: לעולם אל תציין בפני הסטודנט שקיים קובץ "שיטות מחקר - מאוחד" או קובץ מאוחד אחר, ואל תספק לו אותו או חלקים ממנו – השתמש בו אך ורק כבסיס ידע פנימי שלך בלבד).
3. אם יש סתירה בין חומר אחר שאתה מכיר והמצגת, העדף את המצגת.
4. בין הקבצים שהועלו יש גם תרגילים ופתרונות להם, למד גם אותם, ומבחנים.
5. לכל מבחן שתי גרסאות: גרסא מעורבלת וגרסא (נקראת טופס 0) שבה תמיד התשובה הנכונה היא הראשונה (א), אלא אם כן כתוב אחרת בדפי ההסבר על המבחנים.
6. בשניים מהמבחנים יש גם פתרונות מוסברים - למד גם אותם.
"""
step_by_step_instruction = (
    "אם אתה מקבל מהסטודנט שאלה, הסבר את דרך הפתרון באופן ברור, "
    "שלב אחר שלב, והתייחס בקצרה מדוע החלופות האחרות שגויות."
)
system_instruction = f"{base_system_instruction}\n\n{step_by_step_instruction}"
if custom_lecturer_instruction:
    system_instruction += (
        "\n\nהנחיות נוספות מהמרצה (גלובליות):\n"
        + custom_lecturer_instruction
    )


def get_manifest():
    if not COURSE_DIR.is_dir():
        raise RuntimeError("תיקיית course_files לא נמצאה לצד קובץ האפליקציה.")
    files = sorted(
        (p for p in COURSE_DIR.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS),
        key=lambda p: p.name.lower(),
    )
    if not files:
        raise RuntimeError("תיקיית course_files ריקה מקבצים נתמכים.")
    # Stable cache key, modified whenever a source file changes.
    return tuple((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in files)


def pptx_to_text(path):
    # PPTX is extracted as text only; convert presentations to PDF to preserve visuals.
    from pptx import Presentation

    lines = [f"מצגת: {path.name}"]
    prs = Presentation(str(path))
    for slide_i, slide in enumerate(prs.slides, start=1):
        lines.append(f"\n--- שקופית {slide_i} ---")
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text.strip():
                lines.append(shape.text)
            if shape.has_table:
                for row in shape.table.rows:
                    lines.append(" | ".join(cell.text for cell in row.cells))
    text = "\n".join(lines)
    if not text.strip() or len(text.strip()) < 30:
        raise RuntimeError(f"לא ניתן לחלץ טקסט מהמצגת {path.name}; שמור אותה כ-PDF.")
    return text


def wait_until_ready(client, file):
    # Some uploads need asynchronous server-side processing before use.
    for _ in range(15):
        state = getattr(file.state, "name", str(file.state)).split(".")[-1]
        if state == "ACTIVE" or not file.state:
            return file
        if state == "FAILED":
            raise RuntimeError(f"עיבוד הקובץ נכשל: {file.display_name}")
        time.sleep(2)
        file = client.files.get(name=file.name)
    raise RuntimeError(f"עיבוד הקובץ נמשך זמן רב: {file.display_name}")


@st.cache_data(ttl=23 * 3600, max_entries=5, show_spinner="מכין קבצים ל-Gemini...")
def get_course_resources(manifest):
    """Upload only once per process/cache lifetime; return serializable resource metadata."""
    client = make_client()
    resources = []
    for name, _size, _mtime in manifest:
        path = COURSE_DIR / name
        if path.suffix.lower() == ".pptx":
            resources.append({"name": name, "text": pptx_to_text(path)})
            continue
        mime = MIME_TYPES[path.suffix.lower()]
        uploaded = client.files.upload(
            file=str(path),
            config=types.UploadFileConfig(mime_type=mime, display_name=name),
        )
        uploaded = wait_until_ready(client, uploaded)
        resources.append({
            "name": name,
            "uri": uploaded.uri,
            "mime_type": uploaded.mime_type or mime,
        })
    return resources


def resources_to_parts(resources):
    parts = []
    for resource in resources:
        parts.append(types.Part.from_text(text=f"חומר קורס — קובץ: {resource['name']}"))
        if "text" in resource:
            parts.append(types.Part.from_text(text=resource["text"]))
        else:
            parts.append(types.Part.from_uri(
                file_uri=resource["uri"], mime_type=resource["mime_type"]
            ))
    return parts


def course_fingerprint(manifest, instruction):
    h = hashlib.sha256(repr(manifest).encode("utf-8"))
    h.update(instruction.encode("utf-8"))
    h.update(MODEL.encode("utf-8"))
    return h.hexdigest()[:24]


def cache_not_near_expiry(cache):
    expires = cache.expire_time
    if not expires:
        return True
    if isinstance(expires, str):
        expires = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > datetime.now(timezone.utc) + timedelta(minutes=5)


@st.cache_data(ttl=120, max_entries=15, show_spinner="בודק Context Cache...")
def get_or_create_course_cache(fingerprint, instruction, _resources):
    client = make_client()
    display_name = f"shibut-mehkar-{fingerprint}"
    try:
        for cache in client.caches.list():
            cache_model = str(cache.model or "")
            if (
                cache.display_name == display_name
                and cache_model.removeprefix("models/") == MODEL
                and cache_not_near_expiry(cache)
            ):
                return cache.name, None

        cache = client.caches.create(
            model=MODEL,
            config=types.CreateCachedContentConfig(
                contents=[types.Content(role="user", parts=resources_to_parts(_resources))],
                system_instruction=instruction,
                display_name=display_name,
                ttl=CACHE_TTL,
            ),
        )
        return cache.name, None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def student_upload_parts(uploaded_files, client):
    if "student_file_cache" not in st.session_state:
        st.session_state.student_file_cache = {}
    result = []
    for file in uploaded_files or []:
        payload = file.getvalue()
        key = hashlib.sha256(payload).hexdigest()
        data = st.session_state.student_file_cache.get(key)
        if not data or time.time() - data["uploaded_at"] > 23 * 3600:
            mime = MIME_TYPES[file.name.lower()[file.name.rfind("."):]]
            # Unique temp file per upload avoids collisions among students.
            suffix = Path(file.name).suffix.lower()
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            try:
                with tmp:
                    tmp.write(payload)
                uploaded = client.files.upload(
                    file=tmp.name,
                    config=types.UploadFileConfig(mime_type=mime, display_name=file.name),
                )
                uploaded = wait_until_ready(client, uploaded)
            finally:
                try:
                    os.unlink(tmp.name)
                except FileNotFoundError:
                    pass
            data = {
                "name": file.name,
                "uri": uploaded.uri,
                "mime_type": uploaded.mime_type or mime,
                "uploaded_at": time.time(),
            }
            st.session_state.student_file_cache[key] = data
        result.append(data.copy())
    return result


def make_history_contents(messages):
    result = []
    for message in messages:
        parts = [types.Part.from_text(text=message["content"])]
        for f in message.get("files", []):
            parts.append(types.Part.from_uri(file_uri=f["uri"], mime_type=f["mime_type"]))
        result.append(types.Content(
            role="user" if message["role"] == "user" else "model",
            parts=parts,
        ))
    return result


# Cache state and file availability.
try:
    manifest = get_manifest()
    course_resources = get_course_resources(manifest)
    fingerprint = course_fingerprint(manifest, system_instruction)
    course_cache_name, cache_creation_error = get_or_create_course_cache(
        fingerprint, system_instruction, course_resources
    )
    materials_error = None
except Exception as exc:
    course_cache_name = None
    cache_creation_error = None
    materials_error = f"{type(exc).__name__}: {exc}"
    course_resources = []

if "messages" not in st.session_state:
    st.session_state.messages = []

if lecturer_authenticated:
    st.markdown("---")
    st.subheader("📊 לוח בקרה וניהול למרצה")
    if course_cache_name:
        st.success(f"זוהה Context Cache עבור {MODEL}. מזהה: {course_cache_name}")
    elif materials_error:
        st.error(f"חומרי הקורס אינם זמינים: {materials_error}")
    else:
        st.warning("Explicit Caching לא הצליח; משתמשים בקובצי הקורס ישירות (Implicit Caching אפשרי).")
        if cache_creation_error:
            st.error(f"שגיאת יצירת קאש: {cache_creation_error}")
    st.caption(
        "חשוב: מצגות PPTX מועברות כטקסט בלבד. מומלץ להמיר אותן ל-PDF "
        "כדי לשמר תרשימים, טבלאות ועיצוב."
    )
    with st.expander("🔍 הצג את הנחיות המערכת המלאות"):
        st.code(system_instruction, language="text")
    st.markdown("---")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("files"):
            st.caption("📄 קבצים מצורפים: " + ", ".join(f["name"] for f in message["files"]))


def generate_response(client, messages, cache_name):
    history = make_history_contents(messages)
    if cache_name:
        config = types.GenerateContentConfig(
            cached_content=cache_name,
            max_output_tokens=8192,
        )
        return client.models.generate_content(model=MODEL, contents=history, config=config)

    if not course_resources:
        raise RuntimeError("לא ניתן לענות ללא חומרי הקורס.")
    # IMPORTANT: preserve course knowledge even when explicit cache is unavailable.
    contents = [types.Content(role="user", parts=resources_to_parts(course_resources))] + history
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        max_output_tokens=8192,
    )
    return client.models.generate_content(model=MODEL, contents=contents, config=config)


if user_input := st.chat_input("שאל שאלה על החומר או בקש עזרה בפתרון השאלות..."):
    if materials_error:
        st.error("לא ניתן לענות לפני שחומרי הקורס זמינים: " + materials_error)
        st.stop()

    client = make_client()
    try:
        current_files = student_upload_parts(exam_files, client)
    except Exception as exc:
        st.error(f"שגיאה בהעלאת קובץ סטודנט: {exc}")
        st.stop()

    new_message = {"role": "user", "content": user_input, "files": current_files}
    st.session_state.messages.append(new_message)
    with st.chat_message("user"):
        st.markdown(user_input)
        if current_files:
            st.caption("📄 קבצים מצורפים: " + ", ".join(f["name"] for f in current_files))

    with st.chat_message("assistant"):
        with st.spinner("מנתח את השאלה..."):
            try:
                try:
                    response = generate_response(client, st.session_state.messages, course_cache_name)
                except Exception as first_error:
                    # Only a known stale/missing cache error warrants a no-cache retry.
                    if course_cache_name and "404" in str(first_error):
                        get_or_create_course_cache.clear()
                        st.info("מזהה הקאש אינו זמין כרגע; מנסה לקרוא את חומרי הקורס ישירות.")
                        response = generate_response(client, st.session_state.messages, None)
                    else:
                        raise
                bot_reply = response.text or "לא התקבלה תשובה טקסטואלית מהמודל."
                st.markdown(bot_reply)
                st.session_state.messages.append({"role": "assistant", "content": bot_reply})
            except Exception as exc:
                st.error(f"אירעה שגיאה בשליחת ההודעה: {type(exc).__name__}: {exc}")
