import os
import random
import time
from typing import Any, Dict, Generator, List, Optional

import streamlit as st
import openai
import phospho
from dotenv import load_dotenv

# Initialize environment variables
load_dotenv()
openai_api_key = os.getenv('OPENAI_API_KEY')
phospho_api_key = os.getenv('PHOSPHO_API_KEY')
phospho_project_id = os.getenv('PHOSPHO_PROJECT_ID')
phospho_base_url = os.getenv('PHOSPHO_BASE_URL', 'https://api.phospho.com')

# Check if environment variables are set
if not openai_api_key or not phospho_api_key or not phospho_project_id:
    st.error('API keys and project ID must be set in the environment variables.')
    st.stop()

# Initialize OpenAI with the API key from environment variables
openai.api_key = openai_api_key

# Initialize Phospho with API key, project ID, and base URL from environment variables
phospho.init(api_key=phospho_api_key,
             project_id=phospho_project_id,
             base_url=phospho_base_url)

class ArticleGenerator:
    def __init__(self):
        self.client = openai  # Use the openai directly without re-initializing it
        self.system_prompt = "Generate an SEO-optimized article based on user inputs."

    def new_session(self) -> str:
        """Start a new session_id. This is used to keep discussions separate in phospho."""
        return phospho.new_session()

    def generate_article(self, transcript, h1, header):
        """Generate an article using OpenAI's model."""
        prompt = f"{self.system_prompt} Transcript: {transcript}, H1: {h1}, Header: {header}."
        response = self.client.Completion.create(
            model="text-davinci-003",
            prompt=prompt,
            max_tokens=1500,
            stop=None,
            temperature=0.7
        )
        return response.choices[0].text.strip()

    def interact(self, transcript, h1, header):
        """Simulates interactive communication with the user, mimicking the Santa Claus example."""
        session_id = self.new_session()
        intro = self.generate_intro()
        yield intro  # Initial greeting/intro to the user
        article = self.generate_article(transcript, h1, header)
        phospho.log(session_id=session_id, input={"transcript": transcript, "h1": h1, "header": header}, output=article)
        yield article

    def generate_intro(self):
        """Generate a dynamic introduction based on random selections."""
        greetings = [
            "Hello! Let's create an SEO-optimized article. Please provide the details.",
            "Welcome! Ready to craft an article? Start by giving me the transcript.",
            "Hi there! I can help you write an engaging article. What's your main topic?"
        ]
        return random.choice(greetings)

# Streamlit interface
st.title("SEO Article Generator")
left, right = st.columns(2)
with left:
    if st.button("New session"):
        st.session_state.session_id = ArticleGenerator().new_session()
        st.session_state.messages = []
with right:
    st.write("Let's generate an SEO article!")

if "messages" not in st.session_state:
    st.session_state.messages = []

if "session_id" not in st.session_state:
    st.session_state.session_id = ArticleGenerator().new_session()

if st.session_state.messages == []:
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        for streamed_content in ArticleGenerator().random_intro(
            session_id=st.session_state.session_id
        ):
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
        streamed_response = ArticleGenerator().answer(
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
    ArticleGenerator().feedback(raw_flag=feedback["score"], notes=feedback["text"])
    st.toast(f"Thank you for your feedback!")

if len(st.session_state.messages) > 1:
    feedback = streamlit_feedback(
        feedback_type="thumbs",
        optional_text_label="[Optional] Please provide an explanation",
        on_submit=_submit_feedback,
        key=f"{st.session_state.session_id}_{len(st.session_state.messages)}",
    )
