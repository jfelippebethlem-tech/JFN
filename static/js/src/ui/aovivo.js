/* AO VIVO — a interface dos motores (v61). O estado mora em `aovivo/estado.js`; aqui é só tela. */
import {$, esc} from '../nucleo/dom.js';
import {aoVivo} from '../aovivo/estado.js';
import {rotuloEstado, quando, haQuanto} from '../aovivo/formato.js';

/** Cartão de UM motor na folha (toque no nó em órbita, no cartão da grade ou no ticker). */
export function abrirMotor(id) {
  const m = aoVivo.motores.find(x => x.id === id), ov = $('ov'), sh = $('sheet');
  if (!m || !ov || !sh) return;
  const evs = aoVivo.eventos.filter(e => e.motor === id).slice(-8).reverse();
  const linha = (r, v) => v ? `<div class="mt-l"><span>${r}</span><b>${esc(v)}</b></div>` : '';
  sh.innerHTML = `<span class="x" onclick="fecharDossie()">✕ fechar</span><div class="grab"></div>
    <div class="mt-ficha e-${esc(m.estado)}">
      <h3 class="v61-disp"><i class="mt-pt" aria-hidden="true"></i>${esc(m.nome)}</h3>
      <div class="mt-estado">${esc(rotuloEstado(m))}</div>
      ${typeof m.progresso === 'number' ? `<div class="mt-barra" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(m.progresso * 100)}"><i style="width:${Math.round(m.progresso * 100)}%"></i></div>` : ''}
      ${linha('O que faz', m.descricao)}
      ${linha('Desde', m.desde ? `${quando(m.desde)} (${haQuanto(m.desde)})` : '')}
      ${linha('Próxima execução', quando(m.proxima))}
      ${linha('Unidade', m.unidade)}
      ${linha('Último código de saída', m.saida == null ? '' : String(m.saida))}
      <h4>Últimos eventos</h4>
      ${evs.length ? `<ul class="mt-evs">${evs.map(e => `<li><span class="num">${esc(quando(e.t))}</span>${esc(e.texto)}</li>`).join('')}</ul>`
                   : '<div class="dim">Sem evento registrado nesta janela.</div>'}
    </div>`;
  ov.classList.add('on');
}
