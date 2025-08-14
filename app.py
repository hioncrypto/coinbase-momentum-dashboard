def worker(products, channel, chunk, mode_select):
    """
    Mode order changed: Auto tries Exchange URLs first (more reliable),
    then Advanced. We always move to the next URL on failure.
    """
    state.endpoint_mode = mode_select
    while True:
        if mode_select == "Advanced only":
            try_list = [(ADV_WS_URL, "advanced")]
        elif mode_select == "Exchange only":
            try_list = [(u, "exchange") for u in EXC_WS_URLS]
        else:  # Auto: prefer Exchange (public) first, then Advanced
            try_list = [(u, "exchange") for u in EXC_WS_URLS] + [(ADV_WS_URL, "advanced")]

        any_ok = False
        for url, mode in try_list:
            state.connected = False
            state.err = ""
            state.active_url = url
            ok = asyncio.run(ws_once(url, mode, channel, products, chunk))
            if ok:
                state.connected = True
                any_ok = True
                dbg("first ticks parsed — stream is connected")
                time.sleep(2.0)
                break
            else:
                dbg("attempt failed; trying next endpoint")
                state.reconnections += 1

        if not any_ok:
            time.sleep(2.0)  # short backoff then retry the whole list

