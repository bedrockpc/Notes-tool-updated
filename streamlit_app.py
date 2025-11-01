import streamlit as st
import io
# Import the functions from the new utils.py file
from utils import extract_text_from_pdf, inject_custom_css 
import time # Used for placeholder delay

# Call the CSS injection function immediately upon script execution
inject_custom_css()

# --- Application Setup ---
st.title("📄 AI-Powered PDF Analysis Tool")

# Initialize session state for analysis response and file name
if 'final_llm_response' not in st.session_state:
    st.session_state['final_llm_response'] = ""
if 'file_name' not in st.session_state:
    st.session_state['file_name'] = "Uploaded_Document"


# --- File Uploader ---
pdf_file = st.file_uploader("Upload your PDF document", type=["pdf"])

pdf_text = None
if pdf_file:
    with st.spinner(f'Processing and caching text from {pdf_file.name}...'):
        # Caching function called from utils.py
        pdf_text = extract_text_from_pdf(pdf_file)
    st.success("PDF text successfully extracted and cached. Ready for analysis!")

    
# --------------------------------------------------------------------------
# --- Sidebar for User Controls ---
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Analysis Controls")

    # A. Slider for Output Words (AI Generation Control)
    max_words = st.slider(
        '1. Maximum AI Output Words:', 
        min_value=50, max_value=500, value=200, step=25,
        help="Controls the max length of the summary the AI will generate (max_tokens)."
    )
    
    st.markdown("---")

    # B. Checkboxes for Section Selection
    st.subheader("2. Select Sections to Process")
    st.markdown("The AI will prioritize these topics for analysis:")
    
    process_intro = st.checkbox('Introduction / Executive Summary', value=True)
    process_method = st.checkbox('Methodology / Approach', value=False)
    process_results = st.checkbox('Results / Key Findings', value=True)
    process_discuss = st.checkbox('Discussion / Analysis', value=False)
    process_concl = st.checkbox('Conclusion / Summary', value=True)

    sections_list = []
    if process_intro: sections_list.append("Introduction / Executive Summary")
    if process_method: sections_list.append("Methodology / Approach")
    if process_results: sections_list.append("Results / Key Findings")
    if process_discuss: sections_list.append("Discussion / Analysis")
    if process_concl: sections_list.append("Conclusion / Summary")

    st.markdown("---")
    
    # C. Visual Scaling Slider (for PDF display)
    scaling_options = ['Default', 'Large', 'X-Large', 'Huge']
    selected_scale = st.select_slider(
        '3. Display Font Size / Scaling:',
        options=scaling_options,
        value='Default',
        help="Visually scales the raw PDF text display equally."
    )
    
    # Map the selected option to a CSS font-size value
    scale_map = {
        'Default': '1.05rem',
        'Large': '1.2rem',
        'X-Large': '1.35rem',
        'Huge': '1.5rem',
    }
    font_size_css = scale_map[selected_scale]

    st.markdown("---")
    
    # G. Custom Filename Input (for the download button)
    default_name = f"AI_Analysis_of_{st.session_state['file_name'].replace('.pdf', '')}.txt"
    output_filename = st.text_input(
        "Name your analysis file:",
        value=default_name,
        key="output_filename_input"
    )

st.markdown("---")

# --------------------------------------------------------------------------
# --- Main Content: Prompt, Button, and Output ---
# --------------------------------------------------------------------------

if pdf_text:
    
    # D. Better Prompt Input
    user_prompt_input = st.text_area(
        '4. Refine Your Analysis Prompt:',
        value="Summarize the key findings and the final recommendation. What is the single most important quantitative result?",
        height=150
    )
    
    # E. The Analysis Trigger Button
    run_analysis = st.button("🚀 Run AI Analysis", type="primary") 
    
    if run_analysis:
        
        # 1. Gather all inputs (Slider, Checkboxes)
        sections_to_process = ", ".join(sections_list)
        
        # 2. Define the Unified, Enhanced Prompt Template
        better_prompt = f"""
        **ROLE AND INSTRUCTION:**
        You are a highly skilled **Academic/Data Analyst**. Your goal is to extract, analyze, and synthesize information strictly from the provided document text.

        **CONSTRAINT:**
        Your final output **must not exceed {max_words} words**. Maintain a professional, objective, and academic tone.

        **USER FOCUS AREA:**
        The user is specifically interested in the following document sections: **{sections_to_process}**. Use these as the primary source for your response.

        **CORE TASK (User's Specific Input):**
        **{user_prompt_input}**

        **DOCUMENT TEXT FOR ANALYSIS:**
        ---
        {pdf_text}
        ---

        **FINAL OUTPUT FORMAT:**
        Provide the analysis directly, without any preamble or introductory phrases.
        """
        
        # 3. Add a spinner for better user experience while waiting
        with st.spinner('Contacting AI and synthesizing response...'):
            # --- Placeholder for LLM API call ---
            time.sleep(4) # Simulate network/processing delay
            llm_response = f"AI Analysis (Max Words: {max_words}, Sections: {sections_to_process}):\n\nThe most important quantitative result is the 45% increase in feature adoption found in the Results section. This strongly validates the hypothesis. The final recommendation is to proceed with deployment after fixing the minor confusion issue noted in the Discussion section. This analysis was generated strictly adhering to the {max_words}-word limit and the specific sections you selected."
            # --- End Placeholder ---

            # Save the final response to session state for the download button
            st.session_state['final_llm_response'] = llm_response
            
            # Display the result to the user
            st.success("Analysis Complete!")
            st.markdown("### AI Analysis Result:")
            st.info(llm_response)

        st.markdown("---")
        
        # Optional: Show the prompt that was sent to the AI
        st.subheader("Final Enhanced Prompt Sent to AI:")
        st.code(better_prompt, language='markdown')


    # F. Display the Processed PDF Text with Dynamic Scaling
    st.subheader(f"Raw PDF Text Preview (Scaled to {selected_scale})")
    
    # Inject the dynamic CSS variable into the output container
    st.markdown(
        f'<div class="pdf-output-text" style="--custom-font-size: {font_size_css};">{pdf_text.replace("##", "####")}</div>', 
        unsafe_allow_html=True
    )
    
# --- 5. Download Button (Only visible if analysis has run) ---
if st.session_state['final_llm_response']:
    st.markdown("---")
    st.subheader("📥 Download Analysis")
    
    st.download_button(
        label=f"Download '{output_filename}'",
        data=st.session_state['final_llm_response'],
        file_name=output_filename, # Uses the user-defined filename!
        mime="text/plain" 
    )
