import streamlit as st
import google.generativeai as genai

st.set_page_config(page_title="מורה פרטי לקורס", page_icon="🎓")

# עיצוב יישור מימין לשמאל (RTL) לעברית
st.markdown("""
    <style>
    body, .stChatMessage, .stChatInput, p, div, span {
        direction: rtl;
        text-align: right;
    }
    </style>
""", unsafe_allow_html=True)

st.title("🎓 מורה פרטי אישי לקורס")

# בדיקה האם המפתח קיים בהגדרות
if "GEMINI_API_KEY" not in st.secrets:
    st.error("שגיאה: מפתח ה-GEMINI_API_KEY לא הוגדר בהגדרות ה-Secrets של Streamlit.")
    st.stop()

api_key = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=api_key)

# שימוש במודל ה-Flash Lite המהיר והזמין אצלך
try:
    model = genai.GenerativeModel("gemini-3.5-flash-lite")
except Exception as e:
    st.error(f"שגיאה בטעינת המודל: {e}")
    st.stop()

# ניהול היסטוריית השיחה
if "chat" not in st.session_state:
    st.session_state.chat = model.start_chat(history=[])

for message in st.session_state.chat.history:
    role = "user" if message.role == "user" else "assistant"
    with st.chat_message(role):
        st.markdown(message.parts[0].text)

# תיבת הקלט לסטודנט
if user_input := st.chat_input("שאל שאלה על חומרי הקורס..."):
    with st.chat_message("user"):
        st.markdown(user_input)
    
    try:
        with st.chat_message("assistant"):
            with st.spinner("חושב..."):
                response = st.session_state.chat.send_message(user_input)
                st.markdown(response.text)
    except Exception as e:
        st.error(f"אירעה שגיאה בשליחת ההודעה לשרת של גוגל: {e}")
