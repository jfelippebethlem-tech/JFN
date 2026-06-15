import { NextResponse } from 'next/server'
import { captarEstadoCompleto } from '@/lib/estado'

// Sempre dinâmico: lê o banco em tempo real (nunca cachear no build)
export const dynamic = 'force-dynamic'

// GET /api/estado → retrato completo do sistema (para Hermes e dashboards)
export async function GET() {
  const estado = await captarEstadoCompleto()
  return NextResponse.json(estado)
}
