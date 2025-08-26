# ---------------------- TABLE BUILD (chips + strong buy + safe styling)

def chips_from_gates(gates: dict) -> str:
    """
    Render compact chips in a fixed order so the column always exists.
    Legend:
      Δ = %+Change, V = Volume×, R = RSI, M = MACD, A = ATR, T = Trend, C = ROC
    """
    order = [("Δ", "pct"), ("V", "vol"), ("R", "rsi"),
             ("M", "macd"), ("A", "atr"), ("T", "trend"), ("C", "roc")]
    html_parts = []
    for label, key in order:
        val = bool(gates.get(key, False))
        cls = "ok" if val else "no"
        html_parts.append(f'<span class="mv-chip {cls}">{label}</span>')
    return "".join(html_parts)

def style_rows_color(x: pd.DataFrame) -> pd.DataFrame:
    """
    Row-wise color (green for Strong Buy == YES, yellow for __partial__).
    This never references columns that might be absent.
    """
    styles = pd.DataFrame("", index=x.index, columns=x.columns)
    if "Strong Buy" in x.columns:
        green_mask = x["Strong Buy"].astype(str).str.upper().eq("YES")
        styles.loc[green_mask, :] = "background-color: rgba(0,180,0,0.22); font-weight:600;"
    if "__partial__" in x.columns:
        yellow_mask = x["__partial__"].fillna(False).astype(bool)
        styles.loc[yellow_mask & ~x.get("Strong Buy","").astype(str).str.upper().eq("YES"), :] = \
            "background-color: rgba(255,235,0,0.45); font-weight:600;"
    return styles

# Build rows (this replaces your prior list→DataFrame part)
table_rows = []          # (re)start a clean list
have_roc = True          # flip False if you haven’t wired ROC yet

# If you already computed K (green), Y (yellow), keep them; else read from UI
K_needed = st.session_state.get("k_green_needed", 2)   # set from your “Gates needed to turn green (K)”
Y_needed = st.session_state.get("y_yellow_needed", 1)  # set from “Yellow needs ≥ Y”

for pid in pairs:                        # you already set 'pairs' and ensured [:max_pairs]
    dft = df_for_tf(effective_exchange, pid, sort_tf)
    if dft is None or len(dft) < 30:
        continue

    # ---- you already compute these; keep your versions if you have them
    last_price = float(dft["close"].iloc[-1])
    first_price = float(dft["close"].iloc[0])
    pct_change = (last_price/first_price - 1.0) * 100.0

    # ATH/ATL (keep your existing helper if you like)
    hist = get_hist(effective_exchange, pid, basis, amount)
    if hist is None or len(hist) < 10:
        athp, athd, atlp, atld = (np.nan, "—", np.nan, "—")
    else:
        info = ath_atl_info(hist)
        athp, athd, atlp, atld = info["From ATH %"], info["ATH date"], info["From ATL %"], info["ATL date"]

    # ------------- gates dict (ensure every key exists so chips render consistently)
    g = {
        "pct":  pct_change >= st.session_state.get("gate_min_pct", 2.0) and pct_change > 0,
        "vol":  st.session_state.get("gate_vol_last_ge_mult", False),   # replace with your computed boolean
        "rsi":  st.session_state.get("gate_rsi_ge", False),             # ^
        "macd": st.session_state.get("gate_macd_hist_ge", False),       # ^
        "atr":  st.session_state.get("gate_atr_ge", False),             # ^
        "trend": st.session_state.get("gate_trend_up", False),          # ^
        "roc":  st.session_state.get("gate_roc_ge", False) if have_roc else False
    }
    # If you already have these booleans from your gate engine, just write:
    # g = {"pct": m["pct"].iloc[-1], "vol": m["vol"].iloc[-1], ...}

    true_count = sum(bool(v) for v in g.values())
    green = (true_count >= K_needed)
    yellow = (true_count >= Y_needed) and (true_count < K_needed)

    table_rows.append({
        "Pair": pid,
        "Price": last_price,
        f"% Change ({sort_tf})": pct_change,
        "From ATH %": athp, "ATH date": athd,
        "From ATL %": atlp, "ATL date": atld,
        "Gates": chips_from_gates(g),          # <- HTML chips
        "Strong Buy": "YES" if green else "—",
        "__partial__": yellow                  # <- helper for yellow paint, dropped before display
    })

df_all = pd.DataFrame(table_rows)

if df_all.empty:
    st.info("No rows to show yet. Loosen gates (lower Min +% change, reduce K), or increase discovery ‘Max pairs’.")
else:
    # Default sort: green first then biggest %+ (desc)
    chg_col = f"% Change ({sort_tf})"
    df_all["__green__"] = df_all["Strong Buy"].eq("YES")
    df_sorted = df_all.sort_values(["__green__", chg_col], ascending=[False, False]).reset_index(drop=True)
    df_sorted.insert(0, "#", df_sorted.index + 1)

    # Choose columns to show (always include Gates + Strong Buy)
    show_cols = ["#", "Pair", "Price", chg_col, "From ATH %", "ATH date", "From ATL %", "ATL date", "Gates", "Strong Buy", "__partial__"]

    styled = (
        df_sorted[show_cols]
        .style
        .hide(axis="columns", subset=["__partial__"])  # we keep it for styling but hide visually
        .apply(style_rows_color, axis=None)
        .format(precision=6, na_rep="—")
    )

    # Allow HTML (chips) in the “Gates” column
    styled = styled.format({"Gates": lambda s: s}, na_rep="—", escape="html")

    st.subheader("📌 Top-10 (meets green rule)")
    top10 = df_sorted[df_sorted["Strong Buy"].eq("YES")].head(10).reset_index(drop=True)
    if top10.empty:
        st.write("—")
        st.caption("💡 If nothing appears, loosen gates (lower Min +% change or reduce K).")
    else:
        top10 = top10[show_cols].style.hide(axis="columns", subset=["__partial__"]).apply(style_rows_color, axis=None).format(precision=6, na_rep="—")
        top10 = top10.format({"Gates": lambda s: s}, na_rep="—", escape="html")
        st.dataframe(top10, use_container_width=True)

    st.subheader("📑 Discover")
    st.dataframe(styled, use_container_width=True)

