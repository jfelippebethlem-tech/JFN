/**
 * CATÁLOGO DE AÇÕES — camada de ferramentas para o Hermes (IA fraca).
 *
 * Cada ação é auto-documentada: nome, descrição em pt-BR simples, parâmetros e
 * nível de segurança. O Hermes consegue (1) listar o catálogo, (2) captar o
 * estado, (3) escolher e executar uma ação por NOME com parâmetros simples.
 *
 * seguranca:
 *   "auto"      → leitura/análise, segura: o Hermes pode executar sozinho.
 *   "aprovacao" → envia mensagem externa ou altera algo sensível: o Hermes NÃO
 *                 executa sozinho; deve criar uma recomendação para o humano.
 */
import { prisma } from './db'
import { captarEstadoCompleto } from './estado'
import { calcularMetricasApoiadores, calcularHeatMap, quemCobrar } from './metricas'
import { compararShareOfVoice, sincronizarAdversarios, adicionarAdversario } from './adversarios'
import { calcularNps, dispararPesquisaNps, registrarNps } from './nps'
import { enfileirarWhatsapp, enfileirarBroadcast, statusWhatsapp } from './whatsapp'
import {
  gerarRankingCabos, buscarComentariosPendentes, sugerirResposta,
  analisarTopPosts, syncAll, gerarRelatorioSemanal,
} from './bond'
import { analisarPadroesCampanha, sugerirConteudoViral, analisarMelhoresHorarios } from './campanha'

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Params = Record<string, any>

export type Acao = {
  nome: string
  descricao: string
  categoria: 'estado' | 'apoiadores' | 'conteudo' | 'comentarios' | 'adversarios' | 'whatsapp' | 'nps' | 'redes'
  seguranca: 'auto' | 'aprovacao'
  parametros: Record<string, string> // nome do param -> descrição
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  executar: (p: Params) => Promise<any>
}

export const CATALOGO: Acao[] = [
  // ── ESTADO ──
  {
    nome: 'captar_estado',
    descricao: 'Retorna um retrato completo do sistema (deputado, redes, apoiadores, posts, cobranças, adversários, NPS, WhatsApp, alertas). Use ANTES de decidir qualquer coisa.',
    categoria: 'estado', seguranca: 'auto', parametros: {},
    executar: () => captarEstadoCompleto(),
  },

  // ── APOIADORES ──
  {
    nome: 'ranking_apoiadores',
    descricao: 'Lista os apoiadores ordenados por score de engajamento (curtidas×1 + comentários×2 + compartilhos×3).',
    categoria: 'apoiadores', seguranca: 'auto', parametros: {},
    executar: () => gerarRankingCabos(),
  },
  {
    nome: 'metricas_apoiadores',
    descricao: 'Métricas avançadas por apoiador: Influencer Score, Consistência (%), Velocidade de engajamento (min), streak.',
    categoria: 'apoiadores', seguranca: 'auto',
    parametros: { dias: 'período em dias (opcional, padrão 30)' },
    executar: (p) => calcularMetricasApoiadores(p.dias ?? 30),
  },
  {
    nome: 'quem_cobrar',
    descricao: 'Lista os apoiadores valiosos que NÃO engajaram nos posts recentes, ordenados por prioridade de cobrança.',
    categoria: 'apoiadores', seguranca: 'auto',
    parametros: { nPostsRecentes: 'quantos posts recentes considerar (opcional, padrão 3)' },
    executar: (p) => quemCobrar(p.nPostsRecentes ?? 3),
  },
  {
    nome: 'heatmap_engajamento',
    descricao: 'Mapa de calor: em quais horas e dias da semana os apoiadores mais engajam. Útil para escolher horário de postar/notificar.',
    categoria: 'apoiadores', seguranca: 'auto', parametros: {},
    executar: () => calcularHeatMap(30),
  },

  // ── CONTEÚDO / CAMPANHA ──
  {
    nome: 'analisar_campanha',
    descricao: 'Diagnóstico de IA da campanha: o que funciona, onde está errando, padrão do conteúdo viral, ações imediatas.',
    categoria: 'conteudo', seguranca: 'auto', parametros: {},
    executar: () => analisarPadroesCampanha(),
  },
  {
    nome: 'sugerir_conteudo_viral',
    descricao: 'Gera 3 sugestões de posts com alto potencial viral (texto, hashtags, melhor horário).',
    categoria: 'conteudo', seguranca: 'auto',
    parametros: { tema: 'tema do post (opcional)' },
    executar: (p) => sugerirConteudoViral(p.tema),
  },
  {
    nome: 'melhores_horarios',
    descricao: 'Calcula os melhores horários e dias para publicar com base no engajamento histórico dos posts.',
    categoria: 'conteudo', seguranca: 'auto', parametros: {},
    executar: () => analisarMelhoresHorarios(),
  },
  {
    nome: 'analisar_top_posts',
    descricao: 'Analisa os posts de maior engajamento e gera insight.',
    categoria: 'conteudo', seguranca: 'auto', parametros: {},
    executar: () => analisarTopPosts(),
  },

  // ── COMENTÁRIOS ──
  {
    nome: 'comentarios_pendentes',
    descricao: 'Lista os comentários ainda não respondidos, priorizando apoiadores e críticas.',
    categoria: 'comentarios', seguranca: 'auto', parametros: {},
    executar: () => buscarComentariosPendentes(),
  },
  {
    nome: 'sugerir_resposta_comentario',
    descricao: 'Gera uma sugestão de resposta para um comentário específico, no estilo do deputado.',
    categoria: 'comentarios', seguranca: 'auto',
    parametros: { comentarioId: 'ID do comentário', plataforma: 'instagram|facebook|twitter' },
    executar: (p) => sugerirResposta(p.comentarioId, p.plataforma),
  },

  // ── REDES ──
  {
    nome: 'sincronizar_redes',
    descricao: 'Sincroniza posts e interações de todas as redes do deputado (Twitter, Facebook, Instagram).',
    categoria: 'redes', seguranca: 'auto', parametros: {},
    executar: () => syncAll(),
  },
  {
    nome: 'gerar_relatorio_semanal',
    descricao: 'Gera o relatório semanal de redes sociais.',
    categoria: 'redes', seguranca: 'auto', parametros: {},
    executar: () => gerarRelatorioSemanal(),
  },

  // ── ADVERSÁRIOS ──
  {
    nome: 'share_of_voice',
    descricao: 'Compara o engajamento do deputado com os adversários monitorados (share of voice %).',
    categoria: 'adversarios', seguranca: 'auto',
    parametros: { dias: 'período em dias (opcional, padrão 30)' },
    executar: (p) => compararShareOfVoice(p.dias ?? 30),
  },
  {
    nome: 'sincronizar_adversarios',
    descricao: 'Atualiza os dados públicos dos adversários monitorados.',
    categoria: 'adversarios', seguranca: 'auto', parametros: {},
    executar: () => sincronizarAdversarios(),
  },
  {
    nome: 'adicionar_adversario',
    descricao: 'Passa a monitorar um novo perfil adversário.',
    categoria: 'adversarios', seguranca: 'aprovacao',
    parametros: { plataforma: 'instagram|twitter', handle: '@usuario', nome: 'nome (opcional)' },
    executar: (p) => adicionarAdversario(p.plataforma, p.handle, p.nome),
  },

  // ── WHATSAPP ──
  {
    nome: 'status_whatsapp',
    descricao: 'Mostra o status da conexão do WhatsApp e estatísticas da fila de mensagens.',
    categoria: 'whatsapp', seguranca: 'auto', parametros: {},
    executar: async () => ({ ...(await statusWhatsapp()) }),
  },
  {
    nome: 'enviar_whatsapp',
    descricao: 'Envia (enfileira) uma mensagem WhatsApp para um telefone ou apoiador específico.',
    categoria: 'whatsapp', seguranca: 'aprovacao',
    parametros: { telefone: 'número (ou use pessoaId)', pessoaId: 'ID do apoiador (opcional)', mensagem: 'texto da mensagem' },
    executar: async (p) => {
      let telefone = p.telefone
      if (!telefone && p.pessoaId) {
        const pe = await prisma.pessoa.findUnique({ where: { id: p.pessoaId } })
        telefone = pe?.telefone ?? undefined
      }
      if (!telefone) return { ok: false, motivo: 'sem telefone' }
      return enfileirarWhatsapp({ telefone, mensagem: p.mensagem, pessoaId: p.pessoaId, tipo: 'notificacao' })
    },
  },
  {
    nome: 'broadcast_whatsapp',
    descricao: 'Envia (enfileira) uma mensagem para TODOS os apoiadores com telefone cadastrado.',
    categoria: 'whatsapp', seguranca: 'aprovacao',
    parametros: { mensagem: 'texto da mensagem' },
    executar: (p) => enfileirarBroadcast(p.mensagem, 'broadcast'),
  },
  {
    nome: 'cobrar_apoiador',
    descricao: 'Envia (enfileira) uma cobrança gentil via WhatsApp pedindo que o apoiador engaje no último post.',
    categoria: 'whatsapp', seguranca: 'aprovacao',
    parametros: { pessoaId: 'ID do apoiador', linkPost: 'link do post (opcional)' },
    executar: async (p) => {
      const pe = await prisma.pessoa.findUnique({ where: { id: p.pessoaId } })
      if (!pe?.telefone) return { ok: false, motivo: 'apoiador sem telefone' }
      const msg = `Olá ${pe.nome.split(' ')[0]}! 🙏 Sentimos sua falta nas últimas publicações. Sua curtida e compartilhamento fazem MUITA diferença${p.linkPost ? `:\n${p.linkPost}` : '!'}\n\nConto com você! 💪`
      return enfileirarWhatsapp({ telefone: pe.telefone, mensagem: msg, pessoaId: pe.id, tipo: 'cobranca' })
    },
  },

  // ── NPS ──
  {
    nome: 'calcular_nps',
    descricao: 'Calcula o pNPS (Net Promoter Score político) dos apoiadores: promotores, passivos, detratores.',
    categoria: 'nps', seguranca: 'auto', parametros: {},
    executar: () => calcularNps(),
  },
  {
    nome: 'disparar_pesquisa_nps',
    descricao: 'Envia (enfileira) a pesquisa pNPS via WhatsApp para todos os apoiadores com telefone.',
    categoria: 'nps', seguranca: 'aprovacao',
    parametros: { nomeDeputado: 'nome a usar na mensagem (opcional)' },
    executar: (p) => dispararPesquisaNps(p.nomeDeputado),
  },
  {
    nome: 'registrar_nps',
    descricao: 'Registra a nota pNPS (0-10) que um apoiador respondeu.',
    categoria: 'nps', seguranca: 'auto',
    parametros: { pessoaId: 'ID do apoiador', nota: 'nota 0-10', comentario: 'comentário (opcional)' },
    executar: (p) => registrarNps(p.pessoaId, Number(p.nota), p.comentario),
  },
]

// Catálogo sem as funções (seguro p/ serializar e mostrar ao Hermes)
export function listarAcoes() {
  return CATALOGO.map(({ nome, descricao, categoria, seguranca, parametros }) => ({
    nome, descricao, categoria, seguranca, parametros,
  }))
}

export function buscarAcao(nome: string): Acao | undefined {
  return CATALOGO.find(a => a.nome === nome)
}

// Executa uma ação por nome, com log de auditoria
export async function executarAcao(nome: string, params: Params = {}, origem: 'hermes' | 'humano' | 'sistema' = 'humano') {
  const acao = buscarAcao(nome)
  if (!acao) {
    return { ok: false, erro: `Ação "${nome}" não existe. Use listarAcoes() para ver as disponíveis.` }
  }

  // Trava de segurança: Hermes não executa ações sensíveis sozinho
  if (origem === 'hermes' && acao.seguranca === 'aprovacao') {
    await prisma.bondInsight.create({
      data: {
        titulo: `🤖 Hermes recomenda: ${acao.nome}`,
        descricao: `O Hermes sugeriu executar "${acao.nome}" (${acao.descricao}) com parâmetros: ${JSON.stringify(params)}. Requer sua aprovação.`,
        tipo: 'sugestao',
        dados: JSON.stringify({ acao: acao.nome, params }),
      },
    })
    return { ok: false, requerAprovacao: true, mensagem: `Ação "${nome}" requer aprovação humana — recomendação registrada.` }
  }

  try {
    const resultado = await acao.executar(params)
    await prisma.acaoLog.create({
      data: { acao: nome, origem, params: JSON.stringify(params), resultado: JSON.stringify(resultado).slice(0, 1000), sucesso: true },
    })
    return { ok: true, resultado }
  } catch (e) {
    const erro = e instanceof Error ? e.message : String(e)
    await prisma.acaoLog.create({
      data: { acao: nome, origem, params: JSON.stringify(params), sucesso: false, erro },
    })
    return { ok: false, erro }
  }
}
