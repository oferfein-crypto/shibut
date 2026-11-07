import streamlit as st
from google import genai
from google.genai import types
import pypdf
import os
import shutil

st.set_page_config(page_title="שיבוט מחקר - המורה הפרטי שלך", page_icon="🎓")

# עיצוב כיווניות RTL
st.markdown("""
    <style>
    .stChatMessage, .stChatMessage * {
        direction: rtl !important;
        text-align: right !important;
    }
    .stChatInput textarea {
        direction: rtl !important;
        text-align: right !important;
    }
    </style>
""", unsafe_allow_html=True)

st.title("שיבוט מחקר - המורה הפרטי שלך")

if "GEMINI_API_KEY" not in st.secrets:
    st.error("שגיאה: מפתח ה-GEMINI_API_KEY לא הוגדר בהגדרות ה-Secrets.")
    st.stop()

# אתחול הלקוח עם החבילה החדשה
client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])

# --- סרגל צדי: קבצים להעלאה ומצב מרצה ---
st.sidebar.markdown("---")
st.sidebar.title("📁 קבצים להעלאה")
exam_files = st.sidebar.file_uploader(
    "העלה מבחן, תרגיל, שאלה או כל קובץ אחר", 
    type=["pdf", "png", "jpg", "jpeg", "txt"],
    accept_multiple_files=True
)

st.sidebar.markdown("---")
st.sidebar.title("🛠️ אזור מרצה")
lecturer_mode_checkbox = st.sidebar.checkbox("הפעל מצב מרצה")

lecturer_authenticated = False
if lecturer_mode_checkbox:
    entered_password = st.sidebar.text_input("הכנס סיסמת מרצה:", type="password")
    if "LECTURER_PASSWORD" in st.secrets and entered_password == st.secrets["LECTURER_PASSWORD"]:
        lecturer_authenticated = True
        st.sidebar.success("הזדהות הצליחה!")
    else:
        if entered_password:
            st.sidebar.error("סיסמה שגויה.")

# --- הנחיות המערכת ---
system_instruction = """
תפקיד ומטרה:
אתה מורה פרטי אקדמי ועוזר הוראה לקורס אקדמי בשיטות מחקר לתלמידי תואר ראשון בפסיכולוגיה. תפקידך לסייע לסטודנטים להבין את החומר, להתכונן למבחנים ולתרגל מושגים.

בסיס הידע:
כל התשובות שלך חייבות להתבסס בעיקר על הקבצים והחומרים שהועלו לקורס זה. 
אם סטודנט שואל על נושא שאינו מופיע בחומרים, ענה בנימוס בדיוק במילים אלו: "נושא זה אינו מופיע בחומרי הקורס שהועלו." 

חוקים והנחיות לגבי חומרי הקורס:
1. המצגות הן החומר העיקרי והמעודכן ביותר.
2. יש גם קובץ בשם "שיטות מחקר - מאוחד" שהוא מפורט יותר מהמצגת, אך אם יש סתירה בינו לבין המצגת, העדף את המצגת.
3. אם יש סתירה בין חומר אחר שאינו מכיר והמצגת, העדף את המצגת.
4. בין הקבצים שהועלו יש גם תרגילים ופתרונות להם, למד גם אותם, ומבחנים.
5. לכל מבחן שתי גרסאות: גרסא מעורבלת וגרסא (נקראת טופס 0) שבה תמיד התשובה הנכונה היא הראשונה (א), אלא אם כן כתוב אחרת בדפי ההסבר על המבחנים.
6. בשניים מהמבחנים יש גם פתרונות מוסברים - למד גם אותם.
"""

# --- טעינת הקבצים והעלאתם הישירה לשרת ---
@st.cache_resource
def get_or_create_course_chat():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    folder_path = os.path.join(current_dir, "course_files")
    
    uploaded_files_info = []
    gemini_files = []
    
    if os.path.exists(folder_path):
        files = os.listdir(folder_path)
        for index, filename in enumerate(files):
            file_path = os.path.join(folder_path, filename)
            if filename.lower().endswith((".pdf", ".txt", ".pptx")):
                try:
                    ext = os.path.splitext(filename)[1]
                    safe_temp_name = f"course_file_{index}{ext}"
                    safe_temp_path = os.path.join(current_dir, safe_temp_name)
                    
                    shutil.copyfile(file_path, safe_temp_path)
                    g_file = client.files.upload(file=safe_temp_path)
                    gemini_files.append(g_file)
                    uploaded_files_info.append(f"✅ הועלה בהצלחה לשרת: {filename}")
                    
                    if os.path.exists(safe_temp_path):
                        os.remove(safe_temp_path)
                except Exception as e:
                    uploaded_files_info.append(f"❌ שגיאה בהעלאת {filename}: {e}")
    else:
        uploaded_files_info.append(f"⚠️ אזהרה: התיקייה course_files לא נמצאה.")

    target_model = 'gemini-2.5-flash'
    
    # פתיחת צ'אט עם צירוף קבצי הקורס ישירות כרקע ראשוני
    try:
        chat_config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.3
        )
        chat = client.chats.create(model=target_model, config=chat_config)
        return chat, gemini_files, uploaded_files_info, "הקבצים הועלו בהצלחה וזמינים למורה הפרטי!"
    except Exception as e:
        chat = client.chats.create(model=target_model)
        return chat, gemini_files, uploaded_files_info, f"שגיאה באתחול הצ'אט: {e}"

chat_session, course_files_payload, file_status_log, status_msg = get_or_create_course_chat()

# --- לוח בקרה למרצה ---
if lecturer_authenticated:
    st.markdown("---")
    st.subheader("📊 לוח בקרה וניהול למרצה")
    st.success(status_msg)
    st.write("**סטטוס קבצי הקורס בתיקייה:**")
    for log_item in file_status_log:
        st.text(log_item)
    st.markdown("---")

# הצגת היסטוריית השיחה
for message in chat_session.get_history():
    role = "user" if message.role == "user" else "assistant"
    with st.chat_message(role):
        for part in message.parts:
            if hasattr(part, "text") and part.text:
                st.markdown(part.text)

# עיבוד קבצים שהסטודנט מעלה בצד
exam_payload = []
if exam_files:
    for uploaded_file in exam_files:
        try:
            temp_path = os.path.join(".", "student_upload_" + uploaded_file.name)
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            g_uploaded = client.files.upload(file=temp_path)
            exam_payload.append(g_uploaded)
            
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception as e:
            st.sidebar.error(f"שגיאה בהעלאת הקובץ {uploaded_file.name}: {e}")

# תיבת הקלט של המשתמש
if user_input := st.chat_input("שאל שאלה על החומר או בקש עזרה בפתרון השאלות..."):
    with st.chat_message("user"):
        st.markdown(user_input)
        if exam_files:
            file_names = ", ".join([f.name for f in exam_files])
            st.caption(f"📄 קבצים מצורפים: {file_names}")

    try:
        with st.chat_message("assistant"):
            with st.spinner("חושב ומנתח מתוך חומרי הקורס..."):
                # שילוב קבצי הקורס ברקע יחד עם השאלה וקבצי הסטודנט אם ישנם
                message_content = []
                # הוספת קבצי הקורס כהקשר להודעה הראשונה או לכל שאלה
                if course_files_payload and len(chat_session.get_history()) == 0:
                    message_content.extend(course_files_payload)
                
                message_content.append(user_input)
                if exam_payload:
                    message_content.extend(exam_payload)
                
                response = chat_session.send_message(message_content)
                st.markdown(response.text)
    except Exception as e:
        st.error(f"אירעה שגיאה בשליחת ההודעה לשרת: {e}")
