'use client'

import { useState, useEffect, useRef } from 'react'
import {
  Users, Upload, Plus, Search, Twitter, Instagram, Facebook,
  Heart, MessageCircle, Share2, Trophy, Loader2, X, Check,
  FileSpreadsheet, AlertCircle, ChevronDown, Phone, Star,
} from 'lucide-react'

type BondFaInfo = { id: string; plataforma: string; totalLikes: number; totalComents: number; totalShares: number }
type Cabo = {
  id: string; nome: string; tipo: string; cargo?: string; telefone?: string
  instagram?: string; twitter?: string; facebook?: string; observacoes?: string
  score: number; plataformasVinculadas: string[]; bondFas: BondFaInfo[]
  criadoEm: string
}

const PLAT_ICON: Record<string, React.ReactNode> = {
  twitter: <Twitter className="w-3.5 h-3.5 text-sky-500" />,
  instagram: <Instagram className="w-3.5 h-3.5 text-pink-500" />,
  facebook: <Facebook className="w-3.5 h-3.5 text-blue-600" />,
}

const TIPO_LABEL: Record<string, string> = {
  apoiador: 'Apoiador',
  coordenador: 'Coordenador',
}

const TIPO_COLOR: Record<string, string> = {
  apoiador: 'bg-blue-100 text-blue-700',
  coordenador: 'bg-purple-100 text-purple-700',
}

const CSV_EXEMPLO = `Nome,Instagram,Twitter,Facebook,Telefone,Cargo,Observacoes
João da Silva,@joao.silva,@joaosilva,joao.silva,(21) 99999-9999,Liderança Zona Sul,Responsável pela Zona Sul
Maria Santos,@maria.santos,,,(22) 88888-8888,Coordenadora Maricá,
`

export default function CabosPage() {
  const [cabos, setCabos] = useState<Cabo[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [tipoFilter, setTipoFilter] = useState<string>('todos')
  const [showForm, setShowForm] = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState<{ criados: number; atualizados: number; erros: number; detalhes?: string[] } | null>(null)
  const [saving, setSaving] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  // Form state
  const [form, setForm] = useState({ nome: '', instagram: '', twitter: '', facebook: '', telefone: '', cargo: '', tipo: 'apoiador', observacoes: '', pessoaId: '' })

  async function loadCabos() {
    setLoading(true)
    const params = new URLSearchParams()
    if (tipoFilter !== 'todos') params.set('tipo', tipoFilter)
    if (search) params.set('q', search)
    const res = await fetch(`/api/apoiadores?${params}`)
    const data = await res.json()
    setCabos(Array.isArray(data) ? data : [])
    setLoading(false)
  }

  useEffect(() => { loadCabos() }, [tipoFilter, search])

  async function handleImport(file: File) {
    setImporting(true)
    setImportResult(null)
    const text = await file.text()
    const res = await fetch('/api/apoiadores', {
      method: 'POST',
      headers: { 'Content-Type': 'text/csv' },
      body: text,
    })
    const data = await res.json()
    setImportResult(data)
    setImporting(false)
    loadCabos()
  }

  async function handleSave() {
    if (!form.nome.trim()) return
    setSaving(true)
    await fetch('/api/apoiadores', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(form),
    })
    setSaving(false)
    setShowForm(false)
    setForm({ nome: '', instagram: '', twitter: '', facebook: '', telefone: '', cargo: '', tipo: 'apoiador', observacoes: '', pessoaId: '' })
    loadCabos()
  }

  async function handleDelete(id: string) {
    if (!confirm('Remover este cabo?')) return
    await fetch(`/api/apoiadores?id=${id}`, { method: 'DELETE' })
    setCabos(prev => prev.filter(c => c.id !== id))
  }

  function editarCabo(c: Cabo) {
    setForm({
      pessoaId: c.id,
      nome: c.nome,
      instagram: c.instagram ?? '',
      twitter: c.twitter ?? '',
      facebook: c.facebook ?? '',
      telefone: c.telefone ?? '',
      cargo: c.cargo ?? '',
      tipo: c.tipo,
      observacoes: c.observacoes ?? '',
    })
    setShowForm(true)
  }

  const filtrados = cabos.filter(c =>
    !search || c.nome.toLowerCase().includes(search.toLowerCase()) ||
    (c.instagram ?? '').toLowerCase().includes(search.toLowerCase()) ||
    (c.twitter ?? '').toLowerCase().includes(search.toLowerCase())
  )

  const totalScore = filtrados.reduce((s, c) => s + c.score, 0)
  const vinculados = filtrados.filter(c => c.plataformasVinculadas.length > 0).length

  return (
    <div className="p-8 max-w-5xl">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-gradient-to-br from-blue-600 to-purple-600 rounded-lg flex items-center justify-center">
              <Users className="w-4 h-4 text-white" />
            </div>
            <h1 className="text-2xl font-bold text-gray-900">Apoiadores</h1>
          </div>
          <p className="text-gray-500 text-sm mt-1 ml-10">
            Gerencie seus cabos e coordenadores — importe planilha e veja quem mais engaja nas redes
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => { setShowImport(!showImport); setShowForm(false) }}
            className="btn-secondary flex items-center gap-1.5 text-xs"
          >
            <Upload className="w-3.5 h-3.5" />
            Importar Planilha
          </button>
          <button
            onClick={() => { setShowForm(!showForm); setShowImport(false); setForm({ nome: '', instagram: '', twitter: '', facebook: '', telefone: '', cargo: '', tipo: 'apoiador', observacoes: '', pessoaId: '' }) }}
            className="btn-primary flex items-center gap-1.5 text-xs"
          >
            <Plus className="w-3.5 h-3.5" />
            Adicionar Cabo
          </button>
        </div>
      </div>

      {/* Cards resumo */}
      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="card">
          <p className="text-xs text-gray-500">Total de Cabos</p>
          <p className="text-2xl font-bold text-gray-900 mt-1">{filtrados.length}</p>
        </div>
        <div className="card">
          <p className="text-xs text-gray-500">Com Redes Vinculadas</p>
          <p className="text-2xl font-bold text-blue-600 mt-1">{vinculados}</p>
        </div>
        <div className="card">
          <p className="text-xs text-gray-500">Score Total (grupo)</p>
          <p className="text-2xl font-bold text-green-600 mt-1">{totalScore.toLocaleString('pt-BR')}</p>
        </div>
      </div>

      {/* Panel de Importação CSV */}
      {showImport && (
        <div className="card mb-6 border-2 border-dashed border-blue-200 bg-blue-50">
          <h3 className="font-semibold text-gray-900 mb-3 flex items-center gap-2">
            <FileSpreadsheet className="w-4 h-4 text-blue-600" />
            Importar Planilha CSV
          </h3>

          <div className="text-xs text-gray-600 mb-4 bg-white rounded-lg p-3 border">
            <p className="font-medium mb-2">Formato esperado (colunas):</p>
            <code className="text-xs text-blue-700 font-mono">
              Nome, Instagram, Twitter, Facebook, Telefone, Cargo, Observacoes
            </code>
            <div className="mt-2 flex gap-2">
              <button
                onClick={() => {
                  const blob = new Blob([CSV_EXEMPLO], { type: 'text/csv' })
                  const url = URL.createObjectURL(blob)
                  const a = document.createElement('a')
                  a.href = url
                  a.download = 'modelo_cabos.csv'
                  a.click()
                }}
                className="text-xs text-blue-600 hover:underline flex items-center gap-1"
              >
                <FileSpreadsheet className="w-3 h-3" />
                Baixar modelo CSV
              </button>
            </div>
          </div>

          <div
            className="border-2 border-dashed border-blue-300 rounded-lg p-8 text-center cursor-pointer hover:border-blue-500 hover:bg-blue-50 transition-colors"
            onDragOver={e => e.preventDefault()}
            onDrop={e => {
              e.preventDefault()
              const file = e.dataTransfer.files[0]
              if (file) handleImport(file)
            }}
            onClick={() => fileRef.current?.click()}
          >
            {importing ? (
              <div className="flex flex-col items-center gap-2">
                <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
                <p className="text-sm text-blue-600">Importando...</p>
              </div>
            ) : (
              <>
                <Upload className="w-8 h-8 text-blue-400 mx-auto mb-2" />
                <p className="text-sm text-gray-600 font-medium">Arraste o arquivo CSV ou clique para selecionar</p>
                <p className="text-xs text-gray-400 mt-1">Suporta arquivos .csv exportados do Excel, Google Sheets, etc.</p>
              </>
            )}
            <input
              ref={fileRef}
              type="file"
              accept=".csv,text/csv"
              className="hidden"
              onChange={e => e.target.files?.[0] && handleImport(e.target.files[0])}
            />
          </div>

          {importResult && (
            <div className={`mt-3 p-3 rounded-lg text-sm ${importResult.erros === 0 ? 'bg-green-50 border border-green-200' : 'bg-amber-50 border border-amber-200'}`}>
              <div className="flex items-center gap-2 font-medium">
                {importResult.erros === 0 ? <Check className="w-4 h-4 text-green-600" /> : <AlertCircle className="w-4 h-4 text-amber-600" />}
                <span>{importResult.criados} criados · {importResult.atualizados} atualizados · {importResult.erros} erros</span>
              </div>
              {importResult.detalhes?.map((d, i) => (
                <p key={i} className="text-xs text-red-600 mt-1">{d}</p>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Formulário de adição manual */}
      {showForm && (
        <div className="card mb-6 border border-blue-200">
          <h3 className="font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <Plus className="w-4 h-4 text-blue-600" />
            {form.pessoaId ? 'Editar Cabo' : 'Novo Apoiador'}
          </h3>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Nome *</label>
              <input value={form.nome} onChange={e => setForm(f => ({ ...f, nome: e.target.value }))} className="input" placeholder="Nome completo" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Tipo</label>
              <select value={form.tipo} onChange={e => setForm(f => ({ ...f, tipo: e.target.value }))} className="input">
                <option value="apoiador">Apoiador</option>
                <option value="coordenador">Coordenador</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Instagram</label>
              <input value={form.instagram} onChange={e => setForm(f => ({ ...f, instagram: e.target.value }))} className="input" placeholder="@handle" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Twitter / X</label>
              <input value={form.twitter} onChange={e => setForm(f => ({ ...f, twitter: e.target.value }))} className="input" placeholder="@handle" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Facebook</label>
              <input value={form.facebook} onChange={e => setForm(f => ({ ...f, facebook: e.target.value }))} className="input" placeholder="username ou @" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Telefone</label>
              <input value={form.telefone} onChange={e => setForm(f => ({ ...f, telefone: e.target.value }))} className="input" placeholder="(21) 99999-9999" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Cargo / Função</label>
              <input value={form.cargo} onChange={e => setForm(f => ({ ...f, cargo: e.target.value }))} className="input" placeholder="Ex: Liderança Zona Sul" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Observações</label>
              <input value={form.observacoes} onChange={e => setForm(f => ({ ...f, observacoes: e.target.value }))} className="input" placeholder="Notas adicionais" />
            </div>
          </div>
          <div className="flex gap-2 mt-4">
            <button onClick={handleSave} disabled={saving || !form.nome.trim()} className="btn-primary flex items-center gap-1.5 text-sm disabled:opacity-50">
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
              {form.pessoaId ? 'Salvar Alterações' : 'Cadastrar Cabo'}
            </button>
            <button onClick={() => setShowForm(false)} className="btn-secondary text-sm">Cancelar</button>
          </div>
        </div>
      )}

      {/* Filtros */}
      <div className="flex gap-3 mb-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="input pl-9"
            placeholder="Buscar por nome ou @handle..."
          />
        </div>
        <div className="relative">
          <select
            value={tipoFilter}
            onChange={e => setTipoFilter(e.target.value)}
            className="input pr-8 appearance-none"
          >
            <option value="todos">Todos os tipos</option>
            <option value="apoiador">Apoiadores</option>
            <option value="coordenador">Coordenadores</option>
          </select>
          <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
        </div>
      </div>

      {/* Lista de cabos */}
      {loading ? (
        <div className="flex justify-center py-16">
          <Loader2 className="w-6 h-6 animate-spin text-gray-400" />
        </div>
      ) : filtrados.length === 0 ? (
        <div className="card text-center py-16">
          <Users className="w-12 h-12 text-gray-200 mx-auto mb-3" />
          <p className="text-gray-400 font-medium">Nenhum cabo cadastrado</p>
          <p className="text-gray-300 text-xs mt-1">Importe uma planilha CSV ou adicione manualmente</p>
        </div>
      ) : (
        <div className="space-y-2">
          {/* Cabeçalho da tabela */}
          <div className="grid grid-cols-[2fr_1fr_auto_auto] items-center gap-4 px-4 py-2 text-xs font-medium text-gray-400 uppercase border-b border-gray-100">
            <span>Cabo</span>
            <span>Redes Sociais</span>
            <span className="text-right">Engajamento</span>
            <span className="text-right">Score</span>
          </div>

          {filtrados
            .sort((a, b) => b.score - a.score)
            .map((cabo, i) => {
              const totalLikes = cabo.bondFas.reduce((s, f) => s + f.totalLikes, 0)
              const totalComents = cabo.bondFas.reduce((s, f) => s + f.totalComents, 0)
              const totalShares = cabo.bondFas.reduce((s, f) => s + f.totalShares, 0)

              return (
                <div
                  key={cabo.id}
                  className="grid grid-cols-[2fr_1fr_auto_auto] items-center gap-4 px-4 py-3 hover:bg-gray-50 rounded-lg cursor-pointer group"
                  onClick={() => editarCabo(cabo)}
                >
                  {/* Nome + tipo + posição */}
                  <div className="flex items-center gap-3">
                    <div className="w-7 flex justify-center shrink-0">
                      {i < 3 ? (
                        <span className="text-lg">{['🥇', '🥈', '🥉'][i]}</span>
                      ) : (
                        <span className="text-xs text-gray-300 font-medium">{i + 1}</span>
                      )}
                    </div>
                    <div>
                      <div className="flex items-center gap-1.5">
                        <p className="text-sm font-medium text-gray-900">{cabo.nome}</p>
                        <span className={`text-xs px-1.5 py-0.5 rounded-full font-medium ${TIPO_COLOR[cabo.tipo] ?? 'bg-gray-100 text-gray-600'}`}>
                          {TIPO_LABEL[cabo.tipo] ?? cabo.tipo}
                        </span>
                        {cabo.plataformasVinculadas.length > 0 && (
                          <span className="text-xs bg-green-100 text-green-700 px-1.5 py-0.5 rounded-full flex items-center gap-0.5">
                            <Star className="w-2.5 h-2.5" />ativo
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 mt-0.5">
                        {cabo.cargo && <span className="text-xs text-gray-400">{cabo.cargo}</span>}
                        {cabo.telefone && (
                          <span className="flex items-center gap-0.5 text-xs text-gray-300">
                            <Phone className="w-2.5 h-2.5" />{cabo.telefone}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Handles de redes */}
                  <div className="flex flex-col gap-0.5">
                    {cabo.instagram && (
                      <span className="flex items-center gap-1 text-xs text-gray-500">
                        {PLAT_ICON['instagram']}@{cabo.instagram}
                        {cabo.plataformasVinculadas.includes('instagram') && (
                          <span className="w-1.5 h-1.5 bg-green-400 rounded-full" title="Vinculado ao Bond" />
                        )}
                      </span>
                    )}
                    {cabo.twitter && (
                      <span className="flex items-center gap-1 text-xs text-gray-500">
                        {PLAT_ICON['twitter']}@{cabo.twitter}
                        {cabo.plataformasVinculadas.includes('twitter') && (
                          <span className="w-1.5 h-1.5 bg-green-400 rounded-full" />
                        )}
                      </span>
                    )}
                    {cabo.facebook && (
                      <span className="flex items-center gap-1 text-xs text-gray-500">
                        {PLAT_ICON['facebook']}{cabo.facebook}
                        {cabo.plataformasVinculadas.includes('facebook') && (
                          <span className="w-1.5 h-1.5 bg-green-400 rounded-full" />
                        )}
                      </span>
                    )}
                    {!cabo.instagram && !cabo.twitter && !cabo.facebook && (
                      <span className="text-xs text-gray-300 italic">sem redes cadastradas</span>
                    )}
                  </div>

                  {/* Métricas de engajamento */}
                  <div className="flex items-center gap-3 text-xs shrink-0">
                    {cabo.plataformasVinculadas.length > 0 ? (
                      <>
                        <span className="flex items-center gap-1 text-red-500"><Heart className="w-3 h-3" />{totalLikes}</span>
                        <span className="flex items-center gap-1 text-blue-500"><MessageCircle className="w-3 h-3" />{totalComents}</span>
                        <span className="flex items-center gap-1 text-green-500"><Share2 className="w-3 h-3" />{totalShares}</span>
                      </>
                    ) : (
                      <span className="text-gray-300 text-xs">—</span>
                    )}
                  </div>

                  {/* Score + ações */}
                  <div className="flex items-center gap-2 shrink-0">
                    <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${cabo.score > 0 ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-400'}`}>
                      {cabo.score}
                    </span>
                    <button
                      onClick={e => { e.stopPropagation(); handleDelete(cabo.id) }}
                      className="opacity-0 group-hover:opacity-100 p-1 hover:bg-red-50 rounded transition-opacity"
                    >
                      <X className="w-3.5 h-3.5 text-red-400" />
                    </button>
                  </div>
                </div>
              )
            })}
        </div>
      )}

      {/* Legenda */}
      {filtrados.length > 0 && (
        <div className="mt-4 flex items-center gap-4 text-xs text-gray-400 px-4">
          <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 bg-green-400 rounded-full" />Vinculado ao Bond (rastreia interações)</span>
          <span>Score = ❤×1 + 💬×2 + 🔁×3</span>
          <span className="flex items-center gap-1"><Trophy className="w-3 h-3 text-yellow-500" />Ordenado por score</span>
        </div>
      )}
    </div>
  )
}
