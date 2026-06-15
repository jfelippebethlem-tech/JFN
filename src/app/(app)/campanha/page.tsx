'use client'

import { useState, useEffect } from 'react'
import {
  TrendingUp, Loader2, RefreshCw, Zap, AlertTriangle,
  CheckCircle2, BarChart2, Clock, Lightbulb, Copy,
  CheckCheck, Heart, MessageCircle, Share2, Twitter,
  Instagram, Facebook, Target,
} from 'lucide-react'

type PostAnalise = { id: string; plataforma: string; conteudo: string; likes: number; comentarios: number; compartilhos: number; potencialViral?: number; score?: number }
type Analise = {
  analise: string
  stats: { totalLikes: number; totalComents: number; totalShares: number; mediaEng: number; totalFas: number; totalApoiadores: number }
  topPosts: PostAnalise[]
  flopPosts: PostAnalise[]
  viralPotential: PostAnalise[]
}
type Insight = { id: string; titulo: string; descricao: string; criadoEm: string }
type Horarios = { topHoras: { hora: number; mediaEng: number }[]; topDias: { dia: string; mediaEng: number }[] }

const PLAT_ICON: Record<string, React.ReactNode> = {
  twitter: <Twitter className="w-3.5 h-3.5 text-sky-500" />,
  instagram: <Instagram className="w-3.5 h-3.5 text-pink-500" />,
  facebook: <Facebook className="w-3.5 h-3.5 text-blue-600" />,
}

function ViralBar({ score }: { score: number }) {
  const color = score >= 70 ? 'bg-green-500' : score >= 40 ? 'bg-amber-500' : 'bg-red-400'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full ${color} transition-all`} style={{ width: `${score}%` }} />
      </div>
      <span className="text-xs font-bold text-gray-600 w-8 text-right">{score}</span>
    </div>
  )
}

export default function CampanhaPage() {
  const [analise, setAnalise] = useState<Analise | null>(null)
  const [insights, setInsights] = useState<Insight[]>([])
  const [horarios, setHorarios] = useState<Horarios | null>(null)
  const [loading, setLoading] = useState(true)
  const [analisando, setAnalisando] = useState(false)
  const [sugestao, setSugestao] = useState('')
  const [gerandoViral, setGerandoViral] = useState(false)
  const [tema, setTema] = useState('')
  const [copied, setCopied] = useState(false)
  const [tab, setTab] = useState<'diagnostico'|'viral'|'historico'>('diagnostico')

  async function loadData() {
    setLoading(true)
    const [ins, hor] = await Promise.all([
      fetch('/api/campanha?tipo=insights').then(r => r.json()),
      fetch('/api/campanha?tipo=horarios').then(r => r.json()),
    ])
    setInsights(Array.isArray(ins) ? ins : [])
    setHorarios(hor && !hor.error ? hor : null)
    setLoading(false)
  }

  async function handleAnalisar() {
    setAnalisando(true)
    const res = await fetch('/api/campanha', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acao: 'analisar' }),
    })
    const data = await res.json()
    if (data.analise) {
      setAnalise(data)
      await loadData()
    }
    setAnalisando(false)
  }

  async function handleSugerirViral() {
    setGerandoViral(true)
    setSugestao('')
    const res = await fetch('/api/campanha', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acao: 'sugerir_viral', tema }),
    })
    const data = await res.json()
    setSugestao(data.sugestao ?? '')
    setGerandoViral(false)
  }

  useEffect(() => { loadData() }, [])

  const TABS = [
    { id: 'diagnostico', label: 'Diagnóstico', icon: BarChart2 },
    { id: 'viral', label: 'Conteúdo Viral', icon: Zap },
    { id: 'historico', label: 'Histórico', icon: Clock },
  ] as const

  return (
    <div className="p-8 max-w-5xl">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-gradient-to-br from-green-500 to-blue-600 rounded-lg flex items-center justify-center">
              <TrendingUp className="w-4 h-4 text-white" />
            </div>
            <h1 className="text-2xl font-bold text-gray-900">Campanha</h1>
            <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full font-medium">Inteligência Digital</span>
          </div>
          <p className="text-gray-500 text-sm mt-1 ml-10">
            Analisa sua campanha, identifica erros e gera conteúdo com potencial viral
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 bg-gray-100 rounded-lg p-1">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button key={id} onClick={() => setTab(id)}
            className={`flex items-center gap-1.5 px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${tab === id ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>
            <Icon className="w-3.5 h-3.5" />{label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex justify-center py-16"><Loader2 className="w-6 h-6 animate-spin text-gray-400" /></div>
      ) : (
        <>
          {/* DIAGNÓSTICO */}
          {tab === 'diagnostico' && (
            <div className="space-y-5">
              {/* Botão de análise */}
              <button
                onClick={handleAnalisar}
                disabled={analisando}
                className="w-full btn-primary flex items-center justify-center gap-2 py-3 text-sm disabled:opacity-50"
              >
                {analisando ? (
                  <><Loader2 className="w-4 h-4 animate-spin" />Analisando sua campanha...</>
                ) : (
                  <><RefreshCw className="w-4 h-4" />Analisar Campanha Agora</>
                )}
              </button>

              {/* Horários sugeridos */}
              {horarios && (
                <div className="card">
                  <div className="flex items-center gap-2 mb-4">
                    <Clock className="w-4 h-4 text-blue-500" />
                    <h2 className="font-semibold text-gray-900">Melhores Horários para Postar</h2>
                    <span className="text-xs text-gray-400">(baseado nos seus dados reais)</span>
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <p className="text-xs font-medium text-gray-500 mb-2 uppercase">Melhores Horas</p>
                      <div className="space-y-2">
                        {horarios.topHoras.map((h, i) => (
                          <div key={i} className="flex items-center gap-2">
                            <span className="text-sm font-bold text-gray-700 w-12">{h.hora}h</span>
                            <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                              <div className="h-full bg-blue-500 rounded-full" style={{ width: `${Math.min(100, h.mediaEng * 10)}%` }} />
                            </div>
                            <span className="text-xs text-gray-400">{h.mediaEng.toFixed(1)}%</span>
                          </div>
                        ))}
                      </div>
                    </div>
                    <div>
                      <p className="text-xs font-medium text-gray-500 mb-2 uppercase">Melhores Dias</p>
                      <div className="space-y-2">
                        {horarios.topDias.map((d, i) => (
                          <div key={i} className="flex items-center gap-2">
                            <span className="text-sm font-bold text-gray-700 w-16">{d.dia}</span>
                            <div className="flex-1 h-2 bg-gray-100 rounded-full overflow-hidden">
                              <div className="h-full bg-green-500 rounded-full" style={{ width: `${Math.min(100, d.mediaEng * 10)}%` }} />
                            </div>
                            <span className="text-xs text-gray-400">{d.mediaEng.toFixed(1)}%</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Resultado da análise */}
              {analise && (
                <>
                  {/* Stats */}
                  <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
                    {[
                      { label: 'Curtidas', value: analise.stats.totalLikes, icon: Heart, color: 'text-red-500' },
                      { label: 'Comentários', value: analise.stats.totalComents, icon: MessageCircle, color: 'text-blue-500' },
                      { label: 'Compartilhos', value: analise.stats.totalShares, icon: Share2, color: 'text-green-500' },
                      { label: 'Engaj. Médio', value: `${analise.stats.mediaEng.toFixed(1)}%`, icon: TrendingUp, color: 'text-purple-500' },
                      { label: 'Fãs Bond', value: analise.stats.totalFas, icon: Target, color: 'text-orange-500' },
                      { label: 'Apoiadores', value: analise.stats.totalApoiadores, icon: CheckCircle2, color: 'text-teal-500' },
                    ].map(s => (
                      <div key={s.label} className="card p-3 text-center">
                        <s.icon className={`w-4 h-4 ${s.color} mx-auto mb-1`} />
                        <p className="text-lg font-bold text-gray-900">{typeof s.value === 'number' ? s.value.toLocaleString('pt-BR') : s.value}</p>
                        <p className="text-xs text-gray-400">{s.label}</p>
                      </div>
                    ))}
                  </div>

                  {/* Diagnóstico textual da IA */}
                  <div className="card border-l-4 border-blue-400">
                    <div className="flex items-center gap-2 mb-3">
                      <BarChart2 className="w-4 h-4 text-blue-500" />
                      <h2 className="font-semibold text-gray-900">Diagnóstico da Campanha</h2>
                    </div>
                    <p className="text-sm text-gray-700 whitespace-pre-line leading-relaxed">{analise.analise}</p>
                  </div>

                  {/* Top posts vs flops */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div className="card">
                      <div className="flex items-center gap-2 mb-3">
                        <CheckCircle2 className="w-4 h-4 text-green-500" />
                        <h3 className="font-semibold text-sm text-gray-900">Top Posts</h3>
                      </div>
                      <div className="space-y-3">
                        {analise.topPosts.map((p, i) => (
                          <div key={p.id} className="border-b border-gray-50 pb-2 last:border-0">
                            <div className="flex items-center gap-1.5 mb-1">
                              {PLAT_ICON[p.plataforma]}
                              <p className="text-xs text-gray-700 line-clamp-2 flex-1">{p.conteudo}</p>
                            </div>
                            {p.potencialViral !== undefined && (
                              <div className="mt-1">
                                <p className="text-xs text-gray-400 mb-0.5">Potencial viral</p>
                                <ViralBar score={p.potencialViral} />
                              </div>
                            )}
                            <div className="flex items-center gap-2 mt-1 text-xs text-gray-400">
                              <span className="flex items-center gap-0.5"><Heart className="w-2.5 h-2.5 text-red-400" />{p.likes}</span>
                              <span className="flex items-center gap-0.5"><MessageCircle className="w-2.5 h-2.5 text-blue-400" />{p.comentarios}</span>
                              <span className="flex items-center gap-0.5"><Share2 className="w-2.5 h-2.5 text-green-400" />{p.compartilhos}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                    <div className="card">
                      <div className="flex items-center gap-2 mb-3">
                        <AlertTriangle className="w-4 h-4 text-amber-500" />
                        <h3 className="font-semibold text-sm text-gray-900">Posts com Baixo Desempenho</h3>
                      </div>
                      <div className="space-y-3">
                        {analise.flopPosts.map(p => (
                          <div key={p.id} className="border-b border-gray-50 pb-2 last:border-0">
                            <div className="flex items-center gap-1.5 mb-1">
                              {PLAT_ICON[p.plataforma]}
                              <p className="text-xs text-gray-600 line-clamp-2 flex-1 opacity-75">{p.conteudo}</p>
                            </div>
                            <div className="flex items-center gap-2 mt-1 text-xs text-gray-300">
                              <span className="flex items-center gap-0.5"><Heart className="w-2.5 h-2.5" />{p.likes}</span>
                              <span className="flex items-center gap-0.5"><MessageCircle className="w-2.5 h-2.5" />{p.comentarios}</span>
                              <span className="flex items-center gap-0.5"><Share2 className="w-2.5 h-2.5" />{p.compartilhos}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </>
              )}

              {!analise && !analisando && (
                <div className="card text-center py-12">
                  <BarChart2 className="w-12 h-12 text-gray-200 mx-auto mb-3" />
                  <p className="text-gray-400 font-medium">Nenhuma análise gerada ainda</p>
                  <p className="text-gray-300 text-xs mt-1">Clique em "Analisar Campanha Agora" para obter o diagnóstico</p>
                </div>
              )}
            </div>
          )}

          {/* CONTEÚDO VIRAL */}
          {tab === 'viral' && (
            <div className="space-y-5">
              <div className="card">
                <div className="flex items-center gap-2 mb-4">
                  <Zap className="w-4 h-4 text-yellow-500" />
                  <h2 className="font-semibold text-gray-900">Gerador de Conteúdo Viral</h2>
                </div>
                <p className="text-xs text-gray-500 mb-4">
                  Bond analisa seus posts de maior engajamento e cria conteúdo otimizado para viralizar.
                </p>
                <div className="flex gap-2">
                  <input
                    value={tema}
                    onChange={e => setTema(e.target.value)}
                    className="input flex-1"
                    placeholder="Tema opcional (ex: segurança pública, saúde, educação)..."
                    onKeyDown={e => e.key === 'Enter' && handleSugerirViral()}
                  />
                  <button
                    onClick={handleSugerirViral}
                    disabled={gerandoViral}
                    className="btn-primary px-5 flex items-center gap-2 disabled:opacity-50 shrink-0"
                  >
                    {gerandoViral ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
                    Gerar
                  </button>
                </div>
              </div>

              {sugestao && (
                <div className="card border border-green-200 bg-green-50">
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <Lightbulb className="w-4 h-4 text-green-600" />
                      <h3 className="font-semibold text-green-900">Posts Gerados</h3>
                    </div>
                    <button
                      onClick={async () => { await navigator.clipboard.writeText(sugestao); setCopied(true); setTimeout(() => setCopied(false), 2000) }}
                      className="flex items-center gap-1.5 text-xs text-green-700 hover:text-green-900"
                    >
                      {copied ? <><CheckCheck className="w-3.5 h-3.5" />Copiado!</> : <><Copy className="w-3.5 h-3.5" />Copiar tudo</>}
                    </button>
                  </div>
                  <pre className="text-sm text-gray-800 whitespace-pre-wrap font-sans leading-relaxed">{sugestao}</pre>
                </div>
              )}

              {!sugestao && !gerandoViral && (
                <div className="card text-center py-12">
                  <Zap className="w-12 h-12 text-gray-200 mx-auto mb-3" />
                  <p className="text-gray-400 font-medium">Pronto para gerar conteúdo viral</p>
                  <p className="text-gray-300 text-xs mt-1">Deixe o tema em branco para que Bond escolha o melhor tema baseado nos seus dados</p>
                </div>
              )}
            </div>
          )}

          {/* HISTÓRICO */}
          {tab === 'historico' && (
            <div className="space-y-3">
              {insights.length === 0 ? (
                <div className="card text-center py-12">
                  <Clock className="w-12 h-12 text-gray-200 mx-auto mb-3" />
                  <p className="text-gray-400 font-medium">Nenhuma análise salva ainda</p>
                  <p className="text-gray-300 text-xs mt-1">Execute uma análise na aba "Diagnóstico"</p>
                </div>
              ) : (
                insights.map(insight => (
                  <div key={insight.id} className="card border-l-4 border-green-400 p-4">
                    <div className="flex items-center justify-between mb-2">
                      <p className="text-sm font-semibold text-gray-900">{insight.titulo}</p>
                      <span className="text-xs text-gray-400">{new Date(insight.criadoEm).toLocaleDateString('pt-BR')}</span>
                    </div>
                    <p className="text-xs text-gray-600 whitespace-pre-line line-clamp-6">{insight.descricao}</p>
                  </div>
                ))
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}
