"""Charts drawn as PNGs with matplotlib, one at a time (_drawn). A report describes its chart as a Chart, which draw()
draws only for a chat that takes charts, and once: the image is cached by the spec's hash."""
import dataclasses
import datetime
import functools
import hashlib
import importlib.metadata
import io
import json
import threading
from pathlib import Path
from lib import config # first: sets MPLCONFIGDIR before matplotlib is imported (lazily, by the chart functions)
from lib import cache
from lib import formats


@dataclasses.dataclass(frozen=True)
class Chart:
	"""A chart not yet drawn, for draw(). kind 'bars': rows of (label, value), first on top, a (label, None) row a gap;
	'pie': rows of (label, value); 'shorts': rows of (label, percent), and the threshold; 'line': rows of (date, close),
	a price line, and the change it shows; 'compare': rows of (label, ((date, close), ...)), two to six price lines."""
	kind: str
	title: str = ''
	subtitle: str = ''
	rows: tuple = ()
	value_format: str = 'percent' # bars: how a value prints, a key of VALUE_FORMATS
	xlim: tuple = None # bars: the value axis, zoomed
	session: str = None # bars: 'midsession' or 'premarket' tints the background
	threshold: float = None # shorts: the outrageous line
	change: float = None # line: the change shown, whose sign colours the line and its subtitle

VALUE_FORMATS = {'percent': lambda v: formats.signed_percent(round(v)),
	'percent2': lambda v: formats.signed_percent(v, 2), 'number': lambda v: f"{v:g}"}

def fit_left_margin(fig, ax, pad_px=18):
	"""Widen the left margin so the longest Y tick label is never clipped; the right edge stays put."""
	renderer = fig.canvas.get_renderer()
	fig.canvas.draw()
	widest = max((t.get_window_extent(renderer).width for t in ax.get_yticklabels() if t.get_text()), default=0)
	need = (widest + ax.yaxis.get_tick_padding() * fig.dpi / 72 + pad_px) / fig.bbox.width
	x0, y0, w, h = ax.get_position().bounds
	if need > x0:
		ax.set_position([need, y0, w - (need - x0), h])

def style_date_axis(ax, start, end, ink):
	"""Explicit date ticks: the format follows the span, and few enough ticks that they never collide."""
	import matplotlib.dates as mdates
	days = (end - start).days
	fmt = '%Y' if days > 1460 else '%b %Y' if days > 150 else '%-d %b'
	ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=2, maxticks=5)) # minticks=3 warns on a 2-day span
	ax.xaxis.set_major_formatter(mdates.DateFormatter(fmt))
	ax.tick_params(axis='x', colors=ink, labelsize=10, length=3, width=0.8, pad=6)

PALETTE = ('#14181f', '#eef1f5', '#9aa4b2', '#2a313c') # charts: dark surface, ink, muted ink, grid lines
CATEGORIES = ('#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767') # the dark
# categorical slots, in fixed order; the green and red ones mean up and down, so lines that are neither leave them out
NEITHER_UP_NOR_DOWN = tuple(color for color in CATEGORIES if color not in ('#008300', '#e66767'))
UP, DOWN, FLAT = '#34d399', '#fb7185', PALETTE[2] # a rise, a fall, neither: a price line's colour by its change
BAR_UP = CATEGORIES[0] # bars rise in blue; they fall in DOWN

_drawing = threading.RLock() # one chart at a time: matplotlib's caches are shared by every thread

def preload():
	"""For the bot, at start: import matplotlib now, instead of when the first chart is asked for."""
	import importlib
	for module in ('matplotlib.backends.backend_agg', 'matplotlib.dates', 'matplotlib.figure', 'matplotlib.patches',
			'matplotlib.path', 'matplotlib.ticker'):
		importlib.import_module(module)

def _drawn(draw):
	"""A chart function that draws while no other thread does (it may call another such function)."""
	@functools.wraps(draw)
	def alone(*args, **kwargs):
		"""Draw, holding the drawing lock."""
		with _drawing:
			return draw(*args, **kwargs)
	return alone

def _figure(facecolor):
	"""A 1280x800 figure (Telegram's photo size, so it is never resampled) and its Agg canvas."""
	from matplotlib.figure import Figure
	from matplotlib.backends.backend_agg import FigureCanvasAgg
	fig = Figure(figsize=(6.4, 4.0), dpi=200, facecolor=facecolor)
	return fig, FigureCanvasAgg(fig)

def _time_axes(fig, bg, width):
	"""The axes of a chart over time, `width` of the figure wide: the line chart's, and the compare chart's, whose end
	labels take the rest."""
	from matplotlib.ticker import MaxNLocator
	ax = fig.add_axes([0.075, 0.105, width, 0.755], facecolor=bg)
	ax.margins(x=0.02)
	ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
	return ax

def _style_time_axes(fig, ax, start, end):
	"""What the line charts share: a horizontal grid, no frame, muted ticks, and the date axis from start to end."""
	_, ink, ink2, grid = PALETTE
	ax.grid(axis='y', color=grid, linewidth=0.6)
	ax.set_axisbelow(True)
	for side in ax.spines.values():
		side.set_visible(False)
	ax.tick_params(colors=ink2, labelsize=10, length=0, pad=4)
	style_date_axis(ax, start, end, ink2)
	fit_left_margin(fig, ax)

def _shrink(texts, room):
	"""Shrink texts by one factor, so that the widest is at most `room` pixels wide (texts that fit stay as they are):
	the factor."""
	renderer = texts[0].figure.canvas.get_renderer()
	widest = max(text.get_window_extent(renderer).width for text in texts)
	factor = min(1.0, room / widest) if widest else 1.0
	for text in texts:
		text.set_fontsize(text.get_fontsize() * factor)
	return factor

def _heading(fig, title, subtitle='', subtitle_color=None):
	"""A chart's title at the top left, and its subtitle (if any) beneath, each shrunk to fit the width."""
	_, ink, ink2, _ = PALETTE
	room = 0.94 * fig.bbox.width
	_shrink([fig.text(0.03, 0.957, title, color=ink, fontsize=13, fontweight='bold', ha='left', va='center')], room)
	if subtitle:
		_shrink([fig.text(0.03, 0.910, subtitle, color=subtitle_color or ink2, fontsize=8.5, ha='left', va='center')],
			room)

def _dated(rows):
	"""(date, close) rows, each date an ISO date or a datetime.date, as (the dates as datetime.date, the closes as a
	numpy array): matplotlib takes both as they are."""
	import numpy as np
	dates = [day if isinstance(day, datetime.date) else datetime.date.fromisoformat(day) for day, _ in rows]
	return dates, np.array([float(close) for _, close in rows])

def _png(fig, facecolor):
	"""The figure as PNG bytes, rewound (or an upload sends nothing); not bbox_inches='tight': it alters 1280x800."""
	buf = io.BytesIO()
	fig.savefig(buf, format='png', facecolor=facecolor)
	buf.seek(0)
	return buf

@_drawn
def draw_line(chart):
	"""A price line (rows of (date, close)), coloured by the sign of the change it shows (green up, red down, grey
	neither: told apart by lightness as well as hue), its high and low marked: a 1280x800 PNG."""
	from matplotlib.ticker import FuncFormatter
	import matplotlib.dates as mdates
	import numpy as np
	bg, ink, ink2, grid = PALETTE
	x, y = _dated(chart.rows)
	change = chart.change if chart.change is not None else y[-1] - y[0]
	color = UP if change > 0 else DOWN if change < 0 else FLAT

	fig, _ = _figure(bg)
	ax = _time_axes(fig, bg, 0.885)
	ax.fill_between(x, y, y.min() - (y.max() - y.min()) * 0.15, color=color, alpha=0.14, linewidth=0)
	ax.plot(x, y, color=color, linewidth=1.6, solid_capstyle='round')
	ax.plot([x[-1]], [y[-1]], marker='o', markersize=5, color=color, markeredgecolor=bg, markeredgewidth=1.5,
		clip_on=False)

	# headroom above/below so annotations never leave the plot
	span = (y.max() - y.min()) or max(abs(y.max()) * 0.02, 1e-9)
	ax.set_ylim(y.min() - span * 0.22, y.max() + span * 0.17)
	ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.2f}".rstrip('0').rstrip('.'))) # 66,000 / 1.5
	_style_time_axes(fig, ax, x[0], x[-1])

	def annotate(i, name, above):
		"""Label the point at index i, the high or the low, with its value and date, above or below it."""
		xd, yv = x[i], y[i]
		frac = (mdates.date2num(xd) - mdates.date2num(x[0])) / max(mdates.date2num(x[-1]) - mdates.date2num(x[0]), 1)
		# anchor text toward the inside of the plot so it cannot run off either edge
		ha = 'left' if frac < 0.25 else 'right' if frac > 0.75 else 'center'
		dx = {'left': 4, 'right': -4, 'center': 0}[ha]
		ax.annotate(f"{name} {yv:,.2f}\n{xd:%-d %b %Y}", xy=(xd, yv), xytext=(dx, 9 if above else -9),
			textcoords='offset points', ha=ha, va='bottom' if above else 'top',
			fontsize=7, color=ink, linespacing=1.3, annotation_clip=False)
		ax.plot([xd], [yv], marker='o', markersize=4, color=ink, markeredgecolor=bg, markeredgewidth=1, zorder=5)
	imax, imin = int(np.argmax(y)), int(np.argmin(y))
	if imax != len(y) - 1:
		annotate(imax, 'High', True)
	if imin != len(y) - 1 and imin != imax:
		annotate(imin, 'Low', False)

	_heading(fig, chart.title, chart.subtitle, color)

	return _png(fig, bg)

@_drawn
def draw_compare(chart):
	"""Rebased % change lines of two to six price series (rows of (label, ((date, close), ...)), already cropped to the
	period), each labelled at its end: a 1280x800 PNG."""
	from matplotlib.ticker import FuncFormatter
	bg, ink, ink2, grid = PALETTE
	colors = NEITHER_UP_NOR_DOWN
	fig, _ = _figure(bg)
	ax = _time_axes(fig, bg, 0.72)
	rebased = [] # (label, dates, % change since the first close)
	for label, points in chart.rows:
		x, y = _dated(points)
		rebased.append((label, x, (y / y[0] - 1) * 100))
	ax.axhline(0, color=ink2, linewidth=0.8, alpha=0.6, zorder=1)
	for (label, x, y), color in zip(rebased, colors):
		ax.plot(x, y, color=color, linewidth=1.5, solid_capstyle='round', zorder=3)
	lo = min(y.min() for _, _, y in rebased)
	hi = max(y.max() for _, _, y in rebased)
	span = (hi - lo) or 1.0
	ax.set_ylim(min(lo, 0) - span * 0.06, max(hi, 0) + span * 0.06)
	ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:+,.0f}%" if v else "0%"))
	_style_time_axes(fig, ax, min(x[0] for _, x, _ in rebased), max(x[-1] for _, x, _ in rebased))

	# direct end-labels in the right margin, spread so they never overlap
	ymin, ymax = ax.get_ylim()
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
	for (value, i), p in zip(ends, pos):
		label, x, _ = rebased[i]
		color = colors[i]
		ax.plot([1.015], [p], marker='s', markersize=4, color=color, transform=ax.transAxes, clip_on=False, zorder=4)
		ax.annotate(f"{label}  {value:+,.1f}%", xy=(x[-1], value), xycoords='data', xytext=(1.03, p),
			textcoords='axes fraction', ha='left', va='center', fontsize=7.5, color=ink, annotation_clip=False,
			arrowprops=dict(arrowstyle='-', color=color, linewidth=0.7, alpha=0.7, shrinkA=0, shrinkB=2,
				relpos=(0, 0.5)))
	_heading(fig, chart.title, chart.subtitle)
	return _png(fig, bg)

SESSION_TINTS = {'midsession': UP, 'premarket': '#facc15'} # subtle green / yellow wash; at close stays plain

def tinted(bg, color, amount=0.07):
	"""bg blended a little way towards color, as a hex string."""
	mix = lambda i: round(int(bg[i:i + 2], 16) * (1 - amount) + int(color[i:i + 2], 16) * amount)
	return '#{:02x}{:02x}{:02x}'.format(mix(1), mix(3), mix(5))

@_drawn
def draw_bars(chart):
	"""Horizontal bars that mirror the caption list, first row on top, filling the whole 1280x800 canvas: blue for >= 0,
	red below, each row's label at the bar's base and its value (as value_format prints it) at the tip. Rows of (label,
	value); a (label, None) row is a gap. xlim zooms the value axis (bars then start at its left edge); session
	'midsession' or 'premarket' washes the background green or yellow."""
	rows, subtitle, xlim, session = chart.rows, chart.subtitle, chart.xlim, chart.session
	value_fmt = VALUE_FORMATS[chart.value_format]
	bg, ink, ink2, _ = PALETTE
	up, down = BAR_UP, DOWN
	if session in SESSION_TINTS:
		bg = tinted(bg, SESSION_TINTS[session])
	fig, canvas = _figure(bg)
	top_edge = 0.85 if subtitle else 0.89
	left = 0.14 if xlim else 0.04 # zoomed charts keep their labels outside the plot
	ax = fig.add_axes([left, 0.02, 0.96 - left, top_edge - 0.02], facecolor=bg)
	real = [(y, label, v) for y, (label, v) in enumerate(rows) if v is not None]
	values = [v for _, _, v in real]
	n = len(rows)
	ax.barh([y for y, _, _ in real], values, height=0.72, color=[up if v >= 0 else down for v in values], zorder=3)
	base = max(xlim[0], 0) if xlim else 0
	if not xlim:
		ax.axvline(0, color=ink2, linewidth=1.0, zorder=4)
	top, bottom = max(max(values), 0), min(min(values), 0)
	lo0 = xlim[0] if xlim else bottom
	hi0 = xlim[1] if xlim else top
	if hi0 <= lo0: # every value zero: give the axis a width, or the scale below divides by zero
		hi0 = lo0 + 1
	ax.set_xlim(lo0, hi0)
	ax.set_ylim(n - 0.4, -0.6) # first row on top
	ax.set_yticks([])
	ax.xaxis.set_visible(False) # no x axis labels or grid lines: every bar carries its own value
	for side in ax.spines.values():
		side.set_visible(False)
	dpi = fig.dpi
	axes_px = (top_edge - 0.02) * fig.get_figheight() * dpi
	bar_px = 0.72 * axes_px / n
	longest = max([len(str(label)) for _, label, _ in real] + [3])
	# text height follows the bar thickness
	em_px = min(bar_px * 1.3, 0.28 * (0.96 - left) * fig.get_figwidth() * dpi / (0.62 * longest))
	size = max(5, min(30, em_px * 72 / dpi))
	# each row's label sits beside the bar's base (left of the zero line for rising bars, right of it for falling ones)
	base_labels = []
	value_labels = []
	# baseline sits half a cap height below the bar's centre, so the capitals are centred on the bar
	drop = -0.365 * size
	for y, label, v in real:
		base_labels.append(ax.annotate(label, xy=(base, y), xytext=(-4, drop), textcoords='offset points', ha='right',
			va='baseline', fontsize=size, color=ink, annotation_clip=False, zorder=5))
		value_labels.append(ax.annotate(value_fmt(v), xy=(v, y), xytext=(4 if v >= 0 else -4, drop),
			textcoords='offset points', ha='left' if v >= 0 else 'right', va='baseline', fontsize=size, color=ink,
			annotation_clip=False))
	renderer = canvas.get_renderer()
	canvas.draw()
	label_width = [t.get_window_extent(renderer).width for t in base_labels]
	value_width = [t.get_window_extent(renderer).width for t in value_labels]
	# zoomed charts put the labels in the left margin: shrink the text until the widest label fits inside the image
	if xlim:
		factor = _shrink(base_labels, left * fig.get_figwidth() * dpi - 30) # leaves the 4pt gap before the bar base too
		if factor < 1:
			for t in value_labels:
				t.set_fontsize(t.get_fontsize() * factor)
			canvas.draw()
			label_width = [t.get_window_extent(renderer).width for t in base_labels]
			value_width = [t.get_window_extent(renderer).width for t in value_labels]
	width = ax.get_window_extent(renderer).width
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
	ax.set_xlim(lo, hi)
	for t, (_, _, v) in zip(base_labels, real):
		t.xyann = (-4 if v >= 0 else 4, drop)
		t.set_ha('right' if v >= 0 else 'left')
	_heading(fig, chart.title, subtitle)
	return _png(fig, bg)

# five points each at the bottom
SHORTS_VERDICTS = ((5, 'board shorts'), (10, 'cargo shorts'), (15, 'boxers'), (20, 'gym shorts'),
	(30, 'cutoffs'), (40, 'short shorts'), (50, 'daisy dukes'), (60, 'hot pants'), (70, 'speedos'),
	(80, 'budgie smugglers'), (90, 'just a belt'),
	(float('inf'), 'never nudes')) # the extreme ones step in every 10 points

def shorts_verdict(percent):
	"""The more shorted, the shorter the shorts."""
	return next(name for limit, name in SHORTS_VERDICTS if percent < limit)

@_drawn
def draw_shorts(chart, step=5):
	"""Short interest as a pictogram: each row (label, percent), largest first, is a run of cartoon shorts, one pair per
	`step` percent (the last pair cropped); a (label, None) row is a gap; the threshold is the outrageous line. Loud on
	purpose and drawn from patches, since matplotlib cannot render colour emoji: a 1280x800 PNG."""
	rows, threshold = chart.rows, chart.threshold
	import math
	import numpy as np
	from matplotlib.patches import Polygon, Rectangle, Circle, Ellipse, PathPatch
	from matplotlib.path import Path
	sky, ink, sea, foam, ray = '#ffe66d', '#1b1f3b', '#1ea7e1', '#b5e8ff', '#ffd23f'
	colors = ['#ff3d81', '#00b8a0', '#ff8a00', '#7a5cff', '#5bc215']
	W, H = 1280, 800
	rows = [(label if len(label) <= 10 else label[:9] + '…', value) for label, value in rows]
	fig, canvas = _figure(sky)
	ax = fig.add_axes([0, 0, 1, 1], facecolor=sky)
	ax.set_xlim(0, W)
	ax.set_ylim(H, 0) # pixels, y down
	ax.axis('off')

	def shorts(x, y, w, h, color, frac=1.0, lw=1.6):
		"""One pair, top-left at (x, y); frac < 1 crops it from the right."""
		def P(px, py):
			"""A point of the pair's box, from fractions of its width and height."""
			return (x + px * w, y + py * h)
		belt = '#' + ''.join(f"{int(int(color[i:i + 2], 16) * 0.7):02x}" for i in (1, 3, 5))
		legs = Polygon([P(0.04, 0.2), P(0.96, 0.2), P(1.0, 0.97), P(0.56, 0.97), P(0.5, 0.58), P(0.44, 0.97),
			P(0.0, 0.97)], closed=True, facecolor=color, edgecolor=ink, linewidth=lw, joinstyle='round')
		waist = Rectangle(P(0.04, 0.0), 0.92 * w, 0.22 * h, facecolor=belt, edgecolor=ink, linewidth=lw)
		parts = [legs, waist]
		for dx, dy in ((0.2, 0.5), (0.3, 0.78), (0.72, 0.5), (0.8, 0.78), (0.14, 0.8)): # polka dots
			parts.append(Circle(P(dx, dy), 0.045 * w, facecolor='white', edgecolor='none'))
		parts.append(Rectangle(P(0.47, 0.0), 0.06 * w, 0.22 * h, facecolor='#ffd23f', edgecolor=ink,
			linewidth=lw * 0.6)) # belt buckle
		clip = Rectangle((x - 2, y - 2), w * frac + 2, h + 4, transform=ax.transData) if frac < 1 else None
		for part in parts:
			ax.add_patch(part)
			if clip is not None:
				part.set_clip_path(clip)

	# decor: a big sun in sunglasses whose rays run under everything to the edges, and the sea
	R = 100 # the sun's radius; it sits in the top right corner
	margin = 5 # gap between the sun and the top and right edges
	sx, sy, rays = W - R - margin, R + margin, 16
	tilt = math.radians(-1) # beams turned 1 degree counter-clockwise (angles run clockwise here, as y points down)
	for k in range(0, rays, 2): # every other wedge, so the rays alternate with the sky
		a0, a1 = k * 2 * math.pi / rays + tilt, (k + 1) * 2 * math.pi / rays + tilt
		ax.add_patch(Polygon([(sx, sy), (sx + 2000 * math.cos(a0), sy + 2000 * math.sin(a0)),
			(sx + 2000 * math.cos(a1), sy + 2000 * math.sin(a1))],
			closed=True, facecolor=ray, edgecolor='none', zorder=-1))
	def at(u, v):
		"""A point on the sun's face, in sun radii from its centre with y down, in the axes' pixels."""
		return (sx + u * R, sy + v * R)
	ax.add_patch(Circle((sx, sy), R, facecolor='#ffb000', edgecolor='none'))
	for dx, dy, r, c in ((-0.05, -0.06, 0.93, '#ffb90a'), (-0.1, -0.12, 0.78, '#ffc21f'),
			(-0.16, -0.2, 0.55, '#ffcb35')): # fake gradient
		ax.add_patch(Circle(at(dx, dy), r * R, facecolor=c, edgecolor='none'))
	brown = '#5a3d37'
	for (u, v), w, h in (((-0.46, -0.07), 0.21, 0.25), ((0.31, -0.37), 0.20, 0.24)): # lopsided eyes
		ax.add_patch(Ellipse(at(u, v), w * R, h * R, facecolor=brown, edgecolor='none'))
	nose = np.array([(-0.07, -0.35), (0.05, -0.26), (0.15, -0.13), (0.18, 0.0), (0.10, 0.10), (-0.03, 0.16)])
	nose = nose.mean(axis=0) + 0.62 * (nose - nose.mean(axis=0)) # dainty: a smaller squiggle
	pts = np.vstack([nose[0], nose, nose[-1]]) # Catmull-Rom through the points, so the squiggle is smooth
	curve = [0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
		+ (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)
		for p0, p1, p2, p3 in zip(pts, pts[1:], pts[2:], pts[3:]) for t in np.linspace(0, 1, 12)]
	ax.plot([sx + u * R for u, _ in curve], [sy + v * R for _, v in curve], color='#e07b1a', linewidth=2.6,
		solid_capstyle='round')
	mouth_pts = [(-0.47, 0.47), (0.73, 0.0), (0.75, 0.35), (0.45, 0.74), (0.1, 0.74), (-0.15, 0.74), (-0.42, 0.62),
		(-0.47, 0.47), (-0.47, 0.47)]
	mc = (0.13, 0.37) # the mouth shrinks towards its middle
	mouth = Path([at(mc[0] + 0.65 * (u - mc[0]), mc[1] + 0.65 * (v - mc[1])) for u, v in mouth_pts],
		[Path.MOVETO, Path.LINETO, Path.CURVE4, Path.CURVE4, Path.CURVE4, Path.CURVE4, Path.CURVE4, Path.CURVE4,
			Path.CLOSEPOLY])
	ax.add_patch(PathPatch(mouth, facecolor='#2b2118', edgecolor='none'))
	ax.add_patch(Rectangle((0, 748), W, H - 748, facecolor=sea, edgecolor='none'))
	for cx in range(0, W + 36, 36):
		ax.add_patch(Circle((cx, 748), 19, facecolor=foam, edgecolor='none'))

	ax.text(40, 52, 'Shorts', color=ink, fontsize=21, fontweight='bold', ha='left', va='center')
	ax.text(40, 104, f"each pair of shorts = {step}% of shares shorted", color=ink, fontsize=9.5, ha='left',
		va='center')

	top, bottom = 205, 726 # below the sun
	n = len(rows)
	row_h = min((bottom - top) / n, 110)
	top += ((bottom - top) - row_h * n) / 2 # few rows sit in the middle of the beach, not the top
	bottom = top + row_h * n
	size = max(6, min(18, row_h * 0.5 * 72 / 200 * 2))
	label_w = max(len(str(label)) for label, _ in rows) * size * 200 / 72 * 0.62
	x0 = 40 + label_w + 16
	room = 40 + 400 # right-hand text: percent and verdict
	max_icons = max(math.ceil(max(v for _, v in rows if v is not None) / step), 1)
	icon_w = min((W - room - x0) / max_icons, row_h * 1.1 * 0.9, 120)
	icon_h = icon_w / 1.1
	lw = max(0.6, min(1.6, icon_w / 45))
	pct_texts = []
	for i, (label, value) in enumerate(rows):
		if value is None: # the gap between the most shorted and the least
			continue
		cy = top + (i + 0.5) * row_h
		ax.text(x0 - 14, cy, label, color=ink, fontsize=size, fontweight='bold', ha='right', va='center')
		whole, frac = divmod(value / step, 1)
		color = colors[i % len(colors)]
		for k in range(int(whole) + (1 if frac > 0.02 else 0)):
			shorts(x0 + k * icon_w, cy - icon_h / 2, icon_w * 0.92, icon_h, color,
				frac if k == int(whole) and frac > 0.02 else 1.0, lw)
		end = x0 + (value / step) * icon_w
		pct_texts.append((ax.text(end + 14, cy, f"{round(value)}%", color=ink, fontsize=size, fontweight='bold',
			ha='left', va='center'), cy, value))
	canvas.draw() # measure the percentages, then put each verdict right after its own
	for text, cy, value in pct_texts:
		x = text.get_window_extent(canvas.get_renderer()).x1 + 10
		verdict = ax.text(x, cy, shorts_verdict(round(value)), color=ink, fontsize=size * 0.62, fontstyle='italic',
			ha='left', va='center')
		_shrink([verdict], W - 16 - x) # never run off the image
	ax.text(W / 2, 784, 'past fashion not indicative of future fashion', color='white', fontsize=8, fontstyle='italic',
		ha='center', va='center')
	line_x = x0 + threshold / step * icon_w
	ax.plot([line_x, line_x], [top - 12, bottom], color=ink, linewidth=1.8, linestyle=(0, (5, 4)), zorder=0)
	ax.text(line_x, top - 18, f"{threshold:g}% outrageous line", color=ink, fontsize=7.5, fontweight='bold',
		ha='center', va='bottom')

	return _png(fig, sky)

@_drawn
def draw_pie(chart):
	"""Pie of (label, value) rows, largest first, with a legend of name and share. At most 8 named slices (the dark
	categorical slots, in fixed order); a slice labelled 'Other' is gray: a 1280x800 PNG."""
	from matplotlib.patches import Rectangle
	rows = chart.rows
	bg, ink, ink2, _ = PALETTE
	slots = CATEGORIES
	other = '#6b7280'
	total = sum(v for _, v in rows) or 1.0
	colors, n = [], 0
	for label, _ in rows:
		if label == 'Other':
			colors.append(other)
		else:
			colors.append(slots[n % len(slots)])
			n += 1
	fig, _ = _figure(bg)
	ax = fig.add_axes([0.02, 0.02, 0.525, 0.84], facecolor=bg) # square: 0.84 * 4in = 0.525 * 6.4in
	ax.pie([v for _, v in rows], colors=colors, startangle=90, counterclock=False,
		wedgeprops={'edgecolor': bg, 'linewidth': 2}) # 2px surface gap between slices
	ax.set_xlim(-1.03, 1.03) # matplotlib's default 1.25 leaves a wide margin around the pie
	ax.set_ylim(-1.03, 1.03)
	ax.set_aspect('equal')
	step = min(0.075, 0.74 / max(len(rows), 1))
	y = 0.5 + step * (len(rows) - 1) / 2 - 0.03 # legend block centred on the pie
	for (label, value), color in zip(rows, colors):
		fig.add_artist(Rectangle((0.57, y - 0.014), 0.018, 0.028, transform=fig.transFigure, facecolor=color,
			edgecolor='none'))
		fig.text(0.60, y, label if len(label) <= 28 else label[:27] + '…', color=ink, fontsize=8.5, ha='left',
			va='center')
		fig.text(0.97, y, f"{value / total * 100:.1f}%", color=ink2, fontsize=8.5, ha='right', va='center')
		y -= step
	_heading(fig, chart.title, chart.subtitle)
	return _png(fig, bg)

def _code_version():
	"""What else decides how a spec looks: this file and the matplotlib release."""
	try:
		matplotlib = importlib.metadata.version('matplotlib')
	except importlib.metadata.PackageNotFoundError:
		matplotlib = ''
	return hashlib.sha1(Path(__file__).read_bytes() + matplotlib.encode()).hexdigest()[:8]

CODE_VERSION = _code_version()

RENDERERS = {'bars': draw_bars, 'pie': draw_pie, 'shorts': draw_shorts, 'line': draw_line, 'compare': draw_compare}
LIMITS = {'bars': 40, 'shorts': 24} # the rows a chart has room for

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
	key = json.dumps([CODE_VERSION, dataclasses.asdict(chart)], sort_keys=True, default=str)
	name = f"finbot_chart_{hashlib.sha1(key.encode()).hexdigest()[:20]}.png"
	if config.prefs.cache and (image := cache.read_bytes(name)):
		return image
	image = RENDERERS[chart.kind](trimmed(chart))
	if config.prefs.cache:
		cache.write_bytes(name, image)
		image.seek(0)
	return image
