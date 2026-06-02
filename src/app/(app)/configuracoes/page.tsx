'use client'

import { useEffect, useState } from 'react'
import { Settings, Loader2, CheckCircle, Key, User, Bot, Send } from 'lucide-react'

export default function ConfiguracoesPage() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [form, setForm] = useState({
    deputado_nome: '',
    deputado_partido: '',
    deputado_estado: '',
    deputado_mandato: '',
    gabinete_email: '',
    gabinete_telefone: '',
    gabinete_endereco: '',
  })

  useEffect(() => {
    async function load() {
      const res = await fetch('/api/configuracoes')
      const data = await res.json()
      setForm((prev) => ({ ...prev, ...data }))
      setLoading(false)
    }
    load()
  }, [])

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    await fetch('/api/configuracoes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    })
    setSaving(false)
    setSaved(true)
    setTimeout(() => setSaved(false), 3000)
  }

  if (loading) {
    return (
      <div className="p-8 flex justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
      </div>
    )
  }

  return (
    <div className="p-8 max-w-2xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Configurações</h1>
        <p className="text-gray-500 text-sm mt-1">Informações do gabinete e integrações</p>
      </div>

      <form onSubmit={handleSave} className="space-y-6">
        <div className="card">
          <div className="flex items-center gap-2 mb-4">
            <User className="w-5 h-5 text-blue-500" />
            <h2 className="font-semibold text-gray-900">Dados do Deputado</h2>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="col-span-2">
              <label className="block text-sm font-medium text-gray-700 mb-1">Nome</label>
              <input
                value={form.deputado_nome}
                onChange={(e) => setForm({ ...form, deputado_nome: e.target.value })}
                className="input"
                placeholder="Dep. Nome Completo"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Partido</label>
              <input
                value={form.deputado_partido}
                onChange={(e) => setForm({ ...form, deputado_partido: e.target.value })}
                className="input"
                placeholder="Ex: PT, PSDB, MDB..."
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Estado</label>
              <input
                value={form.deputado_estado}
                onChange={(e) => setForm({ ...form, deputado_estado: e.target.value })}
                className="input"
                placeholder="Ex: SP, RJ, MG..."
              />
            </div>
            <div className="col-span-2">
              <label className="block text-sm font-medium text-gray-700 mb-1">Mandato</label>
              <input
                value={form.deputado_mandato}
                onChange={(e) => setForm({ ...form, deputado_mandato: e.target.value })}
                className="input"
                placeholder="Ex: 2023-2027"
              />
            </div>
          </div>
        </div>

        <div className="card">
          <div className="flex items-center gap-2 mb-4">
            <Settings className="w-5 h-5 text-blue-500" />
            <h2 className="font-semibold text-gray-900">Contato do Gabinete</h2>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
              <input
                type="email"
                value={form.gabinete_email}
                onChange={(e) => setForm({ ...form, gabinete_email: e.target.value })}
                className="input"
                placeholder="gabinete@exemplo.com"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Telefone</label>
              <input
                value={form.gabinete_telefone}
                onChange={(e) => setForm({ ...form, gabinete_telefone: e.target.value })}
                className="input"
                placeholder="(11) 3333-3333"
              />
            </div>
            <div className="col-span-2">
              <label className="block text-sm font-medium text-gray-700 mb-1">Endereço</label>
              <input
                value={form.gabinete_endereco}
                onChange={(e) => setForm({ ...form, gabinete_endereco: e.target.value })}
                className="input"
                placeholder="Rua, Número - Cidade - Estado"
              />
            </div>
          </div>
        </div>

        <div className="card bg-gray-50 border-dashed">
          <div className="flex items-center gap-2 mb-3">
            <Key className="w-5 h-5 text-gray-400" />
            <h2 className="font-semibold text-gray-700">Integrações (via .env)</h2>
          </div>
          <p className="text-sm text-gray-500 mb-3">
            As chaves de API são configuradas no arquivo <code className="bg-gray-200 px-1 rounded">.env</code> por segurança.
          </p>
          <div className="space-y-2">
            <div className="flex items-center gap-3 p-3 bg-white rounded-lg border border-gray-200">
              <Bot className="w-5 h-5 text-green-500" />
              <div>
                <p className="text-sm font-medium text-gray-700">Gemini 2.0 Flash <span className="text-green-600 font-semibold">(Gratuito)</span></p>
                <p className="text-xs text-gray-400">
                  Variável: <code>GEMINI_API_KEY</code> — obtenha em aistudio.google.com
                </p>
              </div>
              <div className="ml-auto">
                <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-green-100 text-green-700">
                  Grátis
                </span>
              </div>
            </div>
            <div className="flex items-center gap-3 p-3 bg-white rounded-lg border border-gray-200">
              <Send className="w-5 h-5 text-blue-500" />
              <div>
                <p className="text-sm font-medium text-gray-700">Telegram Bot</p>
                <p className="text-xs text-gray-400">
                  Variável: <code>TELEGRAM_BOT_TOKEN</code>
                </p>
              </div>
              <div className="ml-auto">
                <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-yellow-100 text-yellow-700">
                  Ver .env
                </span>
              </div>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={saving}
            className="btn-primary flex items-center gap-2 disabled:opacity-50"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
            Salvar Configurações
          </button>
          {saved && (
            <div className="flex items-center gap-1.5 text-green-600 text-sm">
              <CheckCircle className="w-4 h-4" />
              Salvo com sucesso!
            </div>
          )}
        </div>
      </form>
    </div>
  )
}
