meta, passed, chips, enabled_cnt = build_gate_eval(dft, dict(
    lookback_candles=int(st.session_state["lookback_candles"]),
    min_pct=float(st.session_state["min_pct"]),

    use_vol_spike=st.session_state["use_vol_spike"],
    vol_mult=float(st.session_state["vol_mult"]),
    vol_window=DEFAULTS["vol_window"],

    use_rsi=st.session_state["use_rsi"],
    rsi_len=int(st.session_state.get("rsi_len", 14)),
    min_rsi=int(st.session_state["min_rsi"]),

    use_macd=st.session_state["use_macd"],
    macd_fast=int(st.session_state.get("macd_fast", 12)),
    macd_slow=int(st.session_state.get("macd_slow", 26)),
    macd_sig=int(st.session_state.get("macd_sig", 9)),
    min_mhist=float(st.session_state["min_mhist"]),

    use_atr=st.session_state["use_atr"],
    atr_len=int(st.session_state.get("atr_len", 14)),
    min_atr=float(st.session_state["min_atr"]),

    use_trend=st.session_state["use_trend"],
    pivot_span=int(st.session_state["pivot_span"]),
    trend_within=int(st.session_state["trend_within"]),

    use_roc=st.session_state["use_roc"],
    min_roc=float(st.session_state["min_roc"]),

    # MACD cross gate
    use_macd_cross=st.session_state.get("use_macd_cross", True),
    macd_cross_bars=int(st.session_state.get("macd_cross_bars", 5)),
    macd_cross_only_bull=st.session_state.get("macd_cross_only_bull", True),
    macd_cross_below_zero=st.session_state.get("macd_cross_below_zero", True),
    macd_hist_confirm_bars=int(st.session_state.get("macd_hist_confirm_bars", 3)),
))

