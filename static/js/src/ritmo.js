/* O RELÓGIO DO PAINEL — um só, e o BPM dele é telemetria, não decoração.
 *
 * POR QUE ISTO EXISTE. O painel tinha 54 animações infinitas, cada uma com a duração cravada no
 * CSS. Isso custa caro (foi o que derrubou a VM para 1-2 FPS e obrigou a inventar o modo sóbrio) e,
 * pior, não diz nada: a tela se mexia igual com a máquina parada ou no meio de um sweep de 40 mil
 * páginas. Aqui as duas coisas se resolvem juntas — UM relógio, `--bpm`, do qual toda a respiração
 * da cena deriva por `calc()`, e cujo valor vem do estado REAL do barramento.
 *
 * TRÊS MARCHAS, e a troca é para ser VISTA (decisão do dono: degraus nítidos, não rampa contínua):
 *
 *   vigília    sem sweep, carga baixa, menos de 1 evento/min   respiração lenta e ampla
 *   coleta     sweep vivo OU pelo menos 1 evento/min           o painel muda de marcha
 *   enxurrada  muitos eventos no minuto OU carga alta          tensão máxima
 *
 * DUAS TRAVAS, e sem elas isto vira um semáforo epiléptico:
 *
 *   HISTERESE — subir de marcha exige o sinal por 3 s; descer exige 15 s de silêncio. Um evento
 *   isolado não pode fazer o painel inteiro piscar entre marchas. É o defeito clássico de limiar
 *   sem amortecimento, e ele aparece exatamente quando o sistema está quase parado — o momento em
 *   que a tela mais precisa estar calma.
 *
 *   O REGIME É CONSTANTE, A PASSAGEM É QUE SE ANIMA — dentro de uma marcha o BPM não flutua com o
 *   ruído do minuto. O que se anima é a transição (1,2 s, no CSS, via `@property --bpm`). É o que
 *   faz parecer câmbio de máquina em vez de um número tremendo.
 *
 * REGRA DE HONESTIDADE, herdada do resto do painel: nada aqui acelera sozinho. Sem barramento, o
 * painel respira devagar — e isso também é informação. Nenhum `Math.random`, nenhum tráfego
 * simulado; a mesma regra que já vale para o arco do kyber (só carga medida) e para o `.khit`
 * (um pulso = um evento que existiu).
 */

const MARCHAS = ["vigilia", "coleta", "enxurrada"];
const SUBIR_MS = 3000;      // o sinal precisa persistir para a marcha subir
const DESCER_MS = 15000;    // e o silêncio precisa persistir para ela cair
const JANELA_MS = 60000;    // "eventos por minuto" é literalmente isto

let _marcha = "vigilia";
let _candidata = "vigilia";
let _desdeCandidata = 0;
let _eventos = [];          // timestamps dentro da janela
let _sweepVivo = false;
let _load1 = 0;
let _tique = 0;

/* Teto de carga: a VM tem 2 vCPU, então load 5 já é o teto crítico — o mesmo número que o arco do
   kyber usa (`_kyber`, `frac = load1/5`). Repetir a constante em dois lugares seria pedir para uma
   delas envelhecer sozinha; ela vive aqui e o kyber continua com a dele porque desenha outra
   coisa (carga instantânea, não regime). Se um dia divergirem, é este comentário que denuncia. */
const LOAD_ENXURRADA = 3.5;

function _agora() { return Date.now(); }

function _podar() {
  const corte = _agora() - JANELA_MS;
  while (_eventos.length && _eventos[0] < corte) _eventos.shift();
}

/** A marcha que o estado ATUAL pede, sem histerese — a histerese entra no `_avaliar`. */
function _pedida() {
  _podar();
  const porMinuto = _eventos.length;
  if (porMinuto >= 12 || _load1 >= LOAD_ENXURRADA) return "enxurrada";
  if (_sweepVivo || porMinuto >= 1) return "coleta";
  return "vigilia";
}

function _aplicar(nova) {
  if (nova === _marcha) return;
  const subiu = MARCHAS.indexOf(nova) > MARCHAS.indexOf(_marcha);
  _marcha = nova;
  const b = document.body;
  if (!b) return;
  b.dataset.ritmo = nova;
  /* A TROCA É UM ACONTECIMENTO, não só um número novo. A classe sai sozinha no fim da animação;
     se o navegador não disparar `animationend` (aba oculta, reduced-motion), o setTimeout tira —
     classe presa é a diferença entre "trocou de marcha" e "está travado em transição". */
  const marca = subiu ? "marcha-sobe" : "marcha-desce";
  b.classList.add(marca);
  const limpar = () => b.classList.remove(marca);
  b.addEventListener("animationend", limpar, {once: true});
  setTimeout(limpar, 1600);
}

function _avaliar() {
  const quer = _pedida();
  if (quer === _marcha) { _candidata = _marcha; return; }
  if (quer !== _candidata) { _candidata = quer; _desdeCandidata = _agora(); return; }
  const subindo = MARCHAS.indexOf(quer) > MARCHAS.indexOf(_marcha);
  const espera = subindo ? SUBIR_MS : DESCER_MS;
  if (_agora() - _desdeCandidata >= espera) _aplicar(quer);
}

function _ligarTique() {
  if (_tique) return;
  /* Um intervalo só, de 1 s, e ele existe porque a QUEDA de marcha não tem evento que a dispare:
     o silêncio não avisa. Ligado preguiçosamente no primeiro sinal — antes disso não há nada para
     avaliar e um timer parado é um timer que não gasta a VM. */
  _tique = setInterval(_avaliar, 1000);
}

/** Batimento do SSE: carga medida da VM e se há sweep em curso. */
export function ritmoTelemetria(load1, sweeps) {
  _load1 = Number(load1) || 0;
  _sweepVivo = !!(sweeps && (sweeps.sei || sweeps.siafe));
  _ligarTique();
  _avaliar();
}

/** Um evento REAL entrou no barramento. Uma sístole. */
export function ritmoEvento() {
  _eventos.push(_agora());
  _ligarTique();
  _avaliar();
}

/** Leitura para quem quiser mostrar o regime na tela (o deck da Consciência vai querer). */
export function ritmoEstado() {
  _podar();
  return {marcha: _marcha, eventosPorMinuto: _eventos.length, load1: _load1, sweep: _sweepVivo};
}
