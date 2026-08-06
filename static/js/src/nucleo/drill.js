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

/** Registra o conjunto por trás de uma métrica. `render(item)` devolve o HTML de UMA linha. */
export function registrarDrill(nome, { titulo, itens, render, nota }) {
  if (!nome) return;
  _REG.set(nome, { titulo: titulo || nome, itens: itens || [], render, nota: nota || '' });
}

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
        try { return d.render ? d.render(x) : card(esc(JSON.stringify(x)).slice(0, 300)); }
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

/** Delegação única, no `document`: sobrevive à troca de `innerHTML` do `#view`. */
export function ligarDrill() {
  document.addEventListener('click', ev => {
    if (!ev.target.closest) return;
    if (ev.target.closest('[data-drill-fechar]')) {
      const b = $('drill-box'); if (b) { ev.preventDefault(); b.remove(); }
      return;
    }
    const k = ev.target.closest('[data-drill]');
    if (k && _REG.has(k.dataset.drill)) { ev.preventDefault(); abrirDrill(k.dataset.drill); }
  });
}
