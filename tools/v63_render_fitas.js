// Renderiza o vídeo de fundo da v63 a partir de `static/js/src/v63/fitas.js` (a MESMA função do fallback ao vivo).
// uso: node v63_render_fitas.js <saida_dir> <largura> <altura> <fps> [preview]
const fs = require('fs'), path = require('path'), puppeteer = require('puppeteer');
const [,, out, W, H, FPS, prev, DESDE] = process.argv;
const src = fs.readFileSync(path.join(__dirname, '../static/js/src/v63/fitas.js'), 'utf8').replace(/^export /gm, '');
(async () => {
  fs.mkdirSync(out, {recursive: true});
  const b = await puppeteer.launch({headless: 'new', executablePath: '/home/ubuntu/.cache/ms-playwright/chromium-1228/chrome-linux/chrome', args: ['--no-sandbox']});
  const p = await b.newPage();
  await p.setContent(`<canvas id=c width=${W} height=${H}></canvas><script>${src}
    const cv=document.getElementById('c'),ctx=cv.getContext('2d');
    window.quadro=(t)=>{ctx.globalCompositeOperation='source-over';desenharFitas(ctx,${W},${H},t);
      ctx.globalCompositeOperation='destination-over';ctx.fillStyle='#F7FAFF';ctx.fillRect(0,0,${W},${H});
      return cv.toDataURL('image/png');};
    window.bench=()=>{const t0=performance.now();for(let i=0;i<60;i++)desenharFitas(ctx,${W},${H},i/30);return (performance.now()-t0)/60;};
  </script>`);
  console.log('ms/quadro', (await p.evaluate(() => bench())).toFixed(2));
  const total = prev ? 4 : Math.round(PERIODO_S() * FPS);
  function PERIODO_S() { return 12; }
  for (let i = +(DESDE || 0); i < total; i++) {
    const t = prev ? i * 3 : i / FPS;
    const url = await p.evaluate(t => quadro(t), t);
    fs.writeFileSync(path.join(out, `f${String(i).padStart(4, '0')}.png`), Buffer.from(url.split(',')[1], 'base64'));
  }
  await b.close();
  console.log('quadros', total);
})();
