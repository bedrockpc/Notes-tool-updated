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
# (Keys, SYSTEM_PROMPT, and COLORS remain the same for brevity)
# ... [Keeping original content for these sections] ...

EXPECTED_KEYS = [
    "main_subject", "topic_breakdown", "key_vocabulary",
    "formulas_and_principles", "teacher_insights",
    "exam_focus_points", "common_mistakes_explained", 
    "key_points", "short_tricks", "must_remembers" 
]

SYSTEM_PROMPT = """
You are a master academic analyst creating a concise, hyperlinked study guide from a video transcript file. The transcript text contains timestamps in formats like (MM:SS) or [HH:MM:SS].

**Primary Goal:** Create a detailed summary. For any key point you extract, you MUST find its closest preceding timestamp in the text and include it in your response as total seconds.

**Instructions:**
1.  Analyze the entire transcript.
2.  For every piece of information you extract, find the nearest timestamp that comes *before* it in the text. Convert that timestamp into **total seconds** (e.g., (01:30) becomes 90).
3.  **Highlighting:** Inside any 'detail', 'definition', 'explanation', or 'insight' string, find the single most critical phrase (3-5 words) and wrap it in `<hl>` and `</hl>` tags. Do this only once per item where appropriate.
4.  Be concise. Each point must be a short, clear sentence.
5.  Extract the information for the following categories. **Only include a category in the final JSON if the user specifically requested it.**

The JSON structure must include these keys with objects/arrays:
{
  "main_subject": "A short phrase identifying the main subject.",
  "topic_breakdown": [{"topic": "Topic 1", "details": [{"detail": "This is a <hl>short detail</hl>.", "time": 120}]}],
  "key_vocabulary": [{"term": "Term 1", "definition": "A <hl>short definition</hl>.", "time": 150}],
  "formulas_and_principles": [{"formula_or_principle": "Principle 1", "explanation": "A <hl>brief explanation</hl>.", "time": 180}],
  "teacher_insights": [{"insight": "<hl>Short insight</hl> 1.", "time": 210}],
  "exam_focus_points": [{"point": "Brief <hl>focus point</hl> 1.", "time": 240}],
  "common_mistakes_explained": [{"mistake": "Mistake 1", "explanation": "A <hl>short explanation</hl>.", "time": 270}],
  "key_points": [{"point": "A major <hl>takeaway point</hl>.", "time": 300}],
  "short_tricks": [{"trick": "A <hl>quick method</hl> to solve a problem.", "time": 330}],
  "must_remembers": [{"fact": "A fact that <hl>must be memorized</hl>.", "time": 360}]
}
"""

COLORS = {
    "title_bg": (40, 54, 85), "title_text": (255, 255, 255),
    "heading_text": (40, 54, 85), "link_text": (0, 0, 255), 
    "body_text": (30, 30, 30), "line": (220, 220, 220),
    "highlight_bg": (255, 255, 0)
}

# --------------------------------------------------------------------------
# --- STREAMLIT UTILITY FUNCTIONS ---
# --------------------------------------------------------------------------

@st.cache_data
def run_analysis_and_summarize(api_key: str, transcript_text: str, max_words: int, sections_list: list, user_prompt: str):
    """
    Runs the full analysis using the Gemini API. 
    Cached to prevent re-running if parameters haven't changed.
    """
    
    sections_to_process = ", ".join(sections_list)
    
    full_prompt = f"""
    {SYSTEM_PROMPT}

    **USER CONSTRAINTS (from Streamlit app):**
    - Max Detail Length: {max_words} words (Limit the length of each detail/explanation string).
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
        
    print("    > Sending transcript to Gemini API...")
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash') 
        
        response = model.generate_content(full_prompt)
        
        cleaned_response = clean_gemini_response(response.text)
        
        # Aggressive JSON Post-Processing/Error Handling
        cleaned_response = cleaned_response.strip().rstrip(',').rstrip('.')
        if not cleaned_response.endswith('}'):
            last_bracket = cleaned_response.rfind('}')
            if last_bracket != -1:
                cleaned_response = cleaned_response[:last_bracket + 1]

        json_data = json.loads(cleaned_response)
        
        return json_data, None, full_prompt
        
    except json.JSONDecodeError:
        return None, "JSON DECODE ERROR: AI response was malformed.", full_prompt
    except Exception as e:
        return None, f"Gemini API Error: {e}", full_prompt
        
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
    
# --------------------------------------------------------------------------
# --- ORIGINAL HELPER FUNCTIONS (Corrected) ---
# --------------------------------------------------------------------------

def get_video_id(url: str) -> str | None:
    patterns = [
        r"(?<=v=)[^&#?]+", r"(?<=be/)[^&#?]+", r"(?<=live/)[^&#?]+",
        r"(?<=embed/)[^&#?]+", r"(?<=shorts/)[^&#?]+"
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match: return match.group(0)
    return None

def clean_gemini_response(response_text: str) -> str:
    match = re.search(r'```json\s*(\{.*?\})\s*```|(\{.*?\})', response_text, re.DOTALL)
    if match: return match.group(1) if match.group(1) else match.group(2)
    return response_text.strip()

def format_timestamp(total_seconds: int) -> str:
    """Converts total seconds to [HH:MM:SS] or [MM:SS] format."""
    
    # Calculate hours, minutes, and remaining seconds
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    if hours > 0:
        return f"[{hours:02}:{minutes:02}:{seconds:02}]"
    else:
        return f"[{minutes:02}:{seconds:02}]"

def ensure_valid_youtube_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"

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
        self.cell(0, 20, title, align="C", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(10)

    def create_section_heading(self, heading):
        self.set_font(self.font_name, "B", 16)
        self.set_text_color(*COLORS["heading_text"])
        self.cell(0, 10, heading, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*COLORS["line"])
        self.line(self.get_x(), self.get_y(), self.get_x() + 190, self.get_y())
        self.ln(5)

    # UPDATED: This method now wraps the text using multi_cell
    def write_highlighted_text(self, text, style=''):
        self.set_font(self.font_name, style, 11)
        self.set_text_color(*COLORS["body_text"])
        
        line_height = 6 
        
        parts = re.split(r'(<hl>.*?</hl>)', text)
        
        # Start a new block of text that can wrap
        start_x = self.get_x()
        start_y = self.get_y()
        current_x = start_x
        
        for part in parts:
            if part.startswith('<hl>'):
                highlight_text = part[4:-5]
                self.set_fill_color(*COLORS["highlight_bg"])
                self.set_font(self.font_name, 'B', 11)
                
                # Use cell for the highlighted part to maintain background color
                w = self.get_string_width(highlight_text)
                self.cell(w, line_height, highlight_text, fill=True, new_x=XPos.CURRENT)
                
                self.set_font(self.font_name, style, 11)
                current_x += w
            else:
                # Use write for the standard part, which is essential for placing continuous text
                self.set_fill_color(255, 255, 255)
                w = self.get_string_width(part)
                
                # Check if the part will exceed the page margin
                if current_x + w > self.w - self.r_margin:
                    # If it exceeds, force a line break using multi_cell to handle wrapping
                    self.multi_cell(self.w - self.l_margin - self.r_margin, line_height, part, new_x=XPos.LMARGIN)
                    current_x = self.get_x() + w # Reset current X position
                else:
                    self.write(line_height, part)
                    current_x += w
        
        # Move to the next line after the entire content is written
        self.ln(line_height) 


# --- Save to PDF Function (Primary Output) ---
def save_to_pdf(data: dict, video_id: str, font_path: Path, output):
    print(f"    > Saving elegantly hyperlinked PDF...")
    base_url = ensure_valid_youtube_url(video_id) 
    
    pdf = PDF(base_path=font_path) 
    pdf.add_page()
    pdf.create_title(data.get("main_subject", "Video Summary"))
    
    # Map friendly section names to their JSON keys
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
            
            # --- START A NEW WRAPPING BLOCK ---
            
            if is_nested:
                # 1. Write the Topic Name
                pdf.set_font(pdf.font_name, "B", 11)
                pdf.multi_cell(0, line_height, text=f"  {item.get('topic', '')}", new_x=XPos.LMARGIN)
                
                # 2. Write all Details for that topic
                for detail_item in item.get('details', []):
                    timestamp_sec = int(detail_item.get('time', 0))
                    link = f"{base_url}&t={timestamp_sec}s"
                    detail_text = detail_item.get('detail', '')
                    
                    # Create the full text line including the timestamp
                    display_text = f"    • {detail_text} {format_timestamp(timestamp_sec)}"
                    
                    # Use multi_cell for wrapping the entire detail line
                    pdf.set_font(pdf.font_name, "", 11)
                    
                    # Find and format highlighted parts within the detail text
                    highlighted_parts = re.split(r'(<hl>.*?</hl>)', display_text)
                    
                    # Temporarily store the start position for hyperlinking
                    start_x = pdf.get_x()
                    start_y = pdf.get_y()
                    
                    # We write the hyperlinked timestamp manually to the end of the line.
                    # First, we write the text content which wraps.
                    pdf.set_text_color(*COLORS["body_text"])
                    
                    # 90% width for the main text, reserving space for the timestamp on the same line
                    main_text_width = pdf.w - pdf.l_margin - pdf.r_margin - 30 
                    
                    # Use write() parts for highlighting. The text is written and wraps automatically.
                    # NOTE: multi_cell() is generally better for wrapping whole paragraphs. 
                    # For combined text, we revert to writing parts and setting the link/text color at the end.
                    
                    # For simplicity and correctness with linking:
                    # Write the content without the timestamp first, using a custom-wrapping function if needed,
                    # but here we simplify to the most robust wrapping method:
                    
                    pdf.set_text_color(*COLORS["body_text"])
                    pdf.set_font(pdf.font_name, "", 11)
                    
                    # The text part (excluding the timestamp)
                    text_only = display_text.replace(format_timestamp(timestamp_sec), '').strip()
                    
                    # Use the standard multi_cell for wrapping the main text content (the detail)
                    pdf.multi_cell(main_text_width, line_height, text_only, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                    
                    # Now position the cursor back to the right margin to place the link
                    
                    # Go back to the position before the multi_cell wrapped the line. 
                    # This is tricky with fpdf2, so we place the link at the START of the line 
                    # and align it right, or place it on the line after the wrapped text.
                    
                    # Place the timestamp link right below the wrapped text for reliable placement
                    pdf.set_text_color(*COLORS["link_text"])
                    pdf.cell(0, line_height, text=format_timestamp(timestamp_sec), link=link, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R")
                    
            else:
                timestamp_sec = int(item.get('time', 0))
                link = f"{base_url}&t={timestamp_sec}s"
                
                full_line = []
                for sk, sv in item.items():
                    if sk != 'time':
                        title = sk.replace('_', ' ').title()
                        full_line.append(f"• **{title}:** {str(sv)}")
                
                text_content = " ".join(full_line)
                
                # 90% width for the main text
                main_text_width = pdf.w - pdf.l_margin - pdf.r_margin - 30 
                
                # Use multi_cell for wrapping the main text content
                pdf.set_font(pdf.font_name, "", 11)
                pdf.set_text_color(*COLORS["body_text"])
                pdf.multi_cell(main_text_width, line_height, text_content, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

                # Place the timestamp link right below the wrapped text for reliable placement
                pdf.set_text_color(*COLORS["link_text"])
                pdf.cell(0, line_height, text=format_timestamp(timestamp_sec), link=link, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R")
                
            pdf.ln(2) 

    pdf.output(output)
    if isinstance(output, BytesIO):
        output.seek(0)
