// E2E journeys against a running AcceptGuard. Usage: node journeys.js <baseUrl> <outDir> [outageUrl]
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const [base, outDir, outageBase] = process.argv.slice(2);
const evidence = path.resolve(__dirname, "../../eval/data/dev/evidence");
fs.mkdirSync(outDir, { recursive: true });

async function waitResult(page) {
  await page.waitForSelector("#result .verdict, #result .err", { timeout: 240000 });
}

async function summary(page) {
  return page.evaluate(() => ({
    stamp: document.querySelector(".stamp")?.innerText.replace(/\n/g, " ") ?? null,
    headline: document.querySelector(".verdict h3")?.innerText ?? document.querySelector(".err p")?.innerText ?? null,
    reasons: [...document.querySelectorAll(".why b")].map((b) => b.innerText),
    compare: document.querySelector(".compare")?.innerText ?? null,
  }));
}

async function unstick(page) {
  await page.evaluate(() => { document.querySelector(".top").style.position = "static"; }); // CSP-safe (CSSOM)
}

async function sample(page, title, file) {
  await page.goto(base);
  await unstick(page);
  await page.getByText(title, { exact: false }).click();
  await waitResult(page);
  await page.locator("#result").screenshot({ path: path.join(outDir, file) });
  return summary(page);
}

async function upload(page, url, files, fields, file) {
  await page.goto(url);
  await unstick(page);
  await page.locator("#upload-panel summary").click();
  for (const [name, value] of Object.entries(fields)) await page.fill(`[name=${name}]`, value);
  await page.setInputFiles("#files", files);
  await page.click("#upload-btn");
  await waitResult(page);
  await page.locator("#result").screenshot({ path: path.join(outDir, file) });
  return summary(page);
}

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 2, colorScheme: "light" });
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(String(e)));
  const results = {};
  await page.goto(base);
  await page.screenshot({ path: path.join(outDir, "home.png") });
  results.A_valid = await sample(page, "Goods arrived 15 days after the invoice", "journey-a-valid.png");
  results.B_objection = await sample(page, "Rejected on day 11", "journey-b-objection.png");
  results.B2_oral = await sample(page, "Complaint by phone", "journey-b2-oral.png");
  results.C_conflict = await sample(page, "Challan and email disagree", "journey-c-conflict.png");
  results.D_unreadable = await sample(page, "blurred receipt date", "journey-d-unreadable.png");
  results.F_injection = await sample(page, "Challan tells the AI", "journey-f-injection.png");
  const contract = [path.join(evidence, "INV-007/challan.png"), path.join(evidence, "INV-007/contract.pdf")];
  const fields = { invoice_no: "INV-007", invoice_date: "2026-03-10", amount: "118000.00", credit_days: "30", payment_date: "2026-04-08" };
  results.A2_upload = await upload(page, base, contract, fields, "journey-a2-upload.png");
  if (outageBase) results.E_outage = await upload(page, outageBase, contract.slice(0, 1), fields, "journey-e-outage.png");
  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true });
  await mobile.goto(base);
  await mobile.screenshot({ path: path.join(outDir, "mobile-home.png") });
  const overflow = await mobile.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  await mobile.getByText("Rejected on day 11").click();
  await waitResult(mobile);
  await mobile.screenshot({ path: path.join(outDir, "mobile-result.png"), fullPage: true });
  results.mobile_horizontal_overflow = overflow;
  results.console_errors = errors;
  fs.writeFileSync(path.join(outDir, "journeys.json"), JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results, null, 2));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
