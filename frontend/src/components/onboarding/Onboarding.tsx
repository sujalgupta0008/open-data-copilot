import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/common/Card'
import { Button } from '@/components/common/Button'
import { Sparkles, Upload, Gauge, Brush, Search, MessageSquare, ShieldCheck, FileText, X, ArrowRight, Check } from 'lucide-react'

const STEPS = [
  { id: 'upload', label: 'Upload', desc: 'Add your CSV/XLSX/JSON', icon: Upload },
  { id: 'health', label: 'Check Health', desc: 'Quality & issues', icon: Gauge },
  { id: 'clean', label: 'Fix your data', desc: 'Cleaning Studio', icon: Brush },
  { id: 'explore', label: 'Explore', desc: 'Preview & profile', icon: Search },
  { id: 'copilot', label: 'Ask your data', desc: 'Copilot Q&A', icon: MessageSquare },
  { id: 'validate', label: 'Validate', desc: 'Trust & lineage', icon: ShieldCheck },
  { id: 'report', label: 'Generate report', desc: 'Exports & sharing', icon: FileText },
]

export function OnboardingBanner({ hasDatasets }: { hasDatasets: boolean }) {
  const [dismissed, setDismissed] = useState(()=> localStorage.getItem('odc-onboarding-dismissed')==='1')
  const [active, setActive] = useState(0)
  useEffect(()=>{
    const t=setInterval(()=> setActive(a=> (a+1)%STEPS.length), 2500)
    return ()=> clearInterval(t)
  },[])
  if(dismissed) return null
  return (
    <Card className="overflow-hidden border-[#6d6af0]/20 dark:border-white/10">
      <div className="h-1 bg-gradient-to-r from-[#6d6af0] to-[#38bdf8]" />
      <CardHeader className="pb-2 flex flex-row items-start justify-between gap-3">
        <div>
          <CardTitle className="flex items-center gap-2 text-[15px]"><Sparkles className="h-4 w-4 text-[#6d6af0]" /> Welcome to Open Data Copilot</CardTitle>
          <p className="text-xs text-slate-500 dark:text-white/60 mt-1">Your workflow: Upload → Check health → Fix → Explore → Ask → Validate → Report. It takes 2 minutes.</p>
        </div>
        <button onClick={()=>{ setDismissed(true); localStorage.setItem('odc-onboarding-dismissed','1')}} className="h-8 w-8 rounded-full border bg-white dark:bg-white/5 grid place-items-center"><X className="h-3.5 w-3.5" /></button>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex gap-1.5 overflow-auto pb-1">
          {STEPS.map((s,i)=>{
            const Icon=s.icon
            const isActive=i===active
            return (
              <span key={s.id} className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs whitespace-nowrap transition ${isActive?'bg-[#0b0d18] text-white dark:bg-white dark:text-[#0b0d18] border-transparent shadow-sm':'bg-white dark:bg-white/5 dark:border-white/10'}`}>
                <Icon className="h-3.5 w-3.5" />{s.label}
              </span>
            )
          })}
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to="/datasets"><Button size="sm">Start New Analysis <ArrowRight className="ml-1 h-3.5 w-3.5" /></Button></Link>
          {!hasDatasets && <span className="text-xs rounded-full border bg-slate-50 px-3 py-1.5 dark:bg-white/5 dark:border-white/10 inline-flex items-center gap-1"><Check className="h-3 w-3" /> No datasets yet — upload first</span>}
          <Button size="sm" variant="outline" onClick={()=>{ setDismissed(true); localStorage.setItem('odc-onboarding-dismissed','1')}}>Dismiss</Button>
        </div>
        <div className="text-[11px] text-slate-500 dark:text-white/50">Tip: After upload, you’ll see a “Next recommended action” card so you never wonder what to do next.</div>
      </CardContent>
    </Card>
  )
}

export function NextStepCard({ title, desc, primary, secondary, icon: Icon }: { title: string; desc: string; primary: { label: string; to: string }; secondary?: { label: string; to: string }; icon?: any }) {
  const I = Icon || Sparkles
  return (
    <Card className="overflow-hidden border-emerald-200 dark:border-emerald-500/20">
      <div className="h-1 bg-gradient-to-r from-emerald-500 to-teal-500" />
      <CardContent className="p-4 flex gap-4 items-center">
        <span className="h-10 w-10 rounded-full bg-emerald-500 text-white grid place-items-center shrink-0"><I className="h-5 w-5" /></span>
        <span className="flex-1 min-w-0">
          <span className="text-xs tracking-widest font-semibold text-emerald-700 dark:text-emerald-300">NEXT RECOMMENDED ACTION</span>
          <span className="font-semibold block text-sm mt-0.5">{title}</span>
          <span className="text-xs text-slate-500 dark:text-white/60 block">{desc}</span>
        </span>
        <span className="flex gap-2 shrink-0">
          <Link to={primary.to}><Button size="sm">{primary.label} <ArrowRight className="ml-1 h-3.5 w-3.5" /></Button></Link>
          {secondary && <Link to={secondary.to}><Button size="sm" variant="outline">{secondary.label}</Button></Link>}
        </span>
      </CardContent>
    </Card>
  )
}
