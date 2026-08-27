import { useParams, Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle, Badge } from '@/components/common/Card'
import { Button } from '@/components/common/Button'
import { useState, useEffect, useRef } from 'react'
import { Sparkles, ShieldCheck, Activity, Layers, Clock, Eye, Download, Save, GitCompare, Undo2, Redo2, Gauge, AlertTriangle, CheckCircle2 } from 'lucide-react'
import { authenticatedDownload } from '@/lib/export'

export default function CleaningStudio({ isDrawer = false, datasetId }: { isDrawer?: boolean; datasetId?: string } = {}){
  const { id: paramId } = useParams()
  const id = datasetId || paramId
  const qc = useQueryClient()
  const [selectedOp, setSelectedOp] = useState<string>('missing')
  const [params, setParams] = useState<any>({})
  const [preview, setPreview] = useState<any>(null)
  const [mode, setMode] = useState<'manual'|'ai'>('manual')
  const [showDiff, setShowDiff] = useState(false)
  const previewRef = useRef<HTMLDivElement>(null)
  const [successMsg, setSuccessMsg] = useState<string|null>(null)
  const [errorMsg, setErrorMsg] = useState<string|null>(null)
  const [previewError, setPreviewError] = useState<string|null>(null)
  const [conflict, setConflict] = useState<{payload:any, message:string}|null>(null)

  const { data: dataset } = useQuery({ queryKey:['ds',id], queryFn: async()=> (await api.get(`/api/datasets/${id}`)).data })
  const { data: profile } = useQuery({ queryKey:['profile',id], queryFn: async()=> (await api.get(`/api/datasets/${id}/profile`)).data })
  const { data: previewData } = useQuery({ queryKey:['preview',id], queryFn: async()=> (await api.get(`/api/datasets/${id}/preview`, {params:{page:1,page_size:20}})).data })
  const { data: history } = useQuery({ queryKey:['history',id], queryFn: async()=> (await api.get(`/api/datasets/${id}/history`)).data })
  const { data: versions } = useQuery({ queryKey:['versions',id], queryFn: async()=> (await api.get(`/api/datasets/${id}/versions`)).data })
  const { data: doctorData, isFetching: doctorFetching } = useQuery<any>({ queryKey:['doctor',id], queryFn: async()=> (await api.get(`/api/datasets/${id}/doctor`)).data })
  const { data: diffData } = useQuery<any>({ queryKey:['diff',id], queryFn: async()=> (await api.get(`/api/datasets/${id}/diff`)).data, enabled: showDiff })
  const { data: datasetType } = useQuery<any>({ queryKey:['type',id], queryFn: async()=> (await api.get(`/api/datasets/${id}/type`)).data })

  // AI plan query - uses POST (was GET bug). Scanning state handled via isFetching
  const { data: aiPlan, isFetching: aiPlanFetching, error: aiPlanError, refetch: refetchAiPlan } = useQuery<any>({
    queryKey:['ai-plan',id],
    queryFn: async()=>{
      // backend supports POST and GET; use POST for correct semantics
      const r = await api.post(`/api/datasets/${id}/clean/ai-plan`)
      return r.data
    },
    enabled: mode==='ai',
    retry: 1,
    staleTime: 30000,
  })

  useEffect(()=>{
    if(successMsg){
      const t = setTimeout(()=>setSuccessMsg(null), 4000)
      return ()=>clearTimeout(t)
    }
  },[successMsg])
  useEffect(()=>{
    if(errorMsg){
      const t = setTimeout(()=>setErrorMsg(null), 6000)
      return ()=>clearTimeout(t)
    }
  },[errorMsg])

  const columns = profile?.columns || []
  const currentVersionId = versions?.find((v:any)=>v.is_current)?.id

  // C13: invalidate all 16 dataset query keys on version restore / apply
  const invalidateAllDatasetQueries = (datasetId: string) => {
    const keys = ['profile','preview','doctor','ai-plan','diff','history','versions','type','eda','anomalies','lineage','metrics','monitors','workflow','next-action','recipe','ds']
    keys.forEach(k => qc.invalidateQueries({queryKey:[k, datasetId]}))
  }

  const formatError = (e:any): string => {
    const raw = e?.response?.data?.detail ?? e?.response?.data?.error ?? e?.message ?? 'Failed'
    if (typeof raw === 'string') return raw
    if (raw && typeof raw === 'object') {
      if ((raw as any).message) return String((raw as any).message)
      if ((raw as any).detail) {
        const d = (raw as any).detail
        return typeof d === 'string' ? d : JSON.stringify(d)
      }
      try { return JSON.stringify(raw) } catch { return String(raw) }
    }
    return String(raw)
  }

  const previewMutation = useMutation({
    mutationFn: async (payload:any)=>{
      const r = await api.post(`/api/datasets/${id}/clean/preview`, payload, {timeout: 15000})
      return r.data
    },
    onMutate: ()=>{ setPreviewError(null); setErrorMsg(null) },
    onSuccess: (data)=>{ setPreview(data); setPreviewError(null); setTimeout(()=>previewRef.current?.scrollIntoView({behavior:'smooth', block:'nearest'}), 100) },
    onError: (e:any)=>{ const msg = formatError(e); setPreviewError(msg); setPreview(null) }
  })

  const handlePreview = async()=>{
    setPreviewError(null)
    const payload = buildPayload(selectedOp, params)
    // quick client validation
    if(selectedOp==='missing' && payload.params?.method && !payload.params?.column && payload.params?.method!=='custom_value' && payload.params?.method!=='forward_fill' && payload.params?.method!=='backward_fill'){
      // fill_median etc without column will be treated as whole dataset? But we require column
      // Allow but warn
    }
    previewMutation.mutate(payload)
  }

  const applyMutation = useMutation({
    mutationFn: async(payload:any)=> {
      const p = {...payload}
      if(currentVersionId) p.expected_version_id = currentVersionId
      const r = await api.post(`/api/datasets/${id}/clean/apply`, p, {timeout: 30000})
      return r.data
    },
    onMutate: ()=>{ setErrorMsg(null); setSuccessMsg(null); setConflict(null) },
    onSuccess: (data)=>{
      const ver = data.version?.version_number ? `V${data.version.version_number}` : (data.version?.name || 'new version')
      setSuccessMsg(`Changes applied — Version ${ver}`)
      setPreview(null)
      if (id) invalidateAllDatasetQueries(id)
      setTimeout(()=>previewRef.current?.scrollIntoView({behavior:'smooth'}), 150)
    },
    onError: async (e:any, variables:any)=>{
      if(e.response?.status===409){
        const raw = e.response?.data?.detail || e.message || 'Version conflict — dataset was modified elsewhere'
        const msg = typeof raw === 'object' ? (raw.message || JSON.stringify(raw)) : String(raw)
        setConflict({payload: variables, message: msg})
        // C13: refresh all keys so UI reflects server state even before user resolves
        if (id) invalidateAllDatasetQueries(id)
        return
      }
      const msg = formatError(e)
      setErrorMsg(msg)
    }
  })

  const handleApply = ()=>{
    if(applyMutation.isPending) return
    const payload = buildPayload(selectedOp, params)
    applyMutation.mutate(payload)
  }

  const handleUndo = async()=>{
    setErrorMsg(null)
    try{
      await api.post(`/api/datasets/${id}/history/undo`, {}, {timeout:15000})
      setSuccessMsg('Undone — reverted to previous version')
      if (id) invalidateAllDatasetQueries(id)
    }catch(e:any){ setErrorMsg(formatError(e))}
  }
  const handleRedo = async()=>{
    setErrorMsg(null)
    try{
      await api.post(`/api/datasets/${id}/history/redo`, {}, {timeout:15000})
      setSuccessMsg('Redone — change re-applied')
      if (id) invalidateAllDatasetQueries(id)
    }catch(e:any){ setErrorMsg(formatError(e))}
  }

  const doctorApplyMutation = useMutation({
    mutationFn: async(issue:any)=>{
      const r = await api.post(`/api/datasets/${id}/doctor/apply`, {issue_ids:[issue.id]}, {timeout:30000})
      return r.data
    },
    onSuccess: (data)=>{
      const ver = data.version?.version_number ? `V${data.version.version_number}` : ''
      setSuccessMsg(`Doctor fix applied — Version ${ver}`)
      if (id) invalidateAllDatasetQueries(id)
    },
    onError: (e:any)=>{ setErrorMsg(formatError(e)) }
  })
  const applyDoctorIssue = async(issue:any)=>{
    if(doctorApplyMutation.isPending) return
    doctorApplyMutation.mutate(issue)
  }

  // AI plan apply - uses same deterministic engine
  const aiApplyMutation = useMutation({
    mutationFn: async(selectedSteps?:number[])=>{
      const payload = selectedSteps ? {selected_steps:selectedSteps, apply_all:false} : {apply_all:true}
      const r = await api.post(`/api/datasets/${id}/clean/ai-apply`, payload, {timeout:30000})
      return r.data
    },
    onSuccess: (data)=>{
      const ver = data.version?.version_number ? `V${data.version.version_number}` : ''
      setSuccessMsg(`AI plan applied — Version ${ver} (${data.applied?.length||0} steps)`)
      if (id) invalidateAllDatasetQueries(id)
    },
    onError: (e:any)=>{ setErrorMsg(formatError(e)) }
  })
  const applyAiPlan = async(selectedSteps?:number[])=>{ if(aiApplyMutation.isPending) return; aiApplyMutation.mutate(selectedSteps) }

  const score = profile?.quality_details?.score ?? dataset?.quality_score ?? 0
  const isApplying = applyMutation.isPending || doctorApplyMutation.isPending || aiApplyMutation.isPending

  return (
    <div className={`${isDrawer ? 'space-y-4 p-0' : 'space-y-4'}`}>
      {/* Header — health bar - hidden in drawer mode (drawer provides title) */}
      {!isDrawer && <div className="rounded-[20px] border bg-white dark:bg-white/[0.04] dark:border-white/10 p-4">
        <div className="flex flex-col lg:flex-row justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-xs"><Link to={`/datasets/${id}`} className="text-slate-500 hover:text-slate-900 dark:text-white/50">{dataset?.name}</Link><span className="text-slate-300">/</span><span className="font-medium">Cleaning Studio</span><span className="hidden sm:inline-flex items-center gap-1 rounded-full bg-[#0b0d18] text-white dark:bg-white dark:text-[#0b0d18] px-2 py-0.5 text-[11px]"><Sparkles className="h-3 w-3" /> Workstation</span></div>
            <h1 className="text-[20px] font-semibold tracking-tight mt-1">Data Cleaning Studio <span className="text-slate-500 font-normal hidden sm:inline">— {dataset?.name}</span></h1>
            <div className="flex flex-wrap gap-2 mt-2 text-[11px]">
              {datasetType?.dataset_type && <span className="rounded-full border bg-slate-50 px-2.5 py-1 dark:bg-white/5 dark:border-white/10">Detected: {datasetType.dataset_type} ({datasetType.confidence}%)</span>}
              <span className="rounded-full border bg-slate-50 px-2.5 py-1 dark:bg-white/5 dark:border-white/10 flex items-center gap-1"><Gauge className="h-3 w-3" /> {score}/100 quality</span>
              <span className="rounded-full border bg-slate-50 px-2.5 py-1 dark:bg-white/5 dark:border-white/10">{profile?.row_count ?? dataset?.row_count} rows</span>
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <select value={versions?.find((v:any)=>v.is_current)?.id || ''} onChange={async(e)=>{
              try{
                await api.post(`/api/datasets/${id}/versions/${e.target.value}/restore`)
                if (id) invalidateAllDatasetQueries(id)
                setSuccessMsg(`Restored to V${versions?.find((v:any)=>v.id===e.target.value)?.version_number ?? ''}`)
              }catch(err:any){ setErrorMsg(formatError(err)) }
            }} className="text-sm border rounded-full px-3 py-2 bg-white dark:bg-white/5 dark:border-white/10 h-9">
              {versions?.map((v:any)=><option key={v.id} value={v.id}>V{v.version_number}: {v.name} {v.is_current?'• current':''}</option>)}
            </select>
            <Button variant="outline" size="sm" onClick={handleUndo} disabled={isApplying || !history || history.history.filter((h:any)=>!h.undone).length===0}><Undo2 className="h-3.5 w-3.5 mr-1" />Undo</Button>
            <Button variant="outline" size="sm" onClick={handleRedo} disabled={isApplying || !history || history.history.filter((h:any)=>h.undone).length===0}><Redo2 className="h-3.5 w-3.5 mr-1" />Redo</Button>
            <Button variant={showDiff?'default':'outline'} size="sm" onClick={()=>setShowDiff(!showDiff)}><GitCompare className="h-3.5 w-3.5 mr-1" />{showDiff?'Hide Diff':'Before/After'}</Button>
          </div>
        </div>
        {/* health meter */}
        <div className="mt-4 grid grid-cols-12 gap-3 items-center">
          <div className="col-span-12 lg:col-span-8">
            <div className="h-1.5 rounded-full bg-slate-100 dark:bg-white/10 overflow-hidden flex">
              <div className="bg-emerald-500" style={{width:`${Math.min(score,100)}%`}} />
              <div className="bg-slate-200 dark:bg-white/10 flex-1" />
            </div>
            <div className="flex justify-between text-[11px] text-slate-500 dark:text-white/50 mt-1"><span>Original immutable • every change reversible</span><span className="font-medium text-slate-900 dark:text-white">{score}/100</span></div>
          </div>
          <div className="col-span-12 lg:col-span-4 flex gap-2 justify-end">
            <Button variant={mode==='manual'?'default':'outline'} size="sm" onClick={()=>{setMode('manual'); setErrorMsg(null)}} disabled={isApplying}>Manual</Button>
            <Button variant={mode==='ai'?'default':'outline'} size="sm" onClick={()=>{setMode('ai'); setErrorMsg(null); if(mode!=='ai') refetchAiPlan()}} disabled={isApplying}><Sparkles className="h-3.5 w-3.5 mr-1" />Clean with AI</Button>
          </div>
        </div>
        {(successMsg || errorMsg) && (
          <div className={`mt-3 rounded-[12px] border p-3 text-xs flex items-center gap-2 ${successMsg ? 'bg-emerald-50 border-emerald-200 text-emerald-800 dark:bg-emerald-500/10 dark:border-emerald-500/20 dark:text-emerald-300' : 'bg-red-50 border-red-200 text-red-700 dark:bg-red-500/10 dark:border-red-500/20 dark:text-red-300'}`}>
            {successMsg ? <CheckCircle2 className="h-4 w-4 shrink-0" /> : <AlertTriangle className="h-4 w-4 shrink-0" />}
            <span className="flex-1">{successMsg || errorMsg}</span>
            <button onClick={()=>{setSuccessMsg(null); setErrorMsg(null)}} className="text-[11px] underline">Dismiss</button>
          </div>
        )}
      </div>}

      {isDrawer && (successMsg || errorMsg) && (
        <div className={`rounded-[12px] border p-3 text-xs flex items-center gap-2 ${successMsg ? 'bg-emerald-50 border-emerald-200 text-emerald-800 dark:bg-emerald-500/10 dark:border-emerald-500/20 dark:text-emerald-300' : 'bg-red-50 border-red-200 text-red-700 dark:bg-red-500/10 dark:border-red-500/20 dark:text-red-300'}`}>
          {successMsg ? <CheckCircle2 className="h-4 w-4 shrink-0" /> : <AlertTriangle className="h-4 w-4 shrink-0" />}
          <span className="flex-1">{successMsg || errorMsg}</span>
          <button onClick={()=>{setSuccessMsg(null); setErrorMsg(null)}} className="text-[11px] underline">Dismiss</button>
        </div>
      )}

      {/* C14: ConflictModal on 409 Version Conflict */}
      {conflict && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-label="Version Conflict">
          <div className="max-w-md w-full rounded-[16px] border bg-white dark:bg-[#0f1220] dark:border-white/10 p-5 shadow-xl">
            <h3 className="font-semibold text-sm flex items-center gap-2"><AlertTriangle className="h-4 w-4 text-amber-600"/> Version Conflict (409)</h3>
            <p className="text-xs text-slate-600 dark:text-white/60 mt-2">{conflict.message}</p>
            <p className="text-xs text-slate-500 mt-2">Another change was applied. Your version is stale — choose how to resolve.</p>
            <div className="flex flex-wrap gap-2 mt-4">
              <Button size="sm" onClick={async()=>{ if (id) invalidateAllDatasetQueries(id); setConflict(null); setSuccessMsg('Refreshed to latest version — please retry your change')}}>Accept Theirs — Refresh</Button>
              <Button size="sm" variant="outline" onClick={()=>{ const p = conflict.payload; setConflict(null); if (p) applyMutation.mutate(p)}}>Keep Mine — Retry</Button>
              <Button size="sm" variant="outline" onClick={()=> setConflict(null)}>Cancel</Button>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-12 gap-4">
        {/* LEFT: Tool rail */}
        <div className="col-span-12 lg:col-span-3 space-y-3">
          <Card className="overflow-hidden">
            <div className="h-1 bg-gradient-to-r from-[#6d6af0] to-[#38bdf8]" />
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2"><Layers className="h-4 w-4" /> Tool Rail</CardTitle>
              <p className="text-xs text-slate-500">Select an operation — preview before apply.</p>
            </CardHeader>
            <CardContent className="space-y-3">
              {mode==='manual' && (
                <div className="space-y-3">
                  <div className="grid grid-cols-2 gap-1.5">
                    {[
                      ['missing','Missing','◐'],
                      ['remove_duplicates','Dedup','◎'],
                      ['column','Columns','▭'],
                      ['text','Text','Aa'],
                      ['numeric','Numeric','#'],
                      ['date','Date','◷'],
                      ['row_filter','Rows','≡'],
                    ].map(([key,label,icon])=>(
                      <button key={key} onClick={()=>{setSelectedOp(key); setPreview(null); setPreviewError(null)}} disabled={isApplying} className={`p-2.5 rounded-[12px] border text-center text-xs font-medium transition-all ${selectedOp===key?'bg-[#0b0d18] text-white border-[#0b0d18] dark:bg-white dark:text-[#0b0d18] shadow-sm':'bg-white hover:bg-slate-50 dark:bg-white/5 dark:border-white/10 dark:hover:bg-white/10'} disabled:opacity-50`}>
                        <div className="text-[13px]">{icon}</div>{label}
                      </button>
                    ))}
                  </div>

                  {selectedOp==='missing' && (
                    <div className="space-y-2 border-t dark:border-white/10 pt-3">
                      <div className="text-xs font-semibold">Missing Values</div>
                      <select value={params.column||''} onChange={e=>setParams({...params, column:e.target.value})} disabled={isApplying} className="w-full h-9 rounded-full border px-3 text-sm bg-white dark:bg-white/5 dark:border-white/10">
                        <option value="">Select column</option>{columns.map((c:any)=><option key={c.id} value={c.name}>{c.name} ({c.null_percentage.toFixed(1)}%)</option>)}
                      </select>
                      <select value={params.method||'fill_median'} onChange={e=>setParams({...params, method:e.target.value})} disabled={isApplying} className="w-full h-9 rounded-full border px-3 text-sm bg-white dark:bg-white/5 dark:border-white/10">
                        <option value="drop_rows">Drop rows</option><option value="fill_mean">Fill with mean</option><option value="fill_median">Fill with median</option><option value="fill_mode">Fill with mode</option><option value="forward_fill">Forward fill</option><option value="backward_fill">Backward fill</option><option value="custom_value">Custom value</option>
                      </select>
                      {params.method==='custom_value' && <input placeholder="Custom value" value={params.custom_value||''} onChange={e=>setParams({...params, custom_value:e.target.value})} disabled={isApplying} className="w-full h-9 rounded-full border px-3 text-sm bg-white dark:bg-white/5 dark:border-white/10"/>}
                      <div className="text-[11px] text-slate-500 rounded-full border bg-slate-50 px-3 py-1 dark:bg-white/5 dark:border-white/10">Affected: preview before applying</div>
                    </div>
                  )}

                  {selectedOp==='remove_duplicates' && (
                    <div className="space-y-2 border-t dark:border-white/10 pt-3">
                      <div className="text-xs font-semibold">Duplicates</div>
                      <div className="text-xs text-slate-600 dark:text-white/60">Exact duplicate rows will be removed. Preview first.</div>
                      {profile?.duplicates !== undefined && <div className="text-xs rounded-full border bg-amber-50 border-amber-200 px-3 py-1 dark:bg-amber-500/10 dark:border-amber-500/20">Current duplicates: {profile.duplicates}</div>}
                    </div>
                  )}

                  {selectedOp==='column' && (
                    <div className="space-y-2 border-t dark:border-white/10 pt-3">
                      <div className="text-xs font-semibold">Column Operations</div>
                      <select value={params.sub_operation||'rename'} onChange={e=>setParams({...params, sub_operation:e.target.value})} disabled={isApplying} className="w-full h-9 rounded-full border px-3 text-sm bg-white dark:bg-white/5 dark:border-white/10">
                        <option value="rename">Rename column</option><option value="remove">Remove column</option><option value="change_type">Change datatype</option>
                      </select>
                      {(params.sub_operation==='rename' || !params.sub_operation) && <>
                        <select value={params.old_name||''} onChange={e=>setParams({...params, old_name:e.target.value})} disabled={isApplying} className="w-full h-9 rounded-full border px-3 text-sm bg-white dark:bg-white/5 dark:border-white/10"><option value="">Old name</option>{columns.map((c:any)=><option key={c.id} value={c.name}>{c.name}</option>)}</select>
                        <input placeholder="New name" value={params.new_name||''} onChange={e=>setParams({...params, new_name:e.target.value})} disabled={isApplying} className="w-full h-9 rounded-full border px-3 text-sm bg-white dark:bg-white/5 dark:border-white/10"/>
                      </>}
                      {params.sub_operation==='remove' && <select value={params.column||''} onChange={e=>setParams({...params, column:e.target.value})} disabled={isApplying} className="w-full h-9 rounded-full border px-3 text-sm bg-white dark:bg-white/5 dark:border-white/10"><option value="">Column to remove</option>{columns.map((c:any)=><option key={c.id} value={c.name}>{c.name}</option>)}</select>}
                      {params.sub_operation==='change_type' && <>
                        <select value={params.column||''} onChange={e=>setParams({...params, column:e.target.value})} disabled={isApplying} className="w-full h-9 rounded-full border px-3 text-sm bg-white dark:bg-white/5 dark:border-white/10"><option value="">Column</option>{columns.map((c:any)=><option key={c.id} value={c.name}>{c.name}</option>)}</select>
                        <select value={params.dtype||'numeric'} onChange={e=>setParams({...params, dtype:e.target.value})} disabled={isApplying} className="w-full h-9 rounded-full border px-3 text-sm bg-white dark:bg-white/5 dark:border-white/10"><option value="numeric">Numeric</option><option value="datetime">Datetime</option><option value="string">String</option></select>
                      </>}
                    </div>
                  )}

                  {selectedOp==='text' && (
                    <div className="space-y-2 border-t dark:border-white/10 pt-3">
                      <div className="text-xs font-semibold">Text Cleaning</div>
                      <select value={params.column||''} onChange={e=>setParams({...params, column:e.target.value})} disabled={isApplying} className="w-full h-9 rounded-full border px-3 text-sm bg-white dark:bg-white/5 dark:border-white/10"><option value="">Column</option>{columns.filter((c:any)=>c.data_type.includes('object')||c.data_type.includes('string')).map((c:any)=><option key={c.id} value={c.name}>{c.name}</option>)}</select>
                      <select value={params.sub_operation||'trim'} onChange={e=>setParams({...params, sub_operation:e.target.value})} disabled={isApplying} className="w-full h-9 rounded-full border px-3 text-sm bg-white dark:bg-white/5 dark:border-white/10"><option value="trim">Trim whitespace</option><option value="lowercase">Lowercase</option><option value="uppercase">Uppercase</option><option value="find_replace">Find and replace</option></select>
                      {params.sub_operation==='find_replace' && <><input placeholder="Find" value={params.find||''} onChange={e=>setParams({...params, find:e.target.value})} disabled={isApplying} className="w-full h-9 rounded-full border px-3 text-sm bg-white dark:bg-white/5 dark:border-white/10"/><input placeholder="Replace" value={params.replace||''} onChange={e=>setParams({...params, replace:e.target.value})} disabled={isApplying} className="w-full h-9 rounded-full border px-3 text-sm bg-white dark:bg-white/5 dark:border-white/10"/></>}
                    </div>
                  )}

                  {selectedOp==='numeric' && (
                    <div className="space-y-2 border-t dark:border-white/10 pt-3">
                      <div className="text-xs font-semibold">Numeric Cleaning</div>
                      <select value={params.column||''} onChange={e=>setParams({...params, column:e.target.value})} disabled={isApplying} className="w-full h-9 rounded-full border px-3 text-sm bg-white dark:bg-white/5 dark:border-white/10"><option value="">Column</option>{columns.filter((c:any)=>c.mean_value!=null).map((c:any)=><option key={c.id} value={c.name}>{c.name}</option>)}</select>
                      <select value={params.sub_operation||'convert_to_numeric'} onChange={e=>setParams({...params, sub_operation:e.target.value})} disabled={isApplying} className="w-full h-9 rounded-full border px-3 text-sm bg-white dark:bg-white/5 dark:border-white/10"><option value="convert_to_numeric">Convert to numeric</option><option value="handle_outliers">Handle outliers</option></select>
                    </div>
                  )}

                  {selectedOp==='date' && (
                    <div className="space-y-2 border-t dark:border-white/10 pt-3">
                      <div className="text-xs font-semibold">Date Cleaning</div>
                      <select value={params.column||''} onChange={e=>setParams({...params, column:e.target.value})} disabled={isApplying} className="w-full h-9 rounded-full border px-3 text-sm bg-white dark:bg-white/5 dark:border-white/10"><option value="">Column</option>{columns.map((c:any)=><option key={c.id} value={c.name}>{c.name}</option>)}</select>
                      <select value={params.sub_operation||'convert_to_datetime'} onChange={e=>setParams({...params, sub_operation:e.target.value})} disabled={isApplying} className="w-full h-9 rounded-full border px-3 text-sm bg-white dark:bg-white/5 dark:border-white/10"><option value="convert_to_datetime">Convert to datetime</option><option value="standardize_format">Standardize format</option></select>
                    </div>
                  )}

                  {selectedOp==='row_filter' && (
                    <div className="space-y-2 border-t dark:border-white/10 pt-3">
                      <div className="text-xs font-semibold">Row Filtering</div>
                      <select value={params.column||''} onChange={e=>setParams({...params, column:e.target.value})} disabled={isApplying} className="w-full h-9 rounded-full border px-3 text-sm bg-white dark:bg-white/5 dark:border-white/10"><option value="">Column</option>{columns.map((c:any)=><option key={c.id} value={c.name}>{c.name}</option>)}</select>
                      <input placeholder="Value to filter" value={params.value||''} onChange={e=>setParams({...params, value:e.target.value})} disabled={isApplying} className="w-full h-9 rounded-full border px-3 text-sm bg-white dark:bg-white/5 dark:border-white/10"/>
                    </div>
                  )}

                  {previewError && <div className="rounded-[12px] border bg-red-50 border-red-200 p-2 text-xs text-red-700 dark:bg-red-500/10 dark:border-red-500/20 dark:text-red-300 flex gap-2 items-center"><AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" /><span className="flex-1">{previewError}</span><Button size="sm" variant="outline" className="h-7 text-xs shrink-0" onClick={handlePreview} disabled={previewMutation.isPending}>Retry</Button></div>}

                  <div className="flex gap-2 pt-2">
                    <Button size="sm" variant="outline" onClick={handlePreview} disabled={previewMutation.isPending || isApplying} className="flex-1">{previewMutation.isPending ? 'Previewing…' : <><Eye className="h-3.5 w-3.5 mr-1" />Preview</>}</Button>
                    <Button size="sm" onClick={handleApply} disabled={applyMutation.isPending || isApplying} className="flex-1">{applyMutation.isPending?'Applying…':'Apply'}</Button>
                  </div>
                  <div className="text-[11px] text-slate-500 text-center">Preview is cheap — Apply creates a new version</div>
                </div>
              )}

              {mode==='ai' && (
                <div className="space-y-3">
                  <div className="rounded-[12px] border bg-gradient-to-br from-[#0b0d18] to-[#1a1d2e] text-white p-3 dark:border-white/10">
                    <div className="text-xs font-semibold flex items-center gap-1.5"><Sparkles className="h-3.5 w-3.5" /> Clean with AI</div>
                    <div className="text-[11px] opacity-70 mt-1">Proposed plan • you approve everything</div>
                  </div>
                  {(aiPlanFetching) && <div className="rounded-[12px] border bg-slate-50 p-3 text-xs dark:bg-white/5 dark:border-white/10 flex items-center gap-2"><span className="h-4 w-4 border-2 border-slate-300 border-t-[#6d6af0] rounded-full animate-spin" />Scanning dataset…</div>}
                  {aiPlanError && !aiPlanFetching && <div className="rounded-[12px] border bg-red-50 border-red-200 p-2 text-xs text-red-700 dark:bg-red-500/10 dark:border-red-500/20">Scan failed: {(aiPlanError as any)?.response?.data?.detail || (aiPlanError as any)?.message || 'Unknown'} <button onClick={()=>refetchAiPlan()} className="underline ml-2">Retry</button></div>}
                  {!aiPlanFetching && !aiPlanError && !aiPlan ? <div className="space-y-2">{Array.from({length:3}).map((_,i)=><div key={i} className="h-14 shimmer rounded-[12px]" />)}</div> : null}
                  {!aiPlanFetching && aiPlan && (
                    <div className="space-y-2">
                      {aiPlan.plan?.map((step:any)=><div key={step.step} className="rounded-[12px] border p-3 text-xs bg-slate-50 dark:bg-white/5 dark:border-white/10">
                        <div className="font-medium flex justify-between"><span>{step.step}. {step.title}</span><Badge variant={step.severity==='Critical'?'danger':step.severity==='Warning'?'warning':'muted'}>{step.severity}</Badge></div>
                        <div className="text-slate-600 dark:text-white/60 mt-1 leading-relaxed">{step.recommendation}</div>
                        <div className="mt-1 text-slate-500">{step.affected_rows} rows • {step.operation?.op}:{step.operation?.params?.column || step.operation?.params?.old_name || ''}</div>
                        <div className="mt-2 flex gap-2">
                          <Button size="sm" className="h-7 text-xs flex-1" disabled={aiApplyMutation.isPending} onClick={()=> applyAiPlan([step.step])}>{aiApplyMutation.isPending? 'Applying…':'Apply'}</Button>
                          <Button size="sm" variant="outline" className="h-7 text-xs" onClick={()=> setSuccessMsg('Issue ignored — you can revisit in history')}>Reject</Button>
                        </div>
                      </div>)}
                      {aiPlan.plan?.length===0 && <div className="text-xs rounded-full border bg-emerald-50 px-3 py-2 dark:bg-emerald-500/10 dark:border-emerald-500/20">No issues — dataset looks healthy.</div>}
                      {aiPlan.plan?.length>0 && (
                        <div className="flex gap-2">
                          <Button size="sm" onClick={()=>applyAiPlan()} disabled={aiApplyMutation.isPending} className="flex-1">{aiApplyMutation.isPending?'Applying…':'Apply All'}</Button>
                          <Button size="sm" variant="outline" onClick={()=>applyAiPlan(aiPlan.plan.slice(0,2).map((s:any)=>s.step))} disabled={aiApplyMutation.isPending}>Top 2</Button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2"><CardTitle className="text-xs flex items-center gap-2"><Clock className="h-3.5 w-3.5" /> Timeline</CardTitle></CardHeader>
            <CardContent>
              {!history || history.history.length===0 ? <div className="text-xs text-slate-500 rounded-full border bg-slate-50 px-3 py-2 dark:bg-white/5 dark:border-white/10">No transformations — original dataset</div> : (
                <div className="space-y-1 text-xs">
                  <div className="flex items-center gap-1.5 font-medium"><span className="w-2 h-2 bg-[#0b0d18] dark:bg-white rounded-full" /> Original Dataset</div>
                  <div className="ml-[3px] border-l dark:border-white/10 pl-3 space-y-1.5 py-1">
                    {history.history.map((h:any, idx:number)=><div key={h.id} className={`flex items-center gap-1.5 ${h.undone?'opacity-40 line-through':'font-medium'}`}><span className="w-1.5 h-1.5 rounded-full bg-white border dark:bg-white/20" />{idx+1}. {h.operation}</div>)}
                  </div>
                  <div className="text-slate-500 pt-1">→ Current Dataset</div>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* CENTER: Grid */}
        <div className="col-span-12 lg:col-span-5 space-y-3">
          <Card className="overflow-hidden">
            <CardHeader className="pb-2 flex flex-row justify-between items-center">
              <CardTitle className="text-sm flex items-center gap-2"><Activity className="h-4 w-4" /> Data Preview</CardTitle>
              <span className="text-xs rounded-full border bg-slate-50 px-2.5 py-1 dark:bg-white/5 dark:border-white/10">{previewData?.total_rows ?? '—'} rows</span>
            </CardHeader>
            <CardContent>
              {!previewData ? <div className="space-y-2">{Array.from({length:4}).map((_,i)=><div key={i} className="h-6 shimmer rounded-full" />)}</div> : (
                <div className="overflow-auto rounded-[12px] border dark:border-white/10 max-h-[380px]">
                  <table className="min-w-full text-xs">
                    <thead className="bg-slate-50 dark:bg-white/5 sticky top-0"><tr>{Object.keys(previewData.rows[0]||{}).map(k=><th key={k} className="px-3 py-2 text-left whitespace-nowrap border-b dark:border-white/10 text-[11px] font-semibold tracking-wide">{k}</th>)}</tr></thead>
                    <tbody>{previewData.rows.map((r:any,i:number)=><tr key={i} className="border-t dark:border-white/10 hover:bg-slate-50 dark:hover:bg-white/5">{Object.values(r).map((v:any, idx)=><td key={idx} className="px-3 py-1.5 whitespace-nowrap">{v===null?<span className="text-slate-400">—</span>:String(v).slice(0,40)}</td>)}</tr>)}</tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          {preview && (
            <Card ref={previewRef as any} className="border-amber-200 dark:border-amber-500/20 overflow-hidden">
              <div className="h-1 bg-amber-500" />
              <CardHeader className="pb-2"><CardTitle className="text-sm">Preview — Before / After</CardTitle></CardHeader>
              <CardContent className="space-y-2 text-xs">
                <div className="rounded-full border bg-slate-50 px-3 py-2 dark:bg-white/5 dark:border-white/10 inline-flex">Before: {preview.before_shape?.[0]}×{preview.before_shape?.[1]} → After: {preview.after_shape?.[0]}×{preview.after_shape?.[1]}</div>
                <div className="bg-slate-50 p-2 rounded-[12px] border dark:bg-white/5 dark:border-white/10 text-slate-700 dark:text-white/70">Stats: {JSON.stringify(preview.stats)}</div>
                <div className="grid grid-cols-2 gap-2">
                  <div><div className="font-medium mb-1">Before</div><pre className="bg-white border p-2 rounded-[12px] overflow-auto text-[11px] dark:bg-white/5 dark:border-white/10">{JSON.stringify(preview.before_rows, null, 2)}</pre></div>
                  <div><div className="font-medium mb-1">After</div><pre className="bg-white border p-2 rounded-[12px] overflow-auto text-[11px] dark:bg-white/5 dark:border-white/10">{JSON.stringify(preview.after_rows, null, 2)}</pre></div>
                </div>
                <Button size="sm" onClick={handleApply} disabled={applyMutation.isPending}>{applyMutation.isPending?'Applying…':'Confirm Apply'}</Button>
              </CardContent>
            </Card>
          )}

          {showDiff && diffData && (
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2"><GitCompare className="h-4 w-4" /> Before / After Diff</CardTitle></CardHeader>
              <CardContent className="text-xs space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <div className="rounded-[16px] border p-3 dark:border-white/10"><div className="font-semibold">BEFORE</div><div className="mt-2 space-y-1 text-slate-600 dark:text-white/60"><div>{diffData.rows.before} rows</div><div>{diffData.columns.before} cols</div><div>{diffData.missing_cells.before} missing</div><div>{diffData.duplicates.before} dup</div><div>Quality {diffData.quality.before}</div></div></div>
                  <div className="rounded-[16px] border p-3 bg-emerald-50 dark:bg-emerald-500/10 dark:border-emerald-500/20"><div className="font-semibold">AFTER</div><div className="mt-2 space-y-1"><div>{diffData.rows.after} rows</div><div>{diffData.columns.after} cols</div><div>{diffData.missing_cells.after} missing</div><div>{diffData.duplicates.after} dup</div><div>Quality {diffData.quality.after} (Δ {diffData.quality.delta})</div></div></div>
                </div>
                {diffData.changes_applied && (
                  <div className="rounded-[12px] border bg-white dark:bg-white/5 dark:border-white/10 p-3 space-y-2">
                    <div className="font-semibold text-xs">Changes Applied</div>
                    <div className="space-y-1 text-xs">
                      <div className="flex items-center gap-1.5"><span className="text-emerald-600">✓</span>{diffData.changes_applied.missing_resolved} missing values resolved</div>
                      <div className="flex items-center gap-1.5"><span className="text-emerald-600">✓</span>{diffData.changes_applied.rows_removed} rows removed</div>
                      <div className="flex items-center gap-1.5"><span className="text-emerald-600">✓</span>{diffData.changes_applied.duplicates_removed} duplicates removed</div>
                      <div className="flex items-center gap-1.5"><span className="text-emerald-600">✓</span>{diffData.changes_applied.columns_added?.length||0} columns added</div>
                      <div className="flex items-center gap-1.5"><span className="text-emerald-600">✓</span>{diffData.changes_applied.columns_removed?.length||0} columns removed</div>
                    </div>
                    <div className="rounded-full border bg-slate-50 px-3 py-1 text-xs dark:bg-white/5 dark:border-white/10">Quality {diffData.changes_applied.quality_before} → {diffData.changes_applied.quality_after} ({diffData.changes_applied.quality_delta>0?`+${diffData.changes_applied.quality_delta}`:diffData.changes_applied.quality_delta})</div>
                    {(diffData.columns_added?.length>0 || diffData.columns_removed?.length>0) && (
                      <div className="space-y-1 text-xs">
                        <div>Columns: {diffData.columns.before} → {diffData.columns.after}</div>
                        {diffData.columns_added?.length>0 && <div><span className="font-medium">Added:</span> {diffData.columns_added.join(", ")}</div>}
                        {diffData.columns_removed?.length>0 && <div><span className="font-medium">Removed:</span> {diffData.columns_removed.join(", ")}</div>}
                      </div>
                    )}
                  </div>
                )}
                <div className="overflow-auto rounded-[12px] border dark:border-white/10">
                  <table className="min-w-full text-xs">
                    <thead className="bg-slate-50 dark:bg-white/5"><tr className="border-b dark:border-white/10"><th className="text-left p-2">FIELD</th><th className="text-left p-2">BEFORE</th><th className="text-left p-2">AFTER</th></tr></thead>
                    <tbody className="divide-y dark:divide-white/10">
                      <tr><td className="p-2 font-medium">Rows</td><td className="p-2">{diffData.rows.before}</td><td className="p-2">{diffData.rows.after}</td></tr>
                      <tr><td className="p-2 font-medium">Columns</td><td className="p-2">{diffData.columns.before}</td><td className="p-2">{diffData.columns.after}</td></tr>
                      <tr><td className="p-2 font-medium">Missing values</td><td className="p-2">{diffData.missing_cells.before}</td><td className="p-2">{diffData.missing_cells.after}</td></tr>
                      <tr><td className="p-2 font-medium">Duplicates</td><td className="p-2">{diffData.duplicates.before}</td><td className="p-2">{diffData.duplicates.after}</td></tr>
                      <tr><td className="p-2 font-medium">Quality</td><td className="p-2">{diffData.quality.before}</td><td className="p-2">{diffData.quality.after}</td></tr>
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}
        </div>

        {/* RIGHT: AI Data Doctor */}
        <div className="col-span-12 lg:col-span-4 space-y-3">
          <Card className="overflow-hidden">
            <div className="h-1 bg-gradient-to-r from-[#6d6af0] via-[#38bdf8] to-emerald-500" />
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2"><Sparkles className="h-4 w-4 text-[#6d6af0]" /> AI Data Doctor</CardTitle>
              <p className="text-xs text-slate-500">{doctorData ? `${(doctorData as any).total_issues} issues detected` : 'Scanning with premium diagnostics…'}</p>
              {(!doctorData || doctorFetching) && <div className="mt-2 h-1 rounded-full bg-slate-100 dark:bg-white/10 overflow-hidden relative"><div className="absolute inset-y-0 w-1/3 bg-gradient-to-r from-[#6d6af0] to-[#38bdf8] animate-[drift_1.2s_ease_infinite]" /></div>}
            </CardHeader>
            <CardContent className="space-y-2.5 max-h-[620px] overflow-auto pr-1">
              {!doctorData ? <div className="space-y-2">{Array.from({length:3}).map((_,i)=><div key={i} className="h-24 shimmer rounded-[12px]" />)}</div> : (doctorData as any).issues.map((iss:any)=>(
                <div key={iss.id} className={`rounded-[16px] border p-3 text-xs relative overflow-hidden ${iss.severity==='Critical'?'bg-red-50 border-red-200 dark:bg-red-500/10 dark:border-red-500/20':iss.severity==='Warning'?'bg-amber-50 border-amber-200 dark:bg-amber-500/10 dark:border-amber-500/20':iss.severity==='Healthy'?'bg-emerald-50 border-emerald-200 dark:bg-emerald-500/10 dark:border-emerald-500/20':'bg-white dark:bg-white/5 dark:border-white/10'}`}>
                  <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-white/60 to-transparent opacity-60" style={{animation:'scan 2.5s linear infinite'}} />
                  <div className="flex justify-between items-center">
                    <span className={`font-semibold px-2 py-0.5 rounded-full text-[11px] ${iss.severity==='Critical'?'bg-red-600 text-white':iss.severity==='Warning'?'bg-amber-500 text-white':iss.severity==='Healthy'?'bg-emerald-600 text-white':'bg-slate-600 text-white'}`}>{iss.severity}</span>
                    <span className="text-slate-500 text-[11px] rounded-full border bg-white px-2 py-0.5 dark:bg-white/5 dark:border-white/10">{iss.type}</span>
                  </div>
                  <div className="font-semibold mt-2 text-[13px] leading-tight">{iss.title}</div>
                  <div className="mt-1.5 space-y-1 leading-relaxed">
                    <div><span className="font-medium">Problem:</span> {iss.problem}</div>
                    <div className="text-slate-600 dark:text-white/60"><span className="font-medium">Why:</span> {iss.why_it_matters}</div>
                    <div><span className="font-medium">Fix:</span> {iss.recommendation}</div>
                  </div>
                  {iss.column && <div className="mt-1 text-[11px] text-slate-500">Column: {iss.column} • Affected: {iss.affected_rows} rows</div>}
                  <div className="mt-2 rounded-[12px] border bg-white/70 p-2 dark:bg-white/5 dark:border-white/10 text-[11px]">Preview: {JSON.stringify(iss.preview)}</div>
                  {iss.operation && (
                    <div className="flex gap-2 mt-3">
                      <Button size="sm" className="h-7 text-xs flex-1" onClick={()=>applyDoctorIssue(iss)} disabled={doctorApplyMutation.isPending || isApplying}>{doctorApplyMutation.isPending?'Applying…':'Apply'}</Button>
                      <Button size="sm" variant="outline" className="h-7 text-xs" onClick={()=> setSuccessMsg('Issue ignored — you can revisit in history')}>Reject</Button>
                    </div>
                  )}
                </div>
              ))}
              <div className="text-[11px] text-slate-500 border-t dark:border-white/10 pt-3 flex items-center gap-1.5"><ShieldCheck className="h-3.5 w-3.5" /> AI never silently modifies — explicit approval required.</div>
            </CardContent>
          </Card>
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2"><Layers className="h-4 w-4" /> Cleaning Recipe</CardTitle></CardHeader>
          <CardContent className="text-xs space-y-2">
            <RecipeView datasetId={id!} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm flex items-center gap-2"><Gauge className="h-4 w-4" /> Health & Versions</CardTitle></CardHeader>
          <CardContent className="text-xs space-y-3">
            <div className="flex justify-between rounded-full border px-3 py-2 bg-slate-50 dark:bg-white/5 dark:border-white/10"><span>Current quality</span><span className="font-semibold">{profile?.quality_details?.score} / 100</span></div>
            <div className="text-slate-500">Versions: {versions?.length || 0} — <Link to={`/datasets/${id}`} className="underline">View detail</Link></div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" onClick={async()=>{ const name = prompt('Recipe name?') || 'My Recipe'; await api.post(`/api/datasets/${id}/recipe/save`, {name}); alert('Recipe saved')}}><Save className="h-3.5 w-3.5 mr-1" />Save Recipe</Button>
              <Button size="sm" variant="outline" onClick={async()=> authenticatedDownload(`/api/datasets/${id}/export?format=csv`)}><Download className="h-3.5 w-3.5 mr-1" />CSV</Button>
              <Button size="sm" variant="outline" onClick={async()=> authenticatedDownload(`/api/datasets/${id}/export/recipe`)}>Recipe JSON</Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}

function buildPayload(op:string, params:any){
  return {op, params}
}

function RecipeView({datasetId}:{datasetId:string}){
  const { data } = useQuery({ queryKey:['recipe',datasetId], queryFn: async()=> (await api.get(`/api/datasets/${datasetId}/recipe`)).data })
  if(!data) return <div className="space-y-2">{Array.from({length:2}).map((_,i)=><div key={i} className="h-8 shimmer rounded-full" />)}</div>
  if(data.recipe.length===0) return <div className="text-slate-500 rounded-full border bg-slate-50 px-3 py-2 dark:bg-white/5 dark:border-white/10">No operations yet — apply cleaning to generate recipe.</div>
  return <ol className="space-y-1">{data.recipe.map((r:any)=><li key={r.step} className="flex gap-2 rounded-full border px-3 py-2 bg-white dark:bg-white/5 dark:border-white/10"><span className="h-5 w-5 rounded-full bg-[#0b0d18] text-white dark:bg-white dark:text-[#0b0d18] grid place-items-center text-[11px] shrink-0">{r.step}</span><span className="truncate">{r.operation} — {JSON.stringify(r.params)}</span></li>)}</ol>
}
