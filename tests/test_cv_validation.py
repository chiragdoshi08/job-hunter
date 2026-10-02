"""The PDF gate must catch the original underfilled-page failure."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from hunter.cv_validation import verify_ai_cv, verify_strategy_cv


class Page:
    mediabox = SimpleNamespace(height=842)

    def __init__(self, positions):
        self.positions = positions

    def extract_text(self, visitor_text):
        for y in self.positions:
            visitor_text('Substantive verified career content', [1, 0, 0, 1, 0, y], None, None, 11)


class CVValidationTests(unittest.TestCase):
    def check(self, positions, count=2):
        reader = SimpleNamespace(pages=[Page([]), Page(positions)][:count])
        with patch('pypdf.PdfReader', return_value=reader):
            return verify_strategy_cv('/tmp/fixture.pdf')

    def test_full_second_page_passes(self):
        result = self.check([700, 300, 120, 90, 60, 30])
        self.assertEqual(result['layout_gate'], 'passed')
        self.assertEqual(result['second_page_lower_content_lines'], 4)

    def test_two_pages_but_underfilled_rejected(self):
        with self.assertRaisesRegex(ValueError, 'underfilled'):
            self.check([700, 600, 400, 265])

    def test_one_page_rejected(self):
        with self.assertRaisesRegex(ValueError, 'exactly two pages'):
            self.check([], count=1)

    def test_ai_cv_requires_one_readable_a4_page(self):
        page = SimpleNamespace(mediabox=SimpleNamespace(width=595.3, height=841.9), extract_text=lambda: 'Fixture Candidate ' * 50)
        with patch('pypdf.PdfReader', return_value=SimpleNamespace(pages=[page])):
            self.assertEqual(verify_ai_cv('/tmp/fixture.pdf')['page_count'], 1)
        with patch('pypdf.PdfReader', return_value=SimpleNamespace(pages=[page, page])):
            with self.assertRaisesRegex(ValueError, 'exactly one page'):
                verify_ai_cv('/tmp/fixture.pdf')


if __name__ == '__main__':
    unittest.main()
