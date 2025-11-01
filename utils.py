# utils.py
# -*- coding: utf-8 -*-
import streamlit as st # NEW: Required for Streamlit utilities
import os
import json
import re
from pathlib import Path
import google.generativeai as genai
from fpdf import FPDF
from fpdf.enums import XPos, YPos
import pandas as pd
from io import BytesIO 
import time # NEW: Required for simulating delay in extract_text_from_pdf

# --- Configuration and Constants ---

EXPECTED_KEYS = [
    "main_subject", "topic_breakdown", "key_vocabulary",
    "formulas_and_principles", "teacher_insights",
    "exam_focus_points", "common_mistakes_explained"
]

SYSTEM_PROMPT = """
You are a master academic analyst creating a concise, timestamped study guide from a video transcript file. The transcript text contains timestamps in formats like (MM:SS) or [HH:MM:SS].

**Primary Goal:** Create a detailed summary. For any key point you extract, you MUST find its closest preceding timestamp in the text and include it in your response as total seconds.

**Instructions:**
1.  Analyze the entire transcript.
2.  For every piece of information you extract, find the nearest timestamp that comes *before* it in the text. Convert that timestamp into **total seconds** (e.g., (01:30) becomes 90).
3.  **Highlighting:** Inside any 'detail', 'definition', 'explanation', or 'insight' string, find the single most critical phrase (3-5 words) and wrap it in `<hl>` and `</hl>` tags. For example: 'The derivative is a <hl>rate of change</hl>.' Do this only once per item where appropriate.
4.  Be concise. Each point must be a short, clear sentence.
5.  Extract the following information:
    -   main_subject: A short phrase identifying the main subject.
    -   topic_breakdown: For each topic, list details as objects with "detail" and "time" keys.
    -   key_vocabulary: A list of objects with "term", "definition", and "time" keys.
    -   formulas_and_principles: A list of objects with "formula_or_principle", "explanation", and "time" keys.
    -   teacher_insights: A list of objects with "insight", and "time" keys.
    -   exam_focus_points: A list of objects with "point", and "time" keys.
    -   common_mistakes_explained: A list of objects with "mistake", "explanation", and "time" keys.
6.  Return your output **only** as a single, valid JSON object.

The JSON structure must be exactly as follows:
{
  "main_subject": "Subject Name",
  "topic_breakdown": [{"topic": "Topic 1", "details": [{"detail": "This is a <hl>short detail</hl>.", "time": 120}]}],
  "key_vocabulary": [{"term": "Term 1", "definition": "A <hl>short definition</hl>.", "time": 150}],
  "formulas_and_principles": [{"formula_or_principle": "Principle 1", "explanation": "A <hl>brief explanation</hl>.", "time": 180}],
  "teacher_insights": [{"insight": "<hl>Short insight</hl> 1.", "time": 210}],
  "exam_focus_points": [{"point": "Brief <hl>focus point</hl> 1.", "time": 240}],
  "common_mistakes_explained": [{"mistake": "Mistake 1", "explanation": "A <hl>short explanation</hl>.", "time": 270}]
}
"""

# --- Color Palette (Used for PDF generation) ---
COLORS = {
    "title_bg": (40, 54, 85), "title_text": (255, 255, 255),
    "heading_text": (40, 54, 85), "link_text": (0, 0, 255), 
    "body_text": (30, 30, 30), "line": (220, 220, 220),
    "highlight_bg": (255, 255, 0)
}

# --------------------------------------------------------------------------
# --- NEW/UPDATED STREAMLIT UTILITY FUNCTIONS ---
# --------------------------------------------------------------------------

# NEW: Custom CSS Injection Function
def inject_custom_css():
    """
    Injects custom CSS for application-wide styling, including font size and line spacing.
    """
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

# NEW: Caching Function (Solves the Timestamp/Re-run Issue)
@st.cache_data
def extract_text_from_pdf(pdf_file):
    """
    Reads PDF and extracts text. Cached to prevent re-running on widget changes.
    Returns placeholder text for demonstration purposes.
    """
    if pdf_file is not None:
        # Simulate text extraction time
        time.sleep(2) 

        # --- PLACEHOLDER LOGIC (Replace this with your actual PDF extraction code) ---
        st.session_state['file_name'] = pdf_file.name
        placeholder_text = f"""
        # Document: {pdf_file.name}
        ## Introduction / Executive Summary
        This section provides an overview of the analysis scope and the primary objectives. The research was initiated to determine the feasibility of the new feature set. The initial findings suggest a strong correlation between user engagement and the simplicity of the interface.

        ## Methodology / Approach
        The method utilized a mixed-methods approach, combining quantitative A/B testing with qualitative user interviews. The testing ran over a 12-week period, gathering 50,000 data points.

        ## Results / Key Findings
        The key findings are significant. The test group showed a 45% increase in feature adoption compared to the control group (p < 0.01).

        ## Discussion / Analysis
        The increase in adoption strongly validates the initial hypothesis regarding interface simplicity. The analysis suggests that minor tweaks to the feature placement could resolve the confusion.

        ## Conclusion / Summary
        In summary, the new feature set is highly effective and recommended for deployment.
        """
        # --- END PLACEHOLDER LOGIC ---
        
        return placeholder_text
    return None

# --------------------------------------------------------------------------
# --- ORIGINAL VIDEO ANALYSIS FUNCTIONS (KEPT & MODIFIED) ---
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
    # Extracts the JSON object, handles markdown fences (```json...```)
    match = re.search(r'```json\s*(\{.*?\})\s*```|(\{.*?\})', response_text, re.DOTALL)
    if match: return match.group(1) if match.group(1) else match.group(2)
    return response_text.strip()

def summarize_with_gemini(api_key: str, transcript_text: str) -> dict | None:
    print("    > Sending transcript to Gemini API...")
    try:
        genai.configure(api_key=api_key)
        # Using the highly stable model
        model = genai.GenerativeModel('gemini-2.5-flash') 
        
        # 1. Send Request
        response = model.generate_content(f"{SYSTEM_PROMPT}\n\nTranscript:\n---\n{transcript_text}")
        
        # 2. Extract JSON (Handles Markdown Fence)
        cleaned_response = clean_gemini_response(response.text)

        # 3. Aggressive JSON Post-Processing (FIX for Incomplete Output)
        if cleaned_response.endswith(','):
            cleaned_response = cleaned_response.rstrip(',')
        if not cleaned_response.endswith('}'):
            last_bracket = cleaned_response.rfind('}')
            if last_bracket != -1:
                cleaned_response = cleaned_response[:last_bracket + 1]

        # 4. Attempt to Load JSON
        return json.loads(cleaned_response)
        
    except json.JSONDecodeError:
        print("    > JSON DECODE ERROR: Failed to parse API response.")
        print(f"    > Truncated Response (first 500 chars): {cleaned_response[:500]}...")
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

# --- PDF Class ---
class PDF(FPDF):
    def __init__(self, font_path, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.font_name = "NotoSans"
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
def save_to_pdf(data: dict, video_id: str, font_path: Path, output):
    print(f"    > Saving elegantly hyperlinked PDF...")
    base_url = ensure_valid_youtube_url(video_id) 
    
    pdf = PDF(font_path=font_path)
    pdf.add_page()
    pdf.create_title(data.get("main_subject", "Video Summary"))

    for key, values in data.items():
        if key == "main_subject" or not values:
            continue
        pdf.create_section_heading(key.replace('_', ' ').title())
        for item in values:
            is_nested = any(isinstance(v, list) for v in item.values())
            if is_nested:
                pdf.set_font(pdf.font_name, "B", 11)
                pdf.multi_cell(0, 7, text=f"  {item.get('topic', '')}")
                for detail_item in item.get('details', []):
                    timestamp_sec = int(detail_item.get('time', 0))
                    link = f"{base_url}&t={timestamp_sec}s"
                    display_text = f"    • {detail_item.get('detail', '')}"
                    pdf.write_highlighted_text(display_text)
                    pdf.set_text_color(*COLORS["link_text"])
                    # FIX: Corrected typo for standard MM:SS display
                    pdf.cell(0, 7, text=format_timestamp(timestamp_sec), link=link, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R")
            else:
                timestamp_sec = int(item.get('time', 0))
                link = f"{base_url}&t={timestamp_sec}s"
                for sk, sv in item.items():
                    if sk != 'time':
                        pdf.set_text_color(*COLORS["body_text"])
                        pdf.set_font(pdf.font_name, "B", 11)
                        pdf.write(7, f"• {sk.replace('_', ' ').title()}: ")
                        pdf.set_font(pdf.font_name, "", 11)
                        pdf.write_highlighted_text(str(sv))
                pdf.set_text_color(*COLORS["link_text"])
                # FIX: Corrected typo for standard MM:SS display
                pdf.cell(0, 7, text=format_timestamp(timestamp_sec), link=link, new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="R")
            pdf.ln(4)
        pdf.ln(5)

    pdf.output(output)
    if isinstance(output, BytesIO):
        output.seek(0)
