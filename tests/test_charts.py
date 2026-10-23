"""Charts, tested three ways that survive restyling:
  1. image sanity: a real 1280x800 PNG, drawn, with nothing touching the edges (no clipped text)
  2. contracts: blue/red by sign, row order, titles and sort order, captured from what is drawn on the canvas
  3. one golden image per chart type, compared with a tolerance. Refresh after an intended restyle with:
		 UPDATE_GOLDEN=1 python -m unittest tests.test_charts
"""
import datetime, itertools, math, os, re, subprocess, sys, tempfile, threading, unittest
from unittest import mock
from PIL import Image, ImageChops, ImageStat
from tests.common import *

GOLDEN = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'golden')
BG, BLUE, RED = (0x14, 0x18, 0x1f), (0x39, 0x87, 0xe5), (0xfb, 0x71, 0x85)
SKY = (0xff, 0xe6, 0x6d) # the shorts chart's yellow, and the deeper yellow of its sun rays
RAY = (0xff, 0xd2, 0x3f)
SHORTS_BG = (SKY, RAY)

MIXED = [('AAA', 42), ('BBB', 17), ('CCC', 3), ('', None), ('DDD', -5), ('EEE', -30)]


def uncached(chart):
	"""render.draw(chart) without the cache, for the tests that have no fixture's temporary cache dir."""
	with mock.patch.object(config, 'settings', dataclasses.replace(config.settings, cache=False)):
		return render.draw(chart)


def decode(buf):
	"""A PNG buffer as an RGB image."""
	buf.seek(0)
	return Image.open(buf).convert('RGB')


def price_rows(days=120):
	"""A made-up price history of `days` days, wavy and rising, as a line chart's (date, close) rows."""
	return tuple((str(datetime.date(2026, 1, 1) + datetime.timedelta(days=i)), 100 + 12 * math.sin(i / 9) + i * 0.15)
		for i in range(days))


def line(rows, title='Apple Inc (AAPL) 120 days', subtitle='164.12 USD   ▲ 6.96%', change=6.96):
	"""A line chart of these rows."""
	return render.Chart('line', title, subtitle, rows, change=change)


def compare_rows():
	"""Three made-up price series over the same 120 days, as a compare chart's rows."""
	days = [str(datetime.date(2026, 1, 1) + datetime.timedelta(days=i)) for i in range(120)]
	return tuple((name, tuple(zip(days, (100 + total for total in itertools.accumulate(math.sin(i / k) + drift
		for i in range(120)))))) for name, k, drift in (('AAA', 7, 0.2), ('BBB', 11, -0.1), ('CCC', 5, 0.05)))


def bars(rows, title='T', subtitle='', **kwargs):
	"""A bar chart of these rows, drawn."""
	return render.draw_bars(render.Chart('bars', title, subtitle, tuple(rows), **kwargs))


def colours(image):
	"""How many pixels of each colour an image has: {(red, green, blue): count}."""
	return {colour: count for count, colour in image.getcolors(image.width * image.height)}


def shorts(rows, threshold=15):
	"""The shorts pictogram of these rows, drawn."""
	return render.draw_shorts(render.Chart('shorts', rows=tuple(rows), threshold=threshold))


CHARTS = {
	'hbar_mixed': lambda: bars(MIXED, 'Price movement 5.0%, 5 Sep - 5 Oct 2026', 'subtitle here'),
	'price_line': lambda: render.draw_line(line(price_rows())),
	'compare_lines': lambda: render.draw_compare(render.Chart('compare', 'Compare 120 days', 'subtitle here',
		compare_rows())),
	'shorts': lambda: shorts([('GME', 47.3), ('AMC', 32.1), ('TSLA', 21.6), ('AAPL', 15.2)]),
	'treemap': lambda: render.draw_treemap(render.Chart('treemap', 'SueSMSF treemap by industry',
		'17 industries, 36 holdings', (
		('Semiconductors', (('NVDA', 15.8), ('ASML', 6.4), ('AMD', 5.4), ('TSM', 4.5), ('SITM', 2.9), ('AIP', 1.9),
			('AXE', 0.5))),
		('Packaged Software', (('PLTR', 8.7), ('CRWD', 5.6), ('S', 3.4), ('YOU', 2.2), ('QSI', 1.0), ('WRK', 0.8),
			('CLBT', 0.6), ('NXT', 0.3))),
		('Investment Trusts/Mutual Funds', (('NVDL', 6.6), ('QLD', 3.9), ('VTS', 1.8), ('XLK', 1.0))),
		('Engineering & Construction', (('GNP', 5.9),)), ('Services to the Health Industry', (('PME', 5.6),)),
		('Precious Metals', (('FRS', 1.8), ('AIS', 1.6), ('GOLD', 0.3))),
		('Internet Software/Services', (('GOOGL', 3.4),)),
		('Other', (('SPCX', 1.4), ('ONDS', 1.4), ('WDC', 1.0), ('AIRJ', 0.9), ('MAD', 0.8), ('AMPX', 0.8),
			('NET', 0.8), ('MAP', 0.5), ('RKLB', 0.5)))))),
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
	def check_image(self, buf, name, bg=BG, edge_clean=True, size=(1280, 800), edge=3):
		"""Fail unless buf is a PNG of this size (1280x800) that is not blank, starts with the background, and
		(edge_clean) draws nothing in `edge` pixels at its edges, where clipped text or bars would show."""
		image = decode(buf)
		self.assertEqual(image.size, size, name)
		self.assertGreater(len(colours(image)), 8, f'{name} looks blank')
		self.assertGreater(max(ImageStat.Stat(image).stddev), 5, f'{name} looks blank')
		allowed = bg if isinstance(bg[0], tuple) else (bg,)
		self.assertIn(image.getpixel((0, 0)), allowed, name)
		if not edge_clean: # the shorts beach draws its sea right to the edge
			return
		width, height = image.size
		border = [image.crop(box) for box in ((0, 0, width, edge), (0, height - edge, width, height),
			(0, 0, edge, height), (width - edge, 0, width, height))]
		self.assertTrue(all(colours(strip) == {bg: strip.width * strip.height} for strip in border),
			f'{name}: something is drawn on the image edge (clipped text or bars?)')

	def test_each_chart_type(self):
		"""Every chart type draws a sane image."""
		for name, make in CHARTS.items():
			with self.subTest(chart=name):
				if name == 'shorts':
					self.check_image(make(), name, bg=SHORTS_BG, edge_clean=False)
				elif name == 'treemap':
					self.check_image(make(), name, edge=2)
				else:
					self.check_image(make(), name)

	def test_edge_case_rows(self):
		"""Rows that broke charts before (one, all zero, forty, long labels, huge or tiny values) draw sane images."""
		for name, rows in EDGE_ROWS.items():
			with self.subTest(rows=name):
				self.check_image(bars(rows, 'Title', 'sub'), name)
				self.check_image(uncached(render.Chart('bars', 'Title', rows=tuple(rows))), name + '/drawn')

	def test_a_long_bar_chart_grows_taller_and_stays_sane(self):
		"""Past 40 rows a bar chart's image grows taller, each row as tall as at 40, and draws as sanely."""
		rows = [(f'T{i}', (i - 30) * 1.5) for i in range(60)]
		self.check_image(bars(rows, 'Title', 'sub'), 'sixty rows', size=(1280, 1200))

	def test_zoomed_axis(self):
		"""A bar chart with a narrow x range (ratings, 1 to 5) draws sane images, wide labels and many rows included."""
		self.check_image(bars([('AAA', 1.2), ('BBB', 3.4)], 'Ratings', xlim=(0.9, 4.0)), 'zoomed')
		self.check_image(bars([('WWWWWWWW', 1.2), ('MMM', 3.4)], 'Ratings', xlim=(0.9, 4.0)), 'zoomed wide labels')
		self.check_image(bars([(f'T{i}', 1 + i / 10) for i in range(15)], 'Ratings', xlim=(0.9, 3.0)), 'zoomed 15 rows')

	def test_red_rows_draw_in_red(self):
		"""Positive bars in red_rows are drawn in the falling colour, the others in blue."""
		rows = [('AAA', 1.2), ('', None), ('BBB', 4.4)]
		plain = bars(rows, 'Ratings', xlim=(0.9, 4.6)).getvalue()
		red = bars(rows, 'Ratings', xlim=(0.9, 4.6), red_rows=(2,)).getvalue()
		self.assertNotEqual(plain, red)

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
		draws = [lambda i=i: bars((('a', 1.0), ('b', 2.0)), f't{i}') for i in range(4)]
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

	def test_a_chart_hands_its_memory_back(self):
		"""After each chart, drawn or failed, the memory it drew in goes back to the system (glibc's malloc_trim): the
		bot stayed some 30 MB larger after its first charts."""
		trimmed = []
		with mock.patch.object(render, '_trim', lambda: trimmed.append):
			render._drawn(lambda: None)()
			with self.assertRaises(ZeroDivisionError):
				render._drawn(lambda: 1 / 0)()
		self.assertEqual(trimmed, [0, 0])
		self.assertIn(render._trim()(0), (0, 1)) # glibc's, or the stand-in without it


class Contracts(unittest.TestCase):
	def capture(self, method, make):
		"""The arguments of each call make() makes to this method of the canvas, as it draws."""
		calls, real = [], getattr(render._Canvas, method)
		def spy(canvas, *args, **kwargs):
			"""Record a call, then draw it."""
			calls.append(args)
			return real(canvas, *args, **kwargs)
		with mock.patch.object(render._Canvas, method, spy):
			make()
		return calls

	def capture_bars(self, rows, **kwargs):
		"""The bars draw_bars draws for these rows, in the order drawn: (left, top, right, bottom, colour)."""
		return [args[:5] for args in self.capture('rect', lambda: bars(rows, **kwargs))
			if args[4] in (render.BAR_UP, render.DOWN)]

	def test_bars_are_blue_when_positive_and_red_when_negative(self):
		"""Gains (and zero) are blue, losses red."""
		drawn = self.capture_bars([('A', 3), ('B', 0), ('C', -2)])
		self.assertEqual([bar[4] for bar in drawn], ['#3987e5', '#3987e5', '#fb7185'])

	def test_first_row_is_on_top_and_spacers_are_skipped(self):
		"""The first row is drawn at the top, a blank spacer row gets no bar, and each bar is as long as its value, from
		the zero line, to its right for a gain and to its left for a loss."""
		drawn = self.capture_bars(MIXED)
		tops = [top for _, top, _, _, _ in drawn]
		self.assertGreater(tops[1], tops[0]) # down the image: the first row on top
		self.assertEqual([round((top - tops[0]) / (tops[1] - tops[0]), 6) for top in tops], [0, 1, 2, 4, 5]) # 3: spacer
		lengths = [right - left for left, _, right, _, _ in drawn]
		self.assertEqual([round(length / lengths[0] * 42, 6) for length in lengths], [42, 17, 3, -5, -30])
		self.assertEqual(len({left for left, _, _, _, _ in drawn}), 1) # every bar starts at the zero line

	def test_pixels_follow_the_sign_of_the_data(self):
		"""The drawn image is blue for gains and red for losses, in proportion to the rows."""
		def count(rows):
			"""(blue pixels, red pixels) in the bar chart of rows."""
			counts = colours(decode(bars(rows)))
			return counts.get(BLUE, 0), counts.get(RED, 0)
		blue, red = count([('A', 5), ('B', 3)])
		self.assertGreater(blue, 1000); self.assertEqual(red, 0)
		blue, red = count([('A', -5), ('B', -3)])
		self.assertEqual(blue, 0); self.assertGreater(red, 1000)
		blue, red = count([('A', 5), ('B', -3)])
		self.assertGreater(blue, 1000); self.assertGreater(red, 1000)

	def test_session_tints_the_background(self):
		"""Mid-session tints the background faint green, pre-market faint yellow; close and the default stay plain."""
		corner = lambda session: decode(bars(MIXED, session=session)).getpixel((2, 2))
		plain, close, mid, pre = corner(None), corner('close'), corner('midsession'), corner('premarket')
		self.assertEqual(plain, (0x14, 0x18, 0x1f))
		self.assertEqual(close, plain) # at close stays untinted
		self.assertTrue(mid[1] > mid[0] and mid[1] > plain[1]) # green
		# yellow: red and green channels both lead blue
		self.assertTrue(pre[0] > plain[0] and pre[1] > plain[1] and pre[0] > pre[2] and pre[1] > pre[2])
		self.assertLess(max(abs(int(a) - int(b)) for a, b in zip(pre, plain)), 20) # subtle

	def test_longer_bar_is_drawn_longer(self):
		"""A bar four times as long is drawn over twice as long."""
		image = decode(bars([('A', 40), ('B', 10)]))
		blue = [count for count in (colours(image.crop((0, y, image.width, y + 1))).get(BLUE, 0)
			for y in range(image.height)) if count]
		self.assertGreater(blue[0], 2 * blue[-1]) # the first row's band, and the last's

	def test_titles_are_drawn(self):
		"""The title and subtitle appear on the bar chart, and on the price line, which works out no change itself."""
		texts = [args[2] for args in self.capture('text', lambda: bars(MIXED, 'My Title', 'My subtitle'))]
		self.assertIn('My Title', texts)
		self.assertIn('My subtitle', texts)
		texts = [args[2] for args in self.capture('text', lambda: render.draw_line(line(price_rows())))]
		self.assertIn('Apple Inc (AAPL) 120 days', texts)
		self.assertEqual([text for text in texts if '%' in text], ['164.12 USD   ▲ 6.96%'])

	def test_price_line_colour_follows_the_change_it_shows(self):
		"""The price line and its subtitle are green for the change it shows rising, red falling, grey for none: the
		change the caption gives, not one worked out from the first and last closes."""
		def line_colour(change):
			"""The colour of the subtitle of a falling price line that shows this change."""
			drawn = self.capture('text', lambda: render.draw_line(line(price_rows()[::-1], subtitle='sub',
				change=change)))
			return {args[2]: args[4] for args in drawn}['sub']
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

	def test_a_bar_chart_keeps_every_row_and_the_shorts_both_ends(self):
		"""A bar chart keeps every row, however many: its image grows instead (the caption is cut, so the chart must
		show them all); the shorts pictogram, a scene of a fixed size, keeps the first and last 12 of over 24, a gap
		between."""
		chart = render.Chart('bars', 'T', rows=tuple((f'T{i}', i) for i in range(50)))
		self.assertEqual(render.trimmed(chart).rows, chart.rows)
		self.assertEqual(decode(render.draw_bars(chart)).size, (1280, 1000))
		rows = render.trimmed(render.Chart('shorts', rows=tuple((f'T{i}', 60 - i) for i in range(30)))).rows
		self.assertEqual((len(rows), rows[12], rows[11][0], rows[13][0]), (25, ('', None), 'T11', 'T18'))

	def test_a_chart_is_drawn_once(self):
		"""The same spec, for another chat or a later run, is read back from the cache, not drawn again."""
		calls, real = [], render.RENDERERS['treemap']
		draw = lambda chart: calls.append(chart) or real(chart)
		self.patch(render, 'RENDERERS', {**render.RENDERERS, 'treemap': draw})
		chart = render.Chart('treemap', f'T {time.time()}', rows=(('G', (('a', 1.0), ('b', 2.0))),))
		first, second = render.draw(chart).read(), render.draw(chart).read()
		self.assertEqual((len(calls), first[:4]), (1, b'\x89PNG'))
		self.assertEqual(first, second)

	def test_a_drawn_chart_is_kept_until_cleanup(self):
		"""A chart drawn is read back however long ago it was drawn (a spec's image never goes stale): it was drawn
		again once older than cache_seconds."""
		calls, real = [], render.RENDERERS['treemap']
		self.patch(render, 'RENDERERS', {**render.RENDERERS, 'treemap': lambda chart: calls.append(chart) or
			real(chart)})
		chart = render.Chart('treemap', f'T {time.time()}', rows=(('G', (('a', 1.0), ('b', 2.0))),))
		render.draw(chart)
		[drawn] = Path(config.env.cache_dir).glob('finbot_chart_*.png')
		old = time.time() - config.settings.cache_seconds - 86400
		os.utime(drawn, (old, old))
		render.draw(chart)
		self.assertEqual(len(calls), 1)

	def test_a_label_too_wide_is_cut_short_to_fit(self):
		"""A treemap's group name too wide for its block is cut short with an ellipsis, measured as it is drawn; where
		not even a letter fits, there is none (_Canvas.fitted)."""
		canvas = render._Canvas(10, 10, '#000000')
		wide = canvas.measure('Packaged Software', 8, bold=True)
		self.assertEqual(canvas.fitted('Packaged Software', 8, wide, bold=True), 'Packaged Software')
		cut = canvas.fitted('Packaged Software', 8, wide / 2, bold=True)
		self.assertTrue(cut.endswith('…') and canvas.measure(cut, 8, bold=True) <= wide / 2, cut)
		self.assertIsNone(canvas.fitted('Packaged Software', 8, 5, bold=True))

	def test_movers_top_lists_best_first_then_worst(self):
		""".movers top: the ten best, best first, a spacer, then the ten worst, the worst last."""
		chart = self.run_report(lambda: self.command('.movers top 7d'))
		values = [v for _, v in chart.rows if v is not None]
		top, bottom = values[:10], values[10:]
		self.assertEqual(top, sorted(top, reverse=True))
		self.assertEqual(bottom, sorted(bottom, reverse=True)) # the worst performer is last
		self.assertGreater(min(top), max(bottom))
		self.assertIn(None, [v for _, v in chart.rows]) # spacer between the two lists

	def test_movers_threshold_chart_is_sorted_and_titled_with_the_threshold(self):
		""".movers 5%: the chart is sorted best first and its title names the threshold."""
		chart = self.run_report(lambda: self.command('.movers 5%'))
		values = [v for _, v in chart.rows if v is not None]
		self.assertEqual(values, sorted(values, reverse=True))
		self.assertIn('5', chart.title)

	def test_every_chart_gives_its_date_or_dates_in_its_subtitle(self):
		"""Every chart's subtitle ends with the date it shows (5 Oct 2026), or the dates it spans (28 Sep - 5 Oct
		2026), which its title leaves to it."""
		captured, real = [], render.draw
		self.patch(render, 'draw', lambda chart: captured.append(chart) or real(chart))
		commands = ('.movers 5%', '.session', '.movers 7d', '.movers 30d top', '.performance 7d', '.price T1 T2 1y',
			'.treemap Rob', '.shorts', '.buy & sell', '.pe', '.beta')
		for text in commands:
			self.command(text)
		self.assertEqual(len(captured), len(commands))
		day = r'\d{1,2} (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
		for text, chart in zip(commands, captured):
			with self.subTest(text=text, subtitle=chart.subtitle):
				self.assertRegex(chart.subtitle, rf'(, |   |^)({day}( \d{{4}})? - )?{day} \d{{4}}$')
				self.assertNotRegex(chart.title, day)
		spans = [chart.subtitle.rpartition(', ')[2] for chart in captured[2:5]]
		self.assertTrue(all(' - ' in span for span in spans), spans) # 28 Sep - 5 Oct 2026

	def test_performance_is_sorted_by_name(self):
		""".performance 7d: the portfolios by name, in any case, whatever their gains, then the two benchmarks: the
		list and the chart in the same order."""
		self.patch(sharesight, '_portfolios', lambda seconds=None: [{'name': name, 'id': i} for i, name in
			enumerate(('super', 'Rob', 'kids', 'Bonds'), 1)])
		gains = {1: '9.5', 2: '-3.25', 3: '0.5', 4: '12'}
		self.patch(sharesight, '_performance', lambda pid, days=None, seconds=None:
			{'capital_gain_percent': gains[pid], 'holdings': []})
		chart = self.run_report(lambda: self.command('.performance 7d'))
		names = ['Bonds', 'kids', 'Rob', 'super', 'S&P 500', 'NASDAQ 100']
		self.assertEqual([label for label, _ in chart.rows], names)
		self.assertEqual([value for _, value in chart.rows][:4], [12.0, 0.5, -3.25, 9.5])
		payload, _ = performance.report(TELEGRAM, 7)
		self.assertEqual([re.search(r'>([^<]+)</a>', line).group(1) for line in payload[1:]], names)

	def test_shorts_is_sorted_and_carries_the_threshold(self):
		""".shorts: the pictogram gets the stocks over the threshold, most shorted first, and the threshold."""
		chart = self.run_report(lambda: self.command('.shorts'))
		values = [v for _, v in chart.rows]
		self.assertEqual((chart.kind, values), ('shorts', sorted(values, reverse=True)))
		self.assertTrue(all(v > chart.threshold for v in values))


class WithoutPandas(unittest.TestCase):
	def test_every_chart_draws_with_pandas_numpy_and_matplotlib_blocked(self):
		"""Every kind of chart draws in a process that can import none of pandas, numpy and matplotlib: Pillow draws
		them, from plain dates and floats."""
		code = ('import sys\nfrom tests import test_charts\nfor draw in test_charts.CHARTS.values(): draw()\n'
			'print(sorted(test_charts.CHARTS))')
		with tempfile.TemporaryDirectory() as data:
			stubs = Path(data, 'stubs')
			stubs.mkdir()
			for name in ('pandas', 'numpy', 'matplotlib'):
				(stubs / f'{name}.py').write_text('raise ImportError("blocked by the test")\n')
			env = bare_environment()
			env.update(DATA_DIR=data, PYTHONPATH=str(stubs))
			out = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=env, capture_output=True, text=True,
				timeout=120)
		self.assertEqual(out.stdout.strip().splitlines()[-1:], [str(sorted(CHARTS))], out.stderr)


@unittest.skipUnless(render._font_file(False), "DejaVu Sans, which the golden images are drawn in, is not installed")
class GoldenImages(unittest.TestCase):
	"""One reference image per chart type. Tolerant on purpose: compares 160x100 thumbnails, so font anti-aliasing and
	minor Pillow or FreeType differences pass, while changed colours, layout, bar sizes or missing text do not."""
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
		diff = sum(ImageStat.Stat(ImageChops.difference(thumb, Image.open(path).convert('RGB'))).mean) / 3
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

	def test_squarify_tiles_the_box_in_proportion(self):
		"""The tiles of a squarified layout stay in the box, don't overlap, and have areas in proportion."""
		values = [40.0, 25.0, 15.0, 10.0, 6.0, 3.0, 1.0]
		tiles = render._squarify(values, 10, 20, 300, 200)
		self.assertEqual(len(tiles), len(values))
		for (x, y, w, h), value in zip(tiles, values):
			self.assertAlmostEqual(w * h, value / sum(values) * 300 * 200, places=4)
			self.assertGreaterEqual(x, 10 - 1e-9)
			self.assertGreaterEqual(y, 20 - 1e-9)
			self.assertLessEqual(x + w, 310 + 1e-9)
			self.assertLessEqual(y + h, 220 + 1e-9)
		for i, (x, y, w, h) in enumerate(tiles):
			for x2, y2, w2, h2 in tiles[i + 1:]:
				self.assertTrue(x + w <= x2 + 1e-9 or x2 + w2 <= x + 1e-9 or y + h <= y2 + 1e-9 or y2 + h2 <= y + 1e-9)

	def test_treemap(self):
		"""The treemap matches its golden image."""
		self.check('treemap')


class BlankImage(unittest.TestCase):
	def test_the_picker_image_is_one_pixel(self):
		"""The image of a picker's answer without a chart is a 1x1 PNG, drawn holding the drawing lock as every chart
		is (render._drawn): a press draws it while charts are drawn in the background."""
		self.assertEqual(decode(render.blank()).size, (1, 1))
		self.assertTrue(hasattr(render.blank, '__wrapped__'), 'render.blank draws without the lock')


if __name__ == '__main__':
	unittest.main()
