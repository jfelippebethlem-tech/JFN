/* O BARRAMENTO — a única porta por onde o painel escuta o sistema em tempo real.
 *
 * Um `EventSource` em `/api/eventos/stream`, e duas classes de mensagem que NÃO se misturam:
 *
 *   pulse   batimento da máquina: carga medida, memória, quais sweeps estão vivos. Não entra no
 *           feed nem pulsa a lâmina — é sinal vital, não acontecimento.
 *   evento  algo entrou no banco: uma OB, um alerta, uma perícia. Vira uma linha no holofeed, um
 *           pulso no conduíte e um choque no anel do kyber.
 *
 * A DIVISÃO DE TRABALHO NO KYBER É HONESTA, e é a razão de este módulo existir separado: o ARCO
 * é só carga medida (`kyber()`, `load1`) e nada mais toca nele; o EVENTO real empurra um pulso de
 * choque no anel externo. Um pulso = um evento que existiu. Nenhum movimento aqui é inventado —
 * sem SSE, o anel fica parado, e isso também é a verdade.
 *
 * POR QUE `sabreStart` RECEBE GANCHOS EM VEZ DE IMPORTAR O QUE PRECISA. Ele precisa de duas
 * coisas que moram fora do barramento: pulsar a mesa de vigília (`nucleoPulse`) e saber se pode
 * animar (preferência de movimento + modo sóbrio). Importá-las daqui criaria um ciclo — o
 * entrypoint importa o barramento, o barramento importaria o entrypoint. Recebê-las como
 * parâmetro inverte a dependência e diz a verdade sobre o desenho: o barramento não conhece a
 * cena; ele avisa quem quiser ouvir.
 */
import {$, esc} from '../nucleo/dom.js';
import {fmtN, fmtD} from '../nucleo/formato.js';

const COR_ESTADO = {ok: 'var(--teal)', carga: 'var(--amber)', critico: 'var(--rose)'};

export const COR_EVENTO = {
  ob_siafe: 'var(--gold)', ob_tfe: 'var(--gold)', alerta: 'var(--rose)', radar: 'var(--rose)',
  clausula: 'var(--violet)', pericia: 'var(--green)', ata: 'var(--blue)', sei_doc: 'var(--teal)',
};

export function hfToggle() { $('holofeed').classList.toggle('open'); }

/** Uma linha no holofeed. Teto de 10: o feed é uma janela, não um histórico. */
function holofeedAdd(ev, crit) {
  const ul = $('hflist'); if (!ul) return;
  $('hfvazio').style.display = 'none';
  const li = document.createElement('li'); if (crit) li.className = 'crit';
  li.style.setProperty('--evc', COR_EVENTO[ev.tipo] || 'var(--saber)');
  li.innerHTML = `<span class="t">${esc(ev.t || '')}</span><span class="d">${ev.delta > 1 ? '×' + fmtN(ev.delta) : '◈'}</span><span>${esc(ev.rotulo || ev.tipo)}</span>`;
  ul.prepend(li);
  while (ul.children.length > 10) ul.lastChild.remove();
}

/** Um pulso atravessando o conduíte, com o rótulo do evento junto. */
function pulsoNoConduite(ev, crit, podeAnimar) {
  if (!podeAnimar()) return;
  const c = $('conduit'); if (!c) return;
  const p = document.createElement('span'); p.className = 'cpulse' + (crit ? ' crit' : '');
  p.addEventListener('animationend', () => p.remove()); c.appendChild(p);
  if (ev.rotulo) {
    const l = document.createElement('span'); l.className = 'clabel';
    l.textContent = (ev.delta > 1 ? ev.delta + '× ' : '') + ev.rotulo;
    l.addEventListener('animationend', () => l.remove()); c.appendChild(l);
  }
}

/** O arco do kyber. SÓ carga medida — nenhum evento chega aqui. */
function kyber(load1, sweeps, mem) {
  const arc = $('karc'); if (!arc) return;
  const frac = Math.min(1, (load1 || 0) / 5);      // 2 vCPU: load 5 = teto crítico do arco
  arc.style.strokeDashoffset = (72.3 * (1 - frac)).toFixed(1);
  $('kyber').classList.toggle('sweep', !!(sweeps && (sweeps.sei || sweeps.siafe)));
  $('hfload').textContent = 'load ' + (load1 == null ? '—' : fmtD(load1, 2))
                          + (mem != null ? ' · ram ' + mem + '%' : '');
}

/** O choque no anel externo. SÓ evento — nenhuma carga chega aqui. */
function kyberHit(tipo, crit, podeAnimar) {
  const k = $('kyber'); if (!k || !podeAnimar()) return;
  const o = document.createElement('span'); o.className = 'khit' + (crit ? ' crit' : '');
  o.style.setProperty('--kc', COR_EVENTO[tipo] || 'var(--saber)');
  o.addEventListener('animationend', () => o.remove()); k.appendChild(o);
}

/**
 * Liga o barramento.
 * @param {object} ganchos
 * @param {(ev:object)=>void}  ganchos.aoEvento     um evento REAL chegou (a mesa pulsa aqui)
 * @param {(t:object)=>void}   ganchos.aoBatimento  carga/sweeps novos (o relógio do ritmo lê aqui)
 * @param {()=>boolean}        ganchos.podeAnimar   respeita reduced-motion e o modo sóbrio
 */
export function sabreStart({aoEvento, aoBatimento, podeAnimar}) {
  if (!window.EventSource) return;                 // navegador antigo: segue o polling de sempre
  const es = new EventSource('/api/eventos/stream');
  es.onopen = () => { $('livetxt').textContent = 'ao vivo'; };
  es.onerror = () => { $('livetxt').textContent = 'reconectando…'; };
  es.onmessage = m => {
    let ev; try { ev = JSON.parse(m.data); } catch (_) { return; }
    if (ev.tipo === 'pulse') {
      document.documentElement.style.setProperty('--saber',
        COR_ESTADO[ev.estado] || COR_ESTADO.ok);
      kyber(ev.load1, ev.sweeps, ev.mem);
      aoBatimento(ev);
      return;                                      // batimento não polui o feed nem pulsa a lâmina
    }
    const crit = (ev.tipo === 'alerta' || ev.tipo === 'radar');
    pulsoNoConduite(ev, crit, podeAnimar);
    holofeedAdd(ev, crit);
    kyberHit(ev.tipo, crit, podeAnimar);
    aoEvento(ev);
  };
}
