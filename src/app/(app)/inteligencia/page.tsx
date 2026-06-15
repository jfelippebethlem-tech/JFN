'use client'

import { useState, useEffect, useCallback } from 'react'
import { Brain, Zap, Clock, Target, Swords, Star, TrendingUp, Loader2, Plus, RefreshCw, Send } from 'lucide-react'

type Tab = 'metricas' | 'heatmap' | 'cobranca' | 'adversarios' | 'nps'

type Metrica = {
  pessoaId: string; nome: string; tipo: string; seguidores: number
  score: number; influencerScore: number; alcanceEstimado: number
  consistenciaPct: number; velocidadeMin: number | null; streak: number
  postsEngajados: number; totalPostsPeriodo: number
}
type HeatMap = { porHora: { hora: number; total: number }[]; porDia: { dia: number; nome: string; total: number }[]; matriz: number[][]; melhorHora: number; melhorDia: { nome: string }; totalInteracoes: number }
type Alvo = { pessoaId: string; nome: string; telefone: string | null; consistenciaPct: number; influencerScore: number; postsRecentesSemEngajar: number; prioridade: number }
type Sov = { proprios: Perfil[]; adversarios: Perfil[]; meuEngajamento: number; engajamentoAdversarios: number; shareOfVoicePct: number }
type Perfil = { perfilId: string; plataforma: string; handle: string; nome: string; seguidores: number; posts: number; engajamentoTotal: number; engajamentoMedio: number }
type Nps = { pnps: number; total: number; promotores: number; passivos: number; detratores: number; semResposta: number }

const TABS: { id: Tab; label: string; icon: typeof Brain }[] = [
  { id: 'metricas', label: 'Métricas', icon: Zap },
  { id: 'heatmap', label: 'Horários', icon: Clock },
  { id: 'cobranca', label: 'Quem Cobrar', icon: Target },
  { id: 'adversarios', label: 'Adversários', icon: Swords },
  { id: 'nps', label: 'NPS', icon: Star },
]

export default function InteligenciaPage() {
  const [tab, setTab] = useState<Tab>('metricas')

  return (
    <div className="p-8 max-w-5xl">
      <div className="flex items-center gap-2 mb-1">
        <div className="w-8 h-8 bg-gradient-to-br from-purple-600 to-indigo-600 rounded-lg flex items-center justify-center">
          <Brain className="w-4 h-4 text-white" />
        </div>
        <h1 className="text-2xl font-bold text-gray-900">Inteligência</h1>
      </div>
      <p className="text-gray-500 text-sm mb-6 ml-10">
        Métricas avançadas de apoiadores, horários de pico, cobrança inteligente, adversários e NPS.
      </p>

      <div className="flex gap-1 mb-6 border-b border-gray-200">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === id ? 'border-purple-600 text-purple-700' : 'border-transparent text-gray-500 hover:text-gray-800'
            }`}
          >
            <Icon className="w-4 h-4" />{label}
          </button>
        ))}
      </div>

      {tab === 'metricas' && <MetricasTab />}
      {tab === 'heatmap' && <HeatmapTab />}
      {tab === 'cobranca' && <CobrancaTab />}
      {tab === 'adversarios' && <AdversariosTab />}
      {tab === 'nps' && <NpsTab />}
    </div>
  )
}

function MetricasTab() {
  const [dados, setDados] = useState<Metrica[]>([])
  const [loading, setLoading] = useState(true)
  useEffect(() => { fetch('/api/apoiadores/metricas?tipo=metricas').then(r => r.json()).then(d => { setDados(d); setLoading(false) }) }, [])
  if (loading) return <Spinner />
  return (
    <div className="card overflow-x-auto">
      <p className="text-xs text-gray-500 mb-3">
        <strong>Influencer Score</strong> = alcance potencial (seguidores × engajamento) · <strong>Consistência</strong> = % dos posts em que engajou · <strong>Velocidade</strong> = min médios até engajar
      </p>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-xs text-gray-400 uppercase border-b border-gray-100">
            <th className="text-left py-2">Apoiador</th>
            <th className="text-right px-2">Score</th>
            <th className="text-right px-2" title="Alcance potencial via seguidores">Influência</th>
            <th className="text-right px-2">Seguidores</th>
            <th className="text-right px-2">Consist.</th>
            <th className="text-right px-2">Veloc.</th>
            <th className="text-right px-2">🔥 Streak</th>
          </tr>
        </thead>
        <tbody>
          {dados.map(m => (
            <tr key={m.pessoaId} className="border-b border-gray-50 hover:bg-gray-50">
              <td className="py-2 font-medium text-gray-800">{m.nome}
                <span className="ml-1 text-xs text-gray-400">{m.tipo === 'coordenador' ? 'Coord.' : ''}</span>
              </td>
              <td className="text-right px-2 font-bold">{m.score}</td>
              <td className="text-right px-2 text-indigo-600 font-medium">{m.influencerScore}</td>
              <td className="text-right px-2 text-gray-500">{m.seguidores.toLocaleString('pt-BR')}</td>
              <td className="text-right px-2">
                <span className={`px-1.5 py-0.5 rounded-full text-xs ${m.consistenciaPct >= 70 ? 'bg-green-100 text-green-700' : m.consistenciaPct >= 30 ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-500'}`}>
                  {m.consistenciaPct}%
                </span>
              </td>
              <td className="text-right px-2 text-gray-500">{m.velocidadeMin != null ? `${m.velocidadeMin}min` : '—'}</td>
              <td className="text-right px-2">{m.streak > 0 ? `🔥${m.streak}` : '—'}</td>
            </tr>
          ))}
          {dados.length === 0 && <tr><td colSpan={7} className="text-center py-8 text-gray-400">Sem dados de apoiadores ainda</td></tr>}
        </tbody>
      </table>
    </div>
  )
}

function HeatmapTab() {
  const [h, setH] = useState<HeatMap | null>(null)
  useEffect(() => { fetch('/api/apoiadores/metricas?tipo=heatmap').then(r => r.json()).then(setH) }, [])
  if (!h) return <Spinner />
  const maxHora = Math.max(...h.porHora.map(x => x.total), 1)
  const maxMatriz = Math.max(...h.matriz.flat(), 1)
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4">
        <div className="card text-center">
          <p className="text-xs text-gray-500">Melhor horário</p>
          <p className="text-3xl font-bold text-purple-600 mt-1">{h.melhorHora}h</p>
        </div>
        <div className="card text-center">
          <p className="text-xs text-gray-500">Melhor dia</p>
          <p className="text-3xl font-bold text-indigo-600 mt-1">{h.melhorDia.nome}</p>
        </div>
      </div>

      <div className="card">
        <h3 className="font-semibold text-gray-900 mb-3 text-sm">Engajamento por hora do dia</h3>
        <div className="flex items-end gap-0.5 h-32">
          {h.porHora.map(x => (
            <div key={x.hora} className="flex-1 flex flex-col items-center justify-end group">
              <div className="w-full bg-purple-400 hover:bg-purple-600 rounded-t transition-colors" style={{ height: `${(x.total / maxHora) * 100}%` }} title={`${x.hora}h: ${x.total}`} />
              {x.hora % 3 === 0 && <span className="text-[9px] text-gray-400 mt-0.5">{x.hora}</span>}
            </div>
          ))}
        </div>
      </div>

      <div className="card overflow-x-auto">
        <h3 className="font-semibold text-gray-900 mb-3 text-sm">Mapa de calor (dia × hora)</h3>
        <table className="text-[9px]">
          <tbody>
            {h.matriz.map((linha, dia) => (
              <tr key={dia}>
                <td className="pr-2 text-gray-500 font-medium whitespace-nowrap">{h.porDia[dia].nome.slice(0, 3)}</td>
                {linha.map((v, hora) => (
                  <td key={hora}>
                    <div className="w-3.5 h-3.5 rounded-sm m-px" title={`${h.porDia[dia].nome} ${hora}h: ${v}`}
                      style={{ backgroundColor: v === 0 ? '#f1f5f9' : `rgba(124,58,237,${0.15 + (v / maxMatriz) * 0.85})` }} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        <p className="text-xs text-gray-400 mt-2">Total de interações analisadas: {h.totalInteracoes}</p>
      </div>
    </div>
  )
}

function CobrancaTab() {
  const [alvos, setAlvos] = useState<Alvo[]>([])
  const [loading, setLoading] = useState(true)
  const [enviando, setEnviando] = useState<string | null>(null)
  const carregar = useCallback(() => { setLoading(true); fetch('/api/apoiadores/metricas?tipo=cobrar').then(r => r.json()).then(d => { setAlvos(d); setLoading(false) }) }, [])
  useEffect(() => { carregar() }, [carregar])

  async function cobrar(pessoaId: string) {
    setEnviando(pessoaId)
    await fetch('/api/acoes', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ nome: 'cobrar_apoiador', params: { pessoaId }, origem: 'humano' }) })
    setEnviando(null)
    alert('Cobrança enfileirada no WhatsApp ✓')
  }

  if (loading) return <Spinner />
  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm text-gray-600">Apoiadores valiosos que <strong>não engajaram</strong> nos últimos 3 posts, por prioridade.</p>
        <button onClick={carregar} className="text-gray-400 hover:text-gray-700"><RefreshCw className="w-4 h-4" /></button>
      </div>
      {alvos.length === 0 ? (
        <p className="text-center py-8 text-green-600 text-sm">🎉 Todos os apoiadores engajaram nos posts recentes!</p>
      ) : (
        <div className="space-y-1">
          {alvos.map((a, i) => (
            <div key={a.pessoaId} className="flex items-center gap-3 py-2 px-2 hover:bg-gray-50 rounded-lg">
              <span className="text-xs text-gray-300 font-medium w-5">{i + 1}</span>
              <div className="flex-1">
                <p className="text-sm font-medium text-gray-800">{a.nome}</p>
                <p className="text-xs text-gray-400">
                  Faltou em {a.postsRecentesSemEngajar} post(s) · consistência {a.consistenciaPct}% · influência {a.influencerScore}
                  {a.telefone && ` · ${a.telefone}`}
                </p>
              </div>
              <span className="text-xs bg-orange-100 text-orange-700 px-2 py-0.5 rounded-full">prio {a.prioridade}</span>
              {a.telefone && (
                <button onClick={() => cobrar(a.pessoaId)} disabled={enviando === a.pessoaId}
                  className="btn-secondary flex items-center gap-1 text-xs disabled:opacity-50">
                  {enviando === a.pessoaId ? <Loader2 className="w-3 h-3 animate-spin" /> : <Send className="w-3 h-3" />}
                  Cobrar
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function AdversariosTab() {
  const [sov, setSov] = useState<Sov | null>(null)
  const [loading, setLoading] = useState(true)
  const [form, setForm] = useState({ plataforma: 'instagram', handle: '', nome: '' })
  const [busy, setBusy] = useState(false)

  const carregar = useCallback(() => { setLoading(true); fetch('/api/adversarios?tipo=sov').then(r => r.json()).then(d => { setSov(d); setLoading(false) }) }, [])
  useEffect(() => { carregar() }, [carregar])

  async function adicionar() {
    if (!form.handle.trim()) return
    setBusy(true)
    await fetch('/api/adversarios', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ acao: 'adicionar', ...form }) })
    setForm({ plataforma: 'instagram', handle: '', nome: '' })
    setBusy(false)
    carregar()
  }
  async function sincronizar() {
    setBusy(true)
    await fetch('/api/adversarios', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ acao: 'sincronizar' }) })
    setBusy(false)
    carregar()
  }

  if (loading) return <Spinner />
  return (
    <div className="space-y-6">
      <div className="card">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold text-gray-900 text-sm flex items-center gap-2"><TrendingUp className="w-4 h-4 text-indigo-500" /> Share of Voice (30 dias)</h3>
          <button onClick={sincronizar} disabled={busy} className="btn-secondary flex items-center gap-1 text-xs disabled:opacity-50">
            {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />} Sincronizar
          </button>
        </div>
        <div className="flex items-center gap-4 mb-2">
          <div className="flex-1">
            <div className="h-6 bg-gray-100 rounded-full overflow-hidden flex">
              <div className="bg-green-500 h-full flex items-center justify-center text-xs text-white font-medium" style={{ width: `${sov?.shareOfVoicePct ?? 0}%` }}>
                {sov && sov.shareOfVoicePct >= 15 ? `Você ${sov.shareOfVoicePct}%` : ''}
              </div>
              <div className="bg-red-400 h-full flex items-center justify-center text-xs text-white font-medium" style={{ width: `${100 - (sov?.shareOfVoicePct ?? 0)}%` }}>
                {sov && (100 - sov.shareOfVoicePct) >= 15 ? `Adversários ${100 - sov.shareOfVoicePct}%` : ''}
              </div>
            </div>
          </div>
        </div>
        <p className="text-xs text-gray-500">Seu engajamento: {sov?.meuEngajamento.toLocaleString('pt-BR')} · Adversários: {sov?.engajamentoAdversarios.toLocaleString('pt-BR')}</p>
      </div>

      <div className="card">
        <h3 className="font-semibold text-gray-900 text-sm mb-3">Adversários monitorados</h3>
        {sov?.adversarios.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-4">Nenhum adversário cadastrado ainda</p>
        ) : (
          <div className="space-y-1 mb-4">
            {sov?.adversarios.map(a => (
              <div key={a.perfilId} className="flex items-center gap-3 py-2 px-2 hover:bg-gray-50 rounded-lg text-sm">
                <span className="text-xs text-gray-400 w-16">{a.plataforma}</span>
                <span className="font-medium text-gray-800 flex-1">@{a.handle}</span>
                <span className="text-xs text-gray-500">{a.seguidores.toLocaleString('pt-BR')} seg.</span>
                <span className="text-xs text-gray-500">{a.posts} posts</span>
                <span className="text-xs font-medium text-red-600">{a.engajamentoTotal.toLocaleString('pt-BR')} eng.</span>
              </div>
            ))}
          </div>
        )}
        <div className="flex gap-2 border-t border-gray-100 pt-3">
          <select value={form.plataforma} onChange={e => setForm(f => ({ ...f, plataforma: e.target.value }))} className="input text-sm">
            <option value="instagram">Instagram</option>
            <option value="twitter">Twitter</option>
          </select>
          <input value={form.handle} onChange={e => setForm(f => ({ ...f, handle: e.target.value }))} className="input flex-1 text-sm" placeholder="@usuario do adversário" />
          <button onClick={adicionar} disabled={busy || !form.handle.trim()} className="btn-primary flex items-center gap-1 text-sm disabled:opacity-50">
            <Plus className="w-4 h-4" /> Monitorar
          </button>
        </div>
      </div>
    </div>
  )
}

function NpsTab() {
  const [nps, setNps] = useState<Nps | null>(null)
  useEffect(() => { fetch('/api/adversarios?tipo=nps').then(r => r.json()).then(setNps) }, [])
  if (!nps) return <Spinner />
  const cor = nps.pnps >= 50 ? 'text-green-600' : nps.pnps >= 0 ? 'text-amber-600' : 'text-red-600'
  return (
    <div className="space-y-6">
      <div className="card text-center">
        <p className="text-xs text-gray-500">pNPS — Net Promoter Score Político</p>
        <p className={`text-5xl font-bold mt-2 ${cor}`}>{nps.pnps > 0 ? '+' : ''}{nps.pnps}</p>
        <p className="text-xs text-gray-400 mt-1">{nps.total} respostas · {nps.semResposta} sem responder</p>
        <p className="text-xs text-gray-400 mt-2">Meta de campanha bem-sucedida: <strong>acima de +50</strong></p>
      </div>
      <div className="grid grid-cols-3 gap-4">
        <div className="card text-center bg-green-50">
          <p className="text-2xl font-bold text-green-600">{nps.promotores}</p>
          <p className="text-xs text-green-700">Promotores (9-10)</p>
        </div>
        <div className="card text-center bg-amber-50">
          <p className="text-2xl font-bold text-amber-600">{nps.passivos}</p>
          <p className="text-xs text-amber-700">Passivos (7-8)</p>
        </div>
        <div className="card text-center bg-red-50">
          <p className="text-2xl font-bold text-red-600">{nps.detratores}</p>
          <p className="text-xs text-red-700">Detratores (0-6)</p>
        </div>
      </div>
      <p className="text-xs text-gray-500 text-center">
        Dispare a pesquisa pelo menu <strong>WhatsApp → Disparar Pesquisa NPS</strong>. As respostas dos apoiadores (número de 0 a 10) são registradas automaticamente.
      </p>
    </div>
  )
}

function Spinner() {
  return <div className="flex justify-center py-16"><Loader2 className="w-6 h-6 animate-spin text-gray-400" /></div>
}
