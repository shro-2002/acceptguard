// Record real AcceptGuard footage for the demo video. Usage: node record.js <baseUrl> <outDir>
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const [base, outDir] = process.argv.slice(2);
fs.mkdirSync(outDir, { recursive: true });
const VIEW = { width: 1536, height: 864 }; // recorded natively, upscaled 1.25x to 1080p when composing

// A visible cursor: Playwright videos do not draw the OS pointer.
const CURSOR = `
  window.addEventListener('DOMContentLoaded', () => {
    const c = document.createElement('div');
    c.style.cssText = 'position:fixed;z-index:99999;width:22px;height:22px;border-radius:50%;background:rgba(36,58,99,.35);border:2px solid #243a63;pointer-events:none;transform:translate(-50%,-50%);transition:width .12s,height .12s;left:-50px;top:-50px';
    document.body.appendChild(c);
    document.addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; });
    document.addEventListener('mousedown', () => { c.style.width = '14px'; c.style.height = '14px'; });
    document.addEventListener('mouseup', () => { c.style.width = '22px'; c.style.height = '22px'; });
    // The app's CSP blocks injected <style> tags; CSSOM property writes are allowed.
    const top = document.querySelector('.top'); if (top) top.style.position = 'static';
    document.documentElement.style.scrollBehavior = 'auto';
  });`;

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

async function smoothScroll(page, to, ms) {
  await page.evaluate(async ({ to, ms }) => {
    const from = window.scrollY, start = performance.now();
    await new Promise((done) => {
      const step = (t) => {
        const k = Math.min(1, (t - start) / ms), e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
        window.scrollTo(0, from + (to - from) * e);
        k < 1 ? requestAnimationFrame(step) : done();
      };
      requestAnimationFrame(step);
    });
  }, { to, ms });
}

async function moveTo(page, locator, ms = 700) {
  const box = await locator.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + Math.min(box.height / 2, 40), { steps: Math.round(ms / 16) });
}

async function clickSample(page, title) {
  const card = page.getByText(title, { exact: false });
  await card.scrollIntoViewIfNeeded();
  await moveTo(page, card);
  await wait(250);
  await card.click();
  await page.waitForSelector("#result .verdict, #result .err", { timeout: 120000 });
}

async function y(page, selector) {
  return page.evaluate((s) => document.querySelector(s).getBoundingClientRect().top + window.scrollY - 24, selector);
}

async function segment(browser, name, fn) {
  const context = await browser.newContext({ viewport: VIEW, colorScheme: "light", recordVideo: { dir: outDir, size: VIEW } });
  await context.addInitScript(CURSOR);
  const page = await context.newPage();
  await page.goto(base);
  await page.waitForSelector(".sample");
  await page.mouse.move(VIEW.width * 0.6, VIEW.height * 0.4);
  await fn(page);
  const video = page.video();
  await context.close();
  fs.renameSync(await video.path(), path.join(outDir, `${name}.webm`));
  console.log("recorded", name);
}

(async () => {
  const browser = await chromium.launch();
  // S1 problem (~14.3 s): hero headline, then the five-step flow.
  await segment(browser, "s1_hero", async (page) => {
    await wait(5500);
    await smoothScroll(page, 330, 3500);
    await wait(6000);
  });
  // S2 demo (~15 s): run the written-objection case, land on the verdict.
  await segment(browser, "s2_demo", async (page) => {
    await smoothScroll(page, await y(page, "#workspace"), 1500);
    await wait(1200);
    await clickSample(page, "Rejected on day 11");
    await wait(600);
    await moveTo(page, page.locator(".compare"), 900);
    await wait(10500);
  });
  // S3 technical (~15.7 s): verified timeline, calculation and source quotes.
  await segment(browser, "s3_tech", async (page) => {
    await smoothScroll(page, await y(page, "#workspace"), 10);
    await clickSample(page, "Rejected on day 11");
    await wait(400);
    await smoothScroll(page, await y(page, ".timeline"), 2200);
    await wait(4000);
    await smoothScroll(page, await y(page, ".doc"), 2800);
    await moveTo(page, page.locator(".doc .ok").first(), 800);
    await wait(5600);
  });
  // S4 safety (~14.5 s): blurred photo abstains with a reason; injection is ignored.
  await segment(browser, "s4_safety", async (page) => {
    await smoothScroll(page, await y(page, "#workspace"), 10);
    await clickSample(page, "blurred receipt date");
    await wait(300);
    await moveTo(page, page.locator(".why").first(), 800);
    await wait(5200);
    await smoothScroll(page, await y(page, "#workspace"), 600);
    await clickSample(page, "Challan tells the AI");
    await wait(300);
    await smoothScroll(page, await y(page, ".doc"), 1500);
    await wait(4500);
  });
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
