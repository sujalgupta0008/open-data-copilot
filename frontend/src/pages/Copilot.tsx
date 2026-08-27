import { useParams } from 'react-router-dom'
import { useState, useMemo, useEffect, useRef } from 'react'
import api from '@/services/api'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@/components/common/Button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/common/Card'
import { ChartRenderer } from '@/components/charts/ChartRenderer'
import { Sparkles, Database, Gauge, MessageSquare, Search, Send, Brain, ShieldCheck, GitBranch, FileCode, BarChart3, AlertTriangle, FileText, RotateCw, Share2, X, Link as LinkIcon } from 'lucide-react'
import { MiniLineage } from '@/components/copilot/MiniLineage'
import { TrustRing } from '@/components/copilot/TrustRing'

function generateQuickPrompts(columns: any[] | undefined, datasetType?: string, confidence?: number): string[] {
  const typeNorm = (datasetType || '').toLowerCase().replace(/[\s-]+/g, '_')
  const conf = confidence ?? 100
  const typeTemplates: Record<string,string[]> = {
    flight_pricing: ["Which airline has highest avg fare?","How does price vary by source city?","What is price distribution by airline?","Which route has most price outliers?","How has avg fare trended over booking dates?","Compare price across different journey types"],
    ecommerce: ["Which product category drives most revenue?","What is monthly sales trend?","Which region has highest order value?","What is return rate by category?","Compare revenue this month vs last month","Which customer segment is most valuable?"],
    finance: ["What is revenue trend by quarter?","Which expense category grew fastest?","What drives profit margin changes?","Compare actual vs budget by department","Which accounts show unusual activity?","What is cash flow distribution?"]
  }
  // normalize key
  let typeKey = ''
  if(typeNorm.includes('flight')) typeKey='flight_pricing'
  else if(typeNorm.includes('ecommerce')||typeNorm.includes('e_commerce')||typeNorm.includes('sales')) typeKey='ecommerce'
  else if(typeNorm.includes('finance')) typeKey='finance'

  const useTypeAware = typeKey && conf >= 60 && typeTemplates[typeKey]
  let typeSpecific: string[] = []
  if(useTypeAware){
    typeSpecific = typeTemplates[typeKey].slice(0,4)
  }

  // Generic generation (keep original logic for fallback/mix)
  if (!columns || columns.length === 0) {
    const base = ["Explain this dataset","Missing values","Show summary statistics","Any outliers?","Correlation between numeric columns"]
    return [...typeSpecific, ...base].slice(0,12)
  }
  const isNumeric = (c: any) => { const dt=(c.data_type||"").toLowerCase(); return dt.includes("int")||dt.includes("float")||dt.includes("double")||dt.includes("decimal")||dt.includes("number")||c.mean_value!=null }
  const isDatetime = (c: any) => { const dt=(c.data_type||"").toLowerCase(); const name=(c.name||"").toLowerCase(); return dt.includes("date")||dt.includes("time")||name.includes("date")||name.includes("time") }
  const numericCols = columns.filter(isNumeric)
  const datetimeCols = columns.filter(isDatetime)
  const categoricalCols = columns.filter(c => !isNumeric(c) && !isDatetime(c))
  let primaryNum: string | null = null
  const priceKeywords = ["revenue","price","fare","amount","total","cost","sales","quantity"]
  for(const kw of priceKeywords){ const found=numericCols.find(c=>c.name.toLowerCase().includes(kw)); if(found){ primaryNum=found.name; break }}
  if(!primaryNum && numericCols.length>0) primaryNum=numericCols[0].name
  const catPriority=["category","product","region","airline","source","destination","customer_id","order_id"]
  const sortedCats=[...categoricalCols]; sortedCats.sort((a,b)=>{ const ai=catPriority.indexOf(a.name.toLowerCase()); const bi=catPriority.indexOf(b.name.toLowerCase()); if(ai===-1&&bi===-1) return 0; if(ai===-1) return 1; if(bi===-1) return -1; return ai-bi})
  const hasPriority = sortedCats.some((c,i)=> catPriority.includes(c.name.toLowerCase()) && categoricalCols[i]?.name !== c.name)
  const effectiveCats = hasPriority? sortedCats : categoricalCols
  const prompts:string[]=[]; const pluralize=(w:string)=> w.endsWith("y")? w.slice(0,-1)+"ies" : w.endsWith("s")? w: w+"s"; const cap=(w:string)=> w.charAt(0).toUpperCase()+w.slice(1)
  if(effectiveCats.length>0 && primaryNum){ const firstCat=effectiveCats[0].name; prompts.push(`Top 5 ${pluralize(firstCat)} by total ${primaryNum}`); prompts.push(`Average ${primaryNum} by ${firstCat}`); const remaining=effectiveCats.slice(1,3); for(const cat of remaining){ prompts.push(`Which ${cat.name} has the highest average ${primaryNum}?`); if(prompts.length>=5) break } }
  else if(effectiveCats.length>0){ const firstCat=effectiveCats[0].name; prompts.push(`Top 5 ${pluralize(firstCat)} by count`); if(effectiveCats.length>1) prompts.push(`Distribution of ${effectiveCats[1].name}`)}
  if(numericCols.length>0){ const distCandidate=primaryNum||numericCols[0].name; if(!prompts.some(p=>p.toLowerCase().includes("distribution"))) prompts.push(`${cap(distCandidate)} distribution`)}
  if(datetimeCols.length>0 && primaryNum) prompts.push(`Trend of ${primaryNum} over time`)
  prompts.push("Missing values"); prompts.push("Explain this dataset")

  // Mix type-specific + generic
  let full: string[] = []
  if(useTypeAware){
    const genericNeeded = 2
    full = [...typeSpecific, ...prompts.slice(0, genericNeeded)]
    // fill remaining generic if needed to reach at least 12 for rotation
    const remainingGeneric = prompts.slice(genericNeeded)
    full = [...full, ...remainingGeneric]
  } else {
    full = prompts
  }

  // Deduplication: exact + semantic (same verb + same column)
  const seenExact=new Set<string>()
  const semanticKeys=new Set<string>()
  const uniq:string[]=[]
  const verbOf=(p:string)=>{
    const lower=p.toLowerCase()
    if(/highest|lowest|ranking|compare|vs/.test(lower)) return 'compare'
    if(/trend|over time|month|week|daily/.test(lower)) return 'trend'
    if(/outlier|anomaly|unusual|spike/.test(lower)) return 'outlier'
    if(/distribution|spread|range|histogram/.test(lower)) return 'distribution'
    if(/correlation|relationship|impact|affect/.test(lower)) return 'correlation'
    const m=lower.match(/\b(highest|lowest|trend|compare|distribution|correlation|outlier)\b/)
    return m?m[1]: lower.split(' ').slice(0,2).join(' ')
  }
  const colOf=(p:string)=>{
    // extract column name mentioned: look for words that match column names
    if(!columns) return ''
    const lower=p.toLowerCase()
    for(const c of columns){
      if(lower.includes(c.name.toLowerCase())) return c.name.toLowerCase()
    }
    return ''
  }
  for(const p of full){
    const low=p.toLowerCase()
    if(seenExact.has(low)) continue
    seenExact.add(low)
    const key=verbOf(p)+'|'+colOf(p)
    if(semanticKeys.has(key) && colOf(p)) continue
    semanticKeys.add(key)
    uniq.push(p)
  }
  return uniq
}

export function getPromptCategory(prompt: string): { label: string; emoji: string } {
  const l=prompt.toLowerCase()
  if(/trend|over time|month|week|daily/.test(l)) return { label: 'Trend', emoji: '📈' }
  if(/compare|vs|highest|lowest|ranking/.test(l)) return { label: 'Compare', emoji: '🔍' }
  if(/outlier|anomaly|unusual|spike/.test(l)) return { label: 'Outlier', emoji: '⚠️' }
  if(/distribution|spread|range|histogram/.test(l)) return { label: 'Distribution', emoji: '📊' }
  if(/correlation|relationship|impact|affect/.test(l)) return { label: 'Correlation', emoji: '🔗' }
  return { label: 'Compare', emoji: '🔍' }
}

// Provider Badge — small, subtle, dismissible
function ProviderBadge({ meta }: { meta: any }){
  const [dismissed, setDismissed] = useState(false)
  if(!meta || dismissed) return null
  const isFallback = !!meta.is_fallback
  const providerRaw = (meta.provider || '').toLowerCase()
  const providerLabel = providerRaw === 'deterministic' ? 'Heuristic' : providerRaw.charAt(0).toUpperCase() + providerRaw.slice(1)
  const modelLabel = meta.model && meta.model !== 'deterministic' ? ` • ${meta.model}` : ''
  const green = !isFallback
  const tooltip = meta.fallback_reason ? String(meta.fallback_reason) : (green ? `Powered by ${providerLabel}${modelLabel}` : 'LLM unavailable — using deterministic heuristic')
  return (
    <div
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors ${green ? 'bg-emerald-50 border-emerald-200 text-emerald-700 dark:bg-emerald-500/10 dark:border-emerald-500/20 dark:text-emerald-300' : 'bg-amber-50 border-amber-200 text-amber-700 dark:bg-amber-500/10 dark:border-amber-500/20 dark:text-amber-300'}`}
      title={tooltip}
      role="status"
      aria-label={tooltip}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${green ? 'bg-emerald-500' : 'bg-amber-500'}`} />
      {green ? `✓ Powered by ${providerLabel}${modelLabel}` : `⚡ Heuristic Mode — LLM unavailable`}
      <button
        onClick={()=>setDismissed(true)}
        className="ml-1 rounded-full hover:bg-black/5 dark:hover:bg-white/10 p-0.5 leading-none"
        aria-label="Dismiss badge"
        title="Dismiss"
      >
        <span className="text-[12px] leading-none">×</span>
      </button>
    </div>
  )
}

import { ErrorCard } from '@/components/common/ErrorCard'
import { HelpTooltip } from '@/components/common/HelpTooltip'

export default function Copilot(){
  const { id } = useParams()
  const [question,setQuestion]=useState('')
  const [sessionId,setSessionId]=useState<string|undefined>(undefined)
  const [messages,setMessages]=useState<any[]>([])
  const [loading,setLoading]=useState(false)
  const [errorMsg, setErrorMsg]=useState<{msg:string; detail?:string} | null>(null)
  const { data: dataset } = useQuery({ queryKey:['ds',id], queryFn: async()=> (await api.get(`/api/datasets/${id}`)).data })
  const { data: profile } = useQuery({ queryKey:['profile',id], queryFn: async()=> (await api.get(`/api/datasets/${id}/profile`)).data, enabled: !!id })
  const { data: datasetType } = useQuery({ queryKey:['type',id], queryFn: async()=> (await api.get(`/api/datasets/${id}/type`)).data, enabled: !!id })
  const { data: aiStatus } = useQuery({ queryKey:['ai-status'], queryFn: async()=> (await api.get('/api/ai/status')).data, refetchOnWindowFocus: true, staleTime: 0 })
  const [lastProviderMeta, setLastProviderMeta] = useState<any>(null)
  // Per-message provider metadata map (messageId -> provider_metadata)
  const [msgProviderMeta, setMsgProviderMeta] = useState<Record<string, any>>({})
  const fullPrompts = useMemo(() => generateQuickPrompts(profile?.columns, datasetType?.dataset_type, datasetType?.confidence), [profile, datasetType])
  const [promptOffset, setPromptOffset] = useState(0)
  const quickPrompts = useMemo(() => {
    if (fullPrompts.length <= 6) return fullPrompts
    return Array.from({ length: 6 }, (_, i) => fullPrompts[(promptOffset + i) % fullPrompts.length])
  }, [fullPrompts, promptOffset])
  const qc = useQueryClient()
  const [reportMsg, setReportMsg] = useState<string|null>(null)
  // Use per-request actual provider if available, else fall back to global status (avoids stale cache)
  const effectiveProvider = lastProviderMeta?.ai_provider || (aiStatus as any)?.provider || 'mock'
  const effectiveMode = lastProviderMeta?.ai_mode || (aiStatus as any)?.mode || 'Deterministic Analysis'
  const isDeterministic = effectiveMode.toLowerCase().includes('deterministic') || effectiveProvider === 'deterministic' || effectiveProvider === 'mock'
  // Metrics for metric-aware copilot
  const { data: metrics } = useQuery({ queryKey:['metrics',id], queryFn: async()=> (await api.get(`/api/datasets/${id}/metrics`)).data, enabled: !!id })
  // Ambiguity / Plan state
  const [clarifications, setClarifications] = useState<any[]|null>(null)
  const [pendingQuestion, setPendingQuestion] = useState<string|null>(null)
  const [analysisPlan, setAnalysisPlan] = useState<any[]|null>(null)
  const [metricHint, setMetricHint] = useState<{name:string, sql:string}|null>(null)
  const [drillFilters, setDrillFilters] = useState<Record<string, { column: string; value: any; rows: any[] }>>({})
  const [msgTrustScores, setMsgTrustScores] = useState<Record<string, number>>({})
  const [viewMode, setViewMode] = useState<'analyst'|'executive'>(()=>{
    if(typeof window==='undefined') return 'analyst'
    return (localStorage.getItem(`odc-view-mode-${id}`) as any) || 'analyst'
  })
  const [analysisShareUrl, setAnalysisShareUrl] = useState('')
  const [analysisShareCopied, setAnalysisShareCopied] = useState(false)
  const [showAnalysisShareModal, setShowAnalysisShareModal] = useState(false)
  const [insightCopied, setInsightCopied] = useState<string|null>(null)
  useEffect(()=>{
    const key = `odc-view-mode-${id}`
    const check = () => {
      const v = localStorage.getItem(key) as any
      if(v && (v==='analyst'||v==='executive')) setViewMode(v)
    }
    check()
    window.addEventListener('storage', check)
    window.addEventListener('focus', check)
    const iv = setInterval(check, 1000)
    return ()=>{ window.removeEventListener('storage', check); window.removeEventListener('focus', check); clearInterval(iv)}
  },[id])

  // Composer auto-grow refs and helpers
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const messagesContainerRef = useRef<HTMLDivElement>(null)
  const autoResize = (el: HTMLTextAreaElement | null) => {
    if(!el) return
    el.style.height = '48px'
    el.style.height = 'auto'
    const max = 160
    const newH = Math.min(el.scrollHeight, max)
    el.style.height = newH + 'px'
    el.style.overflowY = el.scrollHeight > max ? 'auto' : 'hidden'
  }
  useEffect(()=>{ autoResize(textareaRef.current) },[question])
  useEffect(()=>{
    // Ensure latest assistant response is not covered: scroll messages container to bottom when messages change
    if(messagesContainerRef.current){
      const el = messagesContainerRef.current
      el.scrollTop = el.scrollHeight
    }
  },[messages, loading])

  // Fetch trust scores for MiniLineage (reuse same payload as TrustInline)
  useEffect(()=>{
    messages.filter(m=> m.role!=='user' && !msgTrustScores[m.id]).forEach(m=>{
      const coverage = (m.results || []).find((r:any)=> r.result_type === 'question_coverage')?.result_data
      const payload:any = {query_result:{success: m.execution_status==='success' || m.execution_status==='partial'}}
      if(coverage) payload.question_coverage = coverage
      const topCoverage = (m as any).question_coverage
      if(topCoverage && !payload.question_coverage) payload.question_coverage = topCoverage
      const stat = (m.results || []).find((r:any)=> r.result_type === 'statistical_validation')?.result_data
      if(stat) payload.statistical_validation = stat
      const assumptions = (m.results || []).find((r:any)=> r.result_type === 'assumptions')?.result_data
      if(assumptions) payload.assumptions = assumptions.limitations || assumptions
      if(!id) return
      api.post(`/api/datasets/${id}/trust-score`, payload).then(r=>{
        if(r.data?.score != null) setMsgTrustScores(prev=> ({...prev, [m.id]: r.data.score}))
      }).catch(()=>{})
    })
  },[messages, id, msgTrustScores])

  const doAnalyze = async (q:string)=>{
    setLoading(true)
    setErrorMsg(null)
    try{
      // Heavy audits (data-quality) can take >30s; give the pipeline up to 90s before axios aborts
      const res=await api.post(`/api/datasets/${id}/analyze`, { question: q, session_id: sessionId }, { timeout: 90000 })
      setSessionId(res.data.session_id)
      // TASK 3: read provider_metadata from API response
      const pm = res.data.provider_metadata || (res.data.ai_provider ? { provider: res.data.ai_provider, model: res.data.ai_model, mode: res.data.ai_mode, is_fallback: res.data.is_fallback, fallback_reason: res.data.fallback_reason } : null)
      if(pm){
        setLastProviderMeta(pm)
        // store per-message meta for badge below that specific message
        const mid = res.data.message?.id
        if(mid) setMsgProviderMeta(prev => ({...prev, [mid]: pm}))
      }
      const sess=await api.get(`/api/analysis/${res.data.session_id}`)
      // Enrich messages with stored provider_metadata if available (do not overwrite provenance)
      const enriched = (sess.data.messages || []).map((mm:any) => {
        if(msgProviderMeta[mm.id]) return {...mm, _providerMeta: msgProviderMeta[mm.id]}
        if(mm.id === res.data.message?.id && pm) return {...mm, _providerMeta: pm}
        return mm
      })
      // Also handle case where sess messages are already up-to-date but new message meta not in map yet
      setMessages(enriched.length ? enriched : sess.data.messages)
      setQuestion('')
      setClarifications(null)
      setAnalysisPlan(null)
      setPendingQuestion(null)
      setMetricHint(null)
      requestAnimationFrame(()=>{
        if(textareaRef.current){
          textareaRef.current.style.height = '48px'
          textareaRef.current.style.overflowY = 'hidden'
        }
      })
    }catch(e:any){
      const isTimeout = e.code === 'ECONNABORTED' || String(e.message || '').toLowerCase().includes('timeout')
      const detail = e.response?.data?.detail || e.message || 'Unknown error'
      const msg = typeof detail === 'object' ? JSON.stringify(detail) : String(detail)
      let friendly = msg
      if(isTimeout){
        friendly = 'Analysis is taking longer than expected (timeout). Your dataset may be large or the AI service is slow. Please click Retry — the request now allows up to 90s. If it persists, try a smaller sample or check the backend logs.'
      } else if(String(msg).includes('500')){
        friendly = 'Something went wrong while analysing your dataset. Please try again.'
      }
      setErrorMsg({msg: friendly, detail: typeof detail === 'string' ? detail : JSON.stringify(detail)})
    }finally{setLoading(false)}
  }

  const ask=async()=>{
    if(!question.trim() || loading) return
    const q = question.trim()
    setErrorMsg(null)
    // Metric hint: check if question mentions a saved metric
    if(metrics && Array.isArray(metrics)){
      const lower = q.toLowerCase()
      const matched = (metrics as any[]).find((m:any)=> lower.includes(m.name.toLowerCase()))
      if(matched){
        setMetricHint({name: matched.name, sql: matched.sql_expression})
      } else {
        setMetricHint(null)
      }
    }
    // Ambiguity check
    try{
      const clarRes = await api.post(`/api/datasets/${id}/clarify`, {question: q})
      if(clarRes.data.needs_clarification && clarRes.data.clarifications?.length){
        setClarifications(clarRes.data.clarifications)
        setPendingQuestion(q)
        return
      }
    }catch(_e){ /* ignore, proceed */ }
    // Plan check for complex questions
    try{
      const planRes = await api.post(`/api/datasets/${id}/plan`, {question: q})
      if(planRes.data.needs_plan && planRes.data.plan?.length){
        setAnalysisPlan(planRes.data.plan)
        setPendingQuestion(q)
        return
      }
    }catch(_e){ /* ignore */ }
    await doAnalyze(q)
  }

  const handleClarificationSelect = async (opt:string, _clarification:any)=>{
    setClarifications(null)
    // Include selected clarification value in the question so backend can use it (e.g., metric choice)
    const base = pendingQuestion || question
    const enriched = base && opt ? `${base} [Selected: ${opt}]` : base
    await doAnalyze(enriched || base)
  }

  const handleRunPlan = async ()=>{
    if(!pendingQuestion) return
    const q = pendingQuestion
    setAnalysisPlan(null)
    await doAnalyze(q)
  }

  const handleDrillDown = async (msg:any, chart:any, value:any, column:string) => {
    const chartId = chart.id || `${msg.id}-${chart.chart_type}`
    // Try server filtered evidence first
    let filtered: any[] = []
    try {
      const res = await api.get(`/api/datasets/${id}/evidence/${msg.id}`, { params: { filter_col: column, filter_val: value } })
      if (res.data?.rows) filtered = res.data.rows
      else if (Array.isArray(res.data)) filtered = res.data
    } catch (_e) {
      // fallback to client-side filter on existing evidence
    }
    if (filtered.length === 0) {
      // client-side fallback: filter existing table result rows
      const tableRes = msg.results?.find((r:any)=> r.result_type==='table' && r.result_data?.rows)
      const rows = tableRes?.result_data?.rows || []
      if (rows.length > 0) {
        filtered = rows.filter((row:any)=> String(row[column]) === String(value) || String(row[Object.keys(row)[0]]) === String(value))
      } else {
        // fallback: filter chart data itself
        const chartRows = chart.configuration?.data || []
        filtered = chartRows.filter((row:any)=> String(row[column]) === String(value))
      }
    }
    setDrillFilters(prev => ({ ...prev, [chartId]: { column, value, rows: filtered } }))
  }

  const clearDrill = (chartId: string) => {
    setDrillFilters(prev => {
      const copy = { ...prev }
      delete copy[chartId]
      return copy
    })
  }

  return (
    <div className="flex h-[calc(100vh-96px)] gap-4">
      {/* Left rail */}
      <div className="w-[300px] hidden lg:flex flex-col gap-4 shrink-0">
        <Card className="overflow-hidden">
          <div className="h-1 bg-gradient-to-r from-[#6d6af0] to-[#38bdf8]" />
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2"><Database className="h-4 w-4" /> Dataset</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="rounded-[12px] border bg-slate-50 dark:bg-white/5 dark:border-white/10 p-3">
              <div className="text-sm font-semibold truncate">{dataset?.name || 'Loading…'}</div>
              <div className="text-xs text-slate-600 dark:text-white/60 mt-1">{dataset?.row_count ?? '—'} rows • {dataset?.column_count ?? '—'} cols</div>
              {profile && <div className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-white border px-2.5 py-1 text-xs dark:bg-white/5 dark:border-white/10"><Gauge className="h-3 w-3" /> Quality {profile.quality_details?.score ?? dataset?.quality_score}/100</div>}
            </div>
            <div className="flex gap-1.5 text-[11px]">
              <span className="rounded-full border bg-white px-2 py-1 dark:bg-white/5 dark:border-white/10">DuckDB</span>
              <span className="rounded-full border bg-white px-2 py-1 dark:bg-white/5 dark:border-white/10">Provenance</span>
              <span className="rounded-full bg-emerald-500 text-white px-2 py-1">Live</span>
            </div>
          </CardContent>
        </Card>

        <Card className="flex-1 flex flex-col overflow-hidden">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm flex items-center gap-2"><Sparkles className="h-4 w-4 text-[#6d6af0]" /> Quick Prompts</CardTitle>
              <button onClick={() => setPromptOffset(prev => (prev + 6) % (fullPrompts.length || 6))} className="h-7 w-7 inline-flex items-center justify-center rounded-full border bg-white hover:bg-slate-50 dark:bg-white/5 dark:border-white/10" title="Refresh prompts" aria-label="Refresh prompts">
                <RotateCw className="h-3.5 w-3.5" />
              </button>
            </div>
            <p className="text-xs text-slate-500">Schema-aware • {datasetType?.dataset_type || 'generic'} • tap to fill</p>
          </CardHeader>
          <CardContent className="space-y-2 overflow-auto">
            {quickPrompts.map(p=>{
              const cat = getPromptCategory(p)
              return (
              <button key={p} onClick={()=>setQuestion(p)} className="text-xs text-left rounded-[12px] border bg-white px-3 py-2.5 w-full hover:bg-slate-50 hover:border-slate-300 dark:bg-white/5 dark:border-white/10 dark:hover:bg-white/10 text-slate-800 dark:text-white/80 leading-relaxed transition-colors flex items-center gap-2">
                <span className="text-[11px] shrink-0" title={cat.label}>{cat.emoji}</span>
                <span className="flex-1">
                  <span className="inline-flex items-center gap-1 text-[10px] font-medium text-slate-500 dark:text-white/50 mb-0.5">{cat.label}</span>
                  <span className="block">{p}</span>
                </span>
                <Search className="h-3 w-3 shrink-0 opacity-40" />
              </button>
              )
            })}
            <div className="rounded-[12px] border bg-gradient-to-br from-[#0b0d18] to-[#1a1d2e] text-white p-3 dark:border-white/10 mt-2">
              <div className="text-xs font-medium flex items-center gap-1.5"><Brain className="h-3.5 w-3.5" /> Analyst Tip</div>
              <div className="text-[11px] opacity-80 mt-1 leading-relaxed">Try “Why did this happen?” after any insight to challenge & verify.</div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Analytics Workspace */}
      <div className="flex-1 flex flex-col rounded-[20px] border bg-white dark:bg-[#0f1220] dark:border-white/10 overflow-hidden elev-2">
        <div className="h-[56px] flex items-center justify-between px-4 border-b dark:border-white/10 bg-white dark:bg-[#0f1220]">
          <div className="flex items-center gap-3">
            <div className="h-8 w-8 rounded-full bg-[#0b0d18] dark:bg-white grid place-items-center"><MessageSquare className="h-4 w-4 text-white dark:text-[#0b0d18]" /></div>
            <div>
              <div className="text-sm font-semibold leading-none">AI Analytics Workspace</div>
              <div className="text-xs text-slate-500 dark:text-white/50">{dataset?.name} • trusted • explainable</div>
            </div>
          </div>
          <div className="hidden md:flex items-center gap-2 text-xs">
            <span className={`rounded-full border px-2.5 py-1 flex items-center gap-1 ${isDeterministic?'bg-amber-50 border-amber-200 dark:bg-amber-500/10 dark:border-amber-500/20':'bg-emerald-50 border-emerald-200 dark:bg-emerald-500/10 dark:border-emerald-500/20'}`} title={effectiveMode}>
              {isDeterministic ? 'Deterministic Analysis' : `LLM-powered • ${effectiveProvider}`} 
              <HelpTooltip title={isDeterministic?'Deterministic • Verified':'LLM-powered'}>
                {isDeterministic 
                  ? 'Verified analysis — DuckDB is source of truth. SQL executed locally, numbers from actual data. LLM fallback silent, HTTP 200.' 
                  : `Using ${effectiveProvider} (${(aiStatus as any)?.model || lastProviderMeta?.ai_model || 'LLM'}) for explanation; SQL still executed deterministically via DuckDB with provenance. Only schema/sample sent.`}
              </HelpTooltip>
              {isDeterministic ? <span className="ml-1 text-[10px] opacity-70">Verified</span> : null}
            </span>
            <span className="rounded-full border bg-slate-50 px-2.5 py-1 dark:bg-white/5 dark:border-white/10 flex items-center gap-1"><ShieldCheck className="h-3 w-3 text-emerald-600" /> Trust Score</span>
            <span className="rounded-full border bg-slate-50 px-2.5 py-1 dark:bg-white/5 dark:border-white/10 flex items-center gap-1"><GitBranch className="h-3 w-3" /> Lineage</span>
            <button onClick={async()=>{
              if(!sessionId){ alert('Start a conversation first'); return }
              try{
                const res=await api.post(`/api/analysis/${sessionId}/share`, {expires_in_days:30})
                const url=res.data.share_url.replace('https://app', window.location.origin)
                setAnalysisShareUrl(url); setShowAnalysisShareModal(true)
              }catch(e:any){ alert(e.response?.data?.detail||e.message) }
            }} className="rounded-full border bg-white px-2.5 py-1 text-xs hover:bg-slate-50 dark:bg-white/5 dark:border-white/10 inline-flex items-center gap-1"><Share2 className="h-3 w-3" /> Share Analysis</button>
          </div>
        </div>
        {showAnalysisShareModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
            <div className="absolute inset-0 bg-black/40" onClick={()=>setShowAnalysisShareModal(false)} />
            <div className="relative w-full max-w-md rounded-[16px] bg-white dark:bg-[#0f1220] border dark:border-white/10 p-5 shadow-xl">
              <div className="flex justify-between items-center"><h3 className="font-semibold">Share Analysis</h3><button onClick={()=>setShowAnalysisShareModal(false)} className="h-8 w-8 grid place-items-center rounded-full border dark:border-white/10"><X className="h-4 w-4" /></button></div>
              <p className="text-xs text-slate-500 mt-1">Anyone with the link can view</p>
              <div className="mt-3 flex gap-2">
                <input value={analysisShareUrl} readOnly className="flex-1 h-9 rounded-full border px-3 text-xs dark:bg-white/5 dark:border-white/10" />
                <Button size="sm" onClick={async()=>{ await navigator.clipboard.writeText(analysisShareUrl); setAnalysisShareCopied(true); setTimeout(()=>setAnalysisShareCopied(false),2000)}}>{analysisShareCopied?'Copied!':'Copy Link'}</Button>
              </div>
            </div>
          </div>
        )}

        <div ref={messagesContainerRef} className="flex-1 overflow-auto p-4 lg:p-6 space-y-5 bg-[#fcfcfd] dark:bg-[#0a0c14] scroll-pb-4">
          {messages.length===0 && (
            <div className="max-w-[720px] mx-auto mt-6">
              <div className="rounded-[20px] border bg-white dark:bg-white/[0.04] dark:border-white/10 p-6 elev-1">
                <div className="inline-flex items-center gap-2 rounded-full border bg-slate-50 px-3 py-1 text-xs dark:bg-white/5 dark:border-white/10"><Sparkles className="h-3 w-3" /> Ask questions about your dataset</div>
                <h3 className="text-[18px] font-semibold mt-3">Ask anything about <span className="underline decoration-[#6d6af0]/30 underline-offset-4">{dataset?.name || 'your dataset'}</span></h3>
                <p className="text-sm text-slate-600 dark:text-white/60 mt-2 leading-relaxed">Example prompts — schema-aware, evidence-backed: Try “Which airline has the highest average price?” or “What are the top 5 routes by number of flights?” Every answer: <span className="font-medium text-slate-900 dark:text-white">Insight → Trust → Evidence → Chart → Table → Provenance → Methodology</span>.</p>
                <div className="mt-4 grid sm:grid-cols-2 gap-2">
                  {quickPrompts.slice(0,4).map(p=> (
                    <button key={p} onClick={()=>setQuestion(p)} className="text-left rounded-[12px] border bg-white px-3 py-2.5 hover:bg-slate-50 dark:bg-white/5 dark:border-white/10 text-xs leading-relaxed">{p}</button>
                  ))}
                </div>
                <div className="mt-3 text-[11px] text-slate-500 dark:text-white/40">More examples: Which source has the highest average price? Are there unusual price outliers? Show monthly price trends.</div>
                <div className="mt-4 flex gap-2 text-xs">
                  <span className="rounded-full bg-[#0b0d18] text-white dark:bg-white dark:text-[#0b0d18] px-3 py-1.5">Try: “{quickPrompts[0] || 'Which airline has the highest average price?'}”</span>
                  <span className="rounded-full border bg-white px-3 py-1.5 dark:bg-white/5 dark:border-white/10">⌘K for commands</span>
                </div>
              </div>

              <div className="grid md:grid-cols-3 gap-3 mt-4">
                {[
                  { title:'Evidence', desc:'SQL/Python + data quality', icon: FileCode },
                  { title:'Chart', desc:'Premium, export-ready', icon: BarChart3 },
                  { title:'Trust', desc:'Ring score + provenance', icon: ShieldCheck },
                ].map(c=>{
                  const Icon=c.icon
                  return <div key={c.title} className="rounded-[16px] border bg-white dark:bg-white/[0.04] dark:border-white/10 p-4"><Icon className="h-4 w-4 opacity-60" /><div className="font-medium text-sm mt-2">{c.title}</div><div className="text-xs text-slate-500 dark:text-white/50">{c.desc}</div></div>
                })}
              </div>
            </div>
          )}

          {messages.map((m:any)=>(
            <div key={m.id} className={`max-w-[820px] w-full ${m.role==='user'?'ml-auto':''}`}>
              {m.role==='user' ? (
                <div className="ml-auto max-w-[640px] rounded-[20px] bg-[#0b0d18] text-white dark:bg-white dark:text-[#0b0d18] px-5 py-3.5 shadow-sm">
                  <div className="text-[11px] opacity-60 mb-1">You • {new Date(m.created_at).toLocaleTimeString()}</div>
                  <div className="text-[14px] leading-relaxed">{m.content}</div>
                </div>
              ) : (
                <div className="rounded-[20px] border bg-white dark:bg-[#0f1220] dark:border-white/10 overflow-hidden elev-1">
                  {/* MiniLineage breadcrumb */}
                  <div className="px-5 pt-3">
                    {(() => {
                      const rowCount = (m.results?.find((r:any)=> r.result_type==='table')?.result_data?.rows?.length) ?? (m.results?.find((r:any)=> r.result_data?.rows)?.result_data?.rows?.length) ?? (m.charts?.[0]?.configuration?.data?.length ?? null)
                      const hasChart = (m.charts?.length ?? 0) > 0
                      const hasSql = !!m.generated_code
                      const trustScore = msgTrustScores[m.id] ?? null
                      const version = (dataset as any)?.current_version ? `v${(dataset as any).current_version}` : (dataset as any)?.version_number ? `v${(dataset as any).version_number}` : 'v1'
                      const dsName = dataset?.name || profile?.dataset?.name || 'Dataset'
                      return (
                        <MiniLineage
                          datasetName={dsName}
                          version={version}
                          rowCount={rowCount}
                          hasChart={hasChart}
                          hasSql={hasSql}
                          trustScore={trustScore}
                          onStepClick={(step)=>{
                            const el = document.getElementById(`step-${m.id}-${step}`)
                            if(el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
                            if(el) el.classList.add('ring-2','ring-[#6d6af0]','rounded-[12px]')
                            setTimeout(()=> el?.classList.remove('ring-2','ring-[#6d6af0]'), 1200)
                          }}
                        />
                      )
                    })()}
                  </div>
                  {viewMode==='executive' && (
                    <div className="mx-5 mt-2 rounded-full bg-amber-50 border border-amber-200 px-3 py-1 text-xs text-amber-700 dark:bg-amber-500/10 dark:border-amber-500/20">
                      Executive view — Switch to Analyst for full details
                    </div>
                  )}
                  {/* Insight header */}
                  <div id={`step-${m.id}-insight`} className="px-5 py-4 border-b dark:border-white/10 bg-gradient-to-r from-white to-slate-50 dark:from-white/[0.04] dark:to-transparent">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <div className="inline-flex items-center gap-1.5 rounded-full bg-[#0b0d18] text-white dark:bg-white dark:text-[#0b0d18] px-2.5 py-1 text-[11px] font-medium"><Brain className="h-3 w-3" /> Insight</div>
                          <button onClick={async()=>{
                            const url=`${window.location.origin}/datasets/${id}/copilot?session=${sessionId}&msg=${m.id}`
                            await navigator.clipboard.writeText(url)
                            setInsightCopied(m.id)
                            setTimeout(()=>setInsightCopied(null),2000)
                          }} className="h-7 w-7 inline-flex items-center justify-center rounded-full border bg-white dark:bg-white/5 dark:border-white/10" title="Copy link to this insight"><LinkIcon className="h-3.5 w-3.5" /></button>
                          {insightCopied===m.id && <span className="text-xs text-emerald-600">Link copied — recipient needs access</span>}
                        </div>
                        {(() => {
                          const raw = m.content || ''
                          const splitIdx = raw.search(/Key takeaway:/i)
                          let summary = raw
                          let takeaway: string | null = null
                          if(splitIdx !== -1){
                            summary = raw.slice(0, splitIdx).trim()
                            takeaway = raw.slice(splitIdx).replace(/Key takeaway:\s*/i,'').trim()
                          }
                          return (
                            <>
                              <div className="mt-2 text-[14px] leading-relaxed whitespace-pre-wrap">{summary}</div>
                              {takeaway && (
                                <div className="mt-3 rounded-[12px] border bg-amber-50 dark:bg-amber-500/10 dark:border-amber-500/20 px-3 py-2.5">
                                  <div className="text-[11px] font-semibold tracking-wide text-amber-700 dark:text-amber-300">Key takeaway</div>
                                  <div className="text-[13px] font-medium text-slate-900 dark:text-white mt-1 leading-relaxed">{takeaway}</div>
                                </div>
                              )}
                            </>
                          )
                        })()}
                        <div className="mt-2 text-[11px] text-slate-500 flex items-center gap-2"><span className={`h-1.5 w-1.5 rounded-full ${m.execution_status==='partial'?'bg-amber-500':'bg-emerald-500'}`} /> {m.execution_status==='partial'?'Partially Verified': 'Verified'} • {new Date(m.created_at).toLocaleTimeString()}</div>
                      </div>
                      {(m.execution_status==='success' || m.execution_status==='partial') && <TrustInline datasetId={id!} message={m} />}
                    </div>
                    {/* TASK 3: Provider Badge below insight header — subtle, per-message, dismissible, tooltip = fallback_reason */}
                    <div className="px-5 pb-2">
                      <ProviderBadge meta={(m as any)._providerMeta || msgProviderMeta[m.id] || (m.id === messages[messages.length-1]?.id ? lastProviderMeta : null)} />
                    </div>
                  </div>

                    {(() => {
                      const coverage = m.results?.find((r:any)=> r.result_type==='question_coverage')?.result_data
                      const isPartial = m.execution_status==='partial' || (coverage && coverage.missing_components && coverage.missing_components.length>0)
                      const isComplete = (m.execution_status==='success' || m.execution_status==='partial') && coverage && coverage.missing_components.length===0
                      if(isPartial){
                        return <div className="mx-4 mt-3 rounded-[12px] border bg-amber-50 dark:bg-amber-500/10 dark:border-amber-500/20 p-3 text-xs"><div className="font-semibold">Partially Completed Analysis — {coverage ? `${Math.round(coverage.coverage_ratio*100)}% coverage` : 'partial'}</div><div className="mt-1 text-slate-600 dark:text-white/60">Requested: {coverage?.requested_components?.join(', ')} | Completed: {coverage?.completed_components?.join(', ')} | Missing: {coverage?.missing_components?.join(', ') || 'none'}</div><div className="text-[11px] text-amber-700 dark:text-amber-300 mt-1">Some requested components were not executable with current data. Available drivers and MoM remain valid where applicable.</div></div>
                      }
                      if(isComplete){
                        return <div className="mx-4 mt-3 rounded-[12px] border bg-emerald-50 dark:bg-emerald-500/10 dark:border-emerald-500/20 p-2 text-xs flex items-center gap-1"><ShieldCheck className="h-3 w-3 text-emerald-600" />Complete analysis — all {coverage.requested_components.length} requested components executed.</div>
                      }
                      return null
                    })()}
                    {/* Connected cards */}
                    <div className="p-4 space-y-3 bg-[#fcfcfd] dark:bg-[#0a0c14]">
                    {viewMode !== 'executive' && (() => {
                      const isDataQualityAudit = m.results?.some((r:any) => r.result_type === 'data_quality' || r.result_type === 'analysis_meta' && r.result_data?.analysis_mode === 'data_quality_audit')
                      // For pure data_quality audit, do NOT render generic SQL cards when no SQL was executed
                      if (isDataQualityAudit && !m.generated_code) return null
                      return (
                        <div id={`step-${m.id}-sql`} className="rounded-[16px] border bg-white dark:bg-white/[0.04] dark:border-white/10 overflow-hidden">
                          <div className="flex items-center justify-between px-4 h-9 border-b dark:border-white/10 bg-slate-50 dark:bg-white/5">
                            <span className="text-xs font-semibold tracking-wide flex items-center gap-1.5"><FileCode className="h-3.5 w-3.5" /> QUERY • {m.execution_status.toUpperCase()}</span>
                            <span className="text-[11px] rounded-full bg-emerald-500 text-white px-2 py-0.5">DuckDB • Executed SQL</span>
                          </div>
                          <details className="group" open={!!m.generated_code}>
                            <summary className="px-4 py-2 text-xs cursor-pointer text-slate-600 dark:text-white/60 hover:text-slate-900">Show code — Executed SQL (from backend)</summary>
                            {/* Render actual executed SQL returned by backend (m.generated_code) — do not regenerate in frontend */}
                            {m.generated_code ? (
                              <pre className="mx-3 mb-3 bg-[#0b0d18] dark:bg-black text-slate-100 p-3 rounded-[12px] text-xs overflow-auto border border-white/10 leading-relaxed">{m.generated_code}</pre>
                            ) : (
                              <div className="mx-3 mb-3 bg-[#0b0d18] dark:bg-black text-slate-100 p-3 rounded-[12px] text-xs border border-white/10">SQL unavailable for this analysis</div>
                            )}
                          </details>
                        </div>
                      )
                    })()}

                    {m.results?.map((r:any)=>(
                      <div key={r.id}>
                        {viewMode !== 'executive' && r.result_type==='mom_analysis' && (
                          <div className="rounded-[16px] border bg-white dark:bg-white/[0.04] dark:border-white/10 overflow-hidden">
                            <div className="px-4 h-9 flex items-center border-b dark:border-white/10 bg-slate-50 dark:bg-white/5"><span className="text-xs font-semibold tracking-wide">MOM • {r.result_data.has_mom ? `${r.result_data.mom_rows.length} intervals` : 'Unavailable'}</span></div>
                            <div className="p-3 text-xs space-y-2">
                              {r.result_data.has_mom ? (
                                <>
                                  <div className="grid grid-cols-1 gap-1"><div><span className="font-medium">Strongest:</span> {Object.entries(r.result_data.strongest || {}).map(([k,v]:any)=> `${k} peak ${v.month} (${v.value})`).join(' | ')}</div><div><span className="font-medium">Weakest:</span> {Object.entries(r.result_data.weakest || {}).map(([k,v]:any)=> `${k} trough ${v.month} (${v.value})`).join(' | ')}</div></div>
                                  <div><span className="font-medium">Latest vs previous:</span> {Object.entries(r.result_data.latest_change || {}).map(([k,v]:any)=> v ? `${k} ${v.prev_month}→${v.latest_month} ${v.change} (${v.change_pct!==null?`${v.change_pct}%`:''})` : '').join(' | ')}</div>
                                  <div className="overflow-auto max-h-[200px] border rounded-[8px]"><table className="min-w-full text-[11px]"><thead className="bg-slate-50 dark:bg-white/5"><tr>{Object.keys(r.result_data.mom_rows[0] || {}).map((k:string)=><th key={k} className="px-2 py-1 text-left border-b dark:border-white/10 whitespace-nowrap">{k}</th>)}</tr></thead><tbody>{r.result_data.mom_rows.map((row:any,i:number)=><tr key={i} className={i%2===0?"bg-white dark:bg-transparent":"bg-slate-50 dark:bg-white/[0.03] border-t dark:border-white/10"}>{Object.values(row).map((v:any,j:number)=><td key={j} className="px-2 py-1 whitespace-nowrap">{v===null||v===''?'—':String(v)}</td>)}</tr>)}</tbody></table></div>
                                </>
                              ) : <div className="text-amber-700 dark:text-amber-300">{r.result_data.reason}</div>}
                            </div>
                          </div>
                        )}
                        {viewMode !== 'executive' && r.result_type==='driver_analysis' && (
                          <div className="rounded-[16px] border bg-white dark:bg-white/[0.04] dark:border-white/10 overflow-hidden">
                            <div className="px-4 h-9 flex items-center border-b dark:border-white/10 bg-slate-50 dark:bg-white/5"><span className="text-xs font-semibold tracking-wide">DRIVER • {r.result_data.driver_column} → {r.result_data.metric}</span><span className="ml-2 text-[11px] text-slate-500">{r.result_data.latest_month} vs {r.result_data.prev_month}</span></div>
                            <div className="p-3 text-xs space-y-1">
                              {r.result_data.error ? <div className="text-amber-700 dark:text-amber-300">{r.result_data.error}</div> : (
                                <>
                                  <div className="text-[11px] text-slate-500">Ranked by contribution — association, not causation</div>
                                  <div className="overflow-auto max-h-[200px] border rounded-[8px]"><table className="min-w-full text-[11px]"><thead className="bg-slate-50 dark:bg-white/5"><tr><th className="px-2 py-1 text-left border-b dark:border-white/10">Driver</th><th className="px-2 py-1 text-right border-b dark:border-white/10">Prev</th><th className="px-2 py-1 text-right border-b dark:border-white/10">Curr</th><th className="px-2 py-1 text-right border-b dark:border-white/10">Change</th><th className="px-2 py-1 text-right border-b dark:border-white/10">Contrib</th></tr></thead><tbody>{(r.result_data.drivers||[]).slice(0,10).map((d:any,i:number)=><tr key={i} className="border-t dark:border-white/10"><td className="px-2 py-1">{d.driver_value}</td><td className="px-2 py-1 text-right">{d.prev_value ?? d.prev_avg ?? ''}</td><td className="px-2 py-1 text-right">{d.curr_value ?? d.curr_avg ?? ''}</td><td className="px-2 py-1 text-right">{d.change}</td><td className="px-2 py-1 text-right">{d.contribution_pct ?? d.change_pct ?? ''}</td></tr>)}</tbody></table></div>
                                </>
                              )}
                            </div>
                          </div>
                        )}
                        {viewMode !== 'executive' && r.result_type==='question_coverage' && (
                          <div className="rounded-[12px] border bg-slate-50 dark:bg-white/5 dark:border-white/10 p-3 text-xs">
                            <div className="font-semibold">Question Coverage — {r.result_data.analysis_completeness} ({Math.round(r.result_data.coverage_ratio*100)}%)</div>
                            <div className="mt-1">Requested: {r.result_data.requested_components.join(', ')}</div>
                            <div>Completed: {r.result_data.completed_components.join(', ')}</div>
                            {r.result_data.missing_components.length>0 && <div className="text-amber-700 dark:text-amber-300">Missing: {r.result_data.missing_components.join(', ')}</div>}
                          </div>
                        )}
                        {viewMode !== 'executive' && r.result_type==='table' && r.result_data?.rows && r.result_data.rows.length>0 && (
                          <div className="rounded-[16px] border bg-white dark:bg-white/[0.04] dark:border-white/10 overflow-hidden">
                            <div className="px-4 h-9 flex items-center justify-between border-b dark:border-white/10 bg-slate-50 dark:bg-white/5">
                              <span className="text-xs font-semibold tracking-wide flex items-center gap-1.5"><Database className="h-3.5 w-3.5" /> EVIDENCE • {r.result_data.rows.length} rows</span>
                              <span className="text-[11px] text-slate-500">{r.result_data.columns?.length} cols</span>
                            </div>
                            <div className="overflow-auto max-h-[260px]">
                              <table className="min-w-full text-xs">
                                <thead className="bg-slate-50 dark:bg-white/5 sticky top-0"><tr>{r.result_data.columns?.map((c:string)=><th key={c} className="px-3 py-2 text-left font-semibold whitespace-nowrap border-b dark:border-white/10">{c}</th>)}</tr></thead>
                                <tbody className="divide-y dark:divide-white/10">{r.result_data.rows.slice(0,20).map((row:any,i:number)=><tr key={i} className={i%2===0?"bg-white dark:bg-transparent":"bg-slate-50 dark:bg-white/[0.03]"}>{r.result_data.columns.map((c:string)=><td key={c} className="px-3 py-1.5 whitespace-nowrap">{row[c]===null || row[c]===''?'—':String(row[c])}</td>)}</tr>)}</tbody>
                              </table>
                              {r.result_data.rows.length>20 && <div className="text-xs p-2 text-slate-500 bg-slate-50 dark:bg-white/5 border-t dark:border-white/10">Showing 20 of {r.result_data.rows.length} rows</div>}
                            </div>
                          </div>
                        )}
                        {r.result_type==='error' && <div className="rounded-[12px] border border-red-200 bg-red-50 text-red-700 p-3 text-sm dark:bg-red-500/10 dark:border-red-500/20 dark:text-red-300 flex gap-2"><AlertTriangle className="h-4 w-4 shrink-0" />{r.result_data.error}</div>}
                      </div>
                    ))}

                    {m.charts?.map((c:any)=>{
                      const chartId = c.id || `${m.id}-${c.chart_type}`
                      const drill = drillFilters[chartId]
                      const isBarOrPie = c.chart_type === 'bar' || c.chart_type === 'pie'
                      return (
                      <div key={c.id} className="rounded-[16px] border bg-white dark:bg-white/[0.04] dark:border-white/10 overflow-hidden">
                        <div className="px-4 h-9 flex items-center justify-between border-b dark:border-white/10 bg-slate-50 dark:bg-white/5">
                          <span className="text-xs font-semibold tracking-wide flex items-center gap-1.5"><BarChart3 className="h-3.5 w-3.5" /> CHART • {c.chart_type.toUpperCase()}</span>
                          <button onClick={()=>{
                            const dataStr=JSON.stringify(c.configuration.data,null,2); const blob=new Blob([dataStr],{type:'application/json'}); const url=URL.createObjectURL(blob); const a=document.createElement('a'); a.href=url; a.download='chart-data.json'; a.click(); URL.revokeObjectURL(url)
                          }} className="rounded-full border bg-white px-2.5 py-1 text-xs hover:bg-slate-50 dark:bg-white/5 dark:border-white/10">Download</button>
                        </div>
                        <div className="p-3 bg-white dark:bg-transparent">
                          <ChartRenderer chart={c} onDrillDown={isBarOrPie ? (val, col) => handleDrillDown(m, c, val, col) : undefined} />
                        </div>
                        {drill && (
                          <div className="mx-3 mb-3 rounded-[12px] border bg-slate-50 dark:bg-white/5 dark:border-white/10 p-3">
                            <div className="flex items-center justify-between">
                              <span className="text-xs font-medium">Showing rows where {drill.column} = {String(drill.value)} ({drill.rows.length} rows)</span>
                              <button onClick={() => clearDrill(chartId)} className="text-xs rounded-full border bg-white px-2 py-1 hover:bg-slate-50 dark:bg-white/5 dark:border-white/10">× Clear filter</button>
                            </div>
                            <div className="mt-2 overflow-auto max-h-[260px] rounded-[8px] border dark:border-white/10">
                              {drill.rows.length === 0 ? <div className="text-xs p-3 text-slate-500">No matching rows</div> : (
                                <table className="min-w-full text-xs">
                                  <thead className="bg-slate-50 dark:bg-white/5 sticky top-0"><tr>{Object.keys(drill.rows[0]||{}).map((col:string)=><th key={col} className="px-2 py-1 text-left whitespace-nowrap border-b dark:border-white/10">{col}</th>)}</tr></thead>
                                  <tbody className="divide-y dark:divide-white/10">{drill.rows.slice(0,20).map((row:any,i:number)=><tr key={i}>{Object.values(row).map((v:any,j:number)=><td key={j} className="px-2 py-1 whitespace-nowrap">{String(v)}</td>)}</tr>)}</tbody>
                                </table>
                              )}
                              {drill.rows.length > 20 && <div className="text-[11px] p-2 text-slate-500">Showing 20 of {drill.rows.length}</div>}
                            </div>
                          </div>
                        )}
                      </div>
                      )
                    })}

                    {/* connector */}
                    <div className="flex items-center justify-center gap-1.5 py-1 text-slate-300 dark:text-white/15">
                      <div className="h-px w-8 bg-current" /><span className="text-[10px] tracking-widest">PROVENANCE</span><div className="h-px w-8 bg-current" />
                    </div>

                    {viewMode !== 'executive' && (m.execution_status==='success' || m.execution_status==='partial') && <InsightEvidence datasetId={id!} message={m} />}
                    {(m.execution_status==='success' || m.execution_status==='partial') && (
                      <div className="px-4 pb-3 flex gap-2 border-t dark:border-white/10 bg-white dark:bg-[#0f1220] pt-3">
                        <Button size="sm" variant="outline" className="h-7 text-xs rounded-full" onClick={async()=>{
                          try{
                            const title = prompt('Report title', `Report — ${m.content.slice(0,40)}`) || `Report ${new Date().toLocaleDateString()}`
                            if(!title) return
                            await api.post('/api/reports/from-session', {dataset_id: id, session_id: sessionId, title})
                            qc.invalidateQueries({queryKey:['reports']})
                            setReportMsg('Report created — view in Reports Library')
                            setTimeout(()=>setReportMsg(null), 3000)
                          }catch(e:any){ alert(e.response?.data?.detail || e.message) }
                        }}><FileText className="h-3 w-3 mr-1" />Create Report</Button>
                        {reportMsg && <span className="text-xs text-emerald-600 py-1">{reportMsg}</span>}
                        <span className="text-[11px] text-slate-500 py-1">Persisted to Reports Library — will appear with dataset version</span>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}

          {metricHint && (
            <div className="max-w-[820px] rounded-[16px] border bg-blue-50 dark:bg-blue-500/10 dark:border-blue-500/20 p-3 text-xs">
              <div className="font-medium">I'll use your saved <span className="font-semibold">{metricHint.name}</span> metric: <code className="bg-white dark:bg-black px-1 py-0.5 rounded border dark:border-white/10">{metricHint.sql}</code></div>
              <div className="flex gap-2 mt-2">
                <Button size="sm" className="h-7 text-xs" onClick={()=>{ setMetricHint(null); doAnalyze(pendingQuestion||question) }}>Use this metric</Button>
                <Button size="sm" variant="outline" className="h-7 text-xs" onClick={()=>setMetricHint(null)}>Change definition</Button>
              </div>
            </div>
          )}
          {clarifications && (
            <div className="max-w-[820px] space-y-2">
              {clarifications.map((cl:any,idx:number)=>(
                <div key={idx} className="rounded-[16px] border bg-amber-50 dark:bg-amber-500/10 dark:border-amber-500/20 p-4">
                  <div className="text-sm font-semibold">{cl.question}</div>
                  <div className="text-xs text-slate-600 dark:text-white/60 mt-1">{cl.message}</div>
                  <div className="flex flex-wrap gap-2 mt-3">
                    {cl.options?.map((opt:any)=><Button key={opt.value} size="sm" variant="outline" className="rounded-full h-7 text-xs" disabled={loading} onClick={()=> handleClarificationSelect(opt.value, cl)}>{opt.label}</Button>)}
                    <Button size="sm" variant="outline" className="h-7 text-xs" disabled={loading} onClick={()=>{ setClarifications(null); doAnalyze(pendingQuestion||question) }}>Skip — Run Anyway</Button>
                  </div>
                </div>
              ))}
            </div>
          )}
          {analysisPlan && (
            <div className="max-w-[820px] rounded-[16px] border bg-white dark:bg-white/[0.04] dark:border-white/10 p-4">
              <div className="text-sm font-semibold flex items-center gap-2"><Brain className="h-4 w-4" /> Analysis Plan</div>
              <div className="text-xs text-slate-500 mt-1">I'll:</div>
              <ol className="mt-2 space-y-1 text-xs list-decimal list-inside">
                {analysisPlan.map((s:any)=><li key={s.step} className="leading-relaxed"><span className="font-medium">{s.title}</span> — <span className="text-slate-500">{s.detail}</span></li>)}
              </ol>
              <div className="flex gap-2 mt-3">
                {(() => {
                  const hasPreview = analysisPlan.some((s:any) => s.title.toLowerCase().includes("preview"))
                  const isAudit = analysisPlan.some((s:any) => s.title.toLowerCase().includes("no data will be modified")) || (!hasPreview && analysisPlan.some((s:any) => s.title.toLowerCase().includes("scan the dataset")))
                  return <Button size="sm" onClick={handleRunPlan}>{isAudit ? "Run Quality Audit" : "Run Analysis"}</Button>
                })()}
                <Button size="sm" variant="outline" onClick={()=>setAnalysisPlan(null)}>Edit Plan</Button>
              </div>
            </div>
          )}
          {errorMsg && <div className="max-w-[820px]"><ErrorCard title="Analysis failed" message={errorMsg.msg} detail={errorMsg.detail} onRetry={()=>{ setErrorMsg(null); ask()}} /></div>}
          {loading && (
            <div className="max-w-[820px] rounded-[16px] border bg-white dark:bg-white/[0.04] dark:border-white/10 p-4 flex items-center gap-3">
              <div className="h-8 w-8 rounded-full bg-[#0b0d18] dark:bg-white grid place-items-center animate-spin border-2 border-white/20 border-t-[#6d6af0]"><Sparkles className="h-4 w-4 text-white dark:text-[#0b0d18]" /></div>
              <div className="flex-1">
                <div className="text-sm font-medium">Generating analysis…</div>
                <div className="text-xs text-slate-500">Building SQL • Validating • Running DuckDB • Preparing chart</div>
              </div>
              <span className="text-xs rounded-full border px-3 py-1 dark:border-white/10 animate-pulse">Deterministic • No guesswork</span>
            </div>
          )}
        </div>

        {/* Composer */}
        <div className="p-3 border-t dark:border-white/10 bg-white dark:bg-[#0f1220]">
          <div className="flex gap-2 items-end max-w-[900px] mx-auto">
            <div className="flex-1 relative">
              <textarea
                ref={textareaRef}
                rows={1}
                placeholder={quickPrompts[0] ? `Ask: ${quickPrompts[0]}` : "Ask a question — e.g., 'Top 5 categories by revenue'"}
                value={question}
                onChange={(e:any)=>{ setQuestion(e.target.value); autoResize(e.target) }}
                onInput={(e:any)=> autoResize(e.target as HTMLTextAreaElement)}
                className="flex w-full min-h-[48px] max-h-[160px] rounded-[20px] border border-slate-200 bg-slate-50 px-4 py-3 pr-[96px] text-[13.5px] leading-relaxed placeholder:text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900/10 focus-visible:border-slate-300 transition-colors dark:border-white/10 dark:bg-white/[0.06] dark:text-white dark:placeholder:text-white/40 resize-none overflow-y-hidden"
                style={{ height: '48px' }}
                onKeyDown={(e:any)=>{ if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); ask() }}}
              />
              <span className="absolute right-3 bottom-3 text-[11px] text-slate-400 hidden sm:inline pointer-events-none">↵ send / ⇧↵ new line</span>
            </div>
            <Button onClick={ask} disabled={loading || !question.trim()} className="h-[48px] w-[48px] rounded-full p-0 shrink-0 self-end">
              <Send className="h-4 w-4" />
            </Button>
          </div>
          <div className="text-[11px] text-center text-slate-500 dark:text-white/40 mt-2">AI never fabricates — every answer is backed by SQL, evidence, and trust score.</div>
        </div>
      </div>
    </div>
  )
}

function TrustInline({ datasetId, message }: any){
  const [trust,setTrust]=useState<any>(null)
  useEffect(()=>{
    const coverage = (message.results || []).find((r:any)=> r.result_type === 'question_coverage')?.result_data
    const payload:any = {query_result:{success: message.execution_status==='success' || message.execution_status==='partial'}}
    if(coverage) payload.question_coverage = coverage
    const topCoverage = (message as any).question_coverage
    if(topCoverage && !payload.question_coverage) payload.question_coverage = topCoverage
    const stat = (message.results || []).find((r:any)=> r.result_type === 'statistical_validation')?.result_data
    if(stat) payload.statistical_validation = stat
    const assumptions = (message.results || []).find((r:any)=> r.result_type === 'assumptions')?.result_data
    if(assumptions) payload.assumptions = assumptions.limitations || assumptions
    api.post(`/api/datasets/${datasetId}/trust-score`, payload).then(r=>setTrust(r.data)).catch(()=>{}) 
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[datasetId, message.id, message.execution_status])
  if(!trust) return <div className="h-[56px] w-[56px] rounded-full shimmer" />
  const details = trust.reasons || trust.details || (trust.score ? [`Score ${trust.score}/100`] : [])
  return (
    <div className="flex items-center gap-3 shrink-0">
      <div className="hidden sm:block text-right">
        <div className="text-xs font-semibold">Trusted Insight</div>
        <div className="text-[11px] text-slate-500">{trust.score}/100</div>
      </div>
      <TrustRing score={trust.score} details={Array.isArray(details) ? details.map((d:any)=> typeof d==='string'? d : d.text||JSON.stringify(d)) : undefined} />
    </div>
  )
}

function InsightEvidence({datasetId, message}: any){
  const [trust, setTrust] = useState<any>(null)
  const [evidence, setEvidence] = useState<any>(null)
  const [challenge, setChallenge] = useState<any>(null)
  const [showEvidence, setShowEvidence] = useState(false)
  const [whatIfRes, setWhatIfRes] = useState<any>(null)
  const [drivers, setDrivers] = useState<any>(null)
  const [whyLoading, setWhyLoading] = useState(false)
  const statValidation = (message.results || []).find((r:any)=> r.result_type === 'statistical_validation')?.result_data
  const recommendation = (message.results || []).find((r:any)=> r.result_type === 'recommendation')?.result_data
  const assumptions = (message.results || []).find((r:any)=> r.result_type === 'assumptions')?.result_data
  const isDataQualityAudit = (message.results || []).some((r:any) => r.result_type === 'data_quality' || (r.result_type === 'analysis_meta' && r.result_data?.analysis_mode === 'data_quality_audit'))
  const dataQualityResult = (message.results || []).find((r:any)=> r.result_type === 'data_quality')?.result_data
  const loadTrust = async()=>{ try{ const payload:any = {query_result: {success: true}}; if(statValidation) payload.statistical_validation = statValidation; if(assumptions) payload.assumptions = assumptions.limitations; const coverage = (message.results || []).find((r:any)=> r.result_type === 'question_coverage')?.result_data; if(coverage) payload.question_coverage = coverage; const res = await api.post(`/api/datasets/${datasetId}/trust-score`, payload); setTrust(res.data)}catch (_e){ /* ignore */ }}
  const loadEvidence = async()=>{ try{ const res = await api.get(`/api/datasets/${datasetId}/evidence/${message.id}`); setEvidence(res.data); setShowEvidence(!showEvidence)}catch (_e){ /* ignore */ }}
  const doChallenge = async()=>{ try{ const res = await api.post(`/api/datasets/${datasetId}/challenge`, {message_id: message.id}); setChallenge(res.data)}catch (_e){ /* ignore */ }}
  const runWhatIf = async()=>{ try{ const res = await api.post(`/api/datasets/${datasetId}/whatif`, {column: 'revenue', percent: 10, type: 'price_increase'}); setWhatIfRes(res.data)}catch (_e){ /* ignore */ }}
  const runWhy = async()=>{ 
    if (drivers) { setDrivers(null); return; }
    if (isDataQualityAudit && dataQualityResult) {
      const issues = dataQualityResult.issues || []
      const priority = dataQualityResult.priority || []
      const summary = priority.length ? `Why this matters: ${priority[0]?.title || 'Top issue'} affects ${priority[0]?.affected_rows || 0} rows in column ${priority[0]?.column || 'dataset'}. ${issues[0]?.why_it_matters || ''}` : 'No actionable issues — no downstream impact.'
      setDrivers({ summary, data_quality: true, issues, priority, disclaimer: "Data-quality impact: severity, affected rows/columns, downstream impact, recommended fix. No causal claim." })
      return
    }
    // Check complex first
    const hasComplex = (message.results || []).some((r:any)=> r.result_type==='mom_analysis') && (message.results || []).some((r:any)=> r.result_type==='driver_analysis')
    const momAnalysis = (message.results || []).find((r:any)=> r.result_type==='mom_analysis')?.result_data
    const coverage = (message.results || []).find((r:any)=> r.result_type==='question_coverage')?.result_data
    // Simple trend with derived month — use existing table deterministically, no API, no derived alias as physical column
    const tableResult = (message.results || []).find((r:any)=> r.result_type==='table')?.result_data
    const hasSimpleTrendTable = tableResult && tableResult.columns && tableResult.columns.some((c:string)=> c.toLowerCase()==='month') && tableResult.rows && tableResult.rows.length>0
    if (hasSimpleTrendTable && !hasComplex) {
      // Check if this is a simple trend (single metric, month derived) and not already complex
      const cols = tableResult.columns
      const rows = tableResult.rows
      const metricCol = cols.find((c:string)=> c.toLowerCase()!=='month')
      if (metricCol) {
        // Compute strongest/weakest and MoM deterministically from existing table
        const sorted = [...rows].sort((a:any,b:any)=> String(a.month).localeCompare(String(b.month)))
        let maxRow = sorted[0], minRow = sorted[0]
        let maxVal = parseFloat(sorted[0][metricCol]), minVal = parseFloat(sorted[0][metricCol])
        for (const r of sorted) {
          const v = parseFloat(r[metricCol])
          if (!isNaN(v)) {
            if (v > maxVal) { maxVal = v; maxRow = r }
            if (v < minVal) { minVal = v; minRow = r }
          }
        }
        const latest = sorted[sorted.length-1], prev = sorted.length>=2 ? sorted[sorted.length-2] : null
        let summary = `Monthly ${metricCol} trend across ${sorted.length} months. Strongest month is ${String(maxRow.month)} (${maxVal}), weakest is ${String(minRow.month)} (${minVal}).`
        if (prev) {
          const latestVal = parseFloat(latest[metricCol]), prevVal = parseFloat(prev[metricCol])
          const change = latestVal - prevVal
          const pct = prevVal!==0 ? (change/prevVal*100) : 0
          summary += ` Latest change: ${String(prev.month)} (${prevVal}) → ${String(latest.month)} (${latestVal}) — change ${change >=0 ? '+'+change.toFixed(1) : change.toFixed(1)} (${pct>=0? '+'+pct.toFixed(1): pct.toFixed(1)}% MoM). Peak/trough show volatility, not a statistically inferred trend.`
        }
        summary += ` Evidence reused from existing monthly aggregation; association, not causation.`
        setDrivers({
          summary,
          isSimpleTrend: true,
          table: tableResult,
          strongest: {month: String(maxRow.month), value: maxVal},
          weakest: {month: String(minRow.month), value: minVal},
          latestChange: prev ? {prev_month: String(prev.month), latest_month: String(latest.month), change: parseFloat(latest[metricCol]) - parseFloat(prev[metricCol])} : null,
          disclaimer: "Trend explanation reused from existing monthly aggregation; association, not causation."
        })
        return
      }
    }
    // Complex time-series with existing drivers/mom — use deterministic rendering, no API, no SQL regeneration
    if (hasComplex && momAnalysis) {
      const driverAnalyses = (message.results || []).filter((r:any)=> r.result_type==='driver_analysis').map((r:any)=> r.result_data)
      // tableResult already defined above for simple trend check, reuse
      const strongest = momAnalysis.strongest || {}
      const latestChange = momAnalysis.latest_change || {}
      const summaryParts:string[] = []
      if (Object.keys(strongest).length) {
        summaryParts.push(`Strongest months: ${Object.entries(strongest).map(([k,v]:any)=> `${k} ${String(v.month)} (${v.value})`).join(', ')}`)
        const weakest = momAnalysis.weakest || {}
        summaryParts.push(`Weakest months: ${Object.entries(weakest).map(([k,v]:any)=> `${k} ${String(v.month)} (${v.value})`).join(', ')}`)
      }
      if (Object.keys(latestChange).length) {
        summaryParts.push(`Latest period change: ${Object.entries(latestChange).map(([k,v]:any)=> v ? `${k} ${v.prev_month}→${v.latest_month} ${v.change} (${v.change_pct!==null? v.change_pct+'%':''})` : '').join(' | ')}`)
      }
      summaryParts.push(`MoM analyzed for ${momAnalysis.mom_rows?.length || 0} intervals; peak/trough show volatility, not inferred trend.`)
      const topDrivers:string[] = []
      for (const d of driverAnalyses) {
        if (d.drivers && d.drivers[0]) {
          const top = d.drivers[0]
          const contrib = top.contribution_pct ?? top.change_pct ?? ''
          const contribStr = contrib !== '' ? `, contribution ${contrib}%` : ''
          topDrivers.push(`${d.driver_column} ${String(top.driver_value)} (change ${top.change}${contribStr})`)
        }
      }
      const summary = summaryParts.join('. ') + (topDrivers.length ? `. Top drivers for latest change: ${topDrivers.slice(0,2).join('; ')} — association, not causation.` : '')
      setDrivers({ 
        summary, 
        mom: momAnalysis, 
        driverAnalyses, 
        table: tableResult, 
        coverage,
        isComplex: true, 
        disclaimer: "Drivers show association/contribution to the latest observed change, not proven causation." 
      })
      return
    }
    if (whyLoading) return
    setWhyLoading(true); try{ const res = await api.post(`/api/datasets/${datasetId}/root-cause`, {message_id: message.id}); setDrivers(res.data)}catch(_e){ /* ignore */ } finally{ setWhyLoading(false)}}
  useEffect(()=>{ loadTrust() },[datasetId, message.id, statValidation]) // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="rounded-[16px] border bg-white dark:bg-white/[0.04] dark:border-white/10 overflow-hidden">
      <div className="px-4 py-3 flex items-center justify-between border-b dark:border-white/10">
        <span className="text-xs font-semibold tracking-wide flex items-center gap-1.5"><ShieldCheck className="h-3.5 w-3.5" /> TRUST & METHODOLOGY</span>
        {trust && <span className="text-xs rounded-full bg-slate-900 text-white dark:bg-white dark:text-[#0b0d18] px-2.5 py-1">{trust.score}/100 • {trust.score>=80?'Trusted':trust.score>=60?'Review':'Needs review'}</span>}
      </div>
      <div className="p-4 space-y-3">
        {trust && (
          <div className="grid md:grid-cols-[96px_1fr] gap-4 items-center">
            <TrustRing score={trust.score} />
            <div className="space-y-1.5">
              {trust.reasons?.slice(0,5).map((r:any,i:number)=><div key={i} className="flex gap-2 text-xs"><span className={r.status==='pass'?'text-emerald-600':r.status==='warning'?'text-amber-600':'text-red-600'}>{r.status==='pass'?'✓':r.status==='warning'?'⚠':'✕'}</span><span className="font-medium">{r.check}</span><span className="text-slate-500 dark:text-white/50">— {r.detail}</span></div>)}
              <div className="text-[11px] text-slate-500 mt-1">Why {trust.score}/100? Data quality, sample, evidence, statistical validation, assumptions.</div>
            </div>
          </div>
        )}
        {/* Statistical Validation — approval-rate: strongest vs overall (benchmark, overlapping) and strongest vs rest (inferential) */}
        {statValidation && (
          <div className="rounded-[12px] border bg-slate-50 dark:bg-white/5 dark:border-white/10 p-3 text-xs space-y-2">
            <div className="font-semibold flex items-center gap-1.5">Statistical Validation <span className={`rounded-full px-2 py-0.5 text-[11px] ${statValidation.applicable ? 'bg-emerald-500 text-white' : 'bg-amber-500 text-white'}`}>{statValidation.applicable ? 'Applicable' : 'Statistical validation unavailable'}</span></div>
            {statValidation.applicable ? (
              <>
                {(() => {
                  const obs = statValidation.observed || {}
                  const ci = statValidation.confidence_interval || {}
                  const isApproval = obs.strongest_rate != null || statValidation.benchmark || statValidation.inferential
                  if (isApproval) {
                    const strongestRate = obs.strongest_rate ?? statValidation.inferential?.strongest_rate ?? statValidation.benchmark?.strongest_rate
                    const overallRate = obs.overall_rate ?? statValidation.benchmark?.overall_rate
                    const restRate = obs.rest_rate ?? statValidation.inferential?.rest_rate ?? statValidation.observed?.rest_rate
                    const diffRest = obs.difference_vs_rest_pp ?? statValidation.inferential_difference_pp ?? statValidation.estimate ?? statValidation.inferential?.difference_pp
                    const diffOverall = obs.difference_vs_overall_pp ?? statValidation.benchmark_difference_pp ?? statValidation.benchmark?.difference_pp
                    const hInterpret = statValidation.effect_size_interpretation
                    const hValue = statValidation.effect_size
                    const hLabel = statValidation.effect_size_label || 'cohens_h'
                    const metricName = hLabel === 'cohens_h' ? "Cohen's h" : hLabel === 'cohens_d' ? "Cohen's d" : hLabel
                    const interpretHelp: Record<string,string> = { negligible: 'negligible (<0.2) — no practical difference', small: 'small (0.2–0.5) — modest difference', medium: 'medium (0.5–0.8) — meaningful difference', large: 'large (≥0.8) — substantial difference' }
                    return (
                      <div className="space-y-2">
                        <div className="grid md:grid-cols-3 gap-2">
                          <div><span className="font-medium">Strongest segment:</span> {strongestRate != null ? `${strongestRate}%` : '—'}</div>
                          <div><span className="font-medium">Overall (benchmark):</span> {overallRate != null ? `${overallRate}%` : '—'}</div>
                          <div><span className="font-medium">Rest-of-population:</span> {restRate != null ? `${restRate}%` : '—'}</div>
                        </div>
                        <div className="grid md:grid-cols-2 gap-2">
                          <div className="rounded-[8px] border bg-white dark:bg-black/20 p-2">
                            <div className="font-semibold">Benchmark comparison (descriptive — overlapping)</div>
                            <div className="mt-1">Strongest {strongestRate ?? '—'}% vs Overall {overallRate ?? '—'}% = {diffOverall != null ? `${diffOverall > 0 ? '+' : ''}${diffOverall} pp` : '—'}</div>
                            <div className="text-[11px] text-slate-500">Not independent — groups overlap; for business context only</div>
                          </div>
                          <div className="rounded-[8px] border bg-white dark:bg-black/20 p-2">
                            <div className="font-semibold">Inferential comparison (independent)</div>
                            <div className="mt-1">Strongest {strongestRate ?? '—'}% vs Rest {restRate ?? '—'}% = {diffRest != null ? `${diffRest > 0 ? '+' : ''}${diffRest} pp` : '—'}</div>
                            <div className="text-[11px] text-slate-500">Statistical test: strongest vs rest-of-population • p = {statValidation.p_value ?? '—'} • {statValidation.significance}</div>
                          </div>
                        </div>
                        {statValidation.effect_size != null && (
                          <div><span className="font-medium">Effect size ({metricName}):</span> {hValue} <span className="font-medium">— {hInterpret ?? 'unknown'}</span> {hInterpret && interpretHelp[hInterpret] ? `(${interpretHelp[hInterpret]})` : ''} <span className="text-slate-500">[{hLabel}]</span></div>
                        )}
                        {(ci.strongest_segment || ci.overall || ci.rest) && (
                          <div className="text-[11px] text-slate-600 dark:text-white/60">
                            <div><span className="font-medium">95% CI Strongest:</span> {ci.strongest_segment ? `${ci.strongest_segment.lower}% – ${ci.strongest_segment.upper}%` : '—'} {ci.strongest_segment ? `(centre ${ci.strongest_segment.centre}%)` : ''}</div>
                            <div><span className="font-medium">95% CI Overall (benchmark):</span> {ci.overall ? `${ci.overall.lower}% – ${ci.overall.upper}%` : '—'}</div>
                            <div><span className="font-medium">95% CI Rest:</span> {ci.rest ? `${ci.rest.lower}% – ${ci.rest.upper}%` : '—'}</div>
                          </div>
                        )}
                        {statValidation.sample_sizes && <div><span className="font-medium">Samples:</span> strongest n={statValidation.sample_sizes.strongest}, overall n={statValidation.sample_sizes.overall}, rest n={statValidation.sample_sizes.rest}</div>}
                        <div className="text-slate-600 dark:text-white/60"><span className="font-medium">Practical significance (inferential):</span> {statValidation.practical_significance ?? statValidation.practical_significance_inferential ?? '—'} {statValidation.practical_significance_benchmark ? `• Benchmark: ${statValidation.practical_significance_benchmark}` : ''} • {statValidation.causation_disclaimer || 'Association does not imply causation'}</div>
                        {statValidation.comparison_note && <div className="text-[11px] text-amber-700 dark:text-amber-300">{statValidation.comparison_note}</div>}
                        {statValidation.limitations?.filter((l:string)=> l && l.trim() !== '' && l.trim() !== '-').length>0 && <div className="text-[11px] text-slate-500">Limitations: {statValidation.limitations.filter((l:string)=> l && l.trim() !== '' && l.trim() !== '-').slice(0,3).join(' • ')}</div>}
                      </div>
                    )
                  }
                  // Fallback for non-approval (Welch, chi-square)
                  const metricNameFb = statValidation.effect_size_label === 'cohens_h' ? "Cohen's h" : statValidation.effect_size_label === 'cohens_d' ? "Cohen's d" : (statValidation.effect_size_label || 'effect')
                  const interpretHelpFb: Record<string,string> = { negligible: 'negligible (<0.2)', small: 'small (0.2–0.5)', medium: 'medium (0.5–0.8)', large: 'large (≥0.8)' }
                  return (
                    <>
                      <div className="grid md:grid-cols-2 gap-2">
                        <div><span className="font-medium">Observed difference:</span> {statValidation.estimate ?? statValidation.observed?.difference_pp ?? '—'} {statValidation.estimate_label ? `(${statValidation.estimate_label})` : ''}</div>
                        <div><span className="font-medium">p-value:</span> {statValidation.p_value ?? '—'} • <span className="font-medium">Significance:</span> {statValidation.significance}</div>
                        {statValidation.confidence_interval && <div className="md:col-span-2"><span className="font-medium">CI:</span> {JSON.stringify(statValidation.confidence_interval)}</div>}
                        {statValidation.effect_size != null && <div><span className="font-medium">Effect size ({metricNameFb}):</span> {statValidation.effect_size} — {statValidation.effect_size_interpretation ?? 'unknown'} {statValidation.effect_size_interpretation && interpretHelpFb[statValidation.effect_size_interpretation] ? `(${interpretHelpFb[statValidation.effect_size_interpretation]})` : ''} <span className="text-slate-500">[{statValidation.effect_size_label}]</span></div>}
                        {statValidation.sample_sizes && <div><span className="font-medium">Samples:</span> {JSON.stringify(statValidation.sample_sizes)}</div>}
                      </div>
                      <div className="text-slate-600 dark:text-white/60"><span className="font-medium">Practical:</span> {statValidation.practical_significance} • {statValidation.causation_disclaimer || 'Association not causation'}</div>
                      {statValidation.limitations?.filter((l:string)=> l && l.trim() !== '' && l.trim() !== '-').length>0 && <div className="text-[11px] text-slate-500">Limitations: {statValidation.limitations.filter((l:string)=> l && l.trim() !== '' && l.trim() !== '-').slice(0,2).join(' • ')}</div>}
                    </>
                  )
                })()}
              </>
            ) : (
              <div className="text-slate-600 dark:text-white/60"><span className="font-medium">Statistical validation unavailable:</span> {statValidation.reason} • {statValidation.limitations?.filter((l:string)=> l && l.trim() !== '' && l.trim() !== '-').join(' • ')}</div>
            )}
          </div>
        )}
        {/* Recommendation */}
        {recommendation && (
          <div className="rounded-[12px] border bg-emerald-50 dark:bg-emerald-500/10 dark:border-emerald-500/20 p-3 text-xs space-y-2">
            <div className="font-semibold flex items-center justify-between"><span>Recommendation • {recommendation.title}</span><span className="rounded-full bg-white dark:bg-black border px-2 py-0.5 text-[11px]">{recommendation.confidence} confidence</span></div>
            <div className="text-slate-800 dark:text-white/90 leading-relaxed">{recommendation.recommendation}</div>
            <div><span className="font-medium">Rationale:</span> {recommendation.rationale}</div>
            {recommendation.supporting_evidence?.length>0 && <div><span className="font-medium">Evidence:</span> {recommendation.supporting_evidence.slice(0,3).join(' • ')}</div>}
            {recommendation.limitations?.length>0 && <div className="text-[11px] text-amber-700 dark:text-amber-300">Limitations: {recommendation.limitations.slice(0,2).join(' • ')}</div>}
            {recommendation.requires_validation && <div className="text-[11px] font-semibold text-red-700 dark:text-red-300">Requires human/business validation before operational action.</div>}
            <div className="text-slate-500">Expected impact: {recommendation.expected_impact}</div>
          </div>
        )}
        {/* Assumptions & Limitations — filter empty "-" bullets; show fallback if none */}
        {(() => {
          const raw = assumptions?.limitations || []
          const filtered = raw.filter((l:string) => l && l.trim() !== '' && l.trim() !== '-')
          if (filtered.length === 0 && !assumptions) return null
          if (filtered.length === 0) {
            return (
              <div className="rounded-[12px] border bg-white dark:bg-white/5 dark:border-white/10 p-3 text-xs">
                <div className="font-semibold">Assumptions & limitations</div>
                <div className="mt-1 text-slate-600 dark:text-white/60">No additional assumptions identified.</div>
              </div>
            )
          }
          return (
            <details className="rounded-[12px] border bg-white dark:bg-white/5 dark:border-white/10 p-3 text-xs" open>
              <summary className="cursor-pointer font-semibold">Assumptions & limitations</summary>
              <ul className="mt-2 list-disc list-inside space-y-1 text-slate-600 dark:text-white/60">
                {filtered.slice(0,6).map((lim:string,i:number)=><li key={i}>{lim}</li>)}
              </ul>
            </details>
          )
        })()}
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" className="rounded-full h-8" onClick={runWhy} disabled={whyLoading}>{whyLoading?'Analyzing…':'Why?'}</Button>
          <Button size="sm" variant="outline" className="rounded-full h-8" onClick={loadEvidence}>{showEvidence?'Hide Evidence':'Show Evidence'}</Button>
          <Button size="sm" variant="outline" className="rounded-full h-8" onClick={doChallenge}>Challenge</Button>
          <Button size="sm" variant="outline" className="rounded-full h-8" onClick={runWhatIf}>What-If</Button>
          <Button size="sm" variant="outline" className="rounded-full h-8" onClick={async()=>{ try{ await api.post('/api/reports', {title: message.content.slice(0,50), dataset_id: datasetId}); alert('Report created') }catch(e:any){ alert(e.response?.data?.detail||e.message)} }}>Create Report</Button>
        </div>
        {drivers && drivers.isComplex && (
          <div className="rounded-[12px] border bg-white dark:bg-white/5 dark:border-white/10 p-3 text-xs space-y-2">
            <div className="font-semibold">Why? — Complex Time-Series Explanation <span className="font-normal text-slate-500">• Deterministic, no SQL regeneration</span></div>
            <div className="text-slate-600 dark:text-white/60 whitespace-pre-wrap">{drivers.summary}</div>
            {drivers.mom && (
              <div className="space-y-1">
                <div className="font-medium">MoM Details:</div>
                <div className="text-[11px]">Strongest: {Object.entries(drivers.mom.strongest||{}).map(([k,v]:any)=> `${String(k)} ${String(v.month)} (${v.value})`).join(', ')}</div>
                <div className="text-[11px]">Weakest: {Object.entries(drivers.mom.weakest||{}).map(([k,v]:any)=> `${String(k)} ${String(v.month)} (${v.value})`).join(', ')}</div>
                <div className="text-[11px]">Latest: {Object.entries(drivers.mom.latest_change||{}).map(([k,v]:any)=> v ? `${String(k)} ${String(v.prev_month)}→${String(v.latest_month)} ${v.change} (${v.change_pct!==null? `${v.change_pct}%`:''})` : '').join(' | ')}</div>
              </div>
            )}
            {drivers.driverAnalyses && drivers.driverAnalyses.map((da:any)=>(
              <div key={da.driver_column} className="rounded-[8px] border bg-slate-50 dark:bg-white/5 dark:border-white/10 p-2">
                <div className="font-medium text-xs">{String(da.driver_column)} → {String(da.metric)} ({String(da.prev_month)} vs {String(da.latest_month)})</div>
                <div className="mt-1 space-y-1">
                  {(da.drivers||[]).slice(0,3).map((d:any)=> <div key={String(d.driver_value)} className="flex justify-between text-[11px]"><span>{String(d.driver_value)}</span><span>change {String(d.change)} {d.contribution_pct!==undefined? `• ${d.contribution_pct}%`: d.change_pct!==undefined? `• ${d.change_pct}%`:''}</span></div>)}
                </div>
              </div>
            ))}
            {drivers.coverage && <div className="text-[11px] text-slate-500">Coverage: {Math.round(drivers.coverage.coverage_ratio*100)}% complete • {drivers.coverage.requested_components.length} requested • association, not causation</div>}
            <div className="text-[11px] text-slate-500">{drivers.disclaimer}</div>
            <Button size="sm" variant="outline" className="h-7 text-xs" onClick={()=> setDrivers(null)}>Dismiss</Button>
          </div>
        )}
        {drivers && drivers.isSimpleTrend && (
          <div className="rounded-[12px] border bg-white dark:bg-white/5 dark:border-white/10 p-3 text-xs space-y-2">
            <div className="font-semibold">Why? — Trend Explanation <span className="font-normal text-slate-500">• Deterministic, reused existing monthly aggregation</span></div>
            <div className="text-slate-600 dark:text-white/60 whitespace-pre-wrap">{drivers.summary}</div>
            <div className="text-[11px]">Strongest: {String(drivers.strongest.month)} ({drivers.strongest.value}) • Weakest: {String(drivers.weakest.month)} ({drivers.weakest.value})</div>
            {drivers.latestChange && <div className="text-[11px]">Latest: {String(drivers.latestChange.prev_month)} → {String(drivers.latestChange.latest_month)} change {String(drivers.latestChange.change)} ({drivers.latestChange.change_pct!==null? `${drivers.latestChange.change_pct}%`:''})</div>}
            <div className="text-[11px] text-slate-500">{drivers.disclaimer}</div>
            <Button size="sm" variant="outline" className="h-7 text-xs" onClick={()=> setDrivers(null)}>Dismiss</Button>
          </div>
        )}
        {drivers && !isDataQualityAudit && !drivers.isComplex && !drivers.isSimpleTrend && (
          <div className="rounded-[12px] border bg-white dark:bg-white/5 dark:border-white/10 p-3 text-xs space-y-2">
            <div className="font-semibold">Why? — Driver Analysis <span className="font-normal text-slate-500">• DuckDB verified</span></div>
            <div className="text-slate-600 dark:text-white/60">{drivers.summary}</div>
            {drivers.dimensions ? (
              <div className="space-y-3">
                {drivers.dimensions.map((dim:any)=>(
                  <div key={dim.dimension} className="rounded-[12px] border bg-slate-50 dark:bg-white/5 dark:border-white/10 p-2">
                    <div className="font-medium flex justify-between"><span>{dim.dimension}</span><span className="text-slate-500">Δ {dim.difference_pp>0?`+${dim.difference_pp}`:dim.difference_pp} pp {dim.largest?'• largest':''}</span></div>
                    <div className="mt-1 space-y-1">
                      {dim.groups.map((g:any)=><div key={g.value} className="flex justify-between text-[11px]"><span>{g.value}</span><span>{g.rate.toFixed(1)}% approval, n={g.n} ({g.approved} approved)</span></div>)}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="space-y-1">
                {drivers.primary_drivers?.map((d:any,i:number)=><div key={i} className="flex justify-between rounded-full border px-3 py-1.5 bg-slate-50 dark:bg-white/5 dark:border-white/10"><span className="font-medium">{i+1}. {d.dimension_value}</span><span>{d.metric_value.toFixed(2)} • {d.contribution_percent}%</span></div>)}
              </div>
            )}
            <div className="text-[11px] text-slate-500">{drivers.disclaimer}</div>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" className="h-7 text-xs" onClick={()=> navigator.clipboard.writeText(drivers.sql)}>View SQL</Button>
              <Button size="sm" variant="outline" className="h-7 text-xs" onClick={()=> setDrivers(null)}>Dismiss</Button>
            </div>
          </div>
        )}
        {drivers && isDataQualityAudit && drivers.data_quality && (
          <div className="rounded-[12px] border bg-amber-50 dark:bg-amber-500/10 dark:border-amber-500/20 p-3 text-xs space-y-2">
            <div className="font-semibold">Why this matters — Data Quality</div>
            <div className="text-slate-700 dark:text-white/80">{drivers.summary}</div>
            {drivers.priority?.slice(0,3).map((p:any,i:number)=><div key={i} className="text-[11px]"><span className="font-medium">{i+1}. [{p.level}] {p.title}</span> — column: {p.column || 'dataset'} — affected: {p.affected_rows}</div>)}
            <div className="text-[11px] text-slate-500">{drivers.disclaimer}</div>
            <Button size="sm" variant="outline" className="h-7 text-xs" onClick={()=> setDrivers(null)}>Dismiss</Button>
          </div>
        )}
        {showEvidence && evidence && (
          <div className="rounded-[12px] border bg-slate-50 dark:bg-white/5 dark:border-white/10 p-3 text-xs space-y-1.5">
            <div><span className="font-medium">Method:</span> {evidence.method}</div>
            <div><span className="font-medium">Query:</span> <code className="bg-white dark:bg-black px-1 py-0.5 rounded border dark:border-white/10">{evidence.query}</code></div>
            <div><span className="font-medium">Records:</span> {evidence.data_quality.row_count} • Quality {evidence.data_quality.score}/100</div>
            <div><span className="font-medium">Trust:</span> {evidence.trust_score.score}/100</div>
          </div>
        )}
        {challenge && (
          <div className="rounded-[12px] border bg-white dark:bg-white/5 dark:border-white/10 p-3 text-xs space-y-1">
            <div className="font-semibold">Challenge Result: {challenge.conclusion}</div>
            {challenge.challenges?.map((c:any,i:number)=><div key={i}><span className="font-medium">{c.hypothesis}</span> — {c.evidence} ({c.impact})</div>)}
          </div>
        )}
        {whatIfRes && (
          <div className="rounded-[12px] border bg-amber-50 dark:bg-amber-500/10 dark:border-amber-500/20 p-3 text-xs">
            <div className="font-medium">What-If: {whatIfRes.scenario}</div>
            <div className="mt-1">Before: {JSON.stringify(whatIfRes.before)} → After: {JSON.stringify(whatIfRes.after)}</div>
            <div className="text-amber-700 dark:text-amber-300 mt-1">Scenario — hypothetical, not a prediction</div>
          </div>
        )}
      </div>
    </div>
  )
}
