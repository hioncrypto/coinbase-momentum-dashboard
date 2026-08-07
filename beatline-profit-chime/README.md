# BeatLine profit chime patch

Branch: `cursor/profit-chime-once-78aa` (committed locally; push to hioncrypto/beatline was 403).

## Behavior
- Soft major arpeggio when open unrealized P/L first crosses **above \$0**
- Does **not** re-chime while already green / rising
- Re-arms only if P/L goes flat or red, then green again
- Uses the same Alerts bell toggle as other chimes
- Options → Test plays target chime, then the profit tone

## Files
- `app.js` / `index.html` — drop into BeatLine `static/` (app.js cache `?v=9.53`)
