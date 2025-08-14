dbg("opening websocket...")

async def _open():
    return await websockets.connect(
        url,
        ping_interval=20,
        ping_timeout=20,
        close_timeout=5,
        max_size=2**22,
        extra_headers={
            "User-Agent": "Mozilla/5.0 (compatible; StreamlitCloud; +https://streamlit.io)",
            "Origin": "https://share.streamlit.io",
            "Accept": "*/*",
        },
    )

ws = await asyncio.wait_for(_open(), timeout=6.0)
async with ws:
    dbg("socket open; subscribing...")
    ...
