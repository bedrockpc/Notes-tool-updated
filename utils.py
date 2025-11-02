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
from typing import Optional, Tuple, Dict, Any

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
3.  Be concise. Each point must be a short, clear sentence.
4.  Extract the information for the following categories. **Only include a category in the final JSON if the user specifically requested it.**
5.  DO NOT use any special markdown or tags like <hl> in the final JSON content.

The JSON structure must include these keys with objects/arrays:
{
  "main_subject": "A short phrase identifying the main subject.",
  "topic_breakdown": [{"topic": "Topic 1", "details": [{"detail": "This is a short detail.", "time": 120}]}],
  "key_vocabulary": [{"term": "Term 1", "definition": "A short definition.", "time": 150}],
  "formulas_and_principles": [{"formula_or_principle": "Principle 1", "explanation": "A brief explanation.", "time": 180}],
  "teacher_insights": [{"insight": "Short insight 1.", "time": 210}],
  "exam_focus_points": [{"point": "Brief focus point 1.", "time": 240}],
  "common_mistakes_explained": [{"mistake": "Mistake 1", "explanation": "A short explanation.", "time": 270}],
  "key_points": [{"point": "A major takeaway point.", "time": 300}],
  "short_tricks": [{"trick": "A quick method to solve a problem.", "time": 330}],
  "must_remembers": [{"fact": "A fact that must be memorized.", "time": 360}]
}
"""

# 🎨 VIBRANT AND READABLE PALETTE 🎨
COLORS = {
    "title_bg": (65, 105, 225),   # Royal Blue
    "title_text": (255, 255, 255),
    "heading_text": (30, 30, 30),   # Dark Charcoal
    "link_text": (0, 150, 136),   # Bright Teal
    "body_text": (50, 50, 50),     # Dark Gray
    "line": (178, 207, 255),      # Light Blue
    "item_title_text": (205, 92, 92), # Indian Red (For labels like "Mistake:", "Definition:")
    "item_bullet_color": (150, 150, 150), # Medium Gray (For bullet points)
}

# --------------------------------------------------------------------------
# --- STREAMLIT UTILITY FUNCTIONS ---
# --------------------------------------------------------------------------

def extract_gemini_text(response) -> Optional[str]:
    """Safely extracts text from Gemini response object."""
    response_text = getattr(response, "text", None)
    if not response_text and hasattr(response, "candidates") and response.candidates:
        try:
            return response.candidates[0].content.parts[0].text
        except (AttributeError, IndexError):
            pass
    return response_text

def extract_clean_json(response_text: str) -> Optional[str]:
    """Centralized and safer JSON extraction."""
    match = re.search(r'\{.*\}', response_text.strip(), re.DOTALL)
    
    if not match:
        match = re.search(r'```json\s*(\{.*?\})\s*```', response_text, re.DOTALL)
    
    if match:
        cleaned_response = match.group(0).strip()
        
        # Safe cleanup: only remove * and •
        cleaned_response = re.sub(r'[*•]', '', cleaned_response) 
        
        # Aggressive final cleanup
        cleaned_response = cleaned_response.rstrip(',').rstrip('.').strip()

        if not cleaned_response.endswith('}'):
            cleaned_response += '}'
        
        return cleaned_response
    return None


@st.cache_data(ttl=0) # Cache control for API calls
def run_analysis_and_summarize(api_key: str, transcript_text: str, max_words: int, sections_list: list, user_prompt: str, model_name: str) -> Tuple[Optional[Dict[str, Any]], Optional[str], str]:
    
    sections_to_process = ", ".join(sections_list)
    
    SYSTEM_PROMPT_CLEAN = SYSTEM_PROMPT.replace("<hl>", "").replace("</hl>", "")
    
    full_prompt = f"""
    {SYSTEM_PROMPT_CLEAN}

    **CRITICAL INSTRUCTION: PROVIDE ONLY VALID, PURE JSON. DO NOT INCLUDE ANY MARKUP (**), BULLETS (•), OR SURROUNDING TEXT OUTSIDE THE JSON {{{{...}}}} BLOCK. THE JSON VALUES MUST CONTAIN ONLY CLEAN TEXT.**

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
        model = genai.GenerativeModel(model_name) 
        
        response = model.generate_content(full_prompt)
        response_text = extract_gemini_text(response)

        if not response_text:
            return None, "API returned empty response.", full_prompt
        
        cleaned_response = extract_clean_json(response_text)

        if not cleaned_response:
             return None, "JSON structure could not be extracted from API response.", full_prompt

        json_data = json.loads(cleaned_response)
        
        return json_data, None, full_prompt
        
    except json.JSONDecodeError as e:
        return None, f"JSON PARSE ERROR: {e}", full_prompt
    except Exception as e:
        return None, f"Gemini API Error: {e}", full_prompt
        
def inject_custom_css():
    """Injects custom CSS for application-wide styling."""
    st.markdown(
        """
        <style>
        p, label, .stMarkdown, .stTextArea, .stSelectbox {
            font-size: 1.05rem !important; 
        }
        .pdf-output-text {
            border: 1px solid #ccc;
            padding: 15px;
            margin-top: 10px;
            background-color: #f9f9f9;
            --custom-font-size: 1.05rem; 
        }
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
# --- CORE HELPER FUNCTIONS (PDF/FORMATTING) ---
# --------------------------------------------------------------------------

def get_video_id(url: str) -> str | None:
    """Extracts the YouTube video ID from a URL."""
    patterns = [
        r"(?<=v=)[^&#?]+", r"(?<=be/)[^&#?]+", r"(?<=live/)[^&#?]+",
        r"(?<=embed/)[^&#?]+", r"(?<=shorts/)[^&#?]+"
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match: return match.group(0)
    return None

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

def ensure_valid_youtube_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"

# --- PDF Class ---
class PDF(FPDF):
    def __init__(self, base_path, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.font_name = "NotoSans"
        
        # Handle missing font files gracefully
        try:
            self.add_font(self.font_name, "", str(base_path / "NotoSans-Regular.ttf"))
            self.add_font(self.font_name, "B", str(base_path / "NotoSans-Bold.ttf"))
        except RuntimeError:
            self.font_name = "Arial" # Fallback to a common built-in font
            print(f"Warning: NotoSans font files not found. Falling back to {self.font_name}.")


    def create_title(self, title):
        self.set_font(self.font_name, "B", 24)
        self.set_fill_color(*COLORS["title_bg"])
        self.set_text_color(*COLORS["title_text"])
        
        title_width = self.w - 2 * self.l_margin
        
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
            link_cell_width = 30 
            
            if is_nested:
                # 1. Write the Topic Name (Bold)
                pdf.set_font(pdf.font_name, "B", 11)
                pdf.multi_cell(0, line_height, text=f"  {item.get('topic', '')}", new_x=XPos.LMARGIN)
                
                # 2. Write all Details for that topic
                for detail_item in item.get('details', []):
                    timestamp_sec = int(detail_item.get('time', 0))
                    link = f"{base_url}&t={timestamp_sec}s"
                    
                    # FIX 7: Sanitize text before PDF generation
                    detail_text = re.sub(r'\s+', ' ', detail_item.get('detail', '')).strip()
                    
                    text_content = f"    - {detail_text}"
                    start_y = pdf.get_y()
                    
                    pdf.set_text_color(*COLORS["body_text"])
                    pdf.set_font(pdf.font_name, "", 11)
                    pdf.multi_cell(content_width, line_height, text_content, border=0, new_x=XPos.RMARGIN, new_y=YPos.TOP)
                    
                    final_y = pdf.get_y()
                    
                    # Position the cursor for the link placement
                    pdf.set_xy(pdf.w - pdf.r_margin - link_cell_width, start_y)
                    
                    # Place the timestamp link
                    pdf.set_text_color(*COLORS["link_text"])
                    pdf.cell(link_cell_width, line_height, text=format_timestamp(timestamp_sec), link=link, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R")
                    
                    # Reset cursor position
                    pdf.set_xy(pdf.l_margin, final_y)
            
            else:
                timestamp_sec = int(item.get('time', 0))
                link = f"{base_url}&t={timestamp_sec}s"
                
                start_y = pdf.get_y()
                
                for sk, sv in item.items():
                    if sk != 'time':
                        title = sk.replace('_', ' ').title()
                        
                        # 1. Write Title (Bold)
                        title_str = f"• {title}: "
                        pdf.set_text_color(*COLORS["item_title_text"]) 
                        pdf.set_font(pdf.font_name, "B", 11)
                        pdf.cell(pdf.get_string_width(title_str), line_height, title_str, new_x=XPos.CURRENT, new_y=YPos.TOP)
                        
                        # 2. Write Value (Normal, Wrapping)
                        # FIX 7: Sanitize text before PDF generation
                        value_str = re.sub(r'\s+', ' ', str(sv)).strip()
                        
                        value_start_x = pdf.get_x()
                        remaining_width = pdf.w - pdf.r_margin - value_start_x - 5
                        
                        pdf.set_text_color(*COLORS["body_text"])
                        pdf.set_font(pdf.font_name, "", 11)
                        
                        pdf.set_xy(value_start_x, pdf.get_y())
                        
                        # Use multi_cell for the value to ensure wrapping
                        pdf.multi_cell(remaining_width, line_height, value_str, border=0, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                
                final_y = pdf.y
                
                # Position the cursor for the link placement
                pdf.set_xy(pdf.l_margin + content_width + 5, start_y)
                
                # Place the timestamp link
                pdf.set_text_color(*COLORS["link_text"])
                pdf.cell(link_cell_width, line_height, text=format_timestamp(timestamp_sec), link=link, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R")
                
                # Reset cursor position
                pdf.set_xy(pdf.l_margin, final_y)
                
            pdf.ln(2) 

    pdf.output(output)
    if isinstance(output, BytesIO):
        output.seek(0)
