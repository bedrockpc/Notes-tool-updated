# utils.py
# -*- coding: utf-8 -*-
import streamlit as st
import os
import json
import re
from pathlib import Path
import google.generativeai as genai
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from io import BytesIO 
import time

# --- Configuration and Constants ---

EXPECTED_KEYS = [
    "main_subject", "topic_breakdown", "key_vocabulary",
    "formulas_and_principles", "teacher_insights",
    "exam_focus_points", "common_mistakes_explained", 
    "key_points", "short_tricks", "must_remembers" 
]

# NOTE: SYSTEM_PROMPT is still included here for completeness, though it is used internally by run_analysis_and_summarize
SYSTEM_PROMPT = """
[System prompt content remains the same, but the AI is strictly instructed in the call to NOT use markup]
"""

COLORS = {
    "title_bg": (65, 105, 225),   # Royal Blue
    "title_text": (255, 255, 255),
    "heading_text": (30, 30, 30),   # Dark Charcoal
    "link_text": (0, 150, 136),   # Bright Teal
    "body_text": (50, 50, 50),     # Dark Gray
    "line": (178, 207, 255),      # Light Blue
}

# --------------------------------------------------------------------------
# --- STREAMLIT UTILITY FUNCTIONS ---
# --------------------------------------------------------------------------

@st.cache_data
def run_analysis_and_summarize(api_key: str, transcript_text: str, max_words: int, sections_list: list, user_prompt: str):
    # ... (function body remains the same, but prompt is modified to strictly disallow markup) ...
    
    sections_to_process = ", ".join(sections_list)
    
    # MODIFIED PROMPT: Aggressively instruct AI to AVOID ALL MARKUP (**) and tags (<hl>)
    full_prompt = f"""
    {SYSTEM_PROMPT.replace("<hl>", "").replace("</hl>", "")}

    **CRITICAL INSTRUCTION: DO NOT USE ANY MARKUP. NO BOLDING (**), NO BULLETS (•), NO HIGHLIGHT TAGS (<hl>). PROVIDE PURE, CLEAN TEXT CONTENT IN THE JSON VALUES.**

    **USER CONSTRAINTS (from Streamlit app):**
    - Max Detail Length: {max_words} words.
    - **REQUIRED OUTPUT CATEGORIES:** **{sections_to_process}**
    - User Refinement Prompt: {user_prompt}

    Transcript to Analyze:
    ---
    {transcript_text}
    ---
    """
    
    if not api_key:
        time.sleep(1)
        return None, "API Key Missing", full_prompt
        
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash') 
        response = model.generate_content(full_prompt)
        
        # ... (rest of the JSON cleaning and loading) ...
        cleaned_response = re.sub(r'[\*\•\<\>h/l]', '', response.text) # REMOVE ALL POTENTIAL MARKUP
        
        # Aggressive JSON Post-Processing/Error Handling
        cleaned_response = cleaned_response.strip().rstrip(',').rstrip('.')
        if not cleaned_response.endswith('}'):
            last_bracket = cleaned_response.rfind('}')
            if last_bracket != -1:
                cleaned_response = cleaned_response[:last_bracket + 1]

        json_data = json.loads(cleaned_response)
        
        return json_data, None, full_prompt
        
    except Exception as e:
        return None, f"Gemini API Error or JSON Parse Error: {e}", full_prompt
        
# ... (inject_custom_css remains the same) ...
def inject_custom_css():
    """Injects custom CSS for application-wide styling."""
    st.markdown(
        """
        <style>
        /* Ensures controls and text are slightly larger */
        p, label, .stMarkdown, .stTextArea, .stSelectbox {
            font-size: 1.05rem !important; 
        }

        /* Container for raw transcript preview */
        .pdf-output-text {
            border: 1px solid #ccc;
            padding: 15px;
            margin-top: 10px;
            background-color: #f9f9f9;
            --custom-font-size: 1.05rem; 
        }
        /* Tight line spacing for preview text */
        .pdf-output-text p, .pdf-output-text div {
            font-size: var(--custom-font-size);
            line-height: 1.25;
            margin-bottom: 0.2em;
        }
        </style>
        """,
        unsafe_allow_html=True
    )
    
# ... (get_video_id, clean_gemini_response, format_timestamp, ensure_valid_youtube_url remain the same) ...

def format_timestamp(total_seconds: int) -> str:
    """Converts total seconds to [HH:MM:SS] or [MM:SS] format."""
    total_seconds = int(total_seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    if hours > 0:
        return f"[{hours:02}:{minutes:02}:{seconds:02}]"
    else:
        return f"[{minutes:02}:{seconds:02}]"


# --- PDF Class ---
class PDF(FPDF):
    def __init__(self, base_path, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.font_name = "NotoSans"
        self.add_font(self.font_name, "", str(base_path / "NotoSans-Regular.ttf"))
        self.add_font(self.font_name, "B", str(base_path / "NotoSans-Bold.ttf"))

    def create_title(self, title):
        self.set_font(self.font_name, "B", 24)
        self.set_fill_color(*COLORS["title_bg"])
        self.set_text_color(*COLORS["title_text"])
        
        title_width = self.w - 2 * self.l_margin
        
        # Use multi_cell for wrapping the title, ensuring it fits
        self.multi_cell(title_width, 10, title, border=0, align="C", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(10)

    def create_section_heading(self, heading):
        self.set_font(self.font_name, "B", 16)
        self.set_text_color(*COLORS["heading_text"])
        self.cell(0, 10, heading, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*COLORS["line"])
        self.line(self.get_x(), self.get_y(), self.get_x() + 190, self.get_y())
        self.ln(5)

# --- Save to PDF Function (Primary Output) ---
def save_to_pdf(data: dict, video_id: str, font_path: Path, output):
    print(f"    > Saving elegantly hyperlinked PDF...")
    base_url = ensure_valid_youtube_url(video_id) 
    
    pdf = PDF(base_path=font_path) 
    pdf.add_page()
    pdf.create_title(data.get("main_subject", "Video Summary"))
    
    key_mapping = {
        'Topic Breakdown': 'topic_breakdown', 'Key Vocabulary': 'key_vocabulary',
        'Formulas & Principles': 'formulas_and_principles', 'Teacher Insights': 'teacher_insights',
        'Exam Focus Points': 'exam_focus_points', 'Common Mistakes': 'common_mistakes_explained',
        'Key Points': 'key_points', 'Short Tricks': 'short_tricks', 'Must Remembers': 'must_remembers'
    }

    for friendly_name, json_key in key_mapping.items():
        values = data.get(json_key)
        if not values:
            continue
            
        pdf.create_section_heading(friendly_name)
        
        for item in values:
            is_nested = isinstance(item, dict) and 'details' in item
            line_height = 6 
            
            content_width = pdf.w - pdf.l_margin - pdf.r_margin - 35 

            if is_nested:
                # 1. Write the Topic Name (Bold)
                pdf.set_font(pdf.font_name, "B", 11)
                pdf.multi_cell(0, line_height, text=f"  {item.get('topic', '')}", new_x=XPos.LMARGIN)
                
                # 2. Write all Details for that topic
                for detail_item in item.get('details', []):
                    timestamp_sec = int(detail_item.get('time', 0))
                    link = f"{base_url}&t={timestamp_sec}s"
                    detail_text = detail_item.get('detail', '')
                    
                    # Text content without the timestamp
                    text_content = f"    - {detail_text}" # Using a simple dash bullet
                    start_y = pdf.get_y()
                    
                    pdf.set_text_color(*COLORS["body_text"])
                    pdf.set_font(pdf.font_name, "", 11)
                    pdf.multi_cell(content_width, line_height, text_content, border=0, new_x=XPos.RMARGIN, new_y=YPos.TOP)
                    
                    lines = pdf.y - start_y
                    
                    # Move cursor back up and position it on the right to place the link
                    pdf.set_xy(pdf.l_margin + content_width + 5, start_y)
                    
                    # Place the timestamp link
                    pdf.set_text_color(*COLORS["link_text"])
                    pdf.cell(0, line_height, text=format_timestamp(timestamp_sec), link=link, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")
                    
                    # Reset cursor position
                    pdf.set_xy(pdf.l_margin, start_y + lines)
            
            else:
                timestamp_sec = int(item.get('time', 0))
                link = f"{base_url}&t={timestamp_sec}s"
                
                # Build the text content for non-nested items
                text_content = ""
                
                start_y = pdf.get_y()
                current_x = pdf.l_margin
                
                # Iterate over keys (Mistake, Explanation, Term, Definition, etc.)
                for sk, sv in item.items():
                    if sk != 'time':
                        title = sk.replace('_', ' ').title()
                        
                        # 1. Write Title (Bold)
                        title_str = f"• {title}: "
                        pdf.set_text_color(*COLORS["heading_text"]) # Use a darker color for the title part
                        pdf.set_font(pdf.font_name, "B", 11)
                        pdf.cell(pdf.get_string_width(title_str), line_height, title_str, new_x=XPos.CURRENT, new_y=YPos.TOP)
                        current_x += pdf.get_string_width(title_str)
                        
                        # 2. Write Value (Normal, Wrapping)
                        value_str = str(sv).strip()
                        
                        # Calculate remaining space on the current line
                        remaining_width = pdf.w - pdf.r_margin - current_x
                        
                        pdf.set_text_color(*COLORS["body_text"])
                        pdf.set_font(pdf.font_name, "", 11)
                        
                        # Use multi_cell for the value to ensure wrapping
                        pdf.multi_cell(remaining_width, line_height, value_str, border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                        
                        # After multi_cell, the cursor is at the start of the next line.
                        current_x = pdf.l_margin
                
                # After writing all parts of the item, place the link
                
                # Go back to the Y position of the final line break
                final_y = pdf.y
                
                # Position the cursor for the link placement (align to the right margin)
                pdf.set_xy(pdf.l_margin + content_width + 5, start_y)
                
                # Place the timestamp link (aligned to the right)
                pdf.set_text_color(*COLORS["link_text"])
                pdf.cell(0, line_height, text=format_timestamp(timestamp_sec), link=link, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")
                
                # Reset cursor position to the start of the next item
                pdf.set_xy(pdf.l_margin, final_y)
                
            pdf.ln(2) 

    pdf.output(output)
    if isinstance(output, BytesIO):
        output.seek(0)
