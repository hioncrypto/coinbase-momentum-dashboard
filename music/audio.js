/**
 * Heavy distorted guitar voice for Music Teacher circle pages.
 * Power chords + waveshaping overdrive — not piano.
 */
window.MusicAudio = (function () {
  const FREQ = {
    C: 82.41, "C#": 87.31, Db: 87.31, D: 92.5, "D#": 98.0, Eb: 98.0,
    E: 110.0, F: 116.54, "F#": 123.47, Gb: 123.47, G: 98.0, "G#": 103.83, Ab: 103.83,
    A: 110.0, "A#": 116.54, Bb: 116.54, B: 123.47,
  };
  // Guitar-range roots (approx dropped / low register)
  const GUITAR_ROOT = {
    C: 65.41, "C#": 69.3, Db: 69.3, D: 73.42, "D#": 77.78, Eb: 77.78,
    E: 82.41, F: 87.31, "F#": 92.5, Gb: 92.5, G: 98.0, "G#": 103.83, Ab: 103.83,
    A: 110.0, "A#": 116.54, Bb: 116.54, B: 123.47,
  };

  let ctx = null;
  let enabled = true;
  let lastPlayed = null;
  let lastAt = 0;
  let bus = null;

  function makeDistortionCurve(amount) {
    const n = 2048;
    const curve = new Float32Array(n);
    const k = amount;
    for (let i = 0; i < n; i++) {
      const x = (i * 2) / n - 1;
      // Hard clip + asymmetric drive = amp grit
      const driven = ((1 + k) * x) / (1 + k * Math.abs(x));
      curve[i] = Math.tanh(driven * 2.2);
    }
    return curve;
  }

  function ensure() {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    if (!ctx) {
      ctx = new AC();
      // Guitar amp bus: pre → dist → EQ → master
      const pre = ctx.createGain();
      pre.gain.value = 0.55;

      const dist = ctx.createWaveShaper();
      dist.curve = makeDistortionCurve(280);
      dist.oversample = "4x";

      const mid = ctx.createBiquadFilter();
      mid.type = "peaking";
      mid.frequency.value = 800;
      mid.Q.value = 1.1;
      mid.gain.value = 6;

      const presence = ctx.createBiquadFilter();
      presence.type = "highshelf";
      presence.frequency.value = 2500;
      presence.gain.value = 3.5;

      const lowcut = ctx.createBiquadFilter();
      lowcut.type = "highpass";
      lowcut.frequency.value = 70;

      const lowpass = ctx.createBiquadFilter();
      lowpass.type = "lowpass";
      lowpass.frequency.value = 5500;
      lowpass.Q.value = 0.7;

      const master = ctx.createGain();
      master.gain.value = 0.38;

      pre.connect(dist);
      dist.connect(lowcut);
      lowcut.connect(mid);
      mid.connect(presence);
      presence.connect(lowpass);
      lowpass.connect(master);
      master.connect(ctx.destination);

      bus = { pre, dist, master };
    }
    if (ctx.state === "suspended") ctx.resume();
    return ctx;
  }

  function rootName(key) {
    const s = String(key || "").trim();
    return s.endsWith("m") ? s.slice(0, -1) : s.replace(/maj$/i, "").replace(/°/g, "");
  }

  function isMinor(key) {
    const s = String(key || "").trim();
    return s.endsWith("m");
  }

  function freqFor(key) {
    const root = rootName(key);
    let f = GUITAR_ROOT[root];
    if (!f) {
      const alt = { "D#": "Eb", "G#": "Ab", "A#": "Bb", "C#": "Db", Gb: "F#" };
      f = GUITAR_ROOT[alt[root]];
    }
    return f || null;
  }

  /** One distorted string / oscillator into the amp bus */
  function stringHit(freq, when, dur, gain) {
    const audio = ensure();
    if (!audio || !bus || freq == null) return;

    const osc = audio.createOscillator();
    const osc2 = audio.createOscillator(); // slight detune = thicker stack
    const g = audio.createGain();
    const filter = audio.createBiquadFilter();

    osc.type = "sawtooth";
    osc2.type = "sawtooth";
    osc.frequency.setValueAtTime(freq, when);
    osc2.frequency.setValueAtTime(freq * 1.003, when);

    // Pick attack: bright then darken (pick → sustain)
    filter.type = "lowpass";
    filter.frequency.setValueAtTime(4200, when);
    filter.frequency.exponentialRampToValueAtTime(1600, when + Math.min(0.35, dur * 0.4));
    filter.Q.value = 1.2;

    const peak = gain == null ? 0.45 : gain;
    const d = dur || 0.9;
    // Aggressive pick attack, then amp sustain/decay
    g.gain.setValueAtTime(0.0001, when);
    g.gain.exponentialRampToValueAtTime(peak, when + 0.008);
    g.gain.exponentialRampToValueAtTime(peak * 0.7, when + 0.12);
    g.gain.exponentialRampToValueAtTime(peak * 0.25, when + d * 0.55);
    g.gain.exponentialRampToValueAtTime(0.0001, when + d);

    osc.connect(filter);
    osc2.connect(filter);
    filter.connect(g);
    g.connect(bus.pre);

    osc.start(when);
    osc2.start(when);
    osc.stop(when + d + 0.05);
    osc2.stop(when + d + 0.05);
  }

  /**
   * Power chord (root + fifth + octave) — metal guitar default.
   * Minor keys add a dark minor third quietly; majors keep pure power chord.
   */
  function playKey(key, opts) {
    opts = opts || {};
    if (!enabled) return false;
    const audio = ensure();
    if (!audio) return false;

    let root = freqFor(key);
    if (root == null) return false;

    const t = performance.now();
    if (opts.scrub && lastPlayed === key && t - lastAt < 95) return false;
    lastPlayed = key;
    lastAt = t;

    // Keep guitar range sensible
    while (root > 180) root *= 0.5;
    while (root < 55) root *= 2;

    const now = audio.currentTime + 0.01;
    const scrub = !!opts.scrub;
    const dur = opts.dur || (scrub ? 0.55 : 1.05);
    const gScale = opts.gainScale || 1;

    // Power chord voices
    stringHit(root, now, dur, 0.5 * gScale);                    // root
    stringHit(root * Math.pow(2, 7 / 12), now + 0.012, dur, 0.42 * gScale); // fifth
    stringHit(root * 2, now + 0.02, dur * 0.95, 0.28 * gScale);  // octave

    // Color: quiet third for major/minor flavor under the distortion
    if (!opts.powerOnly) {
      const thirdSemis = isMinor(key) ? 3 : 4;
      stringHit(root * Math.pow(2, thirdSemis / 12), now + 0.03, dur * 0.85, 0.12 * gScale);
    }
    return true;
  }

  function playKeys(keys, gapMs) {
    const list = (keys || []).filter(Boolean);
    const gap = gapMs == null ? 300 : gapMs;
    list.forEach((k, i) => {
      setTimeout(() => playKey(k, { dur: 0.85 }), i * gap);
    });
  }

  function playChord(rootKey, quality) {
    // Force minor/major color from quality for diatonic chips
    const key =
      quality === "min" || quality === "dim"
        ? rootName(rootKey) + "m"
        : rootName(rootKey);
    playKey(key, { dur: 1.15, gainScale: 1.05 });
  }

  function playFreq(freq, dur, gain) {
    const audio = ensure();
    if (!audio || !enabled) return;
    stringHit(freq, audio.currentTime + 0.01, dur || 0.8, gain == null ? 0.4 : gain);
  }

  function setEnabled(on) {
    enabled = !!on;
    if (on) ensure();
  }

  function unlock() {
    const audio = ensure();
    if (!audio) return Promise.resolve(false);
    return audio.resume().then(() => audio.state === "running");
  }

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
      const clientX = e.touches && e.touches[0] ? e.touches[0].clientX : e.clientX;
      const clientY = e.touches && e.touches[0] ? e.touches[0].clientY : e.clientY;
      const top = document.elementFromPoint(clientX, clientY);
      const wedge = top && top.closest && top.closest(".key-wedge");
      if (wedge && wedge.dataset.key) {
        const key = wedge.dataset.key;
        if (playKey(key, { scrub: true }) && options.onKey) options.onKey(key, e);
      }
    }

    function onUp() { scrubbing = false; }

    svg.addEventListener("pointerdown", onDown);
    svg.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
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
