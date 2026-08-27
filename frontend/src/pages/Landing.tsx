import { Link } from 'react-router-dom'
import { Button } from '@/components/common/Button'
import { ArrowRight, Sparkles, ShieldCheck, Database, Activity, Gauge, TrendingUp, Layers, Check } from 'lucide-react'
import { useEffect, useState } from 'react'

export default function Landing(){
  const [dark,setDark]=useState(()=> {
    if(typeof window==='undefined') return true
    return localStorage.getItem('odc-theme')==='dark' || !localStorage.getItem('odc-theme')
  })
  useEffect(()=>{ document.documentElement.classList.toggle('dark', dark)},[dark])

  return (
    <div className="min-h-screen bg-white dark:bg-[#070914] text-slate-900 dark:text-white overflow-x-hidden">
      {/* Nav */}
      <nav className="sticky top-0 z-50 border-b bg-white/75 backdrop-blur-xl dark:bg-[#0a0c14]/70 dark:border-white/[0.06]">
        <div className="mx-auto flex h-[64px] max-w-[1280px] items-center justify-between px-4">
          <div className="flex items-center gap-3">
            <div className="h-8 w-8 rounded-xl bg-[#0b0d18] dark:bg-white flex items-center justify-center shadow-sm">
              <div className="h-2.5 w-2.5 rounded-full bg-white dark:bg-[#0b0d18]" />
            </div>
            <span className="font-semibold tracking-tight">Open Data Copilot</span>
            <span className="text-xs text-muted-foreground ml-2 font-medium">by Sujal Gupta</span>
            <span className="hidden md:inline-flex rounded-full border bg-slate-50 px-2 py-0.5 text-[11px] dark:bg-white/5 dark:border-white/10">Premium Intelligence</span>
          </div>
          <div className="hidden md:flex items-center gap-6 text-[13.5px] text-slate-600 dark:text-white/60">
            <a href="#features" className="hover:text-slate-900 dark:hover:text-white">Features</a>
            <a href="#how" className="hover:text-slate-900 dark:hover:text-white">How It Works</a>
            <a href="#trust" className="hover:text-slate-900 dark:hover:text-white">Trust</a>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={()=>setDark(d=>!d)} className="h-9 px-3 rounded-full border bg-white text-xs dark:bg-white/5 dark:border-white/10">{dark?'☾':'☀'}</button>
            <Link to="/login"><Button variant="ghost" className="hidden sm:inline-flex">Sign In</Button></Link>
            <Link to="/signup"><Button>Get Started <ArrowRight className="ml-1.5 h-3.5 w-3.5" /></Button></Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 mesh opacity-100" />
        <div className="absolute inset-0 grid-pattern opacity-[0.35] dark:opacity-[0.2]" style={{maskImage:'linear-gradient(to bottom, black 60%, transparent)'}} />
        {/* ambient glow */}
        <div className="pointer-events-none absolute -top-24 left-1/2 -translate-x-1/2 h-[700px] w-[1200px] rounded-full blur-[80px] opacity-20 dark:opacity-25" style={{background:'radial-gradient(ellipse at center, #6d6af0 0%, transparent 60%)'}} />

        <div className="relative mx-auto max-w-[1280px] px-4 pt-14 pb-10 lg:pt-20 lg:pb-12">
          <div className="grid lg:grid-cols-2 gap-10 items-center">
            <div className="reveal">
              <div className="inline-flex items-center gap-2 rounded-full border bg-white px-3 py-1 text-[12px] font-medium shadow-sm dark:bg-white/5 dark:border-white/10">
                <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" /> Trusted Data Intelligence • SOC2-ready
              </div>
              <h1 className="mt-6 text-[40px] lg:text-[56px] font-semibold leading-[0.95] tracking-[-0.04em]">
                Turn Raw Data<br />
                <span className="bg-gradient-to-r from-[#3b5bff] via-[#6d6af0] to-[#a78bfa] bg-clip-text text-transparent">Into Trusted</span><br />
                Decisions.
              </h1>
              <p className="mt-5 text-[16px] lg:text-[18px] leading-relaxed text-slate-600 dark:text-white/60 max-w-[560px]">
                <span className="font-medium text-slate-900 dark:text-white">Upload. Clean. Analyze. Explain.</span> — the AI Data Doctor, premium analytics workspace, and audit-grade provenance.
              </p>
              <div className="mt-7 flex flex-wrap gap-3">
                <Link to="/signup"><Button size="lg">Start Analyzing <ArrowRight className="ml-2 h-4 w-4" /></Button></Link>
                <Link to="/login"><Button size="lg" variant="outline">View Demo →</Button></Link>
              </div>
              <div className="mt-6 flex items-center gap-4 text-xs text-slate-500 dark:text-white/50">
                <span className="inline-flex items-center gap-1.5"><ShieldCheck className="h-3.5 w-3.5" /> Provenance & trust score</span>
                <span className="inline-flex items-center gap-1.5"><Database className="h-3.5 w-3.5" /> DuckDB • Parquet • CSV</span>
              </div>

            </div>

            {/* 3D Hero Visualization */}
            <div className="relative lg:h-[560px] tilt">
              <div className="tilt-inner relative">
                {/* soft glow behind */}
                <div className="absolute -inset-6 bg-gradient-to-br from-[#6d6af0]/20 via-[#38bdf8]/15 to-transparent rounded-[32px] blur-2xl" />

                {/* Main stage card */}
                <div className="relative rounded-[24px] border bg-white dark:bg-[#0f1220] dark:border-white/10 elev-float overflow-hidden">
                  {/* top bar */}
                  <div className="flex items-center justify-between px-5 h-[56px] border-b dark:border-white/10">
                    <div className="flex items-center gap-2 text-xs font-medium"><Layers className="h-4 w-4 text-slate-500" /> Intelligence Workspace</div>
                    <div className="flex items-center gap-2 text-[11px]">
                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-500/20 px-2 py-1"><span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> Live</span>
                      <span className="text-slate-500">Dataset: retail_orders_v2</span>
                    </div>
                  </div>

                  {/* pipeline */}
                  <div className="px-5 pt-4 pb-2">
                    <div className="flex items-center justify-between gap-1 text-[11px]">
                      {[
                        {label:'Dataset', sub:'12.4k rows'},
                        {label:'AI Data Doctor', sub:'6 issues'},
                        {label:'Cleaning', sub:'4 ops'},
                        {label:'Analysis', sub:'SQL + Python'},
                        {label:'Insights', sub:'3 cards'},
                      ].map((s,i)=>(
                        <div key={s.label} className="flex items-center gap-1.5 flex-1">
                          <div className={`h-8 flex-1 rounded-full border flex items-center justify-center gap-1.5 text-[11px] font-medium ${i===1?'bg-[#0b0d18] text-white dark:bg-white dark:text-[#0b0d18] border-transparent':'bg-slate-50 dark:bg-white/5 border-slate-200 dark:border-white/10'}`}>
                            {i===1 && <Sparkles className="h-3 w-3" />} {s.label}
                          </div>
                          {i<4 && <div className="hidden sm:block h-px flex-1 bg-gradient-to-r from-slate-200 to-slate-100 dark:from-white/15 dark:to-transparent relative overflow-hidden"><div className="absolute inset-0 bg-gradient-to-r from-transparent via-[#6d6af0]/50 to-transparent animate-[drift_2s_ease_infinite]" /></div>}
                        </div>
                      ))}
                    </div>
                    {/* animated connection dots */}
                    <div className="mt-3 h-px bg-slate-100 dark:bg-white/5 relative overflow-hidden">
                      <div className="absolute top-1/2 -translate-y-1/2 h-1 w-12 rounded-full bg-gradient-to-r from-[#6d6af0] to-[#38bdf8] blur-[0.5px] animate-[drift_3s_ease_infinite]" />
                    </div>
                  </div>

                  {/* body grid */}
                  <div className="grid grid-cols-12 gap-3 p-4 bg-[#fcfcfd] dark:bg-[#0a0c14]">
                    {/* left KPIs */}
                    <div className="col-span-5 space-y-3">
                      <div className="rounded-[16px] border bg-white dark:bg-white/[0.04] dark:border-white/10 p-3 elev-1">
                        <div className="text-[10px] tracking-widest font-semibold text-slate-500">AVG QUALITY</div>
                        <div className="mt-1 flex items-baseline gap-2"><span className="text-[22px] font-semibold">94</span><span className="text-xs text-slate-500">/100</span><span className="ml-auto inline-flex items-center gap-1 rounded-full bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 px-2 py-0.5 text-[11px]"><TrendingUp className="h-3 w-3" /> +2.4%</span></div>
                        <div className="mt-2 h-1.5 rounded-full bg-slate-100 dark:bg-white/10 overflow-hidden"><div className="h-full w-[94%] bg-gradient-to-r from-emerald-500 to-teal-500" /></div>
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        <div className="rounded-[14px] border bg-white p-3 dark:bg-white/[0.04] dark:border-white/10"><div className="text-[10px] tracking-widest text-slate-500">ROWS</div><div className="text-[18px] font-semibold">12.4k</div><div className="text-[11px] text-slate-500">• 6 cols</div></div>
                        <div className="rounded-[14px] border bg-white p-3 dark:bg-white/[0.04] dark:border-white/10"><div className="text-[10px] tracking-widest text-slate-500">HEALTH</div><div className="text-[11px] flex gap-1 mt-1"><span className="px-1.5 py-0.5 rounded-full bg-emerald-500 text-white">4</span><span className="px-1.5 py-0.5 rounded-full bg-amber-500 text-white">1</span><span className="px-1.5 py-0.5 rounded-full bg-red-500 text-white">1</span></div></div>
                      </div>
                      <div className="rounded-[16px] border bg-gradient-to-br from-[#0b0d18] to-[#1a1d2e] text-white p-3 dark:border-white/10">
                        <div className="text-[11px] opacity-70 flex items-center gap-1.5"><Sparkles className="h-3 w-3" /> AI DATA DOCTOR</div>
                        <div className="text-[13px] font-medium mt-1">6 issues detected</div>
                        <div className="mt-2 space-y-1.5 text-[11px]">
                          <div className="flex items-center justify-between rounded-full bg-white/10 px-2.5 py-1"><span>Critical</span><span className="bg-red-500 text-white px-1.5 py-0.5 rounded-full">2</span></div>
                          <div className="flex items-center justify-between rounded-full bg-white/10 px-2.5 py-1"><span>Warning</span><span className="bg-amber-500 text-white px-1.5 py-0.5 rounded-full">3</span></div>
                        </div>
                      </div>
                    </div>

                    {/* chart */}
                    <div className="col-span-7 rounded-[16px] border bg-white dark:bg-white/[0.04] dark:border-white/10 p-3 elev-1">
                      <div className="flex items-center justify-between">
                        <div className="text-[12px] font-semibold">Revenue Trend</div>
                        <span className="text-[11px] rounded-full border bg-slate-50 px-2 py-1 dark:bg-white/5 dark:border-white/10">Last 6 months</span>
                      </div>
                      {/* premium line chart SVG */}
                      <div className="mt-3 h-[132px] relative">
                        <svg viewBox="0 0 300 120" className="w-full h-full">
                          <defs>
                            <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
                              <stop offset="0%" stopColor="#6d6af0" stopOpacity="0.25" />
                              <stop offset="100%" stopColor="#6d6af0" stopOpacity="0" />
                            </linearGradient>
                          </defs>
                          <g stroke="#e2e8f0" className="dark:opacity-20" strokeWidth="0.7" opacity="0.6">
                            <line x1="0" y1="20" x2="300" y2="20" /><line x1="0" y1="50" x2="300" y2="50" /><line x1="0" y1="80" x2="300" y2="80" /><line x1="0" y1="110" x2="300" y2="110" />
                          </g>
                          <path d="M0 90 C30 70, 60 85, 90 60 S150 40, 180 45 S240 80, 300 20" fill="none" stroke="#0b0d18" className="dark:stroke-white" strokeWidth="2.2" strokeLinecap="round" />
                          <path d="M0 90 C30 70, 60 85, 90 60 S150 40, 180 45 S240 80, 300 20 L300 110 L0 110 Z" fill="url(#g)" />
                          {/* dots */}
                          {[0,60,120,180,240,300].map((x,i)=> <g key={i}><circle cx={x||6} cy={[90,60,40,45,80,20][i]} r="3.5" fill="white" stroke="#6d6af0" strokeWidth="1.8" /><circle cx={x||6} cy={[90,60,40,45,80,20][i]} r="7" fill="#6d6af0" opacity="0.12" /></g>)}
                        </svg>
                        <div className="absolute left-[42%] top-[18%] rounded-full bg-[#0b0d18] text-white dark:bg-white dark:text-[#0b0d18] text-[11px] px-2 py-1 shadow-lg">● Insight: +18% peak</div>
                      </div>
                      <div className="mt-2 flex gap-2 text-[11px]">
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 px-2 py-1"><Activity className="h-3 w-3" /> Trusted</span>
                        <span className="text-slate-500">Method: SQL • DuckDB</span>
                      </div>
                    </div>

                    {/* bottom insight */}
                    <div className="col-span-12 rounded-[16px] border bg-white dark:bg-white/[0.04] dark:border-white/10 p-3 flex items-center gap-3">
                      <div className="h-10 w-10 rounded-full bg-gradient-to-br from-emerald-500 to-teal-500 grid place-items-center text-white"><Gauge className="h-5 w-5" /></div>
                      <div className="flex-1 min-w-0">
                        <div className="text-[13px] font-medium">Trust Score 94 — Trusted Insight</div>
                        <div className="text-[11px] text-slate-500 dark:text-white/60">Evidence • Chart • SQL • Methodology • Data Quality — all linked</div>
                      </div>
                      <span className="hidden sm:inline-flex items-center gap-1 rounded-full border bg-slate-50 px-3 py-1 text-xs dark:bg-white/5 dark:border-white/10"><Check className="h-3.5 w-3.5 text-emerald-600" /> Verified</span>
                    </div>
                  </div>
                </div>

                {/* floating cards */}
                <div className="hidden lg:block absolute -right-6 top-10 rounded-[14px] border bg-white dark:bg-[#151a2e] dark:border-white/10 p-3 w-[180px] elev-2" style={{transform:'rotate(2deg)'}}>
                  <div className="text-[11px] font-semibold">Dataset Health</div>
                  <div className="mt-2 space-y-1.5 text-[11px]">
                    <div className="flex justify-between"><span>Healthy</span><span className="text-emerald-600 font-medium">4</span></div>
                    <div className="flex justify-between"><span>Attention</span><span className="text-amber-600 font-medium">1</span></div>
                    <div className="flex justify-between"><span>Critical</span><span className="text-red-600 font-medium">1</span></div>
                  </div>
                </div>
                <div className="hidden lg:block absolute -left-8 bottom-10 rounded-[14px] border bg-white dark:bg-[#151a2e] dark:border-white/10 p-3 w-[190px] elev-2" style={{transform:'rotate(-1.5deg)'}}>
                  <div className="text-[11px] font-semibold">Insight • Evidence • Chart</div>
                  <div className="mt-2 text-[11px] text-slate-600 dark:text-white/60 leading-relaxed">Every answer carries its provenance. No black boxes.</div>
                  <div className="mt-2 flex gap-1.5"><span className="h-1.5 flex-1 rounded-full bg-[#0b0d18] dark:bg-white" /><span className="h-1.5 flex-1 rounded-full bg-slate-200 dark:bg-white/15" /><span className="h-1.5 flex-1 rounded-full bg-slate-200 dark:bg-white/15" /></div>
                </div>
              </div>
            </div>
          </div>

          {/* trust logos */}
          <div className="mt-12 border-t dark:border-white/10 pt-6 flex flex-wrap items-center justify-between gap-4 text-xs text-slate-500 dark:text-white/40">
            <span className="font-medium tracking-wide">TRUSTED DATA STACK</span>
            <div className="flex flex-wrap gap-6 items-center">
              <span>Linear-grade polish</span><span>•</span><span>Stripe-grade trust</span><span>•</span><span>Vercel-grade speed</span><span>•</span><span>Raycast-grade command</span>
            </div>
          </div>
        </div>
      </section>

      <section id="features" className="mx-auto max-w-[1280px] px-4 py-14">
        <div className="flex flex-col lg:flex-row justify-between gap-4 items-start">
          <h2 className="text-[28px] font-semibold tracking-tight">Everything for trusted analysis</h2>
          <p className="text-sm text-slate-600 dark:text-white/60 max-w-[520px]">From raw upload to board-ready reports — with explainability, not hallucinations.</p>
        </div>
        <div className="mt-8 grid md:grid-cols-3 gap-4">
          {[
            ["AI Data Doctor","Finds duplicates, nulls, outliers, drift — with severity & one-click fixes.", "from-[#6d6af0]/15 to-transparent"],
            ["Natural Language → SQL","Ask in plain English. Executed safely via DuckDB, shown with methodology.", "from-[#38bdf8]/15 to-transparent"],
            ["Premium Visualizations","Auto-selected, theme-aware charts with export-ready styling.", "from-emerald-500/15 to-transparent"],
            ["Trust Score","Every insight carries a 0–100 score with evidence, not vibes.", "from-amber-500/15 to-transparent"],
            ["Cleaning Studio","Pro-grade workstation: preview, history, recipes, before/after diff.", "from-[#a78bfa]/15 to-transparent"],
            ["Lineage & Reports","Trace any insight to its origin. One-click CSV/Excel/PowerBI exports.", "from-teal-500/15 to-transparent"],
          ].map(([t,d,grad])=>(
            <div key={t} className="group rounded-[20px] border bg-white dark:bg-white/[0.04] dark:border-white/10 p-5 elev-1 hover:elev-2 transition-all">
              <div className={`h-9 w-9 rounded-full bg-gradient-to-br ${grad} border dark:border-white/10 grid place-items-center`}><Sparkles className="h-4 w-4 opacity-70" /></div>
              <div className="mt-3 font-semibold text-[15px]">{t}</div>
              <div className="mt-1.5 text-[13px] leading-relaxed text-slate-600 dark:text-white/60">{d}</div>
            </div>
          ))}
        </div>
      </section>

      <section id="how" className="bg-[#fcfcfd] dark:bg-white/[0.02] border-y dark:border-white/10">
        <div className="mx-auto max-w-[1280px] px-4 py-12">
          <h2 className="text-[22px] font-semibold tracking-tight text-center">How it works</h2>
          <div className="mt-8 grid grid-cols-2 lg:grid-cols-6 gap-3">
            {[
              ["01","Upload","Drop CSV/XLSX/Parquet"],
              ["02","Understand","Auto profile & quality"],
              ["03","Ask","Natural language"],
              ["04","Analyze","SQL • Python"],
              ["05","Visualize","Premium charts"],
              ["06","Report","Export & share"],
            ].map(([n,t,s])=>(
              <div key={n} className="rounded-[16px] border bg-white dark:bg-white/[0.04] dark:border-white/10 p-4">
                <div className="text-[11px] tracking-widest text-slate-400">{n}</div>
                <div className="font-semibold mt-1">{t}</div>
                <div className="text-xs text-slate-500 dark:text-white/50 mt-1">{s}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <footer className="border-t dark:border-white/10 py-8">
        <div className="mx-auto max-w-[1280px] px-4 flex flex-col md:flex-row justify-between gap-4 text-sm text-slate-500 dark:text-white/50">
          <span>© 2026 Open Data Copilot — AI + Data + Trust + Intelligence + Premium SaaS</span>
          <span className="inline-flex items-center gap-2"><span className="h-2 w-2 rounded-full bg-emerald-500" /> All systems operational</span>
        </div>
      </footer>
    </div>
  )
}
