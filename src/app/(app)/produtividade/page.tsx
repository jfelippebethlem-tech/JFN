'use client'

import { useEffect, useState } from 'react'
import { BarChart3, Plus, Edit2, Trash2, Loader2, X, CheckSquare, FileSignature, Users2, Mic } from 'lucide-react'
import { format } from 'date-fns'
import { ptBR } from 'date-fns/locale'

type Atividade = {
  id: string
  tipo: string
  titulo: string
  descricao: string | null
  data: string
  resultado: string | null
  criadoEm: string
}

const tipoConfig: Record<string, { label: string; icon: React.ElementType; color: string }> = {
  voto: { label: 'Voto', icon: CheckSquare, color: 'bg-blue-100 text-blue-700' },
  projeto: { label: 'Projeto de Lei', icon: FileSignature, color: 'bg-purple-100 text-purple-700' },
  reuniao: { label: 'Reunião', icon: Users2, color: 'bg-green-100 text-green-700' },
  pronunciamento: { label: 'Pronunciamento', icon: Mic, color: 'bg-orange-100 text-orange-700' },
  outro: { label: 'Outro', icon: BarChart3, color: 'bg-gray-100 text-gray-700' },
}

const emptyForm = {
  tipo: 'voto',
  titulo: '',
  descricao: '',
  data: new Date().toISOString().slice(0, 16),
  resultado: '',
}

export default function ProdutividadePage() {
  const [atividades, setAtividades] = useState<Atividade[]>([])
  const [loading, setLoading] = useState(true)
  const [tipoFilter, setTipoFilter] = useState('')
  const [showModal, setShowModal] = useState(false)
  const [editing, setEditing] = useState<Atividade | null>(null)
  const [form, setForm] = useState(emptyForm)
  const [saving, setSaving] = useState(false)

  async function load() {
    setLoading(true)
    const params = new URLSearchParams()
    if (tipoFilter) params.set('tipo', tipoFilter)
    const res = await fetch(`/api/atividades?${params}`)
    const data = await res.json()
    setAtividades(data)
    setLoading(false)
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tipoFilter])

  function openCreate() {
    setEditing(null)
    setForm(emptyForm)
    setShowModal(true)
  }

  function openEdit(a: Atividade) {
    setEditing(a)
    setForm({
      tipo: a.tipo,
      titulo: a.titulo,
      descricao: a.descricao ?? '',
      data: new Date(a.data).toISOString().slice(0, 16),
      resultado: a.resultado ?? '',
    })
    setShowModal(true)
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    const method = editing ? 'PUT' : 'POST'
    const url = editing ? `/api/atividades/${editing.id}` : '/api/atividades'
    await fetch(url, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    })
    setSaving(false)
    setShowModal(false)
    load()
  }

  async function handleDelete(id: string) {
    if (!confirm('Deseja excluir esta atividade?')) return
    await fetch(`/api/atividades/${id}`, { method: 'DELETE' })
    load()
  }

  const counts = Object.fromEntries(
    Object.keys(tipoConfig).map((tipo) => [
      tipo,
      atividades.filter((a) => a.tipo === tipo).length,
    ])
  )

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Produtividade</h1>
          <p className="text-gray-500 text-sm mt-1">Votos, projetos, reuniões e pronunciamentos</p>
        </div>
        <button onClick={openCreate} className="btn-primary flex items-center gap-2">
          <Plus className="w-4 h-4" /> Nova Atividade
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
        {Object.entries(tipoConfig).map(([tipo, cfg]) => (
          <div key={tipo} className="card p-4 cursor-pointer hover:shadow-md transition-shadow" onClick={() => setTipoFilter(tipoFilter === tipo ? '' : tipo)}>
            <div className={`inline-flex p-2 rounded-lg mb-2 ${cfg.color}`}>
              <cfg.icon className="w-4 h-4" />
            </div>
            <div className="text-2xl font-bold text-gray-900">{counts[tipo] ?? 0}</div>
            <div className="text-xs text-gray-500 mt-0.5">{cfg.label}</div>
          </div>
        ))}
      </div>

      {tipoFilter && (
        <div className="flex items-center gap-2 mb-4">
          <span className="text-sm text-gray-600">
            Filtrando por: <strong>{tipoConfig[tipoFilter]?.label}</strong>
          </span>
          <button onClick={() => setTipoFilter('')} className="text-xs text-blue-600 hover:underline">
            Limpar
          </button>
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
        </div>
      ) : atividades.length === 0 ? (
        <div className="card text-center py-12">
          <BarChart3 className="w-10 h-10 text-gray-300 mx-auto mb-3" />
          <p className="text-gray-500">Nenhuma atividade registrada</p>
        </div>
      ) : (
        <div className="card p-0 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="text-left px-6 py-3 font-medium text-gray-500">Tipo</th>
                <th className="text-left px-6 py-3 font-medium text-gray-500">Título</th>
                <th className="text-left px-6 py-3 font-medium text-gray-500">Data</th>
                <th className="text-left px-6 py-3 font-medium text-gray-500">Resultado</th>
                <th className="px-6 py-3" />
              </tr>
            </thead>
            <tbody>
              {atividades.map((a) => {
                const cfg = tipoConfig[a.tipo] ?? tipoConfig.outro
                const Icon = cfg.icon
                return (
                  <tr key={a.id} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="px-6 py-4">
                      <span className={`inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full font-medium ${cfg.color}`}>
                        <Icon className="w-3 h-3" />
                        {cfg.label}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="font-medium text-gray-900">{a.titulo}</div>
                      {a.descricao && (
                        <div className="text-xs text-gray-400 mt-0.5 truncate max-w-xs">{a.descricao}</div>
                      )}
                    </td>
                    <td className="px-6 py-4 text-gray-600 whitespace-nowrap">
                      {format(new Date(a.data), 'dd/MM/yyyy HH:mm', { locale: ptBR })}
                    </td>
                    <td className="px-6 py-4 text-gray-600">{a.resultado ?? '—'}</td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2 justify-end">
                        <button onClick={() => openEdit(a)} className="p-1.5 text-gray-400 hover:text-blue-600 hover:bg-blue-50 rounded-lg transition-colors">
                          <Edit2 className="w-4 h-4" />
                        </button>
                        <button onClick={() => handleDelete(a.id)} className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors">
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {showModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl w-full max-w-lg shadow-2xl">
            <div className="flex items-center justify-between px-6 py-4 border-b">
              <h2 className="font-semibold text-gray-900">
                {editing ? 'Editar Atividade' : 'Nova Atividade'}
              </h2>
              <button onClick={() => setShowModal(false)} className="p-1.5 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg">
                <X className="w-5 h-5" />
              </button>
            </div>
            <form onSubmit={handleSave} className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Tipo *</label>
                <select value={form.tipo} onChange={(e) => setForm({ ...form, tipo: e.target.value })} className="input">
                  <option value="voto">Voto</option>
                  <option value="projeto">Projeto de Lei</option>
                  <option value="reuniao">Reunião</option>
                  <option value="pronunciamento">Pronunciamento</option>
                  <option value="outro">Outro</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Título *</label>
                <input required value={form.titulo} onChange={(e) => setForm({ ...form, titulo: e.target.value })} className="input" placeholder="Descreva a atividade..." />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Descrição</label>
                <textarea value={form.descricao} onChange={(e) => setForm({ ...form, descricao: e.target.value })} className="input" rows={2} placeholder="Detalhes adicionais..." />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Data *</label>
                <input required type="datetime-local" value={form.data} onChange={(e) => setForm({ ...form, data: e.target.value })} className="input" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Resultado</label>
                <input value={form.resultado} onChange={(e) => setForm({ ...form, resultado: e.target.value })} className="input" placeholder="Ex: Aprovado, Rejeitado..." />
              </div>
              <div className="flex gap-3 pt-2">
                <button type="button" onClick={() => setShowModal(false)} className="btn-secondary flex-1">Cancelar</button>
                <button type="submit" className="btn-primary flex-1 flex items-center justify-center gap-2">
                  {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                  {editing ? 'Salvar' : 'Criar'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
