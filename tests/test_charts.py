"""Charts, tested three ways that survive restyling:
  1. image sanity: a real 1280x800 PNG, drawn, with nothing touching the edges (no clipped text)
  2. contracts: blue/red by sign, row order, titles and sort order, captured from what is handed to matplotlib
  3. one golden image per chart type, compared with a tolerance. Refresh after an intended restyle with:
         UPDATE_GOLDEN=1 python -m unittest tests.test_charts
"""
import datetime, io, os, unittest
from unittest import mock
import numpy as np
import pandas as pd
from PIL import Image
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from tests.common import *

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'golden')
BG, BLUE, RED = (0x14, 0x18, 0x1f), (0x39, 0x87, 0xe5), (0xfb, 0x71, 0x85)

MIXED = [('AAA', 42), ('BBB', 17), ('CCC', 3), ('', None), ('DDD', -5), ('EEE', -30)]


def decode(buf):
    buf.seek(0)
    return Image.open(buf).convert('RGB')


def price_frame(days=120):
    dates = [datetime.date(2026, 1, 1) + datetime.timedelta(days=i) for i in range(days)]
    closes = [100 + 12 * np.sin(i / 9) + i * 0.15 for i in range(days)]
    return pd.DataFrame({'Date': dates, 'Close': closes})


def compare_series():
    index = pd.date_range('2026-01-01', periods=120)
    return [(name, pd.Series(100 + np.cumsum(np.sin(np.arange(120) / k) + drift), index=index))
            for name, k, drift in (('AAA', 7, 0.2), ('BBB', 11, -0.1), ('CCC', 5, 0.05))]


CHARTS = {
    'hbar_mixed': lambda: util.hbar_chart(MIXED, 'Price movement 5.0%, 5 Sep - 5 Oct 2026', 'subtitle here'),
    'price_line': lambda: util.graph(price_frame(), 'Apple Inc (AAPL)', 'USD'),
    'compare_lines': lambda: util.compare_graph(compare_series(), 'Compare 120 days', 'subtitle here'),
}
# inputs that have broken chart code before or are likely to: sizes, signs, long names, zeros, a single row
EDGE_ROWS = {
    'one_row': [('AAA', 5)],
    'one_negative': [('AAA', -5)],
    'all_positive': [(f'T{i}', i + 1) for i in range(15)],
    'all_negative': [(f'T{i}', -(i + 1)) for i in range(15)],
    'all_zero': [(f'T{i}', 0) for i in range(5)],
    'forty_rows': [(f'T{i}', (i - 20) * 1.5) for i in range(40)],
    'long_labels': [('A very long company name indeed (TICKER)', 12), ('Another equally long label here ok', -8)],
    'huge_values': [('AAA', 12345), ('BBB', -9876)],
    'tiny_values': [('AAA', 0.01), ('BBB', -0.02)],
}


class ImageSanity(unittest.TestCase):
    def check_image(self, buf, name):
        image = decode(buf)
        self.assertEqual(image.size, (1280, 800), name)
        pixels = np.asarray(image)
        self.assertGreater(len({tuple(p) for p in pixels.reshape(-1, 3)[::97]}), 8, f'{name} looks blank')
        self.assertGreater(pixels.std(), 5, f'{name} looks blank')
        np.testing.assert_array_equal(pixels[0, 0], BG, err_msg=name)
        edge = np.concatenate([pixels[:3].reshape(-1, 3), pixels[-3:].reshape(-1, 3), pixels[:, :3].reshape(-1, 3), pixels[:, -3:].reshape(-1, 3)])
        self.assertTrue((edge == BG).all(), f'{name}: something is drawn on the image edge (clipped text or bars?)')

    def test_each_chart_type(self):
        for name, make in CHARTS.items():
            with self.subTest(chart=name):
                self.check_image(make(), name)

    def test_edge_case_rows(self):
        for name, rows in EDGE_ROWS.items():
            with self.subTest(rows=name):
                self.check_image(util.hbar_chart(rows, 'Title', 'sub'), name)
                self.check_image(util.rows_chart(rows, 'Title'), name + '/rows_chart')

    def test_zoomed_axis_and_threshold(self):
        self.check_image(util.hbar_chart([('AAA', 1.2), ('BBB', 3.4)], 'Ratings', xlim=(0.9, 4.0)), 'zoomed')
        self.check_image(util.hbar_chart([('WWWWWWWW', 1.2), ('MMM', 3.4)], 'Ratings', xlim=(0.9, 4.0)), 'zoomed wide labels')
        self.check_image(util.hbar_chart([(f'T{i}', 1 + i / 10) for i in range(15)], 'Ratings', xlim=(0.9, 3.0)), 'zoomed 15 rows')
        self.check_image(util.hbar_chart(MIXED, 'Threshold', threshold=10), 'threshold')

    def test_bar_graph_has_top_and_bottom(self):
        self.check_image(util.bar_graph([('AAA', 9)], [('ZZZ', -9)], 'Top and bottom'), 'bar_graph')

    def test_flat_and_tiny_price_series(self):
        flat = pd.DataFrame({'Date': [datetime.date(2026, 1, 1) + datetime.timedelta(days=i) for i in range(10)], 'Close': [5.0] * 10})
        self.check_image(util.graph(flat, 'Flat', 'USD'), 'flat price')
        two = price_frame(2)
        self.check_image(util.graph(two, 'Two points', 'USD'), 'two points')


class Contracts(unittest.TestCase):
    def capture_bars(self, rows, **kwargs):
        calls = []
        real = Axes.barh
        def spy(ax, y, width, *a, **k):
            calls.append({'y': list(y), 'width': list(width), 'color': list(k.get('color', []))})
            return real(ax, y, width, *a, **k)
        with mock.patch.object(Axes, 'barh', spy):
            util.hbar_chart(rows, 'T', **kwargs)
        return calls[0]

    def capture_text(self, make):
        texts = []
        real = Figure.text
        def spy(fig, x, y, s, *a, **k):
            texts.append(s)
            return real(fig, x, y, s, *a, **k)
        with mock.patch.object(Figure, 'text', spy):
            make()
        return texts

    def test_bars_are_blue_when_positive_and_red_when_negative(self):
        bars = self.capture_bars([('A', 3), ('B', 0), ('C', -2)])
        self.assertEqual(bars['color'], ['#3987e5', '#3987e5', '#fb7185'])

    def test_first_row_is_on_top_and_spacers_are_skipped(self):
        bars = self.capture_bars(MIXED)
        self.assertEqual(bars['width'], [42, 17, 3, -5, -30])
        self.assertEqual(bars['y'], [0, 1, 2, 4, 5]) # row 3 is the blank spacer
        calls = []
        real = Axes.set_ylim
        with mock.patch.object(Axes, 'set_ylim', lambda ax, *a, **k: (calls.append(a), real(ax, *a, **k))[1]):
            util.hbar_chart(MIXED, 'T')
        self.assertTrue(any(len(a) == 2 and a[0] > a[1] for a in calls), 'y axis must be inverted so row 0 is drawn first (top)')

    def test_pixels_follow_the_sign_of_the_data(self):
        def count(rows):
            pixels = np.asarray(decode(util.hbar_chart(rows, 'T'))).reshape(-1, 3)
            return (pixels == BLUE).all(axis=1).sum(), (pixels == RED).all(axis=1).sum()
        blue, red = count([('A', 5), ('B', 3)])
        self.assertGreater(blue, 1000); self.assertEqual(red, 0)
        blue, red = count([('A', -5), ('B', -3)])
        self.assertEqual(blue, 0); self.assertGreater(red, 1000)
        blue, red = count([('A', 5), ('B', -3)])
        self.assertGreater(blue, 1000); self.assertGreater(red, 1000)

    def test_longer_bar_is_drawn_longer(self):
        pixels = np.asarray(decode(util.hbar_chart([('A', 40), ('B', 10)], 'T')))
        blue_rows = np.where((pixels == BLUE).all(axis=2).any(axis=1))[0]
        top_band, bottom_band = pixels[blue_rows[0]], pixels[blue_rows[-1]]
        self.assertGreater((top_band == BLUE).all(axis=1).sum(), 2 * (bottom_band == BLUE).all(axis=1).sum())

    def test_titles_are_drawn(self):
        texts = self.capture_text(lambda: util.hbar_chart(MIXED, 'My Title', 'My subtitle'))
        self.assertIn('My Title', texts)
        self.assertIn('My subtitle', texts)
        texts = self.capture_text(lambda: util.graph(price_frame(), 'Apple Inc (AAPL)', 'USD'))
        self.assertIn('Apple Inc (AAPL)', texts)
        self.assertTrue(any('over period' in t for t in texts))

    def test_price_line_colour_follows_direction(self):
        def line_colour(closes):
            frame = pd.DataFrame({'Date': [datetime.date(2026, 1, 1) + datetime.timedelta(days=i) for i in range(len(closes))], 'Close': closes})
            texts = []
            real = Figure.text
            with mock.patch.object(Figure, 'text', lambda fig, x, y, s, *a, **k: (texts.append((s, k.get('color'))), real(fig, x, y, s, *a, **k))[1]):
                util.graph(frame, 'T', 'USD')
            return next(color for s, color in texts if 'over period' in s)
        self.assertEqual(line_colour([1, 2, 3]), '#34d399') # up: green
        self.assertEqual(line_colour([3, 2, 1]), '#fb7185') # down: red
        self.assertEqual(line_colour([2, 3, 2]), '#9aa4b2') # flat


class ReportChartInputs(FinbotCase):
    """What the reports hand to the chart: sort order, titles and dates, taken from the real report code."""

    def run_report(self, call):
        captured = []
        real = util.hbar_chart
        def spy(rows, title, subtitle='', **kw):
            captured.append({'rows': list(rows), 'title': title, 'subtitle': subtitle})
            return real(rows, title, subtitle, **kw)
        self.patch(util, 'hbar_chart', spy)
        call()
        self.assertTrue(captured, 'no chart was drawn')
        return captured[0]

    def test_price_top_lists_best_first_then_worst(self):
        chart = self.run_report(lambda: self.command('.price top 7d'))
        values = [v for _, v in chart['rows'] if v is not None]
        top, bottom = values[:10], values[10:]
        self.assertEqual(top, sorted(top, reverse=True))
        self.assertEqual(bottom, sorted(bottom)) # the worst performer comes first, like the caption's second list
        self.assertGreater(min(top), max(bottom))
        self.assertIn(None, [v for _, v in chart['rows']]) # spacer between the two lists

    def test_price_threshold_chart_is_sorted_and_titled_with_the_threshold(self):
        chart = self.run_report(lambda: self.command('.price 5%'))
        values = [v for _, v in chart['rows'] if v is not None]
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertIn('5', chart['title'])

    def test_price_over_a_period_has_a_dated_title(self):
        chart = self.run_report(lambda: self.command('.price 7d'))
        self.assertRegex(chart['title'], r'\d{1,2} \w{3} - \d{1,2} \w{3} \d{4}') # 28 Sep - 5 Oct 2026

    def test_performance_is_sorted_by_percent(self):
        chart = self.run_report(lambda: self.command('.performance 7d'))
        values = [v for _, v in chart['rows'] if v is not None]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_shorts_is_sorted_and_titled(self):
        chart = self.run_report(lambda: self.command('.shorts'))
        values = [v for _, v in chart['rows'] if v is not None]
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertTrue(chart['title'])


class GoldenImages(unittest.TestCase):
    """One reference image per chart type. Tolerant on purpose: compares 160x100 thumbnails, so font anti-aliasing and
    minor matplotlib differences pass, while changed colours, layout, bar sizes or missing text do not."""
    TOLERANCE = 2.0 # mean absolute difference, in 0-255 grey levels, of the 160x100 thumbnails

    @staticmethod
    def thumb(image):
        return image.resize((160, 100), Image.LANCZOS) # goldens are stored at this size too: a few KB each, not 100 KB

    def check(self, name):
        thumb = self.thumb(decode(CHARTS[name]()))
        path = os.path.join(GOLDEN, name + '.png')
        if os.environ.get('UPDATE_GOLDEN') or not os.path.exists(path):
            os.makedirs(GOLDEN, exist_ok=True)
            thumb.save(path, optimize=True)
            if not os.environ.get('UPDATE_GOLDEN'):
                self.fail(f'{name}: no golden image existed, so one was written to {path}. Review it and commit it.')
            return
        diff = np.abs(np.asarray(thumb, dtype=float) - np.asarray(Image.open(path).convert('RGB'), dtype=float)).mean()
        self.assertLess(diff, self.TOLERANCE, f'{name} no longer matches tests/golden/{name}.png (diff {diff:.2f}). '
                        f'If the change is intended, run: UPDATE_GOLDEN=1 python -m unittest tests.test_charts')

    def test_hbar_mixed(self): self.check('hbar_mixed')
    def test_price_line(self): self.check('price_line')
    def test_compare_lines(self): self.check('compare_lines')


if __name__ == '__main__':
    unittest.main()
