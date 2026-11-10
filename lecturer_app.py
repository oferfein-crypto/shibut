"""Private lecturer console for the Shibut Mehkar teaching assistant."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import streamlit as st

import chat_store
from lecturer_instructions import (
    github_settings,
    load_lecturer_instructions_record,
    save_lecturer_instructions,
)


st.set_page_config(page_title="שיבוט מחקר | ניהול למרצה", page_icon="📚", layout="wide")
st.markdown(
    """
    <style>
    [data-testid="stMain"] {
        direction: rtl;
        text-align: right;
    }
    [data-testid="stMain"] :is(p, h1, h2, h3, label, textarea, input) {
        direction: rtl;
        text-align: right;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
st.title("שיבוט מחקר | ניהול למרצה")

try:
    allowed_email = st.secrets.get("LECTURER_EMAIL", "").strip().casefold()
    auth_configured = bool(st.secrets.get("auth"))
except Exception:
    allowed_email = ""
    auth_configured = False
if not allowed_email or not auth_configured:
    st.info("יש להשלים את הגדרות הכניסה של אפליקציית המרצה.")
    st.stop()

if not st.user.is_logged_in:
    if st.button("התחבר באמצעות Google", type="primary"):
        st.login()
    st.stop()

if st.button("התנתק"):
    st.logout()
if (
    st.user.get("email_verified") is not True
    or str(st.user.get("email", "")).strip().casefold() != allowed_email
):
    st.error("לחשבון Google זה אין גישה לאפליקציית המרצה.")
    st.stop()


def edit_instructions():
    if github_settings() is None:
        st.info("יש להגדיר את המאגר הפרטי של ההנחיות ב-Secrets של אפליקציית המרצה.")
        return
    if st.session_state.pop("instructions_saved", False):
        st.session_state.pop("instructions_draft", None)
        st.success("ההנחיות נשמרו. האפליקציה לסטודנטים תטען אותן ברענון הבא בתוך כדקה.")
    if st.button("טען מחדש מ-GitHub והשלך טיוטה"):
        load_lecturer_instructions_record.clear()
        st.session_state.pop("instructions_record", None)
        st.session_state.pop("instructions_draft", None)
    if "instructions_record" not in st.session_state:
        try:
            st.session_state.instructions_record = load_lecturer_instructions_record()
        except Exception:
            st.error("טעינת ההנחיות נכשלה. בדוק את המאגר, הענף והרשאת הקריאה.")
            return
    instructions, sha = st.session_state.instructions_record
    with st.form("edit_instructions"):
        draft = st.text_area("הנחיות נוספות לכל הסטודנטים", value=instructions, height=400,
                             key="instructions_draft")
        submitted = st.form_submit_button("שמור הנחיות", type="primary")
    if submitted:
        try:
            save_lecturer_instructions(draft, sha)
        except RuntimeError as exc:
            st.error(str(exc))
        except Exception:
            st.error("שמירת ההנחיות נכשלה. בדוק שלחשבון ה-GitHub יש הרשאת כתיבה.")
        else:
            st.session_state.pop("instructions_record", None)
            st.session_state.instructions_saved = True
            st.rerun()


@st.cache_resource(show_spinner=False)
def get_chat_db(credential_json):
    return chat_store.firestore_client(credential_json)


def show_conversations():
    credential_json = st.secrets.get("FIREBASE_SERVICE_ACCOUNT_JSON", "")
    try:
        chat_db = get_chat_db(credential_json) if credential_json else None
    except Exception:
        chat_db = None
    st.subheader("📚 מאגר השיחות — לוח בקרה למרצה")
    if chat_db is None:
        st.error("Firestore אינו מחובר. הגדר FIREBASE_SERVICE_ACCOUNT_JSON ב-Secrets.")
    else:
        try:
            recent = sorted(
                chat_store.all_threads(chat_db),
                key=lambda row: row.get("updated_at") or datetime.min.replace(tzinfo=timezone.utc),
                reverse=True,
            )
            total_recent = len(recent)
            google_recent = sum(row.get("auth_mode") == "google" for row in recent)
            guest_recent = total_recent - google_recent
            c1, c2, c3 = st.columns(3)
            c1.metric("שיחות שמורות", total_recent)
            c2.metric("עם Google", google_recent)
            c3.metric("שיחות אורח", guest_recent)
            if recent:
                per_day = {}
                for row in recent:
                    stamp = row.get("created_at")
                    if stamp:
                        day = stamp.astimezone(ZoneInfo("Asia/Jerusalem")).date().isoformat()
                        per_day[day] = per_day.get(day, 0) + 1
                if per_day:
                    st.caption("שיחות חדשות לפי יום")
                    days = sorted(per_day)
                    st.bar_chart({"תאריך": days, "שיחות": [per_day[d] for d in days]},
                                 x="תאריך", y="שיחות")

                filter_mode = st.selectbox("סוג התחברות", ["הכול", "Google", "אורח"])
                title_query = st.text_input("חיפוש בכותרת השיחה", "").strip().lower()
                with st.expander("סינון לפי תאריכים"):
                    earliest = min(
                        (r["created_at"].astimezone(ZoneInfo("Asia/Jerusalem")).date()
                         for r in recent if r.get("created_at")),
                        default=datetime.now(ZoneInfo("Asia/Jerusalem")).date(),
                    )
                    start_date = st.date_input("מתאריך", value=earliest, key="admin_date_start")
                    end_date = st.date_input(
                        "עד תאריך", value=datetime.now(ZoneInfo("Asia/Jerusalem")).date(),
                        key="admin_date_end",
                    )
                display_rows = [
                    row for row in recent
                    if (filter_mode == "הכול" or
                        row.get("auth_mode") == ("google" if filter_mode == "Google" else "guest"))
                    and (not title_query or title_query in row.get("title", "").lower())
                    and (not row.get("created_at") or
                         start_date <= row["created_at"].astimezone(ZoneInfo("Asia/Jerusalem")).date() <= end_date)
                ]
                with st.expander("חיפוש בטקסט של שיחות"):
                    st.caption("החיפוש עובר על כל השיחות שנכללות בסינון, "
                               "והוא עשוי לצרוך קריאות נוספות במסד הנתונים.")
                    term = st.text_input("מילה או ביטוי מתוך ההודעות", key="admin_fulltext_term")
                    if st.button("חפש בתמלילים", key="admin_fulltext_search") and term.strip():
                        results = []
                        for row in display_rows:
                            if any(term.casefold() in str(msg.get("content", "")).casefold()
                                   for msg in chat_store.read_messages(chat_db, row["id"])):
                                results.append(row["id"])
                        st.session_state.admin_content_results = results
                        st.session_state.admin_content_search_term = term
                    if "admin_content_results" in st.session_state:
                        st.caption(
                            f"נמצאו {len(st.session_state.admin_content_results)} שיחות המכילות "
                            f"'{st.session_state.get('admin_content_search_term', '')}' "
                            "(בהתאם למסננים בזמן ביצוע החיפוש)."
                        )
                        if st.checkbox("הצג להלן רק שיחות שנמצאו בחיפוש", key="admin_content_filter"):
                            matches = set(st.session_state.admin_content_results)
                            display_rows = [row for row in display_rows if row["id"] in matches]

                st.caption(f"נמצאו {len(display_rows)} שיחות לאחר הסינון")
                if display_rows:
                    choices = {r["id"]: r for r in display_rows}
                    chosen = st.selectbox(
                        "עיון בתמליל שיחה", list(choices),
                        format_func=lambda ident: (
                            f"{choices[ident].get('title','שיחה')[:70]} — "
                            f"{'Google' if choices[ident].get('auth_mode') == 'google' else 'אורח'}"
                        ),
                        key="admin_thread_select",
                    )
                    if chosen:
                        selected = choices[chosen]
                        st.caption("מזהה משתמש אנונימי: " + selected.get("owner_key", ""))
                        for item in chat_store.read_messages(chat_db, chosen):
                            with st.chat_message("user" if item.get("role") == "user" else "assistant"):
                                st.markdown(item.get("content", ""))
                                if item.get("graphic"):
                                    st.caption("התשובה כוללת גרף או שקופית. נתוני התצוגה נשמרו.")
                        st.download_button(
                            "הורד שיחה זו (CSV)",
                            chat_store.transcript_csv(chat_db, [selected]),
                            file_name=f"shibut_thread_{chosen}.csv",
                            mime="text/csv",
                        )
            if st.button("הכן ייצוא של כל השיחות (CSV)", key="admin_export_all"):
                with st.spinner("מייצא את כל השיחות השמורות; פעולה זו צורכת קריאות Firestore..."):
                    st.session_state.admin_export_data = chat_store.transcript_csv(
                        chat_db, recent
                    )
            if st.session_state.get("admin_export_data"):
                st.download_button(
                    "הורד את כל השיחות", st.session_state.admin_export_data,
                    file_name="shibut_all_conversations.csv", mime="text/csv",
                    key="admin_download_all",
                )
        except Exception:
            st.error("לא ניתן לטעון כרגע את נתוני מאגר השיחות. בדוק את חיבור Firestore.")
    st.markdown("---")

section = st.radio("תצוגה", ["עריכת הנחיות", "לוח שיחות"], horizontal=True)
if section == "עריכת הנחיות":
    edit_instructions()
else:
    show_conversations()
