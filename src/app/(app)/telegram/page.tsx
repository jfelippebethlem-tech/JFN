'use client'

import { useEffect, useState } from 'react'
import { Send, Loader2, Bot, CheckCircle, Clock, RefreshCw } from 'lucide-react'
import { formatDistanceToNow } from 'date-fns'
import { ptBR } from 'date-fns/locale'

type Mensagem = {
  id: string
  chatId: string
  userId: string | null
  username: string | null
  nome: string | null
  mensagem: string
  respondida: boolean
  resposta: string | null
  criadoEm: string
}

export default function TelegramPage() {
  const [mensagens, setMensagens] = useState<Mensagem[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<'all' | 'pendentes' | 'respondidas'>('all')
  const [selected, setSelected] = useState<Mensagem | null>(null)
  const [resposta, setResposta] = useState('')
  const [aiLoading, setAiLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  async function load() {
    setLoading(true)
    const params = new URLSearchParams()
    if (filter === 'pendentes') params.set('respondida', 'false')
    if (filter === 'respondidas') params.set('respondida', 'true')
    const res = await fetch(`/api/telegram?${params}`)
    const data = await res.json()
    setMensagens(data)
    setLoading(false)
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter])

  async function gerarResposta() {
    if (!selected) return
    setAiLoading(true)
    const res = await fetch('/api/ia', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acao: 'resposta', demanda: selected.mensagem }),
    })
    const data = await res.json()
    if (data.texto) setResposta(data.texto)
    setAiLoading(false)
  }

  async function handleResponder() {
    if (!selected || !resposta.trim()) return
    setSaving(true)
    await fetch(`/api/telegram/${selected.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ respondida: true, resposta }),
    })
    setSaving(false)
    setSelected(null)
    setResposta('')
    load()
  }

  const pendentes = mensagens.filter((m) => !m.respondida).length

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Telegram</h1>
          <p className="text-gray-500 text-sm mt-1">
            Mensagens recebidas pelo bot do Telegram
            {pendentes > 0 && (
              <span className="ml-2 bg-red-100 text-red-700 text-xs font-medium px-2 py-0.5 rounded-full">
                {pendentes} pendente{pendentes > 1 ? 's' : ''}
              </span>
            )}
          </p>
        </div>
        <button onClick={load} className="btn-secondary flex items-center gap-2">
          <RefreshCw className="w-4 h-4" /> Atualizar
        </button>
      </div>

      <div className="card mb-6 p-4 bg-blue-50 border-blue-100">
        <h3 className="font-medium text-blue-900 mb-2">Como configurar o bot do Telegram</h3>
        <ol className="text-sm text-blue-700 space-y-1 list-decimal list-inside">
          <li>Crie um bot com o @BotFather no Telegram e copie o token</li>
          <li>
            Adicione <code className="bg-blue-100 px-1 rounded">TELEGRAM_BOT_TOKEN=seu_token</code>{' '}
            no arquivo <code className="bg-blue-100 px-1 rounded">.env</code>
          </li>
          <li>
            Inicie o worker do bot com:{' '}
            <code className="bg-blue-100 px-1 rounded">npx tsx src/bot/telegram.ts</code>
          </li>
        </ol>
      </div>

      <div className="flex gap-2 mb-6">
        {(['all', 'pendentes', 'respondidas'] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
              filter === f
                ? 'bg-blue-600 text-white'
                : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'
            }`}
          >
            {f === 'all' ? 'Todas' : f === 'pendentes' ? 'Pendentes' : 'Respondidas'}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
        </div>
      ) : mensagens.length === 0 ? (
        <div className="card text-center py-12">
          <Send className="w-10 h-10 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-500">Nenhuma mensagem ainda</p>
          <p className="text-gray-400 text-sm mt-1">Configure o bot do Telegram para receber mensagens</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="space-y-3">
            {mensagens.map((msg) => (
              <div
                key={msg.id}
                onClick={() => {
                  setSelected(msg)
                  setResposta(msg.resposta ?? '')
                }}
                className={`card p-4 cursor-pointer transition-all hover:shadow-md ${
                  selected?.id === msg.id ? 'ring-2 ring-blue-500' : ''
                }`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm font-medium text-gray-900">
                        {msg.nome ?? msg.username ?? `Chat ${msg.chatId}`}
                      </span>
                      {msg.username && (
                        <span className="text-xs text-gray-400">@{msg.username}</span>
                      )}
                    </div>
                    <p className="text-sm text-gray-600 line-clamp-2">{msg.mensagem}</p>
                    <p className="text-xs text-gray-400 mt-1">
                      {formatDistanceToNow(new Date(msg.criadoEm), {
                        addSuffix: true,
                        locale: ptBR,
                      })}
                    </p>
                  </div>
                  <div className="shrink-0">
                    {msg.respondida ? (
                      <CheckCircle className="w-5 h-5 text-green-500" />
                    ) : (
                      <Clock className="w-5 h-5 text-yellow-500" />
                    )}
                  </div>
                </div>
                {msg.resposta && (
                  <div className="mt-2 p-2 bg-green-50 rounded-lg border border-green-100">
                    <p className="text-xs text-green-600 line-clamp-2">{msg.resposta}</p>
                  </div>
                )}
              </div>
            ))}
          </div>

          {selected && (
            <div className="card h-fit sticky top-4">
              <h3 className="font-semibold text-gray-900 mb-3">Responder Mensagem</h3>
              <div className="bg-gray-50 rounded-lg p-3 mb-4">
                <p className="text-xs font-medium text-gray-500 mb-1">
                  {selected.nome ?? selected.username ?? selected.chatId}
                </p>
                <p className="text-sm text-gray-700">{selected.mensagem}</p>
              </div>
              <div className="mb-3">
                <div className="flex items-center justify-between mb-1">
                  <label className="text-sm font-medium text-gray-700">Resposta</label>
                  <button
                    onClick={gerarResposta}
                    disabled={aiLoading}
                    className="flex items-center gap-1.5 text-xs text-blue-600 hover:text-blue-700 disabled:opacity-40"
                  >
                    {aiLoading ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : (
                      <Bot className="w-3 h-3" />
                    )}
                    Gerar com IA
                  </button>
                </div>
                <textarea
                  value={resposta}
                  onChange={(e) => setResposta(e.target.value)}
                  className="input"
                  rows={5}
                  placeholder="Digite a resposta..."
                />
              </div>
              <div className="flex gap-3">
                <button
                  onClick={() => {
                    setSelected(null)
                    setResposta('')
                  }}
                  className="btn-secondary flex-1"
                >
                  Cancelar
                </button>
                <button
                  onClick={handleResponder}
                  disabled={saving || !resposta.trim()}
                  className="btn-primary flex-1 flex items-center justify-center gap-2 disabled:opacity-40"
                >
                  {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                  Marcar Respondida
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
