import streamlit as st
from utils import inject_custom_css, get_video_id, run_analysis_and_summarize, save_to_pdf
from pathlib import Path
from io import BytesIO 
import json 
from typing import List, Dict, Any

# Call the CSS injection function
inject_custom_css()

# --- Application Setup ---
st.title("📹 AI-Powered Hyperlinked Video Notes Generator")

# --- Model Context Constants ---
WARNING_THRESHOLD_CHARS = 300000 

# Initialize session state variables
if 'analysis_data' not in st.session_state:
    st.session_state['analysis_data'] = None
if 'api_key_valid' not in st.session_state:
    st.session_state['api_key_valid'] = False
if 'output_filename_base' not in st.session_state:
    st.session_state['output_filename_base'] = "Video_Notes"
if 'chunked_results' not in st.session_state:
    st.session_state['chunked_results'] = []
if 'processing' not in st.session_state:
    st.session_state['processing'] = False
if 'max_words_value' not in st.session_state:
    st.session_state['max_words_value'] = 3000 # Default for Pro model

# --- 🔧 CORE HELPER FUNCTIONS ---

def split_transcript_by_parts(transcript: str, num_parts: int) -> List[str]:
    """Splits transcript text into equal parts, clamping num_parts to avoid empty strings."""
    text = transcript or ""
    length = len(text)
    
    num_parts = max(1, min(num_parts, length)) 
    part_size = length // num_parts
    
    parts = []
    for i in range(num_parts):
        start = i * part_size
        end = (i + 1) * part_size if i < num_parts - 1 else length
        parts.append(text[start:end])
    return parts

def merge_all_json_outputs(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    FIX: Combines outputs, initializing all list keys to guarantee the PDF structure.
    This prevents iterating over empty keys later.
    """
    
    # Master list of keys the PDF generator relies on (list types only)
    LIST_KEYS = [
        "topic_breakdown", "key_vocabulary", "formulas_and_principles", 
        "teacher_insights", "exam_focus_points", "common_mistakes_explained", 
        "key_points", "short_tricks", "must_remembers"
    ]
    
    combined: Dict[str, Any] = {"main_subject": ""}
    
    # Initialize all list keys as empty lists
    for key in LIST_KEYS:
        combined[key] = []
        
    for res in results:
        for k, v in res.items():
            if k == "main_subject":
                # Take first non-empty subject
                if not combined.get("main_subject") and v:
                    combined["main_subject"] = str(v).strip()
                continue

            if isinstance(v, list) and k in LIST_KEYS:
                # Append to the already initialized list
                combined[k].extend(v)
    
    # Final Deduplication Logic
    for k in LIST_KEYS:
        if k in combined:
            seen = set()
            combined[k] = [
                item for item in combined[k] 
                if not (s := json.dumps(item, sort_keys=True) if isinstance(item, (dict, list)) else str(item)) or s not in seen and not seen.add(s)
            ]
            
    return combined

def update_word_limit_default():
    """Sets the default max_words value based on the selected model using callback."""
    model = st.session_state.get('model_choice_select', 'gemini-2.5-pro')
    if model == "gemini-2.5-flash":
        st.session_state['max_words_value'] = 1000 # Flash default
    else: # Pro
        st.session_state['max_words_value'] = 3000 # Pro default


# --------------------------------------------------------------------------
# --- Sidebar for User Inputs and Controls ---
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("🔑 Configuration")
    
    # 2. Model Selection Dropdown (with callback)
    model_choice = st.selectbox(
        "Select Gemini Model:",
        options=["gemini-2.5-pro", "gemini-2.5-flash"],
        index=0, 
        key='model_choice_select', 
        on_change=update_word_limit_default, 
        help="Pro = better reasoning, 1M token context. Flash = cheaper, faster, smaller context."
    )
    
    # 1. API Key Input
    api_key = st.text_input("Gemini API Key:", type="password")
    if api_key:
        st.session_state['api_key_valid'] = True
        st.success("API Key Entered.")
    else:
        st.session_state['api_key_valid'] = False
        st.warning("Please enter your Gemini API Key.")

    st.markdown("---")

    # 2. YouTube URL Input
    yt_url = st.text_input("YouTube URL:")
    video_id = get_video_id(yt_url)
    if video_id:
        st.success(f"Video ID found: {video_id}")
    elif yt_url:
        st.error("Invalid YouTube URL format.")
    
    st.markdown("---")
    st.header("⚙️ Analysis Controls")

    # 3. Automatic Chunking Behavior (Adaptive UI)
    is_flash = model_choice == "gemini-2.5-flash"
    num_parts = 1 # Default for Pro

    if is_flash:
        st.subheader("Chunking Settings")
        num_parts = st.number_input(
            "Divide transcript into how many parts?",
            min_value=1,
            max_value=10,
            value=3, # Default for Flash
            step=1,
            key='num_parts_input',
            help="Split transcript into parts before sending to Gemini Flash."
        )
    else:
        st.info("Gemini 2.5 Pro handles the full transcript in one call (no manual chunking needed).")

    # A. Max Detail Length (Word Limit)
    st.subheader("Max Detail Length")
    max_words = st.number_input(
        'Word Limit per Note Item:', 
        min_value=50, 
        max_value=10000, 
        value=st.session_state['max_words_value'], 
        step=50, 
        key='max_words_input', 
        help="Controls the word limit for each detail/explanation extracted by the AI."
    )
    
    st.markdown("---")

    # B. Checkboxes for Section Selection
    section_options = {
        'Topic Breakdown': True, 'Key Vocabulary': True,
        'Formulas & Principles': True, 'Teacher Insights': False, 
        'Exam Focus Points': True, 'Common Mistakes': False,
        'Key Points': True, 'Short Tricks': False, 'Must Remembers': True      
    }
    
    sections_list = []
    st.subheader("Select Output Sections")
    for label, default_val in section_options.items():
        if st.checkbox(label, value=default_val):
            sections_list.append(label)

    st.markdown("---")
    
    # G. Custom Filename Input
    if video_id:
        st.session_state['output_filename_base'] = f"Notes_{video_id}"
    
    output_filename_base = st.session_state['output_filename_base']
    output_filename = st.text_input(
        "Base Name for PDF file:",
        value=output_filename_base + ".pdf",
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

# Optional Transcript Warning
if len(transcript_text) > WARNING_THRESHOLD_CHARS and model_choice == "gemini-2.5-flash":
    st.warning(f"⚠️ **Long Transcript Detected!** The text is over {WARNING_THRESHOLD_CHARS} characters. We recommend selecting **Gemini 2.5 Pro** or dividing the transcript into **4 or more parts** to avoid context overflow with Flash.")

user_prompt_input = st.text_area(
    '4. Refine AI Focus (Optional Prompt):',
    value="Ensure the output is highly condensed and only focus on practical applications and examples.",
    height=100
)

# E. The Analysis Trigger Button
can_run = transcript_text and video_id and st.session_state['api_key_valid']
run_analysis = st.button(
    f"🚀 Generate Notes using {model_choice}", 
    type="primary", 
    disabled=not can_run or st.session_state['processing']
) 

if run_analysis and not st.session_state['processing']:
    st.session_state['processing'] = True
    st.session_state['chunked_results'] = []
    
    try:
        # 4. Transcript Splitting Logic
        if is_flash:
            transcript_parts = split_transcript_by_parts(transcript_text, int(num_parts))
        else:
            transcript_parts = [transcript_text] # Pro runs the full transcript in one part
        
        st.info(f"Analyzing in **{len(transcript_parts)}** sequential part(s) using **{model_choice}**.")

        # 6. Chunked Execution
        status_bar = st.progress(0, text="Starting analysis...")
        
        for i, part in enumerate(transcript_parts, start=1):
            status_bar.progress(
                i / len(transcript_parts), 
                text=f'Analyzing Part {i} of {len(transcript_parts)}... (Model: {model_choice})'
            )
            
            data_json, error_msg, full_prompt = run_analysis_and_summarize(
                api_key, part, max_words, sections_list, user_prompt_input, model_choice
            )
            
            if data_json:
                st.session_state['chunked_results'].append(data_json)
            else:
                st.error(f"Analysis failed for Part {i}. Error: {error_msg}")
                st.session_state['chunked_results'] = []
                break

        status_bar.empty()

        if st.session_state['chunked_results']:
            st.success(f"Analysis complete for all {len(st.session_state['chunked_results'])} parts.")
            st.session_state['pdf_ready'] = True
        else:
            st.session_state['pdf_ready'] = False
            
    finally:
        st.session_state['processing'] = False

st.markdown("---")

# 7. Output Options and Download Section
if st.session_state['chunked_results']:
    st.subheader("🧩 Output Options")
    combine_choice = st.radio(
        "Choose how to handle analyzed chunks:",
        options=["🔗 Combine all outputs into one file", "📦 Download each part separately"],
        index=0,
        help="You can merge all analyzed chunks into a single hyperlinked PDF, or keep each chunk's output separate."
    )

    current_dir = Path(__file__).parent

    if combine_choice.startswith("🔗"):
        # 3. Combine Logic
        st.subheader("Single Merged PDF")
        
        # Merge the data using the helper function (guarantees all keys exist)
        combined_data = merge_all_json_outputs(st.session_state['chunked_results'])
        
        pdf_output = BytesIO()
        try:
            with st.spinner("Generating combined PDF..."):
                save_to_pdf(combined_data, video_id, current_dir, pdf_output)
            
            st.download_button(
                label=f"⬇️ Download Merged Notes: {output_filename_base}.pdf",
                data=pdf_output,
                file_name=output_filename, 
                mime="application/pdf" 
            )
        except Exception as e:
            st.error(f"Error generating merged PDF: {e}")
            st.warning("Ensure font files (NotoSans-*.ttf) are in the main directory.")

    else:
        # 4. Separate Download Logic
        st.subheader("Separate PDF Downloads")
        st.info("Each part represents a section of the original transcript.")

        for i, part_data in enumerate(st.session_state['chunked_results'], start=1):
            pdf_output = BytesIO()
            
            try:
                with st.spinner(f"Preparing Part {i}..."):
                    save_to_pdf(part_data, video_id, current_dir, pdf_output)
                
                st.download_button(
                    label=f"⬇️ Download Part {i}",
                    data=pdf_output,
                    file_name=f"{output_filename_base}_part{i}.pdf",
                    mime="application/pdf",
                    key=f'download_part_{i}'
                )
            except Exception as e:
                st.error(f"Error generating Part {i} PDF: {e}")
                break

st.markdown("---")

if not st.session_state['chunked_results'] and st.session_state.get('pdf_ready'):
    st.warning("Analysis ran successfully, but no output was generated. Please verify your transcript and settings.")