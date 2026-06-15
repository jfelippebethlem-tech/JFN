'use client'

import { useState, useEffect, useCallback } from 'react'
import { MessageSquare, Send, RefreshCw, CheckCircle, Clock, XCircle, Users, Megaphone, Star, Smartphone, Loader2 } from 'lucide-react'

type Status = { status: string; qr: string | null; atualizadoEm: string | null; fila: { pendente: number; enviado: number; erro: number } }
type FilaItem = { id: string; telefone: string; mensagem: string; tipo: string; status: string; criadoEm: string; enviadoEm: string | null; erro: string | null }

const STATUS_INFO: Record<string, { label: string; cor: string; bg: string }> = {
  conectado:    { label: 'Conectado', cor: 'text-green-700', bg: 'bg-green-100' },
  aguardando_qr:{ label: 'Aguardando leitura do QR', cor: 'text-amber-700', bg: 'bg-amber-100' },
  reconectando: { label: 'Reconectando...', cor: 'text-blue-700', bg: 'bg-blue-100' },
  iniciando:    { label: 'Iniciando...', cor: 'text-slate-700', bg: 'bg-slate-100' },
  desconectado: { label: 'Desconectado', cor: 'text-red-700', bg: 'bg-red-100' },
  desconhecido: { label: 'Worker não iniciado', cor: 'text-slate-500', bg: 'bg-slate-100' },
}

const TIPO_BADGE: Record<string, string> = {
  notificacao: 'bg-blue-100 text-blue-700', cobranca: 'bg-orange-100 text-orange-700',
  nps: 'bg-purple-100 text-purple-700', conquista: 'bg-green-100 text-green-700',
  broadcast: 'bg-indigo-100 text-indigo-700', alerta: 'bg-red-100 text-red-700',
}

export default function WhatsappPage() {
  const [status, setStatus] = useState<Status | null>(null)
  const [fila, setFila] = useState<FilaItem[]>([])
  const [mensagem, setMensagem] = useState('')
  const [enviando, setEnviando] = useState(false)
  const [feedback, setFeedback] = useState<string | null>(null)

  const carregar = useCallback(async () => {
    const [s, f] = await Promise.all([
      fetch('/api/whatsapp?tipo=status').then(r => r.json()),
      fetch('/api/whatsapp?tipo=fila').then(r => r.json()),
    ])
    setStatus(s)
    setFila(f.itens ?? [])
  }, [])

  useEffect(() => {
    carregar()
    const t = setInterval(carregar, 8000) // atualiza p/ ver QR e fila
    return () => clearInterval(t)
  }, [carregar])

  async function enviarBroadcast() {
    if (!mensagem.trim()) return
    setEnviando(true)
    setFeedback(null)
    const res = await fetch('/api/whatsapp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ acao: 'broadcast', mensagem }),
    })
    const data = await res.json()
    setFeedback(`✓ ${data.enfileirados ?? 0} de ${data.totalApoiadores ?? 0} apoiadores na fila de envio`)
    setMensagem('')
    setEnviando(false)
    carregar()
  }

  async function dispararNps() {
    if (!confirm('Enviar a pesquisa de NPS para todos os apoiadores com telefone?')) return
    const res = await fetch('/api/acoes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nome: 'disparar_pesquisa_nps', params: {}, origem: 'humano' }),
    })
    const data = await res.json()
    setFeedback(data.ok ? `✓ Pesquisa NPS enfileirada para ${data.resultado?.enfileirados ?? 0} apoiadores` : `Erro: ${data.erro}`)
    carregar()
  }

  const si = STATUS_INFO[status?.status ?? 'desconhecido'] ?? STATUS_INFO.desconhecido

  return (
    <div className="p-8 max-w-4xl">
      <div className="flex items-center gap-2 mb-1">
        <div className="w-8 h-8 bg-green-500 rounded-lg flex items-center justify-center">
          <MessageSquare className="w-4 h-4 text-white" />
        </div>
        <h1 className="text-2xl font-bold text-gray-900">WhatsApp</h1>
        <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full font-medium">100% Grátis (Baileys)</span>
      </div>
      <p className="text-gray-500 text-sm mb-6 ml-10">
        Avise apoiadores de novos posts, cobre quem não engajou e dispare pesquisas — sem custo de API.
      </p>

      {/* Status + QR */}
      <div className="grid grid-cols-[1fr_auto] gap-4 mb-6">
        <div className="card">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-semibold text-gray-900 flex items-center gap-2">
              <Smartphone className="w-4 h-4 text-gray-500" /> Conexão
            </h3>
            <button onClick={carregar} className="text-gray-400 hover:text-gray-700"><RefreshCw className="w-4 h-4" /></button>
          </div>
          <span className={`inline-flex items-center gap-1.5 text-sm font-medium px-3 py-1 rounded-full ${si.bg} ${si.cor}`}>
            {status?.status === 'conectado' ? <CheckCircle className="w-4 h-4" /> : <Clock className="w-4 h-4" />}
            {si.label}
          </span>

          {status?.status !== 'conectado' && (
            <div className="mt-4 text-xs text-gray-600 bg-gray-50 rounded-lg p-3 space-y-1">
              <p className="font-medium text-gray-700">Como conectar (uma vez):</p>
              <p>1. Inicie o worker: <code className="bg-gray-200 px-1 rounded">npm run whatsapp</code></p>
              <p>2. No celular: WhatsApp → Aparelhos conectados → Conectar aparelho</p>
              <p>3. Escaneie o QR ao lado →</p>
            </div>
          )}

          <div className="grid grid-cols-3 gap-2 mt-4">
            <div className="text-center bg-amber-50 rounded-lg py-2">
              <p className="text-lg font-bold text-amber-600">{status?.fila.pendente ?? 0}</p>
              <p className="text-xs text-amber-700">Pendentes</p>
            </div>
            <div className="text-center bg-green-50 rounded-lg py-2">
              <p className="text-lg font-bold text-green-600">{status?.fila.enviado ?? 0}</p>
              <p className="text-xs text-green-700">Enviados</p>
            </div>
            <div className="text-center bg-red-50 rounded-lg py-2">
              <p className="text-lg font-bold text-red-600">{status?.fila.erro ?? 0}</p>
              <p className="text-xs text-red-700">Erros</p>
            </div>
          </div>
        </div>

        {/* QR Code */}
        <div className="card flex flex-col items-center justify-center w-56">
          {status?.qr ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={status.qr} alt="QR Code WhatsApp" className="w-44 h-44" />
          ) : status?.status === 'conectado' ? (
            <div className="text-center text-green-600">
              <CheckCircle className="w-16 h-16 mx-auto mb-2" />
              <p className="text-sm font-medium">Aparelho conectado</p>
            </div>
          ) : (
            <div className="text-center text-gray-400">
              <Loader2 className="w-10 h-10 mx-auto mb-2 animate-spin" />
              <p className="text-xs">Aguardando QR do worker...</p>
            </div>
          )}
        </div>
      </div>

      {/* Broadcast */}
      <div className="card mb-6">
        <h3 className="font-semibold text-gray-900 mb-3 flex items-center gap-2">
          <Megaphone className="w-4 h-4 text-indigo-500" /> Disparo em massa para apoiadores
        </h3>
        <textarea
          value={mensagem}
          onChange={e => setMensagem(e.target.value)}
          rows={3}
          className="input w-full resize-none"
          placeholder="Ex: Acabei de publicar! Curtam e compartilhem nas próximas 2h. 💪"
        />
        <div className="flex items-center justify-between mt-3">
          <button onClick={dispararNps} className="btn-secondary flex items-center gap-1.5 text-xs">
            <Star className="w-3.5 h-3.5" /> Disparar Pesquisa NPS
          </button>
          <button onClick={enviarBroadcast} disabled={enviando || !mensagem.trim()} className="btn-primary flex items-center gap-1.5 text-sm disabled:opacity-50">
            {enviando ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            Enviar para todos
          </button>
        </div>
        {feedback && <p className="text-sm text-green-600 mt-2">{feedback}</p>}
      </div>

      {/* Fila */}
      <div className="card">
        <h3 className="font-semibold text-gray-900 mb-3 flex items-center gap-2">
          <Users className="w-4 h-4 text-gray-500" /> Últimas mensagens na fila
        </h3>
        {fila.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-6">Nenhuma mensagem ainda</p>
        ) : (
          <div className="space-y-1 max-h-96 overflow-y-auto">
            {fila.map(item => (
              <div key={item.id} className="flex items-center gap-3 py-2 px-2 hover:bg-gray-50 rounded-lg text-sm">
                <span className="shrink-0">
                  {item.status === 'enviado' ? <CheckCircle className="w-4 h-4 text-green-500" /> :
                   item.status === 'erro' ? <XCircle className="w-4 h-4 text-red-500" /> :
                   <Clock className="w-4 h-4 text-amber-500" />}
                </span>
                <span className="text-gray-500 font-mono text-xs shrink-0">{item.telefone}</span>
                <span className={`text-xs px-1.5 py-0.5 rounded-full shrink-0 ${TIPO_BADGE[item.tipo] ?? 'bg-gray-100 text-gray-600'}`}>{item.tipo}</span>
                <span className="text-gray-600 truncate flex-1">{item.mensagem}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
