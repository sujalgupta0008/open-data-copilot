import { useQuery } from '@tanstack/react-query'
import api from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/common/Card'
import { Button } from '@/components/common/Button'
import { Link } from 'react-router-dom'
import { Database, LineChart, FileText, Gauge, Sparkles, ArrowUpRight, Activity, Clock, Upload, Search } from 'lucide-react'

function KPICard({ label, value, sub, icon: Icon, trend }: any){
  return (
    <Card className="relative overflow-hidden group">
      <div className="absolute inset-0 bg-gradient-to-br from-white to-slate-50 dark:from-white/[0.04] dark:to-transparent opacity-60" />
      <div className="absolute -right-6 -top-6 h-24 w-24 rounded-full bg-gradient-to-br from-[#6d6af0]/12 to-transparent blur-xl group-hover:from-[#6d6af0]/18 transition-colors" />
      <CardHeader className="pb-2 relative">
        <CardTitle className="text-[10px] tracking-[0.14em] text-slate-500 dark:text-white/50 flex items-center gap-1.5"><Icon className="h-3.5 w-3.5" /> {label}</CardTitle>
      </CardHeader>
      <CardContent className="relative">
        <div className="flex items-baseline gap-2">
          <div className="text-[26px] font-semibold tracking-tight leading-none">{value}</div>
          {trend && <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 px-1.5 py-0.5 text-[11px] font-medium"><ArrowUpRight className="h-3 w-3" /> {trend}</span>}
        </div>
        <div className="text-[11px] text-slate-500 dark:text-white/50 mt-1">{sub}</div>
      </CardContent>
    </Card>
  )
}

import { OnboardingBanner } from '@/components/onboarding/Onboarding'
import { HelpTooltip } from '@/components/common/HelpTooltip'
import { useAuth } from '@/hooks/useAuth'

export default function Dashboard(){
  const { user } = useAuth()
  const displayName = user?.name?.trim() ? user.name : (user?.email ? user.email.split('@')[0] : 'there')
  const { data, isLoading } = useQuery({ queryKey:['dashboard'], queryFn: async()=> (await api.get('/api/dashboard/stats')).data })
  if(isLoading) return (
    <div className="space-y-6 animate-pulse">
      <div className="h-10 w-64 shimmer rounded-full" />
      <div className="grid md:grid-cols-5 gap-4">{Array.from({length:5}).map((_,i)=><div key={i} className="h-[110px] rounded-[16px] border shimmer" />)}</div>
      <div className="grid md:grid-cols-3 gap-6">{Array.from({length:3}).map((_,i)=><div key={i} className="h-[220px] rounded-[16px] border shimmer" />)}</div>
    </div>
  )
  const health = data.dataset_health || {healthy:0, attention:0, critical:0}
  const totalHealth = health.healthy + health.attention + health.critical || 1
  const hasDatasets = (data?.total_datasets ?? 0) > 0
  return (
    <div className="space-y-6">
      <OnboardingBanner hasDatasets={hasDatasets} />
      {/* Header */}
      <div className="flex flex-col lg:flex-row justify-between gap-4">
        <div>
          <h1 className="text-[28px] font-semibold tracking-tight leading-none">Good morning, {displayName}</h1>
          <p className="text-sm text-slate-600 dark:text-white/60 mt-2 flex items-center gap-2">Command center — trust, provenance, and momentum at a glance. <HelpTooltip title="How to start">Upload a dataset → check Data Health (quality & issues) → Fix your data in Cleaning Studio → Ask your data via Copilot → validate with Trust & Lineage → Generate report. Click “Start New Analysis” to begin.</HelpTooltip></p>
        </div>
        <div className="flex items-center gap-2">
          <div className="hidden md:flex items-center gap-2 rounded-full border bg-white px-2 py-1 dark:bg-white/5 dark:border-white/10">
            <Search className="h-3.5 w-3.5 text-slate-500" />
            <input placeholder="Search datasets…" className="bg-transparent outline-none text-sm placeholder:text-slate-400 w-[180px] dark:text-white" />
            <span className="rounded-full bg-slate-900 text-white dark:bg-white dark:text-slate-900 px-2 py-1 text-[11px]">⌘K</span>
          </div>
          <Link to="/datasets"><Button><Upload className="h-3.5 w-3.5 mr-1.5" /> Upload Dataset</Button></Link>
          <Link to="/privacy"><Button variant="outline">Privacy Center</Button></Link>
        </div>
      </div>

      {/* Start New Analysis CTA - prominent when no datasets */}
      {!hasDatasets && (
        <div className="rounded-[16px] border bg-gradient-to-r from-[#0b0d18] to-[#1a1d2e] text-white p-4 flex flex-col md:flex-row gap-3 items-center justify-between dark:border-white/10">
          <span className="flex gap-3 items-center"><span className="h-10 w-10 rounded-full bg-white text-[#0b0d18] grid place-items-center"><Upload className="h-5 w-5" /></span><span><span className="font-semibold block">Start New Analysis</span><span className="text-xs opacity-70">Upload your first dataset to see health, cleaning, and Copilot in action.</span></span></span>
          <Link to="/datasets"><Button variant="outline" className="bg-white text-[#0b0d18] hover:bg-slate-100">Upload Dataset <ArrowUpRight className="ml-1 h-3.5 w-3.5" /></Button></Link>
        </div>
      )}

      {/* KPI */}
      <div className="grid md:grid-cols-5 gap-4 stagger">
        <KPICard label="TOTAL DATASETS" value={data.total_datasets} sub="Across workspace" icon={Database} />
        <KPICard label="ANALYSES" value={data.total_analyses} sub="Sessions" icon={LineChart} trend="+4" />
        <KPICard label="REPORTS" value={data.total_reports} sub="Generated" icon={FileText} />
        <KPICard label="AVG QUALITY" value={<><span>{data.avg_quality}</span><span className="text-[14px] font-normal text-slate-500">/100</span></>} sub="Trust baseline" icon={Gauge} trend="stable" />
        <KPICard label="CLEANING OPS" value={data.total_cleaning_ops ?? 0} sub="Transformations" icon={Sparkles} />
      </div>

      {/* Health + Activity + Quick Actions */}
      <div className="grid lg:grid-cols-3 gap-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-sm flex items-center gap-2"><Activity className="h-4 w-4" /> Dataset Health</CardTitle>
            <span className="text-[11px] rounded-full border bg-slate-50 px-2 py-1 dark:bg-white/5 dark:border-white/10">{health.healthy+health.attention+health.critical} datasets</span>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="h-2 rounded-full bg-slate-100 dark:bg-white/10 overflow-hidden flex">
              <div style={{width:`${(health.healthy/totalHealth)*100}%`}} className="bg-emerald-500" />
              <div style={{width:`${(health.attention/totalHealth)*100}%`}} className="bg-amber-500" />
              <div style={{width:`${(health.critical/totalHealth)*100}%`}} className="bg-red-500" />
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between rounded-full border px-3 py-2.5 bg-emerald-50 border-emerald-200 dark:bg-emerald-500/10 dark:border-emerald-500/20">
                <span className="text-sm flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-emerald-500" /> Healthy</span><span className="font-semibold text-emerald-700 dark:text-emerald-300">{health.healthy}</span>
              </div>
              <div className="flex items-center justify-between rounded-full border px-3 py-2.5 bg-amber-50 border-amber-200 dark:bg-amber-500/10 dark:border-amber-500/20">
                <span className="text-sm flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-amber-500" /> Needs attention</span><span className="font-semibold text-amber-700 dark:text-amber-300">{health.attention}</span>
              </div>
              <div className="flex items-center justify-between rounded-full border px-3 py-2.5 bg-red-50 border-red-200 dark:bg-red-500/10 dark:border-red-500/20">
                <span className="text-sm flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-red-500" /> Critical</span><span className="font-semibold text-red-700 dark:text-red-300">{health.critical}</span>
              </div>
            </div>
            <div className="text-[11px] text-slate-500 dark:text-white/50">Scored by completeness • consistency • freshness</div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="text-sm flex items-center gap-2"><Clock className="h-4 w-4" /> Recent Activity</CardTitle></CardHeader>
          <CardContent>
            {(!data.recent_activity || data.recent_activity.length===0) ? (
              <div className="py-10 text-center">
                <div className="mx-auto h-12 w-12 rounded-full border bg-slate-50 grid place-items-center dark:bg-white/5 dark:border-white/10"><Clock className="h-5 w-5 text-slate-400" /></div>
                <div className="text-sm font-medium mt-3">No activity yet</div>
                <div className="text-xs text-slate-500">Your cleaning & analysis history will appear here.</div>
              </div>
            ) : (
              <div className="space-y-2 text-sm">{data.recent_activity.map((a:any,i:number)=><div key={i} className="flex items-center justify-between rounded-full border px-3 py-2.5 hover:bg-slate-50 dark:hover:bg-white/5 transition-colors"><span className="truncate pr-2">{a.title}</span><span className="text-xs text-slate-500 shrink-0 ml-2 rounded-full bg-slate-100 px-2 py-1 dark:bg-white/10">{new Date(a.timestamp).toLocaleDateString()}</span></div>)}</div>
            )}
          </CardContent>
        </Card>

        <Card className="overflow-hidden">
          <CardHeader><CardTitle className="text-sm">Quick Actions</CardTitle></CardHeader>
          <CardContent className="grid grid-cols-2 gap-3 text-xs">
            {[
              { label:'Upload', icon:'↗', href:'/datasets', desc:'New dataset' },
              { label:'Clean', icon:'✦', href:'/datasets', desc:'Studio' },
              { label:'Analyze', icon:'◐', href:'/analysis', desc:'Copilot' },
              { label:'Report', icon:'▤', href:'/reports', desc:'Generate' },
            ].map(a=>(
              <Link key={a.label} to={a.href} className="group rounded-[16px] border bg-white p-4 hover:bg-slate-50 dark:bg-white/[0.04] dark:border-white/10 dark:hover:bg-white/[0.06] transition-colors">
                <div className="h-8 w-8 rounded-full bg-[#0b0d18] text-white dark:bg-white dark:text-[#0b0d18] grid place-items-center text-xs">{a.icon}</div>
                <div className="font-medium mt-2 text-sm">{a.label}</div>
                <div className="text-slate-500 dark:text-white/50">{a.desc}</div>
              </Link>
            ))}
          </CardContent>
        </Card>
      </div>

      <div className="grid md:grid-cols-2 gap-6">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-sm">Recent Datasets</CardTitle>
            <Link to="/datasets" className="text-xs rounded-full border px-3 py-1 hover:bg-slate-50 dark:hover:bg-white/5">View all</Link>
          </CardHeader>
          <CardContent>
            {data.recent_datasets.length===0? (
              <div className="py-10 text-center border border-dashed rounded-[16px] bg-slate-50/50 dark:bg-white/[0.03] dark:border-white/10">
                <div className="mx-auto h-10 w-10 rounded-full bg-white border grid place-items-center dark:bg-white/5"><Database className="h-4 w-4" /></div>
                <div className="text-sm font-medium mt-3">No datasets yet</div>
                <div className="text-xs text-slate-500">Upload your first dataset to begin.</div>
                <Link to="/datasets"><Button size="sm" className="mt-3">Upload</Button></Link>
              </div>
            ) : (
              <div className="space-y-2">{data.recent_datasets.map((d:any)=>
                <Link key={d.id} to={`/datasets/${d.id}`} className="group flex items-center justify-between rounded-full border px-4 py-3 hover:bg-slate-50 hover:border-slate-300 dark:hover:bg-white/5 dark:border-white/10 transition-colors">
                  <span className="flex items-center gap-3 min-w-0"><span className="h-8 w-8 rounded-full bg-gradient-to-br from-[#6d6af0] to-[#38bdf8] grid place-items-center text-white text-xs">◈</span><span className="truncate font-medium text-sm">{d.name}</span></span>
                  <span className="text-xs text-slate-500 flex items-center gap-2 shrink-0 ml-3"><span className="hidden sm:inline">{d.row_count} rows • {d.quality_score}/100</span><ArrowUpRight className="h-3.5 w-3.5 opacity-0 group-hover:opacity-100 transition" /></span>
                </Link>
              )}</div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-sm">Recent Analyses</CardTitle>
            <Link to="/analysis" className="text-xs rounded-full border px-3 py-1 hover:bg-slate-50 dark:hover:bg-white/5">View all</Link>
          </CardHeader>
          <CardContent>
            {data.recent_analyses.length===0? (
              <div className="py-10 text-center border border-dashed rounded-[16px] bg-slate-50/50 dark:bg-white/[0.03] dark:border-white/10">
                <div className="mx-auto h-10 w-10 rounded-full bg-white border grid place-items-center dark:bg-white/5"><LineChart className="h-4 w-4" /></div>
                <div className="text-sm font-medium mt-3">No analyses yet</div>
                <div className="text-xs text-slate-500">Ask Copilot to generate your first insight.</div>
              </div>
            ) : (
              <div className="space-y-2">{data.recent_analyses.map((a:any)=><Link key={a.id} to={`/analysis/${a.id}`} className="block rounded-[16px] border px-4 py-3 hover:bg-slate-50 dark:hover:bg-white/5 dark:border-white/10 transition-colors"><div className="font-medium text-sm">{a.title}</div><div className="text-xs text-slate-500 mt-1 inline-flex items-center gap-1.5"><Clock className="h-3 w-3" /> {new Date(a.updated_at).toLocaleString()}</div></Link>)}</div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
