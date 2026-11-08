import streamlit as st
from google import genai
from google.genai import types
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
custom_lecturer_instruction = ""

if lecturer_mode_checkbox:
    entered_password = st.sidebar.text_input("הכנס סיסמת מרצה:", type="password")
    if "LECTURER_PASSWORD" in st.secrets and entered_password == st.secrets["LECTURER_PASSWORD"]:
        lecturer_authenticated = True
        st.sidebar.success("הזדהות הצליחה!")
        
        # שדה הוספת הנחיות מערכת דינמיות למרצה
        st.sidebar.markdown("---")
        custom_lecturer_instruction = st.sidebar.text_area(
            "⚙️ הנחיות מערכת נוספות (לעיני המרצה בלבד):",
            value=st.session_state.get("custom_lecturer_instruction", ""),
            placeholder="הכנס כאן הנחיות נוספות שהמודל יתחשב בהן..."
        )
        st.session_state["custom_lecturer_instruction"] = custom_lecturer_instruction
    else:
        if entered_password:
            st.sidebar.error("סיסמה שגויה.")

# אם המרצה לא מחובר, שומרים את הערך האחרון שהוזן אם קיים בסטייט
if not lecturer_authenticated and "custom_lecturer_instruction" in st.session_state:
    custom_lecturer_instruction = st.session_state["custom_lecturer_instruction"]

# --- הנחיות המערכת המעודכנות ---
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

step_by_step_instruction = "אם אתה מקבל מהסטודנט שאלה, תמיד נתח את השאלה בצורה מעמיקה, הסבר שלב אחר שלב את תהליך החשיבה, והתייחס בקצרה מדוע החלופות האחרות שגויות."

# בניית הנחיית המערכת הסופית כולל תוספות המרצה אם קיימות
system_instruction = f"{base_system_instruction}\n\n{step_by_step_instruction}"
if custom_lecturer_instruction:
    system_instruction += f"\n\nהנחיות נוספות מהמרצה:\n{custom_lecturer_instruction}"

target_model = 'gemini-3.5-flash-lite'

# --- העלאת קבצי הקורס פעם אחת ב-Session (עם עקיפת שמות בעברית) ---
@st.cache_resource
def upload_course_files():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    folder_path = os.path.join(current_dir, "course_files")
    
    client_temp = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
    uploaded_files_info = []
    gemini_files = []
    
    if os.path.exists(folder_path):
        for index, filename in enumerate(os.listdir(folder_path)):
            file_path = os.path.join(folder_path, filename)
            if filename.lower().endswith((".pdf", ".txt", ".pptx", ".png", ".jpg", ".jpeg")):
                try:
                    ext = os.path.splitext(filename)[1]
                    safe_temp_name = f"course_file_{index}{ext}"
                    safe_temp_path = os.path.join(current_dir, safe_temp_name)
                    
                    shutil.copyfile(file_path, safe_temp_path)
                    g_file = client_temp.files.upload(file=safe_temp_path)
                    gemini_files.append(g_file)
                    uploaded_files_info.append(f"✅ הועלה בהצלחה לשרת: {filename}")
                    
                    if os.path.exists(safe_temp_path):
                        os.remove(safe_temp_path)
                except Exception as e:
                    uploaded_files_info.append(f"❌ שגיאה בהעלאת {filename}: {e}")
    else:
        uploaded_files_info.append(f"⚠️ אזהרה: התיקייה course_files לא נמצאה.")
        
    return gemini_files, uploaded_files_info

course_files_payload, file_status_log = upload_course_files()

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- לוח בקרה למרצה ---
if lecturer_authenticated:
    st.markdown("---")
    st.subheader("📊 לוח בקרה וניהול למרצה")
    st.success("המערכת מחוברת עם מודל gemini-3.5-flash-lite, רמת חשיבה 0.5 והנחיות דינמיות פעילות!")
    st.write("**סטטוס קבצי הקורס בתיקייה:**")
    for log_item in file_status_log:
        st.text(log_item)
    st.markdown("---")

# הצגת היסטוריית השיחה מתוך הזיכרון
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# עיבוד קבצים שהסטודנט מעלה בצד (עם עקיפת שמות בעברית)
exam_payload = []
if exam_files:
    for index, uploaded_file in enumerate(exam_files):
        try:
            ext = os.path.splitext(uploaded_file.name)[1]
            safe_student_name = f"student_exam_{index}{ext}"
            temp_path = os.path.join(".", safe_student_name)
            
            with open(temp_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            
            client_temp = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
            g_uploaded = client_temp.files.upload(file=temp_path)
            exam_payload.append(g_uploaded)
            
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception as e:
            st.sidebar.error(f"שגיאה בהעלאת הקובץ {uploaded_file.name}: {e}")

# תיבת הקלט של המשתמש
if user_input := st.chat_input("שאל שאלה על החומר או בקש עזרה בפתרון השאלות..."):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)
        if exam_files:
            file_names = ", ".join([f.name for f in exam_files])
            st.caption(f"📄 קבצים מצורפים: {file_names}")

    try:
        with st.chat_message("assistant"):
            with st.spinner("מנתח את השאלה בצורה מעמיקה ובונה הסבר שלב-אחר-שלב..."):
                # אתחול לקוח חדש ונקי לכל שאלה – מונע לחלוטין את שגיאת 'client has been closed'
                client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
                
                contents = []
                
                # צרוף קבצי הקורס כהקשר רקע למודל
                if course_files_payload:
                    contents.extend(course_files_payload)
                    
                # צרוף קבצי המבחן/תרגיל שהסטודנט העלה כעת
                if exam_payload:
                    contents.extend(exam_payload)
                    
                # צרוף היסטוריית השיחה הקודמת לצורך רציפות
                for m in st.session_state.messages[:-1]:
                    role_str = "סטודנט" if m["role"] == "user" else "מורה"
                    contents.append(f"{role_str}: {m['content']}")
                    
                # צרוף השאלה הנוכחית
                contents.append(user_input)

                response = client.models.generate_content(
                    model=target_model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.5
                    )
                )
                
                bot_reply = response.text
                st.markdown(bot_reply)
                st.session_state.messages.append({"role": "assistant", "content": bot_reply})
                
    except Exception as e:
        st.error(f"אירעה שגיאה בשליחת ההודעה לשרת: {e}")
