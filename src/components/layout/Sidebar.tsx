'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  LayoutDashboard,
  Users,
  Radio,
  FileText,
  BarChart3,
  Send,
  Bot,
  Settings,
  LogOut,
  ChevronLeft,
  ChevronRight,
  Landmark,
  Brain,
  Link2,
} from 'lucide-react'
import { useState } from 'react'
import clsx from 'clsx'

const nav = [
  { href: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { href: '/pessoas', icon: Users, label: 'Pessoas' },
  { href: '/monitoramento', icon: Radio, label: 'Monitoramento' },
  { href: '/demandas', icon: FileText, label: 'Demandas' },
  { href: '/produtividade', icon: BarChart3, label: 'Produtividade' },
  { href: '/telegram', icon: Send, label: 'Telegram' },
  { href: '/ia', icon: Bot, label: 'Assistente IA' },
  { href: '/hermes', icon: Brain, label: 'Hermes Agent' },
  { href: '/bond', icon: Link2, label: 'Bond — Social' },
  { href: '/configuracoes', icon: Settings, label: 'Configurações' },
]

export default function Sidebar() {
  const pathname = usePathname()
  const [collapsed, setCollapsed] = useState(false)

  return (
    <aside
      className={clsx(
        'relative flex flex-col bg-slate-900 text-slate-300 transition-all duration-300 min-h-screen',
        collapsed ? 'w-16' : 'w-64'
      )}
    >
      <div className="flex items-center gap-3 px-4 py-5 border-b border-slate-700">
        <Landmark className="w-7 h-7 text-blue-400 shrink-0" />
        {!collapsed && (
          <span className="font-bold text-white text-sm leading-tight">
            PolitiMonitor
          </span>
        )}
      </div>

      <nav className="flex-1 py-4 space-y-1 px-2">
        {nav.map(({ href, icon: Icon, label }) => {
          const active = pathname.startsWith(href)
          return (
            <Link
              key={href}
              href={href}
              className={clsx(
                'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
                active
                  ? 'bg-blue-600 text-white'
                  : 'text-slate-400 hover:bg-slate-800 hover:text-white'
              )}
            >
              <Icon className="w-5 h-5 shrink-0" />
              {!collapsed && <span>{label}</span>}
            </Link>
          )
        })}
      </nav>

      <div className="px-2 pb-4 border-t border-slate-700 pt-4">
        <form action="/api/auth/logout" method="POST">
          <button
            type="submit"
            className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-slate-400 hover:bg-slate-800 hover:text-white w-full transition-colors"
          >
            <LogOut className="w-5 h-5 shrink-0" />
            {!collapsed && <span>Sair</span>}
          </button>
        </form>
      </div>

      <button
        onClick={() => setCollapsed(!collapsed)}
        className="absolute -right-3 top-6 bg-slate-700 text-slate-300 rounded-full p-0.5 hover:bg-slate-600 border border-slate-600"
      >
        {collapsed ? (
          <ChevronRight className="w-4 h-4" />
        ) : (
          <ChevronLeft className="w-4 h-4" />
        )}
      </button>
    </aside>
  )
}
