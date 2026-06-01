'use client'

import { useState } from 'react'
import { Bot, Loader2, Copy, CheckCheck, Sparkles, MessageSquare, Share2 } from 'lucide-react'

type Tab = 'resposta' | 'post' | 'sentimento'

export default function IAPage() {
  const [tab, setTab] = useState<Tab>('resposta')
  const [loading, setLoading] = useState(false)
  const [resultado, setResultado] = useState('')
  const [copied, setCopied] = useState(false)

  // Resposta form
  const [demanda, setDemanda] = useState('')
  const [contexto, setContexto] = useState('')

  // Post form
  const [tema, setTema] = useState('')
  const [plataforma, setPlataforma] = useState('instagram')
  const [tom, setTom] = useState('institucional')

  // Sentimento form
  const [texto, setTexto] = useState('')

  async function handleGerarResposta(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setResultado('')
    const res = await fetch('/api/ia', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acao: 'resposta', demanda, contexto }),
    })
    const data = await res.json()
    setResultado(data.texto || data.error || 'Erro ao processar')
    setLoading(false)
  }

  async function handleGerarPost(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setResultado('')
    const res = await fetch('/api/ia', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acao: 'post', tema, plataforma, tom }),
    })
    const data = await res.json()
    setResultado(data.texto || data.error || 'Erro ao processar')
    setLoading(false)
  }

  async function handleAnalisarSentimento(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setResultado('')
    const res = await fetch('/api/ia', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acao: 'sentimento', texto }),
    })
    const data = await res.json()
    setResultado(data.sentimento || data.error || 'Erro ao processar')
    setLoading(false)
  }

  async function handleCopy() {
    await navigator.clipboard.writeText(resultado)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const tabs = [
    { id: 'resposta' as Tab, label: 'Resposta a Demanda', icon: MessageSquare },
    { id: 'post' as Tab, label: 'Post para Redes', icon: Share2 },
    { id: 'sentimento' as Tab, label: 'Análise de Sentimento', icon: Sparkles },
  ]

  return (
    <div className="p-8 max-w-3xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Assistente IA</h1>
        <p className="text-gray-500 text-sm mt-1">
          Powered by Claude — gere respostas, posts e análises automaticamente
        </p>
      </div>

      {!process.env.NEXT_PUBLIC_APP_URL?.includes('localhost') ? null : (
        <div className="card mb-6 p-4 bg-amber-50 border-amber-100">
          <p className="text-sm text-amber-700">
            <strong>Configure sua chave da API:</strong> adicione{' '}
            <code className="bg-amber-100 px-1 rounded">ANTHROPIC_API_KEY=sua_chave</code> no arquivo{' '}
            <code className="bg-amber-100 px-1 rounded">.env</code> para ativar o assistente de IA.
          </p>
        </div>
      )}

      <div className="flex gap-2 mb-6 border-b border-gray-200">
        {tabs.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => {
              setTab(id)
              setResultado('')
            }}
            className={`flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
              tab === id
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            <Icon className="w-4 h-4" />
            {label}
          </button>
        ))}
      </div>

      {tab === 'resposta' && (
        <form onSubmit={handleGerarResposta} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Demanda do Cidadão *
            </label>
            <textarea
              required
              value={demanda}
              onChange={(e) => setDemanda(e.target.value)}
              className="input"
              rows={4}
              placeholder="Cole ou descreva a demanda do cidadão aqui..."
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Contexto Adicional (opcional)
            </label>
            <textarea
              value={contexto}
              onChange={(e) => setContexto(e.target.value)}
              className="input"
              rows={2}
              placeholder="Ex: área da saúde, município de SP, urgente..."
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className="btn-primary flex items-center gap-2 disabled:opacity-50"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Bot className="w-4 h-4" />}
            Gerar Resposta
          </button>
        </form>
      )}

      {tab === 'post' && (
        <form onSubmit={handleGerarPost} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Tema do Post *</label>
            <textarea
              required
              value={tema}
              onChange={(e) => setTema(e.target.value)}
              className="input"
              rows={3}
              placeholder="Ex: Aprovação do projeto de lei de saúde pública..."
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Plataforma</label>
              <select
                value={plataforma}
                onChange={(e) => setPlataforma(e.target.value)}
                className="input"
              >
                <option value="instagram">Instagram</option>
                <option value="twitter">Twitter/X</option>
                <option value="facebook">Facebook</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Tom</label>
              <select value={tom} onChange={(e) => setTom(e.target.value)} className="input">
                <option value="institucional">Institucional</option>
                <option value="informal">Informal</option>
                <option value="motivacional">Motivacional</option>
                <option value="informativo">Informativo</option>
              </select>
            </div>
          </div>
          <button
            type="submit"
            disabled={loading}
            className="btn-primary flex items-center gap-2 disabled:opacity-50"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Share2 className="w-4 h-4" />}
            Gerar Post
          </button>
        </form>
      )}

      {tab === 'sentimento' && (
        <form onSubmit={handleAnalisarSentimento} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Texto para Análise *
            </label>
            <textarea
              required
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              className="input"
              rows={5}
              placeholder="Cole o texto que deseja analisar o sentimento..."
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className="btn-primary flex items-center gap-2 disabled:opacity-50"
          >
            {loading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Sparkles className="w-4 h-4" />
            )}
            Analisar Sentimento
          </button>
        </form>
      )}

      {resultado && (
        <div className="mt-6 card bg-blue-50 border-blue-100">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold text-blue-900">Resultado</h3>
            <button
              onClick={handleCopy}
              className="flex items-center gap-1.5 text-xs text-blue-600 hover:text-blue-700"
            >
              {copied ? (
                <>
                  <CheckCheck className="w-3.5 h-3.5" />
                  Copiado!
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5" />
                  Copiar
                </>
              )}
            </button>
          </div>
          <p className="text-sm text-blue-800 whitespace-pre-wrap">{resultado}</p>
        </div>
      )}
    </div>
  )
}
