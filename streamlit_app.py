import streamlit as st
import io
import time # Used for placeholder delay

# --- 0. Custom CSS for Styling (Larger Font & Reduced Line Gap) ---
def inject_custom_css():
    st.markdown(
        """
        <style>
        /* Increase overall font size for standard text and text areas */
        p, label, .stMarkdown, .stTextArea, .stSelectbox {
            font-size: 1.05rem !important; 
        }

        /* --- Custom class for output text with no gap --- */
        .pdf-output-text {
            border: 1px solid #ccc;
            padding: 15px;
            margin-top: 10px;
            background-color: #f9f9f9;
            /* Define a CSS variable to be used by the dynamic slider */
            --custom-font-size: 1.05rem; 
        }
        /* Target paragraphs/lines inside the output container to control spacing */
        .pdf-output-text p, .pdf-output-text div {
            font-size: var(--custom-font-size); /* Uses the CSS variable for scaling */
            line-height: 1.25;      /* Less line spacing (no gap) */
            margin-bottom: 0.2em;   /* Minimal space between lines/paragraphs */
        }
        </style>
        """,
        unsafe_allow_html=True
    )
inject_custom_css()

# --- 1. Caching Function to solve the Timestamp/Re-run Issue ---
@st.cache_data
def extract_text_from_pdf(pdf_file):
    """
    Reads PDF and extracts text. Cached to prevent re-running on widget changes.
    """
    if pdf_file is not None:
        # Simulate text extraction time
        time.sleep(2) 

        # --- PLACEHOLDER LOGIC ---
        st.session_state['file_name'] = pdf_file.name
        placeholder_text = f"""
        # Document: {pdf_file.name}
        ## Introduction / Executive Summary
        This section provides an overview of the analysis scope and the primary objectives. The research was initiated to determine the feasibility of the new feature set. The initial findings suggest a strong correlation between user engagement and the simplicity of the interface. This introductory text is intentionally longer to demonstrate the font scaling and line spacing.

        ## Methodology / Approach
        The method utilized a mixed-methods approach, combining quantitative A/B testing with qualitative user interviews. The testing ran over a 12-week period, gathering 50,000 data points. The control group used the old interface, and the test group used the proposed new layout.

        ## Results / Key Findings
        The key findings are significant. The test group showed a 45% increase in feature adoption compared to the control group (p < 0.01). However, the qualitative data revealed that 20% of users found the new feature placement confusing, indicating a potential design flaw in the final implementation.

        ## Discussion / Analysis
        The increase in adoption strongly validates the initial hypothesis regarding interface simplicity. The analysis suggests that minor tweaks to the feature placement could resolve the 20% confusion rate without sacrificing the overall engagement gains. The system proved robust, and the data integrity remained high throughout the test period.

        ## Conclusion / Summary
        In summary, the new feature set is highly effective and recommended for deployment, provided the minor design adjustment is implemented first. The project met all primary objectives, and the overall outcome is positive.
        """
        # --- END PLACEHOLDER LOGIC ---
        
        return placeholder_text
    return None

# --- Application Layout and Controls ---
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
        # Caching ensures this is only called once per uploaded file
        pdf_text = extract_text_from_pdf(pdf_file)
    st.success("PDF text successfully extracted and cached. Ready for analysis!")

    
# --- Sidebar for AI Controls ---
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

# --- 4. User Prompt and Analysis Generation ---

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
