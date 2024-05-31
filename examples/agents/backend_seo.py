import os
import random
import time
from typing import Any, Dict, Generator, List, Optional

import streamlit as st
import openai
import phospho
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
#openai_api_key = os.getenv('OPENAI_API_KEY')
#phospho_api_key = os.getenv('PHOSPHO_API_KEY')
#phospho_project_id = os.getenv('PHOSPHO_PROJECT_ID')
#phospho_base_url = os.getenv('PHOSPHO_BASE_URL', 'https://api.phospho.com')

openai_api_key = st.secrets["OPENAI_API_KEY"]

# Check if environment variables are set
if not openai_api_key or not phospho_api_key or not phospho_project_id:
    st.error('API keys and project ID must be set in the environment variables.')
    st.stop()

# Initialize OpenAI client
client = openai.OpenAI(api_key=openai_api_key)

class ArticleGenerator:
    def __init__(self):
        self.system_prompt = "Generate an SEO-optimized article based on user inputs."

    def new_session(self) -> str:
        """Start a new session_id. This is used to keep discussions separate in phospho."""
        return phospho.new_session()

    def generate_article(self, transcript, h1, header):
        """Generate an article using OpenAI's model."""
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"Transcript: {transcript}, H1: {h1}, Header: {header}"}
        ]
        response = client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            max_tokens=1500,
            temperature=0.7
        )
        return response.choices[0].message['content'].strip()

    def random_intro(self) -> Generator[str, Any, None]:
        """Generate a dynamic introduction based on random selections."""
        greetings = [
            "Hello! Let's create an SEO-optimized article. Please provide the details.",
            "Welcome! Ready to craft an article? Start by giving me the transcript.",
            "Hi there! I can help you write an engaging article. What's your main topic?"
        ]
        chosen_intro = random.choice(greetings)
        splitted_text = chosen_intro.split(" ")
        for i, word in enumerate(splitted_text):
            yield " ".join(splitted_text[: i + 1])
            time.sleep(0.05)

    def answer_and_log(
        self,
        messages: List[Dict[str, str]],
        session_id: str,
    ) -> Generator[Optional[str], Any, None]:
        """Generates a response to the user in a streaming fashion."""
        full_prompt = {
            "model": "gpt-4",
            "messages": messages,
            "max_tokens": 1500,
            "stream": True
        }
        streaming_response = client.chat.completions.create(**full_prompt)
        try:
            phospho.log(
                input=full_prompt,
                output=streaming_response,
                session_id=session_id,
                metadata={"intro": messages[0]["content"]} if messages else {}
            )
        except Exception as e:
            st.warning(f"Failed to log to Phospho: {e}")
        for response in streaming_response:
            yield response.choices[0].delta.content

    @phospho.wrap(stream=True, stop=lambda token: token is None)
    def answer(
        self,
        messages: List[Dict[str, str]],
        session_id: Optional[str] = None,
    ) -> Generator[Optional[str], Any, None]:
        """Wrap answer method for logging."""
        full_prompt = {
            "model": "gpt-4",
            "messages": messages,
            "max_tokens": 1500,
            "stream": True
        }
        streaming_response = client.chat.completions.create(**full_prompt)
        for response in streaming_response:
            yield response.choices[0].delta.content

    def feedback(self, raw_flag: str, notes: str) -> None:
        """Collect feedback from the user."""
        try:
            phospho.user_feedback(
                task_id=phospho.latest_task_id, raw_flag=raw_flag, notes=notes
            )
        except Exception as e:
            st.warning(f"Failed to send feedback to Phospho: {e}")

phospho.init(
    api_key=st.secrets["PHOSPHO_API_KEY"],
    project_id=st.secrets["PHOSPHO_PROJECT_ID"],
    # base_url="http://127.0.0.1:8000/v2",
    base_url=os.getenv("PHOSPHO_BASE_URL"),
    # version_id="v2"
)
