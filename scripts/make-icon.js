// Gera o ícone do PolitiMonitor (1024x1024 PNG) a partir de um SVG vetorial.
// Uso: node scripts/make-icon.js
const fs = require('fs')
const path = require('path')
const sharp = require('sharp')

const S = 1024

// Temas de cor. Cada tema define o gradiente do fundo, a cor de destaque
// (pulso + nó + ondas), o tom das barras e a sombra projetada.
const TEMAS = {
  // azul/índigo (padrão)
  azul: {
    bg: ['#3b82f6', '#4f46e5', '#1e1b4b'],
    destaque: '#fbbf24',
    barTopo: '#ffffff', barBase: '#c7d2fe',
    sombra: '#0b1026',
  },
  // verde e amarelo (Brasil)
  verde: {
    bg: ['#16a34a', '#15803d', '#064e3b'],
    destaque: '#ffdf00',
    barTopo: '#ffffff', barBase: '#bbf7d0',
    sombra: '#03251a',
  },
}

function gerarSvg(t) {
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="${S}" height="${S}" viewBox="0 0 ${S} ${S}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0"   stop-color="${t.bg[0]}"/>
      <stop offset="0.45" stop-color="${t.bg[1]}"/>
      <stop offset="1"   stop-color="${t.bg[2]}"/>
    </linearGradient>
    <radialGradient id="glow" cx="0.62" cy="0.3" r="0.5">
      <stop offset="0" stop-color="${t.destaque}" stop-opacity="0.45"/>
      <stop offset="1" stop-color="${t.destaque}" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="bar" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${t.barTopo}" stop-opacity="0.98"/>
      <stop offset="1" stop-color="${t.barBase}" stop-opacity="0.85"/>
    </linearGradient>
    <filter id="soft" x="-30%" y="-30%" width="160%" height="160%">
      <feDropShadow dx="0" dy="10" stdDeviation="14" flood-color="${t.sombra}" flood-opacity="0.35"/>
    </filter>
  </defs>

  <!-- fundo squircle -->
  <rect x="0" y="0" width="${S}" height="${S}" rx="224" ry="224" fill="url(#bg)"/>
  <!-- brilho atrás do nó -->
  <rect x="0" y="0" width="${S}" height="${S}" rx="224" ry="224" fill="url(#glow)"/>

  <!-- barras (métricas crescentes) -->
  <g filter="url(#soft)">
    <rect x="300" y="600" width="78" height="120" rx="26" fill="url(#bar)"/>
    <rect x="408" y="540" width="78" height="180" rx="26" fill="url(#bar)"/>
    <rect x="516" y="470" width="78" height="250" rx="26" fill="url(#bar)"/>
    <rect x="624" y="392" width="78" height="328" rx="26" fill="url(#bar)"/>
  </g>

  <!-- linha de pulso (batimento -> tendência de alta) -->
  <path d="M 196 580 L 312 580 L 348 452 L 388 672 L 426 548 L 498 524 L 588 432 L 668 312"
        fill="none" stroke="${t.destaque}" stroke-width="26"
        stroke-linecap="round" stroke-linejoin="round"/>

  <!-- ondas de sinal (monitoramento ao vivo) -->
  <g fill="none" stroke="${t.destaque}" stroke-width="16" stroke-linecap="round">
    <path d="M 712 268 A 64 64 0 0 1 712 356" opacity="0.85"/>
    <path d="M 756 232 A 112 112 0 0 1 756 392" opacity="0.5"/>
  </g>

  <!-- nó luminoso no topo -->
  <circle cx="668" cy="312" r="40" fill="${t.destaque}"/>
  <circle cx="668" cy="312" r="17" fill="#ffffff"/>
</svg>`
}

const outDir = path.join(__dirname, '..', 'public', 'brand')
fs.mkdirSync(outDir, { recursive: true })

async function build() {
  for (const [nome, tema] of Object.entries(TEMAS)) {
    const svg = gerarSvg(tema)
    // o tema "azul" mantém os nomes padrão (icon.svg / icon-1024 / icon-512);
    // os demais recebem sufixo (icon-verde-1024.png, etc.)
    const sufixo = nome === 'azul' ? '' : `-${nome}`
    fs.writeFileSync(path.join(outDir, `icon${sufixo}.svg`), svg)
    await sharp(Buffer.from(svg)).resize(1024, 1024).png().toFile(path.join(outDir, `icon${sufixo}-1024.png`))
    await sharp(Buffer.from(svg)).resize(512, 512).png().toFile(path.join(outDir, `icon${sufixo}-512.png`))
    console.log(`tema ${nome}: icon${sufixo}-1024.png + icon${sufixo}-512.png`)
  }
  console.log('Ícones gerados em public/brand/')
}

build().catch((e) => { console.error(e); process.exit(1) })
