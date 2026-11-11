/* Assemble existing results without inventing data or cropping plot scales. */
const fs = require('node:fs/promises');
const path = require('node:path');
const sharp = require('sharp');

const root = path.resolve(__dirname, '..');
const tiles = [
  ['quick_pi_plugin/help-native-viewport.png', 'POWER INTEGRITY', 'Real-board copper and voltage-drop inspection'],
  ['quick_therm_plugin/examples/quicktherm-3d-3.6.38.png', '3D THERMAL ANALYSIS', 'Assumed-load thermal demonstration'],
  ['examples/quick_emerge/research_antennas/images/aesa-vnext/30/3d-radiation.png', 'AESA BEAM STEERING', 'Ideal array factor | 30-degree steering'],
  ['examples/quick_emerge/research_antennas/images/dense/wlan-field-3d.png', 'ANTENNA FIELD VISUALIZATION', 'Saved solved WLAN electric-field samples'],
  ['planar_magnetics_plugin/help-coupled-field.png', 'COUPLED MAGNETIC FIELDS', 'Coaxial transformer model | inductance matrix'],
  ['signal_integrity_advisor_plugin/help-board-rlc-eye.png', 'SIGNAL INTEGRITY', 'Board-derived RLC | synthetic channel comparison'],
];
const escape = text => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;');

async function main() {
  const width = 2400, height = 1400;
  const overlays = [];
  let svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}">
    <rect width="2400" height="1400" fill="#edf3f5"/>
    <rect width="2400" height="184" fill="#ffffff"/>
    <rect width="2400" height="9" fill="#168b78"/>
    <g font-family="Segoe UI, Arial, sans-serif" letter-spacing="0">
    <text x="42" y="84" font-size="66" font-weight="700" fill="#16333c">WayriCAD</text>
    <text x="2358" y="73" text-anchor="end" font-size="28" fill="#168b78">27 INDEPENDENT KiCad TOOLS</text>
    <text x="44" y="143" font-size="35" fill="#435c65">Go beyond layout. See the engineering.</text>`;
  for (let i = 0; i < tiles.length; i++) {
    const [source, title, caption] = tiles[i];
    const x = 28 + (i % 3) * 790;
    const y = 204 + Math.floor(i / 3) * 558;
    const input = path.join(root, source);
    const image = await sharp(input).resize(766, 458, {
      fit: 'contain', background: '#ffffff', kernel: 'lanczos3',
    }).png().toBuffer();
    overlays.push({ input: image, left: x, top: y + 76 });
    svg += `<text x="${x + 8}" y="${y + 27}" font-size="27" font-weight="700" fill="#16333c">${escape(title)}</text>
      <text x="${x + 8}" y="${y + 57}" font-size="22" fill="#435c65">${escape(caption)}</text>`;
  }
  svg += `<text x="42" y="1369" font-size="23" fill="#435c65">Actual captures and computed examples. Model limits apply; these are not hardware measurements or compliance certification.</text></g></svg>`;
  // Background and captions are vector-rendered; source plots are only scaled.
  await sharp(Buffer.from(svg)).composite(overlays).png({ compressionLevel: 9 })
    .toFile(path.join(root, 'docs/images/wayricad-showcase.png'));
  const result = await fs.stat(path.join(root, 'docs/images/wayricad-showcase.png'));
  console.log(`Generated ${width}x${height} showcase: ${result.size} bytes`);
}

main().catch(error => { console.error(error); process.exitCode = 1; });
