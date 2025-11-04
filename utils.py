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

SYSTEM_PROMPT = """
You are an intelligent note structurer. 
Input: a list of transcript segments (each with 'time' and 'text').
Task: extract key topics, subtopics, and summarized explanations.

**Guidelines:**
- Always include a key 'main_subject' summarizing the lecture topic in one short sentence.
- Use the provided 'time' value for each extracted point instead of inferring timestamps.
- Do NOT create any separate 'timestamp' sections or headings. Only include timestamps inside each point’s 'time' field (in seconds).
- Keep everything factual and structured for PDF generation.

[Instructions Section]
"""

COLORS = {
    "title_bg": (65, 105, 225),
    "title_text": (255, 255, 255),
    "heading_text": (30, 30, 30),
    "link_text": (0, 150, 136),
    "body_text": (50, 50, 50),
    "line": (178, 207, 255),
    "item_title_text": (205, 92, 92),
    "item_bullet_color": (150, 150, 150),
    "highlight_bg": (255, 255, 0)
}

# --------------------------------------------------------------------------
# --- CORE UTILITY FUNCTIONS ---
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
        text = item.get('detail') or item.get('explanation') or item.get('point') or item.get('text') or item.get('definition') or item.get('formula_or_principle') or item.get('insight') or item.get('mistake') or item.get('trick') or item.get('fact')
        return str(text or '')
    return str(item or '')


@st.cache_data(ttl=0) 
def run_analysis_and_summarize(api_key: str, transcript_segments: List[Dict], max_words: int, sections_list_keys: list, user_prompt: str, model_name: str, is_easy_read: bool) -> Tuple[Optional[Dict[str, Any]], Optional[str], str]:
    
    sections_to_process = ", ".join(sections_list_keys)
    
    if is_easy_read:
        prompt_instructions = SYSTEM_PROMPT.replace('[Instructions Section]', f"""
        4. **Highlighting:** Inside any 'detail', 'definition', 'explanation', or 'insight' string, find the single most critical phrase (3-5 words) and wrap it in `<hl>` and `</hl>` tags.
        5. Be concise. The total combined length of all extracted details must not exceed {max_words} words.
        6. Extract the information for the following categories...
        """)
    else:
        prompt_instructions = SYSTEM_PROMPT.replace('[Instructions Section]', f"""
        4. Be concise. The total combined length of all extracted details must not exceed {max_words} words.
        5. Extract the information for the following categories...
        6. DO NOT use any special markdown or tags like <hl> in the final JSON content.
        """)

    transcript_json_string = json.dumps(transcript_segments, indent=2)

    full_prompt = f"""
    {prompt_instructions}

    **CRITICAL INSTRUCTION: PROVIDE ONLY VALID, PURE JSON. DO NOT INCLUDE ANY MARKUP (**), BULLETS (•), OR SURROUNDING TEXT OUTSIDE THE JSON {{{{...}}}} BLOCK. THE JSON VALUES MUST CONTAIN ONLY CLEAN TEXT. THE KEYS MUST BE IN SNAKE_CASE.**

    **USER CONSTRAINTS (from Streamlit app):**
    - Max Detail Length: {max_words} words (Total).
    - **REQUIRED OUTPUT CATEGORIES (SNAKE_CASE):** **{sections_to_process}**
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
        
        # ✅ PERMANENT FIX: Normalize keys from camelCase/PascalCase to snake_case
        json_data = {re.sub(r'([A-Z])', lambda m: '_' + m.group(1).lower(), k).lstrip('_'): v for k, v in json_data.items()}
        
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

def clean_gemini_response(response_text: str) -> str:
    match = re.search(r'```json\s*(\{.*?\})\s*```|(\{.*?\})', response_text, re.DOTALL)
    if match: return match.group(1) if match.group(1) else match.group(2)
    return response_text.strip()

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
    def __init__(self, base_path, is_easy_read, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.font_name = "NotoSans"
        self.is_easy_read = is_easy_read
        self.base_line_height = 10 if is_easy_read else 7 
        
        try:
            self.add_font(self.font_name, "", str(base_path / "NotoSans-Regular.ttf"))
            self.add_font(self.font_name, "B", str(base_path / "NotoSans-Bold.ttf"))
        except RuntimeError:
            self.font_name = "Arial" 
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

    def write_highlighted_text(self, text, line_height):
        """
        Writes text, handling <hl> tags and advancing the cursor properly.
        """
        self.set_font(self.font_name, '', 11)
        self.set_text_color(*COLORS["body_text"])
        
        parts = re.split(r'(<hl>.*?</hl>)', text)
        
        for part in parts:
            if part.startswith('<hl>'):
                highlight_text = part[4:-5]
                self.set_fill_color(*COLORS["highlight_bg"])
                self.set_font(self.font_name, 'B', 11)
                
                self.cell(self.get_string_width(highlight_text), line_height, highlight_text, fill=True, new_x=XPos.RIGHT, new_y=YPos.TOP)
                self.set_font(self.font_name, '', 11)
            else:
                self.set_fill_color(255, 255, 255)
                self.write(line_height, part) 

# --- Save to PDF Function (Primary Output) ---
# ✅ FIX: Replacing the entire save_to_pdf function with the corrected, simplified logic
def save_to_pdf(data: dict, video_id: Optional[str], font_path: Path, output, format_choice: str = "Default (Compact)"):
    
    print("PDF INPUT DEBUG:", json.dumps(data, indent=2)[:1000] + "...")
    
    is_easy_read = format_choice.startswith("Easier Read")
    base_url = ensure_valid_youtube_url(video_id) if video_id else "#"
    
    pdf = PDF(base_path=font_path, is_easy_read=is_easy_read)
    pdf.add_page()
    
    # --- Title ---
    main_title = data.get("main_subject", "Video Notes")
    pdf.create_title(main_title)
    
    line_height = pdf.base_line_height
    
    # --- Go through each section ---
    for section_key, section_content in data.items():
        if section_key == "main_subject" or not section_content:
            continue
        
        # 🧠 DEBUG 5: Print each friendly_name and len(values)
        friendly_name = section_key.replace("_", " ").title()
        print(f"  > Processing '{friendly_name}' ({section_key}): {len(section_content) if isinstance(section_content, list) else section_content}")
        
        # Convert section key to readable heading
        heading = section_key.replace("_", " ").title()
        pdf.create_section_heading(heading)
        
        # Handle list content (which is most common for sections)
        if isinstance(section_content, list):
            for item in section_content:
                # Use tolerant getter here
                content_text = get_content_text(item)
                if not content_text.strip():
                    continue
                
                # Check for nested structure (e.g., Topic Breakdown)
                if 'topic' in item and 'details' in item and isinstance(item['details'], list):
                    # Write the main topic title (bold)
                    pdf.set_font(pdf.font_name, 'B', 11)
                    pdf.write(line_height, f"• {item['topic']}")
                    pdf.ln(line_height)
                    
                    # Process nested details
                    for detail in item['details']:
                        detail_text = get_content_text(detail)
                        timestamp = detail.get("time") if isinstance(detail, dict) else None
                        
                        pdf.set_font(pdf.font_name, '', 11)
                        pdf.set_x(pdf.get_x() + 5) # Indent
                        
                        # Write text content
                        pdf.write_highlighted_text(detail_text, line_height)
                        
                        # Add timestamp/link logic
                        if timestamp and video_id:
                            # Note: Simplified link logic from original instructions
                            link_url = f"{base_url}&t={timestamp}s"
                            pdf.set_text_color(*COLORS["link_text"])
                            pdf.set_font(pdf.font_name, 'B', 11)
                            pdf.write(line_height, f" [{format_timestamp(int(timestamp))}]")
                            pdf.set_text_color(*COLORS["body_text"])
                        
                        pdf.ln(line_height)
                        pdf.set_x(pdf.l_margin) # Reset indent

                else:
                    # Simple list item (Vocabulary, Key Points, etc.)
                    timestamp = item.get("time") if isinstance(item, dict) else None
                    
                    pdf.set_font(pdf.font_name, '', 11)
                    
                    # Write text content
                    pdf.write_highlighted_text(content_text, line_height)
                    
                    # Add timestamp/link logic
                    if timestamp and video_id:
                        link_url = f"{base_url}&t={timestamp}s"
                        pdf.set_text_color(*COLORS["link_text"])
                        pdf.set_font(pdf.font_name, 'B', 11)
                        pdf.write(line_height, f" [{format_timestamp(int(timestamp))}]")
                        pdf.set_text_color(*COLORS["body_text"])

                    pdf.ln(line_height)

                if is_easy_read:
                    pdf.ln(2) # Extra space for easy reading
        
        # Add a major break after a section completes
        pdf.ln(5)

    pdf.output(output)
    if isinstance(output, BytesIO):
        output.seek(0)