const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const { chromium } = require('playwright');

const [report, output] = process.argv.slice(2);
if (!report || !output) throw new Error('需要报告绝对路径和独立 QA 输出目录');

async function checkGallery(page, expected) {
  const images = page.locator('main [data-image]');
  assert.equal(await images.count(), expected.length);
  for (const image of await page.locator('main .evidence img').all()) await image.evaluate(element => element.decode());
  if (!expected.length) return;
  const trigger = images.first();
  await trigger.focus();
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('.lightbox.open').count(), 1);
  for (const source of expected) {
    assert.equal(await page.locator('#viewer-image').getAttribute('src'), source);
    await page.locator('#viewer-image').evaluate(element => element.decode());
    await page.keyboard.press('ArrowRight');
  }
  assert.equal(await page.locator('#viewer-image').getAttribute('src'), expected[0]);
  await page.keyboard.press('ArrowLeft');
  assert.equal(await page.locator('#viewer-image').getAttribute('src'), expected.at(-1));
  await page.locator('#viewer-zoom').focus();
  await page.keyboard.press('Shift+Tab');
  assert.equal(await page.locator('#viewer-next').evaluate(element => element === document.activeElement), true);
  await page.keyboard.press('Tab');
  assert.equal(await page.locator('#viewer-zoom').evaluate(element => element === document.activeElement), true);
  await page.locator('#viewer-zoom').click();
  assert.equal(await page.locator('#viewer-zoom').getAttribute('aria-pressed'), 'true');
  await page.locator('#viewer-zoom').click();
  assert.equal(await page.locator('#viewer-zoom').getAttribute('aria-pressed'), 'false');
  await page.keyboard.press('Escape');
  assert.equal(await trigger.evaluate(element => element === document.activeElement), true);
  assert.equal(await page.locator('main').evaluate(element => element.inert), false);
}

async function facts(page) {
  return page.evaluate(() => ({
    selected: document.querySelector('#report-round')?.value ?? null,
    title: document.querySelector('h1').textContent,
    overall: document.querySelector('.overall').getAttribute('aria-label'),
    cases: [...document.querySelectorAll('.case')].map(element => element.id),
    sources: [...document.querySelectorAll('main img')].map(element => element.getAttribute('src')),
    width: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
}

async function checkMedia(page) {
  const media = page.locator('main video, main audio');
  for (const item of await media.all()) {
    assert.equal(await item.evaluate(element => element.controls), true);
    await item.evaluate(async element => {
      element.muted = true;
      await element.play();
    });
    await page.waitForFunction(element => element.currentTime > 0, await item.elementHandle());
    await item.evaluate(element => element.pause());
  }
  return media.count();
}

(async () => {
  fs.mkdirSync(output, { recursive: true, mode: 0o700 });
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const results = [];
  try {
    for (const viewport of [{ width: 1440, height: 1000 }, { width: 768, height: 1000 }, { width: 390, height: 844 }]) {
      const page = await browser.newPage({ viewport, reducedMotion: 'reduce' });
      const errors = [];
      const external = [];
      page.on('pageerror', error => errors.push(error.message));
      page.on('request', request => { if (/^https?:/.test(request.url())) external.push(request.url()); });
      await page.goto(pathToFileURL(report).href);
      const prefix = String(viewport.width);
      const initial = await facts(page);
      assert.ok(initial.scrollWidth <= initial.width, '当前报告横向溢出');
      assert.equal(await page.locator('.notice[role="status"]').count(), 0);
      await checkGallery(page, initial.sources);
      const mediaCount = await checkMedia(page);
      const ratiosPreserved = await page.locator('main .evidence img').evaluateAll(images => images.every(image => {
        const box = image.getBoundingClientRect();
        return Math.abs((box.width - 2) / (box.height - 2) - image.naturalWidth / image.naturalHeight) < .02;
      }));
      assert.equal(ratiosPreserved, true, '图片比例被改变');
      await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
      await page.locator('h1').click();
      await page.screenshot({ path: path.join(output, `${prefix}-current.png`) });
      for (let index = 0; index < Math.min(2, initial.cases.length); index++) {
        await page.locator('.case-nav a').nth(index).click();
        const caseHeader = await page.locator('.case-heading').nth(index).boundingBox();
        const navigation = await page.locator('.case-nav').boundingBox();
        assert.ok(caseHeader.y >= navigation.y + navigation.height, '场景标题被固定导航遮挡');
        await page.screenshot({ path: path.join(output, `${prefix}-case-${index + 1}.png`) });
      }
      const options = await page.locator('#report-round option').evaluateAll(items => items.map(item => item.value));
      const history = [];
      for (const round of options.filter(value => value !== initial.selected)) {
        await page.evaluate(async () => {
          window.previousMedia = [...document.querySelectorAll('main video, main audio')];
          await Promise.all(window.previousMedia.map(media => { media.muted = true; return media.play(); }));
        });
        await page.selectOption('#report-round', round);
        assert.equal(await page.evaluate(() => window.previousMedia.every(media => media.paused)), true);
        assert.equal(await page.locator('#report-round').evaluate(element => element === document.activeElement), true);
        const previous = await facts(page);
        assert.ok(previous.scrollWidth <= previous.width, '历史报告横向溢出');
        assert.equal(await page.locator('.notice[role="status"]').count(), 1);
        await checkGallery(page, previous.sources);
        history.push(previous);
        await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
        await page.screenshot({ path: path.join(output, `${prefix}-history-${history.length}.png`) });
      }
      if (initial.selected !== null) await page.selectOption('#report-round', initial.selected);
      assert.deepEqual(await facts(page), initial, '返回当前轮次后内容发生变化');
      await checkGallery(page, initial.sources);
      if (initial.sources.length) {
        await page.locator('main [data-image]').first().click();
        await page.locator('#viewer-image').evaluate(element => element.decode());
        await page.screenshot({ path: path.join(output, `${prefix}-lightbox.png`) });
        await page.keyboard.press('Escape');
      }
      // 原生选择框也必须支持键盘切换，重新加载不持久化历史选择。
      if (options.length > 1) {
        await page.locator('#report-round').focus();
        await page.keyboard.press('ArrowDown');
        assert.notEqual((await facts(page)).selected, initial.selected);
        await page.keyboard.press('Home');
        assert.equal((await facts(page)).selected, initial.selected);
        await page.keyboard.press('End');
        assert.notEqual((await facts(page)).selected, initial.selected);
      }
      await page.reload();
      assert.equal((await facts(page)).selected, initial.selected);
      assert.deepEqual(errors, []);
      assert.deepEqual(external, []);
      results.push({ viewport, initial, history, mediaCount, errors, externalRequests: external.length });
      await page.close();
    }
    const result = { checked_at: new Date().toISOString(), report, results };
    fs.writeFileSync(path.join(output, 'report-qa.json'), JSON.stringify(result, null, 2) + '\n', { mode: 0o600 });
    console.log(JSON.stringify(result, null, 2));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
