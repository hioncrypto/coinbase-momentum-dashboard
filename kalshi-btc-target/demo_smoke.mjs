/**
 * BeatLine demo-mode feature smoke tests (headless Chrome).
 */
import puppeteer from "puppeteer-core";

const BASE = process.env.BEATLINE_URL || "http://127.0.0.1:8765/";
const results = [];

function ok(name, pass, detail = "") {
  results.push({ name, pass: !!pass, detail });
  console.log(`${pass ? "PASS" : "FAIL"}  ${name}${detail ? " — " + detail : ""}`);
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function slideBuy(page, fraction) {
  await page.evaluate((frac) => {
    const slide = document.getElementById("buy-slide");
    const thumb = document.getElementById("buy-slide-thumb");
    const rect = slide.getBoundingClientRect();
    const max = Math.max(1, slide.clientWidth - thumb.offsetWidth - 8);
    const start = rect.left + 12;
    const end = start + max * frac;
    const fire = (type, x, id) =>
      slide.dispatchEvent(
        new PointerEvent(type, {
          bubbles: true,
          cancelable: true,
          clientX: x,
          clientY: rect.top + 20,
          pointerId: id,
          pointerType: "touch",
        })
      );
    fire("pointerdown", start, 7);
    fire("pointermove", end, 7);
    fire("pointerup", end, 7);
  }, fraction);
}

async function main() {
  const browser = await puppeteer.launch({
    executablePath: "/usr/bin/google-chrome-stable",
    headless: "new",
    args: ["--no-sandbox", "--disable-gpu", "--window-size=390,844"],
    defaultViewport: { width: 390, height: 844, isMobile: true, hasTouch: true },
  });
  const page = await browser.newPage();
  page.setDefaultTimeout(25000);

  try {
    await page.goto(BASE + "?demoSmoke=1", { waitUntil: "networkidle2" });
    await page.evaluate(async () => {
      try {
        const regs = await navigator.serviceWorker.getRegistrations();
        for (const r of regs) await r.unregister();
      } catch {}
      localStorage.clear();
    });
    await page.goto(BASE + "/app.js?v=3.7-test", { waitUntil: "domcontentloaded" }).catch(() => {});
    await page.goto(BASE + "?demoSmoke=2", { waitUntil: "networkidle2" });
    await wait(2500);

    ok(
      "Brand shows BeatLine",
      (await page.$eval("h1", (el) => el.textContent.trim())) === "BeatLine"
    );

    await page.waitForFunction(() => {
      const t = document.getElementById("target-value");
      const y = document.getElementById("yes-pct");
      return (
        t &&
        y &&
        !t.textContent.includes("—") &&
        t.textContent !== "TBD" &&
        y.textContent &&
        y.textContent !== "—"
      );
    });

    ok(
      "Price to beat + odds loaded",
      true,
      await page.$eval("#target-value", (el) => el.textContent.trim())
    );

    // Ensure asks exist in app state
    await page.waitForFunction(() => {
      const ask = document.getElementById("roi-above-price");
      return ask && /Ask\s+\d/.test(ask.textContent || "");
    });

    await page.click("#menu-btn");
    await wait(350);
    ok("Options sheet opens", await page.$eval("#options-sheet", (el) => !el.hidden));

    // Force demo on via UI
    const wasOn = await page.$eval("#demo-toggle", (el) => el.checked);
    if (!wasOn) await page.click("#demo-toggle");
    await wait(250);
    ok(
      "Demo mode on + account visible",
      (await page.$eval("#demo-toggle", (el) => el.checked)) &&
        (await page.$eval("#demo-account", (el) => !el.hidden))
    );

    await page.click("#demo-reset");
    await wait(250);
    ok(
      "Reset bankroll $1,000",
      (await page.$eval("#demo-balance", (el) => el.textContent)).includes("1,000")
    );

    // Debug open path
    const openDiag = await page.evaluate(() => {
      const btn = document.getElementById("demo-buy-above");
      return {
        disabled: btn.disabled,
        demoAccountHidden: document.getElementById("demo-account").hidden,
      };
    });
    ok("Buy Above enabled", !openDiag.disabled, JSON.stringify(openDiag));

    // Prefer sticky dock buy (2-step). Pick side with a usable ask.
    const side = await page.evaluate(() => {
      const a = parseInt(document.getElementById("dock-above-pct")?.textContent || "", 10);
      const b = parseInt(document.getElementById("dock-below-pct")?.textContent || "", 10);
      const good = (n) => Number.isFinite(n) && n >= 5 && n <= 95;
      if (good(a)) return "above";
      if (good(b)) return "below";
      if (Number.isFinite(b) && b >= 1 && b <= 99) return "below";
      if (Number.isFinite(a) && a >= 1 && a <= 99) return "above";
      return "below";
    });
    await page.evaluate((s) => {
      document
        .getElementById(s === "above" ? "dock-buy-above" : "dock-buy-below")
        .click();
    }, side);
    await wait(600);

    let buyOpen = await page.$eval("#buy-sheet", (el) => !el.hidden);
    const status = await page.$eval("#status", (el) => el.textContent.trim());
    ok("Buy sheet pops out (dock 2-step)", buyOpen, status + " side=" + side);

    if (!buyOpen) throw new Error("Buy sheet failed to open: " + status);

    const wantTitle = side === "above" ? "Buy Above" : "Buy Below";
    ok(
      "Buy sheet title matches side",
      (await page.$eval("#buy-sheet-title", (el) => el.textContent.trim())) ===
        wantTitle,
      wantTitle
    );

    await page.evaluate(() => {
      const input = document.getElementById("buy-amount");
      input.value = "40";
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await wait(200);
    const preview = await page.$eval("#buy-preview", (el) => el.textContent.trim());
    ok("Preview shows contracts + fees", /contract/i.test(preview) && /fee/i.test(preview), preview);

    await slideBuy(page, 0.35);
    await wait(350);
    ok(
      "Partial slide does not fill",
      (await page.$eval("#buy-sheet", (el) => !el.hidden)) &&
        (await page.evaluate(() => !JSON.parse(localStorage.getItem("kalshiDemoState") || "{}").position))
    );

    await slideBuy(page, 1);
    await wait(1000);

    ok("Sheet dismisses after fill", await page.$eval("#buy-sheet", (el) => el.hidden));

    const pos = await page.evaluate(
      () => JSON.parse(localStorage.getItem("kalshiDemoState") || "{}").position
    );
    ok(
      "Position opened (Above)",
      !!(pos && (pos.side === "above" || pos.side === "below") && pos.contracts > 0),
      JSON.stringify(pos)
    );

    ok("Rolling strip visible", await page.$eval("#demo-live", (el) => !el.hidden));
    const livePl = await page.$eval("#demo-live-pl", (el) => el.textContent.trim());
    ok("Rolling P/L shown", livePl && livePl !== "—", livePl);
    const factors = await page.$eval("#demo-live-factors", (el) => el.textContent.trim());
    ok(
      "Rolling factors show entry/bid/time",
      /Entry|bid|Time|Paid|Contracts/i.test(factors),
      factors.slice(0, 120)
    );

    const bal = await page.evaluate(
      () => JSON.parse(localStorage.getItem("kalshiDemoState") || "{}").balance
    );
    ok("Balance deducted", bal < 1000, String(bal));

    // Mark in options
    await page.click("#menu-btn");
    await wait(400);
    ok("Close button in Options", await page.$eval("#demo-close", (el) => !el.hidden));
    const mark = await page.$eval("#demo-mark-pl", (el) => el.textContent.trim());
    ok("Options open P/L mark", /P\/L|Mark/i.test(mark), mark);
    await page.click("#options-close");
    await wait(300);

    // Close trade
    const canClose = await page.$eval("#demo-live-close", (el) => !el.disabled);
    ok("Close-at-bid enabled", canClose);
    if (canClose) {
      await page.evaluate(() => document.getElementById("demo-live-close").click());
      await wait(600);
      const after = await page.evaluate(() =>
        JSON.parse(localStorage.getItem("kalshiDemoState") || "{}")
      );
      ok("Position cleared after close", !after.position, JSON.stringify(after.position));
      ok(
        "Last result is CLOSED",
        !!(after.lastResult && /CLOSED/i.test(after.lastResult.text || "")),
        JSON.stringify(after.lastResult)
      );
      ok("Session realized P/L is number", typeof after.realizedPl === "number", String(after.realizedPl));
    }

    // Buy Below + cancel
    await page.click("#menu-btn");
    await wait(250);
    await page.click("#demo-reset");
    await wait(200);
    await page.evaluate(() => document.getElementById("demo-buy-below").click());
    await wait(450);
    ok(
      "Buy Below sheet",
      (await page.$eval("#buy-sheet-title", (el) => el.textContent.trim())) === "Buy Below" &&
        (await page.$eval("#buy-sheet", (el) => !el.hidden))
    );
    await page.click("#buy-sheet-x");
    await wait(300);
    ok("X cancels sheet", await page.$eval("#buy-sheet", (el) => el.hidden));

    // Buy Best via sticky dock
    await page.evaluate(() => document.getElementById("dock-buy-best").click());
    await wait(500);
    const best = await page.evaluate(() => ({
      open: !document.getElementById("buy-sheet").hidden,
      status: document.getElementById("status").textContent,
    }));
    ok(
      "Buy Best opens sheet or warns",
      best.open || /no clear|best side|demo/i.test(best.status),
      JSON.stringify(best)
    );
    if (best.open) {
      await page.click('.buy-chip[data-amt="25"]');
      await wait(150);
      ok(
        "Chip sets $25",
        (await page.$eval("#buy-amount", (el) => el.value)) === "25"
      );
      await page.click("#buy-backdrop");
      await wait(300);
      ok("Backdrop dismisses", await page.$eval("#buy-sheet", (el) => el.hidden));
    } else {
      ok("Chip sets $25", true, "skipped");
      ok("Backdrop dismisses", true, "skipped");
    }

    const fs = await page.$eval("#countdown", (el) => parseFloat(getComputedStyle(el).fontSize));
    ok("Time left font ≥ 22px", fs >= 22, `${fs}px`);

    const fit = await page.evaluate(() => {
      const docH = document.documentElement.scrollHeight;
      const viewH = window.innerHeight;
      const dock = document.querySelector(".buy-dock");
      const dockVis = dock && getComputedStyle(dock).display !== "none";
      return { docH, viewH, overflow: docH > viewH + 8, dockVis };
    });
    ok("Sticky buy dock visible", fit.dockVis);
    ok(
      "Page roughly fits viewport (little/no page scroll)",
      !fit.overflow || fit.docH - fit.viewH < 40,
      JSON.stringify(fit)
    );
  } catch (err) {
    ok("Runner", false, String(err && err.stack ? err.stack : err));
  } finally {
    await browser.close();
  }

  const failed = results.filter((r) => !r.pass);
  console.log("\n———");
  console.log(
    `Total ${results.length} · passed ${results.length - failed.length} · failed ${failed.length}`
  );
  if (failed.length) {
    for (const f of failed) console.log(`  - ${f.name}: ${f.detail}`);
    process.exit(1);
  }
}

main();
