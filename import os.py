import os
import tempfile
import streamlit as st
import pdfplumber
import docx
import re
from groq import Groq
import asyncio
import edge_tts
import base64
import requests
from bs4 import BeautifulSoup

# ---------------------------
# CONFIGURATION
# ---------------------------
st.set_page_config(
    page_title="Audio Book Generator",
    page_icon="",
    layout="wide"
)

# --- BACKGROUND IMAGE AND CUSTOM CSS FUNCTION ---
@st.cache_data
def get_base_64_of_bin_file(bin_file):
    with open(bin_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()

def set_png_as_page_bg(png_file):
    # (CSS is unchanged)
    bin_str = get_base_64_of_bin_file(png_file)
    page_bg_img = f'''
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;600&family=Lato:wght@400;700&display=swap');
    .stApp {{ background-image: url("data:image/jpeg;base64,{bin_str}"); background-size: cover; background-repeat: no-repeat; background-attachment: fixed; background-position: top center; font-family: 'Lato', sans-serif; }}
    h1 {{ font-family: 'Poppins', sans-serif; font-weight: 600; font-size: 2.5rem; color: #FFFFFF; text-shadow: 2px 2px 6px rgba(0, 0, 0, 0.5); text-transform: uppercase; letter-spacing: 2px; }}
    h2 {{ font-family: 'Poppins', sans-serif; font-weight: 600; font-size: 1.75rem; color: #FFFFFF; text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.5); text-transform: capitalize; }}
    h3 {{ font-family: 'Poppins', sans-serif; font-weight: 400; font-size: 1.25rem; color: #FFFFFF; text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.5); text-transform: capitalize; }}
    .text-container {{ border: 1px solid rgba(255, 255, 255, 0.3); border-radius: 10px; padding: 15px; background-color: rgba(255, 255, 255, 0.75); backdrop-filter: blur(10px); box-shadow: 0 2px 4px rgba(0,0,0,0.1); height: 350px; overflow-y: auto; color: #1E1E1E; font-family: 'Lato', sans-serif; }}
    [data-testid="stChatMessageContent"] {{ background-color: rgba(255, 255, 255, 0.9); color: #1E1E1E; border-radius: 10px; padding: 1rem; box-shadow: 0 2px 4px rgba(0,0,0,0.1); font-family: 'Lato', sans-serif; }}
    .stButton>button {{ border-radius: 20px; border: 1px solid #FFFFFF; background-color: rgba(255, 255, 255, 0.2); color: #FFFFFF; backdrop-filter: blur(5px); font-family: 'Poppins', sans-serif; }}
    .stButton>button:hover {{ border-color: #FFFFFF; background-color: rgba(255, 255, 255, 0.5); color: #FFFFFF; }}
    div[role="radiogroup"] {{ flex-direction: row; gap: 24px; margin-bottom: 2rem; }}
    div[role="radiogroup"] label > div:first-child {{ display: none; }}
    div[role="radiogroup"] label {{ height: 50px; padding: 10px 20px; background-color: rgba(255, 255, 255, 0.5); backdrop-filter: blur(5px); border-radius: 10px 10px 0 0; color: #1E1E1E; font-family: 'Poppins', sans-serif; cursor: pointer; transition: all 0.2s ease-in-out; }}
    div[role="radiogroup"] input:checked + div {{ background-color: rgba(255, 255, 255, 0.95); font-weight: 600; }}
    </style>
    '''
    st.markdown(page_bg_img, unsafe_allow_html=True)

try:
    set_png_as_page_bg('background.jpg')
except FileNotFoundError:
    st.warning("background.jpg not found. Using a fallback background.")
    st.markdown("<style>.stApp { background-color: #2c3e50; }</style>", unsafe_allow_html=True)

# --- API CLIENT AND STATE MANAGEMENT ---
groq_api_key = st.secrets.get("GROQ_API_KEY") or os.getenv("GROQ_API_KEY")
if not groq_api_key: st.error("No Groq API key found! Please add it to secrets."); st.stop()
client = Groq(api_key=groq_api_key)

if "original_text" not in st.session_state: st.session_state.original_text = ""
if "rewritten_text" not in st.session_state: st.session_state.rewritten_text = ""
if "audio_path" not in st.session_state: st.session_state.audio_path = None
if "last_uploaded_files" not in st.session_state: st.session_state.last_uploaded_files = None
if "messages" not in st.session_state: st.session_state.messages = []
if "active_tab" not in st.session_state: st.session_state.active_tab = "Step 1: Upload"

# --- CORE FUNCTIONS (unchanged) ---
def extract_text_from_url(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        paragraphs = soup.find_all('p')
        if not paragraphs:
            st.warning("Could not find any paragraph text on this page.")
            return ""
        text = "\n".join([p.get_text() for p in paragraphs])
        return text
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
def rewrite_with_groq(text, progress_placeholder):
    chunks = chunk_text(text)
    rewritten = ""
    progress_bar = progress_placeholder.progress(0, text="Initializing rewrite...")
    for i, chunk in enumerate(chunks):
        try:
            response = client.chat.completions.create(model="llama-3.1-8b-instant", messages=[{"role": "system", "content": "You are an expert audiobook scriptwriter..."}, {"role": "user", "content": chunk}], temperature=0.7, max_tokens=4096)
            rewritten_chunk = response.choices[0].message.content.strip()
            rewritten += rewritten_chunk + " "
            progress_bar.progress((i + 1) / len(chunks), text=f"Rewriting chunk {i+1}/{len(chunks)}...")
        except Exception as e:
            st.error(f"Error processing chunk {i+1}: {e}")
    progress_bar.empty()
    return rewritten
def chunk_text(text, chunk_size=3000, overlap=200):
    chunks = []; start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        if end >= len(text): break
        start = end - overlap
    return chunks
def clean_text_for_tts(text):
    cleaned = re.sub(r'(\\|)(.?)(\\*|)', r'\2', text)
    cleaned = re.sub(r'(\|_)(.?)(\*|_)', r'\2', cleaned)
    cleaned = re.sub(r'^\s*[\\-]\s', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'^\s*\d+\.\s*', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'[#>`~=]', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned
async def _convert_text_to_speech_edge(text, voice, output_file):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_file)
def convert_text_to_speech_edge_tts(text, voice):
    cleaned_text = clean_text_for_tts(text)
    final_audio_path = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3").name
    try:
        asyncio.run(_convert_text_to_speech_edge(cleaned_text, voice, final_audio_path))
        return final_audio_path
    except Exception as e:
        st.error(f"Error during audio generation: {e}")
        return None

# --- STREAMLIT UI ---
st.title("AUDIO BOOK GENERATOR")
st.markdown("##### Transform documents and web articles into engaging audiobooks")

with st.sidebar:
    st.header("Audio Settings")
    voice_options = { "Aria (US, Female)": "en-US-AriaNeural", "Guy (US, Male)": "en-US-GuyNeural", "Sonia (UK, Female)": "en-GB-SoniaNeural" }
    selected_voice_name = st.selectbox("Choose a narrator:", list(voice_options.keys()))
    st.session_state.selected_voice_id = voice_options[selected_voice_name]
    st.markdown("---")
    st.markdown("Created by You | Powered by Groq & Streamlit")

# --- Navigation and Tab Content ---
tab_names = ["Step 1: Upload", "Step 2: Rewrite", "Step 3: Generate & Chat"]
st.session_state.active_tab = st.radio("Navigation", tab_names, horizontal=True, label_visibility="collapsed", key="navigation_radio")

if st.session_state.active_tab == "Step 1: Upload":
    st.header("Upload Your Source Material")
    input_method = st.radio("Choose input method:", ("Upload File(s)", "From a Web URL"), horizontal=True)

    if input_method == "Upload File(s)":
        # --- MODIFIED: Enabled multi-file upload ---
        uploaded_files = st.file_uploader(
            "Upload one or more PDF, DOCX, or TXT files.", 
            type=["pdf", "docx", "txt"], 
            accept_multiple_files=True, # This is the key change
            label_visibility="collapsed"
        )
        
        if uploaded_files:
            # --- MODIFIED: Logic to handle a list of files ---
            uploaded_filenames = [f.name for f in uploaded_files]
            if st.session_state.last_uploaded_files != uploaded_filenames:
                # Reset state for new files
                st.session_state.original_text, st.session_state.rewritten_text, st.session_state.audio_path, st.session_state.messages = "", "", None, []
                st.session_state.last_uploaded_files = uploaded_filenames
                
                all_text = ""
                with st.spinner(f"Extracting text from {len(uploaded_files)} file(s)..."):
                    for uploaded_file in uploaded_files:
                        if uploaded_file.name.endswith(".pdf"):
                            all_text += extract_text_from_pdf(uploaded_file) + "\n\n"
                        elif uploaded_file.name.endswith(".docx"):
                            all_text += extract_text_from_docx(uploaded_file) + "\n\n"
                        else:
                            all_text += uploaded_file.read().decode("utf-8") + "\n\n"
                st.session_state.original_text = all_text

            if st.session_state.original_text:
                st.success(f"Successfully extracted {len(st.session_state.original_text)} characters from {len(uploaded_files)} file(s).")
                if st.button("Proceed to Step 2: Rewrite →", use_container_width=True):
                    st.session_state.active_tab = "Step 2: Rewrite"; st.rerun()

    elif input_method == "From a Web URL":
        # (This part is unchanged)
        url = st.text_input("Enter the URL of an article:", "")
        if st.button("Extract Text from URL", use_container_width=True):
            if url:
                st.session_state.original_text, st.session_state.rewritten_text, st.session_state.audio_path, st.session_state.messages = "", "", None, []
                st.session_state.last_uploaded_files = url
                with st.spinner(f"Scraping text from {url}..."):
                    st.session_state.original_text = extract_text_from_url(url)
                if st.session_state.original_text:
                    st.success(f"Successfully extracted {len(st.session_state.original_text)} characters.")
                    st.markdown(f'<div class="text-container" style="height: 200px;">{st.session_state.original_text[:1000]}...</div>', unsafe_allow_html=True)
                    if st.button("Proceed to Step 2: Rewrite →", use_container_width=True):
                        st.session_state.active_tab = "Step 2: Rewrite"; st.rerun()
            else:
                st.warning("Please enter a URL.")

elif st.session_state.active_tab == "Step 2: Rewrite":
    # (This tab's code is unchanged)
    st.header("AI Script Rewriter")
    if not st.session_state.original_text: st.warning("Please upload a document or URL in Step 1 first.")
    else:
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Original Text")
            st.markdown(f'<div class="text-container">{st.session_state.original_text}</div>', unsafe_allow_html=True)
        with col2:
            st.subheader("Audiobook Script")
            if st.button("Rewrite with Groq LLM", use_container_width=True):
                progress_placeholder = st.empty()
                st.session_state.rewritten_text = rewrite_with_groq(st.session_state.original_text, progress_placeholder)
            if st.session_state.rewritten_text:
                 st.markdown(f'<div class="text-container">{st.session_state.rewritten_text}</div>', unsafe_allow_html=True)
                 if st.button("Proceed to Step 3: Generate & Chat →", use_container_width=True):
                     st.session_state.active_tab = "Step 3: Generate & Chat"; st.rerun()
            else:
                 st.markdown('<div class="text-container" style="display: flex; align-items: center; justify-content: center; color: #888;">Your rewritten script...</div>', unsafe_allow_html=True)

elif st.session_state.active_tab == "Step 3: Generate & Chat":
    # (This tab's code is unchanged)
    st.header("Final Audiobook Production")
    if not st.session_state.rewritten_text: st.warning("Please rewrite your script in Step 2 first.")
    else:
        if st.button("Generate Audio 🎧", type="primary", use_container_width=True):
            with st.spinner("Generating audio..."):
                st.session_state.audio_path = convert_text_to_speech_edge_tts(st.session_state.rewritten_text, st.session_state.selected_voice_id)
            if st.session_state.audio_path:
                st.success("Audiobook is ready!")

        if st.session_state.audio_path:
            st.subheader("Listen to Your Creation")
            st.audio(st.session_state.audio_path, format="audio/mp3")
            with open(st.session_state.audio_path, "rb") as f:
                st.download_button("⬇ Download Audiobook (MP3)", data=f, file_name="ai_audiobook.mp3", mime="audio/mp3", use_container_width=True)
            st.markdown("---")
            st.header("Chat with a General AI Assistant")
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])
            if prompt := st.chat_input("What would you like to know?"):
                st.session_state.messages.append({"role": "user", "content": prompt})
                try:
                    with st.spinner("Thinking..."):
                        chat_response = client.chat.completions.create(model="llama-3.1-8b-instant", messages=[{"role": "system", "content": "You are a helpful assistant."}, {"role": "user", "content": prompt}], temperature=0.7)
                        response_content = chat_response.choices[0].message.content
                        st.session_state.messages.append({"role": "assistant", "content": response_content})
                except Exception as e:
                    st.error(f"An error occurred: {e}")
                st.rerun()