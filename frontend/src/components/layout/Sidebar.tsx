import { Link, useLocation } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { LayoutDashboard, Database, Sparkles, MessageSquare, LineChart, FileText, Shield, Settings, Activity, ChevronLeft, Search, Command, Clock } from 'lucide-react'
import { useAuth } from '@/hooks/useAuth'

const nav = [
  { label: 'Overview', href: '/dashboard', icon: LayoutDashboard, desc: 'Command center' },
  { label: 'Datasets', href: '/datasets', icon: Database, desc: 'Your data files' },
  { label: 'Cleaning Studio', href: '/datasets', icon: Sparkles, sub: true, desc: 'Fix your data' },
  { label: 'Copilot', href: '/analysis', icon: MessageSquare, desc: 'Ask your data' },
  { label: 'Insights', href: '/analysis', icon: LineChart, sub:true, desc: 'Auto EDA & trends' },
  { label: 'Reports', href: '/reports', icon: FileText, desc: 'Exports & sharing' },
]

const bottom = [
  { label: 'Data Health', href: '/datasets', icon: Activity, desc: 'Quality & issues' },
  { label: 'Analysis History', href: '/analysis', icon: Clock, desc: 'Past sessions' },
  { label: 'Settings', href: '/settings', icon: Settings, desc: 'Preferences' },
  { label: 'Privacy', href: '/privacy', icon: Shield, desc: 'How data is handled' },
]

function SidebarUserFooter(){
  const { user } = useAuth()
  const displayName = user?.name?.trim() ? user.name : (user?.email ? user.email.split('@')[0] : 'User')
  const initial = displayName.charAt(0).toUpperCase()
  return (
    <div className="p-3 border-t border-slate-100 dark:border-white/[0.06]">
      <div className="rounded-[16px] border bg-slate-50 p-3 dark:bg-white/[0.04] dark:border-white/[0.06]">
        <div className="flex items-center gap-2 text-[12px] font-semibold"><Activity className="h-3.5 w-3.5 text-emerald-600" /> Data Health</div>
        <div className="mt-2 h-1.5 rounded-full bg-slate-200 dark:bg-white/10 overflow-hidden flex">
          <div className="bg-emerald-500 w-[68%]" />
          <div className="bg-amber-500 w-[22%]" />
          <div className="bg-red-500 w-[10%]" />
        </div>
        <div className="mt-2 flex justify-between text-[11px] text-slate-500 dark:text-white/50"><span>Healthy</span><span className="font-medium text-slate-900 dark:text-white">94% trust</span></div>
      </div>
      <div className="mt-3 flex items-center gap-2 px-1">
        <div className="h-7 w-7 rounded-full bg-[#0b0d18] dark:bg-white text-white dark:text-[#0b0d18] grid place-items-center text-[11px] font-semibold shrink-0">{initial}</div>
        <div className="min-w-0 flex-1"><div className="text-[13px] font-medium leading-none truncate">{displayName}</div><div className="text-[11px] text-slate-500 dark:text-white/50 truncate">{user?.email || ''}</div></div>
        <span className="h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)]" />
      </div>
    </div>
  )
}

export function Sidebar({ collapsed, onToggle }: { collapsed?: boolean; onToggle?: () => void }) {
  const loc = useLocation()
  const isActive = (href: string) => loc.pathname === href || (href !== '/dashboard' && loc.pathname.startsWith(href))

  return (
    <aside className={cn("hidden lg:flex shrink-0 flex-col border-r bg-white dark:bg-[#0a0c14] dark:border-white/[0.06] sticky top-0 h-screen", collapsed ? "w-[72px]" : "w-[252px]", "transition-all duration-200")}>
      {/* Logo */}
      <div className="h-[64px] flex items-center gap-3 px-5 border-b border-slate-100 dark:border-white/[0.06] shrink-0">
        <div className="h-8 w-8 rounded-xl bg-[#0b0d18] dark:bg-white flex items-center justify-center shrink-0 shadow-sm">
          <div className="h-2.5 w-2.5 rounded-full bg-white dark:bg-[#0b0d18] shadow-[0_0_10px_rgba(255,255,255,0.6)]" />
        </div>
        {!collapsed && (
           <div className="min-w-0">
             <div className="text-[13px] font-semibold tracking-tight leading-none">Open Data Copilot <span className="text-xs text-muted-foreground ml-1 font-medium">by Sujal Gupta</span></div>
             <div className="text-[11px] text-slate-500 dark:text-white/50 leading-none mt-1">Intelligence Platform</div>
           </div>
         )}
        <button onClick={onToggle} className="ml-auto hidden xl:inline-flex h-7 w-7 items-center justify-center rounded-full border border-slate-200 bg-white hover:bg-slate-50 dark:border-white/10 dark:bg-white/5">
          <ChevronLeft className={cn("h-3.5 w-3.5 transition", collapsed && "rotate-180")} />
        </button>
      </div>

      {/* Search / Command */}
      {!collapsed && (
        <div className="px-3 py-3">
          <button onClick={()=> window.dispatchEvent(new KeyboardEvent('keydown',{key:'k', ctrlKey:true}))} className="w-full flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-2 text-[13px] text-slate-500 hover:bg-white hover:border-slate-300 transition-colors dark:border-white/10 dark:bg-white/[0.06] dark:text-white/60 dark:hover:bg-white/[0.08]">
            <Search className="h-3.5 w-3.5" /> Search
            <span className="ml-auto inline-flex items-center gap-1 rounded-full border bg-white px-1.5 py-0.5 text-[11px] dark:bg-white/10 dark:border-white/10"><Command className="h-3 w-3" />K</span>
          </button>
        </div>
      )}

      <nav className="flex-1 overflow-auto px-2 py-2">
        <div className="px-3 pb-2 text-[10px] font-semibold tracking-widest text-slate-400 dark:text-white/30 uppercase">{!collapsed && "Workspace"}</div>
        <div className="space-y-1">
          {nav.map(i=>{
            const Icon=i.icon
            const active=isActive(i.href) && !(i.sub)
            if(i.sub && collapsed) return null
            return (
              <Link key={i.label+i.href} to={i.href} className={cn(
                "flex items-center gap-3 rounded-full px-3 py-2 transition-colors",
                active ? "bg-[#0b0d18] text-white dark:bg-white dark:text-[#0b0d18] shadow-sm" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900 dark:text-white/60 dark:hover:bg-white/[0.06] dark:hover:text-white",
                collapsed ? "justify-center px-2" : "px-3",
                i.sub && "ml-6 opacity-80"
              )}>
                <Icon className={cn("h-4 w-4 shrink-0", active && "text-white dark:text-[#0b0d18]")} />
                {!collapsed && (
                  <span className="flex-1 min-w-0">
                    <span className="block text-[13.5px] font-medium leading-none truncate">{i.label}</span>
                    <span className="block text-[11px] opacity-60 leading-none mt-0.5 truncate">{(i as any).desc}</span>
                  </span>
                )}
                {!collapsed && active && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-white dark:bg-[#0b0d18]" />}
              </Link>
            )
          })}
        </div>

        <div className="mt-6 px-3 pb-2 text-[10px] font-semibold tracking-widest text-slate-400 dark:text-white/30 uppercase">{!collapsed && "System"}</div>
        <div className="space-y-1">
          {bottom.map(i=>{
            const Icon=i.icon
            return (
              <Link key={i.href+i.label} to={i.href} className={cn("flex items-center gap-3 rounded-full px-3 py-2 text-slate-600 hover:bg-slate-50 dark:text-white/60 dark:hover:bg-white/[0.06]", collapsed && "justify-center")}>
                <Icon className="h-4 w-4 shrink-0" />
                {!collapsed && (
                  <span className="flex-1 min-w-0">
                    <span className="block text-[13.5px] font-medium leading-none">{i.label}</span>
                    <span className="block text-[11px] opacity-60 leading-none mt-0.5">{(i as any).desc}</span>
                  </span>
                )}
              </Link>
            )
          })}
        </div>
      </nav>

      {/* Health mini + user identity */}
      {!collapsed && <SidebarUserFooter />}
    </aside>
  )
}
