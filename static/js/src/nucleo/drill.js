/* DRILL — o caminho da métrica até as linhas que a produziram.
 *
 * O PROBLEMA MEDIDO em 2026-08-06: o painel tem 198 chamadas de `kpi()` e NENHUMA levava a lugar
 * nenhum. Quem lia "Risco ALTO: 12" não tinha como ver os 12. O dono descreveu como "tudo sambando,
 * solto quando puxa".
 *
 * POR QUE UM REGISTRO, e não um `onclick` por KPI: converter 193 métricas reescrevendo cada render
 * seria caro e frágil. Aqui cada render, ao montar a página, REGISTRA o conjunto que cada número
 * representa — `registrarDrill('riscoAlto', {titulo, itens, render})` — e o KPI só cita o nome. Uma
 * linha por métrica.
 *
 * A REGRA QUE NÃO PODE CAIR, e ela já foi violada uma vez: **o conjunto registrado tem de ser o
 * MESMO universo que o número conta.** Na primeira versão da fila de agente público o KPI dizia 68
 * e o clique mostrava 55, porque o número vinha da fila inteira e o filtro caía sobre a página
 * carregada. Se o número conta o universo e a lista é uma página, o drill MENTE — e métrica que não
 * bate com o que o clique mostra é pior do que métrica sem clique. Por isso `registrarDrill` exige
 * `itens` já filtrado pelo mesmo critério do número, e o rodapé imprime a contagem para o leitor
 * conferir contra o KPI com os próprios olhos.
 */
import { $, card, esc, sec } from './dom.js';
import { fmtN } from './formato.js';

const _REG = new Map();

/* RENDERIZADOR PADRÃO — `JSON.stringify` cortado em 300 caracteres era ilegível e fazia a gaveta
   parecer defeito. A maioria das métricas do painel conta objetos com o mesmo desenho: um nome, um
   documento e dois ou três números. Isto os mostra sem que cada conversão precise escrever HTML —
   e quem quiser um cartão melhor passa `render`. */
const _NOMES = ['razao_social', 'nome', 'nome_socio', 'orgao_nome', 'entidade', 'ancora',
                'descricao', 'objeto', 'chave', 'sobrenome', 'item'];
const _DOCS = ['cnpj', 'cnpj_fmt', 'cnpj_basico', 'documento', 'cpf', 'processo', 'numero'];

export function linhaGenerica(x) {
  if (x == null || typeof x !== 'object') return card(esc(String(x)));
  const tit = _NOMES.map(k => x[k]).find(v => v != null && v !== '') ?? '—';
  const doc = _DOCS.map(k => x[k]).find(v => v != null && v !== '');
  const nums = Object.entries(x)
    .filter(([k, v]) => typeof v === 'number' && !_DOCS.includes(k))
    .slice(0, 3)
    .map(([k, v]) => `${esc(k)} <b>${fmtN(v)}</b>`)
    .join(' · ');
  return card(`<div style="display:flex;justify-content:space-between;gap:10px">
      <div style="min-width:0"><div style="font-weight:700">${esc(String(tit))}</div>
      ${doc ? `<div class="dim">${esc(String(doc))}</div>` : ''}</div>
      ${nums ? `<div class="right dim" style="font-size:12.5px">${nums}</div>` : ''}</div>`);
}


/** Registra o conjunto por trás de uma métrica. `render(item)` devolve o HTML de UMA linha. */
export function registrarDrill(nome, { titulo, itens, render, nota }) {
  if (!nome) return;
  _REG.set(nome, { titulo: titulo || nome, itens: itens || [], render, nota: nota || '' });
}


/** Registra o drill SÓ SE a lista em mão for o universo inteiro; senão devolve `null`.
 *
 * O caso mais comum do painel: o KPI mostra um total do SERVIDOR (`d.n`) e a tela tem uma PÁGINA
 * (`?limite=80`). Ligar a gaveta ali produz a mentira que esta casa já cometeu três vezes — 68
 * virando 55, 201 virando 22, 647 virando 0. Mas quando o `limite` não corta nada, a lista É o
 * universo e a gaveta é honesta.
 *
 * Em vez de decidir isso na escrita — quando não se sabe quantos virão —, decide-se em tempo de
 * execução, a cada carga: `total === itens.length` liga; diferente, o KPI fica mudo e o número
 * continua verdadeiro. Nenhuma métrica precisa escolher entre mentir e não ter caminho.
 */
export function drillSeCompleto(nome, total, itens, cfg) {
  const lista = itens || [];
  if (total == null || Number(total) !== lista.length) return null;
  /* TETO DE RENDERIZAÇÃO, medido em campo (2026-08-08): o KPI de 12.640 pessoas registrava a
     gaveta completa — honesta no número — e o clique NÃO ABRIA: montar 12,6 mil cards num
     innerHTML só trava a página, e a sondagem via "gaveta mostra None". Gaveta é instrumento de
     CONFERÊNCIA, não de exportação: acima do teto o KPI cai para a procedência (`sobre`), que
     explica o universo — e quem precisa da lista inteira usa a rota/planilha. O número continua
     verdadeiro; o que muda é o veículo. */
  if (lista.length > TETO_LINHAS_GAVETA) return null;
  registrarDrill(nome, { ...(cfg || {}), itens: lista });
  return { drill: nome };
}

/* 800 cards renderizam em ~1-2 s na VM e num notebook comum; 12.640 travam. O valor é exportado
   para o teste de contrato poder citá-lo. */
export const TETO_LINHAS_GAVETA = 800;

/** Limpa o registro da aba anterior — conjunto velho reaparecendo em tela nova é pior que nenhum. */
export function limparDrill() { _REG.clear(); }

export function temDrill(nome) { return _REG.has(nome); }

/** Abre a gaveta com as linhas da métrica. Sem alvo registrado, não faz nada e não lança. */
export function abrirDrill(nome) {
  const d = _REG.get(nome);
  const alvo = $('drill-out') || $('view');
  if (!d || !alvo) return;
  const linhas = d.itens || [];
  let h = `<div id="drill-box" class="drill-box">`;
  h += `<button type="button" class="btn ghost" data-drill-fechar="1" style="float:right">Fechar</button>`;
  h += sec(d.titulo, linhas.length);
  h += linhas.length
    ? `<div class="grid">${linhas.map(x => {
        try { return d.render ? d.render(x) : linhaGenerica(x); }
        catch (e) { return card(`<div class="warn">linha ilegível: ${esc(String(e))}</div>`); }
      }).join('')}</div>`
    : card('<div class="dim">Nenhuma linha nesta métrica.</div>');
  /* O rodapé existe para o leitor CONFERIR contra o KPI sem confiar em mim. */
  h += `<div class="note">${fmtN(linhas.length)} linha(s) — este número tem de bater com a métrica
        que você clicou. ${esc(d.nota || '')}</div></div>`;
  const box = $('drill-box');
  if (box) box.remove();
  alvo.insertAdjacentHTML('afterbegin', h);
  const novo = $('drill-box');
  if (novo && novo.scrollIntoView) novo.scrollIntoView({ block: 'start' });
}


/** Abre a PROCEDÊNCIA de uma métrica que não tem linhas: o que mede, de onde vem, como se refaz. */
export function abrirSobre(titulo, texto) {
  const alvo = $('drill-out') || $('view');
  if (!alvo) return;
  const box = $('drill-box');
  if (box) box.remove();
  alvo.insertAdjacentHTML('afterbegin',
    `<div id="drill-box" class="drill-box">
       <button type="button" class="btn ghost" data-drill-fechar="1" style="float:right">Fechar</button>
       ${sec(titulo)}${card(`<div style="line-height:1.55">${texto}</div>`)}
       <div class="note">Esta métrica não tem lista por trás — ela mede uma relação, não um conjunto
       de itens. O que se pode conferir é a procedência acima.</div></div>`);
  const novo = $('drill-box');
  if (novo && novo.scrollIntoView) novo.scrollIntoView({ block: 'start' });
}

/** Delegação única, no `document`: sobrevive à troca de `innerHTML` do `#view`. */
export function ligarDrill() {
  document.addEventListener('click', ev => {
    if (!ev.target.closest) return;
    if (ev.target.closest('[data-drill-fechar]')) {
      const b = $('drill-box'); if (b) { ev.preventDefault(); b.remove(); }
      return;
    }
    const s = ev.target.closest('[data-sobre]');
    if (s) { ev.preventDefault(); abrirSobre(s.dataset.sobreTit || 'A métrica', s.dataset.sobre); return; }
    const k = ev.target.closest('[data-drill]');
    if (k && _REG.has(k.dataset.drill)) { ev.preventDefault(); abrirDrill(k.dataset.drill); }
  });
}
