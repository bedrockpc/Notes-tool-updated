# utils.py (Updated for Format Toggle)
# -*- coding: utf-8 -*-
import os
import json
import re
from pathlib import Path
import google.generativeai as genai
from fpdf import FPDF
from fpdf.enums import XPos, YPos
from io import BytesIO 
import streamlit as st # Added for inject_custom_css stub

# --- Configuration and Constants ---

EXPECTED_KEYS = [
    "main_subject", "topic_breakdown", "key_vocabulary",
    "formulas_and_principles", "teacher_insights",
    "exam_focus_points", "common_mistakes_explained"
]

# NOTE: The <hl> tags are assumed to be in the JSON output for this older version
SYSTEM_PROMPT = """
[System prompt content remains the same, including <hl> tag instructions]
"""

# --- Color Palette (Used for PDF generation) ---
COLORS = {
    "title_bg": (40, 54, 85), "title_text": (255, 255, 255),
    "heading_text": (40, 54, 85), "link_text": (0, 0, 255), 
    "body_text": (30, 30, 30), "line": (220, 220, 220),
    "highlight_bg": (255, 255, 0)
}

# --- Helper Functions ---

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

def summarize_with_gemini(api_key: str, transcript_text: str) -> dict | None:
    # This function body remains the same from your original code
    # (Omitted for brevity)
    print("    > Sending transcript to Gemini API...")
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash') 
        
        response = model.generate_content(f"{SYSTEM_PROMPT}\n\nTranscript:\n---\n{transcript_text}")
        
        cleaned_response = clean_gemini_response(response.text)

        if cleaned_response.endswith(','):
            cleaned_response = cleaned_response.rstrip(',')
        if not cleaned_response.endswith('}'):
            last_bracket = cleaned_response.rfind('}')
            if last_bracket != -1:
                cleaned_response = cleaned_response[:last_bracket + 1]

        return json.loads(cleaned_response)
        
    except json.JSONDecodeError:
        print("    > JSON DECODE ERROR: Failed to parse API response.")
        return None
    except Exception as e:
        print(f"    > An unexpected error occurred with the API call: {e}")
        return None

def format_timestamp(seconds: int) -> str:
    minutes = seconds // 60
    seconds = seconds % 60
    return f"[{minutes:02}:{seconds:02}]"

def ensure_valid_youtube_url(video_id: str) -> str:
    """Returns a properly formatted YouTube base URL for hyperlinking."""
    return f"https://www.youtube.com/watch?v={video_id}"

# NEW: Inject CSS stub (for compatibility)
def inject_custom_css():
    pass

# --- PDF Class ---
class PDF(FPDF):
    # CRITICAL: Accepts is_easy_read and sets line height
    def __init__(self, font_path, is_easy_read, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.font_name = "NotoSans"
        self.is_easy_read = is_easy_read
        self.base_line_height = 10 if is_easy_read else 7 # Adjusted for better spacing
        
        # NOTE: Font loading assumes a specific path structure provided in the original code
        self.add_font(self.font_name, "", str(font_path / "NotoSans-Regular.ttf"))
        self.add_font(self.font_name, "B", str(font_path / "NotoSans-Bold.ttf"))

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

    # Provided highlighting function (used only when is_easy_read is True)
    def write_highlighted_text(self, text, style=''):
        # Use dynamic height
        line_height = self.base_line_height 
        
        self.set_font(self.font_name, style, 11)
        self.set_text_color(*COLORS["body_text"])
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
# CRITICAL: Added format_choice parameter
def save_to_pdf(data: dict, video_id: str, font_path: Path, output, format_choice: str = "Default (Compact)"):
    print(f"    > Saving elegantly hyperlinked PDF...")
    
    is_easy_read = format_choice.startswith("Easier Read")
    base_url = ensure_valid_youtube_url(video_id) 
    
    # Initialize PDF object, passing the mode flag
    pdf = PDF(font_path=font_path, is_easy_read=is_easy_read)
    pdf.add_page()
    pdf.create_title(data.get("main_subject", "Video Summary"))
    
    # Use the dynamic line height set in the PDF class
    line_height = pdf.base_line_height

    for key, values in data.items():
        if key == "main_subject" or not values:
            continue
        pdf.create_section_heading(key.replace('_', ' ').title())
        for item in values:
            is_nested = any(isinstance(v, list) for v in item.values())
            
            if is_nested:
                pdf.set_font(pdf.font_name, "B", 11)
                pdf.multi_cell(0, line_height, text=f"  {item.get('topic', '')}")
                for detail_item in item.get('details', []):
                    timestamp_sec = int(detail_item.get('time', 0))
                    link = f"{base_url}&t={timestamp_sec}s"
                    display_text = f"    • {detail_item.get('detail', '')}"
                    
                    if is_easy_read:
                        pdf.write_highlighted_text(display_text) # Use <hl> logic
                    else:
                        pdf.set_font(pdf.font_name, "", 11)
                        pdf.set_text_color(*COLORS["body_text"])
                        pdf.write(line_height, display_text) # Use plain write
                        pdf.ln()

                    pdf.set_text_color(*COLORS["link_text"])
                    pdf.cell(0, line_height, text=format_timestamp(timestamp_sec), link=link, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R")
            
            else:
                timestamp_sec = int(item.get('time', 0))
                link = f"{base_url}&t={timestamp_sec}s"
                for sk, sv in item.items():
                    if sk != 'time':
                        pdf.set_text_color(*COLORS["body_text"])
                        pdf.set_font(pdf.font_name, "B", 11)
                        pdf.write(line_height, f"• {sk.replace('_', ' ').title()}: ")
                        pdf.set_font(pdf.font_name, "", 11)
                        
                        if is_easy_read:
                            pdf.write_highlighted_text(str(sv)) # Use <hl> logic
                        else:
                            pdf.set_text_color(*COLORS["body_text"])
                            pdf.write(line_height, str(sv))
                            pdf.ln()

                pdf.set_text_color(*COLORS["link_text"])
                pdf.cell(0, line_height, text=format_timestamp(timestamp_sec), link=link, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R")
            
            pdf.ln(4)
        pdf.ln(5)

    pdf.output(output)
    if isinstance(output, BytesIO):
        output.seek(0)
