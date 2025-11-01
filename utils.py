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

# FIX: Corrected the timestamp conversion logic to handle hours and ensure seconds < 60.
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

    def write_highlighted_text(self, text, style=''):
        self.set_font(self.font_name, style, 11)
        self.set_text_color(*COLORS["body_text"])
        
        line_height = 6 
        
        parts = re.split(r'(<hl>.*?</hl>)', text)
        for part in parts:
            if part.startswith('<hl>'):
                highlight_text = part[4:-5]
                self.set_fill_color(*COLORS["highlight_bg"])
                self.set_font(self.font_name, 'B', 11)
                self.cell(self.get_string_width(highlight_text), line_height, highlight_text, fill=True)
                self.set_font(self.font_name, style, 11)
            else:
                self.set_fill_color(255, 255, 255)
                self.write(line_height, part)
        self.ln()

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

            if is_nested:
                pdf.set_font(pdf.font_name, "B", 11)
                pdf.multi_cell(0, line_height, text=f"  {item.get('topic', '')}")
                for detail_item in item.get('details', []):
                    timestamp_sec = int(detail_item.get('time', 0))
                    link = f"{base_url}&t={timestamp_sec}s"
                    display_text = f"    • {detail_item.get('detail', '')}"
                    
                    pdf.write(line_height, "") 
                    pdf.write_highlighted_text(display_text)
                    pdf.set_text_color(*COLORS["link_text"])
                    pdf.cell(0, line_height, text=format_timestamp(timestamp_sec), link=link, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R")
            else:
                timestamp_sec = int(item.get('time', 0))
                link = f"{base_url}&t={timestamp_sec}s"
                
                pdf.write(line_height, "") 
                
                main_text_parts = []
                for sk, sv in item.items():
                    if sk != 'time':
                        title = sk.replace('_', ' ').title()
                        main_text_parts.append((f"• **{title}:** ", f"{str(sv)}"))
                        
                for title_part, value_part in main_text_parts:
                    pdf.set_text_color(*COLORS["body_text"])
                    pdf.set_font(pdf.font_name, "B", 11)
                    pdf.write(line_height, title_part.replace('**', ''))
                    
                    pdf.set_font(pdf.font_name, "", 11)
                    pdf.write_highlighted_text(value_part)

                pdf.set_text_color(*COLORS["link_text"])
                pdf.cell(0, line_height, text=format_timestamp(timestamp_sec), link=link, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R")
            pdf.ln(2) 

    pdf.output(output)
    if isinstance(output, BytesIO):
        output.seek(0)