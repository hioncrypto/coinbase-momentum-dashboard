# Music Teacher

Standalone music-learning project — **not** part of the crypto scanner.

Interactive teacher for song analysis:

- **Song Lab** — twelve analysis lenses (pitch, melody, rhythm, articulation, form, texture, dynamics, timbre, technique, lyrics, style, effect)
- **Circle of Fifths** — section-by-section harmonic map
- **Lessons** — Aeolian cadence, modes, articulation storytelling, and more
- **Drills** — quick quizzes drawn from the song catalog

## Songs included

| Song | Focus |
|------|--------|
| Over the Mountain (Ozzy) | G♯ Aeolian · VI–VII–i |
| Diary of a Madman (Ozzy) | Odd meters · Hungarian minor |
| Mr. Crowley (Ozzy) | D minor RR comparison |
| The Trooper (Iron Maiden) | Gallop · twin leads |
| Aces High (Iron Maiden) | Staccato → legato articulation |
| Clarinet Quintet K.581 (Mozart) | Ionian / parallel Aeolian |

## How to open

### Phone (easiest)

After this branch is pushed, open:

`https://htmlpreview.github.io/?https://raw.githubusercontent.com/hioncrypto/coinbase-momentum-dashboard/cursor/music-teacher-0b84/music/index.html`

### Desktop

1. Download `music/index.html` + `music/songs.js` (keep them in the same folder), **or** clone this branch.
2. Double-click `index.html`, or run:

```bash
python -m http.server 8765 --directory music
# http://localhost:8765/
```

### Deep links

- Song Lab, Aces High articulation: `index.html?view=lab&song=aces_high&lens=articulation`
- Circle, Trooper chorus: `index.html?view=circle&song=the_trooper&section=chorus`
- Standalone circle page: `circle_of_fifths.html?song=mr_crowley`

## Files

```
music/
  index.html              ← Music Teacher app
  songs.js                ← catalog + lens analyses
  circle_of_fifths.html   ← standalone circle (legacy-friendly)
  README.md
  HOW_TO_OPEN.txt
```
