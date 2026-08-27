import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, Database, Sparkles, MessageSquare, FileText, Upload, BarChart3, Settings } from 'lucide-react'

const actions = [
  { id:'upload', label:'Upload dataset', desc:'Add a new CSV/XLSX/JSON', icon: Upload, href:'/datasets' },
  { id:'open', label:'Open dataset', desc:'Browse your datasets', icon: Database, href:'/datasets' },
  { id:'clean', label:'Open Cleaning Studio', desc:'Diagnose & transform data', icon: Sparkles, href:'/datasets' },
  { id:'copilot', label:'Ask Copilot', desc:'Natural language analysis', icon: MessageSquare, href:'/analysis' },
  { id:'report', label:'Generate report', desc:'Create a new report', icon: FileText, href:'/reports' },
  { id:'dashboard', label:'Go to Dashboard', desc:'Overview & KPIs', icon: BarChart3, href:'/dashboard' },
  { id:'settings', label:'Settings', desc:'Workspace preferences', icon: Settings, href:'/settings' },
]

export function CommandPalette(){
  const [open,setOpen]=useState(false)
  const [query,setQuery]=useState('')
  const navigate=useNavigate()

  useEffect(()=>{
    const onKey=(e:KeyboardEvent)=>{
      if((e.metaKey||e.ctrlKey) && e.key.toLowerCase()==='k'){ e.preventDefault(); setOpen(o=>!o)}
      if(e.key==='Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return ()=> window.removeEventListener('keydown', onKey)
  },[])

  const filtered = actions.filter(a=> !query || a.label.toLowerCase().includes(query.toLowerCase()) || a.desc.toLowerCase().includes(query.toLowerCase()))

  if(!open) return null
  return (
    <div className="fixed inset-0 z-[80] flex items-start justify-center pt-[18vh] p-4">
      <div className="absolute inset-0 cmd-backdrop" onClick={()=>setOpen(false)} />
      <div className="relative w-full max-w-[640px] rounded-[20px] border bg-white dark:bg-[#0f1220] dark:border-white/10 shadow-[0_16px_48px_rgba(0,0,0,0.18)] overflow-hidden">
        <div className="flex items-center gap-3 px-4 h-[56px] border-b dark:border-white/10">
          <Search className="h-4 w-4 text-slate-500" />
          <input autoFocus value={query} onChange={e=>setQuery(e.target.value)} placeholder="Search datasets, run actions, ask copilot…" className="flex-1 bg-transparent outline-none text-[14px] placeholder:text-slate-400 dark:text-white" />
          <span className="rounded-full border bg-slate-50 px-2 py-1 text-[11px] dark:bg-white/5 dark:border-white/10">ESC</span>
        </div>
        <div className="max-h-[380px] overflow-auto p-2">
          {filtered.map(a=>{
            const Icon=a.icon
            return (
              <button key={a.id} onClick={()=>{ setOpen(false); navigate(a.href)}} className="w-full flex items-center gap-3 rounded-xl px-3 py-3 hover:bg-slate-50 dark:hover:bg-white/5 text-left transition-colors">
                <span className="h-9 w-9 rounded-full border bg-white flex items-center justify-center dark:bg-white/5 dark:border-white/10"><Icon className="h-4 w-4" /></span>
                <span className="flex-1 min-w-0"><span className="text-[13.5px] font-medium block">{a.label}</span><span className="text-[12px] text-slate-500 dark:text-white/50">{a.desc}</span></span>
                <span className="text-[11px] text-slate-400">↵</span>
              </button>
            )
          })}
          {filtered.length===0 && <div className="p-8 text-center text-sm text-slate-500">No results for “{query}”</div>}
        </div>
        <div className="px-4 py-2 border-t dark:border-white/10 text-[11px] text-slate-500 dark:text-white/40 flex justify-between">
          <span>Tip: Type “clean” to open Cleaning Studio for any dataset</span>
          <span>⌘K to toggle</span>
        </div>
      </div>
    </div>
  )
}
