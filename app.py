import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

st.set_page_config(page_title="Crypto Scanner", layout="wide")
st.title("📈 Crypto Scanner Dashboard (Layout Preview)")

# --- Sticky Quick Controls ---
st.markdown("### 🔧 Quick Controls (always visible at top)")
col1, col2, col3, col4, col5 = st.columns(5)
with col1:
    st.selectbox("Sort Timeframe", ["1m", "5m", "15m", "30m", "1h", "4h", "6h", "12h", "1d", "1w"], index=4)
with col2:
    st.slider("Min % Change", 0.0, 20.0, 1.0, 0.1)
with col3:
    st.number_input("Min Volume ($)", min_value=0, value=1000000, step=100000)
with col4:
    st.radio("Gate Logic", ["ALL", "ANY"], horizontal=True)
with col5:
    st.button("🔊 Test Alert")

st.divider()

# --- Sidebar with collapsible gates ---
st.sidebar.header("⚙️ Scanner Options")

with st.sidebar.expander("📊 Price Filters", expanded=False):
    st.checkbox("Enable % Change", value=True)
    st.checkbox("Enable ATH/ATL", value=True)

with st.sidebar.expander("💰 Volume Filters", expanded=False):
    st.checkbox("Enable Quote Volume ($)", value=True)
    st.checkbox("Enable Base Units Volume", value=False)
    st.checkbox("Enable Volume Spike vs SMA", value=True)

with st.sidebar.expander("📉 Trend Filters", expanded=False):
    st.checkbox("Enable Trend Break", value=True)
    st.slider("Pivot Span (bars)", 1, 10, 3)
    st.selectbox("History Depth", ["Hours (≤72)", "Days (≤365)", "Weeks (≤52)"], index=0)

with st.sidebar.expander("📐 Technical Indicators", expanded=False):
    st.checkbox("Enable RSI", value=False)
    st.checkbox("Enable MACD", value=False)
    st.checkbox("Enable ATR", value=False)

# --- Mock data ---
mock_data = pd.DataFrame({
    "Pair": ["BTC/USD", "ETH/USD", "SOL/USD"],
    "Price": ["$62,300", "$3,420", "$155"],
    "% Change (1h)": ["+2.5%", "+0.8%", "+4.1%"],
    "% from ATH": ["-10%", "-30%", "-70%"],
    "% from ATL": ["+6000%", "+2200%", "+350%"],
    "Trend Broken": ["Yes (5h ago)", "No", "Yes (2d ago)"],
})

# --- Main Table with Hover + Chart ---
st.subheader("📑 Market Table")

for idx, row in mock_data.iterrows():
    with st.container():
        cols = st.columns([2,2,2,2,2,3])
        cols[0].markdown(f"**{row['Pair']}**")
        cols[1].write(row["Price"])
        cols[2].write(row["% Change (1h)"])
        cols[3].write(row["% from ATH"])
        cols[4].write(row["% from ATL"])
        cols[5].write(row["Trend Broken"])

        # Hover-style chart mockup (button here simulates hover)
        if cols[0].button(f"📊 View {row['Pair']} Chart", key=f"chart_{idx}"):
            fig, ax = plt.subplots(figsize=(5,3))
            x = np.arange(30)
            y = np.cumsum(np.random.randn(30)) + 100
            ax.plot(x, y, label=row['Pair'])
            ax.set_title(f"{row['Pair']} - Mini Chart")
            st.pyplot(fig)

            st.markdown(
                f"[🔗 Open in TradingView](https://www.tradingview.com/chart/?symbol={row['Pair'].replace('/', '')})"
            )

st.divider()

# --- Pinned Top-10 Movers ---
st.subheader("📌 Pinned Top-10 Movers")
st.success("Top-10 list will populate here when gates are satisfied.")

