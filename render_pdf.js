const puppeteer = require('puppeteer-core');
(async () => {
  const browser = await puppeteer.launch({
    executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    headless: 'new',
    args: ['--no-sandbox', '--disable-crashpad', '--disable-gpu'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1600, height: 1200 });
  await page.goto('file:///D:/DSH-Workspace/mm_page.html', { waitUntil: 'networkidle0', timeout: 60000 });
  await page.waitForFunction(() => window.mm && document.querySelectorAll('.markmap-node').length > 5, { timeout: 30000 });
  await new Promise(r => setTimeout(r, 1000));
  // Measure content size
  const size = await page.evaluate(() => {
    const svg = document.querySelector('#mindmap');
    const g = svg.querySelector('g.markmap');
    return { svg: { w: svg.clientWidth, h: svg.clientHeight } };
  });
  console.log('size', JSON.stringify(size));
  await page.pdf({ path: 'D:\\DSH-Workspace\\动植物体结构层次_思维导图.pdf', width: '1600px', height: '1200px', printBackground: true, margin: {top:0,bottom:0,left:0,right:0} });
  await browser.close();
  console.log('done');
})().catch(e => { console.error(e.message); process.exit(1); });
