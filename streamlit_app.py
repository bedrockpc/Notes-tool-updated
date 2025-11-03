import streamlit as st
from utils import summarize_with_gemini, get_video_id, save_to_pdf
from pathlib import Path
from io import BytesIO 
import json 
from typing import List, Dict, Any

# NOTE: Inject CSS call is removed from here and placed in utils.py for portability.

# --- 1. Page Configuration ---
st.set_page_config(
    page_title="AI Study Guide Generator",
    layout="centered",
    initial_sidebar_state="expanded"
)

# --- 2. Sidebar for Configuration (BYOA) ---
with st.sidebar:
    st.header("⚙️ Configuration")
    st.markdown("This app runs on a 'Bring Your Own API' model.")
    
    st.subheader("🔑 Gemini API Key")
    gemini_api_key = st.text_input(
        "Paste your Gemini API Key", 
        type="password", 
        help="Your key is not stored. It is only used for this session."
    )
    
    st.subheader("🔗 Video Link")
    video_url = st.text_input(
        "Paste the YouTube Video URL",
        placeholder="https://www.youtube.com/watch?v=...",
        help="Required for generating clickable timestamps in the PDF."
    )
    video_id = get_video_id(video_url)

# --- 3. Main Page Title ---
st.title("📚 AI Study Guide Generator")
st.markdown("Convert any video transcript into structured, hyperlinked study notes (PDF).")

# Initialize session state to hold the summary data
if 'summary_data' not in st.session_state:
    st.session_state.summary_data = None

# --- NEW: Format Selection Button ---
st.markdown("---")
format_choice = st.radio(
    "Choose PDF Reading Format:",
    options=["Default (Compact)", "Easier Read (Spacious & Highlighted)"],
    index=0,
    horizontal=True,
    key='pdf_format_choice',
    help="Easier Read format adds vertical spacing between lines and highlights content."
)
st.markdown("---")


# --- 4. Input Card ---
with st.container(border=True):
    st.header("1. Paste Your Transcript")
    
    transcript_text = st.text_area(
        "Video Transcript (must include timestamps)", 
        height=300,
        placeholder="Example: [00:30] Welcome to the lesson. [01:15] Today we discuss the derivative.",
        label_visibility="collapsed"
    )

    generate_button = st.button(
        "Generate Study Guide", 
        use_container_width=True, 
        type="primary"
    )

# --- 5. Processing Logic ---
if generate_button:
    st.session_state.summary_data = None
    
    # --- Validation ---
    if not gemini_api_key:
        st.error("🛑 **API Key Required.** Please enter your Gemini API Key in the sidebar.")
    elif not transcript_text.strip():
        st.error("🛑 **Transcript Required.** Please paste a transcript to begin.")
    elif not video_id:
        st.error("🛑 **Valid URL Required.** Please enter a valid YouTube URL.")
    else:
        # --- API Call ---
        with st.spinner("Analyzing transcript and generating structured notes..."):
            try:
                # The original summarize_with_gemini logic is used here
                summary_data = summarize_with_gemini(gemini_api_key, transcript_text)
                
                if summary_data:
                    st.session_state.summary_data = summary_data
                    st.success("✅ Analysis complete! Your PDF download link is ready below.")
                else:
                    st.error("❌ **Analysis Failed.** The API returned an empty or unparsable response. Please check your API key and try a shorter transcript.")
            
            except Exception as e:
                st.error(f"❌ **An Unhandled Error Occurred:** {e}")

# --- 6. Output Card ---
if st.session_state.summary_data:
    data = st.session_state.summary_data
    
    with st.container(border=True):
        st.header("2. Download Your File")
        st.markdown(f"Your PDF guide for **'{data.get('main_subject', 'Untitled Summary')}'** is ready.")

        try:
            font_path = Path(".")
            base_name = "AI_Study_Guide"

            # --- PDF File Generation ---
            pdf_bytes_io = BytesIO()
            
            # CRITICAL CHANGE: Pass the format_choice to save_to_pdf
            save_to_pdf(data, video_id, font_path, pdf_bytes_io, format_choice) 
            
            pdf_bytes = pdf_bytes_io.getvalue()
            
            # --- Download Button (Only PDF) ---
            st.download_button(
                label="⬇️ Download Structured Notes (PDF)",
                data=pdf_bytes,
                file_name=f"{base_name}_Notes.pdf",
                mime="application/pdf",
                use_container_width=True
            )

        except Exception as e:
            st.error(f"❌ **File Creation Error:** Failed to generate PDF. Error: {e}")
