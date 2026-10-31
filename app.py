import streamlit as st
import google.generativeai as genai

st.set_page_config(page_title="מורה פרטי לקורס", page_icon="🎓")
st.title("🎓 מורה פרטי אישי לקורס")

# חיבור ל-API באמצעות הסודיות שהוגדרה בסטרימליט
api_key = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=api_key)

# כאן אנחנו מגדירים את המודל. 
# אם הגדרת את ההוראות ב-System Instructions בסטודיו, המודל יידע לעבוד לפיהן.
# מומלץ להשתמש בגרסת מודל מתקדמת כמו gemini-1.5-pro
model = genai.GenerativeModel(
    model_name="gemini-1.5-pro"
)

# ניהול היסטוריית השיחה של הסטודנט
if "chat" not in st.session_state:
    st.session_state.chat = model.start_chat(history=[])

for message in st.session_state.chat.history:
    role = "user" if message.role == "user" else "assistant"
    with st.chat_message(role):
        st.markdown(message.parts[0].text)

# תיבת הקלט שבה הסטודנט כותב את השאלה
if user_input := st.chat_input("שאל שאלה על חומרי הקורס..."):
    with st.chat_message("user"):
        st.markdown(user_input)
    
    with st.chat_message("assistant"):
        response = st.session_state.chat.send_message(user_input)
        st.markdown(response.text)
