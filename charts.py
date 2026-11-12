"""Afterglow - explanatory charts (matplotlib, dark theme)."""
import math

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

BG, PANEL, TXT, MUTED = '#0b111c', '#111927', '#f4efe8', '#aab4c6'
LAYER = {'low': ('#9aa7bd', 0.2, 3.0), 'mid': ('#d7dde8', 3.0, 8.0), 'high': ('#ffffff', 8.0, 12.0)}
R_KM = 6371.0


def _style(fig, ax):
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(PANEL)
    for s in ax.spines.values():
        s.set_color('#3b4a66')
    ax.tick_params(colors=MUTED, labelsize=9, direction='out')
    ax.xaxis.label.set_color(TXT)
    ax.yaxis.label.set_color(TXT)
    ax.title.set_color(TXT)


def compass(az):
    d = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
    return d[int(round((az % 360) / 22.5)) % 16]


def cloud_section(a, event_word, time_text, az, canvas_km):
    """Cloud cover along the line toward the Sun, with the sunlight ray that lights a cloud
    canvas_km above the observer.  a = skycolor.assess() result."""
    fig, ax = plt.subplots(figsize=(8.2, 3.7), dpi=150)
    _style(fig, ax)
    s = a['samples']
    kms = [p['km'] for p in s]
    edges = [0] + [(kms[i] + kms[i + 1]) / 2 for i in range(len(kms) - 1)] + [kms[-1] + 50]
    for i, p in enumerate(s):
        for name, (col, y0, y1) in LAYER.items():
            v = p[name]
            if v is None or not math.isfinite(v):
                ax.add_patch(Rectangle((edges[i], y0), edges[i + 1] - edges[i], y1 - y0, fill=False,
                                       hatch='///', edgecolor='#3b4a66', lw=0))
                continue
            ax.add_patch(Rectangle((edges[i], y0), edges[i + 1] - edges[i], y1 - y0, color=col,
                                   alpha=0.08 + 0.8 * v, lw=0))
            ax.text((edges[i] + edges[i + 1]) / 2, (y0 + y1) / 2, f'{v * 100:.0f}%', ha='center', va='center',
                    fontsize=8, color='#0b111c' if v > 0.55 else TXT)
    # sunlight ray that grazes the Earth and lights the canvas above the observer
    D = math.sqrt(2 * R_KM * canvas_km)
    xs = [x * 2.0 for x in range(0, int(edges[-1] / 2) + 1)]
    ys = [(D - x) ** 2 / (2 * R_KM) for x in xs]
    ax.plot(xs, ys, color='#ff7a3d', lw=2.2, label=f'sunlight reaching cloud {canvas_km:.1f} km above you')
    ax.axvspan(max(0, D - 60), D + 60, ymin=0, ymax=3.0 / 12.5, color='#ff7a3d', alpha=0.18, lw=0,
               label='low cloud here would block that light')
    ax.plot([0], [0], marker='^', ms=10, color='#ff4f7b')
    ax.text(4, 0.25, 'you', color='#ff9fb5', fontsize=8)
    for y, t in ((3.0, 'low | mid'), (8.0, 'mid | high')):
        ax.axhline(y, color='#3b4a66', lw=0.8, ls=':')
        ax.text(edges[-1] - 2, y + 0.15, t, color=MUTED, fontsize=7, ha='right')
    ax.set_xlim(0, edges[-1])
    ax.set_ylim(0, 12.5)
    ax.set_xlabel(f'Distance toward the {event_word} (km), direction {az:.0f}° {compass(az)}')
    ax.set_ylabel('Height (km)')
    ax.set_title(f'{event_word.capitalize()} {time_text}: forecast cloud cover along the light path',
                 fontsize=11, loc='left', color=TXT)
    leg = ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.17), ncol=2, fontsize=8, frameon=False)
    for t in leg.get_texts():
        t.set_color(TXT)
    fig.tight_layout()
    return fig


def cloud_layers(profile_rows, lcl_m, time_text):
    fig, ax = plt.subplots(figsize=(4.2, 3.7), dpi=150)
    _style(fig, ax)
    if not profile_rows:
        ax.text(0.5, 0.5, 'No layer data', color=TXT, ha='center', transform=ax.transAxes)
        return fig
    last_label = -9.0
    for r in sorted(profile_rows, key=lambda r: r['above_ground_m']):
        h = r['above_ground_m'] / 1000.0
        col = LAYER['low'][0] if h < 3 else (LAYER['mid'][0] if h < 8 else LAYER['high'][0])
        ax.barh(h, r['cover'], height=0.35, color=col, alpha=0.9)
        # label a level only if it has cloud or is clear of the previous label
        if r['cover'] >= 5 or h - last_label >= 0.7:
            ax.text(r['cover'] + 2, h, f"{r['hpa']} hPa", va='center', fontsize=7, color=MUTED)
            last_label = h
    if lcl_m is not None and math.isfinite(lcl_m) and lcl_m < 12000:
        ax.axhline(lcl_m / 1000.0, color='#6fd0dc', lw=1.2, ls='--')
        ax.text(98, lcl_m / 1000.0 + 0.15, 'cumulus base (LCL)', color='#6fd0dc', fontsize=7, ha='right')
    ax.set_xlim(0, 115)
    ax.set_ylim(0, max(12.5, max(r['above_ground_m'] for r in profile_rows) / 1000.0 + 0.5))
    ax.set_xlabel('Cloud cover (%)')
    ax.set_ylabel('Height above you (km)')
    ax.set_title(f'Cloud layers above you, {time_text}', fontsize=10, loc='left', color=TXT)
    fig.tight_layout()
    return fig
