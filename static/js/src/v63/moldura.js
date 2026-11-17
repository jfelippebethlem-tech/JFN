/* v63 · MOLDURA — topbar fina no estilo Relay: pílula de status ao vivo + CTA azul.
 *
 * A pílula não é enfeite: `● N motores rodando` vem de `/api/ao-vivo/estado` (a mesma regra do reator e da
 * aba Sistema › Motores: `rodando` e classe ≠ infra), relido a cada 30 s com a aba visível. Falhou a leitura → diz
 * "status indisponível" (INDISPONÍVEL ≠ 0: nunca "0 motores").
 * Ela mora DENTRO do `#livebadge` que já existe (o ponto "ao vivo" da v60, que abre a atividade):
 * reaproveita o lugar dele na grade do cabeçalho em vez de abrir uma coluna nova.
 */
import {J} from '../nucleo/http.js';
import {fmtN} from '../nucleo/formato.js';

let _timer = 0;
export function molduraMontar() {
  const lb = document.getElementById('livebadge');
  if (lb && !lb.querySelector('.v63-st')) {
    lb.classList.add('v63-status');
    const s = document.createElement('span');
    s.className = 'v63-st'; s.textContent = 'lendo motores…';
    lb.appendChild(s);
    lb.title = 'motores do JFN agora — clique para a atividade ao vivo';
  }
  const ac = document.querySelector('.htop .actions');
  if (ac && !ac.querySelector('.v63-cta')) {
    const a = document.createElement('a');
    a.className = 'v63-btn sol v63-cta'; a.setAttribute('role', 'button'); a.tabIndex = 0;
    a.dataset.v63Ir = 'g_buscar'; a.textContent = 'Buscar CNPJ';
    ac.insertBefore(a, ac.firstChild);
  }
  _ler();
  clearInterval(_timer);
  _timer = setInterval(() => { if (!document.hidden) _ler(); }, 30000);
}

async function _ler() {
  const lb = document.getElementById('livebadge'); if (!lb) return;
  const st = lb.querySelector('.v63-st');
  const d = await J('/api/ao-vivo/estado');
  if (!d || !Array.isArray(d.motores)) {
    lb.classList.add('indisp'); lb.classList.remove('parado');
    st.textContent = 'status indisponível'; return;
  }
  const n = d.motores.filter(m => m.estado === 'rodando' && m.classe !== 'infra').length;   // a regra do reator
  lb.classList.remove('indisp'); lb.classList.toggle('parado', n === 0);
  /* no celular o CSS esconde `.w`: sobra "2 rodando" / "em espera" */
  st.innerHTML = n ? `${fmtN(n)}<span class="w"> ${n === 1 ? 'motor' : 'motores'}</span> rodando` : '<span class="w">motores </span>em espera';
  lb.dataset.motores = String(n);
}

/** Título de capa de cada aba: a ÚLTIMA palavra ganha a serifa itálica azul. Só embrulha o texto
 *  que já está lá (o leitor de tela lê a mesma frase). Palavra curta demais (≤ 2 letras, "RJ") não. */
export function capaItalico(raiz) {
  raiz.querySelectorAll('.cover .t').forEach(t => {
    if (t.querySelector('.v63-it')) return;
    const nos = [...t.childNodes].filter(n => n.nodeType === 3 && n.textContent.trim());
    const no = nos[nos.length - 1]; if (!no) return;
    const m = no.textContent.match(/^(.*?)(\S{3,})(\s*)$/s); if (!m) return;
    const em = document.createElement('em'); em.className = 'v63-it'; em.textContent = m[2];
    no.textContent = m[1];
    no.after(em);
    if (m[3]) em.after(document.createTextNode(m[3]));
  });
}
