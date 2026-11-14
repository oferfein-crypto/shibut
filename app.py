"""Streamlit teaching assistant with explicit Gemini caching and safe fallback.

Dependencies: streamlit, google-genai, python-pptx, requests, plotly, pymupdf, pydantic.
Put source materials in ./course_files.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import math
import re
import os
import shutil
import tempfile
import time
import uuid
from urllib.parse import quote

import chat_store
from lecturer_instructions import load_lecturer_instructions_record

import plotly.graph_objects as go
import pymupdf
from pydantic import BaseModel, Field
from typing import Literal
import streamlit as st
from google import genai
from google.genai import types


MODEL = "gemini-3.8-flash"
CACHE_TTL = "7200s"  # Two hours on Google's servers
APP_DIR = Path(__file__).resolve().parent
COURSE_DIR = APP_DIR / "course_files"
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
    /* RTL for Markdown text and all nesting levels of lists in chat.
       Scope to Markdown blocks only: never apply it to Plotly/SVG elements. */
    .stChatMessage [data-testid="stMarkdownContainer"] {
        direction: rtl !important;
        text-align: right !important;
    }
    .stChatMessage [data-testid="stMarkdownContainer"] :is(
        p, h1, h2, h3, h4, h5, h6, blockquote, ul, ol, li
    ) {
        direction: rtl !important;
        text-align: right !important;
    }
    /* Move list markers and indentation to the right, including sublists. */
    .stChatMessage [data-testid="stMarkdownContainer"] :is(ul, ol) {
        padding-left: 0 !important;
        padding-right: 1.6rem !important;
        margin-left: 0 !important;
        list-style-position: outside;
    }
    .stChatMessage [data-testid="stCaptionContainer"],
    .stChatMessage [data-testid="stCaptionContainer"] p,
    [data-testid="stPopoverBody"] [data-testid="stCaptionContainer"],
    [data-testid="stPopoverBody"] [data-testid="stCaptionContainer"] p,
    [data-testid="stPopoverBody"] pre,
    [data-testid="stPopoverBody"] code {
        direction: rtl !important;
        text-align: right !important;
    }
    .stChatInput textarea {
        direction: rtl !important;
        text-align: right !important;
    }
    .st-key-login_screen {
        direction: rtl;
    }
    .st-key-login_screen [data-testid="stMarkdownContainer"],
    .st-key-login_screen [data-testid="stCaptionContainer"] {
        direction: rtl;
        text-align: right;
    }
    [data-testid="stSidebar"] {
        order: 1;
        direction: rtl;
        text-align: right;
        left: auto;
        right: 0;
    }
    [data-testid="stSidebar"][data-collapsed="true"] {
        width: 0 !important;
        min-width: 0 !important;
        margin: 0 !important;
        visibility: hidden;
    }
    [data-testid="stSidebar"] :is(p, h1, h2, h3, label, input, textarea) {
        direction: rtl;
        text-align: right;
    }
    [data-testid="stSidebar"] [data-baseweb="select"],
    [data-testid="stSidebar"] button {
        direction: rtl;
        text-align: right;
    }
    [data-testid="stSidebar"][data-collapsed="false"] [data-testid="stSidebarCollapseButton"] {
        visibility: visible;
    }
    [data-testid="stSidebarResizeHandle"] {
        display: none;
    }
    [data-testid="stSidebarCollapsedControl"] {
        left: auto;
        right: 0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
# Use a semantic H1 with explicit RTL so alignment works across Streamlit versions.
st.markdown(
    '<h1 dir="rtl" style="direction:rtl; text-align:right; width:100%;">'
    'שיבוט מחקר - המורה הפרטי שלך</h1>',
    unsafe_allow_html=True,
)

# ---------------------------------------------------------
# Optional Google sign-in and persistent history / guest mode
# ---------------------------------------------------------

def is_google_logged_in():
    # In Streamlit, st.user.is_logged_in doesn't exist without [auth] secrets.
    try:
        return bool(st.user.is_logged_in)
    except (AttributeError, KeyError, RuntimeError):
        return False


def auth_configured():
    try:
        return bool(st.secrets.get("auth"))
    except Exception:
        return False


logged_in = is_google_logged_in()
if not logged_in and not st.session_state.get("guest_accepted", False):
    with st.container(key="login_screen"):
        st.markdown("### כניסה לעוזר הלמידה")
        st.info(
            "התחברות עם Google מאפשרת לשמור את השיחות ולחזור אליהן גם לאחר "
            "סגירת הדפדפן או ממכשיר אחר. **ללא התחברות, השיחות לא יהיו זמינות "
            "לך בכניסה הבאה.**"
        )
        st.caption(
            "לצורך שיפור ההוראה, תוכן השיחות נשמר במאגר שהמרצה יכול לעיין בו, "
            "גם בשימוש כאורח (ללא שם משתמש). אין לכתוב פרטים אישיים רגישים "
            "בשאלות. שיחות אורח לא מועברות אוטומטית לחשבון Google בעת התחברות מאוחרת."
        )
        a, b = st.columns(2)
        with a:
            if auth_configured():
                if st.button("התחבר באמצעות Google", use_container_width=True, type="primary"):
                    st.login()
            else:
                st.caption("כניסה באמצעות Google תהיה זמינה לאחר הגדרת OAuth ב-Secrets.")
        with b:
            if st.button("המשך כאורח — ללא שחזור שיחות", use_container_width=True):
                st.session_state.guest_accepted = True
                st.rerun()
    st.stop()

if logged_in:
    st.sidebar.success("מחובר עם Google — השיחות נשמרות וניתן לשחזר אותן")
    st.sidebar.caption(str(st.user.get("email", "")))
    if st.sidebar.button("התנתק מחשבון Google"):
        st.logout()
else:
    st.sidebar.warning("מצב אורח: לא תוכל לחזור לשיחות בכניסה הבאה.")
    st.sidebar.caption("השיחות נשמרות ללא שם במאגר המרצה, אם Firestore הוגדר.")
    if auth_configured() and st.sidebar.button("התחבר עם Google לשמירת שיחות עתידיות"):
        st.login()

@st.cache_resource(show_spinner=False)
def get_chat_db():
    secret_json = st.secrets.get("FIREBASE_SERVICE_ACCOUNT_JSON", "")
    if not secret_json:
        return None
    return chat_store.firestore_client(secret_json)

try:
    chat_db = get_chat_db()
except Exception:
    chat_db = None

if chat_db is None:
    st.warning(
        "אחסון השיחות ב-Firestore עדיין לא פעיל. אפשר לתרגל, אבל "
        "**השיחות אינן נשמרות לצמיתות כרגע**."
    )

if logged_in:
    sub = str(st.user.get("sub", ""))
    issuer = str(st.user.get("iss", ""))
    pepper = st.secrets.get("USER_ID_PEPPER", "")
    if not sub or not issuer or not pepper:
        st.error("שמירת שיחות Google מחייבת USER_ID_PEPPER ומזהה משתמש מאומת.")
        st.stop()
    owner_key = chat_store.account_key(issuer, sub, pepper)
    auth_mode = "google"
else:
    if "guest_owner" not in st.session_state:
        st.session_state.guest_owner = chat_store.fresh_guest_owner()
    owner_key = st.session_state.guest_owner
    auth_mode = "guest"

# Isolation between Google accounts and guests sharing the same browser session.
if st.session_state.get("identity_key") != owner_key:
    st.session_state.identity_key = owner_key
    st.session_state.messages = []
    st.session_state.active_thread_id = None
    st.session_state.active_thread_initialized = False
    st.session_state.thread_saved = False
    st.session_state.pending_messages = []
    st.session_state.upload_counter = 0


@st.cache_data(ttl=60, show_spinner=False)
def cached_user_threads(user_key):
    return chat_store.list_user_threads(chat_db, user_key, limit=80)


def reset_current_chat():
    st.session_state.messages = []
    st.session_state.active_thread_id = None
    st.session_state.active_thread_initialized = True
    st.session_state.thread_saved = False
    st.session_state.pending_messages = []
    st.session_state.student_file_cache = {}
    st.session_state.upload_counter += 1
    if "history_picker" in st.session_state:
        st.session_state.history_picker = "__new__"


def load_existing_chat(thread_id):
    if chat_db is None:
        raise RuntimeError("מסד הנתונים אינו זמין")
    meta, messages = chat_store.read_thread(chat_db, thread_id, owner_key)
    if meta.get("auth_mode") != "google" or not logged_in:
        raise PermissionError("אפשר לטעון רק שיחות של חשבון Google מחובר")
    st.session_state.active_thread_id = thread_id
    st.session_state.messages = messages
    st.session_state.thread_saved = True
    st.session_state.pending_messages = []
    st.session_state.active_thread_initialized = True
    st.session_state.student_file_cache = {}
    st.session_state.upload_counter += 1


def persist_pending_messages():
    """Retry failures within the SAME Streamlit session; do not silently lose messages."""
    if chat_db is None or not st.session_state.pending_messages:
        return
    if st.session_state.active_thread_id is None:
        st.session_state.active_thread_id = chat_store.fresh_thread_id()
    remaining = list(st.session_state.pending_messages)
    for message in remaining:
        try:
            was_new_thread = not st.session_state.thread_saved
            chat_store.append_message(
                chat_db,
                thread_id=st.session_state.active_thread_id,
                owner_key=owner_key,
                auth_mode=auth_mode,
                message=message,
                new_thread=not st.session_state.thread_saved,
                first_title=next(
                    (m["content"] for m in st.session_state.messages if m["role"] == "user"),
                    "שיחה חדשה",
                ),
            )
            st.session_state.thread_saved = True
            st.session_state.pending_messages.pop(0)
            if was_new_thread and logged_in:
                cached_user_threads.clear(owner_key)
        except Exception:
            # Don't display internal service-account/credential information.
            return


def queue_for_storage(message):
    if chat_db is None:
        return
    st.session_state.pending_messages.append(message)
    persist_pending_messages()


if logged_in and chat_db is not None:
    try:
        user_threads = cached_user_threads(owner_key)
        if not st.session_state.active_thread_initialized:
            if user_threads:
                load_existing_chat(user_threads[0]["id"])
            else:
                st.session_state.active_thread_initialized = True
    except Exception:
        user_threads = []
        st.warning("לא ניתן כרגע לטעון את השיחות הקודמות. נסה לרענן את הדף.")

    st.sidebar.markdown("---")
    st.sidebar.subheader("השיחות שלי")
    st.sidebar.button("+ שיחה חדשה", on_click=reset_current_chat, use_container_width=True)
    options = ["__new__"] + [row["id"] for row in user_threads]
    labels = {row["id"]: row.get("title", "שיחה") for row in user_threads}
    options_selected = st.session_state.get("active_thread_id") or "__new__"
    if options_selected not in options:
        options_selected = "__new__"
    if "history_picker" not in st.session_state:
        st.session_state.history_picker = options_selected
    picked = st.sidebar.selectbox(
        "פתח שיחה קודמת", options,
        format_func=lambda value: "בחר שיחה..." if value == "__new__" else labels.get(value, "שיחה"),
        key="history_picker",
    )
    if picked != "__new__" and picked != st.session_state.active_thread_id:
        try:
            load_existing_chat(picked)
            st.rerun()
        except Exception:
            st.sidebar.error("לא ניתן לטעון את השיחה שנבחרה.")
    if not st.session_state.active_thread_initialized:
        st.session_state.active_thread_initialized = True
else:
    st.session_state.active_thread_initialized = True
    if not logged_in:
        st.sidebar.button("+ שיחה חדשה (אורח)", on_click=reset_current_chat, use_container_width=True)

# If a write previously failed, retry it before the next message.
persist_pending_messages()
if st.session_state.pending_messages:
    st.warning("חלק מההודעות בשיחה הנוכחית טרם נשמרו עקב שגיאת תקשורת. "
               "השאר את הדף פתוח ושלח הודעה נוספת כדי לנסות שוב.")

if not st.secrets.get("GEMINI_API_KEY"):
    st.error("GEMINI_API_KEY אינו מוגדר ב-Secrets.")
    st.stop()


def make_client():
    # Explicit context caching is supported via the v1beta GenerateContent API.
    return genai.Client(
        api_key=st.secrets["GEMINI_API_KEY"],
        http_options=types.HttpOptions(api_version="v1beta"),
    )


st.sidebar.markdown("---")
st.sidebar.title("📁 קבצים להעלאה")
exam_files = st.sidebar.file_uploader(
    "העלה מבחן, תרגיל, שאלה או כל קובץ אחר",
    type=["pdf", "png", "jpg", "jpeg", "txt"],
    accept_multiple_files=True,
    key=f"student_upload_{st.session_state.upload_counter}",
)

try:
    custom_lecturer_instruction, _ = load_lecturer_instructions_record()
except Exception:
    st.error("לא ניתן לטעון כרגע את הנחיות המרצה מ-GitHub. נסה שוב בעוד רגע.")
    st.stop()

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
7. כשמבקשים גרף, אין לצייר גרפים באמצעות תווי ASCII, Markdown או טבלאות כאילו היו תמונה. ממשק האפליקציה מטפל בגרפים אמיתיים באמצעות מנגנון תצוגה ייעודי.
8. כאשר יש גם PPTX וגם PDF של אותה מצגת, הטקסט המחולץ מה-PPTX עדיף לפענוח הניסוח בעברית; ה-PDF מסייע בפירוש הגרפיקה והמבנה החזותי. אל תסתיר אי-ודאות באשר לנתונים או לשקופיות.
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


def upload_with_ascii_filename(client, *, suffix, mime_type, safe_display_name,
                               source_path=None, file_bytes=None):
    """Upload via an ASCII-only path and ASCII-only metadata.

    Some HTTP upload stacks put the local filename or display_name in headers
    that cannot encode Hebrew/other Unicode. The original filename is kept
    separately for the model's source labels and for display in Streamlit.
    """
    if not safe_display_name.isascii() or not suffix.isascii():
        raise ValueError("Temporary upload names must contain ASCII characters only")
    if (source_path is None) == (file_bytes is None):
        raise ValueError("Provide either source_path or file_bytes")

    with tempfile.NamedTemporaryFile(
        mode="wb", prefix="gemini_upload_", suffix=suffix, delete=False
    ) as temporary:
        temporary_path = temporary.name
        if source_path is not None:
            with open(source_path, "rb") as source:
                shutil.copyfileobj(source, temporary)
        else:
            temporary.write(file_bytes)

    try:
        return client.files.upload(
            file=temporary_path,
            config=types.UploadFileConfig(
                mime_type=mime_type, display_name=safe_display_name
            ),
        )
    finally:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass


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
        ascii_name = f"course_{hashlib.sha256(name.encode('utf-8')).hexdigest()[:16]}{path.suffix.lower()}"
        uploaded = upload_with_ascii_filename(
            client,
            source_path=path,
            suffix=path.suffix.lower(),
            mime_type=mime,
            safe_display_name=ascii_name,
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
            # Filename and display_name must both be ASCII; keep the Hebrew
            # original separately for the user-facing UI and model labels.
            suffix = Path(file.name).suffix.lower()
            uploaded = upload_with_ascii_filename(
                client,
                suffix=suffix,
                file_bytes=payload,
                mime_type=mime,
                safe_display_name=f"student_{key[:16]}{suffix}",
            )
            uploaded = wait_until_ready(client, uploaded)
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
        text_content = message["content"]
        if message.get("graphic"):
            text_content += graphic_history_note(message["graphic"])
        available_files = []
        for f in message.get("files", []):
            if f.get("uri"):
                available_files.append(f)
            elif f.get("name"):
                text_content += (
                    f"\n[הקובץ {f['name']} צורף בשיחה קודמת, אך תוכנו אינו זמין "
                    "כעת. אל תסיק ממנו מידע; בקש להעלות אותו מחדש אם נחוץ.]"
                )
        parts = [types.Part.from_text(text=text_content)]
        for f in available_files:
            parts.append(types.Part.from_uri(file_uri=f["uri"], mime_type=f["mime_type"]))
        result.append(types.Content(
            role="user" if message["role"] == "user" else "model",
            parts=parts,
        ))
    return result


# ---------------------------------------------------------
# Visual explanations: original PDF slides + Plotly figures
# ---------------------------------------------------------

class PlotPoint(BaseModel):
    x: str = Field(description="Axis value or category, including Hebrew labels")
    y: float = Field(description="Numerical y value")


class PlotSeries(BaseModel):
    name: str = Field(description="Legend label, e.g. participants' age group")
    points: list[PlotPoint] = Field(default_factory=list)


class VisualAnswer(BaseModel):
    mode: Literal["slide", "chart", "text"]
    explanation: str = Field(description="Short helpful response in Hebrew, without ASCII graphics")
    source_pdf: str = Field(default="", description="Exact filename of an available slide PDF")
    slide_number: int = Field(default=0, description="1-based PDF page/slide number")
    chart_type: Literal["line", "bar", "scatter", "histogram", "pie"] = "line"
    title: str = ""
    x_axis_label: str = ""
    y_axis_label: str = ""
    illustrative: bool = True
    source_note: str = ""
    series: list[PlotSeries] = Field(default_factory=list)


GRAPH_CUE = re.compile(
    r"גר[ףפ]|גרפים|תרשים|תרשימים|שקופית|שקופיות|דיאגרמ[הת]|צייר|שרטט|המחשה גרפית|"
    r"(?:graph|plot|chart|scatter|histogram)", re.IGNORECASE
)
FOLLOWUP_CUE = re.compile(
    r"שנה|תשנה|שינוי|עדכן|תעדכן|הוסף|תוסיף|תיקון|תקן|אותו|אותה|"
    r"עכשיו|במקום|החלף|תראה שוב|עוד גרף", re.IGNORECASE
)


def is_visual_request(user_text, messages):
    if GRAPH_CUE.search(user_text):
        return True
    prior_graphic = any(m.get("graphic") for m in messages[-5:-1])
    return bool(prior_graphic and FOLLOWUP_CUE.search(user_text))


@st.cache_data(show_spinner=False, max_entries=8)
def get_slide_catalog(manifest):
    """Whitelisted PDFs: same base name as PPTX; never reveal unrelated course PDFs.

    PDF export must contain one slide per page and preserve slide order.
    """
    pptx_stems = {
        Path(name).stem.casefold()
        for name, *_ in manifest if Path(name).suffix.lower() == ".pptx"
    }
    catalog = {}
    for name, *_ in manifest:
        path = COURSE_DIR / name
        if path.suffix.lower() != ".pdf" or path.stem.casefold() not in pptx_stems:
            continue
        if "מאוחד" in path.stem:  # internal reference material is never displayed
            continue
        try:
            with pymupdf.open(path) as doc:
                if doc.page_count:
                    catalog[name] = doc.page_count
        except Exception:
            # A malformed presentation PDF should not disable the teaching assistant.
            continue
    return catalog


def original_slide_png(pdf_filename, page_number, catalog):
    """Render exactly one vetted source page locally; do not expose other PDFs."""
    if pdf_filename not in catalog:
        raise ValueError("המצגת המבוקשת אינה זמינה להצגה כתמונה.")
    if not isinstance(page_number, int) or not 1 <= page_number <= catalog[pdf_filename]:
        raise ValueError("מספר השקופית אינו תקין.")
    path = COURSE_DIR / pdf_filename
    with pymupdf.open(path) as doc:
        page = doc[page_number - 1]
        pixmap = page.get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6), alpha=False)
        return pixmap.tobytes("png")


def visual_task_instructions(catalog):
    catalog_text = "\n".join(
        f"- {name} ({count} שקופיות / עמודים)" for name, count in catalog.items()
    ) or "(אין זוגות PPTX/PDF להצגת שקופית מקורית)"
    return f"""
הוראות לתצוגה חזותית לתשובה האחרונה בשיחה:
- ענה בעברית באמצעות explanation ברור וקצר. אסור ליצור ציורים בתווי ASCII.
- אם המשתמש ביקש לראות *גרף מקורי מתוך מצגת*, בחר mode=slide רק אם זיהית
  בביטחון את שם ה-PDF ואת מספר השקופית המדויק התואמים לגרף המבוקש.
  בחר אך ורק מתוך הקבצים ברשימת המקור למטה. אל תנחש מספר שקופית או שם קובץ.
  המספר הוא מספר העמוד בקובץ PDF, החל מ-1; ה-PDF נוצר במצגת עם עמוד לשקופית.
- אם המשתמש ביקש *ליצור גרף חדש*, או גרף להמחשת עיקרון מתודולוגי,
  בחר mode=chart ותאר את נקודות הגרף באמצעות series/points.
  עבור גרף אינטראקציה יש להשתמש בדרך כלל ב-chart_type=line, עם סדרות
  נפרדות לכל קבוצה; סדר הנקודות על ציר X חייב להיות זהה בין הסדרות.
  chart_type=scatter רק כאשר ציר X משתנה כמותי; bar להשוואת ממוצעים או שכיחויות;
  histogram להצגת תדירויות במחלקות; pie להתפלגות קטגוריות של שלם אחד.
- העתק ערכים אמיתיים בדיוק מחומרי הקורס או מפניית הסטודנט. אם לא נמסרו
  נתונים מדויקים, השתמש בערכי דוגמה סבירים וקבע illustrative=true,
  וציין במפורש ב-explanation וב-source_note שהנתונים להמחשה בלבד.
  אין להציג ערכים מומצאים כנתונים אמפיריים.
- אם אין לך די מידע לזהות שקופית מקורית, או שאי אפשר להפיק גרף בלי
  להטעות, החזר mode=text והסבר מה חסר, או mode=chart אם המחשה
  חדשה מותרת ומתאימה לבקשה. אל תמציא שקופית.
- לכל סדרה עד 80 נקודות, ולכל תרשים עד 8 סדרות. x הוא מחרוזת, y מספר.
- התייחס לסוג הגרף ולתוכן הנוכחי של הקורס; אל תחשוף שמות או תוכן
  של חומרי עזר שהמרצה אסר לחשוף.

קובצי PDF מאושרים להצגת *שקופיות מקוריות* (רק זוגות PPTX ו-PDF):
{catalog_text}
"""


def history_with_visual_task(messages, catalog):
    """Preserve conversation/files; add private machine-format hints to final turn."""
    items = [dict(message) for message in messages]
    items[-1]["content"] += "\n\n" + visual_task_instructions(catalog)
    return make_history_contents(items)


def visual_answer_from_model(client, messages, cache_name, catalog):
    history = history_with_visual_task(messages, catalog)
    if cache_name:
        config = types.GenerateContentConfig(
            cached_content=cache_name,
            response_mime_type="application/json",
            response_schema=VisualAnswer,
            max_output_tokens=4096,
        )
        response = client.models.generate_content(model=MODEL, contents=history, config=config)
    else:
        if not course_resources:
            raise RuntimeError("לא ניתן לענות ללא חומרי הקורס.")
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=VisualAnswer,
            max_output_tokens=4096,
        )
        contents = [types.Content(role="user", parts=resources_to_parts(course_resources))] + history
        response = client.models.generate_content(model=MODEL, contents=contents, config=config)
    if isinstance(response.parsed, VisualAnswer):
        return response.parsed
    if response.text:
        return VisualAnswer.model_validate(json.loads(response.text))
    raise RuntimeError("לא התקבלה תשובה גרפית תקינה מהמודל")


def is_missing_cache_error(exc):
    message = str(exc).lower()
    return "404" in message or "not found" in message and "cached" in message


def make_visual_response(client, messages, cache_name, catalog):
    try:
        return visual_answer_from_model(client, messages, cache_name, catalog)
    except Exception as first_error:
        if cache_name and is_missing_cache_error(first_error):
            get_or_create_course_cache.clear()
            return visual_answer_from_model(client, messages, None, catalog)
        raise


# Shared palette for Plotly traces and the separate, properly RTL HTML legend.
CHART_COLORS = (
    "#1670A8", "#E68531", "#16806B", "#9B61B5",
    "#C13A51", "#6495ED", "#A28A43", "#536172",
)


def build_plotly_figure(graph):
    """Render only known chart types. Never evaluate code or HTML from the model."""
    if not graph.get("series"):
        raise ValueError("המודל לא סיפק נתונים לגרף")
    if len(graph["series"]) > 8:
        raise ValueError("הגרף מכיל יותר מדי סדרות")

    kind = graph["chart_type"]
    if kind not in {"line", "bar", "scatter", "histogram", "pie"}:
        raise ValueError("סוג גרף אינו נתמך")
    colors = CHART_COLORS
    fig = go.Figure()
    for idx, series in enumerate(graph["series"]):
        points = series.get("points", [])
        if not points or len(points) > 80:
            raise ValueError("מספר הנקודות בגרף אינו תקין")
        xs = [str(pt["x"]) for pt in points]
        ys = [float(pt["y"]) for pt in points]
        if not all(math.isfinite(y) for y in ys):
            raise ValueError("ערכי הגרף חייבים להיות סופיים")
        name = series.get("name") or f"קבוצה {idx + 1}"
        color = colors[idx % len(colors)]
        if kind == "line":
            fig.add_trace(go.Scatter(x=xs, y=ys, name=name, mode="lines+markers",
                                     line=dict(color=color, width=3), marker=dict(size=10)))
        elif kind in {"bar", "histogram"}:
            fig.add_trace(go.Bar(x=xs, y=ys, name=name, marker_color=color))
        elif kind == "scatter":
            try:
                numeric_xs = [float(x) for x in xs]
            except ValueError as exc:
                raise ValueError("בתרשים פיזור יש לספק ערכי X מספריים") from exc
            if not all(math.isfinite(x) for x in numeric_xs):
                raise ValueError("ערכי X חייבים להיות מספרים סופיים")
            fig.add_trace(go.Scatter(x=numeric_xs, y=ys, name=name, mode="markers",
                                     marker=dict(color=color, size=10, opacity=0.85)))
        else:  # pie: category labels / shares from one series
            if idx > 0:
                raise ValueError("גרף עוגה תומך בסדרה אחת בלבד")
            if any(y < 0 for y in ys) or sum(ys) <= 0:
                raise ValueError("גרף עוגה מחייב ערכים חיוביים")
            fig.add_trace(go.Pie(
                labels=xs, values=ys, hole=0.25,
                marker=dict(colors=[colors[i % len(colors)] for i in range(len(xs))]),
            ))

    fig.update_layout(
        title=dict(text=graph.get("title") or "גרף להמחשה", x=0.5),
        xaxis_title=graph.get("x_axis_label", ""),
        yaxis_title=graph.get("y_axis_label", ""),
        template="plotly_white", font=dict(family="Arial, sans-serif", size=15),
        colorway=colors,
        # Plotly's SVG legend can clip/misorder Hebrew. Render an HTML legend
        # outside the chart, with explicit RTL and the exact same colors.
        showlegend=False,
        hovermode="closest" if kind == "scatter" else "x unified",
        height=450, margin=dict(l=65, r=40, t=82, b=72),
        barmode="group",
    )
    if kind == "histogram":
        fig.update_layout(bargap=0.04)
    if kind != "pie":
        fig.update_yaxes(showgrid=True, zeroline=False, gridcolor="#e8edf2")
    return fig


def normalized_visual(answer, catalog):
    """Return a safe JSON-serializable graphic descriptor for Streamlit session state."""
    if answer.mode == "slide":
        if answer.source_pdf not in catalog:
            raise ValueError("לא זוהתה מצגת מקורית זמינה להצגה. ציין את שם המצגת ומספר השקופית.")
        if answer.slide_number < 1 or answer.slide_number > catalog[answer.source_pdf]:
            raise ValueError("לא זוהה מספר שקופית תקין. ציין את מספר השקופית.")
        return {"type": "slide", "pdf": answer.source_pdf, "page": answer.slide_number}
    if answer.mode == "chart":
        graphic = {
            "type": "chart",
            "chart_type": answer.chart_type,
            "title": answer.title,
            "x_axis_label": answer.x_axis_label,
            "y_axis_label": answer.y_axis_label,
            "illustrative": answer.illustrative,
            "source_note": answer.source_note,
            "series": [series.model_dump() for series in answer.series],
        }
        build_plotly_figure(graphic)  # validation before storing or displaying
        return graphic
    return None


def chart_legend_html(graph):
    """Build a safe browser-native RTL legend aligned with Plotly trace colors.

    Rendering legend labels in regular HTML (not Plotly SVG) prevents Hebrew
    names from being clipped or appearing in the wrong visual order.
    """
    from html import escape

    kind = graph.get("chart_type")
    series = graph.get("series", [])
    if kind == "pie":
        if not series:
            return ""
        labels = [str(point["x"]) for point in series[0].get("points", [])]
    elif len(series) > 1:
        labels = [str(item.get("name") or f"קבוצה {i+1}") for i, item in enumerate(series)]
    else:
        return ""  # For a single series, a legend usually adds no information.

    entries = []
    for idx, label in enumerate(labels):
        color = CHART_COLORS[idx % len(CHART_COLORS)]
        if kind == "line":
            symbol = (
                f'<span aria-hidden="true" style="display:inline-block; flex:none; '
                f'width:25px; border-top:3px solid {color};"></span>'
            )
        elif kind == "scatter":
            symbol = (
                f'<span aria-hidden="true" style="display:inline-block; flex:none; '
                f'width:11px; height:11px; border-radius:50%; background:{color};"></span>'
            )
        else:
            symbol = (
                f'<span aria-hidden="true" style="display:inline-block; flex:none; '
                f'width:13px; height:13px; border-radius:2px; background:{color};"></span>'
            )
        entries.append(
            '<span role="listitem" style="display:inline-flex; direction:rtl; '
            'align-items:center; gap:8px; white-space:nowrap;">'
            + symbol + '<bdi dir="auto">' + escape(label) + '</bdi></span>'
        )

    return (
        '<div role="list" aria-label="מקרא הגרף" dir="rtl" '
        'style="display:flex; direction:rtl; flex-wrap:wrap; '
        'justify-content:center; align-items:center; gap:10px 24px; '
        'padding:0 8px 16px; font-size:15px; line-height:1.6;">'
        + "".join(entries) + '</div>'
    )


def render_graphic(graphic, catalog):
    if not graphic:
        return
    if graphic["type"] == "slide":
        data = original_slide_png(graphic["pdf"], graphic["page"], catalog)
        st.image(data, caption=f"שקופית מקורית: {graphic['pdf']} — עמוד {graphic['page']}",
                 use_container_width=True)
    elif graphic["type"] == "chart":
        fig = build_plotly_figure(graphic)
        st.plotly_chart(fig, use_container_width=True,
                        config={"displaylogo": False, "responsive": True})
        legend_html = chart_legend_html(graphic)
        if legend_html:
            st.markdown(legend_html, unsafe_allow_html=True)
        if graphic.get("illustrative"):
            st.caption("הערכים בגרף הם נתוני המחשה, ולא תוצאות של מחקר אמפירי.")
        if graphic.get("source_note"):
            st.caption(graphic["source_note"])


def graphic_history_note(graphic):
    if graphic["type"] == "slide":
        return f"\n[הוצגה שקופית: {graphic['pdf']}, עמוד {graphic['page']}]."
    return "\n[נתוני הגרף שהוצג: " + json.dumps(graphic, ensure_ascii=False)[:4200] + "]"


# Cache state and file availability.
try:
    manifest = get_manifest()
    course_resources = get_course_resources(manifest)
    fingerprint = course_fingerprint(manifest, system_instruction)
    course_cache_name, _ = get_or_create_course_cache(
        fingerprint, system_instruction, course_resources
    )
    materials_error = None
except Exception as exc:
    course_cache_name = None
    materials_error = f"{type(exc).__name__}: {exc}"
    course_resources = []

try:
    slide_catalog = get_slide_catalog(manifest) if materials_error is None else {}
except Exception:
    slide_catalog = {}


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


def generate_response_with_retry(client, messages, cache_name):
    try:
        return generate_response(client, messages, cache_name)
    except Exception as first_error:
        if cache_name and is_missing_cache_error(first_error):
            get_or_create_course_cache.clear()
            st.info("הקאש הישן אינו זמין כרגע; קורא את חומרי הקורס ישירות.")
            return generate_response(client, messages, None)
        raise


# Temporary benchmark, accessible only with the one-time benchmark code.
if hashlib.sha256(st.query_params.get("cache_benchmark", "").encode()).hexdigest() == "b2d922ded309e6da79684a3f9c386b5da450835846b7be25b33c51afb866a481":
    st.subheader("מדידת זמני תגובה")
    if materials_error or not course_cache_name:
        st.error("חומרי הקורס או המטמון אינם זמינים למדידה.")
        st.stop()
    if st.button("התחל מדידה"):
        client = make_client()
        questions = [
            "מהו תוקף מבחין?",
            "מה ההבדל בין דגימה מקרית פשוטה לדגימה שיטתית?",
            "מה ההבדל בין תוקף פנימי לתוקף חיצוני?",
            "מה ההבדל בין מהימנות לתוקף של כלי מדידה?",
            "מה ההבדל בין הגדרה נומינלית להגדרה אופרציונלית?",
            "מה ההבדל בין מערך בין-נבדקי למערך תוך-נבדקי?",
        ]
        results = []
        with st.spinner("מודד 12 תשובות"):
            new_cache = None
            try:
                # Use the application's normal cache creation path with a unique fingerprint.
                started = time.perf_counter()
                new_cache, _ = get_or_create_course_cache(
                    uuid.uuid4().hex, system_instruction, course_resources
                )
                creation_seconds = round(time.perf_counter() - started, 3)
            finally:
                if new_cache:
                    try:
                        client.caches.delete(name=new_cache)
                    except Exception:
                        st.warning("מטמון המדידה יפוג לפי זמן התפוגה הרגיל.")
            st.write({"cache_creation_and_lookup_seconds": creation_seconds if new_cache else None})
            for index, question in enumerate(questions, start=1):
                messages = [{"role": "user", "content": question + " ענה בעברית בשניים עד שלושה משפטים."}]
                modes = [("explicit", course_cache_name), ("no_explicit", None)]
                if index % 2 == 0:
                    modes.reverse()
                for mode, cache in modes:
                    started = time.perf_counter()
                    try:
                        response = generate_response(client, messages, cache)
                    except Exception as exc:
                        results.append({"question": index, "mode": mode, "error": type(exc).__name__})
                        continue
                    seconds = round(time.perf_counter() - started, 3)
                    usage = response.usage_metadata
                    results.append({
                        "question": index, "mode": mode, "seconds": seconds,
                        "cached": getattr(usage, "cached_content_token_count", None) or 0,
                        "input": getattr(usage, "prompt_token_count", None),
                        "output": getattr(usage, "candidates_token_count", None),
                        "thoughts": getattr(usage, "thoughts_token_count", None),
                    })
        st.json(results)
    st.stop()


# Text sharing: recipient receives only the chosen answer, not the whole conversation.
def reply_share_actions(answer, question=""):
    if not answer:
        return

    if question:
        heading = "שאלה ותשובה מתוך שיבוט מחקר:"
        text = f"שאלה:\n{question}\n\nתשובה:\n{answer}"
        copy_label = "העתק שאלה ותשובה"
    else:
        heading = "תשובה מתוך שיבוט מחקר:"
        text = answer
        copy_label = "העתק תשובה"

    share_url = "https://wa.me/?text=" + quote(f"{heading}\n\n{text}")
    share, copy = st.columns(2)
    with share:
        if len(share_url) <= 20_000:  # App limit for the encoded share URL.
            st.link_button("שתף ב-WhatsApp", share_url, use_container_width=True)
        else:
            st.caption("קישור השיתוף ארוך מדי. אפשר להעתיק את הטקסט ולהדביק אותו בוואטסאפ.")
    with copy:
        with st.popover(copy_label, use_container_width=True):
            st.caption("לחץ על סמל ההעתקה כדי להעתיק את הטקסט במלואו.")
            st.code(text, language=None, wrap_lines=True)

# Render all messages, including the original slides and Plotly figures, on reruns.
latest_question = ""
for message in st.session_state.messages:
    if message["role"] == "user":
        latest_question = str(message.get("content", ""))
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("files"):
            st.caption("📄 קבצים מצורפים: " + ", ".join(f["name"] for f in message["files"]))
        if message.get("graphic"):
            try:
                render_graphic(message["graphic"], slide_catalog)
            except Exception as exc:
                st.caption(f"לא ניתן להציג מחדש את הגרף: {exc}")
        if message.get("role") == "assistant":
            reply_share_actions(str(message.get("content", "")), latest_question)


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

    new_message = {
        "id": uuid.uuid4().hex,
        "role": "user", "content": user_input, "files": current_files,
    }
    st.session_state.messages.append(new_message)
    queue_for_storage(new_message)
    with st.chat_message("user"):
        st.markdown(user_input)
        if current_files:
            st.caption("📄 קבצים מצורפים: " + ", ".join(f["name"] for f in current_files))

    with st.chat_message("assistant"):
        with st.spinner("מנתח את השאלה..."):
            try:
                graphic = None
                if is_visual_request(user_input, st.session_state.messages):
                    try:
                        answer = make_visual_response(
                            client, st.session_state.messages, course_cache_name, slide_catalog
                        )
                        bot_reply = answer.explanation or "להלן ההמחשה המבוקשת."
                        try:
                            graphic = normalized_visual(answer, slide_catalog)
                        except ValueError as data_error:
                            graphic = None
                            bot_reply = (
                                "לא הצלחתי להציג גרף או שקופית באופן אמין: "
                                + str(data_error)
                                + "\n\n" + (answer.explanation if answer.mode == "text" else
                                               "אפשר לציין את שם המצגת ומספר השקופית, או לבקש גרף המחשה חדש.")
                            )
                    except Exception:
                        # Never let a visualization failure break ordinary Q&A.
                        # The student receives a normal answer and a short diagnostic.
                        response = generate_response_with_retry(
                            client, st.session_state.messages, course_cache_name
                        )
                        bot_reply = response.text or "לא התקבלה תשובה טקסטואלית מהמודל."
                        st.info("לא ניתן היה להציג גרף בבקשה זו; התשובה המילולית מוצגת כרגיל.")
                else:
                    response = generate_response_with_retry(
                        client, st.session_state.messages, course_cache_name
                    )
                    bot_reply = response.text or "לא התקבלה תשובה טקסטואלית מהמודל."

                st.markdown(bot_reply)
                if graphic:
                    render_graphic(graphic, slide_catalog)
                assistant_message = {
                    "id": uuid.uuid4().hex,
                    "role": "assistant", "content": bot_reply, "graphic": graphic,
                }
                st.session_state.messages.append(assistant_message)
                queue_for_storage(assistant_message)
                reply_share_actions(bot_reply, user_input)
                if st.session_state.pending_messages:
                    st.warning("ההודעות עדיין לא נשמרו במסד הנתונים. השאר את הדף פתוח.")
            except Exception as exc:
                st.error(f"אירעה שגיאה בשליחת ההודעה: {type(exc).__name__}: {exc}")
