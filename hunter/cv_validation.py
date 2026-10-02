"""Independent PDF layout gate for the Strategy CV."""
from pathlib import Path


def verify_ai_cv(path):
    """Require a readable, native-template AI CV on exactly one A4 page."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError('AI CV review needs pypdf installed; do not mark it prepared without a PDF check') from exc

    try:
        pages = PdfReader(str(Path(path))).pages
        if len(pages) != 1:
            raise ValueError('AI Product CV must be exactly one page')
        page = pages[0]
        width = float(page.mediabox.width)
        height = float(page.mediabox.height)
        if abs(width - 595.3) > 2 or abs(height - 841.9) > 2:
            raise ValueError('AI Product CV must use A4 page size')
        if len((page.extract_text() or '').strip()) < 500:
            raise ValueError('AI Product CV page has too little readable content')
        return {'page_count': 1, 'page_size': 'A4', 'layout_gate': 'passed'}
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('Could not inspect the AI Product CV PDF; do not mark it prepared') from exc


def verify_strategy_cv(path):
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ValueError('CV review needs pypdf installed; do not mark this CV prepared without a PDF check') from exc

    try:
        pages = PdfReader(str(Path(path))).pages
        if len(pages) != 2:
            raise ValueError('Strategy CV must be exactly two pages')
        second = pages[1]
        height = float(second.mediabox.height)
        if height <= 0:
            raise ValueError('Strategy CV has an invalid second page')
        lines = {}

        def visit(text, cm, _tm, _font, _size):
            if not text.strip():
                return
            y = round(float(cm[5]), 1)
            if 0 < y < height:
                lines[y] = lines.get(y, 0) + len(text.strip())

        second.extract_text(visitor_text=visit)
        lower_lines = [y for y, characters in lines.items() if y <= height * 0.18 and characters >= 20]
        if len(lower_lines) < 3:
            raise ValueError('Strategy CV second page is underfilled; revise verified wording and visually review both pages')
        return {'page_count': 2, 'second_page_lower_content_lines': len(lower_lines), 'second_page_last_text_y_pt': min(lines), 'layout_gate': 'passed'}
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('Could not inspect the Strategy CV PDF; do not mark it prepared') from exc
