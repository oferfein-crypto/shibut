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

# --- ניהול קובץ הנחיות מרצה גלובלי (Persistent Storage) ---
INSTRUCTIONS_FILE = "lecturer_instructions.txt"

def load_lecturer_instructions():
    if os.path.exists(INSTRUCTIONS_FILE):
        with open(INSTRUCTIONS_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def save_lecturer_instructions(text):
    with open(INSTRUCTIONS_FILE, "w", encoding="utf-8") as f:
        f.write(text)

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
custom_lecturer_instruction = load_lecturer_instructions()

if lecturer_mode_checkbox:
    entered_password = st.sidebar.text_input("הכנס סיסמת מרצה:", type="password")
    if "LECTURER_PASSWORD" in st.secrets and entered_password == st.secrets["LECTURER_PASSWORD"]:
        lecturer_authenticated = True
        st.sidebar.success("הזדהות הצליחה!")
        
        st.sidebar.markdown("---")
        st.sidebar.subheader("⚙️ ניהול הנחיות גלובליות")
        
        new_instruction_input = st.sidebar.text_area(
            "הנחיות מערכת נוספות (יוחלו על כל הסטודנטים):",
            value=custom_lecturer_instruction,
            height=150,
            placeholder="הכנס כאן הנחיות שהמודל יתחשב בהן..."
        )
        
        if st.sidebar.button("💾 שמור הנחיות בקובץ הגלובלי"):
            save_lecturer_instructions(new_instruction_input)
            st.sidebar.success("ההנחיות נשמרו בהצלחה ועודכנו לכל המשתמשים!")
            custom_lecturer_instruction = new_instruction_input
            st.rerun()
    else:
        if entered_password:
            st.sidebar.error("סיסמה שגויה.")

# --- הנחיות המערכת ---
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

system_instruction = f"{base_system_instruction}\n\n{step_by_step_instruction}"
if custom_lecturer_instruction:
    system_instruction += f"\n\nהנחיות נוספות מהמרצה (גלובליות):\n{custom_lecturer_instruction}"

# --- הגדרת המודל ויצירת הקאש החיה ---
target_model = 'gemini-3.8-flash'

def get_or_create_course_cache():
    try:
        client_temp = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
        
        # שלב א': בדיקת קאשים קיימים
        try:
            existing_caches = client_temp.caches.list()
            for c in existing_caches:
                return c.name, None
        except Exception:
            pass
            
        # שלב ב': העלאת קבצים ויצירת קאש חדש
        current_dir = os.path.dirname(os.path.abspath(__file__))
        folder_path = os.path.join(current_dir, "course_files")
        uploaded_files = []
        
        if not os.path.exists(folder_path):
            return None, "תיקיית course_files לא נמצאה בשרת."
            
        files_list = os.listdir(folder_path)
        supported_files = [f for f in files_list if f.lower().endswith((".pdf", ".txt", ".pptx", ".png", ".jpg", ".jpeg"))]
        
        if not supported_files:
            return None, "תיקיית course_files ריקה מקבצים נתמכים."
            
        for index, filename in enumerate(supported_files):
            file_path = os.path.join(folder_path, filename)
            ext = os.path.splitext(filename)[1]
            safe_temp_path = os.path.join(current_dir, f"cache_file_{index}{ext}")
            shutil.copy(file_path, safe_temp_path)
            
            g_file = client_temp.files.upload(file=safe_temp_path)
            uploaded_files.append(g_file)
            
            if os.path.exists(safe_temp_path):
                os.remove(safe_temp_path)
                
        # שלב ג': יצירת הקאש מול ה-API של גוגל ותפיסת השגיאה המדויקת
        cache_obj = client_temp.caches.create(
            model=target_model,
            config=types.CreateCachedContentConfig(
                contents=uploaded_files,
                system_instruction=system_instruction,
                ttl="7200s"
            )
        )
        return cache_obj.name, None
        
    except Exception as e:
        return None, str(e)

course_cache_name, cache_creation_error = get_or_create_course_cache()

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- לוח בקרה למרצה ---
if lecturer_authenticated:
    st.markdown("---")
    st.subheader("📊 לוח בקרה וניהול למרצה")
    
    if course_cache_name:
        st.success("המערכת מחוברת עם מודל gemini-3.8-flash ו-Context Caching פעיל!")
    else:
        st.warning("המערכת פועלת עם מודל gemini-3.8-flash (עובדת במצב גיבוי יציב).")
        if cache_creation_error:
            st.error(f"🔍 שגיאת ה-API המדויקת בעת יצירת הקאש:\n\n`{cache_creation_error}`")
    
    with st.expander("🔍 הצג את הנחיות המערכת המלאות שמועברות כרגע למודל"):
        st.code(system_instruction, language="text")
        
    st.markdown("---")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# עיבוד קבצים שהסטודנט מעלה בצד
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
            with st.spinner("מנתח את השאלה..."):
                client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
                
                contents = []
                if exam_payload:
                    contents.extend(exam_payload)
                    
                for m in st.session_state.messages[:-1]:
                    role_str = "סטודנט" if m["role"] == "user" else "מורה"
                    contents.append(f"{role_str}: {m['content']}")
                    
                contents.append(user_input)

                config_params = {
                    "temperature": 0.5,
                    "max_output_tokens": 8192
                }
                
                if course_cache_name:
                    config_params["cached_content"] = course_cache_name
                else:
                    config_params["system_instruction"] = system_instruction

                response = client.models.generate_content(
                    model=target_model,
                    contents=contents,
                    config=types.GenerateContentConfig(**config_params)
                )
                
                bot_reply = response.text
                st.markdown(bot_reply)
                st.session_state.messages.append({"role": "assistant", "content": bot_reply})
                
    except Exception as e:
        st.error(f"אירעה שגיאה בשליחת ההודעה לשרת: {e}")
