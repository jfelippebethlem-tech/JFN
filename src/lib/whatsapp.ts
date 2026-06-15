/**
 * WhatsApp GRATUITO via Baileys (WhatsApp Web, sem custo de API).
 * Este módulo só lida com a FILA (enfileirar/consultar). O envio real é feito
 * pelo processo `whatsapp-worker.ts`, que mantém a conexão Baileys.
 *
 * Arquitetura desacoplada: app web e workers apenas escrevem na tabela
 * WhatsappFila; o worker drena a fila e envia. Status da conexão fica em
 * Configuracao (chave: "whatsapp_status" e "whatsapp_qr").
 */
import { prisma } from './db'

// Normaliza telefone brasileiro para o formato do WhatsApp (DDI 55 + DDD + número)
export function normalizarTelefone(tel?: string | null): string | null {
  if (!tel) return null
  let n = tel.replace(/\D/g, '')
  if (n.length < 10) return null
  // Remove zeros à esquerda
  n = n.replace(/^0+/, '')
  // Adiciona DDI 55 se não tiver
  if (!n.startsWith('55')) n = '55' + n
  // Esperado: 55 (2) + DDD (2) + número (8 ou 9) => 12 ou 13 dígitos
  if (n.length < 12 || n.length > 13) return null
  return n
}

export type TipoMensagem = 'notificacao' | 'cobranca' | 'nps' | 'conquista' | 'broadcast' | 'alerta'

// Enfileira uma mensagem para um telefone
export async function enfileirarWhatsapp(opts: {
  telefone: string
  mensagem: string
  tipo?: TipoMensagem
  pessoaId?: string
  referencia?: string
  agendadoPara?: Date
}) {
  const tel = normalizarTelefone(opts.telefone)
  if (!tel) return { ok: false, motivo: 'telefone inválido' }
  await prisma.whatsappFila.create({
    data: {
      telefone: tel,
      mensagem: opts.mensagem,
      tipo: opts.tipo ?? 'notificacao',
      pessoaId: opts.pessoaId,
      referencia: opts.referencia,
      agendadoPara: opts.agendadoPara,
    },
  })
  return { ok: true, telefone: tel }
}

// Envia em massa para todos os apoiadores com telefone (broadcast)
export async function enfileirarBroadcast(mensagem: string, tipo: TipoMensagem = 'broadcast', referencia?: string) {
  const apoiadores = await prisma.pessoa.findMany({
    where: { tipo: { in: ['apoiador', 'coordenador'] }, ativo: true, telefone: { not: null } },
    select: { id: true, telefone: true },
  })
  let enfileirados = 0
  for (const p of apoiadores) {
    const r = await enfileirarWhatsapp({ telefone: p.telefone!, mensagem, tipo, pessoaId: p.id, referencia })
    if (r.ok) enfileirados++
  }
  return { enfileirados, totalApoiadores: apoiadores.length }
}

// Status da conexão (lido da Configuracao, escrito pelo worker)
export async function statusWhatsapp(): Promise<{ status: string; qr: string | null; atualizadoEm: string | null }> {
  const [st, qr, at] = await Promise.all([
    prisma.configuracao.findUnique({ where: { chave: 'whatsapp_status' } }),
    prisma.configuracao.findUnique({ where: { chave: 'whatsapp_qr' } }),
    prisma.configuracao.findUnique({ where: { chave: 'whatsapp_status_em' } }),
  ])
  return {
    status: st?.valor ?? 'desconectado', // "desconectado"|"aguardando_qr"|"conectado"
    qr: qr?.valor || null,
    atualizadoEm: at?.valor ?? null,
  }
}

// Helper usado pelo worker para salvar status/QR
export async function setConfig(chave: string, valor: string) {
  await prisma.configuracao.upsert({
    where: { chave },
    update: { valor },
    create: { chave, valor },
  })
}

// Estatísticas da fila
export async function estatisticasFila() {
  const [pendente, enviado, erro] = await Promise.all([
    prisma.whatsappFila.count({ where: { status: 'pendente' } }),
    prisma.whatsappFila.count({ where: { status: 'enviado' } }),
    prisma.whatsappFila.count({ where: { status: 'erro' } }),
  ])
  return { pendente, enviado, erro }
}
