import streamlit as st
import google.generativeai as genai
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

genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

# --- סרגל צדי: קבצים להעלאה ומצב מרצה ---
st.sidebar.markdown("---")
st.sidebar.title("📁 קבצים להעלאה")
exam_files = st.sidebar.file_uploader(
    "העלה מבחן, תרגיל, שאלה או כל קובץ אחר", 
    type=["pdf", "png", "jpg", "jpeg", "txt"],
    accept_multiple_files=True
)

st.sidebar.markdown("---")
st.sidebar.title("🛠️ הגדרות כניסת מרצה")
lecturer_mode = st.sidebar.checkbox("הפעל מצב מרצה (ניהול ובקרה)")

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

# --- יצירת מודל יציב (שימוש במודל Flash נתמך) ---
@st.cache_resource
def get_or_create_cached_model():
    folder_path = "course_files"
    uploaded_files_for_cache = []
    
    if os.path.exists(folder_path):
        for filename in os.listdir(folder_path):
            file_path = os.path.join(folder_path, filename)
            if filename.lower().endswith((".pdf", ".txt")):
                try:
                    f = genai.upload_file(file_path)
                    uploaded_files_for_cache.append(f)
                except Exception as e:
                    print(f"שגיאה בהעלאת {filename}: {e}")

    # שימוש במודל העדכני והנתמך ביותר בקריאות API
    target_model_name = 'gemini-2.5-flash'
    
    try:
        if uploaded_files_for_cache:
            cache = genai.caching.CachedContent.create(
                model=target_model_name,
                display_name='course_cache_research_methods',
                system_instruction=system_instruction,
                contents=uploaded_files_for_cache,
            )
            model = genai.GenerativeModel.from_cached_content(cached_content=cache)
            return model
        else:
            return genai.GenerativeModel(model_name=target_model_name, system_instruction=system_instruction)
    except Exception as e:
        # פולבק למודל בסיסי במקרה של תקלה ביצירת קאש
        return genai.GenerativeModel(model_name="gemini-flash", system_instruction=system_instruction)

model = get_or_create_cached_model()

if "chat" not in st.session_state:
    st.session_state.chat = model.start_chat(history=[])

if lecturer_mode:
    st.subheader("📊 לוח בקרה למרצה")
    st.success("מצב מרצה פעיל: המערכת פועלת מול שרתי גוגל.")

# עיבוד קבצים שהסטודנט מעלה בצד
exam_payload = []
if exam_files:
    for uploaded_file in exam_files:
        try:
            temp_file = genai.upload_file(uploaded_file)
            exam_payload.append(temp_file)
        except Exception as e:
            st.sidebar.error(f"שגיאה בהעלאת הקובץ {uploaded_file.name}: {e}")

# הצגת היסטוריית השיחה
for message in st.session_state.chat.history:
    if message.role in ["user", "model"]:
        for part in message.parts:
            if hasattr(part, "text") and part.text:
                with st.chat_message("user" if message.role == "user" else "assistant"):
                    st.markdown(part.text)

# תיבת הקלט
if user_input := st.chat_input("שאל שאלה על החומר או בקש עזרה בפתרון השאלות..."):
    with st.chat_message("user"):
        st.markdown(user_input)
        if exam_files:
            file_names = ", ".join([f.name for f in exam_files])
            st.caption(f"📄 קבצים מצורפים: {file_names}")

    try:
        with st.chat_message("assistant"):
            with st.spinner("חושב ומנתח במהירות מתוך הזיכרון..."):
                payload = [user_input]
                if exam_payload:
                    payload.extend(exam_payload)
                
                response = st.session_state.chat.send_message(payload)
                st.markdown(response.text)
    except Exception as e:
        st.error(f"אירעה שגיאה בשליחת ההודעה לשרת: {e}")
