import streamlit as st
from google import genai
from google.genai import types
import pypdf
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
3. אם יש סתירה בין חומר אחר שאתה מכיר והמצגת, העדף את המצגת.
4. בין הקבצים שהועלו יש גם תרגילים ופתרונות להם, למד גם אותם, ומבחנים.
5. לכל מבחן שתי גרסאות: גרסא מעורבלת וגרסא (נקראת טופס 0) שבה תמיד התשובה הנכונה היא הראשונה (א), אלא אם כן כתוב אחרת בדפי ההסבר על המבחנים.
6. בשניים מהמבחנים יש גם פתרונות מוסברים - למד גם אותם.
"""

# --- טעינת קבצי הקורס מתיקיית course_files פעם אחת ב-Session ---
@st.cache_resource
def load_course_files_text():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    folder_path = os.path.join(current_dir, "course_files")
    
    combined_text = ""
    file_status_info = []
    
    if os.path.exists(folder_path):
        files = os.listdir(folder_path)
        for filename in files:
            file_path = os.path.join(folder_path, filename)
            if filename.lower().endswith(".pdf"):
                try:
                    reader = pypdf.PdfReader(file_path)
                    file_text = ""
                    for page in reader.pages:
                        t = page.extract_text()
                        if t:
                            file_text += t + "\n"
                    # תיקון כיווניות טקסט במידת הצורך והוספה למאגר
                    combined_text += f"\n\n--- [מתוך חומרי הקורס: {filename}] ---\n{file_text}"
                    file_status_info.append(f"✅ נטען בהצלחה: {filename}")
                except Exception as e:
                    file_status_info.append(f"❌ שגיאה בקריאת {filename}: {e}")
            elif filename.lower().endswith(".txt"):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        combined_text += f"\n\n--- [מתוך חומרי הקורס: {filename}] ---\n{f.read()}"
                        file_status_info.append(f"✅ נטען בהצלחה: {filename}")
                except Exception as e:
                    file_status_info.append(f"❌ שגיאה בקריאת {filename}: {e}")
    else:
        file_status_info.append(f"⚠️ אזהרה: התיקייה course_files לא נמצאה.")
        
    return combined_text, file_status_info

course_context_text, file_status_log = load_course_files_text()

# אתחול הלקוח והודעות
client = genai.Client(api_key=st.secrets["GEMINI_API_KEY"])
target_model = 'gemini-3.5-flash-lite'

if "messages" not in st.session_state:
    st.session_state.messages = []

# --- לוח בקרה למרצה ---
if lecturer_authenticated:
    st.markdown("---")
    st.subheader("📊 לוח בקרה וניהול למרצה")
    st.success("חומרי הקורס נטענו בהצלחה ופועלים עם מודל 3.5-flash-lite!")
    st.write("**סטטוס קבצי הקורס בתיקייה:**")
    for log_item in file_status_log:
        st.text(log_item)
    st.markdown("---")

# הצגת היסטוריית ההודעות
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# עיבוד קבצים שהסטודנט מעלה בצד
student_exam_text = ""
if exam_files:
    for uploaded_file in exam_files:
        file_ext = uploaded_file.name.split('.')[-1].lower()
        try:
            if file_ext == "pdf":
                reader = pypdf.PdfReader(uploaded_file)
                pdf_text = ""
                for page in reader.pages:
                    t = page.extract_text()
                    if t:
                        pdf_text += t + "\n"
                student_exam_text += f"\n\n--- [קובץ מבחן שהעלה הסטודנט: {uploaded_file.name}] ---\n{pdf_text}"
            elif file_ext == "txt":
                text_content = uploaded_file.getvalue().decode('utf-8')
                student_exam_text += f"\n\n--- [טקסט שהעלה הסטודנט: {uploaded_file.name}] ---\n{text_content}"
        except Exception as e:
            st.sidebar.error(f"שגיאה בקריאת הקובץ {uploaded_file.name}: {e}")

# תיבת הקלט של המשתמש
if user_input := st.chat_input("שאל שאלה על החומר או בקש עזרה בפתרון השאלות..."):
    full_prompt = user_input
    if student_exam_text:
        full_prompt += f"\n{student_exam_text}"

    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)
        if exam_files:
            file_names = ", ".join([f.name for f in exam_files])
            st.caption(f"📄 קבצים מצורפים למבחן: {file_names}")

    try:
        with st.chat_message("assistant"):
            with st.spinner("חושב ומנתח מתוך חומרי הקורס והמבחן..."):
                # בניית ההיסטוריה המלאה עבור ה-SDK החדש
                contents = []
                
                # בפעם הראשונה נצרף את חומרי הקורס כהקשר רקע למערכת
                if len(st.session_state.messages) == 1 and course_context_text:
                    contents.append(types.Content(role="user", parts=[types.Part.from_text(text=f"להלן חומרי הקורס הרשמיים שעליך להתבסס עליהם:\n{course_context_text}")]))
                    contents.append(types.Content(role="model", parts=[types.Part.from_text(text="הבנתי היטב. קלטתי את כל חומרי הקורס ואפעל אך ורק לפיהם.")]))

                # הוספת היסטוריית השיחה הקודמת
                for m in st.session_state.messages[:-1]:
                    contents.append(types.Content(role="user" if m["role"] == "user" else "model", parts=[types.Part.from_text(text=m["content"])]))
                
                # הוספת ההודעה הנוכחית עם תוכן הקבצים
                contents.append(types.Content(role="user", parts=[types.Part.from_text(text=full_prompt)]))

                response = client.models.generate_content(
                    model=target_model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.3
                    )
                )
                
                bot_reply = response.text
                st.markdown(bot_reply)
                st.session_state.messages.append({"role": "assistant", "content": bot_reply})
                
    except Exception as e:
        st.error(f"אירעה שגיאה בשליחת ההודעה לשרת: {e}")
