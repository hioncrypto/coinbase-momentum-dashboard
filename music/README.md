# Circle of Fifths · Song Sections

Interactive harmonic map for songs analyzed in prior sessions.

## Open

```bash
# from repo root
python -m http.server 8765 --directory music
# then visit http://localhost:8765/circle_of_fifths.html
```

Or open `music/circle_of_fifths.html` directly in a browser.

## Songs

| Song | Tonic | What the wheel shows |
|------|-------|----------------------|
| **Over the Mountain** (Ozzy) | G♯ minor | Intro → verse (i–IV) → chorus (VI–VII–i) → bridge → solo → close |
| **Diary of a Madman** (Ozzy) | G♯ minor | Altered intro, 7/8 verses, soft interlude near D♯m, Hungarian-minor solo |
| **Clarinet Quintet K. 581** (Mozart) | A major | I↔V, Larghetto on IV (D), parallel Am in Trio I / Var. III |

## How to use

1. Pick a song from the dropdown.
2. Click each **section** — active keys light on the circle; dashed arcs show the progression path.
3. Use ←/→ or ↑/↓ to step through sections.

Majors sit on the outer ring; relative minors on the inner ring.
