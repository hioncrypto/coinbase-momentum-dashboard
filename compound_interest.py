"""
Compound Interest Calculator
Run: streamlit run compound_interest.py
"""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Compound Interest Calculator",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Design tokens — forest growth theme (not purple / cream-terracotta / broadsheet)
# ---------------------------------------------------------------------------
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,700&family=Sora:wght@400;500;600&display=swap');

:root {
  --ink: #0f1f1a;
  --muted: #4a6358;
  --paper: #f3f7f4;
  --panel: rgba(255, 255, 255, 0.72);
  --accent: #1a7a55;
  --accent-deep: #0d4f38;
  --gold: #c4a35a;
  --line: rgba(15, 31, 26, 0.10);
}

html, body, [data-testid="stAppViewContainer"] {
  background:
    radial-gradient(1200px 600px at 10% -10%, rgba(26, 122, 85, 0.18), transparent 55%),
    radial-gradient(900px 500px at 95% 5%, rgba(196, 163, 90, 0.16), transparent 50%),
    linear-gradient(165deg, #e8f0eb 0%, #f3f7f4 42%, #dde8e2 100%) !important;
  color: var(--ink);
  font-family: 'Sora', sans-serif;
}

[data-testid="stHeader"] { background: transparent; }

.block-container {
  padding-top: 2.25rem !important;
  padding-bottom: 3rem !important;
  max-width: 1100px !important;
}

h1, h2, h3, .hero-brand {
  font-family: 'Fraunces', Georgia, serif !important;
  letter-spacing: -0.02em;
}

.hero {
  text-align: left;
  margin-bottom: 1.75rem;
  animation: rise 0.7s ease-out both;
}

.hero-brand {
  font-size: clamp(2.4rem, 5vw, 3.4rem);
  font-weight: 700;
  color: var(--accent-deep);
  line-height: 1.05;
  margin: 0 0 0.55rem 0;
}

.hero-line {
  font-size: 1.15rem;
  color: var(--muted);
  max-width: 36rem;
  margin: 0;
  line-height: 1.45;
}

.factor-note {
  margin: 0.85rem 0 0 0;
  font-size: 0.92rem;
  color: var(--muted);
}

.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 1.15rem 1.25rem 0.85rem;
  backdrop-filter: blur(10px);
  animation: rise 0.8s ease-out 0.08s both;
}

.result-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 0.85rem;
  margin: 0.35rem 0 1rem;
  animation: rise 0.85s ease-out 0.16s both;
}

@media (max-width: 800px) {
  .result-grid { grid-template-columns: 1fr; }
}

.result-card {
  background: linear-gradient(160deg, rgba(255,255,255,0.9), rgba(232,240,235,0.85));
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 1rem 1.1rem;
  min-height: 96px;
}

.result-card .label {
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
  margin-bottom: 0.35rem;
}

.result-card .value {
  font-family: 'Fraunces', Georgia, serif;
  font-size: 1.65rem;
  font-weight: 700;
  color: var(--ink);
  line-height: 1.15;
}

.result-card.highlight .value { color: var(--accent-deep); }

.formula {
  font-size: 0.88rem;
  color: var(--muted);
  margin-top: 0.4rem;
}

div[data-testid="stNumberInput"] label,
div[data-testid="stSelectbox"] label,
div[data-testid="stSlider"] label {
  font-family: 'Sora', sans-serif !important;
  font-weight: 500 !important;
  color: var(--ink) !important;
}

@keyframes rise {
  from { opacity: 0; transform: translateY(14px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>
""",
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Factors that drive compound interest
# ---------------------------------------------------------------------------
# 1. Principal (P) — starting balance
# 2. Annual interest rate (r) — as a decimal, e.g. 0.07 for 7%
# 3. Time (t) — years invested
# 4. Compounding frequency (n) — how often interest is applied per year
# 5. Regular contribution (PMT) — optional recurring deposit
# 6. Contribution frequency — how often deposits are made
#
# Future value with contributions (end of each period):
#   FV = P(1 + r/n)^(n t) + PMT * [((1 + r/n)^(n t) - 1) / (r/n)]
# When r = 0: FV = P + PMT * n * t

COMPOUND_OPTIONS = {
    "Annually (1×)": 1,
    "Semi-annually (2×)": 2,
    "Quarterly (4×)": 4,
    "Monthly (12×)": 12,
    "Daily (365×)": 365,
}

CONTRIB_OPTIONS = {
    "None": 0,
    "Monthly": 12,
    "Quarterly": 4,
    "Annually": 1,
}


def future_value(
    principal: float,
    annual_rate_pct: float,
    years: float,
    compounds_per_year: int,
    contribution: float,
    contribs_per_year: int,
) -> tuple[float, float, float]:
    """Return (final_balance, total_contributed, total_interest)."""
    p = max(0.0, principal)
    r = max(0.0, annual_rate_pct) / 100.0
    t = max(0.0, years)
    n = max(1, compounds_per_year)
    pmt_annual = max(0.0, contribution) * max(0, contribs_per_year)

    # Model contributions as monthly-equivalent cash flows compounded
    # at the chosen compounding frequency for a smooth, readable schedule.
    periods = int(round(n * t))
    if periods == 0:
        total_contrib = p + pmt_annual * t
        return total_contrib, total_contrib, 0.0

    rate_per = r / n
    # Convert annual contribution stream into per-compounding-period payment
    pmt_per = (pmt_annual / n) if n else 0.0

    balance = p
    for _ in range(periods):
        balance = balance * (1 + rate_per) + pmt_per

    total_contributed = p + pmt_per * periods
    interest = balance - total_contributed
    return balance, total_contributed, interest


def year_by_year(
    principal: float,
    annual_rate_pct: float,
    years: int,
    compounds_per_year: int,
    contribution: float,
    contribs_per_year: int,
) -> pd.DataFrame:
    rows = []
    for y in range(0, years + 1):
        bal, contrib, interest = future_value(
            principal,
            annual_rate_pct,
            float(y),
            compounds_per_year,
            contribution,
            contribs_per_year,
        )
        rows.append(
            {
                "Year": y,
                "Balance": round(bal, 2),
                "Contributed": round(contrib, 2),
                "Interest": round(interest, 2),
            }
        )
    return pd.DataFrame(rows)


def money(x: float) -> str:
    return f"${x:,.2f}"


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.markdown(
    """
<div class="hero">
  <p class="hero-brand">Compound Growth</p>
  <p class="hero-line">See how principal, rate, time, and contributions stack into long-term wealth.</p>
  <p class="factor-note">Factors: starting principal · annual rate · years · compounding frequency · recurring contributions</p>
</div>
""",
    unsafe_allow_html=True,
)

left, right = st.columns([1.05, 1], gap="large")

with left:
    st.markdown('<div class="panel">', unsafe_allow_html=True)
    st.subheader("Inputs")

    principal = st.number_input(
        "Principal (starting amount)",
        min_value=0.0,
        value=10_000.0,
        step=500.0,
        help="The amount you start with before any growth or extra deposits.",
        format="%.2f",
    )
    rate = st.number_input(
        "Annual interest rate (%)",
        min_value=0.0,
        max_value=100.0,
        value=7.0,
        step=0.1,
        help="Nominal yearly rate before compounding is applied.",
        format="%.2f",
    )
    years = st.slider(
        "Time horizon (years)",
        min_value=1,
        max_value=50,
        value=20,
        help="How long the money stays invested and compounding.",
    )
    compound_label = st.selectbox(
        "Compounding frequency",
        options=list(COMPOUND_OPTIONS.keys()),
        index=3,
        help="How often interest is added to the balance each year. More frequent compounding grows slightly faster.",
    )
    contrib_label = st.selectbox(
        "Contribution frequency",
        options=list(CONTRIB_OPTIONS.keys()),
        index=1,
        help="Optional recurring deposits on top of the principal.",
    )
    contribution = 0.0
    if CONTRIB_OPTIONS[contrib_label] > 0:
        period_word = {
            "Monthly": "month",
            "Quarterly": "quarter",
            "Annually": "year",
        }[contrib_label]
        contribution = st.number_input(
            f"Contribution each {period_word}",
            min_value=0.0,
            value=250.0,
            step=50.0,
            help="Extra cash you add on a schedule. These deposits also earn compound interest.",
            format="%.2f",
        )
    st.markdown("</div>", unsafe_allow_html=True)

n = COMPOUND_OPTIONS[compound_label]
c_freq = CONTRIB_OPTIONS[contrib_label]
final_bal, total_in, total_interest = future_value(
    principal, rate, float(years), n, contribution, c_freq
)

with right:
    st.subheader("Results")
    st.markdown(
        f"""
<div class="result-grid">
  <div class="result-card highlight">
    <div class="label">Future value</div>
    <div class="value">{money(final_bal)}</div>
  </div>
  <div class="result-card">
    <div class="label">Total contributed</div>
    <div class="value">{money(total_in)}</div>
  </div>
  <div class="result-card">
    <div class="label">Interest earned</div>
    <div class="value">{money(total_interest)}</div>
  </div>
</div>
<p class="formula">Modeled with period rate r/n and end-of-period contributions.</p>
""",
        unsafe_allow_html=True,
    )

    schedule = year_by_year(principal, rate, years, n, contribution, c_freq)
    chart_df = schedule.set_index("Year")[["Balance", "Contributed"]]
    st.area_chart(chart_df, color=["#1a7a55", "#c4a35a"], height=280)

with st.expander("Year-by-year breakdown", expanded=False):
    show = schedule.copy()
    for col in ("Balance", "Contributed", "Interest"):
        show[col] = show[col].map(money)
    st.dataframe(show, width="stretch", hide_index=True)

with st.expander("What each factor means", expanded=True):
    st.markdown(
        """
| Factor | Symbol | Why it matters |
| --- | --- | --- |
| **Principal** | P | Your starting balance — the seed that compounds from day one. |
| **Annual interest rate** | r | The yearly return before compounding (e.g. 7% → 0.07). |
| **Time** | t | Years invested. Long horizons amplify compounding the most. |
| **Compounding frequency** | n | Times per year interest is credited (monthly, daily, etc.). |
| **Regular contribution** | PMT | Ongoing deposits; each one starts compounding on its own. |
| **Contribution frequency** | — | How often you add money (monthly / quarterly / annually). |

**Core idea:** interest earns interest. Small rate or contribution changes look modest early, then accelerate over decades.
"""
    )

# Sanity check for edge cases (documented for maintainers; not shown in UI)
assert math.isclose(
    future_value(1000, 0, 5, 12, 0, 0)[0], 1000.0, rel_tol=1e-9
)
