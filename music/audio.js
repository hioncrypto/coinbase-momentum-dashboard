/**
 * Per-song tone profiles — quieter, matched to each track's character.
 */
window.MusicAudio = (function () {
  const GUITAR_ROOT = {
    C: 65.41, "C#": 69.3, Db: 69.3, D: 73.42, "D#": 77.78, Eb: 77.78,
    E: 82.41, F: 87.31, "F#": 92.5, Gb: 92.5, G: 98.0, "G#": 103.83, Ab: 103.83,
    A: 110.0, "A#": 116.54, Bb: 116.54, B: 123.47,
  };

  /** Song → amp / dynamics character */
  const PROFILES = {
    over_the_mountain: {
      name: "Rhoads crunch",
      drive: 90, pre: 0.28, master: 0.16,
      midHz: 900, midGain: 4, presence: 2, lowpass: 4200,
      attack: 0.012, sustain: 0.55, release: 0.85,
      voicing: "power", detune: 1.002, osc: "sawtooth",
    },
    diary_of_a_madman: {
      name: "Rhoads dark / gothic",
      drive: 70, pre: 0.24, master: 0.14,
      midHz: 700, midGain: 3, presence: 0.5, lowpass: 3200,
      attack: 0.04, sustain: 0.65, release: 1.15,
      voicing: "power", detune: 1.0015, osc: "sawtooth",
    },
    mr_crowley: {
      name: "Classical metal + organ body",
      drive: 55, pre: 0.22, master: 0.15,
      midHz: 850, midGain: 5, presence: 1.5, lowpass: 3800,
      attack: 0.025, sustain: 0.6, release: 1.0,
      voicing: "triad", detune: 1.002, osc: "sawtooth", organ: true,
    },
    the_trooper: {
      name: "Maiden Marshall gallop",
      drive: 75, pre: 0.26, master: 0.15,
      midHz: 1100, midGain: 3.5, presence: 4, lowpass: 5000,
      attack: 0.006, sustain: 0.4, release: 0.7,
      voicing: "power", detune: 1.004, osc: "sawtooth", twin: true,
    },
      aces_high: {
      name: "Maiden scramble / anthem",
      drive: 80, pre: 0.25, master: 0.15,
      midHz: 1050, midGain: 3, presence: 4.5, lowpass: 5200,
      attack: 0.005, sustain: 0.35, release: 0.65,
      voicing: "power", detune: 1.004, osc: "sawtooth", twin: true, staccato: true,
    },
    rime_of_the_ancient_mariner: {
      name: "Maiden epic / storm theater",
      drive: 72, pre: 0.24, master: 0.14,
      midHz: 1000, midGain: 3.2, presence: 3.5, lowpass: 4800,
      attack: 0.01, sustain: 0.5, release: 1.05,
      voicing: "power", detune: 1.0035, osc: "sawtooth", twin: true,
    },
    surfing_with_the_alien: {
      name: "Satriani singing mid-gain",
      drive: 45, pre: 0.22, master: 0.13,
      midHz: 950, midGain: 5, presence: 3, lowpass: 4500,
      attack: 0.018, sustain: 0.62, release: 1.05,
      voicing: "triad", detune: 1.003, osc: "sawtooth", organ: true,
    },
    voodoo_child: {
      name: "Hendrix wah + fuzz Marshall",
      drive: 85, pre: 0.26, master: 0.14,
      midHz: 800, midGain: 6, presence: 3, lowpass: 4800,
      attack: 0.008, sustain: 0.5, release: 0.9,
      voicing: "power", detune: 1.004, osc: "sawtooth",
    },
    desert_rose: {
      name: "Desert Rose pads / soft edge",
      drive: 12, pre: 0.2, master: 0.12,
      midHz: 700, midGain: 2, presence: 0, lowpass: 3600,
      attack: 0.05, sustain: 0.72, release: 1.35,
      voicing: "triad", detune: 1.0015, osc: "triangle", organ: true,
    },
    mozart_k581: {
      name: "Clarinet chamber clean",
      drive: 0, pre: 0.35, master: 0.12,
      midHz: 1200, midGain: 1, presence: -2, lowpass: 2800,
      attack: 0.06, sustain: 0.7, release: 1.4,
      voicing: "triad", detune: 1.0008, osc: "triangle", clean: true,
    },
    default: {
      name: "Neutral soft crunch",
      drive: 40, pre: 0.2, master: 0.12,
      midHz: 900, midGain: 2, presence: 1, lowpass: 4000,
      attack: 0.02, sustain: 0.5, release: 0.9,
      voicing: "power", detune: 1.002, osc: "sawtooth",
    },
  };

  let ctx = null;
  let enabled = true;
  let lastPlayed = null;
  let lastAt = 0;
  let bus = null;
  let profileId = "default";

  function makeDistortionCurve(amount) {
    const n = 2048;
    const curve = new Float32Array(n);
    const k = Math.max(1, amount);
    for (let i = 0; i < n; i++) {
      const x = (i * 2) / n - 1;
      if (amount < 1) {
        curve[i] = x; // bypass-ish
      } else {
        curve[i] = Math.tanh(((1 + k) * x) / (1 + k * Math.abs(x)) * 1.4);
      }
    }
    return curve;
  }

  function ensure() {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    if (!ctx) {
      ctx = new AC();
      const pre = ctx.createGain();
      const dist = ctx.createWaveShaper();
      dist.oversample = "2x";
      const lowcut = ctx.createBiquadFilter();
      lowcut.type = "highpass";
      lowcut.frequency.value = 65;
      const mid = ctx.createBiquadFilter();
      mid.type = "peaking";
      mid.Q.value = 1;
      const presence = ctx.createBiquadFilter();
      presence.type = "highshelf";
      presence.frequency.value = 2400;
      const lowpass = ctx.createBiquadFilter();
      lowpass.type = "lowpass";
      lowpass.Q.value = 0.7;
      const master = ctx.createGain();
      const dry = ctx.createGain();
      dry.gain.value = 0;

      pre.connect(dist);
      dist.connect(lowcut);
      lowcut.connect(mid);
      mid.connect(presence);
      presence.connect(lowpass);
      lowpass.connect(master);
      // Clean path for Mozart
      pre.connect(dry);
      dry.connect(master);
      master.connect(ctx.destination);

      bus = { pre, dist, mid, presence, lowpass, master, dry };
      applyProfile("default");
    }
    if (ctx.state === "suspended") ctx.resume();
    return ctx;
  }

  function profile() {
    return PROFILES[profileId] || PROFILES.default;
  }

  function applyProfile(id) {
    profileId = PROFILES[id] ? id : "default";
    const p = profile();
    ensure();
    if (!bus) return p;
    bus.pre.gain.value = p.pre;
    bus.master.gain.value = p.master;
    bus.dist.curve = makeDistortionCurve(p.drive);
    bus.mid.frequency.value = p.midHz;
    bus.mid.gain.value = p.midGain;
    bus.presence.gain.value = p.presence;
    bus.lowpass.frequency.value = p.lowpass;
    // Clean songs: more dry, less dist
    if (p.clean) {
      bus.dry.gain.value = 0.85;
      bus.pre.gain.value = p.pre * 0.35;
    } else {
      bus.dry.gain.value = 0.05;
    }
    return p;
  }

  function setSong(songId) {
    return applyProfile(songId || "default");
  }

  function rootName(key) {
    const s = String(key || "").trim();
    return s.endsWith("m") ? s.slice(0, -1) : s.replace(/maj$/i, "").replace(/°/g, "");
  }

  function isMinor(key) {
    return String(key || "").trim().endsWith("m");
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

  function stringHit(freq, when, dur, gain, p) {
    const audio = ensure();
    if (!audio || !bus || freq == null) return;
    const osc = audio.createOscillator();
    const osc2 = audio.createOscillator();
    const g = audio.createGain();
    const filter = audio.createBiquadFilter();

    osc.type = p.osc || "sawtooth";
    osc2.type = p.osc || "sawtooth";
    osc.frequency.setValueAtTime(freq, when);
    osc2.frequency.setValueAtTime(freq * (p.detune || 1.002), when);

    filter.type = "lowpass";
    const bright = p.clean ? 2400 : 3600;
    const dark = p.clean ? 1400 : 1400;
    filter.frequency.setValueAtTime(bright, when);
    filter.frequency.exponentialRampToValueAtTime(dark, when + Math.min(0.4, dur * 0.45));
    filter.Q.value = p.twin ? 1.4 : 0.9;

    const peak = (gain == null ? 0.28 : gain) * (p.staccato ? 0.9 : 1);
    const d = dur || p.release || 0.9;
    const atk = p.attack || 0.015;
    g.gain.setValueAtTime(0.0001, when);
    g.gain.exponentialRampToValueAtTime(peak, when + atk);
    g.gain.exponentialRampToValueAtTime(peak * (p.sustain || 0.5), when + atk + d * 0.2);
    g.gain.exponentialRampToValueAtTime(0.0001, when + d);

    osc.connect(filter);
    osc2.connect(filter);
    filter.connect(g);
    g.connect(bus.pre);

    osc.start(when);
    osc2.start(when);
    osc.stop(when + d + 0.05);
    osc2.stop(when + d + 0.05);

    // Soft organ body for Crowley
    if (p.organ) {
      const o = audio.createOscillator();
      const og = audio.createGain();
      o.type = "sine";
      o.frequency.setValueAtTime(freq * 2, when);
      og.gain.setValueAtTime(0.0001, when);
      og.gain.exponentialRampToValueAtTime(peak * 0.12, when + 0.05);
      og.gain.exponentialRampToValueAtTime(0.0001, when + d);
      o.connect(og);
      og.connect(bus.pre);
      o.start(when);
      o.stop(when + d + 0.05);
    }
  }

  function playKey(key, opts) {
    opts = opts || {};
    if (!enabled) return false;
    const audio = ensure();
    if (!audio) return false;
    const p = profile();

    let root = freqFor(key);
    if (root == null) return false;

    const t = performance.now();
    if (opts.scrub && lastPlayed === key && t - lastAt < 100) return false;
    lastPlayed = key;
    lastAt = t;

    // Mozart sits higher / clearer; metal in guitar register
    if (p.clean) {
      while (root < 130) root *= 2;
      while (root > 320) root *= 0.5;
    } else {
      while (root > 170) root *= 0.5;
      while (root < 55) root *= 2;
    }

    const now = audio.currentTime + 0.01;
    const scrub = !!opts.scrub;
    let dur = opts.dur || (scrub ? p.release * 0.55 : p.release);
    if (p.staccato && scrub) dur *= 0.7;
    const gScale = (opts.gainScale || 1) * 0.75; // overall tone-down

    if (p.voicing === "triad" || p.clean) {
      const third = isMinor(key) ? 3 : 4;
      stringHit(root, now, dur, 0.28 * gScale, p);
      stringHit(root * Math.pow(2, third / 12), now + 0.03, dur * 0.95, 0.2 * gScale, p);
      stringHit(root * Math.pow(2, 7 / 12), now + 0.05, dur * 0.9, 0.18 * gScale, p);
    } else {
      // Power chord, quieter
      stringHit(root, now, dur, 0.3 * gScale, p);
      stringHit(root * Math.pow(2, 7 / 12), now + 0.015, dur, 0.24 * gScale, p);
      stringHit(root * 2, now + 0.025, dur * 0.9, 0.14 * gScale, p);
      if (p.twin) {
        stringHit(root * Math.pow(2, (isMinor(key) ? 3 : 4) / 12), now + 0.04, dur * 0.8, 0.08 * gScale, p);
      }
    }
    return true;
  }

  function playKeys(keys, gapMs) {
    const p = profile();
    const list = (keys || []).filter(Boolean);
    const gap = gapMs == null ? (p.staccato ? 240 : 320) : gapMs;
    list.forEach((k, i) => {
      setTimeout(() => playKey(k, { dur: p.release * 0.85 }), i * gap);
    });
  }

  function playChord(rootKey, quality) {
    const key =
      quality === "min" || quality === "dim"
        ? rootName(rootKey) + "m"
        : rootName(rootKey);
    playKey(key, { dur: profile().release * 1.1, gainScale: 0.9 });
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
    setEnabled,
    unlock,
    bindWheel,
    freqFor,
    setSong,
    applyProfile,
    PROFILES,
  };
})();
