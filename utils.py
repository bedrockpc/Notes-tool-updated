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

-------------------------------------------------------------------

CONFIGURATION

-------------------------------------------------------------------

EXPECTED_KEYS = [
"main_subject", "topic_breakdown", "key_vocabulary",
"formulas_and_principles", "teacher_insights",
"exam_focus_points", "common_mistakes_explained",
"key_points", "short_tricks", "must_remembers"
]

Vibrant color palette

PALETTE = {
"title_bg": (33, 150, 243),           # Bright Blue
"title_text": (255, 255, 255),
"section_colors": {
"topic_breakdown": (255, 87, 34),         # Deep Orange
"key_vocabulary": (0, 150, 136),          # Teal
"formulas_and_principles": (156, 39, 176),# Purple
"teacher_insights": (63, 81, 181),        # Indigo
"exam_focus_points": (255, 193, 7),       # Amber
"common_mistakes_explained": (244, 67, 54),# Red
"key_points": (76, 175, 80),              # Green
"short_tricks": (0, 188, 212),            # Cyan
"must_remembers": (233, 30, 99)           # Pink
},
"body_text": (20, 20, 20),
"link_text": (0, 102, 255),
"highlight_bg": (255, 255, 120),
"line": (210, 210, 210)
}

-------------------------------------------------------------------

CSS INJECTION

-------------------------------------------------------------------

def inject_custom_css():
st.markdown("""
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
""", unsafe_allow_html=True)

-------------------------------------------------------------------

UTILITY FUNCTIONS

-------------------------------------------------------------------

def get_video_id(url: str) -> Optional[str]:
patterns = [
r"(?<=v=)[^&#?]+", r"(?<=be/)[^&#?]+",
r"(?<=live/)[^&#?]+", r"(?<=embed/)[^&#?]+",
r"(?<=shorts/)[^&#?]+"
]
for p in patterns:
m = re.search(p, url)
if m: return m.group(0)
return None

def extract_gemini_text(response) -> Optional[str]:
txt = getattr(response, "text", None)
if not txt and hasattr(response, "candidates") and response.candidates:
try:
return response.candidates[0].content.parts[0].text
except Exception:
pass
return txt

def extract_clean_json(response_text: str) -> Optional[str]:
response_text = re.sub(r'"json\s*', '', response_text) response_text = re.sub(r'"\s*', '', response_text)
match = re.search(r'{.*}', response_text.strip(), re.DOTALL)
return match.group(0) if match else None

def get_content_text(item):
if isinstance(item, dict):
return str(item.get('detail') or item.get('explanation') or
item.get('point') or item.get('text') or
item.get('definition') or item.get('formula_or_principle') or
item.get('insight') or item.get('mistake') or
item.get('trick') or item.get('fact') or item.get('content') or '')
return str(item or '')

def format_timestamp(seconds: int) -> str:
total = int(seconds)
h, m, s = total // 3600, (total % 3600) // 60, total % 60
return f"[{h:02}:{m:02}:{s:02}]" if h else f"[{m:02}:{s:02}]"

def ensure_valid_youtube_url(vid: str) -> str:
return f"https://www.youtube.com/watch?v={vid}"

-------------------------------------------------------------------

PROMPT BUILDING

-------------------------------------------------------------------

def build_simplified_prompt(keys: list, max_words: int, user_prompt: str, is_easy: bool) -> str:
desc = {
"topic_breakdown": "Main topics with details",
"key_vocabulary": "Important terms and definitions",
"formulas_and_principles": "Key formulas and principles",
"teacher_insights": "Instructor explanations",
"exam_focus_points": "Likely exam questions",
"common_mistakes_explained": "Frequent errors and reasons",
"key_points": "Essential takeaways",
"short_tricks": "Quick methods",
"must_remembers": "Critical facts"
}
sections = "\n".join([f"- {desc.get(k, k)}" for k in keys])
hl = ""
if is_easy:
hl = "Wrap the 3-5 most important words with <hl> tags for highlights."
return f"""
You are analyzing an educational transcript and must extract structured study notes.

REQUIRED SECTIONS:
{sections}

RULES:

1. Extract at least 3-5 items per section
2. Use actual time values
3. Keep total under {max_words} words
4. Return only valid JSON
{hl}

USER PROMPT: {user_prompt}
"""

-------------------------------------------------------------------

GEMINI CALL

-------------------------------------------------------------------

@st.cache_data(ttl=0)
def run_analysis_and_summarize(api_key: str, transcript_segments: List[Dict],
max_words: int, sections_keys: list,
user_prompt: str, model_name: str,
is_easy_read: bool) -> Tuple[Optional[Dict[str, Any]], Optional[str], str]:

system_prompt = build_simplified_prompt(sections_keys, max_words, user_prompt, is_easy_read)
transcript = "\n\n".join([f"[Time: {seg.get('time',0)}s] {seg.get('text','')}" for seg in transcript_segments])
full_prompt = f"{system_prompt}\n\nTRANSCRIPT:\n{transcript}\n\nReturn JSON only."

if not api_key:
    return None, "Missing API key", full_prompt

try:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(model_name)
    conf = {"temperature": 0.7, "top_p": 0.9, "max_output_tokens": 8192}
    resp = model.generate_content(full_prompt, generation_config=conf)
    text = extract_gemini_text(resp)
    if not text:
        return None, "Empty response", full_prompt
    cleaned = extract_clean_json(text)
    if not cleaned:
        return None, "JSON not found", full_prompt
    data = json.loads(cleaned)
    normalized = {re.sub(r'(?<!^)(?=[A-Z])', '_', k).lower(): v for k, v in data.items()}
    return normalized, None, full_prompt
except Exception as e:
    return None, f"Gemini error: {e}", full_prompt

-------------------------------------------------------------------

PDF GENERATION

-------------------------------------------------------------------

class PDF(FPDF):
def init(self, font_path, *a, **kw):
super().init(*a, **kw)
self.font_name = "NotoSans"
try:
self.add_font(self.font_name, "", str(font_path / "NotoSans-Regular.ttf"))
self.add_font(self.font_name, "B", str(font_path / "NotoSans-Bold.ttf"))
except:
self.font_name = "Arial"

# Title
def create_title(self, title):
    self.set_font(self.font_name, "B", 24)
    self.set_fill_color(*PALETTE["title_bg"])
    self.set_text_color(*PALETTE["title_text"])
    self.cell(0, 18, title, align="C", fill=True, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    self.ln(10)

# Section Header
def create_section_heading(self, heading, color):
    self.set_font(self.font_name, "B", 16)
    self.set_text_color(*color)
    self.cell(0, 10, heading, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    self.set_draw_color(*color)
    self.set_line_width(0.8)
    self.line(self.get_x(), self.get_y(), self.get_x() + 190, self.get_y())
    self.ln(5)
    self.set_text_color(*PALETTE["body_text"])

# Highlight text writer
def write_highlighted_text(self, text, style=''):
    self.set_font(self.font_name, style, 11)
    parts = re.split(r'(<hl>.*?</hl>)', text)
    for part in parts:
        if part.startswith('<hl>'):
            word = part[4:-5]
            self.set_fill_color(*PALETTE["highlight_bg"])
            self.set_font(self.font_name, 'B', 11)
            self.cell(self.get_string_width(word) + 2, 7, word, fill=True)
            self.set_font(self.font_name, style, 11)
        else:
            self.set_fill_color(255, 255, 255)
            self.multi_cell(0, 7, part)
    self.ln(1)

-------------------------------------------------------------------

SAVE TO PDF

-------------------------------------------------------------------

def save_to_pdf(data: dict, video_id: Optional[str], font_path: Path, output, format_choice: str = "Bright"):
base_url = ensure_valid_youtube_url(video_id) if video_id else "#"
line_h = 7
pdf = PDF(font_path=font_path)
pdf.add_page()
pdf.set_auto_page_break(auto=True, margin=15)

# Title
title = data.get("main_subject", "Video Notes")
pdf.create_title(title)

for key, content in data.items():
    if key == "main_subject" or not isinstance(content, list) or not content:
        continue
    heading = key.replace("_", " ").title()
    color = PALETTE["section_colors"].get(key, (50, 50, 50))
    pdf.create_section_heading(heading, color)

    for item in content:
        if key == "topic_breakdown":
            pdf.set_font(pdf.font_name, "B", 12)
            pdf.multi_cell(0, line_h, f"• {item.get('topic','')}")
            for det in item.get("details", []):
                txt = get_content_text(det)
                pdf.set_x(pdf.l_margin + 6)
                pdf.set_font(pdf.font_name, '', 11)
                pdf.write_highlighted_text(txt)
                ts = det.get("time")
                if ts and video_id:
                    link = f"{base_url}&t={ts}s"
                    pdf.set_text_color(*PALETTE["link_text"])
                    pdf.set_font(pdf.font_name, 'B', 10)
                    pdf.cell(0, line_h, format_timestamp(ts), link=link, align="R")
                    pdf.set_text_color(*PALETTE["body_text"])
                pdf.ln(2)
            pdf.ln(3)
            continue

        txt = get