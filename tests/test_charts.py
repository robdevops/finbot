"""Charts, tested three ways that survive restyling:
  1. image sanity: a real 1280x800 PNG, drawn, with nothing touching the edges (no clipped text)
  2. contracts: blue/red by sign, row order, titles and sort order, captured from what is handed to matplotlib
  3. one golden image per chart type, compared with a tolerance. Refresh after an intended restyle with:
		 UPDATE_GOLDEN=1 python -m unittest tests.test_charts
"""
import datetime, os, threading, unittest
from unittest import mock
import numpy as np
import pandas as pd
from PIL import Image
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from tests.common import *

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'golden')
BG, BLUE, RED = (0x14, 0x18, 0x1f), (0x39, 0x87, 0xe5), (0xfb, 0x71, 0x85)
SKY = (0xff, 0xe6, 0x6d) # the shorts chart's yellow, and the deeper yellow of its sun rays
RAY = (0xff, 0xd2, 0x3f)
SHORTS_BG = (SKY, RAY)

MIXED = [('AAA', 42), ('BBB', 17), ('CCC', 3), ('', None), ('DDD', -5), ('EEE', -30)]


def uncached(chart):
	"""render.draw(chart) without the cache, for the tests that have no fixture's temporary cache dir."""
	with mock.patch.object(config, 'prefs', dataclasses.replace(config.prefs, cache=False)):
		return render.draw(chart)


def decode(buf):
	"""A PNG buffer as an RGB image."""
	buf.seek(0)
	return Image.open(buf).convert('RGB')


def price_rows(days=120):
	"""A made-up price history of `days` days, wavy and rising, as a line chart's (date, close) rows."""
	return tuple((str(datetime.date(2026, 1, 1) + datetime.timedelta(days=i)), 100 + 12 * np.sin(i / 9) + i * 0.15)
		for i in range(days))


def line(rows, title='Apple Inc (AAPL) 120 days', subtitle='164.12 USD   ▲ 6.96%', change=6.96):
	"""A line chart of these rows."""
	return render.Chart('line', title, subtitle, rows, change=change)


def compare_rows():
	"""Three made-up price series over the same 120 days, as a compare chart's rows."""
	days = [str(day.date()) for day in pd.date_range('2026-01-01', periods=120)]
	return tuple((name, tuple(zip(days, 100 + np.cumsum(np.sin(np.arange(120) / k) + drift))))
		for name, k, drift in (('AAA', 7, 0.2), ('BBB', 11, -0.1), ('CCC', 5, 0.05)))


def bars(rows, title='T', subtitle='', **kwargs):
	"""A bar chart of these rows, drawn."""
	return render.draw_bars(render.Chart('bars', title, subtitle, tuple(rows), **kwargs))


def shorts(rows, threshold=15):
	"""The shorts pictogram of these rows, drawn."""
	return render.draw_shorts(render.Chart('shorts', rows=tuple(rows), threshold=threshold))


CHARTS = {
	'hbar_mixed': lambda: bars(MIXED, 'Price movement 5.0%, 5 Sep - 5 Oct 2026', 'subtitle here'),
	'price_line': lambda: render.draw_line(line(price_rows())),
	'compare_lines': lambda: render.draw_compare(render.Chart('compare', 'Compare 120 days', 'subtitle here',
		compare_rows())),
	'shorts': lambda: shorts([('GME', 47.3), ('AMC', 32.1), ('TSLA', 21.6), ('AAPL', 15.2)]),
	'pie': lambda: render.draw_pie(render.Chart('pie', 'Rob by industry', '4 industries',
		(('Software', 41.0), ('Banks', 23.5), ('Mining', 12.0), ('Other', 8.0)))),
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
	def check_image(self, buf, name, bg=BG, edge_clean=True):
		"""Fail unless buf is a 1280x800 PNG that is not blank, starts with the background, and (edge_clean) draws
		nothing on its edges, where clipped text or bars would show."""
		image = decode(buf)
		self.assertEqual(image.size, (1280, 800), name)
		pixels = np.asarray(image)
		self.assertGreater(len({tuple(p) for p in pixels.reshape(-1, 3)[::97]}), 8, f'{name} looks blank')
		self.assertGreater(pixels.std(), 5, f'{name} looks blank')
		allowed = bg if isinstance(bg[0], tuple) else (bg,)
		self.assertIn(tuple(int(c) for c in pixels[0, 0]), allowed, name)
		if not edge_clean: # the shorts beach draws its sea right to the edge
			return
		edge = np.concatenate([pixels[:3].reshape(-1, 3), pixels[-3:].reshape(-1, 3), pixels[:, :3].reshape(-1, 3),
			pixels[:, -3:].reshape(-1, 3)])
		self.assertTrue((edge == bg).all(), f'{name}: something is drawn on the image edge (clipped text or bars?)')

	def test_each_chart_type(self):
		"""Every chart type draws a sane image."""
		for name, make in CHARTS.items():
			with self.subTest(chart=name):
				if name == 'shorts':
					self.check_image(make(), name, bg=SHORTS_BG, edge_clean=False)
				else:
					self.check_image(make(), name)

	def test_edge_case_rows(self):
		"""Rows that broke charts before (one, all zero, forty, long labels, huge or tiny values) draw sane images."""
		for name, rows in EDGE_ROWS.items():
			with self.subTest(rows=name):
				self.check_image(bars(rows, 'Title', 'sub'), name)
				self.check_image(uncached(render.Chart('bars', 'Title', rows=tuple(rows))), name + '/drawn')

	def test_zoomed_axis(self):
		"""A bar chart with a narrow x range (ratings, 1 to 5) draws sane images, wide labels and many rows included."""
		self.check_image(bars([('AAA', 1.2), ('BBB', 3.4)], 'Ratings', xlim=(0.9, 4.0)), 'zoomed')
		self.check_image(bars([('WWWWWWWW', 1.2), ('MMM', 3.4)], 'Ratings', xlim=(0.9, 4.0)), 'zoomed wide labels')
		self.check_image(bars([(f'T{i}', 1 + i / 10) for i in range(15)], 'Ratings', xlim=(0.9, 3.0)), 'zoomed 15 rows')

	def test_shorts_chart_sizes_and_verdicts(self):
		"""The shorts pictogram draws 1 to 45 rows and a long label; each tier of short interest gets its verdict."""
		for n in (1, 5, 45):
			rows = [(f'T{i}', 60.0 - i) for i in range(n)]
			self.check_image(uncached(render.Chart('shorts', rows=tuple(rows), threshold=15)), f'shorts {n} rows',
				bg=SHORTS_BG, edge_clean=False)
		self.check_image(shorts([('A VERY LONG LABEL', 15.0), ('B', 0.4)]), 'shorts long label and tiny value',
			bg=SHORTS_BG, edge_clean=False)
		tiers = [(0, 'board shorts'), (4.9, 'board shorts'), (5, 'cargo shorts'), (10, 'boxers'), (15, 'gym shorts'),
			(20, 'cutoffs'),
				 (30, 'short shorts'), (40, 'daisy dukes'), (50, 'hot pants'), (60, 'speedos'),
				 (70, 'budgie smugglers'),
				 (80, 'just a belt'), (90, 'never nudes'), (200, 'never nudes')]
		self.assertEqual([render.shorts_verdict(p) for p, _ in tiers], [name for _, name in tiers])

	def test_bar_graph_has_top_and_bottom(self):
		"""The top-and-bottom bar chart draws a sane image."""
		self.check_image(uncached(render.Chart('bars', 'Top and bottom', rows=(('AAA', 9), ('', None), ('ZZZ', -9)))),
			'top and bottom')

	def test_flat_and_tiny_price_series(self):
		"""A flat price line and one of two points draw sane images."""
		flat = tuple((str(datetime.date(2026, 1, 1) + datetime.timedelta(days=i)), 5.0) for i in range(10))
		self.check_image(render.draw_line(line(flat, 'Flat', '5.00 USD   ■ 0%', 0)), 'flat price')
		self.check_image(render.draw_line(line(price_rows(2), 'Two points')), 'two points')

	def test_a_long_title_is_shrunk_to_fit(self):
		"""A title longer than the chart is wide is shrunk to fit, on every chart that has one: it ran off the edge."""
		title = 'Top 15 tracked stocks by negative forward pe ratio (7+ analysts), and a few more words besides'
		self.check_image(bars(MIXED, title), 'long title')
		self.check_image(render.draw_line(line(price_rows(), title)), 'long line title')


class DrawingLock(unittest.TestCase):
	"""Charts asked for from several threads at once are drawn one at a time (render._drawn)."""

	def test_charts_asked_for_at_once_all_finish(self):
		"""Six charts asked for from six threads at once all finish, whole."""
		pie = lambda title: render.Chart('pie', title, rows=(('a', 1.0), ('b', 2.0)))
		draws = [lambda i=i: render.draw_pie(pie(f't{i}')) for i in range(4)]
		draws += [lambda: bars(MIXED), lambda: uncached(render.Chart('bars', 'T', rows=tuple(MIXED)))]
		images = {}
		threads = [threading.Thread(target=lambda n=n, draw=draw: images.__setitem__(n, draw()))
			for n, draw in enumerate(draws)]
		for thread in threads:
			thread.start()
		for thread in threads:
			thread.join(120)
		self.assertEqual(sorted(images), list(range(6)), 'a chart did not finish')
		self.assertTrue(all(decode(image).size == (1280, 800) for image in images.values()))

	def test_one_chart_function_may_call_another(self):
		"""The lock is re-entrant: a drawn function that calls another drawn one finishes."""
		inner = render._drawn(lambda: 'drawn')
		self.assertEqual(render._drawn(inner)(), 'drawn')


class Contracts(unittest.TestCase):
	def capture_bars(self, rows, **kwargs):
		"""The y positions, widths and colours draw_bars hands to matplotlib for these rows."""
		calls = []
		real = Axes.barh
		def spy(ax, y, width, *a, **k):
			"""Record a barh call, then draw it."""
			calls.append({'y': list(y), 'width': list(width), 'color': list(k.get('color', []))})
			return real(ax, y, width, *a, **k)
		with mock.patch.object(Axes, 'barh', spy):
			bars(rows, **kwargs)
		return calls[0]

	def capture_text(self, make):
		"""Every text make() puts on the figure."""
		texts = []
		real = Figure.text
		def spy(fig, x, y, s, *a, **k):
			"""Record a text call, then draw it."""
			texts.append(s)
			return real(fig, x, y, s, *a, **k)
		with mock.patch.object(Figure, 'text', spy):
			make()
		return texts

	def test_bars_are_blue_when_positive_and_red_when_negative(self):
		"""Gains (and zero) are blue, losses red."""
		drawn = self.capture_bars([('A', 3), ('B', 0), ('C', -2)])
		self.assertEqual(drawn['color'], ['#3987e5', '#3987e5', '#fb7185'])

	def test_first_row_is_on_top_and_spacers_are_skipped(self):
		"""The first row is drawn at the top (the y axis is inverted), and a blank spacer row gets no bar."""
		drawn = self.capture_bars(MIXED)
		self.assertEqual(drawn['width'], [42, 17, 3, -5, -30])
		self.assertEqual(drawn['y'], [0, 1, 2, 4, 5]) # row 3 is the blank spacer
		calls = []
		real = Axes.set_ylim
		with mock.patch.object(Axes, 'set_ylim', lambda ax, *a, **k: (calls.append(a), real(ax, *a, **k))[1]):
			bars(MIXED)
		self.assertTrue(any(len(a) == 2 and a[0] > a[1] for a in calls),
			'y axis must be inverted so row 0 is drawn first (top)')

	def test_pixels_follow_the_sign_of_the_data(self):
		"""The drawn image is blue for gains and red for losses, in proportion to the rows."""
		def count(rows):
			"""(blue pixels, red pixels) in the bar chart of rows."""
			pixels = np.asarray(decode(bars(rows))).reshape(-1, 3)
			return (pixels == BLUE).all(axis=1).sum(), (pixels == RED).all(axis=1).sum()
		blue, red = count([('A', 5), ('B', 3)])
		self.assertGreater(blue, 1000); self.assertEqual(red, 0)
		blue, red = count([('A', -5), ('B', -3)])
		self.assertEqual(blue, 0); self.assertGreater(red, 1000)
		blue, red = count([('A', 5), ('B', -3)])
		self.assertGreater(blue, 1000); self.assertGreater(red, 1000)

	def test_session_tints_the_background(self):
		"""Mid-session tints the background faint green, pre-market faint yellow; close and the default stay plain."""
		corner = lambda session: tuple(np.asarray(decode(bars(MIXED, session=session)))[2, 2][:3])
		plain, close, mid, pre = corner(None), corner('close'), corner('midsession'), corner('premarket')
		self.assertEqual(plain, (0x14, 0x18, 0x1f))
		self.assertEqual(close, plain) # at close stays untinted
		self.assertTrue(mid[1] > mid[0] and mid[1] > plain[1]) # green
		# yellow: red and green channels both lead blue
		self.assertTrue(pre[0] > plain[0] and pre[1] > plain[1] and pre[0] > pre[2] and pre[1] > pre[2])
		self.assertLess(max(abs(int(a) - int(b)) for a, b in zip(pre, plain)), 20) # subtle

	def test_longer_bar_is_drawn_longer(self):
		"""A bar four times as long is drawn over twice as long."""
		pixels = np.asarray(decode(bars([('A', 40), ('B', 10)])))
		blue_rows = np.where((pixels == BLUE).all(axis=2).any(axis=1))[0]
		top_band, bottom_band = pixels[blue_rows[0]], pixels[blue_rows[-1]]
		self.assertGreater((top_band == BLUE).all(axis=1).sum(), 2 * (bottom_band == BLUE).all(axis=1).sum())

	def test_titles_are_drawn(self):
		"""The title and subtitle appear on the bar chart, and on the price line, which works out no change itself."""
		texts = self.capture_text(lambda: bars(MIXED, 'My Title', 'My subtitle'))
		self.assertIn('My Title', texts)
		self.assertIn('My subtitle', texts)
		texts = self.capture_text(lambda: render.draw_line(line(price_rows())))
		self.assertEqual(texts, ['Apple Inc (AAPL) 120 days', '164.12 USD   ▲ 6.96%'])

	def test_price_line_colour_follows_the_change_it_shows(self):
		"""The price line and its subtitle are green for the change it shows rising, red falling, grey for none: the
		change the caption gives, not one worked out from the first and last closes."""
		def line_colour(change):
			"""The colour of the subtitle of a falling price line that shows this change."""
			texts = []
			real = Figure.text
			def spy(fig, x, y, s, *a, **k):
				"""Record a text and its colour, then draw it."""
				texts.append((s, k.get('color')))
				return real(fig, x, y, s, *a, **k)
			with mock.patch.object(Figure, 'text', spy):
				render.draw_line(line(price_rows()[::-1], subtitle='sub', change=change))
			return dict(texts)['sub']
		self.assertEqual(line_colour(6.96), '#34d399') # up: green
		self.assertEqual(line_colour(-3), '#fb7185') # down: red
		self.assertEqual(line_colour(0), '#9aa4b2') # flat


class ReportChartInputs(FinbotCase):
	"""What the reports hand to the chart: sort order, titles and dates, taken from the real report code."""

	def run_report(self, call):
		"""Run call() and return the first chart spec it handed render.draw."""
		captured, real = [], render.draw
		self.patch(render, 'draw', lambda chart: captured.append(chart) or real(chart))
		call()
		self.assertTrue(captured, 'no chart was drawn')
		return captured[0]

	def test_over_forty_bars_keep_both_ends_with_a_gap(self):
		"""A bar chart of over 40 rows keeps the first 20 and the last 20, a gap between them; the shorts pictogram,
		over 24, the first and last 12, with the same gap (it used to drop the middle without a mark)."""
		rows = render.trimmed(render.Chart('bars', 'T', rows=tuple((f'T{i}', i) for i in range(50)))).rows
		self.assertEqual((len(rows), rows[20], rows[0][0], rows[-1][0]), (41, ('', None), 'T0', 'T49'))
		rows = render.trimmed(render.Chart('shorts', rows=tuple((f'T{i}', 60 - i) for i in range(30)))).rows
		self.assertEqual((len(rows), rows[12], rows[11][0], rows[13][0]), (25, ('', None), 'T11', 'T18'))
		self.assertEqual(render.trimmed(render.Chart('pie', rows=(('a', 1.0),) * 50)).rows, (('a', 1.0),) * 50)

	def test_a_chart_is_drawn_once(self):
		"""The same spec, for another chat or a later run, is read back from the cache, not drawn again."""
		calls, real = [], render.RENDERERS['pie']
		self.patch(render, 'RENDERERS', {**render.RENDERERS, 'pie': lambda chart: calls.append(chart) or real(chart)})
		chart = render.Chart('pie', 'T', rows=(('a', 1.0), ('b', 2.0)))
		first, second = render.draw(chart).read(), render.draw(chart).read()
		self.assertEqual((len(calls), first[:4]), (1, b'\x89PNG'))
		self.assertEqual(first, second)

	def test_price_top_lists_best_first_then_worst(self):
		""".price top: the ten best, best first, a spacer, then the ten worst, worst first, as in the caption."""
		chart = self.run_report(lambda: self.command('.price top 7d'))
		values = [v for _, v in chart.rows if v is not None]
		top, bottom = values[:10], values[10:]
		self.assertEqual(top, sorted(top, reverse=True))
		self.assertEqual(bottom, sorted(bottom)) # the worst performer comes first, like the caption's second list
		self.assertGreater(min(top), max(bottom))
		self.assertIn(None, [v for _, v in chart.rows]) # spacer between the two lists

	def test_price_threshold_chart_is_sorted_and_titled_with_the_threshold(self):
		""".price 5%: the chart is sorted best first and its title names the threshold."""
		chart = self.run_report(lambda: self.command('.price 5%'))
		values = [v for _, v in chart.rows if v is not None]
		self.assertEqual(values, sorted(values, reverse=True))
		self.assertIn('5', chart.title)

	def test_price_over_a_period_has_a_dated_title(self):
		""".price 7d: the chart's title gives the dates covered."""
		chart = self.run_report(lambda: self.command('.price 7d'))
		self.assertRegex(chart.title, r'\d{1,2} \w{3} - \d{1,2} \w{3} \d{4}') # 28 Sep - 5 Oct 2026

	def test_performance_is_sorted_by_percent(self):
		""".performance 7d: the chart is sorted best first."""
		chart = self.run_report(lambda: self.command('.performance 7d'))
		values = [v for _, v in chart.rows if v is not None]
		self.assertEqual(values, sorted(values, reverse=True))

	def test_shorts_is_sorted_and_carries_the_threshold(self):
		""".shorts: the pictogram gets the stocks over the threshold, most shorted first, and the threshold."""
		chart = self.run_report(lambda: self.command('.shorts'))
		values = [v for _, v in chart.rows]
		self.assertEqual((chart.kind, values), ('shorts', sorted(values, reverse=True)))
		self.assertTrue(all(v > chart.threshold for v in values))


class GoldenImages(unittest.TestCase):
	"""One reference image per chart type. Tolerant on purpose: compares 160x100 thumbnails, so font anti-aliasing and
	minor matplotlib differences pass, while changed colours, layout, bar sizes or missing text do not."""
	TOLERANCE = 2.0 # mean absolute difference, in 0-255 grey levels, of the 160x100 thumbnails

	@staticmethod
	def thumb(image):
		"""The 160x100 thumbnail that is compared, and stored as the golden image."""
		return image.resize((160, 100), Image.LANCZOS) # goldens are stored at this size too: a few KB each, not 100 KB

	def check(self, name):
		"""Compare a chart's thumbnail with its golden image (written instead with UPDATE_GOLDEN=1, or when missing)."""
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

	def test_hbar_mixed(self):
		"""The bar chart, gains and losses with a spacer, matches its golden image."""
		self.check('hbar_mixed')

	def test_price_line(self):
		"""The price line matches its golden image."""
		self.check('price_line')

	def test_shorts(self):
		"""The shorts pictogram matches its golden image."""
		self.check('shorts')

	def test_compare_lines(self):
		"""The compare chart matches its golden image."""
		self.check('compare_lines')

	def test_pie(self):
		"""The pie matches its golden image."""
		self.check('pie')


if __name__ == '__main__':
	unittest.main()
