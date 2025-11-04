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

# --- Enhanced Color Palette with Visual Hierarchy ---
COLORS = {
    "title_bg": (40, 54, 85),           # Navy
    "title_text": (255, 255, 255),       # White
    "topic_breakdown_bg": (74, 163, 223),     # Sky Blue
    "topic_breakdown_text": (255, 255, 255),
    "key_vocabulary_bg": (255, 165, 0),       # Orange
    "key_vocabulary_text": (0, 0, 0),
    "formulas_and_principles_bg": (155, 89, 182),  # Purple
    "formulas_and_principles_text": (255, 255, 255),
    "teacher_insights_bg": (39, 174, 96),     # Green
    "teacher_insights_text": (255, 255, 255),
    "exam_focus_points_bg": (231, 76, 60),    # Red
    "exam_focus_points_text": (255, 255, 255),
    "common_mistakes_explained_bg": (52, 73, 94),  # Dark Gray
    "common_mistakes_explained_text": (255, 255, 255),
    "key_points_bg": (41, 128, 185),          # Blue
    "key_points_text": (255, 255, 255),
    "short_tricks_bg": (241, 196, 15),        # Yellow
    "short_tricks_text": (0, 0, 0),
    "must_remembers_bg": (22, 160, 133),      # Teal
    "must_remembers_text": (255, 255, 255),
    "default_bg": (40, 54, 85),               # Fallback Navy
    "default_text": (255, 255, 255),
    "link_text": (0, 102, 204),               # Blue for links
    "body_text": (30, 30, 30),                # Dark gray for body
    "line": (220, 220, 220),                  # Light gray for lines
    "highlight_bg": (255, 255, 0),            # Yellow highlight
    "highlight_text": (0, 0, 0)               # Black text on highlight
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


# --- PDF Class with Fixed Layout Management ---
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
        """Creates title with proper spacing and no clipping."""
        self.ln(15)  # Space from top
        self.set_font(self.font_name, "B", 26)
        self.set_fill_color(*COLORS["title_bg"])
        self.set_text_color(*COLORS["title_text"])
        self.cell(0, 28, title, align="C", fill=True)
        self.ln(18)  # Space after title
        self.set_text_color(*COLORS["body_text"])  # Reset text color

    def create_section_heading(self, heading, section_key):
        """Creates colored section heading with proper spacing."""
        self.ln(8)  # Space before heading
        
        # Get section-specific colors
        bg_key = f"{section_key}_bg"
        text_key = f"{section_key}_text"
        bg_color = COLORS.get(bg_key, COLORS["default_bg"])
        text_color = COLORS.get(text_key, COLORS["default_text"])
        
        self.set_font(self.font_name, "B", 14)
        self.set_fill_color(*bg_color)
        self.set_text_color(*text_color)
        self.cell(0, 10, heading, fill=True)
        self.ln(8)  # Space after heading
        
        # Reset colors
        self.set_fill_color(255, 255, 255)
        self.set_text_color(*COLORS["body_text"])

    def write_text_with_highlights(self, text):
        """Writes text with inline highlights, proper wrapping."""
        parts = re.split(r'(<hl>.*?</hl>)', text)
        
        self.set_font(self.font_name, '', 11)
        self.set_text_color(*COLORS["body_text"])
        
        for part in parts:
            if part.startswith('<hl>'):
                # Highlighted portion
                highlight_text = part[4:-5]
                self.set_fill_color(*COLORS["highlight_bg"])
                self.set_text_color(*COLORS["highlight_text"])
                self.set_font(self.font_name, 'B', 11)
                
                # Use multi_cell for proper wrapping
                self.multi_cell(0, 6, highlight_text, fill=True)
                
                # Reset after highlight
                self.set_fill_color(255, 255, 255)
                self.set_text_color(*COLORS["body_text"])
                self.set_font(self.font_name, '', 11)
            else:
                # Normal text
                if part.strip():
                    self.multi_cell(0, 6, part)
        
        self.ln(2)  # Small space after text block

    def add_timestamp_link(self, timestamp, video_id, base_url):
        """Adds timestamp link on same line as last text, right-aligned."""
        if timestamp and video_id:
            link_url = f"{base_url}&t={timestamp}s"
            
            # Save current Y position
            current_y = self.get_y()
            
            # Move to right side for timestamp
            self.set_xy(self.w - self.r_margin - 35, current_y - 6)
            
            # Write timestamp link
            self.set_text_color(*COLORS["link_text"])
            self.set_font(self.font_name, 'B', 9)
            self.cell(35, 6, format_timestamp(int(timestamp)), link=link_url, align="R")
            
            # Reset position and move down
            self.set_xy(self.l_margin, current_y)
            self.ln(4)
            
            # Reset color
            self.set_text_color(*COLORS["body_text"])


def save_to_pdf(data: dict, video_id: Optional[str], font_path: Path, output, format_choice: str = "Default (Compact)"):
    """Generates PDF from extracted data with proper layout management."""
    
    print("\n=== PDF GENERATION DEBUG ===")
    print(f"Sections in data: {list(data.keys())}")
    for key, value in data.items():
        if isinstance(value, list):
            print(f"  {key}: {len(value)} items")
    print("===========================\n")
    
    base_url = ensure_valid_youtube_url(video_id) if video_id else "#"
    
    pdf = PDF(font_path=font_path)
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Title
    main_title = data.get("main_subject", "Video Notes")
    pdf.create_title(main_title)
    
    # Process each section
    for section_key, section_content in data.items():
        if section_key == "main_subject" or not isinstance(section_content, list) or not section_content:
            continue
        
        heading = section_key.replace("_", " ").title()
        pdf.create_section_heading(heading, section_key)
        
        for item in section_content:
            # Handle nested topic breakdown
            if section_key == 'topic_breakdown':
                # Topic name (bold)
                topic_name = item.get('topic', '')
                pdf.set_font(pdf.font_name, "B", 12)
                pdf.set_text_color(*COLORS["body_text"])
                pdf.multi_cell(0, 7, f"• {topic_name}")
                pdf.ln(2)
                
                # Process nested details
                for detail in item.get('details', []):
                    detail_text = get_content_text(detail)
                    if not detail_text.strip():
                        continue
                    
                    # Indent detail
                    pdf.set_x(pdf.l_margin + 8)
                    
                    # Write detail with highlights
                    pdf.write_text_with_highlights(detail_text)
                    
                    # Add timestamp
                    timestamp = detail.get("time") if isinstance(detail, dict) else None
                    pdf.add_timestamp_link(timestamp, video_id, base_url)
                    
                    pdf.ln(3)
                
                pdf.ln(4)  # Extra space after topic
                continue
                
            # Handle flat sections
            content_text = get_content_text(item)
            if not content_text.strip():
                continue
            
            # Add bullet point
            pdf.set_font(pdf.font_name, '', 11)
            pdf.set_text_color(*COLORS["body_text"])
            pdf.cell(5, 6, "•")
            
            # Write content with highlights
            pdf.write_text_with_highlights(content_text)
            
            # Add timestamp
            timestamp = item.get("time") if isinstance(item, dict) else None
            pdf.add_timestamp_link(timestamp, video_id, base_url)
            
            pdf.ln(4)  # Space between items

    # Output PDF
    pdf.output(output)
    if isinstance(output, BytesIO):
        output.seek(0)