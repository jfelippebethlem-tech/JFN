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
/* v60 (D11): cinco abas ainda caíam no emoji por não terem glifo no set. Em vez de desenhar ícone
   novo (regra do brief: ícone de UI = o SVG que já existe em `jfn-icones.js`), cada uma aponta
   para o glifo existente de sentido mais próximo. Só vale com `html.v60`. */
const _ICO_V60 = {'🔬': '🔍', '📁': '📑', '📝': '📜', '🗂️': '🧾', '📨': '📧'};
/* v61 — GLIFOS PRÓPRIOS (fecha a pendência nº 3 da v60: cinco abas e os botões do cabeçalho usavam
   ícone "emprestado" de sentido próximo). Desenhados à mão no mesmo traço do set da casa: caixa 24,
   só linha, cantos redondos, nenhum preenchimento — raster em ícone foi REPROVADO no v27.
   As chaves de aba são as mesmas do registro (o emoji é só a chave histórica, nunca é exibido). */
const _ICO_V61 = {
  '🔬': '<circle cx="9" cy="10" r="5.5"/><circle cx="15.5" cy="13.5" r="4"/><path d="M18.4 16.4 21 19"/>',                                   // Lentes
  '📁': '<path d="M3 7.5A1.5 1.5 0 0 1 4.5 6h4l2 2.5h9A1.5 1.5 0 0 1 21 10v7.5a1.5 1.5 0 0 1-1.5 1.5h-15A1.5 1.5 0 0 1 3 17.5z"/><path d="M8 13.5h8"/>',   // Casos
  '📝': '<path d="M12.5 3.5H7A1.5 1.5 0 0 0 5.5 5v14A1.5 1.5 0 0 0 7 20.5h4.5"/><path d="M12.5 3.5 17 8h-4.5z"/><path d="m14.5 20 .9-3.4 4.7-4.7a1.4 1.4 0 0 1 2 2l-4.7 4.7z"/><path d="M8.5 12h3.5M8.5 15.5h2"/>',   // Requerimentos
  '🗂️': '<rect x="3" y="4.5" width="18" height="4.5" rx="1"/><path d="M4.5 9v9A1.5 1.5 0 0 0 6 19.5h12a1.5 1.5 0 0 0 1.5-1.5V9"/><path d="M10 13h4"/>',     // Acervo
  '📨': '<rect x="3" y="6" width="18" height="12.5" rx="1.5"/><path d="m3.6 7.2 8.4 6.3 8.4-6.3"/><path d="M12 16.2v.01"/>',                    // LAI
  '§v61-termos': '<path d="M12 6.5c-1.8-1.3-4.3-2-7.5-2v13c3.2 0 5.7.7 7.5 2 1.8-1.3 4.3-2 7.5-2v-13c-3.2 0-5.7.7-7.5 2z"/><path d="M12 6.5v13"/>',
  '§v61-controle': '<path d="M5 6.5h8M17 6.5h2M5 12h2M11 12h8M5 17.5h9M18 17.5h1"/><circle cx="15" cy="6.5" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="16" cy="17.5" r="2"/>',
  '§v61-sair': '<path d="M10 4.5H6.5A1.5 1.5 0 0 0 5 6v12a1.5 1.5 0 0 0 1.5 1.5H10"/><path d="M14.5 8 19 12l-4.5 4"/><path d="M19 12H9.5"/>',
  '§v61-som': '<path d="M4 9.5v5h3.5l4.5 4v-13l-4.5 4z"/><path d="M15.5 9a4 4 0 0 1 0 6"/><path d="M18 6.5a7.5 7.5 0 0 1 0 11"/>',
  '§v61-mudo': '<path d="M4 9.5v5h3.5l4.5 4v-13l-4.5 4z"/><path d="m16 9.5 5 5M21 9.5l-5 5"/>',
  '§v61-atividade': '<path d="M3 12h4l2.5-6 4 12 2.5-6h5"/>',
};
export const svgIco = e => {
  const _h = document.documentElement.classList;
  if (_ICO_V61[e] && (_h.contains('v61') || e.startsWith('§v61-')))
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" class="jico" aria-hidden="true">${_ICO_V61[e]}</svg>`;
  if (_ICO_V60[e] && _h.contains('v60')) e = _ICO_V60[e];
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
/* KPI CLICÁVEL — `dest` existia na assinatura desde sempre e NENHUMA das 198 chamadas do painel o
   passava: 198 métricas, zero caminhos para o dado por trás delas. Quem via "68 comissionados" não
   tinha como chegar aos 68.

   Duas formas, e a segunda é a que faltava:
     · `dest` = id de aba  → navega (comportamento original, preservado);
     · `dest` = `{drill}`  → dispara a ação registrada em `DRILL_ACOES`, que renderiza as LINHAS
       que produziram o número, na mesma tela.
   A ação vai em `data-drill`, nunca em `onclick` com nome de função global — é a mesma delegação
   de `data-vinc`, um ouvinte no `document`, que sobrevive à troca de `innerHTML` do `#view`. */
export const kpi = (v, l, cor, gl, dest) => {
  const ik = _kpiIco(cor);
  const drill = dest && typeof dest === 'object' && dest.drill;
  /* TERCEIRA FORMA: `{sobre:'texto'}`. Nem toda métrica tem linhas — mediana, F1, percentual de
     concentração e "SIAFE ok/off" contam relação, não itens, e exigir gaveta seria pedir mentira.
     O que falta a essas não é a lista: é a PROCEDÊNCIA — o que o número mede, de que fonte sai e
     como se recalcula. Clicar abre isso na mesma gaveta. */
  const sobre = dest && typeof dest === 'object' && dest.sobre;
  const go = drill
    ? ` kpi-go" data-drill="${drill}" role="button" tabindex="0" title="Ver os dados: ${l}`
    : (sobre
      ? ` kpi-go" data-sobre="${esc(sobre)}" data-sobre-tit="${esc(l)}" role="button" tabindex="0" title="O que é: ${l}`
      : (dest ? ` kpi-go" onclick="ir('${dest}')" title="Abrir: ${l}` : ''));
  /* `--n` = caracteres VISÍVEIS do valor: o CSS (v59) só encolhe o corpo quando o valor exato não cabe na largura do
     cartão — "R$ 1.311.540.133,79" encolhe, "302" fica do tamanho de sempre. */
  const n = String(v ?? '').replace(/<[^>]*>/g, '').replace(/&[a-z#0-9]+;/gi, 'x').length || 1;
  return `<div class="card kpi${go}"><div class="l">${l}</div><div class="v" style="--n:${n}${cor ? `;color:${cor}` : ''}">${v}</div>${gl ? `<span class="gl">${gl}</span>` : ''}${ik ? `<span class="kpi-ico" style="color:${cor}" aria-hidden="true">${svgIco(ik)}</span>` : ''}</div>`;
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
