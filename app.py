import streamlit as st
import google.generativeai as genai
from PIL import Image
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

# בדיקת מפתח API
if "GEMINI_API_KEY" not in st.secrets:
    st.error("שגיאה: מפתח ה-GEMINI_API_KEY לא הוגדר בהגדרות ה-Secrets.")
    st.stop()

genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

# --- טעינה אוטומטית של קבצי הקורס מתיקיית course_files ב-GitHub ---
@st.cache_resource
def load_course_context():
    folder_path = "course_files"
    combined_course_text = ""
    
    if os.path.exists(folder_path):
        files = os.listdir(folder_path)
        for filename in files:
            file_path = os.path.join(folder_path, filename)
            if filename.lower().endswith(".pdf"):
                try:
                    reader = pypdf.PdfReader(file_path)
                    for page in reader.pages:
                        text = page.extract_text()
                        if text:
                            combined_course_text += f"\n[מתוך קובץ הקורס: {filename}]:\n" + text + "\n"
                except Exception as e:
                    print(f"שגיאה בקריאת הקובץ {filename}: {e}")
            elif filename.lower().endswith(".txt"):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        combined_course_text += f"\n[מתוך קובץ הקורס: {filename}]:\n" + f.read() + "\n"
                except Exception as e:
                    print(f"שגיאה בקריאת הקובץ {filename}: {e}")
                    
    return combined_course_text

course_context = load_course_context()

# --- אזור העלאת קבצים נקודתיים לסטודנט (למשל מבחן ספציפי לתרגול) ---
st.sidebar.markdown("---")
st.sidebar.title("📁 העלאת מבחן לתרגול")
exam_files = st.sidebar.file_uploader(
    "העלה מבחן נקודתי שתרצה עזרה בפתרונו", 
    type=["pdf", "png", "jpg", "jpeg", "txt"],
    accept_multiple_files=True
)

# --- הנחיות המערכת החדשות והמדויקות ---
system_instruction = f"""
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
5. לכל מבחן שתי גרסאות: גרסא מעורבלת וגרסא (נקראת טופס 0) שבה תמיד התשובה הנכונה هي הראשונה (א), אלא אם כן כתוב אחרת בדפי ההסבר על המבחנים.
6. בשניים מהמבחנים יש גם פתרונות מוסברים - למד גם אותם.

להלן תוכן חומרי הקורס שנטענו למערכת:
{course_context}
"""

@st.cache_resource
def init_model(sys_instruct):
    model = genai.GenerativeModel(
        model_name="gemini-pro-latest",  # או gemini-3.8-flash לפי בחירתך
        system_instruction=sys_instruct
    )
    return model

model = init_model(system_instruction)

if "chat" not in st.session_state:
    st.session_state.chat = model.start_chat(history=[])

# עיבוד מבחן נקודתי שהסטודנט מעלה בצד (אם העלה)
exam_payload = []
if exam_files:
    for uploaded_file in exam_files:
        file_ext = uploaded_file.name.split('.')[-1].lower()
        try:
            if file_ext in ["png", "jpg", "jpeg"]:
                img = Image.open(uploaded_file)
                exam_payload.append(img)
            elif file_ext == "pdf":
                reader = pypdf.PdfReader(uploaded_file)
                pdf_text = ""
                for page in reader.pages:
                    text = page.extract_text()
                    if text:
                        pdf_text += text + "\n"
                exam_payload.append(f"\n[מבחן/תרגיל שהועלה על ידי הסטודנט - {uploaded_file.name}]:\n{pdf_text}\n")
            elif file_ext == "txt":
                text_content = uploaded_file.getvalue().decode('utf-8')
                exam_payload.append(f"\n[טקסט שהועלה - {uploaded_file.name}]:\n{text_content}\n")
        except Exception as e:
            st.sidebar.error(f"שגיאה בעיבוד הקובץ {uploaded_file.name}: {e}")

# הצגת היסטוריית השיחה
for message in st.session_state.chat.history:
    if message.role in ["user", "model"]:
        for part in message.parts:
            if hasattr(part, "text") and part.text:
                with st.chat_message("user" if message.role == "user" else "assistant"):
                    st.markdown(part.text)

# תיבת הקלט של הסטודנט
if user_input := st.chat_input("שאל שאלה על החומר או בקש עזרה בפתרון השאלות..."):
    with st.chat_message("user"):
        st.markdown(user_input)
        if exam_files:
            file_names = ", ".join([f.name for f in exam_files])
            st.caption(f"📄 מבחן מצורף: {file_names}")

    try:
        with st.chat_message("assistant"):
            with st.spinner("חושב ומנתח בהתאם לחומרי הקורס..."):
                payload = [user_input]
                if exam_payload:
                    payload.extend(exam_payload)
                
                response = st.session_state.chat.send_message(payload)
                st.markdown(response.text)
    except Exception as e:
        st.error(f"אירעה שגיאה בשליחת ההודעה לשרת: {e}")
