import streamlit as st
import google.generativeai as genai
from PIL import Image
import pypdf

st.set_page_config(page_title="שיבוט מחקר - המורה הפרטי שלך", page_icon="🎓")

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

st.title("שיבוט מחקר - המורה הפרטי שלך")

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

# אזור העלאת קבצים בסרגל הצדי (Sidebar) עם הכותרת המעודכנת
st.sidebar.title("📁 העלאת קבצים")
uploaded_file = st.sidebar.file_uploader(
    "העלה קובץ (PDF, תמונה או טקסט)", 
    type=["pdf", "png", "jpg", "jpeg", "txt"]
)

file_content_to_send = None

if uploaded_file is not None:
    file_ext = uploaded_file.name.split('.')[-1].lower()
    try:
        if file_ext in ["png", "jpg", "jpeg"]:
            file_content_to_send = Image.open(uploaded_file)
            st.sidebar.success(f"התמונה '{uploaded_file.name}' נטענה בהצלחה!")
        elif file_ext == "pdf":
            reader = pypdf.PdfReader(uploaded_file)
            pdf_text = ""
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    fixed_lines = [line[::-1] for line in text.split('\n')]
                    pdf_text += "\n".join(fixed_lines) + "\n"
            file_content_to_send = f"\n[תוכן מקובץ PDF - {uploaded_file.name}]:\n{pdf_text}\n"
            st.sidebar.success(f"קובץ ה-PDF '{uploaded_file.name}' פוענח בהצלחה!")
        elif file_ext == "txt":
            file_content_to_send = f"\n[תוכן מקובץ טקסט - {uploaded_file.name}]:\n{uploaded_file.getvalue().decode('utf-8')}\n"
            st.sidebar.success(f"קובץ הטקסט '{uploaded_file.name}' נטען בהצלחה!")
    except Exception as e:
        st.sidebar.error(f"שגיאה בעיבוד הקובץ: {e}")

# הצגת היסטוריית ההודעות (הסתרת טקסט הקובץ הגולמי מהבועות)
for message in st.session_state.chat.history:
    role = "user" if message.role == "user" else "assistant"
    with st.chat_message(role):
        for part in message.parts:
            if hasattr(part, "text") and part.text:
                if not part.text.startswith("\n[תוכן מקובץ"):
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
                payload = [user_input]
                if file_content_to_send is not None:
                    payload.append(file_content_to_send)
                
                response = st.session_state.chat.send_message(payload)
                st.markdown(response.text)
    except Exception as e:
        st.error(f"אירעה שגיאה בשליחת ההודעה לשרת של גוגל: {e}")
