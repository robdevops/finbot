"""Charts drawn as PNGs with Pillow, one at a time (_drawn). A report describes its chart as a Chart, which draw()
draws only for a chat that takes charts, and once: the image is cached by the spec's hash. A chart with curves or
slants is drawn at S times its size and reduced, which smooths their edges (_Canvas); its coordinates are pixels of the
1280x800 image (y down), and its text and line sizes are points at 200 dpi, as on the 6.4 by 4 inch page it once was."""
import dataclasses
import datetime
import functools
import hashlib
import io
import json
import math
import threading
from pathlib import Path
from lib import cache
from lib import config
from lib import formats
from lib import log


@dataclasses.dataclass(frozen=True)
class Chart:
	"""A chart not yet drawn, for draw(). kind 'bars': rows of (label, value), first on top, a (label, None) row a gap;
	'treemap': rows of (group, ((label, value), ...)); 'shorts': rows of (label,
	percent), and the threshold; 'line': rows of (date, close), a price line, and the change it shows; 'compare':
	rows of (label, ((date, close), ...)), two to eight price lines."""
	kind: str
	title: str = ''
	subtitle: str = ''
	rows: tuple = ()
	value_format: str = 'percent' # bars: how a value prints, a key of VALUE_FORMATS
	xlim: tuple = None # bars: the value axis, zoomed
	session: str = None # bars: 'midsession' or 'premarket' tints the background
	red_rows: tuple = () # bars: the indices of rows drawn in red though they are not below zero (the sells)
	threshold: float = None # shorts: the outrageous line
	change: float = None # line: the change shown, whose sign colours the line and its subtitle

	@property
	def drawable(self):
		"""Whether the chart is worth drawing: it has rows, and bars have more than one (a single bar says no more than
		the report's line does)."""
		if self.kind == 'bars':
			return sum(value is not None for _, value in self.rows) > 1
		return bool(self.rows)

VALUE_FORMATS = {'percent': lambda v: formats.signed_percent(round(v)),
	'percent2': lambda v: formats.signed_percent(v, 2), 'number': lambda v: f"{v:g}"}

PALETTE = ('#14181f', '#eef1f5', '#9aa4b2', '#2a313c') # charts: dark surface, ink, muted ink, grid lines
CATEGORIES = ('#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767') # the dark
# categorical slots, in fixed order; the green and red ones mean up and down, so lines that are neither leave them out
NEITHER_UP_NOR_DOWN = tuple(color for color in CATEGORIES if color not in ('#008300', '#e66767'))
COMPARE = (*NEITHER_UP_NOR_DOWN, '#2bb5d6', '#d9dde3') # .compare's eight lines: those slots, then a cyan, a pale gray
UP, DOWN, FLAT = '#34d399', '#fb7185', PALETTE[2] # a rise, a fall, neither: a price line's colour by its change
BAR_UP = CATEGORIES[0] # bars rise in blue; they fall in DOWN

W, H = 1280, 800 # Telegram's photo size, so a chart is never resampled
S = 2 # a chart with curves is drawn at S times its size, then reduced: Pillow draws shapes without anti-aliasing
SNAP = 6 # how far a palette PNG's entry may be from a colour drawn in, and be moved onto it (_exact)
PT = 200 / 72 # pixels to a point
FONTS = ('DejaVuSans.ttf', 'DejaVuSans-Bold.ttf') # the system's DejaVu Sans, matplotlib's font: charts look as they did
ASCENT, DESCENT = 0.76, 0.21 # its tallest letters and descenders, in ems: a line of text sits as matplotlib set it
SLANT = 0.2 # italic: the upright face sheared by 11 degrees, as its oblique is (not in fonts-dejavu-core)

_drawing = threading.RLock() # one chart at a time: Pillow's fonts are shared by every thread

def preload():
	"""For the bot, at start: load Pillow and find the fonts now, instead of when the first chart is asked for."""
	_font(10)
	_font(10, bold=True)

def _drawn(draw):
	"""A chart function that draws while no other thread does (it may call another such function), and then hands the
	memory it drew in back to the system."""
	@functools.wraps(draw)
	def alone(*args, **kwargs):
		"""Draw, holding the drawing lock."""
		with _drawing:
			try:
				return draw(*args, **kwargs)
			finally:
				_trim()(0)
	return alone

@functools.cache
def _trim():
	"""glibc's malloc_trim, which hands the free memory of the heap back to the system: a chart's canvas, some 20 MB,
	would otherwise stay with the process (glibc keeps what it last freed for the next time). A no-op without glibc."""
	try:
		import ctypes
		return ctypes.CDLL('libc.so.6').malloc_trim
	except (OSError, AttributeError):
		return lambda pad: 0

@functools.cache
def _font_file(bold):
	"""Where the system keeps DejaVu Sans (bold), found by name in its font folders; None where it has none (a pip
	install on macOS, say), and a note in the log: Pillow's own font stands in."""
	from PIL import ImageFont
	try:
		return ImageFont.truetype(FONTS[bold], 10).path
	except OSError:
		log.warn(f"charts: {FONTS[bold]} is not among the system's fonts, so Pillow's own font stands in (Debian:"
			" fonts-dejavu-core)")
		return None

@functools.lru_cache(maxsize=256)
def _sized(pixels, bold):
	"""The font, bold or not, `pixels` high."""
	from PIL import ImageFont
	path = _font_file(bold)
	return ImageFont.truetype(path, pixels) if path else ImageFont.load_default(pixels)

def _font(size, bold=False, scale=1):
	"""The font `size` points high, for an image `scale` times larger than the chart."""
	return _sized(round(size * PT * scale, 1), bold)

def _rgb(color):
	"""A colour (#rrggbb) as (red, green, blue)."""
	return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))

def _mixed(color, other, share):
	"""`color` (#rrggbb) with `share` of `other` mixed in."""
	return '#%02x%02x%02x' % tuple(round(a * (1 - share) + b * share) for a, b in zip(_rgb(color), _rgb(other)))

def _bezier(p0, p1, p2, p3, steps=16):
	"""Points along the cubic Bézier curve from p0 to p3 (p1 and p2 its control points), p0 left out."""
	return [tuple((1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t * t * c + t ** 3 * d
		for a, b, c, d in zip(p0, p1, p2, p3)) for t in (i / steps for i in range(1, steps + 1))]


class _Canvas:
	"""An image to draw a chart on, in its own pixels (y down): its shapes drawn `scale` times larger and reduced as it
	is saved (S for curves and slants; 1 where every edge is upright, which leaves nothing to smooth); its text then, at
	its own size (FreeType smooths text by itself, in half the time), above every shape."""

	def __init__(self, width, height, color, mode='RGB', scale=S):
		"""A canvas `width` by `height` pixels, filled with `color`."""
		from PIL import Image, ImageDraw
		self.width, self.height, self.scale = width, height, scale
		self.image = Image.new(mode, (round(width * scale), round(height * scale)), color)
		self.pen = ImageDraw.Draw(self.image) # a colour as it is: four times as fast as blending it
		self.blend = ImageDraw.Draw(self.image, 'RGBA') if mode == 'RGB' else self.pen # a colour with alpha blends in
		self.writing = [] # the lines of text, drawn as it is saved: (x, baseline, line, size, colour, bold, italic)
		self.colours = {color} # every colour drawn in, which the PNG keeps exact

	def png(self):
		"""The image at its own size, its text on it, as a PNG of 256 colours, rewound (or an upload sends nothing):
		every colour drawn in exact, and the blends at edges and in text each the nearest of the rest; a third the bytes
		of a PNG of every colour, made in half the time."""
		from PIL import Image, ImageDraw
		image = self.image.reduce(self.scale) if self.scale > 1 else self.image
		pen = ImageDraw.Draw(image)
		for x, baseline, line, size, color, bold, italic in self.writing:
			if italic:
				_slanted(image, x, baseline, line, size, color)
			else: # Pillow's own font has no bold: a stroke thickens it
				pen.text((x, baseline), line, fill=color, font=_font(size, bold), anchor='ls',
					stroke_width=1 if bold and not _font_file(True) else 0, stroke_fill=color)
		image = _exact(image.quantize(256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE), self.colours)
		buf = io.BytesIO()
		image.save(buf, format='png')
		buf.seek(0)
		return buf

	def line(self, points, color, width, rounded=True):
		"""A line through the points, `width` points wide, round at its joints and, `rounded`, at its ends. A joint is a
		disc as wide as the line, which a long history's thousands of segments, each shorter than that, do without."""
		self.colours.add(color)
		points = [(x * self.scale, y * self.scale) for x, y in points]
		w = width * PT * self.scale
		bends = len(points) > 2 and sum(map(math.dist, points, points[1:])) > w * (len(points) - 1)
		self.pen.line(points, fill=color, width=max(1, round(w)), joint='curve' if bends else None)
		if rounded:
			for x, y in (points[0], points[-1]):
				self.pen.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=color)

	def polygon(self, points, fill, outline=None, width=0):
		"""A polygon in `fill` (a colour, or (red, green, blue, alpha), which blends in), its outline `width` points
		wide, round at its corners and centred on its edges."""
		pen = self.blend if isinstance(fill, tuple) and len(fill) == 4 else self.pen
		self.colours.add(fill)
		pen.polygon([(x * self.scale, y * self.scale) for x, y in points], fill=fill)
		if outline:
			self.line([*points, points[0]], outline, width)

	def rect(self, x0, y0, x1, y1, fill, outline=None, width=0):
		"""A rectangle with corners (x0, y0) and (x1, y1), its outline `width` points wide, centred on its edges."""
		(x0, x1), (y0, y1) = sorted((x0, x1)), sorted((y0, y1))
		self.colours.add(fill)
		left, top, right, bottom = (round(v * self.scale) for v in (x0, y0, x1, y1))
		if right > left and bottom > top:
			self.pen.rectangle((left, top, right - 1, bottom - 1), fill=fill)
		if outline:
			h = width * PT / 2
			for box in ((x0 - h, y0 - h, x1 + h, y0 + h), (x0 - h, y1 - h, x1 + h, y1 + h),
					(x0 - h, y0 - h, x0 + h, y1 + h), (x1 - h, y0 - h, x1 + h, y1 + h)):
				self.rect(*box, outline)

	def ellipse(self, x, y, rx, ry, fill):
		"""An ellipse about (x, y), rx and ry its half widths across and down."""
		self.colours.add(fill)
		s = self.scale
		self.pen.ellipse(((x - rx) * s, (y - ry) * s, (x + rx) * s, (y + ry) * s), fill=fill)

	def circle(self, x, y, r, fill):
		"""A disc of radius r about (x, y)."""
		self.ellipse(x, y, r, r, fill)

	def dot(self, x, y, radius, color, edge, width):
		"""A marker about (x, y): a disc `radius` points across in `color`, its rim an `edge` `width` points wide."""
		self.circle(x, y, (radius + width / 2) * PT, edge)
		self.circle(x, y, (radius - width / 2) * PT, color)

	def paste(self, other, x, y, width=None):
		"""Another canvas's image (drawn at the same scale), its top left at (x, y), cut to `width` pixels from its left
		where given."""
		self.colours |= other.colours
		image = other.image
		if width is not None:
			image = image.crop((0, 0, max(1, round(width * self.scale)), image.height))
		self.image.paste(image, (round(x * self.scale), round(y * self.scale)), image)

	def measure(self, text, size, bold=False):
		"""How wide text `size` points high is, in pixels."""
		return _font(size, bold).getlength(text)

	def fitted(self, text, size, room, bold=False):
		"""text, `size` points high, cut short with an ellipsis until it is at most `room` pixels wide; None where not
		even its first letter and the ellipsis fit."""
		while len(text) > 2 and self.measure(text, size, bold) > room:
			text = text.rstrip('… ')[:-1].rstrip() + '…'
		return text if self.measure(text, size, bold) <= room else None

	def fit(self, size, texts, room, bold=False):
		"""The size, in points, that makes the widest of the texts at most `room` pixels wide: `size` if they fit."""
		widest = max((self.measure(text, size, bold) for text in texts), default=0)
		return size * room / widest if widest > room else size

	def text(self, x, y, text, size, color, ha='left', va='center', bold=False, italic=False):
		"""Text `size` points high at (x, y), placed as matplotlib places it (ha: left, center or right; va: top,
		center, center_baseline, baseline or bottom), its lines 1.3 lines apart, and drawn as the canvas is saved,
		above every shape. Returns the x of its right end."""
		em = size * PT
		if em < 0.5: # too small to read, or to make a font of
			return x
		self.colours.add(color)
		lines = text.split('\n')
		pitch = 1.3 * (ASCENT + DESCENT) * em
		below = (len(lines) - 1) * pitch # from the first line's baseline to the last's
		baseline = {'top': y + ASCENT * em, 'center': y + (ASCENT - DESCENT) * em / 2 - below / 2,
			'center_baseline': y + ASCENT * em / 2, 'baseline': y, 'bottom': y - DESCENT * em - below}[va]
		right = x
		for i, line in enumerate(lines):
			width = self.measure(line, size, bold)
			left = {'left': x, 'center': x - width / 2, 'right': x - width}[ha]
			self.writing.append((left, baseline + i * pitch, line, size, color, bold, italic))
			right = max(right, left + width)
		return right


def _exact(image, colours):
	"""A palette image with the entry nearest each colour drawn in (a colour with alpha blends, so it is none) moved
	onto that colour, where it is within SNAP: an entry is the average of the colours it stands for, which moves a
	chart's background, bars and ink a shade or two. The nearest are found by mapping a strip of the colours."""
	from PIL import Image, ImageColor
	exact = sorted({ImageColor.getrgb(c)[:3] if isinstance(c, str) else c for c in colours
		if isinstance(c, str) or len(c) == 3})
	strip = Image.new('RGB', (len(exact), 1))
	strip.putdata(exact)
	palette = image.getpalette()
	for colour, i in zip(exact, strip.quantize(palette=image, dither=Image.Dither.NONE).tobytes()):
		if max(abs(a - b) for a, b in zip(palette[3 * i:3 * i + 3], colour)) <= SNAP:
			palette[3 * i:3 * i + 3] = colour
	image.putpalette(palette)
	return image

def _slanted(image, x, baseline, text, size, color):
	"""Italic text on an image, its baseline from (x, baseline): drawn upright on a mask S times larger, sheared about
	its baseline as an oblique face slants, reduced, and painted through."""
	from PIL import Image, ImageDraw
	font = _font(size, scale=S)
	left, top, right, bottom = font.getbbox(text, anchor='ls')
	lean = math.ceil(SLANT * max(-top, bottom)) # how far the shear moves its top right, its bottom left
	whole = lambda v: S * math.ceil(v / S) # a length in the mask that is whole pixels once reduced
	ox, oy = whole(lean - left + 1), whole(1 - top) # the start of its baseline, in the mask
	mask = Image.new('L', (whole(ox + right + lean + 1), whole(oy + bottom + 1)))
	ImageDraw.Draw(mask).text((ox, oy), text, fill=255, font=font, anchor='ls')
	mask = mask.transform(mask.size, Image.Transform.AFFINE, (1, SLANT, -SLANT * oy, 0, 1, 0),
		Image.Resampling.BILINEAR).reduce(S)
	image.paste(color, (round(x - ox / S), round(baseline - oy / S)), mask)


class _Axes:
	"""Where a plot's values go on its canvas: its box, in pixels, and its limits on x and on y (either may run
	backwards: y as rows, the first on top)."""

	def __init__(self, box, xlim, ylim):
		"""A plot in the box (left, top, right, bottom), from xlim[0] to xlim[1] across and ylim[0] to ylim[1] up."""
		self.left, self.top, self.right, self.bottom = box
		self.xlim, self.ylim = xlim, ylim

	def x(self, value):
		"""The canvas x of a value on the x axis."""
		lo, hi = self.xlim
		return self.left + (value - lo) / (hi - lo) * (self.right - self.left)

	def y(self, value):
		"""The canvas y of a value on the y axis."""
		lo, hi = self.ylim
		return self.bottom - (value - lo) / (hi - lo) * (self.bottom - self.top)

	def at(self, x, y):
		"""The canvas point of a value pair."""
		return self.x(x), self.y(y)


def _ticks(lo, hi, most=5):
	"""The round values from lo to hi that an axis is marked at, at most `most` steps apart: the step is 1, 1.5, 2,
	2.5, 3, 4, 5, 6 or 8 times a power of ten, as matplotlib's MaxNLocator picks it, counted from a power of ten near
	the values where they span little of it."""
	raw, mean = (hi - lo) / most, (hi + lo) / 2
	power = 10 ** math.floor(math.log10(raw))
	step = next(power * times for times in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10) if power * times >= raw * (1 - 1e-9))
	offset = math.copysign(10 ** math.floor(math.log10(abs(mean))), mean) if abs(mean) >= 100 * (hi - lo) else 0
	return [offset + k * step
		for k in range(math.ceil((lo - offset) / step - 1e-9), math.floor((hi - offset) / step + 1e-9) + 1)]

def _date_ticks(lo, hi):
	"""The days (ordinals) that a date axis from lo to hi (ordinals, with fractions of a day) is marked on, two to five
	of them, as matplotlib's AutoDateLocator(minticks=2, maxticks=5) marks it: the first of January every few years,
	else the first of every few months, else days of the month."""
	start, end = (datetime.datetime.fromordinal(math.floor(v)) + datetime.timedelta(days=v % 1) for v in (lo, hi))
	months = (end.year - start.year) * 12 + end.month - start.month
	months -= (end.day, end.time()) < (start.day, start.time()) # the last month not a whole one
	if months >= 24:
		step = next((step for step in (1, 2, 4, 5, 10, 20, 40, 50) if months // 12 <= 4 * step), 100)
		ticks = [datetime.date(year, 1, 1) for year in range(start.year, end.year + 1) if year % step == 0]
	elif months >= 2:
		step = next(step for step in (1, 2, 3, 4, 6) if months <= 4 * step)
		ticks = [datetime.date(month // 12, month % 12 + 1, 1)
			for month in range(start.year * 12 + start.month - 1, end.year * 12 + end.month) if month % 12 % step == 0]
	else: # days of the month; under two days, each day
		days = (end - start).days
		step = next((step for step in (1, 2, 4, 7, 14) if days <= 4 * step), 14)
		on = {7: (1, 8, 15, 22), 14: (1, 15)}.get(step, range(1, 32, step))
		ticks = [day for day in (start.date() + datetime.timedelta(days=i) for i in range(days + 2)) if day.day in on]
	return [day.toordinal() for day in ticks if lo <= day.toordinal() <= hi]

def _date_label(day, days):
	"""A date mark's label on an axis `days` long: its year over 4 years, its month over 5 months, else its day."""
	return f'{day:%Y}' if days > 1460 else f'{day:%b %Y}' if days > 150 else f'{day.day} {day:%b}'

def _time_axes(canvas, right, first, last, ylim, label):
	"""The axes of a chart over time, from the day `first` to `last` (ordinals) and over ylim, out to `right`, with a
	left margin as wide as its value labels need: a horizontal grid line at each round value, labelled label(value),
	and the dates beneath. Returns the axes."""
	_, _, ink2, grid = PALETTE
	values = _ticks(*ylim)
	labels = [label(value) for value in values]
	left = max(0.075 * W, max(canvas.measure(text, 10) for text in labels) + 4 * PT + 18) # never clipped
	pad = (last - first) * 0.02 or 1
	axes = _Axes((left, 0.14 * H, right, 0.895 * H), (first - pad, last + pad), ylim)
	for value, text in zip(values, labels):
		canvas.line([(left, axes.y(value)), (right, axes.y(value))], grid, 0.6, rounded=False)
		canvas.text(left - 4 * PT, axes.y(value), text, 10, ink2, ha='right', va='center_baseline')
	for day in _date_ticks(*axes.xlim):
		x = axes.x(day)
		canvas.line([(x, axes.bottom), (x, axes.bottom + 3 * PT)], ink2, 0.8, rounded=False)
		canvas.text(x, axes.bottom + 9 * PT, _date_label(datetime.date.fromordinal(day), last - first), 10, ink2,
			ha='center', va='top')
	return axes

def _heading(canvas, title, subtitle='', subtitle_color=None):
	"""A chart's title at the top left, and its subtitle (if any) beneath, each shrunk to fit the width."""
	_, ink, ink2, _ = PALETTE
	room = 0.94 * canvas.width
	canvas.text(0.03 * W, 0.043 * H, title, canvas.fit(13, [title], room, bold=True), ink, bold=True)
	if subtitle:
		canvas.text(0.03 * W, 0.09 * H, subtitle, canvas.fit(8.5, [subtitle], room), subtitle_color or ink2)

def _plot_top(subtitle):
	"""Where a chart's plot starts, in pixels from the top: below its subtitle, or its title where it has none."""
	return (0.15 if subtitle else 0.11) * H

def _dated(rows):
	"""(date, close) rows, each date an ISO date or a datetime.date, as (the days as ordinals, the closes as floats)."""
	days = [day if isinstance(day, datetime.date) else datetime.date.fromisoformat(day) for day, _ in rows]
	return [day.toordinal() for day in days], [float(close) for _, close in rows]

@_drawn
def draw_line(chart):
	"""A price line (rows of (date, close)), coloured by the sign of the change it shows (green up, red down, grey
	neither: told apart by lightness as well as hue), its high and low marked: a 1280x800 PNG."""
	bg, ink, _, _ = PALETTE
	x, y = _dated(chart.rows)
	change = chart.change if chart.change is not None else y[-1] - y[0]
	color = UP if change > 0 else DOWN if change < 0 else FLAT
	canvas = _Canvas(W, H, bg)
	low, high = min(y), max(y)
	span = (high - low) or max(abs(high) * 0.02, 1e-9) # headroom above and below, so the labels never leave the plot
	axes = _time_axes(canvas, 0.96 * W, x[0], x[-1], (low - span * 0.22, high + span * 0.17),
		lambda v: f"{v:,.2f}".rstrip('0').rstrip('.')) # 66,000 / 1.5
	points = [axes.at(*point) for point in zip(x, y)]
	floor = axes.y(low - (high - low) * 0.15)
	canvas.polygon([*points, (points[-1][0], floor), (points[0][0], floor)], (*_rgb(color), 36)) # 14% opaque
	canvas.line(points, color, 1.6)
	canvas.dot(*points[-1], 2.5, color, bg, 1.5)

	def annotate(i, name, above):
		"""Label the point at index i, the high or the low, with its value and date, above or below it."""
		frac = (x[i] - x[0]) / max(x[-1] - x[0], 1)
		# anchored toward the inside of the plot, so it cannot run off either edge
		ha = 'left' if frac < 0.25 else 'right' if frac > 0.75 else 'center'
		px, py = points[i]
		day = datetime.date.fromordinal(x[i])
		canvas.text(px + {'left': 4, 'right': -4, 'center': 0}[ha] * PT, py + (-9 if above else 9) * PT,
			f"{name} {y[i]:,.2f}\n{day.day} {day:%b %Y}", 7, ink, ha=ha, va='bottom' if above else 'top')
		canvas.dot(px, py, 2, ink, bg, 1)
	imax, imin = y.index(high), y.index(low)
	if imax != len(y) - 1:
		annotate(imax, 'High', True)
	if imin != len(y) - 1 and imin != imax:
		annotate(imin, 'Low', False)

	_heading(canvas, chart.title, chart.subtitle, color)
	return canvas.png()

@_drawn
def draw_compare(chart):
	"""Rebased % change lines of two to eight price series (rows of (label, ((date, close), ...)), already cropped to
	the period), each labelled at its end: a 1280x800 PNG."""
	bg, ink, ink2, _ = PALETTE
	rebased = [] # (label, days, % change since the first close)
	for label, points in chart.rows:
		x, y = _dated(points)
		rebased.append((label, x, [(close / y[0] - 1) * 100 for close in y]))
	lo = min(min(y) for _, _, y in rebased)
	hi = max(max(y) for _, _, y in rebased)
	span = (hi - lo) or 1.0
	canvas = _Canvas(W, H, bg)
	axes = _time_axes(canvas, 0.795 * W, min(x[0] for _, x, _ in rebased), max(x[-1] for _, x, _ in rebased),
		(min(lo, 0) - span * 0.06, max(hi, 0) + span * 0.06), lambda v: f"{v:+,.0f}%" if v else "0%")
	canvas.line([(axes.left, axes.y(0)), (axes.right, axes.y(0))], _mixed(ink2, bg, 0.4), 0.8, rounded=False)
	for (label, x, y), color in zip(rebased, COMPARE):
		canvas.line([axes.at(*point) for point in zip(x, y)], color, 1.5)

	# direct end-labels in the right margin, spread so they never overlap
	ymin, ymax = axes.ylim
	ends = sorted(((y[-1], i) for i, (_, _, y) in enumerate(rebased)))
	pos = [(v - ymin) / (ymax - ymin) for v, _ in ends]
	gap = 0.065
	for i in range(1, len(pos)):
		pos[i] = max(pos[i], pos[i - 1] + gap)
	overflow = pos[-1] - 0.97
	if overflow > 0: # too high: shift the stack down, then re-enforce the floor
		pos = [p - overflow for p in pos]
		for i in range(len(pos) - 2, -1, -1):
			pos[i] = min(pos[i], pos[i + 1] - gap)
	width = axes.right - axes.left
	for (value, i), p in zip(ends, pos):
		label, x, _ = rebased[i]
		color = COMPARE[i]
		ty, tx = axes.bottom - p * (axes.bottom - axes.top), axes.left + 1.03 * width
		ex, ey = axes.at(x[-1], value) # the line's end: the label's leader stops 2pt short of it
		short = 2 * PT / max(math.hypot(tx - ex, ty - ey), 2 * PT)
		canvas.line([(tx, ty), (ex + (tx - ex) * short, ey + (ty - ey) * short)], _mixed(color, bg, 0.3), 0.7,
			rounded=False)
		side = 5 * PT / 2 # a 4pt square, and its 1pt edge
		canvas.rect(axes.left + 1.015 * width - side, ty - side, axes.left + 1.015 * width + side, ty + side, color)
		canvas.text(tx, ty, f"{label}  {value:+,.1f}%", 7.5, ink)
	_heading(canvas, chart.title, chart.subtitle)
	return canvas.png()

SESSION_TINTS = {'midsession': UP, 'premarket': '#facc15'} # subtle green / yellow wash; at close stays plain

@_drawn
def draw_bars(chart):
	"""Horizontal bars that mirror the caption list, first row on top, filling the whole 1280x800 canvas: blue for >= 0,
	red below, each row's label at the bar's base and its value (as value_format prints it) at the tip. Rows of (label,
	value); a (label, None) row is a gap. Past ROWS rows the image grows taller, each row as tall as at ROWS, so that
	every row is in it. red_rows are drawn red too. xlim zooms the value axis (bars then start at its left edge);
	session 'midsession' or 'premarket' washes the background green or yellow."""
	rows, subtitle, xlim, session = chart.rows, chart.subtitle, chart.xlim, chart.session
	value_fmt = VALUE_FORMATS[chart.value_format]
	bg, ink, ink2, _ = PALETTE
	if session in SESSION_TINTS:
		bg = _mixed(bg, SESSION_TINTS[session], 0.07)
	n = len(rows)
	canvas = _Canvas(W, H * max(1, n / ROWS), bg, scale=1) # upright edges alone: nothing to smooth
	top_edge = _plot_top(subtitle) # as far from the top in a taller image
	bottom_edge = canvas.height - 0.02 * H
	left, right = (0.14 if xlim else 0.04) * W, 0.96 * W # zoomed charts keep their labels outside the plot
	real = [(y, label, v) for y, (label, v) in enumerate(rows) if v is not None]
	values = [v for _, _, v in real]
	base = max(xlim[0], 0) if xlim else 0
	top, bottom = max(max(values), 0), min(min(values), 0)
	lo0 = xlim[0] if xlim else bottom
	hi0 = xlim[1] if xlim else top
	if hi0 <= lo0: # every value zero: give the axis a width, or the scale below divides by zero
		hi0 = lo0 + 1
	bar_px = 0.72 * (bottom_edge - top_edge) / n
	longest = max([len(str(label)) for _, label, _ in real] + [3])
	# text height follows the bar thickness
	size = max(5, min(30, min(bar_px * 1.3, 0.28 * (right - left) / (0.62 * longest)) / PT))
	if xlim: # zoomed charts put the labels in the left margin: shrink the text until the widest label fits there
		size = canvas.fit(size, [label for _, label, _ in real], left - 30) # leaves the 4pt gap before the bar base too
	label_width = [canvas.measure(label, size) for _, label, _ in real]
	value_width = [canvas.measure(value_fmt(v), size) for _, _, v in real]
	width = right - left
	lo, hi = lo0, hi0
	# the pixels-per-unit scale depends on the limits, which depend on the text beside the bars: settle it iteratively
	for _ in range(12):
		per_unit = width / (hi - lo)
		# room for the text outside the bars: each tip's value, and each base's label (zoomed charts keep those in the
		# left margin)
		new_lo, new_hi = lo0, hi0
		for (_, _, v), w, vw in zip(real, label_width, value_width):
			if v >= 0:
				new_hi = max(new_hi, v + (vw + 12) / per_unit)
				if not xlim:
					new_lo = min(new_lo, base - (w + 12) / per_unit)
			else:
				new_lo = min(new_lo, v - (vw + 12) / per_unit)
				if not xlim:
					new_hi = max(new_hi, base + (w + 12) / per_unit)
		if abs(new_lo - lo) < 1e-6 * (hi - lo) and abs(new_hi - hi) < 1e-6 * (hi - lo):
			break
		lo, hi = new_lo, new_hi
	axes = _Axes((left, top_edge, right, bottom_edge), (lo, hi), (n - 0.4, -0.6)) # first row on top
	clipped = lambda v: axes.x(min(max(v, lo), hi)) # a zoomed axis cuts the bars at its edge
	for y, _, v in real:
		canvas.rect(clipped(0), axes.y(y - 0.36), clipped(v), axes.y(y + 0.36),
			BAR_UP if v >= 0 and y not in chart.red_rows else DOWN)
	if not xlim:
		canvas.line([(axes.x(0), top_edge), (axes.x(0), bottom_edge)], ink2, 1.0, rounded=False)
	# each row's label sits beside the bar's base (left of the zero line for rising bars, right of it for falling ones),
	# its baseline half a cap height below the bar's centre, so the capitals are centred on the bar
	for y, label, v in real:
		baseline = axes.y(y) + 0.365 * size * PT
		side = 1 if v >= 0 else -1
		canvas.text(axes.x(base) - side * 4 * PT, baseline, label, size, ink, ha='right' if v >= 0 else 'left',
			va='baseline')
		canvas.text(axes.x(v) + side * 4 * PT, baseline, value_fmt(v), size, ink, ha='left' if v >= 0 else 'right',
			va='baseline')
	_heading(canvas, chart.title, subtitle)
	return canvas.png()

# five points each at the bottom
SHORTS_VERDICTS = ((5, 'board shorts'), (10, 'cargo shorts'), (15, 'boxers'), (20, 'gym shorts'),
	(30, 'cutoffs'), (40, 'short shorts'), (50, 'daisy dukes'), (60, 'hot pants'), (70, 'speedos'),
	(80, 'budgie smugglers'), (90, 'just a belt'),
	(float('inf'), 'never nudes')) # the extreme ones step in every 10 points

PAIR = 5 # the percent of shares shorted that a pair of shorts stands for

def shorts_verdict(percent):
	"""The more shorted, the shorter the shorts."""
	return next(name for limit, name in SHORTS_VERDICTS if percent < limit)

@_drawn
def draw_shorts(chart):
	"""Short interest as a pictogram: each row (label, percent), largest first, is a run of cartoon shorts, one pair per
	PAIR percent (the last pair cropped); a (label, None) row is a gap; the threshold is the outrageous line. Loud on
	purpose, and drawn in shapes, as colour emoji are no part of the font: a 1280x800 PNG."""
	rows, threshold = chart.rows, chart.threshold
	sky, ink, sea, foam, ray = '#ffe66d', '#1b1f3b', '#1ea7e1', '#b5e8ff', '#ffd23f'
	colors = ['#ff3d81', '#00b8a0', '#ff8a00', '#7a5cff', '#5bc215']
	rows = [(label if len(label) <= 10 else label[:9] + '…', value) for label, value in rows]
	canvas = _Canvas(W, H, sky)

	def pair(w, h, color, lw):
		"""A pair of shorts w by h on a canvas of its own, with a margin all round for its outline: (it, the margin)."""
		m = lw * PT
		stamp = _Canvas(w + 2 * m, h + 2 * m, (0, 0, 0, 0), 'RGBA')
		def P(px, py):
			"""A point of the pair's box, from fractions of its width and height."""
			return (m + px * w, m + py * h)
		belt = _mixed(color, '#000000', 0.3)
		stamp.polygon([P(0.04, 0.2), P(0.96, 0.2), P(1.0, 0.97), P(0.56, 0.97), P(0.5, 0.58), P(0.44, 0.97),
			P(0.0, 0.97)], color, ink, lw) # the legs
		stamp.rect(*P(0.04, 0.0), *P(0.96, 0.22), belt, ink, lw) # the waist
		for dx, dy in ((0.2, 0.5), (0.3, 0.78), (0.72, 0.5), (0.8, 0.78), (0.14, 0.8)): # polka dots
			stamp.circle(*P(dx, dy), 0.045 * w, 'white')
		stamp.rect(*P(0.47, 0.0), *P(0.53, 0.22), '#ffd23f', ink, lw * 0.6) # belt buckle
		return stamp, m

	# decor: a big sun in sunglasses whose rays run under everything to the edges, and the sea
	R = 100 # the sun's radius; it sits in the top right corner
	margin = 5 # gap between the sun and the top and right edges
	sx, sy, rays = W - R - margin, R + margin, 16
	tilt = math.radians(-1) # beams turned 1 degree counter-clockwise (angles run clockwise here, as y points down)
	for k in range(0, rays, 2): # every other wedge, so the rays alternate with the sky
		a0, a1 = k * 2 * math.pi / rays + tilt, (k + 1) * 2 * math.pi / rays + tilt
		canvas.polygon([(sx, sy), (sx + 2000 * math.cos(a0), sy + 2000 * math.sin(a0)),
			(sx + 2000 * math.cos(a1), sy + 2000 * math.sin(a1))], ray)

	top, bottom = 205, 726 # below the sun
	n = len(rows)
	row_h = min((bottom - top) / n, 110)
	top += ((bottom - top) - row_h * n) / 2 # few rows sit in the middle of the beach, not the top
	bottom = top + row_h * n
	size = max(6, min(18, row_h * 0.5 * 72 / 200 * 2))
	label_w = max(canvas.measure(str(label), size, bold=True) for label, _ in rows)
	x0 = 40 + label_w + 16
	room = 40 + 400 # right-hand text: percent and verdict
	max_icons = max(math.ceil(max(v for _, v in rows if v is not None) / PAIR), 1)
	icon_w = min((W - room - x0) / max_icons, row_h * 1.1 * 0.9, 120)
	icon_h = icon_w / 1.1
	lw = max(0.6, min(1.6, icon_w / 45))
	line_x = x0 + threshold / PAIR * icon_w
	dash, gap = 5 * 1.8 * PT, 4 * 1.8 * PT # the outrageous line's dashes, under the shorts
	for y in range(math.ceil((bottom - top + 12) / (dash + gap))):
		start = top - 12 + y * (dash + gap)
		canvas.line([(line_x, start), (line_x, min(start + dash, bottom))], ink, 1.8, rounded=False)

	def at(u, v):
		"""A point on the sun's face, in sun radii from its centre with y down, in the canvas's pixels."""
		return (sx + u * R, sy + v * R)
	canvas.circle(sx, sy, R, '#ffb000')
	for dx, dy, r, c in ((-0.05, -0.06, 0.93, '#ffb90a'), (-0.1, -0.12, 0.78, '#ffc21f'),
			(-0.16, -0.2, 0.55, '#ffcb35')): # fake gradient
		canvas.circle(*at(dx, dy), r * R, c)
	brown = '#5a3d37'
	for (u, v), w, h in (((-0.46, -0.07), 0.21, 0.25), ((0.31, -0.37), 0.20, 0.24)): # lopsided eyes
		canvas.ellipse(*at(u, v), w * R / 2, h * R / 2, brown)
	mouth = [(-0.47, 0.47), (0.73, 0.0), (0.75, 0.35), (0.45, 0.74), (0.1, 0.74), (-0.15, 0.74), (-0.42, 0.62),
		(-0.47, 0.47)]
	mc = (0.13, 0.37) # the mouth shrinks towards its middle
	mouth = [at(mc[0] + 0.65 * (u - mc[0]), mc[1] + 0.65 * (v - mc[1])) for u, v in mouth]
	canvas.polygon([*mouth[:2], *_bezier(*mouth[1:5]), *_bezier(*mouth[4:8])], '#2b2118')
	canvas.rect(0, 748, W, H, sea)
	for cx in range(0, W + 36, 36):
		canvas.circle(cx, 748, 19, foam)

	stamps = {}
	for i, (label, value) in enumerate(rows):
		if value is None: # the gap between the most shorted and the least
			continue
		cy = top + (i + 0.5) * row_h
		whole, frac = divmod(value / PAIR, 1)
		color = colors[i % len(colors)]
		if color not in stamps: # each colour's pair drawn once, every row's the same size
			stamps[color] = pair(icon_w * 0.92, icon_h, color, lw)
		stamp, m = stamps[color]
		for k in range(int(whole) + (1 if frac > 0.02 else 0)):
			cut = m + icon_w * 0.92 * frac if k == int(whole) else None
			canvas.paste(stamp, x0 + k * icon_w - m, cy - icon_h / 2 - m, cut)

	nose = [(-0.07, -0.35), (0.05, -0.26), (0.15, -0.13), (0.18, 0.0), (0.10, 0.10), (-0.03, 0.16)]
	mid = [sum(axis) / len(nose) for axis in zip(*nose)]
	nose = [(mid[0] + 0.62 * (u - mid[0]), mid[1] + 0.62 * (v - mid[1])) for u, v in nose] # dainty: a smaller squiggle
	pts = [nose[0], *nose, nose[-1]] # a Catmull-Rom spline through the points, so the squiggle is smooth: each of its
	# segments, p1 to p2, is the Bézier curve with these control points
	curve = [pts[1], *(point for p0, p1, p2, p3 in zip(pts, pts[1:], pts[2:], pts[3:])
		for point in _bezier(p1, tuple(b + (c - a) / 6 for a, b, c in zip(p0, p1, p2)),
			tuple(c - (d - b) / 6 for b, c, d in zip(p1, p2, p3)), p2, 11))]
	canvas.line([at(u, v) for u, v in curve], '#e07b1a', 2.6)

	canvas.text(40, 52, 'Shorts', 21, ink, bold=True)
	canvas.text(40, 104, ', '.join(filter(None, (f"each pair of shorts = {PAIR}% of shares shorted", chart.subtitle))),
		9.5, ink)
	for i, (label, value) in enumerate(rows):
		if value is None:
			continue
		cy = top + (i + 0.5) * row_h
		canvas.text(x0 - 14, cy, label, size, ink, ha='right', bold=True)
		# each verdict right after its own percentage, never off the image
		x = canvas.text(x0 + (value / PAIR) * icon_w + 14, cy, f"{round(value)}%", size, ink, bold=True) + 10
		verdict = shorts_verdict(round(value))
		canvas.text(x, cy, verdict, canvas.fit(size * 0.62, [verdict], W - 16 - x), ink, italic=True)
	canvas.text(W / 2, 784, 'past fashion not indicative of future fashion', 8, 'white', ha='center', italic=True)
	canvas.text(line_x, top - 18, f"{threshold:g}% outrageous line", 7.5, ink, ha='center', va='bottom', bold=True)
	return canvas.png()

def _worst(row, side):
	"""The worst aspect ratio among tiles of areas `row` laid along a side of length `side`."""
	total = sum(row)
	return max(max(side * side * area / (total * total), total * total / (side * side * area)) for area in row)

def _squarify(values, x, y, w, h):
	"""Tiles (x, y, w, h) filling the box, one per value (largest first), areas in proportion and as square as
	the squarified layout makes them."""
	scale = w * h / sum(values)
	areas = [value * scale for value in values]
	tiles, i = [], 0
	while i < len(areas):
		side = min(w, h)
		row, j = [areas[i]], i + 1
		while j < len(areas) and _worst(row + [areas[j]], side) <= _worst(row, side):
			row.append(areas[j])
			j += 1
		span = sum(row) / side
		offset = 0.0
		for area in row:
			length = area / span
			tiles.append((x, y + offset, span, length) if w >= h else (x + offset, y, length, span))
			offset += length
		if w >= h:
			x, w = x + span, w - span
		else:
			y, h = y + span, h - span
		i = j
	return tiles

@_drawn
def draw_treemap(chart):
	"""Treemap of (group, ((label, value), ...)) rows, largest group first: a block a group, in a colour of its own
	(the dark categorical slots in order, gray for 'Other') under its name, a tile a holding sized by value: a
	1280x800 PNG."""
	rows = chart.rows
	bg = PALETTE[0]
	canvas = _Canvas(W, H, bg, scale=1) # upright edges alone: nothing to smooth
	total = sum(value for _, held in rows for _, value in held) or 1.0
	top = _plot_top(chart.subtitle) # below the heading, as the other charts are
	box = _squarify([sum(value for _, value in held) for _, held in rows], 0, top, W, H - top) # 2px edges, with gaps
	n = 0
	for (label, held), (x, y, w, h) in zip(rows, box):
		color = '#6b7280' if label == 'Other' else CATEGORIES[n % len(CATEGORIES)]
		n += label != 'Other'
		x, y, w, h = x + 1, y + 1, w - 2, h - 2
		title = canvas.fitted(label, 8, w - 12, bold=True) if h > 60 else None # over a block with room for a row
		head = 22 if title else 0
		if title:
			canvas.text(x + 2, y + head / 2, title, 8, color, bold=True)
		tiles = _squarify([value for _, value in held], x, y + head, w, h - head)
		for k, ((name, value), (tx, ty, tw, th)) in enumerate(zip(held, tiles)):
			canvas.rect(tx + 1, ty + 1, tx + tw - 1, ty + th - 1, _mixed(color, bg, k % 3 * 0.14))
			share = f"{value / total * 100:.1f}%"
			if th > 34 and canvas.measure(name, 8) + 8 < tw: # its name where it fits, and its share below
				lines = name + (f"\n{share}" if th > 64 and canvas.measure(share, 8) + 8 < tw else '')
				canvas.text(tx + tw / 2, ty + th / 2, lines, 8, '#ffffff', ha='center')
	_heading(canvas, chart.title, chart.subtitle)
	return canvas.png()

@_drawn
def blank():
	"""A 1x1 PNG in the chart background: the image of a picker's answer that has no chart, whose message must stay a
	photo for a press to turn into a chart (a text message cannot become one)."""
	canvas = _Canvas(1, 1, PALETTE[0])
	return canvas.png()

@functools.cache
def _code_version():
	"""What else decides how a spec looks: this file, the Pillow release and the fonts found. Worked out at the first
	chart, as it loads Pillow."""
	import PIL
	drawn_by = f'{PIL.__version__} {_font_file(False)} {_font_file(True)}'
	return hashlib.sha1(Path(__file__).read_bytes() + drawn_by.encode()).hexdigest()[:8]

RENDERERS = {'bars': draw_bars, 'treemap': draw_treemap, 'shorts': draw_shorts, 'line': draw_line,
	'compare': draw_compare}
ROWS = 40 # bars: the rows a 1280x800 image has room for; more make it taller (draw_bars)
LIMITS = {'shorts': 24} # the rows a chart of a fixed size has room for

def trimmed(chart):
	"""The chart with no more rows than it has room for (LIMITS): over that, the first half and the last, a gap
	between."""
	limit = LIMITS.get(chart.kind)
	if not limit or len(chart.rows) <= limit:
		return chart
	return dataclasses.replace(chart, rows=(*chart.rows[:limit // 2], ('', None), *chart.rows[-(limit // 2):]))

def draw(chart):
	"""The chart's PNG, drawn once by the renderer of its kind. The image is cached by a hash of its spec (and of the
	drawing code), so a second chat, a scheduled run or a period button that shows the same thing reads it back; the
	same spec always draws the same image, so it is never stale."""
	if chart.kind not in RENDERERS:
		raise ValueError(f"unknown chart kind {chart.kind!r}")
	key = json.dumps([_code_version(), dataclasses.asdict(chart)], sort_keys=True, default=str)
	name = f"finbot_chart_{hashlib.sha1(key.encode()).hexdigest()[:20]}.png"
	if config.settings.cache and (image := cache.read_bytes(name, math.inf)): # kept until cleanup: it never goes stale
		return image
	image = RENDERERS[chart.kind](trimmed(chart))
	if config.settings.cache:
		cache.write_bytes(name, image)
		image.seek(0)
	return image
