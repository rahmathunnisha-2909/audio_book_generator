import os
import tempfile
import streamlit as st
import pdfplumber
import docx
import re
from groq import Groq
import base64
import requests
from bs4 import BeautifulSoup
from gtts import gTTS
from pydub import AudioSegment

# ---------------------------
# CONFIGURATION
# ---------------------------
st.set_page_config(page_title="Audio Book Generator", page_icon="", layout="wide")

# ---------------------------
# BACKGROUND IMAGE & STYLING
# ---------------------------
@st.cache_data
def get_base_64_of_bin_file(bin_file):
    with open(bin_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()

def set_png_as_page_bg(png_file):
    try:
        bin_str = get_base_64_of_bin_file(png_file)
        page_bg_img = f'''
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;600&family=Lato:wght@400;700&display=swap');
        .stApp {{
            background-image: url("data:image/jpeg;base64,{bin_str}");
            background-size: cover;
            background-repeat: no-repeat;
            background-attachment: fixed;
            background-position: top center;
            font-family: 'Lato', sans-serif;
        }}
        h1, h2, h3 {{ font-family: 'Poppins', sans-serif; color: #fff; text-shadow: 1px 1px 3px rgba(0,0,0,0.6); }}
        .text-container {{
            border: 1px solid rgba(255,255,255,0.3);
            border-radius: 10px;
            padding: 15px;
            background-color: rgba(255,255,255,0.75);
            backdrop-filter: blur(10px);
            height: 350px;
            overflow-y: auto;
            color: #1E1E1E;
        }}
        </style>
        '''
        st.markdown(page_bg_img, unsafe_allow_html=True)
    except FileNotFoundError:
        st.markdown("<style>.stApp { background-color: #2c3e50; }</style>", unsafe_allow_html=True)

set_png_as_page_bg("background.jpg")

# ---------------------------
# API CLIENT (Groq)
# ---------------------------
groq_api_key = st.secrets.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
if not groq_api_key:
    st.error("No Groq API key found! Please add it to Streamlit secrets.")
    st.stop()
client = Groq(api_key=groq_api_key)

# ---------------------------
# SESSION STATE
# ---------------------------
for key, default in {
    "original_text": "",
    "rewritten_text": "",
    "audio_path": None,
    "last_uploaded_files": None,
    "messages": [],
    "active_tab": "Step 1: Upload"
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ---------------------------
# TEXT PROCESSING
# ---------------------------
def chunk_text_by_sentences(text, max_chunk_length=3000):
    sentences = re.split(r'(?<=[.!?]) +', text.strip())
    chunks, current_chunk = [], ""
    for sentence in sentences:
        if len(current_chunk) + len(sentence) < max_chunk_length:
            current_chunk += " " + sentence
        else:
            chunks.append(current_chunk.strip())
            current_chunk = sentence
    if current_chunk:
        chunks.append(current_chunk.strip())
    return chunks

def rewrite_with_groq(text, progress_placeholder):
    chunks = chunk_text_by_sentences(text)
    rewritten = ""
    progress_bar = progress_placeholder.progress(0, text="Initializing rewrite...")
    for i, chunk in enumerate(chunks):
        try:
            response = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": "You are an expert audiobook scriptwriter. Rewrite the text in a storytelling tone."},
                    {"role": "user", "content": chunk}
                ],
                temperature=0.7,
                max_tokens=4096
            )
            rewritten_chunk = response.choices[0].message.content.strip()
            rewritten += rewritten_chunk + " "
            progress_bar.progress((i + 1) / len(chunks), text=f"Rewriting chunk {i+1}/{len(chunks)}...")
        except Exception as e:
            st.error(f"Error processing chunk {i+1}: {e}")
    progress_bar.empty()
    return rewritten

# ---------------------------
# gTTS (Human-Like TTS)
# ---------------------------
MAX_TTS_LENGTH = 4000

def clean_text_for_tts(text):
    cleaned = re.sub(r'[^\w\s.,!?;:()"\']', '', text)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

def chunk_text_for_gtts(text, max_length=MAX_TTS_LENGTH):
    sentences = re.split(r'(?<=[.!?]) +', text.strip())
    chunks, current = [], ""
    for sentence in sentences:
        if len(current) + len(sentence) < max_length:
            current += " " + sentence
        else:
            chunks.append(current.strip())
            current = sentence
    if current:
        chunks.append(current.strip())
    return chunks

def convert_text_to_speech_gtts(text, language="en", storyteller=True):
    """
    Convert text to natural human-like audiobook speech using Google TTS.
    Adds subtle pauses and smooth pacing if storyteller=True.
    """
    cleaned_text = clean_text_for_tts(text)
    chunks = chunk_text_for_gtts(cleaned_text)

    temp_dir = tempfile.mkdtemp()
    mp3_chunks = []

    for i, chunk in enumerate(chunks):
        try:
            # Add slight pauses to mimic narration style
            if storyteller:
                chunk = re.sub(r'(?<=[.!?]) ', '. ', chunk)
                chunk = chunk.replace(',', ', ')
                chunk = chunk + " ..."
            tts = gTTS(text=chunk, lang=language, slow=True)
            temp_chunk_path = os.path.join(temp_dir, f"chunk_{i}.mp3")
            tts.save(temp_chunk_path)
            mp3_chunks.append(temp_chunk_path)
        except Exception as e:
            st.error(f"Error generating audio for chunk {i+1}: {e}")

    if not mp3_chunks:
        st.error("No audio generated.")
        return None

    final_audio = AudioSegment.empty()
    pause = AudioSegment.silent(duration=700)  # 0.7 sec pause between chunks
    for chunk_path in mp3_chunks:
        final_audio += AudioSegment.from_mp3(chunk_path) + pause

    final_path = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3").name
    final_audio.export(final_path, format="mp3")
    return final_path

# ---------------------------
# FILE EXTRACTION
# ---------------------------
def extract_text_from_url(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        paragraphs = soup.find_all('p')
        return "\n".join([p.get_text() for p in paragraphs]) if paragraphs else ""
    except requests.exceptions.RequestException as e:
        st.error(f"Error fetching URL: {e}")
        return ""

def extract_text_from_pdf(file):
    text = ""
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text

def extract_text_from_docx(file):
    doc = docx.Document(file)
    return "\n".join([para.text for para in doc.paragraphs])

# ---------------------------
# STREAMLIT UI
# ---------------------------
st.title(" AI AUDIOBOOK GENERATOR")
st.markdown("##### Convert documents and articles into *human-like narrated audiobooks* — free and easy!")

with st.sidebar:
    st.header("Settings")
    st.markdown(" *Voice:* Google gTTS (Human-like)")
    st.markdown(" *Powered by:* Groq + Streamlit")
    st.markdown("---")
    st.info("Tip: Use en-in for Indian accent or en-uk for British accent.")

tab_names = ["Step 1: Upload", "Step 2: Rewrite", "Step 3: Generate & Chat"]
st.session_state.active_tab = st.radio("Navigation", tab_names, horizontal=True, label_visibility="collapsed", key="navigation_radio")

# ---------------------------
# Step 1: Upload
# ---------------------------
if st.session_state.active_tab == "Step 1: Upload":
    st.header(" Upload or Fetch Content")
    input_method = st.radio("Choose input method:", ("Upload File(s)", "From Web URL"), horizontal=True)

    if input_method == "Upload File(s)":
        uploaded_files = st.file_uploader("Upload PDF, DOCX, or TXT files:", type=["pdf", "docx", "txt"], accept_multiple_files=True)
        if uploaded_files:
            uploaded_filenames = [f.name for f in uploaded_files]
            if st.session_state.last_uploaded_files != uploaded_filenames:
                st.session_state.original_text, st.session_state.rewritten_text, st.session_state.audio_path = "", "", None
                all_text = ""
                with st.spinner("Extracting text..."):
                    for uploaded_file in uploaded_files:
                        if uploaded_file.name.endswith(".pdf"):
                            all_text += extract_text_from_pdf(uploaded_file)
                        elif uploaded_file.name.endswith(".docx"):
                            all_text += extract_text_from_docx(uploaded_file)
                        else:
                            all_text += uploaded_file.read().decode("utf-8")
                st.session_state.original_text = all_text
                st.session_state.last_uploaded_files = uploaded_filenames
            if st.session_state.original_text:
                st.success(f"Extracted {len(st.session_state.original_text)} characters.")
                if st.button("Proceed to Step 2 →", use_container_width=True):
                    st.session_state.active_tab = "Step 2: Rewrite"
                    st.rerun()

    elif input_method == "From Web URL":
        url = st.text_input("Enter article URL:")
        if st.button("Fetch Text", use_container_width=True):
            if url:
                with st.spinner("Fetching text..."):
                    text = extract_text_from_url(url)
                st.session_state.original_text = text
                if text:
                    st.success("Text extracted successfully!")
                    st.markdown(f'<div class="text-container">{text[:1000]}...</div>', unsafe_allow_html=True)
                    if st.button("Proceed to Step 2 →", use_container_width=True):
                        st.session_state.active_tab = "Step 2: Rewrite"
                        st.rerun()
            else:
                st.warning("Please enter a valid URL.")

# ---------------------------
# Step 2: Rewrite
# ---------------------------
elif st.session_state.active_tab == "Step 2: Rewrite":
    st.header("🪄 AI Script Rewriter")
    if not st.session_state.original_text:
        st.warning("Upload or fetch text first.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Original Text")
            st.markdown(f'<div class="text-container">{st.session_state.original_text}</div>', unsafe_allow_html=True)
        with col2:
            st.subheader("Rewritten Script")
            if st.button("Rewrite with AI ", use_container_width=True):
                progress_placeholder = st.empty()
                st.session_state.rewritten_text = rewrite_with_groq(st.session_state.original_text, progress_placeholder)
            if st.session_state.rewritten_text:
                st.markdown(f'<div class="text-container">{st.session_state.rewritten_text}</div>', unsafe_allow_html=True)
                if st.button("Proceed to Step 3 →", use_container_width=True):
                    st.session_state.active_tab = "Step 3: Generate & Chat"
                    st.rerun()

# ---------------------------
# Step 3: Generate & Chat
# ---------------------------
elif st.session_state.active_tab == "Step 3: Generate & Chat":
    st.header(" Generate Your Audiobook")
    if not st.session_state.rewritten_text:
        st.warning("Please rewrite your text first.")
    else:
        if st.button("Generate Human-like Audio ", use_container_width=True):
            with st.spinner("Generating natural narration..."):
                st.session_state.audio_path = convert_text_to_speech_gtts(
                    st.session_state.rewritten_text,
                    language="en",
                    storyteller=True
                )
            if st.session_state.audio_path:
                st.success("Audiobook ready!")

        if st.session_state.audio_path:
            st.audio(st.session_state.audio_path, format="audio/mp3")
            with open(st.session_state.audio_path, "rb") as f:
                st.download_button("⬇ Download Audiobook", data=f, file_name="ai_audiobook.mp3", mime="audio/mp3")

        st.markdown("---")
        st.header("Chat with an AI Assistant")
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
        if prompt := st.chat_input("Ask anything..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            try:
                with st.spinner("Thinking..."):
                    chat_response = client.chat.completions.create(
                        model="llama-3.1-8b-instant",
                        messages=[{"role": "system", "content": "You are a helpful assistant."},
                                  {"role": "user", "content": prompt}],
                        temperature=0.7
                    )
                    response_content = chat_response.choices[0].message.content
                    st.session_state.messages.append({"role": "assistant", "content": response_content})
            except Exception as e:
                st.error(f"Error: {e}")
            st.rerun()
