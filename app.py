import streamlit as st
from google import genai
from google.genai import types
import os

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

# --- הגדרת המודל והקאש החכם (כולל שמירת שגיאות דיבוג) ---
target_model = 'gemini-3.8-flash'

@st.cache_resource
def get_or_create_course_cache():
    try:
        client_temp = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
        
        # 1. בדיקה האם כבר קיים קאש פעיל בשרתים של גוגל
        try:
            existing_caches = client_temp.caches.list()
            for c in existing_caches:
                return c.name
        except Exception as list_err:
            # נשמור גם שגיאה זו לצורך מעקב אם צריך
            pass
            
        # 2. אם אין קאש קיים, ניצור אותו פעם אחת מהתיקייה
        current_dir = os.path.dirname(os.path.abspath(__file__))
        folder_path = os.path.join(current_dir, "course_files")
        uploaded_files = []
        
        if os.path.exists(folder_path):
            for index, filename in enumerate(os.listdir(folder_path)):
                file_path = os.path.join(folder_path, filename)
                if filename.lower().endswith((".pdf", ".txt", ".pptx", ".png", ".jpg", ".jpeg")):
                    g_file = client_temp.files.upload(file=file_path)
                    uploaded_files.append(g_file)
                    
        if not uploaded_files:
            st.session_state["cache_error_debug"] = "תיקיית course_files ריקה או שלא נמצאו בה קבצים נתמכים."
            return None
            
        cache_obj = client_temp.caches.create(
            model=target_model,
            config=types.CreateCachedContentConfig(
                contents=uploaded_files,
                system_instruction=system_instruction,
                ttl="7200s"
            )
        )
        return cache_obj.name
        
    except Exception as e:
        # שמירת השגיאה המדויקת להצגה באזור המרצה
        st.session_state["cache_error_debug"] = str(e)
        return None

course_cache_name = get_or_create_course_cache()

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- לוח בקרה למרצה ---
if lecturer_authenticated:
