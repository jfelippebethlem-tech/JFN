import { NextRequest, NextResponse } from 'next/server'
import { calcularMetricasApoiadores, calcularHeatMap, quemCobrar } from '@/lib/metricas'

// GET /api/apoiadores/metricas?tipo=metricas|heatmap|cobrar
export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const tipo = searchParams.get('tipo') ?? 'metricas'
  const dias = parseInt(searchParams.get('dias') ?? '30')

  if (tipo === 'heatmap') return NextResponse.json(await calcularHeatMap(dias))
  if (tipo === 'cobrar') {
    const n = parseInt(searchParams.get('nPosts') ?? '3')
    return NextResponse.json(await quemCobrar(n))
  }
  return NextResponse.json(await calcularMetricasApoiadores(dias))
}
