import streamlit as st
from utils import inject_custom_css, get_video_id, run_analysis_and_summarize, save_to_pdf
from pathlib import Path
from io import BytesIO 
import json 
import time

# Call the CSS injection function
inject_custom_css()

# --- Application Setup ---
st.title("📹 AI-Powered Hyperlinked Video Notes Generator")

# Initialize session state variables
if 'analysis_data' not in st.session_state:
    st.session_state['analysis_data'] = None
if 'api_key_valid' not in st.session_state:
    st.session_state['api_key_valid'] = False
if 'output_filename_base' not in st.session_state:
    st.session_state['output_filename_base'] = "Video_Notes"


# --------------------------------------------------------------------------
# --- Sidebar for User Inputs (API, URL) and Controls ---
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("🔑 Configuration")
    
    # 1. API Key Input
    api_key = st.text_input(
        "Gemini API Key:", 
        type="password", 
        help="Required to run the AI analysis."
    )
    if api_key:
        st.session_state['api_key_valid'] = True
        st.success("API Key Entered.")
    else:
        st.session_state['api_key_valid'] = False
        st.warning("Please enter your Gemini API Key.")

    st.markdown("---")

    # 2. YouTube URL Input
    yt_url = st.text_input(
        "YouTube URL:",
        help="Paste the full link to the video here."
    )
    video_id = get_video_id(yt_url)
    if video_id:
        st.success(f"Video ID found: {video_id}")
    elif yt_url:
        st.error("Invalid YouTube URL format.")
    
    st.markdown("---")
    st.header("⚙️ Analysis Controls")

    # A. Slider for Output Words (AI Generation Control) - Max 10,000
    max_words = st.slider(
        '1. Max Detail Length (Word Limit):', 
        min_value=50, 
        max_value=10000, 
        value=200, 
        step=50, 
        help="Controls the word limit for each detail/explanation extracted by the AI."
    )
    
    st.markdown("---")

    # B. Checkboxes for Section Selection
    st.subheader("2. Select Output Sections")
    st.markdown("Choose which categories you want in the final notes:")
    
    section_options = {
        'Topic Breakdown': True, 
        'Key Vocabulary': True,
        'Formulas & Principles': True, 
        'Teacher Insights': False, 
        'Exam Focus Points': True, 
        'Common Mistakes': False,
        'Key Points': True,         
        'Short Tricks': False,      
        'Must Remembers': True      
    }
    
    sections_list = []
    for label, default_val in section_options.items():
        if st.checkbox(label, value=default_val):
            sections_list.append(label)

    st.markdown("---")
    
    # G. Custom Filename Input
    if video_id:
        st.session_state['output_filename_base'] = f"Notes_{video_id}"
    
    output_filename = st.text_input(
        "Name your PDF file:",
        value=st.session_state['output_filename_base'] + ".pdf",
        key="output_filename_input"
    )
    
# --------------------------------------------------------------------------
# --- Main Content: Transcript Input, Button, and Output ---
# --------------------------------------------------------------------------

st.subheader("Transcript Input")
transcript_text = st.text_area(
    '3. Paste the video transcript here (must include timestamps):',
    height=300,
    placeholder="[00:00] Welcome to the lesson. [00:45] We start with Topic A..."
)

user_prompt_input = st.text_area(
    '4. Refine AI Focus (Optional Prompt):',
    value="Ensure the output is highly condensed and only focus on practical applications and examples.",
    height=100
)

# E. The Analysis Trigger Button
can_run = transcript_text and video_id and st.session_state['api_key_valid']
run_analysis = st.button("🚀 Generate Hyperlinked Notes (PDF)", type="primary", disabled=not can_run) 

if run_analysis:
    
    # Run Analysis Logic
    with st.spinner('Contacting AI, synthesizing notes, and generating JSON...'):
        
        # The cached function executes the full Gemini pipeline
        data_json, error_msg, full_prompt = run_analysis_and_summarize(
            api_key, 
            transcript_text, 
            max_words, 
            sections_list, 
            user_prompt_input
        )
        
        st.session_state['full_prompt'] = full_prompt
        
        if data_json:
            st.session_state['analysis_data'] = data_json
            st.success("Analysis Complete! Generating PDF...")

            # --- PDF GENERATION ---
            current_dir = Path(__file__).parent
            
            # FIX: Check for font files directly in the current directory
            if not (current_dir / "NotoSans-Regular.ttf").exists():
                st.error("🚨 Font files not found! PDF generation requires 'NotoSans-Regular.ttf' and 'NotoSans-Bold.ttf' to be in the same directory as app.py.")
                st.session_state['pdf_ready'] = False
                
            else:
                pdf_output = BytesIO()
                try:
                    # Pass the current directory as the font path
                    save_to_pdf(data_json, video_id, current_dir, pdf_output) 
                    st.session_state['pdf_buffer'] = pdf_output
                    st.session_state['pdf_ready'] = True
                    st.session_state['json_output'] = json.dumps(data_json, indent=2)
                except Exception as e:
                    st.error(f"Error during PDF generation: {e}")
                    st.session_state['pdf_ready'] = False
        else:
            st.error(f"Analysis failed. Error: {error_msg}")
            st.session_state['pdf_ready'] = False
    
st.markdown("---")

# --------------------------------------------------------------------------
# --- Output Display and Download ---
# --------------------------------------------------------------------------

# Display Raw Transcript Preview (using the custom CSS for line gaps and scaling)
if transcript_text:
    st.subheader(f"Raw Transcript Preview")
    
    st.markdown(
        f'<div class="pdf-output-text">{transcript_text}</div>', 
        unsafe_allow_html=True
    )
    st.markdown("---")

# 5. Download Button
if st.session_state.get('pdf_ready', False):
    st.subheader("📥 Download Hyperlinked PDF Notes")
    
    st.download_button(
        label=f"Download {st.session_state['output_filename_base']}.pdf",
        data=st.session_state['pdf_buffer'],
        file_name=output_filename, 
        mime="application/pdf" 
    )

# Optional: Show the prompt that was sent to the AI
if st.session_state.get('full_prompt'):
    st.subheader("Full Prompt Sent to AI (Debugging):")
    st.code(st.session_state['full_prompt'], language='markdown')