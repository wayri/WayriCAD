const fs = require('fs');
const path = require('path');
const {pathToFileURL} = require('url');
const {chromium} = require(require.resolve('playwright', {paths: [process.argv[2] || process.cwd()]}));

(async () => {
  const root = path.resolve(__dirname, '..');
  const output = path.join(root, '.validation', 'gallery-browser');
  fs.mkdirSync(output, {recursive: true});
  const browser = await chromium.launch({headless: true, channel: process.env.GALLERY_BROWSER_CHANNEL || 'msedge',
    args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    const remote = [];
    page.on('pageerror', error => errors.push(String(error)));
    page.on('request', request => {if (/^https?:/.test(request.url())) remote.push(request.url());});
    await page.goto(pathToFileURL(process.argv[3] ? path.resolve(process.argv[3]) : path.join(root,
      'examples/quick_emerge/research_antennas/images/dense/interactive-results.html')).href);
    await page.waitForFunction(() => document.querySelector('#plot-radiation3d')._fullLayout);
    async function hover(id, x, y) {
      await page.locator('nav a[href="#'+id+'"]').click();
      const plot = page.locator('#plot-' + id);
      await plot.scrollIntoViewIfNeeded();
      const point = await plot.evaluate((node, values) => {
        const box = node.getBoundingClientRect();
        const layout = node._fullLayout;
        return {x: box.left + layout.xaxis._offset + layout.xaxis.l2p(values[0]),
          y: box.top + layout.yaxis._offset + layout.yaxis.l2p(values[1])};
      }, [x, y]);
      await page.mouse.move(point.x, point.y);
      await page.waitForTimeout(500);
      const text = await plot.locator('.hoverlayer').textContent();
      if (!text.trim()) throw new Error('Hover failed: ' + id);
      return text;
    }
    await page.locator('nav a[href="#s11"]').click();
    const mid = await page.locator('#plot-s11').evaluate(node => {
      const i=Math.floor(node.data[0].x.length/2);return {x:node.data[0].x[i],y:node.data[0].y[i]};
    });
    const networkHover = await hover('s11', mid.x, mid.y);
    const fieldHover = await hover('field', 0, 0);
    if (!networkHover.includes(String(mid.x)) || !fieldHover.includes('V/m')) throw new Error('Wrong probe units/data');
    await page.locator('nav a[href="#radiation3d"]').click();
    await page.locator('#radiation3d').scrollIntoViewIfNeeded();
    await page.locator('#plot-radiation3d').evaluate(node => Plotly.Plots.resize(node));
    await page.waitForTimeout(1200);
    const bounds = await page.locator('#plot-radiation3d').boundingBox();
    await page.locator('#plot-radiation3d').evaluate(node => node.on('plotly_hover', event => {
      window.radiationProbe = event.points.map(point => point.text || JSON.stringify({pointNumber:point.pointNumber, customdata:point.customdata})).join(' ');
    }));
    let radiationHover = '';
    for (const dx of [.5, .4, .6, .3, .7]) {
      for (const dy of [.5, .4, .6]) {
        await page.mouse.move(bounds.x + bounds.width * dx, bounds.y + bounds.height * dy);
        await page.waitForTimeout(800);
        radiationHover = await page.evaluate(() => window.radiationProbe || '');
        if (radiationHover.includes('theta=') && radiationHover.includes('relative')) break;
      }
      if (radiationHover.includes('theta=')) break;
    }
    if (!radiationHover.includes('theta=')) {
      await page.screenshot({path: path.join(output, 'hover-diagnostic.png')});
      console.log(await page.evaluate(() => ({probe:window.radiationProbe, target:document.elementFromPoint(innerWidth/2,innerHeight/2)?.outerHTML.slice(0,700)})));
      throw new Error('3D radiation surface hover failed: '+radiationHover.slice(-500));
    }
    await page.locator('#radiation3d').screenshot({path: path.join(output, 'radiation3d-desktop.png')});
    const scenes = await page.locator('#plot-radiation3d').evaluate(node => ({
      count: (node.data[0].customdata || node.data[0].x).length, axes: node._fullLayout.scene.xaxis.title.text,
      canvas: node.querySelectorAll('canvas').length}));
    if (scenes.count !== 91 || !scenes.canvas || !scenes.axes.includes('relative')) throw new Error('Missing 3D scene/scales');
    await page.setViewportSize({width: 390, height: 844});
    await page.waitForTimeout(700);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 2);
    if (overflow) throw new Error('Mobile horizontal overflow');
    await page.locator('nav a[href="#field"]').click();
    await page.locator('#field').scrollIntoViewIfNeeded();
    await page.locator('#field').screenshot({path: path.join(output, 'field-mobile.png')});
    if (errors.length || remote.length) throw new Error(JSON.stringify({errors, remote}));
    console.log(JSON.stringify({networkHover, fieldHover, radiationHover, scenes, mobileOverflow: overflow, remoteRequests: remote.length}));
    fs.writeFileSync(path.join(output, 'verification.json'), JSON.stringify({networkHover, fieldHover, radiationHover, scenes, errors, remote}, null, 2));
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
