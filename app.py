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

# בדיקת מפתח API
if "GEMINI_API_KEY" not in st.secrets:
    st.error("שגיאה: מפתח ה-GEMINI_API_KEY לא הוגדר בהגדרות ה-Secrets.")
    st.stop()

api_key = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=api_key)

# --- מנגנון אבטחה לסרגל המרצה ---
is_lecturer = False
if "LECTURER_PASSWORD" in st.secrets:
    st.sidebar.title("🔐 כניסת מרצה")
    entered_password = st.sidebar.text_input("הכנס סיסמת ניהול:", type="password")
    if entered_password == st.secrets["LECTURER_PASSWORD"]:
        is_lecturer = True
        st.sidebar.success("מחובר כמרצה!")
    elif entered_password:
        st.sidebar.error("סיסמה שגויה")

if "lecturer_corrections" not in st.session_state:
    st.session_state.lecturer_corrections = []

if is_lecturer:
    st.sidebar.markdown("---")
    st.sidebar.title("🔒 אזור בקרה למרצה")
    new_correction = st.sidebar.text_input("הוסף הערה או תיקון למודל:")
    if st.sidebar.button("הוסף תיקון למערכת"):
        if new_correction:
            st.session_state.lecturer_corrections.append(new_correction)
            if "chat" in st.session_state:
                del st.session_state.chat
            st.sidebar.success("ההערה נוספה ונשמרה!")
            st.rerun()

    if st.session_state.lecturer_corrections:
        with st.sidebar.expander(f"📋 תיקונים פעילים ({len(st.session_state.lecturer_corrections)})"):
            for i, corr in enumerate(st.session_state.lecturer_corrections):
                st.markdown(f"**{i+1}.** {corr}")
            if st.button("נקה את כל התיקונים"):
                st.session_state.lecturer_corrections = []
                if "chat" in st.session_state:
                    del st.session_state.chat
                st.rerun()

# --- אזור העלאת קבצים ---
st.sidebar.markdown("---")
st.sidebar.title("📁 העלאת קבצים")
uploaded_file = st.sidebar.file_uploader(
    "העלה קובץ (PDF, תמונה או טקסט)", 
    type=["pdf", "png", "jpg", "jpeg", "txt"]
)

# --- הנחיות מערכת קפדניות למניעת שגיאות והמצאת מסיחים ---
base_instruction = (
    "אתה מורה פרטי אקדמי מומחה לקורס בשיטות מחקר ופסיכומטריקה. "
    "חוקי ברזל לפתרון מבחנים ושאלות רב-ברירתיות (אמריקאיות):\n"
    "1. היצמד אך ורק לטקסט המקורי של השאלה ולמסיחים (אפשרויות התשובה) כפי שהוצגו לך. לעולם אל תמציא מסיחים או אפשרויות שלא קיימים בשאלה.\n"
    "2. שמור על דיוק מוחלט במושגים מדעיים, שמות חוקרים (למשל קרונבאך) וטרמינולוגיה מקצועית.\n"
    "3. תן תשובות מנומקות, אקדמיות ומדויקות המושתתות על עקרונות התוקף, המהימנות ותורת המבחנים הקלאסית."
)

if st.session_state.lecturer_corrections:
    corrections_block = "\n\nהערות ותיקונים נוספים שהוגדרו על ידי המרצה (יש ליישם תמיד!):\n" + "\n".join([f"- {c}" for c in st.session_state.lecturer_corrections])
    full_system_instruction = base_instruction + corrections_block
else:
    full_system_instruction = base_instruction

try:
    model = genai.GenerativeModel(
        model_name="gemini-3.5-flash-lite",
        system_instruction=full_system_instruction
    )
except Exception as e:
    st.error(f"שגיאה בטעינת המודל: {e}")
    st.stop()

if "chat" not in st.session_state:
    st.session_state.chat = model.start_chat(history=[])

file_content_to_send = None

if uploaded_file is not None:
    file_ext = uploaded_file.name.split('.')[-1].lower()
    try:
        if file_ext in ["png", "jpg", "jpeg"]:
            file_content_to_send = Image.open(uploaded_file)
            st.sidebar.success(f"התמונה '{uploaded_file.name}' נטענה בהצלחה!")
        elif file_ext == "pdf":
            # טיפ: עבור PDF, אם הטקסט מתהפך, מומלץ להעלות את המבחן כתמונות (צילומי מסך של העמודים) 
            # אך נשמרת כאן תמיכה בטקסט נקי מבלי היפוך שגוי שמעוות שמות
            reader = pypdf.PdfReader(uploaded_file)
            pdf_text = ""
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    pdf_text += text + "\n"
            file_content_to_send = f"\n[תוכן מקובץ PDF - {uploaded_file.name}]:\n{pdf_text}\n"
            st.sidebar.success(f"קובץ ה-PDF '{uploaded_file.name}' פוענח בהצלחה!")
        elif file_ext == "txt":
            file_content_to_send = f"\n[תוכן מקובץ טקסט - {uploaded_file.name}]:\n{uploaded_file.getvalue().decode('utf-8')}\n"
            st.sidebar.success(f"קובץ הטקסט '{uploaded_file.name}' נטען בהצלחה!")
    except Exception as e:
        st.sidebar.error(f"שגיאה בעיבוד הקובץ: {e}")

# הצגת היסטוריית השיחה
for message in st.session_state.chat.history:
    role = "user" if message.role == "user" else "assistant"
    with st.chat_message(role):
        for part in message.parts:
            if hasattr(part, "text") and part.text:
                if not part.text.startswith("\n[תוכן מקובץ"):
                    st.markdown(part.text)

# תיבת הקלט
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
