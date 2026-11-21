// End-to-end UI screenshots of every screen and state.
// Usage: node e2e/screenshots.js <baseUrl> <outDir> [outageUrl]
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const [base, outDir, outageBase] = process.argv.slice(2);
const evidence = path.resolve(__dirname, "../../eval/data/dev/evidence");
fs.mkdirSync(outDir, { recursive: true });
const shots = [];

async function open(page, url = base) {
  await page.goto(url);
  await page.waitForSelector(".sample");
  await page.evaluate(() => document.fonts.ready);
  // Element captures scroll the page; un-stick the header (via CSSOM, which the app's CSP allows) so it never overlaps.
  await page.evaluate(() => { document.querySelector(".top").style.position = "static"; });
}

async function shot(page, name, title, opts = {}) {
  const file = `${name}.png`;
  if (opts.locator) await page.locator(opts.locator).screenshot({ path: path.join(outDir, file) });
  else await page.screenshot({ path: path.join(outDir, file), fullPage: Boolean(opts.fullPage) });
  shots.push({ file, title });
}

async function runSample(page, title) {
  await page.getByText(title, { exact: false }).click();
  await page.waitForSelector("#result .verdict, #result .err", { timeout: 120000 });
}

async function fillUpload(page, files, fields) {
  await page.locator("#upload-panel summary").click();
  for (const [name, value] of Object.entries(fields)) await page.fill(`[name=${name}]`, value);
  await page.setInputFiles("#files", files);
}

const SAMPLES = [
  ["06-journey-a-valid-evidence", "Goods arrived 15 days after the invoice", "Journey A: valid evidence moves the deadline"],
  ["07-journey-b-written-objection", "Rejected on day 11", "Journey B: written objection moves acceptance"],
  ["08-journey-b2-oral-objection", "Complaint by phone", "Oral complaint: nothing moves, and why"],
  ["09-journey-c-contradiction", "Challan and email disagree", "Journey C: contradictory evidence routes to review"],
  ["10-journey-d-unreadable", "blurred receipt date", "Journey D: unreadable photo, no conclusion"],
  ["11-journey-f-prompt-injection", "Challan tells the AI", "Journey F: injected instruction ignored"],
];
const CONTRACT = [path.join(evidence, "INV-007/challan.png"), path.join(evidence, "INV-007/contract.pdf")];
const FIELDS = { invoice_no: "INV-007", invoice_date: "2026-03-10", amount: "118000.00", credit_days: "30", payment_date: "2026-04-08" };

(async () => {
  const browser = await chromium.launch();
  const errors = [];
  const desktop = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, colorScheme: "light", acceptDownloads: true });
  const page = await desktop.newPage();
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));

  // Landing
  await open(page);
  await shot(page, "01-home-above-the-fold", "Landing page, above the fold");
  await shot(page, "02-home-full-page", "Landing page, full length", { fullPage: true });
  await page.locator("#workspace").scrollIntoViewIfNeeded();
  await shot(page, "03-workspace-empty-state", "Review tool, empty state", { locator: "#workspace" });
  await shot(page, "04-who-does-what", "Who does what: Gemini, Tesseract, Python, accountant", { locator: ".how" });

  // Loading state: hold the response briefly so the in-progress UI is visible
  await page.route("**/api/samples/*/analyze", async (route) => { await new Promise((r) => setTimeout(r, 2500)); await route.continue(); });
  await page.getByText(SAMPLES[1][1]).click();
  await page.waitForSelector("#result .loading");
  await page.waitForTimeout(1200);
  await shot(page, "05-analyzing-in-progress", "Analysis in progress", { locator: "#workspace" });
  await page.waitForSelector("#result .verdict");
  await page.unroute("**/api/samples/*/analyze");

  // Every sample journey: full result panel plus the page around it
  for (const [name, title, label] of SAMPLES) {
    await open(page);
    await runSample(page, title);
    await shot(page, name, label, { locator: "#result" });
  }

  // Workpaper export: capture the downloaded Markdown and render it as a page
  const [download] = await Promise.all([page.waitForEvent("download"), page.click("#export-md")]);
  const mdPath = path.join(outDir, "workpaper-example.md");
  await download.saveAs(mdPath);
  const md = fs.readFileSync(mdPath, "utf8").replace(/&/g, "&amp;").replace(/</g, "&lt;");
  const viewer = await desktop.newPage();
  await viewer.setContent(`<pre style="font:15px/1.55 ui-monospace,Menlo,monospace;padding:32px 40px;margin:0;white-space:pre-wrap;background:#fffdf8;color:#1b1a17">${md}</pre>`);
  await shot(viewer, "12-workpaper-export", "Downloaded workpaper (.md) for the accountant", { fullPage: true });
  await viewer.close();
  await page.emulateMedia({ media: "print" });
  await shot(page, "13-print-view", "Print / save-as-PDF view", { fullPage: true });
  await page.emulateMedia({ media: "screen" });

  // Upload flow
  await open(page);
  await fillUpload(page, CONTRACT, FIELDS);
  await shot(page, "14-upload-form-filled", "Upload form with evidence files chosen", { locator: "#upload-panel" });
  await page.click("#upload-btn");
  await page.waitForSelector("#result .verdict", { timeout: 120000 });
  await shot(page, "15-upload-result", "Result for uploaded evidence", { locator: "#result" });

  // Rejected upload (wrong file type): a clear error, nothing computed
  await open(page);
  const bad = path.join(outDir, "not-evidence.exe");
  fs.writeFileSync(bad, "MZ");
  await fillUpload(page, [bad], FIELDS);
  await page.click("#upload-btn");
  await page.waitForSelector("#result .err");
  fs.unlinkSync(bad);
  await shot(page, "16-upload-rejected", "Upload validation error", { locator: "#workspace" });

  // Provider outage: a second server with an invalid Gemini key
  if (outageBase) {
    await open(page, outageBase);
    await fillUpload(page, CONTRACT.slice(0, 1), FIELDS);
    await page.click("#upload-btn");
    await page.waitForSelector("#result .verdict, #result .err", { timeout: 120000 });
    await shot(page, "17-journey-e-gemini-unavailable", "Journey E: Gemini unavailable, nothing guessed", { locator: "#result" });
  }

  // Mobile
  const mobileCtx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true });
  const mobile = await mobileCtx.newPage();
  await open(mobile);
  await shot(mobile, "18-mobile-home", "Mobile, landing");
  const overflow = await mobile.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  await runSample(mobile, SAMPLES[1][1]);
  await mobile.locator("#result").scrollIntoViewIfNeeded();
  await shot(mobile, "19-mobile-result", "Mobile, verdict and timeline", { locator: "#result" });

  // Dark mode
  const darkCtx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, colorScheme: "dark" });
  const dark = await darkCtx.newPage();
  await open(dark);
  await shot(dark, "20-dark-home", "Dark mode, landing");
  await runSample(dark, SAMPLES[3][1]);
  await shot(dark, "21-dark-result", "Dark mode, contradiction routed to review", { locator: "#result" });

  fs.writeFileSync(path.join(outDir, "index.json"), JSON.stringify({ shots, console_errors: errors, mobile_horizontal_overflow: overflow }, null, 2));
  console.log(JSON.stringify({ count: shots.length, console_errors: errors, mobile_horizontal_overflow: overflow }, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
