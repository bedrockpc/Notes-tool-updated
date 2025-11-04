# -*- coding: utf-8 -*-
import streamlit as st
import os
import json
import re
from pathlib import Path
import google.generativeai as genai
# --- UPDATED IMPORT FOR FPDF2 ---
from fpdf.v2 import FPDF 
# ---------------------------------
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

# --- CORE UTILITY FUNCTIONS (Unchanged) ---
# ... (inject_custom_css, get_video_id, extract_gemini_text, extract_clean_json, 
# get_content_text, format_timestamp, ensure_valid_youtube_url, 
# build_simplified_prompt, run_analysis_and_summarize remain the same)
# ...

# --- PDF Class with FIXED Layout Management ---
class PDF(FPDF):
    def __init__(self, font_path, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.font_name = "NotoSans"
        try:
            # Assumes font files are in the directory specified by font_path (main folder)
            self.add_font(self.font_name, "", str(font_path / "NotoSans-Regular.ttf"))
            self.add_font(self.font_name, "B", str(font_path / "NotoSans-Bold.ttf"))
        except Exception:
            self.font_name = "Arial"
            print(f"WARNING: Could not load NotoSans font. Falling back to {self.font_name}.")

    def create_title(self, title):
        """Creates title with fixed spacing."""
        self.ln(15)  # Space from top
        self.set_font(self.font_name, "B", 26)
        self.set_fill_color(*COLORS["title_bg"])
        self.set_text_color(*COLORS["title_text"])
        self.cell(0, 28, title, align="C", fill=True)
        # --- FIX: Reduced spacing after title (from 18 to 10) ---
        self.ln(10)  
        self.set_text_color(*COLORS["body_text"])  # Reset text color

    def create_section_heading(self, heading, section_key):
        """Creates colored section heading with fixed spacing."""
        self.ln(5)  # Space before heading
        
        # Get section-specific colors
        bg_key = f"{section_key}_bg"
        text_key = f"{section_key}_text"
        bg_color = COLORS.get(bg_key, COLORS["default_bg"])
        text_color = COLORS.get(text_key, COLORS["default_text"])
        
        self.set_font(self.font_name, "B", 14)
        self.set_fill_color(*bg_color)
        self.set_text_color(*text_color)
        self.cell(0, 10, heading, fill=True)
        # --- FIX: Reduced spacing after heading (from 8 to 4) ---
        self.ln(4)
        
        # Reset colors
        self.set_fill_color(255, 255, 255)
        self.set_text_color(*COLORS["body_text"])

    def write_text_with_highlights(self, text, line_height=6):
        """
        FIXED: Writes text with inline highlights using write(), 
        preventing excessive vertical space caused by multi_cell.
        """
        parts = re.split(r'(<hl>.*?</hl>)', text)
        
        self.set_font(self.font_name, '', 11)
        self.set_text_color(*COLORS["body_text"])
        
        # Use available width for wrapping logic
        max_x = self.w - self.r_margin

        for part in parts:
            if part.startswith('<hl>'):
                # Highlighted portion
                highlight_text = part[4:-5]
                
                # Setup highlight style
                self.set_fill_color(*COLORS["highlight_bg"])
                self.set_text_color(*COLORS["highlight_text"])
                self.set_font(self.font_name, 'B', 11)
                
                # Check if the part fits on the current line (simplified check)
                part_width = self.get_string_width(highlight_text)
                if self.get_x() + part_width > max_x:
                    self.ln(line_height) # Force line break if it doesn't fit
                
                # Use write() to keep content inline
                self.write(line_height, highlight_text + " ", fill=True) # Added space after highlight
                
                # Reset after highlight
                self.set_fill_color(255, 255, 255)
                self.set_text_color(*COLORS["body_text"])
                self.set_font(self.font_name, '', 11)
            else:
                # Normal text
                if part.strip():
                    part_width = self.get_string_width(part)
                    if self.get_x() + part_width > max_x:
                        self.ln(line_height) # Force line break if it doesn't fit
                        
                    self.write(line_height, part)

    def add_timestamp_link(self, timestamp, video_id, base_url):
        """Adds timestamp link, correctly positioned."""
        if timestamp and video_id:
            link_url = f"{base_url}&t={timestamp}s"
            
            # Save current Y position
            current_y = self.get_y()
            
            # Move to right side for timestamp, relative to current line
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
    """Generates PDF from extracted data with fixed layout management."""
    
    # ... (Debug prints remain the same)
    
    base_url = ensure_valid_youtube_url(video_id) if video_id else "#"
    
    pdf = PDF(font_path=font_path)
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Title
    main_title = data.get("main_subject", "Video Notes")
    pdf.create_title(main_title)
    
    # Constants for indentation fix
    BULLET_WIDTH = 5
    TEXT_INDENT = 5
    
    # Process each section
    for section_key, section_content in data.items():
        if section_key == "main_subject" or not isinstance(section_content, list) or not section_content:
            continue
        
        heading = section_key.replace("_", " ").title()
        pdf.create_section_heading(heading, section_key)
        
        # --- Save initial margins for restoration ---
        initial_l_margin = pdf.l_margin
        initial_r_margin = pdf.r_margin
        
        for item in section_content:
            # Handle nested topic breakdown (Logic unchanged, but benefits from better write_text_with_highlights)
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
                    
                    # --- Indentation for details ---
                    pdf.set_left_margin(initial_l_margin + BULLET_WIDTH + TEXT_INDENT)
                    pdf.set_x(pdf.l_margin)
                    
                    # Write detail with highlights
                    pdf.write_text_with_highlights(detail_text)
                    
                    # Add timestamp
                    timestamp = detail.get("time") if isinstance(detail, dict) else None
                    pdf.add_timestamp_link(timestamp, video_id, base_url)
                    
                    # --- Reset indentation after detail ---
                    pdf.set_left_margin(initial_l_margin)
                    pdf.set_x(initial_l_margin)
                    pdf.ln(3)

                pdf.ln(4)  # Extra space after topic
                continue
                
            # Handle flat sections
            content_text = get_content_text(item)
            if not content_text.strip():
                continue
            
            # --- FIX: Margin-based bullet point implementation ---
            
            # 1. Draw bullet point
            pdf.set_font(pdf.font_name, '', 11)
            pdf.set_text_color(*COLORS["body_text"])
            pdf.cell(BULLET_WIDTH, 6, "•", new_x=XPos.RIGHT) # Use XPos.RIGHT to keep cursor flowing
            
            # 2. Set temporary margin for text block
            new_l_margin = initial_l_margin + BULLET_WIDTH + TEXT_INDENT
            pdf.set_left_margin(new_l_margin)
            pdf.set_x(new_l_margin)
            
            # 3. Write content with highlights (this handles wrapping internally now)
            pdf.write_text_with_highlights(content_text)
            
            # 4. Add timestamp
            timestamp = item.get("time") if isinstance(item, dict) else None
            pdf.add_timestamp_link(timestamp, video_id, base_url)
            
            # 5. Restore margins
            pdf.set_left_margin(initial_l_margin)
            pdf.set_x(initial_l_margin)
            pdf.ln(4)  # Space between items

    # Output PDF
    pdf.output(output)
    if isinstance(output, BytesIO):
        output.seek(0)
