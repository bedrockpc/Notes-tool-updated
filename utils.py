# -*- coding: utf-8 -*-
import streamlit as st
import json
import re
from pathlib import Path
import google.generativeai as genai
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, KeepTogether
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.lib.colors import HexColor, white
from reportlab.platypus.flowables import Flowable
from reportlab.pdfgen import canvas as pdfcanvas
from io import BytesIO
import time
from typing import Optional, Tuple, Dict, Any, List

# --- MODERN COLOR PALETTE ---
COLORS = {
    # Primary palette (vibrant & professional)
    "primary": HexColor("#1E88E5"),       # Vibrant blue
    "primary_dark": HexColor("#1565C0"),  # Darker blue
    "secondary": HexColor("#26A69A"),     # Teal accent
    "accent": HexColor("#FF6F00"),        # Orange accent
    
    # Text colors
    "text_dark": HexColor("#212121"),     # Almost black
    "text_medium": HexColor("#424242"),   # Dark grey
    "text_light": HexColor("#757575"),    # Medium grey
    
    # Background colors
    "bg_section": HexColor("#E3F2FD"),    # Light blue background
    "bg_highlight": HexColor("#FFF59D"),  # Yellow highlight
    "bg_card": HexColor("#FAFAFA"),       # Off-white card
    
    # Link color
    "link": HexColor("#1976D2"),          # Blue link
}

# Section icons/emojis
SECTION_ICONS = {
    "topic_breakdown": "📚",
    "key_vocabulary": "📖",
    "formulas_and_principles": "🔬",
    "teacher_insights": "💡",
    "exam_focus_points": "⭐",
    "common_mistakes_explained": "⚠️",
    "key_points": "✨",
    "short_tricks": "⚡",
    "must_remembers": "🧠"
}

# --- Configuration and Constants ---
EXPECTED_KEYS = [
    "main_subject", "topic_breakdown", "key_vocabulary",
    "formulas_and_principles", "teacher_insights",
    "exam_focus_points", "common_mistakes_explained", 
    "key_points", "short_tricks", "must_remembers" 
]

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
            background: linear-gradient(90deg, #1E88E5, #1565C0);
            color: white;
            border: none;
            padding: 0.75rem 2rem;
            font-weight: 600;
            border-radius: 8px;
            transition: transform 0.2s;
        }
        .stButton>button:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(30, 136, 229, 0.3);
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
    cleaned = re.sub(r'```json\s*|\s*```', '', response_text)
    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if match:
        json_str = match.group(0)
        try:
            json.loads(json_str)
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
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

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
        
        print(f"\n{'='*60}")
        print(f"RAW API RESPONSE (first 800 chars):\n{response_text[:800]}")
        print(f"{'='*60}\n")
        
        json_str = extract_clean_json(response_text)
        if not json_str:
            return None, f"No valid JSON found in response", full_prompt
        
        json_data = json.loads(json_str)
        
        def to_snake_case(s):
            s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', s)
            return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()
        
        json_data = {to_snake_case(k): v for k, v in json_data.items()}
        
        for key in EXPECTED_KEYS:
            if key not in json_data:
                json_data[key] = "" if key == "main_subject" else []
            elif key != "main_subject" and not isinstance(json_data[key], list):
                json_data[key] = [json_data[key]] if json_data[key] else []
        
        print(f"✅ EXTRACTED KEYS: {list(json_data.keys())}")
        for k, v in json_data.items():
            if k != "main_subject":
                print(f"   {k}: {len(v)} items")
        
        return json_data, None, full_prompt
        
    except json.JSONDecodeError as e:
        return None, f"JSON Parse Error: {e}", full_prompt
    except Exception as e:
        return None, f"API Error: {e}", full_prompt

# --- CUSTOM FLOWABLE FOR SECTION HEADER ---
class SectionHeader(Flowable):
    """Custom section header with colored background box"""
    
    def __init__(self, text, icon="", width=6.5*inch, is_easy_read=False):
        Flowable.__init__(self)
        self.text = text
        self.icon = icon
        self.width = width
        self.height = 0.4*inch if is_easy_read else 0.35*inch
        self.is_easy_read = is_easy_read
    
    def draw(self):
        canvas = self.canv
        
        # Draw colored background box
        canvas.setFillColor(COLORS['primary'])
        canvas.rect(0, 0, self.width, self.height, fill=1, stroke=0)
        
        # Draw text in white
        canvas.setFillColor(white)
        canvas.setFont("Helvetica-Bold", 13 if self.is_easy_read else 12)
        
        text_with_icon = f"{self.icon} {self.text}" if self.icon else self.text
        canvas.drawString(12, self.height/2 - 5, text_with_icon)

# --- CUSTOM PAGE TEMPLATE WITH FOOTER ---
class NumberedCanvas(pdfcanvas.Canvas):
    """Canvas with page numbers and footer"""
    
    def __init__(self, *args, **kwargs):
        self.video_title = kwargs.pop('video_title', 'Video Notes')
        pdfcanvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_footer(num_pages)
            pdfcanvas.Canvas.showPage(self)
        pdfcanvas.Canvas.save(self)

    def draw_page_footer(self, page_count):
        self.saveState()
        self.setFont('Helvetica', 8)
        self.setFillColor(COLORS['text_light'])
        
        # Left: Video title
        self.drawString(0.75*inch, 0.5*inch, self.video_title[:50])
        
        # Right: Page number
        page_num = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(letter[0] - 0.75*inch, 0.5*inch, page_num)
        
        # Center: App branding
        self.drawCentredString(letter[0]/2, 0.5*inch, "Generated by AI Notes Generator")
        
        self.restoreState()

# --- PDF GENERATION ---

def create_custom_styles(is_easy_read: bool):
    """Create professional PDF styles with proper spacing"""
    styles = getSampleStyleSheet()
    
    # Title style
    styles.add(ParagraphStyle(
        name='CustomTitle',
        parent=styles['Heading1'],
        fontSize=26,
        textColor=COLORS['primary_dark'],
        spaceAfter=18 if is_easy_read else 12,
        spaceBefore=6,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    ))
    
    # Topic heading (for nested structures)
    styles.add(ParagraphStyle(
        name='TopicHead',
        parent=styles['Normal'],
        fontSize=11,
        textColor=COLORS['text_dark'],
        spaceBefore=10 if is_easy_read else 6,
        spaceAfter=6 if is_easy_read else 3,
        fontName='Helvetica-Bold',
        leftIndent=8
    ))
    
    # Body text - DEFAULT MODE (COMPACT)
    styles.add(ParagraphStyle(
        name='CustomBody',
        parent=styles['Normal'],
        fontSize=10,
        textColor=COLORS['text_dark'],
        leading=14,  # Tight line spacing for default
        spaceBefore=2,  # Minimal space before
        spaceAfter=4,   # Minimal space after
        leftIndent=20,
        rightIndent=10,
        fontName='Helvetica'
    ))
    
    # Body text - EASY READ MODE (SPACIOUS)
    styles.add(ParagraphStyle(
        name='CustomBodySpacious',
        parent=styles['Normal'],
        fontSize=10,
        textColor=COLORS['text_dark'],
        leading=18,  # INCREASED line spacing (was 16)
        spaceBefore=6,  # MORE space before (was 2)
        spaceAfter=8,   # MORE space after (was 4)
        leftIndent=20,
        rightIndent=10,
        fontName='Helvetica'
    ))
    
    # Timestamp badge style
    styles.add(ParagraphStyle(
        name='TimestampBadge',
        parent=styles['Normal'],
        fontSize=8,
        textColor=COLORS['link'],
        fontName='Helvetica-Bold',
        alignment=TA_LEFT,
        backColor=HexColor("#E3F2FD"),
        borderPadding=2,
        borderRadius=3
    ))
    
    return styles

def process_highlight_text(text: str, is_easy_read: bool) -> str:
    """Convert <hl> tags to ReportLab formatting with improved contrast"""
    if not is_easy_read:
        return re.sub(r'<hl>(.*?)</hl>', r'\1', text)
    
    # Enhanced highlighting: yellow background + bold orange text
    return re.sub(
        r'<hl>(.*?)</hl>',
        r'<span backcolor="#FFF59D" color="#E65100"><b>\1</b></span>',
        text
    )

def save_to_pdf(
    data: dict, 
    video_id: Optional[str], 
    font_path: Path, 
    output: BytesIO, 
    format_choice: str = "Default (Compact)"
):
    """Generate professional PDF with enhanced design"""
    
    is_easy_read = format_choice.startswith("Easier Read")
    base_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else None
    
    # Get video title for footer
    video_title = data.get("main_subject", "Video Study Notes")
    
    # Create PDF with custom canvas (for footer)
    doc = SimpleDocTemplate(
        output,
        pagesize=letter,
        rightMargin=0.75*inch,
        leftMargin=0.75*inch,
        topMargin=0.75*inch,
        bottomMargin=0.75*inch,
        title=video_title
    )
    
    story = []
    styles = create_custom_styles(is_easy_read)
    
    # Select body style based on mode
    body_style = styles['CustomBodySpacious'] if is_easy_read else styles['CustomBody']
    
    # Title with extra padding
    story.append(Spacer(1, 0.1*inch))
    story.append(Paragraph(video_title, styles['CustomTitle']))
    story.append(Spacer(1, 0.25*inch if is_easy_read else 0.15*inch))
    
    # Process each section
    for section_key, section_content in data.items():
        if section_key == "main_subject" or not isinstance(section_content, list) or not section_content:
            continue
        
        # Get section name and icon
        heading = section_key.replace("_", " ").title()
        icon = SECTION_ICONS.get(section_key, "📌")
        
        # Add section header with colored box
        story.append(SectionHeader(heading, icon, is_easy_read=is_easy_read))
        story.append(Spacer(1, 0.15*inch if is_easy_read else 0.1*inch))
        
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
                    
                    formatted_text = process_highlight_text(detail_text, is_easy_read)
                    
                    timestamp = detail.get('time')
                    if timestamp and base_url:
                        link_url = f"{base_url}&t={int(timestamp)}s"
                        ts_formatted = format_timestamp(int(timestamp))
                        # >>> FIX: Embed clickable hyperlink tag
                        link_tag = f'<font color="#1976D2" size="8"><b><a href="{link_url}">[{ts_formatted}]</a></b></font>'
                        formatted_text = f'{formatted_text} {link_tag}'
                    
                    story.append(Paragraph(formatted_text, body_style))
            
            # Extra spacing after section
            story.append(Spacer(1, 0.2*inch if is_easy_read else 0.12*inch))
            continue
        
        # Handle flat sections
        for item in section_content:
            content_text = get_content_text(item)
            if not content_text.strip():
                continue
            
            formatted_text = process_highlight_text(content_text, is_easy_read)
            
            timestamp = item.get('time') if isinstance(item, dict) else None
            if timestamp and base_url:
                link_url = f"{base_url}&t={int(timestamp)}s"
                ts_formatted = format_timestamp(int(timestamp))
                # >>> FIX: Embed clickable hyperlink tag
                link_tag = f'<font color="#1976D2" size="8"><b><a href="{link_url}">[{ts_formatted}]</a></b></font>'
                formatted_text = f'{formatted_text} {link_tag}'
            
            story.append(Paragraph(f"• {formatted_text}", body_style))
        
        # Section spacing
        story.append(Spacer(1, 0.2*inch if is_easy_read else 0.12*inch))
    
    # Build PDF with custom canvas
    doc.build(
        story,
        canvasmaker=lambda *args, **kwargs: NumberedCanvas(*args, video_title=video_title, **kwargs)
    )
    output.seek(0)
    
    print(f"\n✅ PDF generated successfully ({len(story)} elements, Easy Read: {is_easy_read})")
