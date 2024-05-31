import streamlit as st
import os
from dotenv import load_dotenv
import base64
import anthropic  # Ensure you've installed this package

# Load environment variables
load_dotenv()

# Initialize the API client
api_key = os.getenv("ANTHROPIC_API_KEY")
if not api_key:
    st.error("Anthropic API key not found. Please set the ANTHROPIC_API_KEY environment variable.")
    st.stop()

client = anthropic.Anthropic(api_key=api_key)

# Simplified function to simulate asking for details and receiving them
def ask_details():
    st.session_state['ask_details'] = True

def main():
    st.set_page_config(page_title="SEO Article Generator", page_icon=":memo:", layout="wide")
    st.title("SEO Article Generator")

    if 'ask_details' not in st.session_state:
        st.session_state['ask_details'] = False

    if 'conversation_started' not in st.session_state:
        if st.button("Start Conversation"):
            st.session_state['conversation_started'] = True
            st.session_state['messages'] = []
            ask_details()

    if st.session_state.get('ask_details', False):
        with st.form("input_form"):
            transcript = st.text_area("Hello! Please tell me your video transcript to get started:")
            existing_h1 = st.text_input("What is the H1 of your article?")
            existing_header = st.text_input("What is the header of your article?")
            submitted = st.form_submit_button("Submit")
            if submitted:
                st.session_state['article_details'] = {
                    "transcript": transcript,
                    "h1": existing_h1,
                    "header": existing_header
                }
                st.session_state['ask_details'] = False  # Reset or proceed to next step
                st.success("Details received! You can now generate the article.")

    # Further processing can be added here, similar to your existing buttons for generating articles
    if 'article_details' in st.session_state:
        st.write("Details received:", st.session_state['article_details'])
        # Add buttons to proceed with generating the article, fact-checking, etc.

if __name__ == "__main__":
    main()
