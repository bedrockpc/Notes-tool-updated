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
from typing import Optional, Tuple, Dict, Any, List 

# --- Configuration and Constants ---

EXPECTED_KEYS = [
    "main_subject", "topic_breakdown", "key_vocabulary",
    "formulas_and_principles", "teacher_insights",
    "exam_focus_points", "common_mistakes_explained", 
    "key_points", "short_tricks", "must_remembers" 
]

# 🎯 FINAL FIX: Explicit Blueprint SYSTEM_PROMPT to force content generation (solves empty lists)
SYSTEM_PROMPT = """
You are a master academic analyst creating a concise, structured study guide.
Input: a list of transcript segments (each with 'time' and 'text').
Task: Extract key academic content for each segment.

**CRITICAL GUIDELINES:**
1. Use the provided 'time' value (in seconds) from the input segment for each extracted point.
2. Do NOT infer or calculate timestamps. Use the input 'time' directly.
3. Return the output ONLY as a single, valid JSON object following the structure below, filling all requested lists with content found in the transcript.

**REQUIRED JSON OUTPUT STRUCTURE:**
{
  "main_subject": "A short phrase identifying the main subject.",
  "topic_breakdown": [{"topic": "Topic Title", "details": [{"detail": "A <hl>short detail</hl> from the transcript.", "time": 120}]}],
  "key_vocabulary": [{"term": "Term 1", "definition": "A <hl>short definition</hl>.", "time": 150}],
  "formulas_and_principles": [{"formula_or_principle": "Principle Name", "explanation": "A <hl>brief explanation</hl>.", "time": 180}],
  "teacher_insights": [{"insight": "<hl>Short insight</hl> 1.", "time": 210}],
  "exam_focus_points": [{"point": "Brief <hl>focus point</hl> 1.", "time": 240}],
  "common_mistakes_explained": [{"mistake": "Mistake", "explanation": "A <hl>short explanation</hl>.", "time": 270}],
  "key_points": [{"text": "A general key point.", "time": 300}],
  "short_tricks": [{"text": "A useful shortcut.", "time": 330}],
  "must_remembers": [{"text": "Critical takeaway.", "time": 360}]
}

[Instructions Section]
"""

# --- Color Palette (Used for PDF generation) ---
COLORS = {
    "title_bg": (40, 54, 85), "title_text": (255, 255, 255),
    "heading_text": (40, 54, 85), "link_text": (0, 0, 255), 
    "body_text": (30, 30, 30), "line": (220, 220, 220),
    "highlight_bg": (255, 255, 0)
}

# --- CORE UTILITY FUNCTIONS (Ensuring all are defined for import) ---

# FIX: Function definition added to solve ImportError
def inject_custom_css():
    """Injects custom CSS for application-wide styling."""
    st.markdown(
        """
        <style>
        p, label, .stMarkdown, .stTextArea, .stSelectbox {
            font-size: 1.05rem !important; 
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
    
def get_video_id(url: str) -> Optional[str]:
    """Extracts the YouTube video ID from a URL."""
    patterns = [
        r"(?<=v=)[^&#?]+", r"(?<=be/)[^&#?]+", r"(?<=live/)[^&#?]+",
        r"(?<=embed/)[^&#?]+", r"(?<=shorts/)[^&#?]+"
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match: return match.group(0)
    return None

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
    """Tolerantly extracts a single, valid JSON block from the response text."""
    potential_json_blocks = re.findall(r'\{.*?\}', response_text.strip(), re.DOTALL)
    
    for json_string in potential_json_blocks:
        json_string = re.sub(r'```json\s*|```|\s*[*•]', '', json_string).strip()
        
        if not json_string.startswith('{'):
            continue
        if not json_string.endswith('}'):
            json_string += '}'
        
        try:
            json.loads(json_string)
            return json_string
        except json.JSONDecodeError:
            continue
            
    return None

def get_content_text(item):
    """Retrieves content text using multiple fallback keys, ensuring string output."""
    if isinstance(item, dict):
        text = item.get('detail') or item.get('explanation') or item.get('point') or item.get('text') or item.get('definition') or item.get('formula_or_principle') or item.get('insight') or item.get('mistake') or item.get('trick') or item.get('fact') or item.get('content')
        return str(text or '')
    return str(item or '')

def format_timestamp(seconds: int) -> str:
    """Converts total seconds to [MM:SS] or [HH:MM:SS] format."""
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    
    if hours > 0:
        return f"[{hours:02}:{minutes:02}:{seconds:02}]"
    else:
        return f"[{minutes:02}:{seconds:02}]"

def ensure_valid_youtube_url(video_id: str) -> str:
    """Returns a properly formatted YouTube base URL for hyperlinking."""
    return f"https://www.youtube.com/watch?v={video_id}"


@st.cache_data(ttl=0) 
def run_analysis_and_summarize(api_key: str, transcript_segments: List[Dict], max_words: int, sections_list_keys: list, user_prompt: str, model_name: str, is_easy_read: bool) -> Tuple[Optional[Dict[str, Any]], Optional[str], str]:
    
    sections_to_process = ", ".join(sections_list_keys)
    
    # Update instructions based on display mode
    if is_easy_read:
        prompt_instructions = SYSTEM_PROMPT.replace('[Instructions Section]', f"""
        4. **Highlighting:** Inside any string value, find the single most critical phrase (3-5 words) and wrap it in `<hl>` and `</hl>` tags.
        5. The total combined length of all extracted details must not exceed {max_words} words.
        6. Extract information ONLY for the following categories: **{sections_to_process}**. Omit all others.
        """)
    else:
        prompt_instructions = SYSTEM_PROMPT.replace('[Instructions Section]', f"""
        4. DO NOT use any special markdown or tags like <hl> in the final JSON content.
        5. The total combined length of all extracted details must not exceed {max_words} words.
        6. Extract information ONLY for the following categories: **{sections_to_process}**. Omit all others.
        """)

    # Convert segmented input to JSON string
    transcript_json_string = json.dumps(transcript_segments, indent=2)

    full_prompt = f"""
    {prompt_instructions}

    **CRITICAL INSTRUCTION: PROVIDE ONLY VALID, PURE JSON. DO NOT INCLUDE ANY MARKUP (**), BULLETS (•), OR SURROUNDING TEXT OUTSIDE THE JSON {{{{...}}}} BLOCK. THE JSON VALUES MUST CONTAIN ONLY CLEAN TEXT. THE KEYS MUST BE IN SNAKE_CASE.**

    **USER CONSTRAINTS (from Streamlit app):**
    - User Refinement Prompt: {user_prompt}

    Transcript to Analyze (JSON Format):
    ---
    {transcript_json_string}
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
            time.sleep(2)
            return None, "Empty response from model.", full_prompt
        
        cleaned_response = extract_clean_json(response_text)

        if not cleaned_response:
            return None, "JSON structure could not be extracted from API response.", full_prompt

        json_data = json.loads(cleaned_response)
        
        # ✅ FIX: Normalize keys from camelCase/PascalCase to snake_case (Crucial for list matching)
        json_data = {re.sub(r'([A-Z])', lambda m: '_' + m.group(1).lower(), k).lstrip('_'): v for k, v in json_data.items()}
        
        return json_data, None, full_prompt
        
    except json.JSONDecodeError as e:
        return None, f"JSON PARSE ERROR: {e}", full_prompt
    except Exception as e:
        return None, f"Gemini API Error: {e}", full_prompt
        
# --- PDF Class ---
class PDF(FPDF):
    def __init__(self, font_path, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.font_name = "NotoSans"
        try:
            # Assuming NotoSans fonts are available for consistency
            self.add_font(self.font_name, "", str(font_path / "NotoSans-Regular.ttf"))
            self.add_font(self.font_name, "B", str(font_path / "NotoSans-Bold.ttf"))
        except:
            self.font_name = "Arial"

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
        parts = re.split(r'(<hl>.*?</hl>)', text)
        for part in parts:
            if part.startswith('<hl>'):
                highlight_text = part[4:-5]
                self.set_fill_color(*COLORS["highlight_bg"])
                self.set_font(self.font_name, 'B', 11)
                self.cell(self.get_string_width(highlight_text), 7, highlight_text, fill=True)
                self.set_font(self.font_name, style, 11)
            else:
                self.set_fill_color(255, 255, 255)
                self.write(7, part)
        self.ln()

# --- Save to PDF Function (Primary Output) ---
def save_to_pdf(data: dict, video_id: Optional[str], font_path: Path, output, format_choice: str = "Default (Compact)"):
    
    print("PDF INPUT DEBUG:", json.dumps(data, indent=2)[:1000] + "...")
    
    base_url = ensure_valid_youtube_url(video_id) if video_id else "#"
    line_height = 7 
    
    pdf = PDF(font_path=font_path)
    pdf.add_page()
    
    # --- Title ---
    main_title = data.get("main_subject", "Video Notes")
    pdf.create_title(main_title)
    
    
    # --- Go through each section ---
    for section_key, section_content in data.items():
        if section_key == "main_subject" or not isinstance(section_content, list) or not section_content:
            continue
        
        # 🧠 DEBUG 5: Print section key and length
        friendly_name = section_key.replace("_", " ").title()
        print(f"  > Processing '{friendly_name}' ({section_key}): {len(section_content)}")
        
        # Convert section key to readable heading
        heading = section_key.replace("_", " ").title()
        pdf.create_section_heading(heading)
        
        for item in section_content:
            # We use get_content_text to find the main text content for non-nested items
            content_text = get_content_text(item)
            if not content_text.strip():
                continue
            
            # --- Handle Nested Topic Breakdown ---
            if section_key == 'topic_breakdown':
                # Write the Topic Name (Bold)
                pdf.set_font(pdf.font_name, "B", 11)
                pdf.multi_cell(0, line_height, text=f"  {item.get('topic', '')}")
                
                # Process nested details
                for detail in item.get('details', []):
                    detail_text = get_content_text(detail)
                    timestamp = detail.get("time") if isinstance(detail, dict) else None
                    
                    pdf.set_x(pdf.get_x() + 5) # Indent for detail
                    pdf.set_font(pdf.font_name, '', 11)
                    
                    # Write text content with highlight support
                    pdf.write_highlighted_text(detail_text) # write_highlighted_text includes ln()

                    # Add timestamp/link logic right after the text is written
                    if timestamp and video_id:
                        link_url = f"{base_url}&t={timestamp}s"
                        pdf.set_text_color(*COLORS["link_text"])
                        pdf.set_font(pdf.font_name, 'B', 11)
                        # Position the cell for the timestamp link
                        pdf.set_xy(pdf.w - pdf.r_margin - 30, pdf.get_y() - line_height) 
                        pdf.cell(30, line_height, text=format_timestamp(int(timestamp)), link=link_url, align="R")
                        pdf.set_text_color(*COLORS["body_text"])
                    
                    pdf.ln(2) # Extra space

                pdf.set_x(pdf.l_margin) # Reset indent after topic breakdown
                continue
                
            # --- Handle Flat Sections (Vocabulary, Key Points, etc.) ---
            
            # 1. Write the content itself
            pdf.set_font(pdf.font_name, '', 11)
            pdf.write_highlighted_text(content_text) # write_highlighted_text includes ln()
            
            # 2. Add the Timestamp Link
            timestamp = item.get("time") if isinstance(item, dict) else None
            if timestamp and video_id:
                link_url = f"{base_url}&t={timestamp}s"
                pdf.set_text_color(*COLORS["link_text"])
                pdf.set_font(pdf.font_name, 'B', 11)
                # Position the cell for the timestamp link
                pdf.set_xy(pdf.w - pdf.r_margin - 30, pdf.get_y() - line_height)
                pdf.cell(30, line_height, text=format_timestamp(int(timestamp)), link=link_url, align="R")
                pdf.set_text_color(*COLORS["body_text"])
                
            pdf.ln(2) # Final line break after item

    pdf.output(output)
    if isinstance(output, BytesIO):
        output.seek(0)