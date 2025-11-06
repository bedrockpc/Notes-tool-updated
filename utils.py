# -*- coding: utf-8 -*-
import streamlit as st
import json
import re
from pathlib import Path
import google.generativeai as genai
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.lib.colors import HexColor, black, blue
from reportlab.pdfgen import canvas
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

# Modern color palette
COLORS = {
    "primary": HexColor("#2C3E50"),      # Dark blue-grey
    "secondary": HexColor("#3498DB"),     # Bright blue
    "accent": HexColor("#E74C3C"),        # Red accent
    "highlight": HexColor("#F39C12"),     # Orange highlight
    "text": HexColor("#2C3E50"),          # Main text
    "link": HexColor("#3498DB"),          # Links
    "bg_highlight": HexColor("#FFF9C4"),  # Yellow highlight background
}

# Improved System Prompt
SYSTEM_PROMPT = """
You are an expert academic content analyzer. Extract structured study notes from video transcripts.

INPUT FORMAT: JSON array of segments: [{"time": seconds, "text": "content"}]

OUTPUT: Valid JSON object with these exact keys (use snake_case):
{
  "main_subject": "Brief subject description",
  "topic_breakdown": [{"topic": "Name", "details": [{"detail": "Content", "time": 120}]}],
  "key_vocabulary": [{"term": "Word", "definition": "Meaning", "time": 150}],
  "formulas_and_principles": [{"formula_or_principle": "Name", "explanation": "Description", "time": 180}],
  "teacher_insights": [{"insight": "Tip", "time": 210}],
  "exam_focus_points": [{"point": "Important concept", "time": 240}],
  "common_mistakes_explained": [{"mistake": "Error", "explanation": "Why it's wrong", "time": 270}],
  "key_points": [{"text": "Main point", "time": 300}],
  "short_tricks": [{"text": "Quick method", "time": 330}],
  "must_remembers": [{"text": "Critical fact", "time": 360}]
}

RULES:
1. Use EXACT 'time' values from input (in seconds)
2. For highlighting mode: Wrap 2-4 critical words in <hl>text</hl> tags
3. Keep content concise and academic
4. Return ONLY valid JSON (no markdown, no comments)
5. Fill ALL requested sections with available content
"""

# --- UTILITY FUNCTIONS ---

def inject_custom_css():
    """Modern CSS styling"""
    st.markdown("""
        <style>
        .stApp {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        }
        p, label, .stMarkdown {
            font-size: 1.05rem !important;
            line-height: 1.6;
        }
        .stButton>button {
            background: linear-gradient(90deg, #3498DB, #2C3E50);
            color: white;
            border: none;
            padding: 0.75rem 2rem;
            font-weight: 600;
            border-radius: 8px;
            transition: transform 0.2s;
        }
        .stButton>button:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(52, 152, 219, 0.3);
        }
        </style>
    """, unsafe_allow_html=True)

def get_video_id(url: str) -> Optional[str]:
    """Extract YouTube video ID"""
    patterns = [
        r"(?<=v=)[^&#?]+", r"(?<=be/)[^&#?]+", r"(?<=live/)[^&#?]+",
        r"(?<=embed/)[^&#?]+", r"(?<=shorts/)[^&#?]+"
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(0)
    return None

def extract_gemini_text(response) -> Optional[str]:
    """Extract text from Gemini API response"""
    if hasattr(response, 'text'):
        return response.text
    if hasattr(response, 'candidates') and response.candidates:
        try:
            return response.candidates[0].content.parts[0].text
        except (AttributeError, IndexError):
            pass
    return None

def extract_clean_json(response_text: str) -> Optional[str]:
    """Extract JSON from response with markdown cleanup"""
    # Remove markdown code blocks
    cleaned = re.sub(r'```json\s*|\s*```', '', response_text)
    
    # Find JSON object
    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if match:
        json_str = match.group(0)
        try:
            json.loads(json_str)  # Validate
            return json_str
        except json.JSONDecodeError:
            pass
    return None

def format_timestamp(seconds: int) -> str:
    """Convert seconds to [MM:SS] or [HH:MM:SS]"""
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    if hours > 0:
        return f"[{hours:02d}:{minutes:02d}:{secs:02d}]"
    return f"[{minutes:02d}:{secs:02d}]"

def get_content_text(item):
    """Extract text content from various item structures"""
    if isinstance(item, dict):
        for key in ['detail', 'explanation', 'point', 'text', 'definition', 
                    'formula_or_principle', 'insight', 'mistake', 'content']:
            if key in item and item[key]:
                return str(item[key])
    return str(item) if item else ''

# --- API INTERACTION ---

@st.cache_data(ttl=0)
def run_analysis_and_summarize(
    api_key: str, 
    transcript_segments: List[Dict], 
    max_words: int, 
    sections_list_keys: list, 
    user_prompt: str, 
    model_name: str, 
    is_easy_read: bool
) -> Tuple[Optional[Dict[str, Any]], Optional[str], str]:
    """Call Gemini API and return structured JSON"""
    
    sections_str = ", ".join(sections_list_keys)
    
    # Build prompt
    highlighting_instruction = (
        "4. **Highlighting:** Wrap 2-4 critical words in <hl>text</hl> tags."
        if is_easy_read else
        "4. **NO special tags:** Use plain text only."
    )
    
    prompt_instructions = SYSTEM_PROMPT + f"""
{highlighting_instruction}
5. Target total length: ~{max_words} words across all sections
6. Extract ONLY these categories: {sections_str}

USER PREFERENCES: {user_prompt}
"""
    
    transcript_json = json.dumps(transcript_segments, indent=2)
    full_prompt = f"{prompt_instructions}\n\nTRANSCRIPT DATA:\n{transcript_json}"
    
    if not api_key:
        return None, "API Key Missing", full_prompt
    
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        
        response = model.generate_content(full_prompt)
        response_text = extract_gemini_text(response)
        
        if not response_text:
            return None, "Empty API response", full_prompt
        
        # Debug output
        print(f"\n{'='*60}")
        print(f"RAW API RESPONSE (first 800 chars):\n{response_text[:800]}")
        print(f"{'='*60}\n")
        
        json_str = extract_clean_json(response_text)
        if not json_str:
            return None, f"No valid JSON found in response", full_prompt
        
        json_data = json.loads(json_str)
        
        # Normalize keys to snake_case
        def to_snake_case(s):
            s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', s)
            return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
        
        json_data = {to_snake_case(k): v for k, v in json_data.items()}
        
        # Ensure all keys exist with correct types
        for key in EXPECTED_KEYS:
            if key not in json_data:
                json_data[key] = "" if key == "main_subject" else []
            elif key != "main_subject" and not isinstance(json_data[key], list):
                json_data[key] = [json_data[key]] if json_data[key] else []
        
        # Debug output
        print(f"✅ EXTRACTED KEYS: {list(json_data.keys())}")
        for k, v in json_data.items():
            if k != "main_subject":
                print(f"   {k}: {len(v)} items")
        
        return json_data, None, full_prompt
        
    except json.JSONDecodeError as e:
        return None, f"JSON Parse Error: {e}", full_prompt
    except Exception as e:
        return None, f"API Error: {e}", full_prompt

# --- PDF GENERATION (Modern ReportLab) ---

def create_custom_styles(is_easy_read: bool):
    """Create modern PDF styles"""
    styles = getSampleStyleSheet()
    
    # Title style
    styles.add(ParagraphStyle(
        name='CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=COLORS['primary'],
        spaceAfter=12 if is_easy_read else 8,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    ))
    
    # Section heading
    styles.add(ParagraphStyle(
        name='SectionHead',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=COLORS['secondary'],
        spaceBefore=10 if is_easy_read else 6,
        spaceAfter=6 if is_easy_read else 4,
        fontName='Helvetica-Bold',
        borderPadding=(0, 0, 2, 0),
        borderColor=COLORS['secondary'],
        borderWidth=1
    ))
    
    # Topic heading (for nested structures)
    styles.add(ParagraphStyle(
        name='TopicHead',
        parent=styles['Normal'],
        fontSize=11,
        textColor=COLORS['primary'],
        spaceBefore=6 if is_easy_read else 3,
        spaceAfter=3 if is_easy_read else 2,
        fontName='Helvetica-Bold',
        leftIndent=0
    ))
    
    # Body text
    styles.add(ParagraphStyle(
        name='CustomBody',
        parent=styles['Normal'],
        fontSize=10,
        textColor=COLORS['text'],
        leading=16 if is_easy_read else 13,
        spaceBefore=2 if is_easy_read else 1,
        spaceAfter=4 if is_easy_read else 2,
        leftIndent=15,
        fontName='Helvetica'
    ))
    
    # Timestamp link
    styles.add(ParagraphStyle(
        name='Timestamp',
        parent=styles['Normal'],
        fontSize=9,
        textColor=COLORS['link'],
        fontName='Helvetica-Bold',
        alignment=TA_LEFT
    ))
    
    return styles

def process_highlight_text(text: str, is_easy_read: bool) -> str:
    """Convert <hl> tags to ReportLab formatting"""
    if not is_easy_read:
        # Remove all highlight tags for default mode
        return re.sub(r'<hl>(.*?)</hl>', r'\1', text)
    
    # Convert to ReportLab's background color syntax
    return re.sub(
        r'<hl>(.*?)</hl>',
        r'<span backcolor="#FFF9C4" color="#E65100"><b>\1</b></span>',
        text
    )

def save_to_pdf(
    data: dict, 
    video_id: Optional[str], 
    font_path: Path, 
    output: BytesIO, 
    format_choice: str = "Default (Compact)"
):
    """Generate modern PDF with ReportLab"""
    
    is_easy_read = format_choice.startswith("Easier Read")
    base_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else None
    
    # Create PDF document
    doc = SimpleDocTemplate(
        output,
        pagesize=letter,
        rightMargin=0.75*inch,
        leftMargin=0.75*inch,
        topMargin=0.75*inch,
        bottomMargin=0.75*inch
    )
    
    story = []
    styles = create_custom_styles(is_easy_read)
    
    # Title
    title = data.get("main_subject", "Video Study Notes")
    story.append(Paragraph(title, styles['CustomTitle']))
    story.append(Spacer(1, 0.2*inch if is_easy_read else 0.1*inch))
    
    # Process each section
    for section_key, section_content in data.items():
        if section_key == "main_subject" or not isinstance(section_content, list) or not section_content:
            continue
        
        # Section heading
        heading = section_key.replace("_", " ").title()
        story.append(Paragraph(heading, styles['SectionHead']))
        
        # Handle nested topic breakdown
        if section_key == 'topic_breakdown':
            for item in section_content:
                topic_name = item.get('topic', '')
                if topic_name:
                    story.append(Paragraph(f"• {topic_name}", styles['TopicHead']))
                
                for detail in item.get('details', []):
                    detail_text = get_content_text(detail)
                    if not detail_text.strip():
                        continue
                    
                    # Process highlighting
                    formatted_text = process_highlight_text(detail_text, is_easy_read)
                    
                    # Add timestamp link if available
                    timestamp = detail.get('time')
                    if timestamp and base_url:
                        link_url = f"{base_url}&t={int(timestamp)}s"
                        ts_formatted = format_timestamp(int(timestamp))
                        formatted_text = f'{formatted_text} <a href="{link_url}" color="blue">{ts_formatted}</a>'
                    
                    story.append(Paragraph(formatted_text, styles['CustomBody']))
            
            continue
        
        # Handle flat sections
        for item in section_content:
            content_text = get_content_text(item)
            if not content_text.strip():
                continue
            
            # Process highlighting
            formatted_text = process_highlight_text(content_text, is_easy_read)
            
            # Add timestamp
            timestamp = item.get('time') if isinstance(item, dict) else None
            if timestamp and base_url:
                link_url = f"{base_url}&t={int(timestamp)}s"
                ts_formatted = format_timestamp(int(timestamp))
                formatted_text = f'{formatted_text} <a href="{link_url}" color="blue">{ts_formatted}</a>'
            
            story.append(Paragraph(f"• {formatted_text}", styles['CustomBody']))
        
        # Add spacing between sections
        story.append(Spacer(1, 0.15*inch if is_easy_read else 0.08*inch))
    
    # Build PDF
    doc.build(story)
    output.seek(0)
    
    print(f"\n✅ PDF generated successfully ({len(story)} elements)")
