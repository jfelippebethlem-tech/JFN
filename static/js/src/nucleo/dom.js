/* Primitivas de marcação — os tijolos que os 59 renders empilham.
 *
 * `card`, `kpi`, `sec` e `cover` já eram as únicas quatro primitivas de verdade do painel; o
 * resto de cada tela (`chip`, `tag`, `linha`) é escrito à mão dentro dos renders, com três
 * `linha` de assinaturas incompatíveis espalhadas pelo arquivo. Este módulo é onde essa dívida
 * começa a ser paga: forma canônica única, num lugar só.
 *
 * Não importa nada além de `formato.js` (folha). Não guarda estado. Recebe dado, devolve string.
 */
export const $ = id => document.getElementById(id);

export const esc = s => String(s == null ? '' : s)
  .replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));

// ícone da aba = glifo SVG sci-fi, tingido pela esfera. Fallback: o próprio emoji.
export const svgIco = e => {
  const g = window.JFN_ICO && window.JFN_ICO[e];
  return g ? `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" class="jico" aria-hidden="true">${g}</svg>` : e;
};

export const card = (h, cls) => `<div class="card ${cls || ''}">${h}</div>`;

// ícone semântico do KPI, deduzido da cor: crítico/dinheiro/ok/info
const _kpiIco = cor => {
  const c = String(cor || '');
  if (/rose/.test(c)) return '§alert'; if (/gold|amber/.test(c)) return '§money';
  if (/green/.test(c)) return '§ok'; if (/accent|teal|blue|violet|purple/.test(c)) return '§info';
  return '';
};

// dest (opcional) = id de aba: torna o KPI clicável e leva à aba (ir() troca de esfera sozinho;
// a11yfy() já torna qualquer [onclick] operável por teclado). Ex.: kpi(n,'Alertas ativos',cor,'🚨','e_alertas').
export const kpi = (v, l, cor, gl, dest) => {
  const ik = _kpiIco(cor);
  const go = dest ? ` kpi-go" onclick="ir('${dest}')" title="Abrir: ${l}` : '';
  return `<div class="card kpi${go}"><div class="l">${l}</div><div class="v" ${cor ? `style="color:${cor}"` : ''}>${v}</div>${gl ? `<span class="gl">${gl}</span>` : ''}${ik ? `<span class="kpi-ico" style="color:${cor}" aria-hidden="true">${svgIco(ik)}</span>` : ''}</div>`;
};

export const sec = (t, cnt) => `<h2 class="sec">${t}${cnt != null ? `<span class="cnt">${cnt}</span>` : ''}</h2>`;
export const spin = t => `<div class="skel"><span class="sp"></span>${t || 'Carregando…'}</div>`;
export const cover = (sph, t, s, ic) => `<div class="cover ${sph}"><div class="cover-row">${ic ? `<span class="cover-seal" aria-hidden="true">${svgIco(ic)}</span>` : ''}<div class="cover-tx"><h2 class="t">${t}</h2><div class="s">${s}</div></div></div></div>`;
export const leitura = t => `<div class="leitura">${t}</div>`;

// Rota sem número que DIZ por quê (estado='sem_medicao' + mensagem com o comando): renderizar
// KPI com "—" jogava fora a única informação que existe. Medido em campo (2026-07-31):
// /api/eval/hermeneutica devolve 200 com a mensagem inteira e a tela mostrava quatro traços mudos.
// Os crases da mensagem viram <code> — o comando é acionável, não decorativo.
export const semMedicao = (d, t) => card(`<div style="font-weight:700">${esc(t)}</div>
  <div class="dim" style="margin-top:6px">${esc((d && d.mensagem) || 'sem medição neste ambiente').replace(/`([^`]+)`/g, '<code>$1</code>')}</div>`);

// botão "Gerar PDF" (padrão Kroll) para qualquer aba de inteligência.
// O `onclick` cita `gerarPdfIntel` por NOME, resolvido no escopo global pela ponte — não é import:
// handler inline não enxerga escopo de módulo, e é justamente por isso que a ponte existe.
export const btnPdf = tipo => `<button class="btn ghost" style="flex:0 0 auto;min-width:120px" onclick="gerarPdfIntel('${tipo}',this)">Gerar PDF</button>`;

// barra de ação da aba (PDF + eventuais extras), colocada logo após o cover
export const acoesAba = (tipo, extra) => `<div class="btns" style="margin:-4px 0 14px">${btnPdf(tipo)}${extra || ''}</div>`;

export function toggle(el) { el.classList.toggle('open'); }

/* Corta no ESPAÇO, não no caractere: cortar no meio da palavra ('MANUTENÇÃO PREVENT…') lê pior
   do que uma linha um pouco mais curta. Só recua até o espaço se ele estiver depois de 60% do
   limite — senão o corte comeria metade do texto útil. */
export const corta = (s, n) => { const t = String(s || ''); if (t.length <= n) return t;
  const c = t.slice(0, n), i = c.lastIndexOf(' ');
  return (i > n * 0.6 ? c.slice(0, i) : c).replace(/[\s,;:.·\-–—]+$/, '') + '…'; };

export const clk = (cnpj, txt) => {
  const d = String(cnpj || '').replace(/\D/g, '');
  return d.length === 14
    ? `<button type="button" class="clk" onclick="abrirDossie('${d}','${esc(String(txt)).replace(/'/g, '')}')">${esc(txt)}</button>`
    : `<b>${esc(txt)}</b>`;
};
