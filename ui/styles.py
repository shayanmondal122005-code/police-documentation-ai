"""Visual styling for the Streamlit interface (restrained, professional, accessible)."""

APP_CSS = """
<style>
  .block-container { padding-top: 1.6rem; max-width: 1180px; }
  h1, h2, h3 { letter-spacing: 0.01em; color: #1B2430; }
  .pd-header { border-bottom: 3px solid #1F3A5F; padding-bottom: 0.6rem; margin-bottom: 1rem; }
  .pd-header h1 { margin: 0; font-size: 1.7rem; letter-spacing: 0.08em; }
  .pd-header p { margin: 0.2rem 0 0; color: #4A5565; font-size: 0.95rem; }
  .pd-draft-banner {
    background: #FDECEC; border: 1px solid #9B1C1C; color: #7A1212; font-weight: 700;
    padding: 0.55rem 0.9rem; border-radius: 4px; text-align: center; letter-spacing: 0.04em; margin: 0.4rem 0 0.8rem;
  }
  .pd-notice {
    background: #FFF7E0; border-left: 4px solid #B7791F; color: #5C3D0A;
    padding: 0.55rem 0.9rem; border-radius: 3px; font-size: 0.88rem; margin-bottom: 0.7rem;
  }
  .pd-card {
    background: #FFFFFF; border: 1px solid #D5DAE1; border-radius: 6px; padding: 0.65rem 0.85rem; height: 100%;
  }
  .pd-card .label { color: #5B6675; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.07em; }
  .pd-card .value { color: #1B2430; font-size: 0.95rem; font-weight: 600; word-break: break-all; }
  .pd-card .value.mono { font-family: Consolas, "Courier New", monospace; font-size: 0.8rem; font-weight: 500; }
  .pd-badge {
    display: inline-block; padding: 0.05rem 0.5rem; border-radius: 10px; font-size: 0.72rem;
    font-weight: 700; letter-spacing: 0.05em; color: #fff; vertical-align: middle;
  }
  .pd-badge.fact { background: #2F6B3F; } .pd-badge.allegation { background: #9B1C1C; }
  .pd-badge.belief { background: #7A5A00; } .pd-badge.opinion { background: #4A5565; }
  .pd-badge.hearsay { background: #5B3F8C; } .pd-badge.uncertainty { background: #8A5A2B; }
  .pd-source { color: #5B6675; font-size: 0.82rem; }
  .pd-unverified { color: #9B1C1C; font-weight: 600; }
  .pd-item { background: #fff; border: 1px solid #E1E5EA; border-radius: 6px; padding: 0.55rem 0.8rem; margin-bottom: 0.5rem; }
  .stButton > button[kind="primary"] { background: #1F3A5F; border-color: #1F3A5F; font-weight: 600; letter-spacing: 0.03em; }
  .stTabs [data-baseweb="tab"] { font-weight: 600; letter-spacing: 0.05em; }
  :focus-visible { outline: 3px solid #1F6FEB !important; outline-offset: 2px; }
</style>
"""
