import os
import random
import time
from typing import Any, Dict, Generator, List, Optional

import streamlit as st
from openai import OpenAI
from openai._streaming import Stream
from openai.types.chat import ChatCompletionChunk

import phospho


class ArticleGenerator:
    """This agent generates SEO-optimized articles based on user inputs."""

    # This system prompt gives its personality to the agent
    system_prompt = {
        "role": "system",
        "content": "Generate an SEO-optimized article based on user inputs."
    }

    def __init__(self):
        self.client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

    def new_session(self) -> str:
        """Start a new session_id. This is used to keep discussions separate in phospho."""
        return phospho.new_session()

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
            "messages": [self.system_prompt] + messages,
            "max_tokens": 1500,
            "stream": True,
        }
        streaming_response: Stream[
            ChatCompletionChunk
        ] = self.client.chat.completions.create(**full_prompt)

        logged_content = phospho.log(
            input=full_prompt,
            output=streaming_response,
            session_id=session_id,
            metadata={"intro": messages[0]["content"]} if messages else {},
        )

        for response in streaming_response:
            yield response.choices[0].delta.content

    @phospho.wrap(stream=True, stop=lambda token: token is None)
    def answer(
        self,
        messages: List[Dict[str, str]],
        session_id: Optional[str] = None,
    ) -> Generator[Optional[str], Any, None]:
        """Same as answer_and_log, but with phospho.wrap, which automatically logs the input
        and output of the function."""

        streaming_response: Stream[
            ChatCompletionChunk
        ] = self.client.chat.completions.create(
            model="gpt-4",
            messages=[self.system_prompt] + messages,
            max_tokens=1500,
            stream=True,
        )

        for response in streaming_response:
            yield response.choices[0].delta.content

    def feedback(self, raw_flag: str, notes: str) -> None:
        """This method is used to collect feedback from the user.
        It is called after the user has received a response from the agent.
        """
        phospho.user_feedback(
            task_id=phospho.latest_task_id, raw_flag=raw_flag, notes=notes
        )


# Initialize phospho to collect logs
phospho.init(
    api_key=st.secrets["PHOSPHO_API_KEY"],
    project_id=st.secrets["PHOSPHO_PROJECT_ID"],
    base_url=os.getenv("PHOSPHO_BASE_URL"),
)
