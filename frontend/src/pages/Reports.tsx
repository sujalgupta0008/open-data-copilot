import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/common/Card'
import { Button } from '@/components/common/Button'
import { Input } from '@/components/common/Input'
import { useState } from 'react'
import { FileText, Download, Trash2, Sparkles, CheckSquare, Square, Layers, Share2, Copy, ExternalLink, Send, X } from 'lucide-react'
import { authenticatedDownload } from '@/lib/export'


export default function Reports(){
  const [title,setTitle]=useState(''); const [datasetId,setDatasetId]=useState('')
  const [topic,setTopic]=useState(''); const [aiDatasetId,setAiDatasetId]=useState(''); const [aiTitle,setAiTitle]=useState('')
  const [clarifications,setClarifications]=useState<any[]|null>(null)
  const [plan,setPlan]=useState<any[]|null>(null)
  const [selected,setSelected]=useState<Set<string>>(new Set())
  const [combinedTitle,setCombinedTitle]=useState('')
  const [shareReport,setShareReport]=useState<any>(null)
  const [shareLinks,setShareLinks]=useState<any[]>([])
  const [shareUrl,setShareUrl]=useState('')
  const [shareExpires,setShareExpires]=useState(30)
  const [copied,setCopied]=useState(false)
  const [slackPopover,setSlackPopover]=useState<string|null>(null)
  const [slackWebhook,setSlackWebhook]=useState<string>(()=> typeof window!=='undefined' ? (localStorage.getItem('odc-slack-webhook')||'') : '')
  const [slackSent,setSlackSent]=useState<string|null>(null)
  const qc=useQueryClient()
  const { data: datasets } = useQuery({ queryKey:['datasetsList'], queryFn: async()=> (await api.get('/api/datasets')).data })
  const { data: reports, isLoading } = useQuery({ queryKey:['reports'], queryFn: async()=> (await api.get('/api/reports')).data })
  const createMut=useMutation({ mutationFn: async()=> (await api.post('/api/reports', { title, dataset_id: datasetId })).data, onSuccess: ()=> { qc.invalidateQueries({queryKey:['reports']}); setTitle(''); setDatasetId('') } })
  const delMut=useMutation({ mutationFn: async(id:string)=> (await api.delete(`/api/reports/${id}`)).data, onSuccess: ()=> qc.invalidateQueries({queryKey:['reports']}) })
  const generateMut=useMutation({
    mutationFn: async(payload:any)=> (await api.post('/api/reports/generate', payload)).data,
    onSuccess: (data:any)=>{
      if(data?.content?.needs_clarification){
        setClarifications(data.content.clarifications || data.content.clarifications)
        // Also check if data is clarification pseudo-report
        if(data.content.clarifications) setClarifications(data.content.clarifications)
      } else if(data?.content?.needs_plan){
        setPlan(data.content.plan)
      } else {
        qc.invalidateQueries({queryKey:['reports']})
        setTopic(''); setAiTitle(''); setClarifications(null); setPlan(null)
      }
    }
  })
  const combinedMut=useMutation({
    mutationFn: async(payload:any)=> (await api.post('/api/reports/combined', payload)).data,
    onSuccess: ()=> { qc.invalidateQueries({queryKey:['reports']}); setSelected(new Set()); setCombinedTitle('') }
  })

  const handleGenerate = async()=>{
    setClarifications(null); setPlan(null)
    const ds = aiDatasetId || datasetId || (datasets?.[0]?.id || '')
    if(!ds){
      alert('Select a dataset')
      return
    }
    if(!topic.trim()){
      alert('Enter a topic')
      return
    }
    try{
      const res = await api.post('/api/reports/generate', { topic: topic.trim(), title: aiTitle || undefined, dataset_id: ds, confirm: false })
      const data = res.data
      // Check if clarification
      if(data?.content?.needs_clarification || data?.report_type==='clarification'){
        setClarifications(data.content?.clarifications || [])
        return
      }
      // Check if plan
      if(data?.content?.needs_plan || data?.analysis_plan){
        setPlan(data.content?.plan || data.content?.analysis_plan || [])
        // For now, auto-confirm to generate
        await api.post('/api/reports/generate', { topic: topic.trim(), title: aiTitle || undefined, dataset_id: ds, confirm: true })
        qc.invalidateQueries({queryKey:['reports']})
        setTopic(''); setAiTitle('')
      } else {
        // Direct report created
        qc.invalidateQueries({queryKey:['reports']})
        setTopic(''); setAiTitle('')
      }
    }catch(_e:any){
      const clar = (_e as any).response?.data?.content?.clarifications || (_e as any).response?.data?.clarifications
      if(clar){
        setClarifications(clar)
      }
    }
  }

  const handleClarificationChoice = async(opt:string)=>{
    setClarifications(null)
    const ds = aiDatasetId || datasetId || (datasets?.[0]?.id || '')
    const enriched = topic ? `${topic} [Selected: ${opt}]` : opt
    try{
      await api.post('/api/reports/generate', { topic: enriched, title: aiTitle || undefined, dataset_id: ds, confirm: true })
      qc.invalidateQueries({queryKey:['reports']})
      setTopic(''); setAiTitle('')
    }catch(_e:any){
      // ignore - clarification handled via explicit choice
    }
  }

  const toggleSelect = (id:string)=>{
    const next = new Set(selected)
    if(next.has(id)) next.delete(id)
    else next.add(id)
    setSelected(next)
  }
  const selectAll = ()=>{
    if(selected.size===reports?.length) setSelected(new Set())
    else setSelected(new Set(reports?.map((r:any)=>r.id)))
  }
  const handleCombined = async()=>{
    if(selected.size<1){
      alert('Select at least one report')
      return
    }
    if(selected.size===1){
      // Still allow single for testing, but spec says multiple
    }
    await combinedMut.mutateAsync({ report_ids: Array.from(selected), title: combinedTitle || undefined })
  }
  const openShare = async (r:any) => {
    setShareReport(r); setShareUrl(''); setShareLinks([])
    try{ const res=await api.get(`/api/reports/${r.id}/shares`); setShareLinks(res.data); }catch{ /* share fetch error ignored */ }
  }
  const generateShare = async () => {
    if(!shareReport) return
    const res=await api.post(`/api/reports/${shareReport.id}/share`, {expires_in_days: shareExpires})
    const url = res.data.share_url.replace('https://app', window.location.origin)
    setShareUrl(url)
    const list=await api.get(`/api/reports/${shareReport.id}/shares`)
    setShareLinks(list.data)
  }
  const copyLink = async (url:string) => {
    try{ await navigator.clipboard.writeText(url); setCopied(true); setTimeout(()=>setCopied(false),2000)}catch{ /* clipboard error ignored */ }
  }
  const revokeShare = async (token_id:string) => {
    if(!shareReport) return
    await api.delete(`/api/reports/${shareReport.id}/shares/${token_id}`)
    const list=await api.get(`/api/reports/${shareReport.id}/shares`)
    setShareLinks(list.data)
  }
  const sendToSlack = async (r:any) => {
    if(!slackWebhook.startsWith('https://hooks.slack.com/')){ alert('Invalid webhook: must start with https://hooks.slack.com/'); return }
    localStorage.setItem('odc-slack-webhook', slackWebhook)
    try{
      await api.post(`/api/reports/${r.id}/export/slack`, {webhook_url: slackWebhook})
      setSlackSent(r.id)
      setTimeout(()=>setSlackSent(null),3000)
    }catch(e:any){ alert(e.response?.data?.detail || e.message) }
  }

  return (
    <div className="space-y-6 max-w-[1100px]">
      <div>
        <h1 className="text-[26px] font-semibold tracking-tight">Reports</h1>
        <p className="text-sm text-slate-600 dark:text-white/60">Generate board-ready reports — AI Report Generator + Reports Library. Lineage, methodology, and exports included.</p>
      </div>

      {/* MODE A — AI REPORT GENERATOR */}
      <Card className="overflow-hidden border-[#6d6af0]/20">
        <div className="h-1 bg-gradient-to-r from-[#6d6af0] to-[#38bdf8]" />
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-[#6d6af0]" /> Generate AI Report</CardTitle>
          <p className="text-xs text-slate-500">Enter a natural-language topic — the system will inspect schema, clarify if needed, plan, execute via Copilot pipeline (DuckDB truth), and create a PDF.</p>
        </CardHeader>
        <CardContent className="space-y-3">
          <textarea placeholder="Topic — e.g., Analyze revenue performance and identify the main factors behind recent changes." value={topic} onChange={(e:any)=>setTopic(e.target.value)} className="w-full min-h-[80px] rounded-[16px] border bg-white px-4 py-3 text-sm dark:bg-white/5 dark:border-white/10" />
          <div className="grid md:grid-cols-2 gap-2">
            <Input placeholder="Report title (optional)" value={aiTitle} onChange={(e:any)=>setAiTitle(e.target.value)} />
            <select value={aiDatasetId} onChange={(e:any)=>setAiDatasetId(e.target.value)} className="w-full h-10 rounded-full border bg-white px-4 text-sm dark:bg-white/5 dark:border-white/10">
              <option value="">Select dataset {datasets?.length>1 ? '(required for multiple)' : '(auto)'}</option>
              {datasets?.map((d:any)=><option key={d.id} value={d.id}>{d.name} — {d.row_count} rows</option>)}
            </select>
          </div>
          <div className="flex gap-2">
            <Button disabled={!topic.trim() || generateMut.isPending} onClick={handleGenerate}>{generateMut.isPending?'Generating…':'Analyze & Preview'}</Button>
            <Button variant="outline" disabled={!topic.trim() || generateMut.isPending} onClick={handleGenerate}>Generate PDF</Button>
          </div>
          {generateMut.isError && <div className="text-sm text-red-600 rounded-full bg-red-50 border border-red-200 px-3 py-1 inline-flex dark:bg-red-500/10 dark:border-red-500/20">{(generateMut.error as any).response?.data?.detail || 'Failed'}</div>}

          {clarifications && clarifications.length>0 && (
            <div className="rounded-[16px] border bg-amber-50 dark:bg-amber-500/10 dark:border-amber-500/20 p-4 space-y-2">
              <div className="text-sm font-semibold">Clarification required</div>
              {clarifications.map((cl:any, idx:number)=>(
                <div key={idx} className="space-y-2">
                  <div className="text-xs font-medium">{cl.question || cl.message}</div>
                  <div className="flex flex-wrap gap-2">
                    {cl.options?.map((opt:any)=>(
                      <Button key={opt.value} size="sm" variant="outline" className="rounded-full h-7 text-xs" onClick={()=>handleClarificationChoice(opt.value)}>{opt.label}</Button>
                    ))}
                  </div>
                </div>
              ))}
              <div className="text-[11px] text-slate-500">Select an option to continue — numbers will come from DuckDB, not LLM invention.</div>
            </div>
          )}
          {plan && plan.length>0 && (
            <div className="rounded-[16px] border bg-white dark:bg-white/5 dark:border-white/10 p-4">
              <div className="text-sm font-semibold flex items-center gap-2"><Layers className="h-4 w-4" /> Analysis Plan</div>
              <ol className="mt-2 space-y-1 text-xs list-decimal list-inside">
                {plan.map((s:any)=><li key={s.step}><span className="font-medium">{s.title}</span> — <span className="text-slate-500">{s.detail}</span></li>)}
              </ol>
              <Button size="sm" className="mt-3" onClick={handleGenerate} disabled={generateMut.isPending}>Confirm & Generate</Button>
            </div>
          )}
          <div className="text-[11px] text-slate-500 border-t dark:border-white/10 pt-2">All numerical claims originate from executed DuckDB results. LLM is explanation layer only.</div>
        </CardContent>
      </Card>

      {/* Legacy simple generator (kept for compatibility) */}
      <Card className="overflow-hidden">
        <div className="h-1 bg-gradient-to-r from-slate-200 to-slate-300 dark:from-white/10 dark:to-white/5" />
        <CardHeader><CardTitle className="flex items-center gap-2"><Sparkles className="h-4 w-4" /> Generate Report (Legacy)</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <Input placeholder="Report title — e.g., Q3 Retail Review" value={title} onChange={(e:any)=>setTitle(e.target.value)}/>
          <select value={datasetId} onChange={(e:any)=>setDatasetId(e.target.value)} className="w-full h-10 rounded-full border bg-white px-4 text-sm dark:bg-white/5 dark:border-white/10">
            <option value="">Select dataset</option>
            {datasets?.map((d:any)=><option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
          <Button disabled={!title||!datasetId||createMut.isPending} onClick={()=>createMut.mutate()}>{createMut.isPending?'Generating…':'Generate Report'}</Button>
          {createMut.isError && <div className="text-sm text-red-600 rounded-full bg-red-50 border border-red-200 px-3 py-1 inline-flex dark:bg-red-500/10 dark:border-red-500/20">{(createMut.error as any).response?.data?.detail}</div>}
        </CardContent>
      </Card>

      {/* REPORTS LIBRARY */}
      <Card className="overflow-hidden">
        <div className="h-1 bg-gradient-to-r from-[#6d6af0] via-[#38bdf8] to-emerald-500" />
        <CardHeader>
          <div className="flex justify-between items-start gap-3">
            <div>
              <CardTitle className="flex items-center gap-2"><Layers className="h-4 w-4" /> Reports Library</CardTitle>
              <p className="text-xs text-slate-500">{reports?.length||0} saved reports — view, download, select for combined</p>
            </div>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={selectAll} disabled={!reports || reports.length===0}>
                {selected.size===reports?.length ? <CheckSquare className="h-3.5 w-3.5 mr-1" /> : <Square className="h-3.5 w-3.5 mr-1" />}
                {selected.size===reports?.length ? 'Deselect All' : 'Select All'}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading? <div className="space-y-3">{Array.from({length:2}).map((_,i)=><div key={i} className="h-[140px] shimmer rounded-[16px]" />)}</div> : reports?.length===0? (
            <Card><CardContent className="p-10 text-center">
              <div className="mx-auto h-12 w-12 rounded-full border bg-slate-50 grid place-items-center dark:bg-white/5 dark:border-white/10"><FileText className="h-5 w-5 text-slate-400" /></div>
              <div className="font-medium mt-3">No reports yet</div>
              <div className="text-sm text-slate-500">Generate your first report above.</div>
            </CardContent></Card>
          ) : (
            <div className="space-y-3">
              <div className="flex gap-2 items-center flex-wrap border-b dark:border-white/10 pb-3">
                <Input placeholder="Combined report title (optional)" value={combinedTitle} onChange={(e:any)=>setCombinedTitle(e.target.value)} className="flex-1 min-w-[200px]" />
                <Button size="sm" disabled={selected.size<1 || combinedMut.isPending} onClick={handleCombined} className="bg-[#0b0d18] text-white dark:bg-white dark:text-[#0b0d18]">
                  {combinedMut.isPending?'Generating…':`Generate Combined Report (${selected.size})`}
                </Button>
                <span className="text-[11px] text-slate-500">{selected.size} selected → 5 bullets each → {selected.size*5} bullets</span>
              </div>
              {combinedMut.isError && <div className="text-sm text-red-600">{(combinedMut.error as any).response?.data?.detail || 'Combined failed'}</div>}
              <div className="grid gap-4">
                {reports?.map((r:any)=>(
                  <Card key={r.id} className={`group ${selected.has(r.id) ? 'ring-2 ring-[#6d6af0] border-[#6d6af0]' : ''}`}>
                    <CardHeader className="pb-2">
                      <CardTitle className="flex justify-between items-start gap-3">
                        <span className="flex items-center gap-2">
                          <input type="checkbox" checked={selected.has(r.id)} onChange={()=>toggleSelect(r.id)} className="h-4 w-4 rounded" />
                          <span className="h-8 w-8 rounded-full bg-[#0b0d18] dark:bg-white grid place-items-center"><FileText className="h-4 w-4 text-white dark:text-[#0b0d18]" /></span>
                          <span className="flex flex-col">
                            <span>{r.title}</span>
                            <span className="text-xs font-normal text-slate-500 flex gap-2">
                              <span>{r.report_type || 'generic'} • {r.analysis_type || 'unknown'}</span>
                              <span>Dataset: {datasets?.find((d:any)=>d.id===r.dataset_id)?.name || r.dataset_id.slice(0,8)}</span>
                              <span>V{r.dataset_version_number || '?'} • {r.dataset_version?.slice(0,8) || 'v1'}</span>
                            </span>
                          </span>
                        </span>
                        <span className="text-xs font-normal rounded-full border bg-slate-50 px-2 py-1 dark:bg-white/5 dark:border-white/10 shrink-0">{new Date(r.created_at).toLocaleString()}</span>
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <pre className="text-xs bg-slate-50 p-3 rounded-[12px] overflow-auto border dark:bg-white/5 dark:border-white/10 max-h-[120px]">{JSON.stringify(r.content,null,2).slice(0,800)}</pre>
                      <div className="mt-3 flex gap-2 flex-wrap">
                        <Button variant="outline" size="sm" onClick={()=> {
                          // View: could open modal, for now just alert
                          alert(JSON.stringify(r.content, null, 2).slice(0,1000))
                        }}>View</Button>
                        <Button variant="outline" size="sm" onClick={()=> {
                          const mode = (typeof window !== 'undefined' ? localStorage.getItem(`odc-view-mode-${r.dataset_id}`) : null) as string
                          const url = `/api/reports/${r.id}/pdf${mode==='executive' ? '?mode=executive' : ''}`
                          authenticatedDownload(url, `${r.title}.pdf`)
                        }}><Download className="h-3.5 w-3.5 mr-1" />Download PDF</Button>
                        <Button variant="outline" size="sm" onClick={()=> {
                          const mode = (typeof window !== 'undefined' ? localStorage.getItem(`odc-view-mode-${r.dataset_id}`) : null) as string
                          const url = `/api/reports/${r.id}/pdf${mode==='executive' ? '?mode=executive' : ''}`
                          window.open(url, '_blank')
                        }}>Open PDF</Button>
                        <Button variant="ghost" size="sm" onClick={()=>delMut.mutate(r.id)}><Trash2 className="h-3.5 w-3.5 mr-1" />Delete</Button>
                        <Button variant="outline" size="sm" onClick={()=>openShare(r)}><Share2 className="h-3.5 w-3.5 mr-1" />Share</Button>
                        <div className="relative">
                          <Button variant="outline" size="sm" onClick={()=>setSlackPopover(slackPopover===r.id?null:r.id)}><Send className="h-3.5 w-3.5 mr-1" />Slack</Button>
                          {slackPopover===r.id && (
                            <div className="absolute bottom-full mb-2 right-0 w-72 rounded-[12px] border bg-white dark:bg-[#0f1220] dark:border-white/10 p-3 shadow-lg z-10">
                              <div className="text-xs font-medium">Send to Slack</div>
                              <div className="text-[11px] text-slate-500">Webhook URL:</div>
                              <input value={slackWebhook} onChange={e=>setSlackWebhook(e.target.value)} placeholder="https://hooks.slack.com/..." className="w-full h-8 rounded-full border px-3 text-xs mt-1 dark:bg-white/5 dark:border-white/10" />
                              <Button size="sm" className="mt-2 w-full" onClick={()=>sendToSlack(r)}>Send to Slack</Button>
                              <a href="https://api.slack.com/messaging/webhooks" target="_blank" className="text-[11px] underline mt-1 inline-block">Get webhook URL ↗</a>
                              {slackSent===r.id && <div className="text-xs text-emerald-600 mt-1">Sent to Slack! ✓</div>}
                            </div>
                          )}
                        </div>
                        <span className="text-[11px] text-slate-500 py-1">Source: {r.session_id ? `Session ${r.session_id.slice(0,8)}` : (r.source_report_ids ? `Combined from ${r.source_report_ids.length}` : 'Direct')}</span>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      </Card>
      {shareReport && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/40" onClick={()=>setShareReport(null)} />
          <div className="relative w-full max-w-md rounded-[16px] bg-white dark:bg-[#0f1220] border dark:border-white/10 p-5 shadow-xl">
            <div className="flex justify-between items-center">
              <h3 className="font-semibold">Share Report</h3>
              <button onClick={()=>setShareReport(null)} className="h-8 w-8 grid place-items-center rounded-full border dark:border-white/10"><X className="h-4 w-4" /></button>
            </div>
            <p className="text-xs text-slate-500 mt-1">Anyone with the link can view</p>
            {shareUrl && (
              <div className="mt-3">
                <div className="flex gap-2">
                  <input value={shareUrl} readOnly className="flex-1 h-9 rounded-full border px-3 text-xs dark:bg-white/5 dark:border-white/10" />
                  <Button size="sm" onClick={()=>copyLink(shareUrl)}><Copy className="h-3.5 w-3.5 mr-1" />{copied?'Copied!':'Copy Link'}</Button>
                  <Button size="sm" variant="outline" onClick={()=>window.open(shareUrl,'_blank')}><ExternalLink className="h-3.5 w-3.5" /></Button>
                </div>
              </div>
            )}
            <div className="mt-3 flex items-center gap-2 text-xs">
              <span>Expires in:</span>
              <select value={shareExpires} onChange={e=>setShareExpires(Number(e.target.value))} className="h-7 rounded-full border px-2 dark:bg-white/5 dark:border-white/10">
                <option value={7}>7 days</option><option value={30}>30 days</option><option value={90}>90 days</option>
              </select>
              <Button size="sm" onClick={generateShare}>Generate New Link</Button>
            </div>
            <div className="mt-4">
              <div className="text-xs font-medium">Active links ({shareLinks.length}):</div>
              <div className="space-y-2 mt-2 max-h-40 overflow-auto">
                {shareLinks.length===0 ? <div className="text-xs text-slate-500">No active links</div> : shareLinks.map((t:any)=>(
                  <div key={t.id} className="flex items-center justify-between text-xs border rounded-full px-3 py-1.5 dark:border-white/10">
                    <span>{t.token_preview}... • Created {new Date(t.created_at).toLocaleDateString()} • Expires {new Date(t.expires_at).toLocaleDateString()} • {t.view_count} views</span>
                    <button onClick={()=>revokeShare(t.id)} className="ml-2 text-red-600 hover:text-red-700"><X className="h-3 w-3" /></button>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
