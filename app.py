import streamlit as st
import google.generativeai as genai
import tempfile
import os

st.set_page_config(page_title="שיבוט מחקר - המורה הפרטי שלך!", page_icon="🎓")

# עיצוב כיווניות RTL ויישור לימין
st.markdown("""
    <style>
    .stChatMessage, .stChatMessage * {
        direction: rtl !important;
        text-align: right !important;
    }
    ul, ol, li {
        direction: rtl !important;
        text-align: right !important;
        padding-right: 20px !important;
        padding-left: 0px !important;
    }
    .stChatInput textarea {
        direction: rtl !important;
        text-align: right !important;
    }
    </style>
""", unsafe_allow_html=True)

st.title("🎓 מורה פרטי אישי לקורס")

# בדיקה האם המפתח קיים בהגדרות
if "GEMINI_API_KEY" not in st.secrets:
    st.error("שגיאה: מפתח ה-GEMINI_API_KEY לא הוגדר בהגדרות ה-Secrets של Streamlit.")
    st.stop()

api_key = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=api_key)

# שימוש במודל
try:
    model = genai.GenerativeModel("gemini-3.5-flash-lite")
except Exception as e:
    st.error(f"שגיאה בטעינת המודל: {e}")
    st.stop()

# ניהול היסטוריית השיחה
if "chat" not in st.session_state:
    st.session_state.chat = model.start_chat(history=[])

# --- הוספת אזור העלאת קבצים בסרגל הצדי (Sidebar) ---
st.sidebar.title("📁 העלאת חומרי לימוד ומבחנים")
uploaded_file = st.sidebar.file_uploader(
    "העלה קובץ (PDF, תמונה או טקסט)", 
    type=["pdf", "png", "jpg", "jpeg", "txt"]
)

file_ref = None
if uploaded_file is not None:
    # שמירה זמנית של הקובץ כדי להעלות אותו לשרת של גוגל
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(uploaded_file.name)[1]) as tmp:
        tmp.write(uploaded_file.getvalue())
        tmp_path = tmp.name
    
    # העלאה למודל (נשמר בזיכרון כדי לא לעלות מחדש בכל הודעה)
    if "uploaded_file_name" not in st.session_state or st.session_state.uploaded_file_name != uploaded_file.name:
        with st.spinner("מעלה את הקובץ למערכת..."):
            file_ref = genai.upload_file(tmp_path)
            st.session_state.file_ref = file_ref
            st.session_state.uploaded_file_name = uploaded_file.name
        st.sidebar.success(f"הקובץ '{uploaded_file.name}' הועלה בהצלחה!")
    else:
        file_ref = st.session_state.get("file_ref")

# הצגת היסטוריית ההודעות
for message in st.session_state.chat.history:
    role = "user" if message.role == "user" else "assistant"
    with st.chat_message(role):
        for part in message.parts:
            if hasattr(part, "text") and part.text:
                st.markdown(part.text)

# תיבת הקלט לסטודנט
if user_input := st.chat_input("שאל שאלה על חומרי הקורס או על הקובץ שהעלאת..."):
    with st.chat_message("user"):
        st.markdown(user_input)
        if uploaded_file is not None:
            st.caption(f"📄 קובץ מצורף פעיל: {uploaded_file.name}")

    try:
        with st.chat_message("assistant"):
            with st.spinner("חושב..."):
                # שליחת הטקסט יחד עם הקובץ (אם קיים) למודל
                content_payload = [user_input]
                if file_ref is not None:
                    content_payload.append(file_ref)
                
                response = st.session_state.chat.send_message(content_payload)
                st.markdown(response.text)
    except Exception as e:
        st.error(f"אירעה שגיאה בשליחת ההודעה לשרת של גוגל: {e}")
