# ----------------------------- Diagnostics & Tables
# If your file already defines these diag_* counters above, this will just use them.
# Otherwise, the locals().get(...) fallbacks keep this block safe to paste.
diag_available   = locals().get("diag_available", len(pairs) if "pairs" in locals() else 0)
diag_capped      = locals().get("diag_capped",   len(pairs) if "pairs" in locals() else 0)
diag_fetched     = locals().get("diag_fetched",  0)
diag_skip_bars   = locals().get("diag_skip_bars",0)
diag_skip_api    = locals().get("diag_skip_api", 0)

st.caption(
    f"Diagnostics — Available: {diag_available} • Capped: {diag_capped} • "
    f"Fetched OK: {diag_fetched} • Skipped (bars): {diag_skip_bars} • "
    f"Skipped (API): {diag_skip_api} • Shown: {len(rows)}"
)

df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Pair"])

if df.empty:
    st.info(
        "No rows to show. Try ANY mode, lower Min Δ, shorten lookback, reduce Minimum bars, "
        "enable Volume spike/MACD Cross, or increase discovery cap."
    )
else:
    # Determine which TF label was used earlier in the script
    _tf = locals().get("sort_tf", st.session_state.get("sort_tf", "1h"))
    chg_col = f"% Change ({_tf})"

    # Sort and add rank column
    sort_desc_flag = locals().get("sort_desc", st.session_state.get("sort_desc", True))
    df = df.sort_values(chg_col, ascending=not sort_desc_flag, na_position="last").reset_index(drop=True)
    df.insert(0, "#", df.index + 1)

    # ---------------- Top-10 (greens only)
    st.subheader("📌 Top-10 (greens only)")
    top10 = df[df["_green"]].sort_values(chg_col, ascending=False, na_position="last").head(10)
    top10 = top10.drop(columns=["_green", "_yellow"], errors="ignore")
    if top10.empty:
        st.write("—")
    else:
        st.dataframe(top10, use_container_width=True)

    # ---------------- All pairs
    st.subheader("📑 All pairs")
    show_df = df.drop(columns=["_green", "_yellow"], errors="ignore")
    st.dataframe(show_df, use_container_width=True)

    # Footer
    _exchange = locals().get("effective_exchange", "Coinbase")
    _quote    = st.session_state.get("quote", "USD")
    _mode_txt = st.session_state.get("gate_mode", locals().get("gate_mode", "ANY"))
    _hard     = st.session_state.get("hard_filter", locals().get("hard_filter", False))
    st.caption(
        f"Pairs shown: {len(df)} • Exchange: {_exchange} • Quote: {_quote} "
        f"• TF: {_tf} • Gate Mode: {_mode_txt} • Hard filter: {'On' if _hard else 'Off'}"
    )

# ---------------- Auto-refresh timer
# Keep the same behavior as earlier: use session_state timer and rerun when due.
if "last_refresh" not in st.session_state:
    st.session_state["last_refresh"] = time.time()

_refresh_every = int(st.session_state.get("refresh_sec", DEFAULTS.get("refresh_sec", 30)))
remaining = _refresh_every - int(time.time() - st.session_state["last_refresh"])

if remaining <= 0:
    st.session_state["last_refresh"] = time.time()
    st.rerun()
else:
    st.caption(f"Auto-refresh every {_refresh_every}s (next in {max(0, remaining)}s)")

