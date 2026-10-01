// Capture README screenshots from a running local instance with demo data.
// Prereqs: python scripts/seed_demo_results.py, then run app.py with
// ADMIN_PASSWORD=admin EXPERT_PASSWORD=expert FLASK_PORT=4170.
// Usage: node scripts/capture-screenshots.js [baseUrl]   (needs `playwright` resolvable)
const { chromium } = require('playwright');
const path = require('path');

const BASE = process.argv[2] || 'http://127.0.0.1:4170';
const OUT = process.env.OUT_DIR || path.join(__dirname, '..', 'docs', 'images');
const FILE = 'evaluation_demo.json';

async function session(browser, password, opts = {}) {
  const ctx = await browser.newContext({
    viewport: opts.viewport || { width: 1440, height: 900 },
    deviceScaleFactor: 2,
    colorScheme: opts.colorScheme || 'light',
    isMobile: !!opts.mobile,
    hasTouch: !!opts.mobile,
  });
  const page = await ctx.newPage();
  await page.goto(`${BASE}/login`);
  await page.fill('#password', password);
  await Promise.all([page.waitForNavigation(), page.click('button[type=submit]')]);
  return page;
}

async function shot(page, url, name, opts = {}) {
  await page.goto(BASE + url, { waitUntil: 'networkidle' });
  if (opts.before) await opts.before(page);
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(OUT, name), fullPage: !!opts.fullPage });
  console.log('saved', name);
}

(async () => {
  const browser = await chromium.launch();
  const admin = await session(browser, 'admin');
  await shot(admin, `/results/${FILE}`, 'results-dashboard.png');
  await shot(admin, `/results/${FILE}`, 'results-table.png', {
    before: async (p) => { await p.evaluate(() => document.querySelector('#filterCard').scrollIntoView()); },
  });

  const adminDark = await session(browser, 'admin', { colorScheme: 'dark' });
  await shot(adminDark, `/results/${FILE}`, 'results-dark.png');

  const expert = await session(browser, 'expert');
  // Keyboard shortcut "2" only selects a chip; nothing is saved without Enter/click.
  await shot(expert, `/results/${FILE}/detail/5`, 'expert-scoring.png', {
    before: async (p) => { await p.keyboard.press('2'); },
  });
  await shot(expert, `/results/${FILE}/detail/5`, 'judge-opinion.png', {
    before: async (p) => {
      await p.keyboard.press('2');
      await p.click('.ai-opinion__summary');
      await p.evaluate(() => document.querySelector('.score-panel').scrollIntoView());
    },
  });

  const mobile = await session(browser, 'expert', { viewport: { width: 390, height: 844 }, mobile: true });
  await shot(mobile, `/results/${FILE}/detail/1`, 'mobile-scoring.png');

  // Hero banner: static HTML that frames the real results-dashboard.png captured above.
  const heroCtx = await browser.newContext({ viewport: { width: 1600, height: 800 }, deviceScaleFactor: 2 });
  const hero = await heroCtx.newPage();
  const heroUrl = 'file:///' + path.join(__dirname, 'hero.html').replace(/\\/g, '/');
  await hero.goto(heroUrl);
  await hero.evaluate((src) => { document.querySelector('.shot img').src = src; },
    'file:///' + path.join(OUT, 'results-dashboard.png').replace(/\\/g, '/'));
  await hero.waitForFunction(() => document.querySelector('.shot img').complete);
  await hero.screenshot({ path: path.join(OUT, 'hero.png') });
  console.log('saved hero.png');

  await browser.close();
})();
