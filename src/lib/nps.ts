/**
 * pNPS — Net Promoter Score político dos apoiadores.
 * Pergunta: "De 0 a 10, qual a chance de você convencer um amigo a votar
 * no(a) Deputado(a)?"  Promotor 9-10, Passivo 7-8, Detrator 0-6.
 */
import { prisma } from './db'
import { enfileirarWhatsapp } from './whatsapp'

export function categoriaNps(nota: number): 'promotor' | 'passivo' | 'detrator' {
  if (nota >= 9) return 'promotor'
  if (nota >= 7) return 'passivo'
  return 'detrator'
}

// Registra a resposta de um apoiador
export async function registrarNps(pessoaId: string, nota: number, comentario?: string) {
  const n = Math.max(0, Math.min(10, Math.round(nota)))
  const categoria = categoriaNps(n)
  await prisma.npsResposta.create({ data: { pessoaId, nota: n, categoria, comentario } })
  await prisma.pessoa.update({ where: { id: pessoaId }, data: { npsUltimo: n, npsData: new Date() } })

  // Alerta: apoiador que caiu para detrator
  if (categoria === 'detrator') {
    const pessoa = await prisma.pessoa.findUnique({ where: { id: pessoaId } })
    await prisma.bondInsight.create({
      data: {
        titulo: `⚠️ Apoiador detrator: ${pessoa?.nome ?? pessoaId}`,
        descricao: `Deu nota ${n}/10 no pNPS. ${comentario ? `Comentou: "${comentario}". ` : ''}Recomenda-se contato pessoal para reconquista.`,
        tipo: 'alerta',
        dados: JSON.stringify({ pessoaId, nota: n }),
      },
    })
  }
  return { ok: true, categoria, nota: n }
}

// Calcula o pNPS geral (% promotores - % detratores)
export async function calcularNps() {
  const apoiadores = await prisma.pessoa.findMany({
    where: { tipo: { in: ['apoiador', 'coordenador'] }, ativo: true, npsUltimo: { not: null } },
    select: { id: true, nome: true, npsUltimo: true, npsData: true },
  })
  const total = apoiadores.length
  if (total === 0) {
    return { pnps: 0, total: 0, promotores: 0, passivos: 0, detratores: 0, semResposta: 0, detalhe: [] }
  }
  let promotores = 0, passivos = 0, detratores = 0
  for (const a of apoiadores) {
    const c = categoriaNps(a.npsUltimo!)
    if (c === 'promotor') promotores++
    else if (c === 'passivo') passivos++
    else detratores++
  }
  const semResposta = await prisma.pessoa.count({
    where: { tipo: { in: ['apoiador', 'coordenador'] }, ativo: true, npsUltimo: null },
  })
  const pnps = Math.round(((promotores - detratores) / total) * 100)
  return {
    pnps, total, promotores, passivos, detratores, semResposta,
    detalhe: apoiadores.map(a => ({ pessoaId: a.id, nome: a.nome, nota: a.npsUltimo, categoria: categoriaNps(a.npsUltimo!), data: a.npsData })),
  }
}

// Dispara a pesquisa pNPS via WhatsApp para apoiadores com telefone
export async function dispararPesquisaNps(nomeDeputado = 'o Deputado') {
  const apoiadores = await prisma.pessoa.findMany({
    where: { tipo: { in: ['apoiador', 'coordenador'] }, ativo: true, telefone: { not: null } },
    select: { id: true, nome: true, telefone: true },
  })
  const msg = (nome: string) =>
    `Olá ${nome.split(' ')[0]}! 🙏 Sua opinião vale muito.\n\nDe 0 a 10, qual a chance de você convencer um amigo a votar em ${nomeDeputado}?\n\nResponda com um número de 0 a 10. Obrigado pelo apoio! 💪`
  let enfileirados = 0
  for (const a of apoiadores) {
    const r = await enfileirarWhatsapp({ telefone: a.telefone!, mensagem: msg(a.nome), tipo: 'nps', pessoaId: a.id })
    if (r.ok) enfileirados++
  }
  return { enfileirados, total: apoiadores.length }
}
