# app.py — Crypto Tracker (components-safe JS injection; single file)
# - Coinbase & Binance (REST), quotes, watchlist
# - Timeframes: 1m,5m,15m,30m,1h,4h,6h,12h,1d (1w is resampled)
# - Columns: # | Pair | Price | % change (TF) | From ATH % | ATH date | From ATL % | ATL date | Trend broken? | Broken since
# - Sortable headers (ASC/DESC), top scrollbar synced with table
# - Hover preview + in-app modal chart (Lightweight Charts; no redirect)
# - ATH/ATL depth: Hourly (≤72h), Daily (≤365d), Weekly (≤52w)
# - Gates (Price %+ and Volume Spike×) → Top‑10 (green rows), partial matches = yellow rows
# - Alerts: in-app beep + optional email/webhook; “Test beep” button
# - Auto-refresh (sidebar)
# - No st.expander(key=...) usage (avoids TypeError on older Streamlit)

import json, time, datetime as dt, ssl, smtplib, threading, queue, html as _html
from typing import List, Optional, Dict
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import numpy as np
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components


APP_VERSION = "v1.9.0"

# ---------------- Session state
WS_AVAILABLE = True
try:
    import websocket  # websocket-client
except Exception:
    WS_AVAILABLE = False

def _init_state():
    ss = st.session_state
    ss.setdefault("ws_thread", None)
    ss.setdefault("ws_alive", False)
    ss.setdefault("ws_q", queue.Queue())
    ss.setdefault("ws_prices", {})
    ss.setdefault("last_alert_hashes", set())
    ss.setdefault("alert_log", [])
    ss.setdefault("collapse_all_now", False)
_init_state()


# ---------------- CSS
def inject_css(font_scale: float=1.0, col_min_px: int=160, wrap=False):
    nowrap = "normal" if wrap else "nowrap"
    st.markdown(f"""
    <style>
      html, body {{ font-size: {font_scale}rem; }}
      :root {{ --col-min: {col_min_px}px; }}

      .hint {{ color:#a3adb5; font-size:.92em; }}
      .row-green  {{ background: rgba(0,255,0,.22); font-weight:600; }}
      .row-yellow {{ background: rgba(255,255,0,.60); font-weight:600; }}

      .top-scrollbar {{ width:100%; overflow-x:auto; overflow-y:hidden; height:16px; position: sticky; top: 56px; background: var(--background-color,#0e1117); z-index: 5; }}
      .top-scrollbar .spacer {{ height:1px; }}

      .expand-btn {{ cursor:pointer; margin-right:8px; opacity:.8; }}
      table.mv-table tr.row-expanded td {{ white-space: normal !important; height:auto !important; }}

      table.mv-table {{ width: max(1200px, 100%); border-collapse: collapse; table-layout: fixed; }}
      table.mv-table th, table.mv-table td {{
        padding: 6px 10px; border-bottom: 1px solid rgba(255,255,255,0.06);
        white-space: {nowrap}; overflow: hidden; text-overflow: ellipsis;
        vertical-align: middle; min-width: var(--col-min);
      }}
      table.mv-table th {{
        position: sticky; top: 72px; background: var(--background-color,#0e1117); z-index: 4; cursor: pointer;
      }}
      table.mv-table th .sort-ind {{ opacity:.6; margin-left:6px; }}

      a.mv-pair {{ color: var(--text-color,#e6e6e6); text-decoration: underline; cursor:pointer; }}

      /* Modal (created by JS) */
      .tv-modal-backdrop {{
        position: fixed; inset: 0; background: rgba(0,0,0,0.65);
        display: none; align-items: center; justify-content: center; z-index: 99999;
      }}
      .tv-modal {{
        width: min(96vw, 1200px); height: min(85vh, 820px);
        background: var(--background-color,#0e1117); border-radius: 12px;
        box-shadow: 0 8px 28px rgba(0,0,0,.45); overflow: hidden; position: relative;
      }}
      .tv-modal-header {{ display:flex; align-items:center; justify-content:space-between; padding:8px 12px; border-bottom:1px solid rgba(255,255,255,.08); }}
      .tv-modal-title {{ font-weight:700; font-size:1.05rem; }}
      .tv-close {{ cursor:pointer; border:0; background:transparent; font-size:1.3rem; opacity:.8; }}
      .tv-modal-body {{ width:100%; height:calc(100% - 44px); }}

      /* Floating hover preview */
      .lw-preview {{
        position: fixed; pointer-events:none; z-index: 99998;
        width: 420px; height: 280px; background: #111; border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; overflow: hidden; display:none;
      }}
    </style>
    """, unsafe_allow_html=True)


# ---------------- JS injection (via components, not markdown)
def inject_global_js():
    components.html("""
    <script>
    (function(){
      if (window.parent && !window.parent.document.getElementById('mv-global-js')) {
        const S = window.parent.document.createElement('script');
        S.id = 'mv-global-js';
        S.type = 'text/javascript';
        S.text = `
          // Load Lightweight Charts once
          (function addLw(){
            if(window.LightweightCharts) return;
            var s=document.createElement('script');
            s.src='https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js';
            document.head.appendChild(s);
          })();

          // Beep loop
          window._mv_audio_ctx = window._mv_audio_ctx || null;
          function mvEnsureCtx() {
            if (!window._mv_audio_ctx) {
              try { window._mv_audio_ctx = new (window.AudioContext || window.webkitAudioContext)(); }
              catch(e) { window._mv_audio_ctx = null; }
            }
            if (window._mv_audio_ctx && window._mv_audio_ctx.state === 'suspended') { window._mv_audio_ctx.resume(); }
          }
          window.mvBeepNow = function(){ localStorage.setItem('mustBeep','1'); };
          (function loop(){
            if (localStorage.getItem('mustBeep') === '1') {
              try {
                mvEnsureCtx();
                if (window._mv_audio_ctx) {
                  const ctx = window._mv_audio_ctx, osc = ctx.createOscillator(), g = ctx.createGain();
                  osc.type='sine'; osc.frequency.value=1000; osc.connect(g); g.connect(ctx.destination);
                  const t = ctx.currentTime;
                  g.gain.setValueAtTime(0.0001,t);
                  g.gain.exponentialRampToValueAtTime(0.25,t+0.01);
                  g.gain.exponentialRampToValueAtTime(0.0001,t+0.20);
                  osc.start(t); osc.stop(t+0.21);
                }
              } catch(e){}
              localStorage.setItem('mustBeep','0');
            }
            requestAnimationFrame(loop);
          })();
          window.addEventListener('click', mvEnsureCtx, { once:true });

          // Modal scaffold
          (function ensureModal(){
            if (document.getElementById('mv-tv-backdrop')) return;
            const back = document.createElement('div'); back.id='mv-tv-backdrop'; back.className='tv-modal-backdrop';
            const modal = document.createElement('div'); modal.id='mv-tv-modal'; modal.className='tv-modal'; modal.style.display='none';
            const header = document.createElement('div'); header.className='tv-modal-header';
            const title = document.createElement('div'); title.className='tv-modal-title'; title.id='mv-tv-title'; title.textContent='Chart';
            const close = document.createElement('button'); close.className='tv-close'; close.textContent='✕'; close.onclick=function(){ mvCloseChart(); };
            const body = document.createElement('div'); body.className='tv-modal-body'; body.id='mv-tv-body';
            header.appendChild(title); header.appendChild(close);
            modal.appendChild(header); modal.appendChild(body);
            document.body.appendChild(back); document.body.appendChild(modal);
            back.addEventListener('click', (e)=>{ if(e.target.id==='mv-tv-backdrop'){ mvCloseChart(); }});
          })();

          // Candle cache
          window._mvCandleCache = window._mvCandleCache || {};

          // Open/close modal with LW Charts
          window.mvOpenChart = function(symbol, title){
            const data = (window._mvCandleCache||{})[symbol] || [];
            const back = document.getElementById('mv-tv-backdrop');
            const modal= document.getElementById('mv-tv-modal');
            const body = document.getElementById('mv-tv-body');
            document.getElementById('mv-tv-title').textContent = title || symbol;
            body.innerHTML = '<div id="lw-modal" style="width:100%;height:100%"></div>';
            function wait(){
              if(!window.LightweightCharts){ setTimeout(wait,80); return; }
              const c = LightweightCharts.createChart(document.getElementById('lw-modal'), {layout:{background:{type:'solid', color:'#111'}, textColor:'#DDD'}, grid:{vertLines:{color:'#222'}, horzLines:{color:'#222'}}, timeScale:{timeVisible:true}});
              const s = c.addCandlestickSeries(); s.setData(data);
            }
            wait(); back.style.display='flex'; modal.style.display='block';
            document.onkeydown=(e)=>{ if(e.key==='Escape') mvCloseChart(); };
          };
          window.mvCloseChart = function(){
            document.getElementById('mv-tv-backdrop').style.display='none';
            const modal=document.getElementById('mv-tv-modal'); if(modal){ modal.style.display='none'; }
            const body=document.getElementById('mv-tv-body'); if(body){ body.innerHTML=''; }
            document.onkeydown=null;
          };

          // Sorting
          window.mvMakeSortable = function(tableId){
            const tbl=document.getElementById(tableId); if(!tbl) return;
            const thead=tbl.querySelector('thead'); const tbody=tbl.querySelector('tbody');
            if(!thead||!tbody) return;
            const ths=[...thead.querySelectorAll('th')];
            ths.forEach((th, idx)=>{
              th.addEventListener('click', ()=>{
                const asc = !(th.dataset.asc === 'true');
                ths.forEach(t=>{ t.dataset.asc=''; const s=t.querySelector('.sort-ind'); if(s) s.textContent=''; });
                th.dataset.asc = asc ? 'true':'false';
                const rows=[...tbody.querySelectorAll('tr')];
                const parseVal=(td)=>{
                  const raw=td.textContent.trim();
                  const d=Date.parse(raw);
                  if (!isNaN(d) && raw.includes('-')) return d;
                  const t=raw.replace('%','').replace('$','').replaceAll(',','');
                  const n=parseFloat(t);
                  return isNaN(n) ? raw.toLowerCase() : n;
                };
                rows.sort((a,b)=>{
                  const va=parseVal(a.children[idx]); const vb=parseVal(b.children[idx]);
                  if(va<vb) return asc?-1:1;
                  if(va>vb) return asc?1:-1;
                  return 0;
                });
                rows.forEach(r=>tbody.appendChild(r));
                const ind=th.querySelector('.sort-ind') || Object.assign(document.createElement('span'),{{className:'sort-ind'}});
                if(!th.querySelector('.sort-ind')) th.appendChild(ind);
                ind.textContent = asc ? '▲' : '▼';
              });
            });
          };

          // Top scrollbar sync
          window.mvInitTopScroll = function(topId, wrapId, tableId){
            const top=document.getElementById(topId);
            const wrap=document.getElementById(wrapId);
            const tbl=document.getElementById(tableId);
            if(!top||!wrap||!tbl) return;
            function size(){
              const w = tbl.scrollWidth;
              const sp = top.querySelector('.spacer');
              if(sp) sp.style.width = Math.max(w, wrap.clientWidth) + 'px';
            }
            size(); setTimeout(size, 120); setTimeout(size, 500);
            new ResizeObserver(size).observe(wrap);
            new ResizeObserver(size).observe(tbl);
            top.addEventListener('scroll', ()=>{{ wrap.scrollLeft = top.scrollLeft; }});
            wrap.addEventListener('scroll', ()=>{{ top.scrollLeft = wrap.scrollLeft; }});
          };

          // Hover preview + expand
          window.mvBindRowExtras = function(tableId){
            const tbl=document.getElementById(tableId); if(!tbl) return;
            // Hover preview
            let preview=document.getElementById('lw-preview');
            if(!preview){
              preview=document.createElement('div'); preview.id='lw-preview'; preview.className='lw-preview';
              const inner=document.createElement('div'); inner.id='lw-preview-inner'; inner.style.width='100%'; inner.style.height='100%';
              preview.appendChild(inner); document.body.appendChild(preview);
            }
            const inner=preview.querySelector('#lw-preview-inner');
            let series=null, chartReady=false;
            function ensureChart(){
              if (!window.LightweightCharts) return false;
              if (!chartReady){
                const c = LightweightCharts.createChart(inner, {layout:{background:{type:'solid', color:'#111'}, textColor:'#DDD'}, grid:{vertLines:{color:'#222'}, horzLines:{color:'#222'}}, timeScale:{timeVisible:true}});
                series = c.addCandlestickSeries(); chartReady=true;
              }
              return true;
            }
            const links=[...tbl.querySelectorAll('a.mv-pair-link')];
            links.forEach(el=>{
              el.addEventListener('mouseenter', ()=>{
                const sym=el.dataset.tvSymbol;
                const data=(window._mvCandleCache||{})[sym]||[];
                if (!ensureChart()) return;
                series.setData(data); preview.style.display='block';
              });
              el.addEventListener('mousemove', (e)=>{ preview.style.left=(e.clientX+16)+'px'; preview.style.top=(e.clientY+16)+'px'; });
              el.addEventListener('mouseleave', ()=>{ preview.style.display='none'; });
            });
            // Manual row expand
            const exps=[...tbl.querySelectorAll('.expand-btn')];
            exps.forEach(btn=>{
              btn.addEventListener('click', (e)=>{
                e.preventDefault(); e.stopPropagation();
                const tr=btn.closest('tr');
                if(tr) tr.classList.toggle('row-expanded');
              });
            });
          };
        `;
        window.parent.document.body.appendChild(S);
      }
    })();
    </script>
    """, height=0, width=0)


# ---------------- Helpers / indicators
def ema(s, span): return s.ewm(span=span, adjust=False).mean()
def atr(df, length=14):
    h,l,c = df["high"], df["low"], df["close"]; pc=c.shift(1)
    tr = pd.concat([(h-l),(h-pc).abs(),(l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()

def find_pivots(close: pd.Series, span=3):
    n=len(close); highs=[]; lows=[]; v=close.values
    for i in range(span, n-span):
        if v[i]>v[i-span:i].max() and v[i]>v[i+1:i+1+span].max(): highs.append(i)
        if v[i]<v[i-span:i].min() and v[i]<v[i+1:i+1+span].min(): lows.append(i)
    return pd.Index(highs), pd.Index(lows)

def recent_high_metrics(df: pd.DataFrame, span=3):
    if df is None or df.empty or len(df)<(span*2+5): return np.nan, "—"
    highs,_=find_pivots(df["close"], span)
    if len(highs)==0: return np.nan, "—"
    idx=int(highs[-1]); level=float(df["close"].iloc[idx])
    last=float(df["close"].iloc[-1]); last_ts=pd.to_datetime(df["ts"].iloc[-1])
    cross=None
    for j in range(idx+1, len(df)):
        if float(df["close"].iloc[j]) < level: cross=j; break
    if cross is None: return max((last/level-1)*100, 0.0), "—"
    dur=(last_ts - pd.to_datetime(df["ts"].iloc[cross])).total_seconds()
    return max((last/level-1)*100, 0.0), _pretty_dur(dur)

def trend_breakout_info(df: pd.DataFrame, span=3):
    if df is None or df.empty or len(df)<(span*2+5): return "—","—"
    highs,lows=find_pivots(df["close"], span)
    last=float(df["close"].iloc[-1]); last_ts=pd.to_datetime(df["ts"].iloc[-1])
    if len(highs):
        hi=int(highs[-1]); level=float(df["close"].iloc[hi])
        if last>level:
            cross=None
            for j in range(hi+1,len(df)):
                if float(df["close"].iloc[j])>level: cross=j; break
            if cross is not None:
                dur=(last_ts - pd.to_datetime(df["ts"].iloc[cross])).total_seconds()
                return "Yes ↑", _pretty_dur(dur)
    if len(lows):
        lo=int(lows[-1]); level=float(df["close"].iloc[lo])
        if last<level:
            cross=None
            for j in range(lo+1,len(df)):
                if float(df["close"].iloc[j])<level: cross=j; break
            if cross is not None:
                dur=(last_ts - pd.to_datetime(df["ts"].iloc[cross])).total_seconds()
                return "Yes ↓", _pretty_dur(dur)
    return "No","—"

def _pretty_dur(sec):
    if sec is None or np.isnan(sec): return "—"
    sec=int(sec); d,rem=divmod(sec,86400); h,rem=divmod(rem,3600); m,_=divmod(rem,60)
    out=[]; 
    if d: out.append(f"{d}d")
    if h: out.append(f"{h}h")
    if m and not d: out.append(f"{m}m")
    return " ".join(out) if out else "0m"


# ---------------- Exchanges / products / candles
CB_BASE = "https://api.exchange.coinbase.com"
BN_BASE = "https://api.binance.com"

ALL_TFS = {"1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":14400,"6h":21600,"12h":43200,"1d":86400,"1w":604800}
NATIVE_CB = {60,300,900,3600,21600,86400}
NATIVE_BN = {60,300,900,1800,3600,14400,21600,43200,86400}

def coinbase_list_products(quote: str) -> List[str]:
    try:
        r=requests.get(f"{CB_BASE}/products", timeout=15); r.raise_for_status()
        data=r.json(); return sorted([f"{p['base_currency']}-{p['quote_currency']}" for p in data if p.get("quote_currency")==quote])
    except Exception: return []

def binance_list_products(quote: str) -> List[str]:
    try:
        r=requests.get(f"{BN_BASE}/api/v3/exchangeInfo", timeout=20); r.raise_for_status()
        out=[]; 
        for s in r.json().get("symbols",[]):
            if s.get("status")!="TRADING": continue
            if s.get("quoteAsset")==quote: out.append(f"{s['baseAsset']}-{quote}")
        return sorted(out)
    except Exception: return []

def list_products(exchange: str, quote: str) -> List[str]:
    if exchange=="Coinbase": return coinbase_list_products(quote)
    if exchange=="Binance":  return binance_list_products(quote)
    return []

def fetch_candles(exchange: str, pair_dash: str, granularity_sec: int,
                  start: Optional[dt.datetime]=None, end: Optional[dt.datetime]=None) -> Optional[pd.DataFrame]:
    if exchange=="Coinbase":
        url=f"{CB_BASE}/products/{pair_dash}/candles?granularity={granularity_sec}"
        params={}
        if start: params["start"]=start.replace(tzinfo=dt.timezone.utc).isoformat()
        if end:   params["end"]=end.replace(tzinfo=dt.timezone.utc).isoformat()
        try:
            r=requests.get(url, params=params, timeout=20)
            if r.status_code!=200: return None
            arr=r.json()
            if not arr: return None
            df=pd.DataFrame(arr, columns=["ts","low","high","open","close","volume"])
            df["ts"]=pd.to_datetime(df["ts"], unit="s", utc=True)
            return df.sort_values("ts").reset_index(drop=True)
        except Exception: return None
    elif exchange=="Binance":
        base, quote = pair_dash.split("-"); symbol=f"{base}{quote}"
        interval_map = {60:"1m",300:"5m",900:"15m",1800:"30m",3600:"1h",14400:"4h",21600:"6h",43200:"12h",86400:"1d"}
        interval = interval_map.get(granularity_sec)
        if not interval: return None
        params={"symbol":symbol,"interval":interval,"limit":1000}
        if start: params["startTime"]=int(start.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
        if end:   params["endTime"]=int(end.replace(tzinfo=dt.timezone.utc).timestamp()*1000)
        try:
            r=requests.get(f"{BN_BASE}/api/v3/klines", params=params, timeout=20)
            if r.status_code!=200: return None
            rows=[]
            for a in r.json():
                rows.append({"ts":pd.to_datetime(a[0],unit="ms",utc=True),
                             "open":float(a[1]),"high":float(a[2]),
                             "low":float(a[3]),"close":float(a[4]),
                             "volume":float(a[5])})
            return pd.DataFrame(rows).sort_values("ts").reset_index(drop=True)
        except Exception: return None
    return None

def resample_ohlcv(df: pd.DataFrame, target_sec: int) -> Optional[pd.DataFrame]:
    if df is None or df.empty: return None
    d=df.set_index(pd.DatetimeIndex(df["ts"]))
    agg={"open":"first","high":"max","low":"min","close":"last","volume":"sum"}
    out=d.resample(f"{target_sec}s", label="right", closed="right").agg(agg).dropna()
    return out.reset_index()

def df_for_tf(exchange: str, pair: str, tf: str) -> Optional[pd.DataFrame]:
    sec = ALL_TFS[tf]
    native = (sec in NATIVE_CB if exchange=="Coinbase" else sec in NATIVE_BN)
    if native or tf=="1w":
        base_tf = sec if tf!="1w" else ALL_TFS["1d"]
        d = fetch_candles(exchange, pair, base_tf)
        return d if tf!="1w" else resample_ohlcv(d, 7*86400)
    # synthesize 30m/4h/12h for Coinbase
    if exchange=="Coinbase" and tf in ("30m","4h","12h"):
        src = fetch_candles(exchange, pair, ALL_TFS["1m"] if tf=="30m" else ALL_TFS["1h"])
        return resample_ohlcv(src, sec)
    return None


# ---------------- ATH/ATL history
@st.cache_data(ttl=6*3600, show_spinner=False)
def get_hist(exchange: str, pair: str, basis: str, amount: int) -> Optional[pd.DataFrame]:
    end = dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)
    if basis=="Hourly":   amount=min(max(1,amount),72);  gran=3600;  start_cutoff=end-dt.timedelta(hours=amount)
    elif basis=="Daily":  amount=min(max(1,amount),365); gran=86400; start_cutoff=end-dt.timedelta(days=amount)
    else:                 amount=min(max(1,amount),52);  gran=86400; start_cutoff=end-dt.timedelta(weeks=amount)
    out=[]; step=300; cursor_end=end
    while True:
        win=dt.timedelta(seconds=step*gran)
        cursor_start=max(start_cutoff, cursor_end - win)
        if (cursor_end-cursor_start).total_seconds()<gran: break
        df=fetch_candles(exchange, pair, gran, start=cursor_start, end=cursor_end)
        if df is None or df.empty: break
        out.append(df); cursor_end=df["ts"].iloc[0]
        if cursor_end<=start_cutoff: break
    if not out: return None
    hist=pd.concat(out, ignore_index=True).drop_duplicates(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    if basis=="Weekly": hist=resample_ohlcv(hist, 7*86400)
    return hist


def ath_atl_info(hist: pd.DataFrame) -> dict:
    last=float(hist["close"].iloc[-1])
    i_ath=int(hist["high"].idxmax()); i_atl=int(hist["low"].idxmin())
    ath=float(hist["high"].iloc[i_ath]); d_ath=pd.to_datetime(hist["ts"].iloc[i_ath]).date().isoformat()
    atl=float(hist["low"].iloc[i_atl]);  d_atl=pd.to_datetime(hist["ts"].iloc[i_atl]).date().isoformat()
    return {"From ATH %": (last/ath-1)*100 if ath>0 else np.nan, "ATH date": d_ath,
            "From ATL %": (last/atl-1)*100 if atl>0 else np.nan, "ATL date": d_atl}


# ---------------- Gates / masks
def build_masks(disp: pd.DataFrame, sort_tf_label: str,
                pct_thresh: float, use_spike: bool, spike_mult: float, volx_series: Optional[pd.Series]):
    # green = passes all enabled gates; yellow = partial
    mlist = []
    m_pct = disp[sort_tf_label].fillna(-1) >= pct_thresh
    mlist.append(m_pct)
    if use_spike and volx_series is not None:
        mlist.append(volx_series.fillna(0) >= spike_mult)

    m_all = mlist[0].copy()
    m_any = mlist[0].copy()
    for m in mlist[1:]:
        m_all = m_all & m
        m_any = m_any | m
    green = m_all
    yellow = (~green) & m_any
    return green, yellow


# ---------------- Rendering
def tv_symbol(exchange: str, pair: str) -> Optional[str]:
    base, quote = pair.split("-")
    if exchange=="Coinbase":
        tvq={"USDC":"USD","BUSD":"USD"}.get(quote, quote); return f"COINBASE:{base}{tvq}"
    if exchange=="Binance":
        tvq={"BUSD":"USDT"}.get(quote, quote); return f"BINANCE:{base}{tvq}"
    return None

def render_table_html(df: pd.DataFrame, green_mask: pd.Series, yellow_mask: pd.Series,
                      exchange: str, sort_tf: str, table_key: str):
    import uuid
    wrap_id  = f"{table_key}_wrap_{uuid.uuid4().hex[:6]}"
    table_id = f"{table_key}_tbl_{uuid.uuid4().hex[:6]}"
    top_id   = f"{table_key}_top_{uuid.uuid4().hex[:6]}"

    cols=list(df.columns)
    thead="<tr>"+ "".join(f"<th>{_html.escape(c)} <span class='sort-ind'></span></th>" for c in cols) +"</tr>"

    rows=[]
    for i, (_, row) in enumerate(df.iterrows()):
        pair=str(row["Pair"]); sym=tv_symbol(exchange, pair) or ""
        title=f"{pair} • {sort_tf}"
        pair_html=(f"<span class='expand-btn' title='Expand/Collapse row'>⤢</span>"
                   f"<a class='mv-pair mv-pair-link' data-tv-symbol='{_html.escape(sym)}' "
                   f"title='Click to open chart' href='#' onclick='mvOpenChart(\"{_html.escape(sym)}\",\"{_html.escape(title)}\");return false;'>{_html.escape(pair)}</a>")
        cls="row-green" if bool(green_mask.iloc[i]) else ("row-yellow" if bool(yellow_mask.iloc[i]) else "")
        tds=[]
        for c in cols:
            if c=="Pair":
                tds.append(f"<td>{pair_html}</td>")
            else:
                v=row[c]
                if isinstance(v, float):
                    tds.append(f"<td>{v:.6g}</td>")
                else:
                    tds.append(f"<td>{_html.escape(str(v))}</td>")
        rows.append(f"<tr class='{cls}'>"+"".join(tds)+"</tr>")

    html_block=f"""
    <div id="{top_id}" class="top-scrollbar"><div class="spacer"></div></div>
    <div id="{wrap_id}" style="overflow-x:auto; width:100%;">
      <table class="mv-table" id="{table_id}">
        <thead>{thead}</thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>
    """
    st.markdown(html_block, unsafe_allow_html=True)
    components.html(f"""
    <script>
      window.mvMakeSortable("{table_id}");
      window.mvInitTopScroll("{top_id}", "{wrap_id}", "{table_id}");
      window.mvBindRowExtras("{table_id}");
    </script>
    """, height=0, width=0)


# ---------------- Email/Webhook alerts
def send_email_alert(subject, body, recipient):
    try: cfg=st.secrets["smtp"]
    except Exception: return False, "SMTP not configured in st.secrets"
    try:
        msg=MIMEMultipart(); msg["From"]=cfg["sender"]; msg["To"]=recipient; msg["Subject"]=subject
        msg.attach(MIMEText(body,"plain"))
        ctx=ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg["host"], cfg.get("port",465), context=ctx) as s:
            s.login(cfg["user"], cfg["password"]); s.sendmail(cfg["sender"], recipient, msg.as_string())
        return True, "Email sent"
    except Exception as e:
        return False, f"Email error: {e}"

def post_webhook(url, payload):
    try:
        r=requests.post(url, json=payload, timeout=10); ok=(200<=r.status_code<300)
        return ok, (r.text if not ok else "OK")
    except Exception as e:
        return False, str(e)


# ---------------- UI
st.set_page_config(page_title="Crypto Tracker", layout="wide")
st.title(f"Crypto Tracker — {APP_VERSION}")

with st.sidebar:
    if st.button("Collapse all open menu tabs"):
        st.session_state["collapse_all_now"]=True
        st.rerun()

def expander(title):
    opened = not st.session_state.get("collapse_all_now", False)
    return st.expander(title, expanded=opened)

with st.sidebar:
    with expander("Market"):
        exchange = st.selectbox("Exchange", ["Coinbase","Binance","Kraken (coming soon)","KuCoin (coming soon)"], index=0)
        effective_exchange = exchange if "coming soon" not in exchange else "Coinbase"
        if "coming soon" in exchange: st.info("This exchange is coming soon. Using Coinbase for data.")
        quote    = st.selectbox("Quote currency", ["USD","USDC","USDT","BTC","ETH","EUR"], index=0)
        use_watch= st.checkbox("Use watchlist only", value=False)
        watchlist= st.text_area("Watchlist (comma-separated)", "BTC-USD, ETH-USD, SOL-USD")
        max_pairs= st.slider("Max pairs", 10, 1000, 200, 10)

with st.sidebar:
    with expander("Timeframes"):
        pick_tfs = st.multiselect("Select timeframes", ["1m","5m","15m","30m","1h","4h","6h","12h","1d","1w"],
                                  default=["1m","5m","15m","30m","1h","4h","6h","12h","1d"])
        sort_tf  = st.selectbox("Primary sort timeframe", pick_tfs, index=pick_tfs.index("1h") if "1h" in pick_tfs else 0)
        sort_desc= st.checkbox("Sort descending (largest first)", value=True)

with st.sidebar:
    with expander("Gates"):
        pct_thresh = st.slider("Min +% change (Sort TF)", 0.0, 20.0, 0.3, 0.1)
        st.caption("💡 Lower this if nothing shows.")
        use_spike  = st.checkbox("Use Volume spike (20SMA ×)", value=True)
        spike_mult = st.slider("Spike multiple", 1.0, 10.0, 1.05, 0.05)
        st.caption("💡 Reduce to ~1.05× if too few pass.")

with st.sidebar:
    with expander("History depth"):
        basis = st.selectbox("Basis for ATH/ATL & recent-high", ["Hourly","Daily","Weekly"], index=1)
        amount = st.slider({"Hourly":"Hours (≤72)","Daily":"Days (≤365)","Weekly":"Weeks (≤52)"}[basis],
                           1, {"Hourly":72,"Daily":365,"Weekly":52}[basis], {"Hourly":24,"Daily":90,"Weekly":12}[basis], 1)

with st.sidebar:
    with expander("Display"):
        wrap = st.checkbox("Wrap text (show full cell text)", value=False)
        col_min = st.slider("Column min width (px)", 120, 360, 160, 10)
        font_scale = st.slider("Font scale", 0.8, 1.6, 1.0, 0.05)

with st.sidebar:
    with expander("Notifications"):
        enable_sound = st.checkbox("Audible chime", value=True)
        if st.button("Test beep"): components.html("<script>window.parent.mvBeepNow && window.parent.mvBeepNow();</script>", height=0, width=0)
        email_to = st.text_input("Email recipient (optional)", "")
        webhook_url = st.text_input("Webhook URL (optional)", "")

with st.sidebar:
    with expander("Auto-refresh"):
        auto_refresh = st.checkbox("Enable auto-refresh", value=False)
        refresh_sec  = st.slider("Interval (seconds)", 5, 120, 30, 1)
        if auto_refresh:
            components.html(f"<script>window.parent._mv_autoref && clearInterval(window.parent._mv_autoref); window.parent._mv_autoref=setInterval(()=>window.parent.location.reload(), {refresh_sec*1000});</script>", height=0, width=0)
        else:
            components.html("<script>if(window.parent._mv_autoref){clearInterval(window.parent._mv_autoref); window.parent._mv_autoref=null;}</script>", height=0, width=0)

# reset collapse flag
st.session_state["collapse_all_now"]=False

# Inject CSS & JS
inject_css(font_scale, col_min, wrap)
inject_global_js()

# Label
st.subheader(f"Timeframe: {sort_tf}")

# Discover pairs
if use_watch and watchlist.strip():
    pairs=[p.strip().upper() for p in watchlist.split(",") if p.strip()]
else:
    pairs=list_products(effective_exchange, quote)
pairs=[p for p in pairs if p.endswith(f"-{quote}")]
pairs=pairs[:max_pairs]
if not pairs:
    st.info("No pairs found. Try different Quote, uncheck Watchlist-only, or increase Max pairs.")
    st.stop()

# Build core dataset
rows=[]
volx_series=[]
candle_cache={}
for pid in pairs:
    dft = df_for_tf(effective_exchange, pid, sort_tf)
    if dft is None or len(dft)<30:
        continue
    dft=dft.tail(300).copy()
    last=float(dft["close"].iloc[-1]); first=float(dft["close"].iloc[0])
    pct=(last/first-1)*100.0
    volx=float(dft["volume"].iloc[-1]/(dft["volume"].rolling(20).mean().iloc[-1]+1e-9))
    volx_series.append((pid,volx))

    # recent-high & trend
    pct_since_high, since_high = recent_high_metrics(dft[["ts","close"]], span=5)
    tb, since_break = trend_breakout_info(dft[["ts","close"]], span=5)

    # ATH/ATL
    hist=get_hist(effective_exchange, pid, basis, amount)
    if hist is None or len(hist)<10:
        athp, athd, atlp, atld = np.nan, "—", np.nan, "—"
    else:
        aa=ath_atl_info(hist)
        athp, athd, atlp, atld = aa["From ATH %"], aa["ATH date"], aa["From ATL %"], aa["ATL date"]

    # prep chart cache (150 last bars)
    lite=dft.tail(150)
    arr=[{"time":int(pd.to_datetime(t).timestamp()),"open":float(o),"high":float(h),"low":float(l),"close":float(c)}
         for t,o,h,l,c in zip(lite["ts"], lite["open"], lite["high"], lite["low"], lite["close"])]
    sym=tv_symbol(effective_exchange, pid)
    if sym: candle_cache[sym]=arr

    rows.append({"Pair":pid, "Price":last, f"% change ({sort_tf})":pct,
                 "From ATH %":athp, "ATH date":athd, "From ATL %":atlp, "ATL date":atld,
                 "Trend broken?":tb, "Broken since":since_break})

if not rows:
    st.info("No data returned. Loosen gates or pick another timeframe.")
    st.stop()

disp=pd.DataFrame(rows)
# Join vol spike series
volx_map=dict(volx_series)
disp["Vol x (20SMA)"] = disp["Pair"].map(volx_map)

# Sorting default by % change
sort_label=f"% change ({sort_tf})"
disp=disp.sort_values(sort_label, ascending=not sort_desc, na_position="last").reset_index(drop=True)
disp.insert(0, "#", disp.index+1)

# Build masks for gates
green_mask, yellow_mask = build_masks(disp, sort_label, pct_thresh, use_spike, spike_mult, disp["Vol x (20SMA)"])

# Push candle cache to JS (parent)
components.html(f"<script>window.parent._mvCandleCache = {json.dumps(candle_cache)};</script>", height=0, width=0)

# Top‑10 (ALL gates)
st.subheader("📌 Top‑10 (ALL gates)")
top_now = disp.loc[green_mask].sort_values(sort_label, ascending=not sort_desc, na_position="last").head(10).reset_index(drop=True)
if top_now.empty:
    st.write("—")
    st.caption("💡 Nothing? Lower +%, reduce Spike×, or disable Spike gate.")
else:
    render_table_html(top_now, pd.Series([True]*len(top_now)), pd.Series([False]*len(top_now)),
                      effective_exchange, sort_tf, "top")

# All pairs
st.subheader("📑 All pairs (ranked)")
render_table_html(disp, green_mask, yellow_mask, effective_exchange, sort_tf, "main")

# Alerts
log_lines=[]
if not top_now.empty:
    for _, r in top_now.iterrows():
        key=f"TOP10|{r['Pair']}|{sort_tf}|{round(float(r[sort_label]),2)}"
        if key not in st.session_state["last_alert_hashes"]:
            st.session_state["last_alert_hashes"].add(key)
            log_lines.append(f"Top‑10: {r['Pair']} {float(r[sort_label]):+.2f}%")

if log_lines:
    if enable_sound:
        components.html("<script>window.parent.mvBeepNow && window.parent.mvBeepNow();</script>", height=0, width=0)
    sub=f"[{effective_exchange}] Crypto Tracker alerts"
    if email_to:
        ok, info=send_email_alert(sub, "\n".join(log_lines), email_to)
        if not ok: st.warning(info)
    if webhook_url:
        ok, info=post_webhook(webhook_url, {"title": sub, "lines": log_lines})
        if not ok: st.warning(f"Webhook error: {info}")
    st.session_state["alert_log"]=(st.session_state["alert_log"]+ [sub]+log_lines)[-30:]

if st.session_state.get("alert_log"):
    with st.expander("Alert log (last 30)", expanded=False):
        for line in st.session_state["alert_log"]:
            st.write(line)

st.caption(f"Pairs: {len(disp)} • Exchange: {effective_exchange} • Quote: {quote} • Sort TF: {sort_tf} • Mode: REST • "
           f"Gates: %+≥{pct_thresh}, Spike×{spike_mult if use_spike else 'off'}")

