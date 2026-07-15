/**
 * Shared Web Audio helpers for Music Teacher circle pages.
 * Every key/note tap should call MusicAudio.playKey(key).
 */
window.MusicAudio = (function () {
  const FREQ = {
    C: 261.63, "C#": 277.18, Db: 277.18, D: 293.66, "D#": 311.13, Eb: 311.13,
    E: 329.63, F: 349.23, "F#": 369.99, Gb: 369.99, G: 392.0, "G#": 415.3, Ab: 415.3,
    A: 440.0, "A#": 466.16, Bb: 466.16, B: 493.88,
  };

  let ctx = null;
  let enabled = true;
  let lastPlayed = null;
  let lastAt = 0;

  function ensure() {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    if (!ctx) ctx = new AC();
    if (ctx.state === "suspended") ctx.resume();
    return ctx;
  }

  function rootName(key) {
    const s = String(key || "").trim();
    return s.endsWith("m") ? s.slice(0, -1) : s.replace(/maj$/i, "");
  }

  function isMinor(key) {
    return String(key || "").trim().endsWith("m");
  }

  function freqFor(key) {
    const root = rootName(key);
    let f = FREQ[root];
    if (!f) {
      const alt = { "D#": "Eb", "G#": "Ab", "A#": "Bb", "C#": "Db", Gb: "F#" };
      f = FREQ[alt[root]] || FREQ[root];
    }
    if (!f) return null;
    // Minors sound an octave lower so major/minor rings feel distinct
    return isMinor(key) ? f * 0.5 : f;
  }

  function playFreq(freq, dur, gain, type) {
    if (!enabled || freq == null) return;
    const audio = ensure();
    if (!audio) return;
    const osc = audio.createOscillator();
    const g = audio.createGain();
    osc.type = type || "triangle";
    osc.frequency.value = freq;
    const now = audio.currentTime;
    const d = dur || 0.45;
    const vol = gain == null ? 0.2 : gain;
    g.gain.setValueAtTime(0.0001, now);
    g.gain.exponentialRampToValueAtTime(vol, now + 0.02);
    g.gain.exponentialRampToValueAtTime(0.0001, now + d);
    osc.connect(g);
    g.connect(audio.destination);
    osc.start(now);
    osc.stop(now + d + 0.03);
  }

  function playKey(key, opts) {
    opts = opts || {};
    if (!enabled) return false;
    const f = freqFor(key);
    if (f == null) return false;
    // Debounce identical repeats while scrubbing
    const t = performance.now();
    if (opts.scrub && lastPlayed === key && t - lastAt < 90) return false;
    lastPlayed = key;
    lastAt = t;
    playFreq(f, opts.dur || 0.4, opts.gain, opts.type);
    return true;
  }

  function playKeys(keys, gapMs) {
    const list = (keys || []).filter(Boolean);
    const gap = gapMs == null ? 220 : gapMs;
    list.forEach((k, i) => {
      setTimeout(() => playKey(k, { dur: 0.35 }), i * gap);
    });
  }

  function playChord(rootKey, quality) {
    const base = freqFor(isMinor(rootKey) ? rootName(rootKey) : rootKey);
    if (base == null) return;
    // Use mid octave for chords
    const root = freqFor(rootName(rootKey)) || base;
    const third =
      quality === "maj" ? root * Math.pow(2, 4 / 12)
      : quality === "dim" ? root * Math.pow(2, 3 / 12)
      : root * Math.pow(2, 3 / 12);
    const fifth =
      quality === "dim" ? root * Math.pow(2, 6 / 12) : root * Math.pow(2, 7 / 12);
    [root * 0.5, third * 0.5, fifth * 0.5].forEach((f, i) => {
      setTimeout(() => playFreq(f, 0.65, 0.12), i * 16);
    });
  }

  function setEnabled(on) {
    enabled = !!on;
    if (on) ensure();
  }

  function unlock() {
    ensure();
  }

  /**
   * Make every .key-wedge in an SVG play its data-key on pointer.
   * Supports tap + drag-scrub across notes.
   */
  function bindWheel(svg, options) {
    options = options || {};
    if (!svg || svg.dataset.audioBound === "1") return;
    svg.dataset.audioBound = "1";
    let scrubbing = false;

    function keyFromEvent(e) {
      const el = e.target.closest && e.target.closest(".key-wedge");
      return el ? el.dataset.key : null;
    }

    function onDown(e) {
      unlock();
      scrubbing = true;
      const key = keyFromEvent(e);
      if (key) {
        playKey(key, { scrub: true });
        if (options.onKey) options.onKey(key, e);
      }
    }

    function onMove(e) {
      if (!scrubbing) return;
      let clientX, clientY;
      if (e.touches && e.touches[0]) {
        clientX = e.touches[0].clientX;
        clientY = e.touches[0].clientY;
      } else {
        clientX = e.clientX;
        clientY = e.clientY;
      }
      const top = document.elementFromPoint(clientX, clientY);
      const wedge = top && top.closest && top.closest(".key-wedge");
      if (wedge && wedge.dataset.key) {
        const key = wedge.dataset.key;
        if (playKey(key, { scrub: true }) && options.onKey) {
          options.onKey(key, e);
        }
      }
    }

    function onUp() {
      scrubbing = false;
    }

    svg.addEventListener("pointerdown", onDown);
    svg.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    // Fallback for older mobile browsers
    svg.addEventListener("touchstart", (e) => {
      unlock();
      scrubbing = true;
      const key = keyFromEvent(e);
      if (key) {
        playKey(key, { scrub: true });
        if (options.onKey) options.onKey(key, e);
      }
    }, { passive: true });
  }

  return {
    playKey,
    playKeys,
    playChord,
    playFreq,
    setEnabled,
    unlock,
    bindWheel,
    freqFor,
  };
})();
