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

# --- Color Palette (Used for PDF generation) ---
COLORS = {
    "title_bg": (40, 54, 85), "title_text": (255, 255, 255),
    "heading_text": (40, 54, 85), "link_text": (0, 0, 255), 
    "body_text": (30, 30, 30), "line": (220, 220, 220),
    "highlight_bg": (255, 255, 0)
}

# --- CORE UTILITY FUNCTIONS ---

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
    """Extracts JSON from response, handling markdown code blocks."""
    # Remove markdown code blocks
    response_text = re.sub(r'```json\s*', '', response_text)
    response_text = re.sub(r'```\s*', '', response_text)
    
    # Find the JSON object
    match = re.search(r'\{.*\}', response_text.strip(), re.DOTALL)
    if match:
        return match.group(0)
    return None

def get_content_text(item):
    """Retrieves content text using multiple fallback keys."""
    if isinstance(item, dict):
        text = (item.get('detail') or item.get('explanation') or 
                item.get('point') or item.get('text') or 
                item.get('definition') or item.get('formula_or_principle') or 
                item.get('insight') or item.get('mistake') or 
                item.get('trick') or item.get('fact') or 
                item.get('content') or '')
        return str(text)
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


def build_simplified_prompt(sections_list_keys: list, max_words: int, user_prompt: str, is_easy_read: bool) -> str:
    """Builds a simplified, direct prompt that forces content generation."""
    
    # Map sections to simple descriptions
    section_descriptions = {
        "topic_breakdown": "List of main topics with details",
        "key_vocabulary": "Important terms and definitions",
        "formulas_and_principles": "Key formulas, equations, or principles",
        "teacher_insights": "Important teaching points or insights",
        "exam_focus_points": "Points likely to appear in exams",
        "common_mistakes_explained": "Common errors students make",
        "key_points": "Essential takeaways",
        "short_tricks": "Quick tips or shortcuts",
        "must_remembers": "Critical facts to memorize"
    }
    
    sections_desc = "\n".join([f"- {section_descriptions.get(k, k)}" for k in sections_list_keys])
    
    highlight_instruction = ""
    if is_easy_read:
        highlight_instruction = """
For each text entry, identify the MOST important 3-5 word phrase and wrap it with <hl> tags.
Example: "Newton's second law states that <hl>force equals mass times acceleration</hl>."
"""
    
    prompt = f"""You are analyzing an educational video transcript. Extract structured study notes.

REQUIRED SECTIONS:
{sections_desc}

CRITICAL RULES:
1. Extract AT LEAST 3-5 items for EACH section requested above
2. Use the exact 'time' values from the transcript segments (don't calculate or infer)
3. Keep total output under {max_words} words
4. Return ONLY valid JSON, no markdown formatting
{highlight_instruction}

USER INSTRUCTIONS: {user_prompt}

OUTPUT FORMAT - You MUST fill in content for each section:
{{
  "main_subject": "Brief subject description",
  "topic_breakdown": [
    {{
      "topic": "Topic Name",
      "details": [
        {{"detail": "Specific detail about the topic", "time": 45}}
      ]
    }}
  ],
  "key_vocabulary": [
    {{"term": "Term", "definition": "Clear definition", "time": 120}}
  ],
  "formulas_and_principles": [
    {{"formula_or_principle": "Name", "explanation": "What it means", "time": 180}}
  ],
  "teacher_insights": [
    {{"insight": "Important teaching point", "time": 240}}
  ],
  "exam_focus_points": [
    {{"point": "Likely exam question", "time": 300}}
  ],
  "common_mistakes_explained": [
    {{"mistake": "Common error", "explanation": "Why it's wrong", "time": 360}}
  ],
  "key_points": [
    {{"text": "Essential takeaway", "time": 420}}
  ],
  "short_tricks": [
    {{"text": "Helpful shortcut", "time": 480}}
  ],
  "must_remembers": [
    {{"text": "Critical fact", "time": 540}}
  ]
}}

IMPORTANT: Do NOT return empty arrays []. Extract real content from the transcript for each section.
"""
    return prompt


@st.cache_data(ttl=0) 
def run_analysis_and_summarize(api_key: str, transcript_segments: List[Dict], max_words: int, 
                               sections_list_keys: list, user_prompt: str, model_name: str, 
                               is_easy_read: bool) -> Tuple[Optional[Dict[str, Any]], Optional[str], str]:
    
    # Build the simplified prompt
    system_prompt = build_simplified_prompt(sections_list_keys, max_words, user_prompt, is_easy_read)
    
    # Convert transcript segments to readable format
    transcript_text = "\n\n".join([
        f"[Time: {seg.get('time', '0')} seconds]\n{seg.get('text', '')}"
        for seg in transcript_segments
    ])
    
    full_prompt = f"""{system_prompt}

TRANSCRIPT TO ANALYZE:
---
{transcript_text}
---

Now provide the JSON output with actual content extracted from the transcript above:"""
    
    if not api_key:
        time.sleep(1)
        return None, "API Key Missing", full_prompt
        
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        
        # Configure generation to be more deterministic
        generation_config = {
            "temperature": 0.7,
            "top_p": 0.95,
            "top_k": 40,
            "max_output_tokens": 8192,
        }
        
        response = model.generate_content(full_prompt, generation_config=generation_config)
        response_text = extract_gemini_text(response)

        if not response_text:
            time.sleep(2)
            return None, "Empty response from model.", full_prompt
        
        print("\n=== RAW MODEL RESPONSE ===")
        print(response_text[:1000])
        print("=========================\n")
        
        cleaned_response = extract_clean_json(response_text)

        if not cleaned_response:
            return None, "Could not extract JSON from response.", full_prompt

        json_data = json.loads(cleaned_response)
        
        # Normalize keys to snake_case
        normalized_data = {}
        for key, value in json_data.items():
            # Convert camelCase/PascalCase to snake_case
            snake_key = re.sub(r'(?<!^)(?=[A-Z])', '_', key).lower()
            normalized_data[snake_key] = value
        
        # Validate that we got actual content
        empty_sections = []
        for key in sections_list_keys:
            if key in normalized_data:
                if isinstance(normalized_data[key], list) and len(normalized_data[key]) == 0:
                    empty_sections.append(key)
        
        if empty_sections:
            print(f"WARNING: Empty sections detected: {empty_sections}")
        
        print(f"\n=== EXTRACTED DATA SUMMARY ===")
        for key, value in normalized_data.items():
            if isinstance(value, list):
                print(f"{key}: {len(value)} items")
            else:
                print(f"{key}: {value}")
        print("==============================\n")
        
        return normalized_data, None, full_prompt
        
    except json.JSONDecodeError as e:
        print(f"JSON Parse Error: {e}")
        print(f"Attempted to parse: {cleaned_response[:500] if cleaned_response else 'None'}")
        return None, f"JSON PARSE ERROR: {e}", full_prompt
    except Exception as e:
        print(f"API Error: {e}")
        return None, f"Gemini API Error: {e}", full_prompt


# --- PDF Class ---
class PDF(FPDF):
    def __init__(self, font_path, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.font_name = "NotoSans"
        try:
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
        """Writes text with highlight support."""
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


def save_to_pdf(data: dict, video_id: Optional[str], font_path: Path, output, format_choice: str = "Default (Compact)"):
    """Generates PDF from extracted data."""
    
    print("\n=== PDF GENERATION DEBUG ===")
    print(f"Sections in data: {list(data.keys())}")
    for key, value in data.items():
        if isinstance(value, list):
            print(f"  {key}: {len(value)} items")
    print("===========================\n")
    
    base_url = ensure_valid_youtube_url(video_id) if video_id else "#"
    line_height = 7 
    
    pdf = PDF(font_path=font_path)
    pdf.add_page()
    
    # Title
    main_title = data.get("main_subject", "Video Notes")
    pdf.create_title(main_title)
    
    # Process each section
    for section_key, section_content in data.items():
        if section_key == "main_subject" or not isinstance(section_content, list) or not section_content:
            continue
        
        heading = section_key.replace("_", " ").title()
        pdf.create_section_heading(heading)
        
        for item in section_content:
            # Handle nested topic breakdown
            if section_key == 'topic_breakdown':
                pdf.set_font(pdf.font_name, "B", 11)
                pdf.multi_cell(0, line_height, text=f"  {item.get('topic', '')}")
                
                for detail in item.get('details', []):
                    detail_text = get_content_text(detail)
                    timestamp = detail.get("time") if isinstance(detail, dict) else None
                    
                    pdf.set_x(pdf.get_x() + 5)
                    pdf.set_font(pdf.font_name, '', 11)
                    pdf.write_highlighted_text(detail_text)

                    if timestamp and video_id:
                        link_url = f"{base_url}&t={timestamp}s"
                        pdf.set_text_color(*COLORS["link_text"])
                        pdf.set_font(pdf.font_name, 'B', 11)
                        pdf.set_xy(pdf.w - pdf.r_margin - 30, pdf.get_y() - line_height) 
                        pdf.cell(30, line_height, text=format_timestamp(int(timestamp)), link=link_url, align="R")
                        pdf.set_text_color(*COLORS["body_text"])
                    
                    pdf.ln(2)

                pdf.set_x(pdf.l_margin)
                continue
                
            # Handle flat sections
            content_text = get_content_text(item)
            if not content_text.strip():
                continue
            
            pdf.set_font(pdf.font_name, '', 11)
            pdf.write_highlighted_text(content_text)
            
            timestamp = item.get("time") if isinstance(item, dict) else None
            if timestamp and video_id:
                link_url = f"{base_url}&t={timestamp}s"
                pdf.set_text_color(*COLORS["link_text"])
                pdf.set_font(pdf.font_name, 'B', 11)
                pdf.set_xy(pdf.w - pdf.r_margin - 30, pdf.get_y() - line_height)
                pdf.cell(30, line_height, text=format_timestamp(int(timestamp)), link=link_url, align="R")
                pdf.set_text_color(*COLORS["body_text"])
                
            pdf.ln(2)

    pdf.output(output)
    if isinstance(output, BytesIO):
        output.seek(0)