/**
 * captarEstadoCompleto() — "captar tudo" em UMA chamada.
 *
 * Devolve um retrato COMPLETO e ROTULADO do sistema, pensado para uma IA fraca
 * (Hermes 405B) entender a situação sem precisar fazer várias consultas. Cada
 * campo tem nome claro em pt-BR. Os números são limitados (top 5) para caber no
 * contexto do modelo.
 */
import { prisma } from './db'
import { calcularMetricasApoiadores, calcularHeatMap, quemCobrar } from './metricas'
import { compararShareOfVoice } from './adversarios'
import { calcularNps } from './nps'
import { statusWhatsapp, estatisticasFila } from './whatsapp'

export async function captarEstadoCompleto() {
  const [
    cfgNome, cfgPartido, cfgEstado,
    perfis, totalApoiadores, comTelefone, comRedes,
    postsRecentes, comentariosPendentes,
    metricas, heat, alvos, sov, nps, waStatus, waFila,
    alertas, insightsRecentes,
  ] = await Promise.all([
    prisma.configuracao.findUnique({ where: { chave: 'deputado_nome' } }),
    prisma.configuracao.findUnique({ where: { chave: 'deputado_partido' } }),
    prisma.configuracao.findUnique({ where: { chave: 'deputado_estado' } }),
    prisma.bondPerfil.findMany({ where: { categoria: 'proprio', ativo: true } }),
    prisma.pessoa.count({ where: { tipo: { in: ['apoiador', 'coordenador'] }, ativo: true } }),
    prisma.pessoa.count({ where: { tipo: { in: ['apoiador', 'coordenador'] }, ativo: true, telefone: { not: null } } }),
    prisma.bondFa.findMany({ where: { pessoa: { tipo: { in: ['apoiador', 'coordenador'] } } }, select: { pessoaId: true }, distinct: ['pessoaId'] }),
    prisma.bondPost.findMany({ where: { perfil: { categoria: 'proprio' } }, orderBy: { publicadoEm: 'desc' }, take: 5 }),
    prisma.bondComentario.count({ where: { respondido: false } }),
    calcularMetricasApoiadores(30).catch(() => []),
    calcularHeatMap(30).catch(() => null),
    quemCobrar(3).catch(() => []),
    compararShareOfVoice(30).catch(() => null),
    calcularNps().catch(() => null),
    statusWhatsapp().catch(() => ({ status: 'desconhecido', qr: null, atualizadoEm: null })),
    estatisticasFila().catch(() => ({ pendente: 0, enviado: 0, erro: 0 })),
    prisma.bondInsight.findMany({ where: { tipo: 'alerta', lido: false }, orderBy: { criadoEm: 'desc' }, take: 5 }),
    prisma.bondInsight.findMany({ orderBy: { criadoEm: 'desc' }, take: 5 }),
  ])

  const totalSeguidores = perfis.reduce((s, p) => s + p.seguidores, 0)
  const topPorScore = metricas.slice(0, 5).map(m => ({ nome: m.nome, score: m.score, consistencia: `${m.consistenciaPct}%`, streak: m.streak }))
  const topPorInfluencia = [...metricas].sort((a, b) => b.influencerScore - a.influencerScore).slice(0, 5)
    .map(m => ({ nome: m.nome, influencerScore: m.influencerScore, seguidores: m.seguidores, alcanceEstimado: m.alcanceEstimado }))

  return {
    capturadoEm: new Date().toISOString(),
    deputado: {
      nome: cfgNome?.valor ?? 'Deputado(a)',
      partido: cfgPartido?.valor ?? '',
      estado: cfgEstado?.valor ?? '',
    },
    redes: {
      perfis: perfis.map(p => ({ plataforma: p.plataforma, handle: p.handle, seguidores: p.seguidores, totalPosts: p.totalPosts })),
      totalSeguidores,
    },
    apoiadores: {
      total: totalApoiadores,
      comRedesVinculadas: comRedes.length,
      comTelefone,
      topPorScore,
      topPorInfluencia,
    },
    posts: {
      total: postsRecentes.length,
      ultimos: postsRecentes.map(p => ({
        id: p.id, plataforma: p.plataforma, resumo: (p.conteudo ?? '').slice(0, 80),
        likes: p.likes, comentarios: p.comentarios, compartilhos: p.compartilhos,
        publicadoEm: p.publicadoEm, notificadoApoiadores: p.notificado,
      })),
    },
    comentarios: { pendentes: comentariosPendentes },
    cobranca: {
      totalAlvos: alvos.length,
      prioritarios: alvos.slice(0, 5).map(a => ({ nome: a.nome, telefone: a.telefone, faltou: a.postsRecentesSemEngajar, consistencia: `${a.consistenciaPct}%`, prioridade: a.prioridade })),
    },
    melhoresHorarios: heat ? { melhorHora: `${heat.melhorHora}h`, melhorDia: heat.melhorDia.nome, totalInteracoes: heat.totalInteracoes } : null,
    adversarios: sov ? {
      shareOfVoicePct: sov.shareOfVoicePct,
      meuEngajamento: sov.meuEngajamento,
      engajamentoAdversarios: sov.engajamentoAdversarios,
      lista: sov.adversarios.map(a => ({ handle: a.handle, plataforma: a.plataforma, engajamentoTotal: a.engajamentoTotal })),
    } : null,
    nps: nps ? { pnps: nps.pnps, promotores: nps.promotores, passivos: nps.passivos, detratores: nps.detratores, semResposta: nps.semResposta } : null,
    whatsapp: { conexao: waStatus.status, fila: waFila },
    alertas: alertas.map(a => ({ titulo: a.titulo, descricao: a.descricao.slice(0, 160), criadoEm: a.criadoEm })),
    insightsRecentes: insightsRecentes.map(i => ({ titulo: i.titulo, tipo: i.tipo, criadoEm: i.criadoEm })),
  }
}
