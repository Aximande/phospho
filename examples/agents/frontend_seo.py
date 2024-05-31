import streamlit as st
from streamlit_feedback import streamlit_feedback
from backend_seo import ArticleGenerator

# Initialize the article generator
article_generator = ArticleGenerator()

# Streamlit interface
st.title("SEO Article Generator")
left, right = st.columns(2)
with left:
    if st.button("New session"):
        st.session_state.session_id = article_generator.new_session()
        st.session_state.messages = []
with right:
    st.write("Let's generate an SEO article!")

if "messages" not in st.session_state:
    st.session_state.messages = []

if "session_id" not in st.session_state:
    st.session_state.session_id = article_generator.new_session()

if st.session_state.messages == []:
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        for streamed_content in article_generator.random_intro():
            message_placeholder.markdown(streamed_content + "▌")
        message_placeholder.markdown(streamed_content)
        st.session_state.messages = [{"role": "assistant", "content": streamed_content}]
else:
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

if prompt := st.chat_input("Enter the transcript, H1, and header in the format 'Transcript: ..., H1: ..., Header: ...'"):
    new_message = {"role": "user", "content": prompt}
    st.session_state.messages.append(new_message)
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_str_response = ""
        streamed_response = article_generator.answer(
            messages=st.session_state.messages, session_id=st.session_state.session_id
        )
        for resp in streamed_response:
            full_str_response += resp or ""
            message_placeholder.markdown(full_str_response + "▌")
        message_placeholder.markdown(full_str_response)
    st.session_state.messages.append(
        {"role": "assistant", "content": full_str_response}
    )

def _submit_feedback(feedback: dict):
    article_generator.feedback(raw_flag=feedback["score"], notes=feedback["text"])
    st.toast(f"Thank you for your feedback!")

if len(st.session_state.messages) > 1:
    feedback = streamlit_feedback(
        feedback_type="thumbs",
        optional_text_label="[Optional] Please provide an explanation",
        on_submit=_submit_feedback,
        key=f"{st.session_state.session_id}_{len(st.session_state.messages)}",
    )
