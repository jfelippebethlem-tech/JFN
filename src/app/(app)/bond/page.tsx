'use client'

import { useState, useEffect, useRef } from 'react'
import {
  Link2, RefreshCw, Loader2, BarChart2, Users, FileText,
  Lightbulb, Pencil, Send, Twitter, Instagram, Facebook,
  Heart, MessageCircle, Share2, Eye, TrendingUp, Bot,
  Copy, CheckCheck, Save, Trash2, ChevronRight, Trophy,
  MessageSquare, Check, X, Star, Medal, Crown,
} from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { ptBR } from 'date-fns/locale'

type Perfil = { id: string; plataforma: string; handle: string; nomeCompleto?: string; seguidores: number; fotoUrl?: string; ultimaSync?: string }
type Post = { id: string; plataforma: string; postId: string; conteudo: string; tipo: string; url?: string; imagemUrl?: string; likes: number; comentarios: number; compartilhos: number; alcance: number; engajamento: number; publicadoEm: string; perfil?: Perfil }
type Fa = { id: string; plataforma: string; nome?: string; username?: string; totalLikes: number; totalComents: number; totalShares: number; ultimaInter?: string; pessoa?: { id: string; nome: string; tipo: string } | null }
type RankingItem = { plataforma: string; externalId?: string; nome?: string | null; username?: string | null; score: number; totalLikes?: number; totalComents?: number; totalShares?: number; likes?: number; comments?: number; shares?: number; pessoa?: { id: string; nome: string; tipo: string } | null }
type RankingCaboItem = { pessoaId: string; nome: string; tipo: string; cargo?: string | null; instagram?: string | null; twitter?: string | null; facebook?: string | null; plataformas: string[]; totalLikes: number; totalComents: number; totalShares: number; score: number }
type Comentario = { id: string; plataforma: string; postId: string; comentarioId: string; autor?: string | null; autorId?: string | null; texto: string; respondido: boolean; sugestaoIA?: string | null; respostaFinal?: string | null; criadoEm: string; categoria?: string; isCabo?: boolean }
type Insight = { id: string; titulo: string; descricao: string; tipo: string; plataforma?: string; lido: boolean; criadoEm: string }
type Rascunho = { id: string; titulo?: string; texto: string; plataformas: string; hashtags?: string; status: string; criadoEm: string }
type Msg = { role: 'user' | 'assistant'; content: string }

const PLAT_ICON: Record<string, React.ReactNode> = {
  twitter: <Twitter className="w-4 h-4 text-sky-500" />,
  instagram: <Instagram className="w-4 h-4 text-pink-500" />,
  facebook: <Facebook className="w-4 h-4 text-blue-600" />,
}
const PLAT_COLOR: Record<string, string> = {
  twitter: 'bg-sky-100 text-sky-700',
  instagram: 'bg-pink-100 text-pink-700',
  facebook: 'bg-blue-100 text-blue-700',
}

const RANK_MEDAL = [
  <Crown key={0} className="w-4 h-4 text-yellow-500" />,
  <Medal key={1} className="w-4 h-4 text-gray-400" />,
  <Medal key={2} className="w-4 h-4 text-amber-600" />,
]

export default function BondPage() {
  const [tab, setTab] = useState<'overview'|'posts'|'rankings'|'comentarios'|'insights'|'studio'>('overview')
  const [overview, setOverview] = useState<{
    perfis: Perfil[]; totalPosts: number; totalFas: number;
    insightsNaoLidos: number; comentariosPendentes: number;
    stats: { _sum: { likes?: number; comentarios?: number; compartilhos?: number; alcance?: number }; _avg: { engajamento?: number } }
  } | null>(null)
  const [posts, setPosts] = useState<Post[]>([])
  const [rankingGeral, setRankingGeral] = useState<RankingItem[]>([])
  const [rankingSemanal, setRankingSemanal] = useState<RankingItem[]>([])
  const [rankingCabos, setRankingCabos] = useState<RankingCaboItem[]>([])
  const [rankingSubTab, setRankingSubTab] = useState<'cabos'|'geral'|'semanal'>('cabos')
  const [comentarios, setComentarios] = useState<Comentario[]>([])
  const [insights, setInsights] = useState<Insight[]>([])
  const [rascunhos, setRascunhos] = useState<Rascunho[]>([])
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [platFilter, setPlatFilter] = useState('todas')

  // Comentários state
  const [editandoId, setEditandoId] = useState<string | null>(null)
  const [textoEditado, setTextoEditado] = useState('')
  const [gerandoId, setGerandoId] = useState<string | null>(null)

  // Studio state
  const [chatMsgs, setChatMsgs] = useState<Msg[]>([])
  const [chatInput, setChatInput] = useState('')
  const [chatLoading, setChatLoading] = useState(false)
  const [tema, setTema] = useState('')
  const [platGen, setPlatGen] = useState('instagram')
  const [gerando, setGerando] = useState(false)
  const [sugestao, setSugestao] = useState('')
  const [copied, setCopied] = useState(false)
  const chatEndRef = useRef<HTMLDivElement>(null)

  async function load() {
    setLoading(true)
    const [ov, p, rc, rg, rs, coms, i, r] = await Promise.all([
      fetch('/api/bond').then(r => r.json()),
      fetch('/api/bond?tipo=posts').then(r => r.json()),
      fetch('/api/bond?tipo=ranking_cabos').then(r => r.json()),
      fetch('/api/bond?tipo=ranking_geral').then(r => r.json()),
      fetch('/api/bond?tipo=ranking_semanal').then(r => r.json()),
      fetch('/api/bond?tipo=comentarios').then(r => r.json()),
      fetch('/api/bond?tipo=insights').then(r => r.json()),
      fetch('/api/bond?tipo=rascunhos').then(r => r.json()),
    ])
    setOverview(ov)
    setPosts(Array.isArray(p) ? p : [])
    setRankingCabos(Array.isArray(rc) ? rc : [])
    setRankingGeral(Array.isArray(rg) ? rg : [])
    setRankingSemanal(Array.isArray(rs) ? rs : [])
    setComentarios(Array.isArray(coms) ? coms : [])
    setInsights(Array.isArray(i) ? i : [])
    setRascunhos(Array.isArray(r) ? r : [])
    setLoading(false)
  }

  useEffect(() => { load() }, [])
  useEffect(() => { chatEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [chatMsgs])

  async function handleSync(plat?: string) {
    setSyncing(true)
    await fetch('/api/bond', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acao: 'sync', plataforma: plat }),
    })
    await load()
    setSyncing(false)
  }

  async function handleGerarResposta(com: Comentario) {
    setGerandoId(com.comentarioId)
    const res = await fetch('/api/bond', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acao: 'sugerir_resposta', comentarioId: com.comentarioId, plataforma: com.plataforma }),
    })
    const data = await res.json()
    setComentarios(prev => prev.map(c =>
      c.comentarioId === com.comentarioId ? { ...c, sugestaoIA: data.sugestao } : c
    ))
    setEditandoId(com.comentarioId)
    setTextoEditado(data.sugestao ?? '')
    setGerandoId(null)
  }

  async function handleAprovar(com: Comentario) {
    const texto = textoEditado || com.sugestaoIA || ''
    if (!texto) return
    await fetch('/api/bond', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acao: 'aprovar_resposta', comentarioId: com.comentarioId, plataforma: com.plataforma, texto }),
    })
    setComentarios(prev => prev.filter(c => c.comentarioId !== com.comentarioId))
    setEditandoId(null)
    setTextoEditado('')
  }

  async function handleRejeitar(com: Comentario) {
    await fetch('/api/bond', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acao: 'rejeitar_comentario', comentarioId: com.comentarioId, plataforma: com.plataforma }),
    })
    setComentarios(prev => prev.filter(c => c.comentarioId !== com.comentarioId))
    setEditandoId(null)
  }

  async function handleChat(e: React.FormEvent) {
    e.preventDefault()
    if (!chatInput.trim() || chatLoading) return
    const msg = chatInput.trim()
    setChatInput('')
    setChatMsgs(prev => [...prev, { role: 'user', content: msg }])
    setChatLoading(true)
    const res = await fetch('/api/bond', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acao: 'chat', mensagem: msg, historico: chatMsgs.slice(-8) }),
    })
    const data = await res.json()
    setChatMsgs(prev => [...prev, { role: 'assistant', content: data.resposta ?? 'Erro' }])
    setChatLoading(false)
  }

  async function handleSugerir() {
    setGerando(true)
    setSugestao('')
    const res = await fetch('/api/bond', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acao: 'sugerir_conteudo', tema, plataforma: platGen }),
    })
    const data = await res.json()
    setSugestao(data.sugestao ?? '')
    setGerando(false)
  }

  async function handleSalvarRascunho() {
    if (!sugestao) return
    await fetch('/api/bond', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acao: 'salvar_rascunho', texto: sugestao, plataformas: platGen, titulo: tema }),
    })
    await load()
    setSugestao('')
    setTema('')
  }

  async function handleCopy() {
    await navigator.clipboard.writeText(sugestao)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  async function handleDeletarRascunho(id: string) {
    await fetch('/api/bond', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acao: 'deletar_rascunho', id }),
    })
    setRascunhos(prev => prev.filter(r => r.id !== id))
  }

  async function handleMarcarLido(id: string) {
    await fetch('/api/bond', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acao: 'marcar_insight_lido', id }),
    })
    setInsights(prev => prev.map(i => i.id === id ? { ...i, lido: true } : i))
  }

  const filteredPosts = platFilter === 'todas' ? posts : posts.filter(p => p.plataforma === platFilter)
  const comentariosPendentes = overview?.comentariosPendentes ?? comentarios.length

  const tabs = [
    { id: 'overview', label: 'Visão Geral', icon: BarChart2 },
    { id: 'posts', label: `Posts (${posts.length})`, icon: FileText },
    { id: 'rankings', label: 'Rankings', icon: Trophy },
    { id: 'comentarios', label: `Comentários${comentariosPendentes > 0 ? ` (${comentariosPendentes})` : ''}`, icon: MessageSquare },
    { id: 'insights', label: `Insights${insights.filter(i => !i.lido).length > 0 ? ` (${insights.filter(i => !i.lido).length})` : ''}`, icon: Lightbulb },
    { id: 'studio', label: 'Estúdio', icon: Pencil },
  ]

  function RankingRow({ item, position }: { item: RankingItem; position: number }) {
    const nome = item.nome ?? item.username ?? `ID…${(item.externalId ?? '').slice(-6)}`
    const isApoiador = item.pessoa?.tipo === 'apoiador'
    return (
      <div className="flex items-center gap-3 px-3 py-3 hover:bg-gray-50 rounded-lg">
        <div className="w-7 flex justify-center shrink-0">
          {position < 3 ? RANK_MEDAL[position] : <span className="text-xs text-gray-300 font-medium">{position + 1}</span>}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <p className="text-sm font-medium text-gray-900 truncate">{nome}</p>
            {isApoiador && (
              <span className="flex items-center gap-0.5 text-xs bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded-full font-medium shrink-0">
                <Star className="w-2.5 h-2.5" />Apoiador
              </span>
            )}
          </div>
          <div className="flex items-center gap-1 mt-0.5">{PLAT_ICON[item.plataforma]}<span className="text-xs text-gray-400">{item.plataforma}</span></div>
        </div>
        <div className="flex items-center gap-3 text-xs shrink-0">
          {item.totalLikes !== undefined && (
            <>
              <span className="flex items-center gap-1 text-red-600"><Heart className="w-3 h-3" />{item.totalLikes ?? item.likes ?? 0}</span>
              <span className="flex items-center gap-1 text-blue-600"><MessageCircle className="w-3 h-3" />{item.totalComents ?? item.comments ?? 0}</span>
              <span className="flex items-center gap-1 text-green-600"><Share2 className="w-3 h-3" />{item.totalShares ?? item.shares ?? 0}</span>
            </>
          )}
          {item.likes !== undefined && item.totalLikes === undefined && (
            <>
              <span className="flex items-center gap-1 text-red-600"><Heart className="w-3 h-3" />{item.likes}</span>
              <span className="flex items-center gap-1 text-blue-600"><MessageCircle className="w-3 h-3" />{item.comments}</span>
              <span className="flex items-center gap-1 text-green-600"><Share2 className="w-3 h-3" />{item.shares}</span>
            </>
          )}
          <span className="bg-gray-900 text-white text-xs px-2 py-0.5 rounded-full font-bold min-w-[40px] text-center">{item.score}</span>
        </div>
      </div>
    )
  }

  return (
    <div className="p-8 max-w-5xl">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-gradient-to-br from-sky-500 to-pink-500 rounded-lg flex items-center justify-center">
              <Link2 className="w-4 h-4 text-white" />
            </div>
            <h1 className="text-2xl font-bold text-gray-900">Bond</h1>
            <span className="flex items-center gap-1 text-xs bg-gradient-to-r from-sky-100 to-pink-100 text-sky-700 px-2 py-0.5 rounded-full font-medium">
              <span className="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse" />
              Social Intelligence
            </span>
          </div>
          <p className="text-gray-500 text-sm mt-1 ml-10">
            Monitora Facebook, X e Instagram — posts, rankings, comentários e criação de conteúdo
          </p>
        </div>
        <button
          onClick={() => handleSync()}
          disabled={syncing}
          className="btn-secondary flex items-center gap-1.5 text-xs"
        >
          {syncing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          Sincronizar Tudo
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 bg-gray-100 rounded-lg p-1 overflow-x-auto">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id as typeof tab)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium whitespace-nowrap transition-colors ${
              tab === id ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            <Icon className="w-3.5 h-3.5" />
            {label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex justify-center py-16"><Loader2 className="w-6 h-6 animate-spin text-gray-400" /></div>
      ) : (
        <>
          {/* VISÃO GERAL */}
          {tab === 'overview' && (
            <div className="space-y-6">
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {[
                  { label: 'Total Posts', value: overview?.totalPosts ?? 0, icon: FileText, color: 'bg-blue-500' },
                  { label: 'Apoiadores Ativos', value: overview?.totalFas ?? 0, icon: Users, color: 'bg-pink-500' },
                  { label: 'Total Curtidas', value: overview?.stats._sum.likes ?? 0, icon: Heart, color: 'bg-red-500' },
                  { label: 'Engaj. Médio', value: `${(overview?.stats._avg.engajamento ?? 0).toFixed(1)}%`, icon: TrendingUp, color: 'bg-green-500' },
                ].map(s => (
                  <div key={s.label} className="card">
                    <div className="flex items-start justify-between">
                      <div>
                        <p className="text-xs text-gray-500">{s.label}</p>
                        <p className="text-2xl font-bold text-gray-900 mt-1">{typeof s.value === 'number' ? s.value.toLocaleString('pt-BR') : s.value}</p>
                      </div>
                      <div className={`${s.color} p-2 rounded-lg`}><s.icon className="w-4 h-4 text-white" /></div>
                    </div>
                  </div>
                ))}
              </div>

              {/* Alertas rápidos */}
              {(comentariosPendentes > 0 || (insights.filter(i => !i.lido).length > 0)) && (
                <div className="flex gap-3">
                  {comentariosPendentes > 0 && (
                    <button onClick={() => setTab('comentarios')} className="flex-1 flex items-center gap-2 p-3 bg-amber-50 border border-amber-200 rounded-lg hover:bg-amber-100 transition-colors">
                      <MessageSquare className="w-4 h-4 text-amber-600 shrink-0" />
                      <span className="text-sm text-amber-800 font-medium">{comentariosPendentes} comentário{comentariosPendentes !== 1 ? 's' : ''} aguardando resposta</span>
                      <ChevronRight className="w-3.5 h-3.5 text-amber-500 ml-auto" />
                    </button>
                  )}
                  {insights.filter(i => !i.lido).length > 0 && (
                    <button onClick={() => setTab('insights')} className="flex-1 flex items-center gap-2 p-3 bg-sky-50 border border-sky-200 rounded-lg hover:bg-sky-100 transition-colors">
                      <Lightbulb className="w-4 h-4 text-sky-600 shrink-0" />
                      <span className="text-sm text-sky-800 font-medium">{insights.filter(i => !i.lido).length} insight{insights.filter(i => !i.lido).length !== 1 ? 's' : ''} novo{insights.filter(i => !i.lido).length !== 1 ? 's' : ''}</span>
                      <ChevronRight className="w-3.5 h-3.5 text-sky-500 ml-auto" />
                    </button>
                  )}
                </div>
              )}

              {/* Perfis conectados */}
              <div className="card">
                <h2 className="font-semibold text-gray-900 mb-4">Perfis Conectados</h2>
                {(overview?.perfis ?? []).length === 0 ? (
                  <div className="text-center py-8">
                    <Link2 className="w-10 h-10 text-gray-200 mx-auto mb-2" />
                    <p className="text-sm text-gray-400">Nenhum perfil conectado ainda.</p>
                    <p className="text-xs text-gray-300 mt-1">Configure as chaves de API no .env e clique em Sincronizar Tudo</p>
                    <div className="mt-4 text-xs text-left bg-gray-50 rounded-lg p-4 space-y-1 max-w-sm mx-auto">
                      <p className="font-medium text-gray-600">Variáveis necessárias:</p>
                      <p className="font-mono text-gray-500">TWITTER_BEARER_TOKEN</p>
                      <p className="font-mono text-gray-500">TWITTER_USERNAME</p>
                      <p className="font-mono text-gray-500">FACEBOOK_PAGE_TOKEN</p>
                    </div>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    {(overview?.perfis ?? []).map(p => (
                      <div key={p.id} className="flex items-center gap-3 p-3 border border-gray-200 rounded-lg">
                        <div className="w-10 h-10 rounded-full bg-gray-100 flex items-center justify-center overflow-hidden">
                          {p.fotoUrl ? <img src={p.fotoUrl} alt="" className="w-full h-full object-cover" /> : PLAT_ICON[p.plataforma]}
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-gray-900 truncate">{p.nomeCompleto ?? p.handle}</p>
                          <p className="text-xs text-gray-400">@{p.handle} · {p.seguidores.toLocaleString('pt-BR')} seguidores</p>
                        </div>
                        <button onClick={() => handleSync(p.plataforma)} disabled={syncing} className="p-1.5 hover:bg-gray-100 rounded-lg">
                          <RefreshCw className="w-3.5 h-3.5 text-gray-400" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Top posts preview */}
              {posts.length > 0 && (
                <div className="card">
                  <h2 className="font-semibold text-gray-900 mb-4">Top Posts por Engajamento</h2>
                  <div className="space-y-2">
                    {[...posts].sort((a, b) => b.engajamento - a.engajamento).slice(0, 5).map(post => (
                      <div key={post.id} className="flex items-center gap-3 p-2 hover:bg-gray-50 rounded-lg">
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${PLAT_COLOR[post.plataforma]}`}>{post.plataforma}</span>
                        <p className="text-sm text-gray-700 flex-1 truncate">{post.conteudo.slice(0, 80)}</p>
                        <div className="flex items-center gap-3 text-xs text-gray-400 shrink-0">
                          <span className="flex items-center gap-1"><Heart className="w-3 h-3" />{post.likes}</span>
                          <span className="flex items-center gap-1"><TrendingUp className="w-3 h-3" />{post.engajamento.toFixed(1)}%</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* POSTS */}
          {tab === 'posts' && (
            <div>
              <div className="flex gap-2 mb-4">
                {['todas', 'twitter', 'instagram', 'facebook'].map(p => (
                  <button key={p} onClick={() => setPlatFilter(p)}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${platFilter === p ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}>
                    {p !== 'todas' && PLAT_ICON[p]}
                    {p === 'todas' ? 'Todas' : p.charAt(0).toUpperCase() + p.slice(1)}
                  </button>
                ))}
              </div>
              {filteredPosts.length === 0 ? (
                <div className="card text-center py-12">
                  <FileText className="w-10 h-10 text-gray-200 mx-auto mb-2" />
                  <p className="text-gray-400 text-sm">Nenhum post ainda. Sincronize as redes sociais.</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {filteredPosts.map(post => (
                    <div key={post.id} className="card p-4">
                      <div className="flex items-start gap-3">
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium shrink-0 ${PLAT_COLOR[post.plataforma]}`}>{post.plataforma}</span>
                        <div className="flex-1">
                          {post.imagemUrl && (
                            <img src={post.imagemUrl} alt="" className="w-full max-h-48 object-cover rounded-lg mb-2" />
                          )}
                          <p className="text-sm text-gray-800 whitespace-pre-wrap line-clamp-3">{post.conteudo}</p>
                          <div className="flex items-center gap-4 mt-3 text-xs text-gray-400">
                            <span className="flex items-center gap-1"><Heart className="w-3 h-3 text-red-400" />{post.likes.toLocaleString()}</span>
                            <span className="flex items-center gap-1"><MessageCircle className="w-3 h-3 text-blue-400" />{post.comentarios.toLocaleString()}</span>
                            <span className="flex items-center gap-1"><Share2 className="w-3 h-3 text-green-400" />{post.compartilhos.toLocaleString()}</span>
                            <span className="flex items-center gap-1"><Eye className="w-3 h-3 text-purple-400" />{post.alcance.toLocaleString()}</span>
                            <span className="flex items-center gap-1 ml-auto font-medium text-gray-600"><TrendingUp className="w-3 h-3" />{post.engajamento.toFixed(2)}%</span>
                            <span>{formatDistanceToNow(new Date(post.publicadoEm), { addSuffix: true, locale: ptBR })}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* RANKINGS */}
          {tab === 'rankings' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
                  {([
                    { id: 'cabos', label: '🏅 Apoiadores' },
                    { id: 'geral', label: '🌐 Geral (Todos)' },
                    { id: 'semanal', label: '📅 Esta Semana' },
                  ] as const).map(s => (
                    <button key={s.id} onClick={() => setRankingSubTab(s.id)}
                      className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${rankingSubTab === s.id ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`}>
                      {s.label}
                    </button>
                  ))}
                </div>
                <p className="text-xs text-gray-400">❤×1 · 💬×2 · 🔁×3</p>
              </div>

              {/* RANKING CABOS ELEITORAIS */}
              {rankingSubTab === 'cabos' && (
                <div className="card">
                  <div className="flex items-center gap-2 mb-4">
                    <Trophy className="w-4 h-4 text-yellow-500" />
                    <h2 className="font-semibold text-gray-900">Ranking de Apoiadores</h2>
                    <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full">{rankingCabos.length} cadastrados</span>
                  </div>
                  {rankingCabos.length === 0 ? (
                    <div className="text-center py-12">
                      <Users className="w-10 h-10 text-gray-200 mx-auto mb-2" />
                      <p className="text-gray-400 text-sm">Nenhum cabo cadastrado ainda.</p>
                      <a href="/apoiadores" className="text-xs text-blue-500 hover:underline mt-1 inline-block">Ir para Apoiadores →</a>
                    </div>
                  ) : (
                    <div className="space-y-1">
                      <div className="grid grid-cols-[28px_1fr_auto_auto] text-xs font-medium text-gray-400 uppercase px-3 pb-2 border-b border-gray-100">
                        <span>#</span><span>Cabo</span><span>Redes</span><span className="text-right">❤ 💬 🔁 Pts</span>
                      </div>
                      {rankingCabos.map((item, i) => {
                        const medal = i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : null
                        const handle = item.instagram ?? item.twitter ?? item.facebook ?? null
                        return (
                          <div key={item.pessoaId} className="grid grid-cols-[28px_1fr_auto_auto] items-center gap-3 px-3 py-3 hover:bg-gray-50 rounded-lg">
                            <div className="flex justify-center">
                              {medal ? <span className="text-base">{medal}</span> : <span className="text-xs text-gray-300">{i + 1}</span>}
                            </div>
                            <div>
                              <div className="flex items-center gap-1.5">
                                <p className="text-sm font-medium text-gray-900">{item.nome}</p>
                                <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${item.tipo === 'coordenador' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'}`}>
                                  {item.tipo === 'coordenador' ? 'Coord.' : 'Apoiador'}
                                </span>
                              </div>
                              {(handle || item.cargo) && (
                                <p className="text-xs text-gray-400 mt-0.5">
                                  {handle && `@${handle}`}{handle && item.cargo && ' · '}{item.cargo}
                                </p>
                              )}
                            </div>
                            <div className="flex items-center gap-1">
                              {item.plataformas.map(p => (
                                <span key={p}>{PLAT_ICON[p]}</span>
                              ))}
                              {item.plataformas.length === 0 && <span className="text-xs text-gray-300">—</span>}
                            </div>
                            <div className="flex items-center gap-2 text-xs shrink-0">
                              <span className="flex items-center gap-0.5 text-red-500"><Heart className="w-3 h-3" />{item.totalLikes}</span>
                              <span className="flex items-center gap-0.5 text-blue-500"><MessageCircle className="w-3 h-3" />{item.totalComents}</span>
                              <span className="flex items-center gap-0.5 text-green-500"><Share2 className="w-3 h-3" />{item.totalShares}</span>
                              <span className={`font-bold px-2 py-0.5 rounded-full min-w-[36px] text-center ${item.score > 0 ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-400'}`}>{item.score}</span>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              )}

              {/* RANKING GERAL */}
              {rankingSubTab === 'geral' && (
                <div className="card">
                  <div className="flex items-center gap-2 mb-4">
                    <Trophy className="w-4 h-4 text-yellow-500" />
                    <h2 className="font-semibold text-gray-900">Ranking Geral — Todos os Apoiadores</h2>
                  </div>
                  {rankingGeral.length === 0 ? (
                    <div className="text-center py-12">
                      <Trophy className="w-10 h-10 text-gray-200 mx-auto mb-2" />
                      <p className="text-gray-400 text-sm">Nenhuma interação mapeada ainda. Sincronize as redes.</p>
                    </div>
                  ) : (
                    <div className="space-y-1">
                      <div className="grid grid-cols-[28px_1fr_auto] text-xs font-medium text-gray-400 uppercase px-3 pb-2 border-b border-gray-100">
                        <span>#</span><span>Apoiador</span><span className="text-right">❤ 💬 🔁 Pts</span>
                      </div>
                      {rankingGeral.map((item, i) => (
                        <RankingRow key={`${item.plataforma}:${item.externalId}`} item={item} position={i} />
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* RANKING SEMANAL */}
              {rankingSubTab === 'semanal' && (
                <div className="card">
                  <div className="flex items-center gap-2 mb-4">
                    <TrendingUp className="w-4 h-4 text-green-500" />
                    <h2 className="font-semibold text-gray-900">Ranking Semanal — Últimos 7 Dias</h2>
                  </div>
                  {rankingSemanal.length === 0 ? (
                    <div className="text-center py-12">
                      <TrendingUp className="w-10 h-10 text-gray-200 mx-auto mb-2" />
                      <p className="text-gray-400 text-sm">Nenhuma interação registrada nesta semana ainda.</p>
                    </div>
                  ) : (
                    <div className="space-y-1">
                      <div className="grid grid-cols-[28px_1fr_auto] text-xs font-medium text-gray-400 uppercase px-3 pb-2 border-b border-gray-100">
                        <span>#</span><span>Apoiador</span><span className="text-right">❤ 💬 🔁 Pts</span>
                      </div>
                      {rankingSemanal.map((item, i) => (
                        <RankingRow key={`${item.plataforma}:${item.externalId}`} item={item} position={i} />
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* COMENTÁRIOS */}
          {tab === 'comentarios' && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="font-semibold text-gray-900">Comentários para Responder</h2>
                  <p className="text-xs text-gray-400 mt-0.5">Bond sugere uma resposta no seu estilo. Edite e aprove antes de copiar.</p>
                </div>
                {comentarios.length > 0 && (
                  <span className="text-xs bg-amber-100 text-amber-700 px-2 py-1 rounded-full font-medium">
                    {comentarios.length} pendente{comentarios.length !== 1 ? 's' : ''}
                  </span>
                )}
              </div>

              {comentarios.length === 0 ? (
                <div className="card text-center py-16">
                  <MessageSquare className="w-12 h-12 text-gray-200 mx-auto mb-3" />
                  <p className="text-gray-400 text-sm font-medium">Tudo em dia!</p>
                  <p className="text-gray-300 text-xs mt-1">Nenhum comentário pendente. Sincronize para buscar novos.</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {comentarios.map(com => (
                    <div key={com.id} className="card p-4 border-l-4 border-sky-300">
                      {/* Cabeçalho do comentário */}
                      <div className="flex items-start justify-between gap-2 mb-2">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${PLAT_COLOR[com.plataforma]}`}>{com.plataforma}</span>
                          {com.autor && <span className="text-xs font-semibold text-gray-700">{com.autor}</span>}
                          {com.isCabo && (
                            <span className="text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded-full font-medium flex items-center gap-0.5">
                              <Star className="w-2.5 h-2.5" />Cabo
                            </span>
                          )}
                          {com.categoria && ({
                            elogio: <span className="text-xs bg-green-100 text-green-700 px-1.5 py-0.5 rounded-full">😊 Elogio</span>,
                            critica: <span className="text-xs bg-red-100 text-red-700 px-1.5 py-0.5 rounded-full">⚠️ Crítica</span>,
                            pergunta: <span className="text-xs bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded-full">❓ Pergunta</span>,
                            sugestao: <span className="text-xs bg-purple-100 text-purple-700 px-1.5 py-0.5 rounded-full">💡 Sugestão</span>,
                            spam: <span className="text-xs bg-gray-100 text-gray-500 px-1.5 py-0.5 rounded-full">🚫 Spam</span>,
                            neutro: null,
                          }[com.categoria])}
                          <span className="text-xs text-gray-300">{formatDistanceToNow(new Date(com.criadoEm), { addSuffix: true, locale: ptBR })}</span>
                        </div>
                        <button onClick={() => handleRejeitar(com)} className="p-1 hover:bg-gray-100 rounded" title="Ignorar comentário">
                          <X className="w-3.5 h-3.5 text-gray-300 hover:text-gray-500" />
                        </button>
                      </div>

                      {/* Texto do comentário */}
                      <p className="text-sm text-gray-800 bg-gray-50 rounded-lg px-3 py-2 mb-3">&ldquo;{com.texto}&rdquo;</p>

                      {/* Área de resposta */}
                      {editandoId === com.comentarioId ? (
                        <div className="space-y-2">
                          <p className="text-xs font-medium text-gray-500">Resposta (edite se necessário):</p>
                          <textarea
                            value={textoEditado}
                            onChange={e => setTextoEditado(e.target.value)}
                            className="input text-sm resize-none"
                            rows={3}
                            placeholder="Edite a resposta do Bond..."
                          />
                          <div className="flex gap-2">
                            <button
                              onClick={() => handleAprovar(com)}
                              className="flex-1 flex items-center justify-center gap-1.5 btn-primary text-xs py-1.5"
                            >
                              <Check className="w-3.5 h-3.5" />Aprovar e Copiar
                            </button>
                            <button
                              onClick={() => { setEditandoId(null); setTextoEditado('') }}
                              className="px-3 py-1.5 text-xs bg-gray-100 text-gray-600 rounded-lg hover:bg-gray-200"
                            >
                              Cancelar
                            </button>
                          </div>
                        </div>
                      ) : com.sugestaoIA ? (
                        <div className="space-y-2">
                          <p className="text-xs font-medium text-gray-500 flex items-center gap-1"><Bot className="w-3 h-3 text-sky-500" />Sugestão do Bond:</p>
                          <p className="text-sm text-gray-700 bg-sky-50 rounded-lg px-3 py-2 border border-sky-100">{com.sugestaoIA}</p>
                          <div className="flex gap-2">
                            <button
                              onClick={() => { setEditandoId(com.comentarioId); setTextoEditado(com.sugestaoIA ?? '') }}
                              className="flex-1 flex items-center justify-center gap-1.5 btn-primary text-xs py-1.5"
                            >
                              <Check className="w-3.5 h-3.5" />Aprovar
                            </button>
                            <button
                              onClick={() => handleGerarResposta(com)}
                              disabled={gerandoId === com.comentarioId}
                              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-gray-100 text-gray-600 rounded-lg hover:bg-gray-200 disabled:opacity-50"
                            >
                              {gerandoId === com.comentarioId ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                              Nova sugestão
                            </button>
                          </div>
                        </div>
                      ) : (
                        <button
                          onClick={() => handleGerarResposta(com)}
                          disabled={gerandoId === com.comentarioId}
                          className="flex items-center gap-1.5 text-xs btn-secondary py-1.5 disabled:opacity-50"
                        >
                          {gerandoId === com.comentarioId ? (
                            <><Loader2 className="w-3.5 h-3.5 animate-spin" />Gerando resposta...</>
                          ) : (
                            <><Bot className="w-3.5 h-3.5 text-sky-500" />Bond sugerir resposta</>
                          )}
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Dica sobre aprendizado */}
              <div className="flex items-start gap-2 p-3 bg-gradient-to-r from-sky-50 to-pink-50 rounded-lg border border-sky-100">
                <Star className="w-4 h-4 text-sky-500 shrink-0 mt-0.5" />
                <div>
                  <p className="text-xs font-medium text-sky-800">Bond aprende com você</p>
                  <p className="text-xs text-sky-600 mt-0.5">Cada resposta aprovada ensina Bond sobre seu estilo. Quanto mais você aprovar, mais preciso ele fica.</p>
                </div>
              </div>
            </div>
          )}

          {/* INSIGHTS */}
          {tab === 'insights' && (
            <div className="space-y-3">
              {insights.length === 0 ? (
                <div className="card text-center py-12">
                  <Lightbulb className="w-10 h-10 text-gray-200 mx-auto mb-2" />
                  <p className="text-gray-400 text-sm">Nenhum insight ainda. Bond está aprendendo.</p>
                  <button onClick={() => fetch('/api/bond', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ acao: 'analisar' }) }).then(load)}
                    className="btn-primary mt-4 text-xs">Gerar Insights Agora</button>
                </div>
              ) : (
                insights.map(insight => (
                  <div key={insight.id} className={`card p-4 border-l-4 border-sky-400 ${insight.lido ? 'opacity-60' : ''}`}>
                    <div className="flex justify-between items-start gap-2 mb-2">
                      <p className="text-sm font-semibold text-gray-900">{insight.titulo}</p>
                      <div className="flex items-center gap-2 shrink-0">
                        {insight.plataforma && <span className={`text-xs px-2 py-0.5 rounded-full ${PLAT_COLOR[insight.plataforma]}`}>{insight.plataforma}</span>}
                        {!insight.lido && <button onClick={() => handleMarcarLido(insight.id)} className="text-xs text-gray-400 hover:text-gray-600">Lido</button>}
                      </div>
                    </div>
                    <p className="text-xs text-gray-600 whitespace-pre-line line-clamp-5">{insight.descricao}</p>
                    <p className="text-xs text-gray-300 mt-2">{formatDistanceToNow(new Date(insight.criadoEm), { addSuffix: true, locale: ptBR })}</p>
                  </div>
                ))
              )}
            </div>
          )}

          {/* ESTÚDIO */}
          {tab === 'studio' && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Gerador de conteúdo */}
              <div className="space-y-4">
                <div className="card">
                  <h3 className="font-semibold text-gray-900 mb-4 flex items-center gap-2"><Pencil className="w-4 h-4 text-pink-500" />Gerar Conteúdo</h3>
                  <div className="space-y-3">
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Tema ou Assunto</label>
                      <input value={tema} onChange={e => setTema(e.target.value)} className="input" placeholder="Ex: inauguração de escola, votação de projeto..." />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Plataforma</label>
                      <select value={platGen} onChange={e => setPlatGen(e.target.value)} className="input">
                        <option value="instagram">Instagram</option>
                        <option value="twitter">X / Twitter</option>
                        <option value="facebook">Facebook</option>
                        <option value="todas">Todas</option>
                      </select>
                    </div>
                    <button onClick={handleSugerir} disabled={gerando} className="btn-primary w-full flex items-center justify-center gap-2 disabled:opacity-50">
                      {gerando ? <Loader2 className="w-4 h-4 animate-spin" /> : <Bot className="w-4 h-4" />}
                      Gerar com Bond
                    </button>
                  </div>

                  {sugestao && (
                    <div className="mt-4 bg-gradient-to-br from-sky-50 to-pink-50 rounded-lg p-4 border border-sky-100">
                      <div className="flex justify-between items-center mb-2">
                        <p className="text-xs font-semibold text-sky-800">Conteúdo Gerado</p>
                        <div className="flex gap-2">
                          <button onClick={handleCopy} className="flex items-center gap-1 text-xs text-sky-600">
                            {copied ? <><CheckCheck className="w-3 h-3" />Copiado!</> : <><Copy className="w-3 h-3" />Copiar</>}
                          </button>
                          <button onClick={handleSalvarRascunho} className="flex items-center gap-1 text-xs text-green-600">
                            <Save className="w-3 h-3" />Salvar
                          </button>
                        </div>
                      </div>
                      <p className="text-xs text-gray-700 whitespace-pre-wrap">{sugestao}</p>
                    </div>
                  )}
                </div>

                {/* Rascunhos */}
                {rascunhos.length > 0 && (
                  <div className="card">
                    <h3 className="font-semibold text-gray-900 mb-3 text-sm">Rascunhos Salvos</h3>
                    <div className="space-y-2">
                      {rascunhos.map(r => (
                        <div key={r.id} className="flex items-start gap-2 p-2 bg-gray-50 rounded-lg">
                          <div className="flex-1 min-w-0">
                            {r.titulo && <p className="text-xs font-medium text-gray-700">{r.titulo}</p>}
                            <p className="text-xs text-gray-500 truncate">{r.texto.slice(0, 80)}</p>
                          </div>
                          <button onClick={() => handleDeletarRascunho(r.id)} className="p-1 hover:bg-red-50 rounded"><Trash2 className="w-3.5 h-3.5 text-red-400" /></button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {/* Chat com Bond */}
              <div className="card flex flex-col" style={{ height: '520px' }}>
                <div className="flex-1 overflow-y-auto space-y-3 pb-3">
                  {chatMsgs.length === 0 && (
                    <div className="text-center py-10">
                      <div className="w-12 h-12 bg-gradient-to-br from-sky-500 to-pink-500 rounded-full flex items-center justify-center mx-auto mb-3">
                        <Link2 className="w-5 h-5 text-white" />
                      </div>
                      <p className="text-gray-400 text-sm">Olá! Sou o Bond, seu especialista em redes sociais.</p>
                      <div className="mt-3 flex flex-wrap gap-2 justify-center">
                        {['Qual meu post mais viral?', 'Quando devo postar?', 'Quem são meus fãs?'].map(s => (
                          <button key={s} onClick={() => setChatInput(s)} className="text-xs bg-sky-50 text-sky-600 px-2 py-1 rounded-full hover:bg-sky-100 flex items-center gap-1">
                            <ChevronRight className="w-3 h-3" />{s}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                  {chatMsgs.map((msg, i) => (
                    <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                      {msg.role === 'assistant' && (
                        <div className="w-6 h-6 bg-gradient-to-br from-sky-500 to-pink-500 rounded-full flex items-center justify-center mr-1.5 shrink-0 mt-1">
                          <Link2 className="w-3 h-3 text-white" />
                        </div>
                      )}
                      <div className={`max-w-[80%] rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap ${msg.role === 'user' ? 'bg-sky-600 text-white rounded-tr-sm' : 'bg-gray-100 text-gray-800 rounded-tl-sm'}`}>
                        {msg.content}
                      </div>
                    </div>
                  ))}
                  {chatLoading && (
                    <div className="flex items-center gap-1.5">
                      <div className="w-6 h-6 bg-gradient-to-br from-sky-500 to-pink-500 rounded-full flex items-center justify-center shrink-0">
                        <Link2 className="w-3 h-3 text-white" />
                      </div>
                      <div className="bg-gray-100 rounded-2xl rounded-tl-sm px-3 py-2">
                        <Loader2 className="w-4 h-4 animate-spin text-gray-400" />
                      </div>
                    </div>
                  )}
                  <div ref={chatEndRef} />
                </div>
                <form onSubmit={handleChat} className="flex gap-2 pt-3 border-t border-gray-100">
                  <input value={chatInput} onChange={e => setChatInput(e.target.value)} className="input flex-1 text-sm" placeholder="Pergunte ao Bond sobre suas redes..." disabled={chatLoading} />
                  <button type="submit" disabled={chatLoading || !chatInput.trim()} className="btn-primary px-3 disabled:opacity-50"><Send className="w-4 h-4" /></button>
                </form>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
