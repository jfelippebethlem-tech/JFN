/* Formatação — o jeito da casa de escrever número, dinheiro e rótulo.
 *
 * Módulo FOLHA: não importa nada, não toca no DOM, não depende de estado. É o primeiro a ser
 * extraído do monolito de propósito — se algo aqui quebrar, quebra tudo, e é melhor descobrir
 * enquanto ainda há pouco em jogo.
 *
 * As três regras que já custaram bug e por isso viraram função em vez de convenção:
 *   • decimal é VÍRGULA. `toFixed()` devolve ponto ('3.4') e a casa escreve '3,4'.
 *   • percentual assinado só ganha '+' quando é positivo — '+-8%' esteve na tela da e_adit.
 *   • id técnico (snake_case) NUNCA chega ao usuário: passa por `rot()`.
 */

export const fmtN = n => (n == null ? '—' : Number(n).toLocaleString('pt-BR'));

/* decimal pt-BR: toFixed() devolve ponto ('3.4') — a casa escreve virgula ('3,4') */
export const fmtD = (v, d) => (v == null || v === '' ? '—'
  : Number(v).toLocaleString('pt-BR', {minimumFractionDigits: d, maximumFractionDigits: d}));

/* pct assinado: o + so aparece quando e positivo — '+-8%' era bug em e_adit */
export const fmtPct = p => (p == null ? '—' : (p > 0 ? '+' : '') + fmtN(p) + '%');

export const fmtR = v => 'R$ ' + (v == null ? '0,00'
  : Number(v).toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2}));

export const fmtRc = v => {
  v = Number(v || 0); const a = Math.abs(v);
  if (a >= 1e9) return 'R$ ' + (v / 1e9).toLocaleString('pt-BR', {maximumFractionDigits: 1}) + ' bi';
  if (a >= 1e6) return 'R$ ' + (v / 1e6).toLocaleString('pt-BR', {maximumFractionDigits: 1}) + ' mi';
  if (a >= 1e3) return 'R$ ' + (v / 1e3).toLocaleString('pt-BR', {maximumFractionDigits: 0}) + ' mil';
  return fmtR(v);
};

// rótulos humanos p/ ids técnicos de sinal/detector — snake_case NUNCA chega ao usuário
export const ROTULOS={conluio_forte:'conluio societário',conluio_qsa:'conluio societário',sancao_a_epoca:'sanção vigente à época',
  sancao_fora_vigencia:'sanção fora da vigência',sancionada:'sancionada (CEIS/CNEP)',socio_servidor:'sócio na folha pública',
  fantasma_alto:'perfil fantasma (alto)',fantasma_medio:'perfil fantasma (médio)',fantasma_baixo:'perfil fantasma (baixo)',
  perdedora_contumaz:'perdedora contumaz',fenix:'empresa fênix',empresa_fenix:'empresa fênix',escalada_preco:'escalada de preço',
  sobrepreco:'sobrepreço unitário',fracionamento:'fracionamento de despesa',capital_incompativel:'capital incompatível',
  fornecedor_dependente:'fornecedor cativo',corrida_dezembro:'corrida de dezembro',socio_oculto:'sócio oculto',
  hub_massa:'membro de ninho (contato/endereço)',capital_irrisorio:'capital irrisório',conluio_medio:'conluio societário (médio)',
  nepotismo:'nepotismo',nepotismo_cruzado:'nepotismo cruzado',porta_giratoria:'porta giratória',
  situacao_irregular:'situação irregular na Receita',endereco_compartilhado:'endereço-ninho',endereco_residencial:'endereço residencial',
  aberta_as_vesperas:'aberta às vésperas',socio_unico_capital_baixo:'sócio único + capital baixo',cnae_incompativel:'CNAE incompatível',
  radar_risco:'radar de risco',prioridade_valor:'prioridade por valor',grafo_familias:'grafo de famílias',aditivos:'aditivos'};

export const rot = id => ROTULOS[id] || String(id || '').replace(/_/g, ' ');
