"""
theme.py — the AQI Predictor glassmorphism design system.

Single source of truth for the visual language:
  - Design tokens (colors, radii, shadows, spacing)
  - Global CSS injected once per session (aurora background, glass
    surfaces, navbar, dialogs, responsive rules, animations)
  - glass_card() HTML helper for the premium cards
  - glass_theme() Plotly helper so every chart matches the system

Palette (dark glass + aurora):
  base #05070D (near-black navy) · purple #7C3AED · cyan #06B6D4 ·
  blue #3B82F6 · AQI semantics come from src/utils/aqi_utils.py.

Everything is pure Streamlit-safe CSS/HTML — no extra JS libraries,
no heavy effects. prefers-reduced-motion disables animations.
"""

import plotly.graph_objects as go
import streamlit as st

# ------------------------------------------------------------------
# Design tokens
# ------------------------------------------------------------------
COLORS = {
    "bg": "#05070D",
    "bg_alt": "#0B101C",
    "glass": "rgba(255, 255, 255, 0.045)",
    "glass_strong": "rgba(255, 255, 255, 0.07)",
    "border": "rgba(255, 255, 255, 0.10)",
    "border_strong": "rgba(255, 255, 255, 0.16)",
    "text": "#EEF2FA",
    "text_muted": "#9AA6BD",
    "purple": "#7C3AED",
    "cyan": "#06B6D4",
    "blue": "#3B82F6",
    "grid": "#1C2740",
}
RADIUS = {"card": "18px", "pill": "999px", "control": "12px"}
SHADOW = "0 8px 32px rgba(0, 0, 0, 0.35)"

# ------------------------------------------------------------------
# Global CSS
# ------------------------------------------------------------------
_CSS = f"""
<style>
/* ---------- Fonts (system-first, Inter when available) ---------- */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {{
  --bg: {COLORS['bg']};
  --glass: {COLORS['glass']};
  --glass-strong: {COLORS['glass_strong']};
  --border: {COLORS['border']};
  --border-strong: {COLORS['border_strong']};
  --text: {COLORS['text']};
  --muted: {COLORS['text_muted']};
  --purple: {COLORS['purple']};
  --cyan: {COLORS['cyan']};
  --blue: {COLORS['blue']};
  --grid: {COLORS['grid']};
  --radius: {RADIUS['card']};
}}

/* ---------- Aurora background ---------- */
[data-testid="stAppViewContainer"] {{
  background:
    radial-gradient(1100px 600px at 85% -10%, rgba(124, 58, 237, 0.16), transparent 60%),
    radial-gradient(900px 550px at -10% 25%, rgba(6, 182, 212, 0.10), transparent 55%),
    radial-gradient(1000px 700px at 50% 110%, rgba(59, 130, 246, 0.12), transparent 60%),
    {COLORS['bg']};
  background-attachment: fixed;
  animation: aurora 26s ease-in-out infinite alternate;
}}
@keyframes aurora {{
  0%   {{ background-position: 0% 0%, 0% 0%, 0% 0%, 0 0; }}
  100% {{ background-position: 4% 2%, -3% 3%, 2% -2%, 0 0; }}
}}

/* ---------- Base text ---------- */
html, body, [class*="css"], .stMarkdown, .stCaption {{
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  color: var(--text);
}}
h1, h2, h3 {{ letter-spacing: -0.02em; }}

/* ---------- Glass surfaces ---------- */
.glass {{
  background: var(--glass);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  box-shadow: {SHADOW}, inset 0 1px 0 rgba(255,255,255,0.06);
}}
.glass-hover {{ transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease; }}
.glass-hover:hover {{
  transform: translateY(-3px);
  border-color: var(--border-strong);
  box-shadow: 0 14px 44px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.08);
}}

/* Bordered Streamlit containers (used around charts) become glass panels */
[data-testid="stVerticalBlockBorderWrapper"] {{
  background: var(--glass);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  box-shadow: {SHADOW}, inset 0 1px 0 rgba(255,255,255,0.05);
  padding: 0.4rem 0.9rem;
}}

/* ---------- Hide native chrome ---------- */
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stToolbar"], [data-testid="stDecoration"],
#MainMenu, footer {{ display: none !important; }}
[data-testid="stSidebar"] {{ background: rgba(5,7,13,0.85); backdrop-filter: blur(18px); }}
[data-testid="stSidebarCollapseButton"] {{ color: var(--muted); }}

/* ---------- Buttons as glass pills ---------- */
.stButton > button, .stDownloadButton > button {{
  background: var(--glass);
  border: 1px solid var(--border);
  border-radius: {RADIUS['pill']};
  color: var(--text);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  transition: all 0.16s ease;
  font-weight: 500;
}}
.stButton > button:hover {{
  background: var(--glass-strong);
  border-color: var(--border-strong);
  color: #fff;
  transform: translateY(-1px);
}}
.stButton > button:focus-visible {{
  outline: 2px solid var(--cyan);
  outline-offset: 2px;
}}
.stButton > button[kind="primary"] {{
  background: linear-gradient(135deg, var(--purple), var(--blue));
  border: none;
  color: #fff;
}}
.stButton > button[kind="primary"]:hover {{
  filter: brightness(1.12);
}}

/* ---------- Navbar ---------- */
[data-testid="aqi-navbar"] {{
  position: sticky;
  top: 0;
  z-index: 999;
  display: flex;
  align-items: center;
  gap: 1.1rem;
  padding: 0.65rem 1.4rem;
  margin-bottom: 1.1rem;
  background: rgba(7, 10, 18, 0.72);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  backdrop-filter: blur(18px);
  -webkit-backdrop-filter: blur(18px);
  box-shadow: 0 10px 34px rgba(0,0,0,0.4), inset 0 1px 0 rgba(255,255,255,0.06);
}}
[data-testid="aqi-navbar"] .brand {{
  display: flex; align-items: center; gap: 0.55rem;
  font-weight: 800; font-size: 1.05rem; letter-spacing: -0.02em;
  white-space: nowrap;
}}
[data-testid="aqi-navbar"] .brand .logo {{
  width: 30px; height: 30px; border-radius: 10px;
  display: grid; place-items: center;
  background: linear-gradient(135deg, var(--purple), var(--cyan));
  font-size: 1rem;
  box-shadow: 0 4px 14px rgba(124, 58, 237, 0.45);
}}
[data-testid="aqi-navbar"] .chip {{
  display: inline-flex; align-items: center; gap: 0.4rem;
  padding: 0.42rem 1rem;
  border-radius: {RADIUS['pill']};
  background: var(--glass);
  border: 1px solid var(--border);
  color: var(--text);
  font-size: 0.9rem; font-weight: 500;
  white-space: nowrap;
}}
[data-testid="aqi-navbar"] .live-dot {{
  width: 8px; height: 8px; border-radius: 50%;
  background: #34D399;
  box-shadow: 0 0 0 0 rgba(52, 211, 153, 0.6);
  animation: pulse 2.2s infinite;
}}
@keyframes pulse {{
  0%   {{ box-shadow: 0 0 0 0 rgba(52,211,153,0.55); }}
  70%  {{ box-shadow: 0 0 0 7px rgba(52,211,153,0); }}
  100% {{ box-shadow: 0 0 0 0 rgba(52,211,153,0); }}
}}

/* ---------- AQI cards ---------- */
.aqi-card {{
  background: var(--glass);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.1rem 1.2rem;
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  box-shadow: {SHADOW}, inset 0 1px 0 rgba(255,255,255,0.06);
  transition: transform 0.18s ease, border-color 0.18s ease;
  position: relative;
  overflow: hidden;
}}
.aqi-card:hover {{ transform: translateY(-3px); border-color: var(--border-strong); }}
.aqi-card .glow {{
  position: absolute; top: -45%; right: -30%;
  width: 85%; height: 90%;
  border-radius: 50%;
  filter: blur(46px);
  opacity: 0.16;
  pointer-events: none;
}}
.aqi-card .kicker {{ font-size: 0.78rem; color: var(--muted); font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; }}
.aqi-card .value {{ font-size: 2.6rem; font-weight: 800; line-height: 1.1; letter-spacing: -0.03em; }}
.aqi-card .band {{ font-size: 0.92rem; font-weight: 600; }}
.aqi-card .foot {{
  margin-top: 0.7rem; padding-top: 0.6rem;
  border-top: 1px solid rgba(255,255,255,0.10);
  font-size: 0.8rem; color: var(--muted);
}}

/* ---------- Headers ---------- */
.aqi-page-title {{ font-size: 2rem; font-weight: 800; letter-spacing: -0.03em; margin: 0.2rem 0 0.1rem; }}
.aqi-gradient-text {{
  background: linear-gradient(120deg, #C4B5FD 0%, #67E8F9 55%, #93C5FD 100%);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent; color: transparent;
}}
.aqi-sub {{ color: var(--muted); font-size: 0.95rem; }}
.aqi-context {{ color: var(--muted); font-size: 0.82rem; margin-top: 0.25rem; }}

/* ---------- Dialogs ---------- */
[data-testid="stDialog"] [role="dialog"] {{
  background: rgba(10, 14, 24, 0.92);
  border: 1px solid var(--border-strong);
  border-radius: 20px;
  backdrop-filter: blur(22px);
  -webkit-backdrop-filter: blur(22px);
  box-shadow: 0 24px 80px rgba(0,0,0,0.6);
}}

/* ---------- Inputs / selects ---------- */
[data-testid="stTextInput"] input, [data-testid="stSelectbox"] [data-baseweb="select"] > div {{
  background: var(--glass);
  border: 1px solid var(--border);
  border-radius: {RADIUS['control']};
  color: var(--text);
}}
[data-testid="stTextInput"] input:focus, [data-testid="stSelectbox"] [data-baseweb="select"] > div:focus-within {{
  border-color: var(--cyan);
}}

/* ---------- Alerts / insight cards (glass) ---------- */
[data-testid="stAlert"] {{
  background: var(--glass);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  box-shadow: {SHADOW}, inset 0 1px 0 rgba(255,255,255,0.05);
}}

/* ---------- Expander ---------- */
[data-testid="stExpander"] details {{
  background: var(--glass);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  backdrop-filter: blur(12px);
}}

/* ---------- Tabs / radio ---------- */
.stTabs [data-baseweb="tab-list"] {{ gap: 0.5rem; }}
.stTabs [data-baseweb="tab"] {{
  background: var(--glass);
  border: 1px solid var(--border);
  border-radius: {RADIUS['pill']};
  color: var(--muted);
  padding: 0.35rem 1rem;
}}
.stTabs [aria-selected="true"] {{
  background: linear-gradient(135deg, rgba(124,58,237,0.35), rgba(6,182,212,0.25));
  color: #fff;
}}

/* ---------- Responsive ---------- */
@media (max-width: 900px) {{
  [data-testid="aqi-navbar"] {{ flex-wrap: wrap; gap: 0.6rem; padding: 0.55rem 0.9rem; }}
  .aqi-page-title {{ font-size: 1.55rem; }}
  .aqi-card .value {{ font-size: 2.1rem; }}
}}
@media (max-width: 600px) {{
  [data-testid="stVerticalBlock"] > div {{ gap: 0.5rem; }}
}}

/* ---------- Reduced motion ---------- */
@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }}
  [data-testid="stAppViewContainer"] {{ animation: none; }}
}}

/* ---------- Scrollbar ---------- */
::-webkit-scrollbar {{ width: 10px; height: 10px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: rgba(255,255,255,0.14); border-radius: 8px; }}
::-webkit-scrollbar-thumb:hover {{ background: rgba(255,255,255,0.24); }}
</style>
"""


def inject_theme():
    """Inject the global design system CSS (safe to call every rerun)."""
    st.markdown(_CSS, unsafe_allow_html=True)


# ------------------------------------------------------------------
# Card helper
# ------------------------------------------------------------------
def glass_card(title, value, subtitle, accent, time_str=None, glow=True):
    """
    Premium glass AQI card as HTML.

    Parameters
    ----------
    title : str        — small uppercase kicker ("Current AQI").
    value : str|int    — the big number.
    subtitle : str     — band label ("Moderate").
    accent : str       — EPA band hex; drives the value + soft glow.
    time_str : str|None— optional local-time footer.
    glow : bool        — soft accent radial glow in the corner.
    """
    glow_div = ""
    if glow:
        glow_div = f'<div class="glow" style="background:{accent};"></div>'
    foot = f'<div class="foot">🕐 {time_str}</div>' if time_str else ""
    return f"""
    <div class="aqi-card">
      {glow_div}
      <div class="kicker">{title}</div>
      <div class="value" style="color:{accent};">{value}</div>
      <div class="band" style="color:{accent};">{subtitle}</div>
      {foot}
    </div>
    """


# ------------------------------------------------------------------
# Plotly themer
# ------------------------------------------------------------------
def glass_theme(fig: go.Figure) -> go.Figure:
    """
    Apply the glass design system to a Plotly figure (mutates + returns).

    Sets transparent paper so the glass panel behind shows through, the
    dark grid, and the Inter font. Per-chart layout (margins, legends,
    titles) is left untouched — call this AFTER the chart's own layout.
    """
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, -apple-system, sans-serif", color=COLORS["text"], size=12),
        hoverlabel=dict(
            bgcolor="#16203A",
            bordercolor=COLORS["border_strong"],
            font=dict(color="#FFFFFF", family="Inter, sans-serif"),
        ),
        xaxis=dict(gridcolor=COLORS["grid"], zerolinecolor=COLORS["grid"]),
        yaxis=dict(gridcolor=COLORS["grid"], zerolinecolor=COLORS["grid"]),
    )
    return fig
