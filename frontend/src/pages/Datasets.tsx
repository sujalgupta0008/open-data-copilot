import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import api from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle, Badge } from '@/components/common/Card'
import { Button } from '@/components/common/Button'
import { Input } from '@/components/common/Input'
import { Link } from 'react-router-dom'
import { Upload, Database, Gauge, Trash2, Sparkles, ArrowUpRight, Search, FileSpreadsheet, Check, Eye } from 'lucide-react'
import { NextStepCard } from '@/components/onboarding/Onboarding'
import { ErrorCard, LoadingState } from '@/components/common/ErrorCard'
import { HelpTooltip } from '@/components/common/HelpTooltip'

function qualityColor(score:number){
  if(score>=80) return "success"
  if(score>=50) return "warning"
  return "danger"
}
function healthDot(score:number){
  if(score>=80) return "bg-emerald-500"
  if(score>=50) return "bg-amber-500"
  return "bg-red-500"
}

export default function Datasets(){
  const [search,setSearch]=useState('')
  const [file,setFile]=useState<File|null>(null)
  const [dragOver,setDragOver]=useState(false)
  const [uploadErrorDetail, setUploadErrorDetail]=useState<string | null>(null)
  const qc=useQueryClient()
  const { data, isLoading } = useQuery({ queryKey:['datasets',search], queryFn: async()=> (await api.get('/api/datasets', { params:{ search }})).data })

  const uploadMut = useMutation({
    mutationFn: async()=>{
      if(!file) throw new Error('No file')
      const fd=new FormData(); fd.append('file',file)
      const res=await api.post('/api/datasets/upload', fd, { headers:{'Content-Type':'multipart/form-data'}})
      return res.data
    },
    onSuccess: (newDs:any)=>{ qc.invalidateQueries({queryKey:['datasets']}); setFile(null); setUploadErrorDetail(null); (window as any).__lastUploadId = newDs?.id; },
    onError: (err:any)=>{ setUploadErrorDetail(err?.response?.data?.detail || err.message) }
  })

  const delMut = useMutation({
    mutationFn: async(id:string)=> (await api.delete(`/api/datasets/${id}`)).data,
    onSuccess: ()=> qc.invalidateQueries({queryKey:['datasets']})
  })

  const onDrop=(e:any)=>{ e.preventDefault(); setDragOver(false); const f=e.dataTransfer.files?.[0]; if(f) setFile(f) }
  return (
    <div className="space-y-6">
      <div className="flex flex-col lg:flex-row justify-between gap-4">
        <div>
          <h1 className="text-[26px] font-semibold tracking-tight">Datasets</h1>
          <p className="text-sm text-slate-600 dark:text-white/60">Premium dataset health, quality, and lineage. Drag to upload.</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
            <Input placeholder="Search datasets…" className="pl-10 w-[220px]" value={search} onChange={(e:any)=>setSearch(e.target.value)}/>
          </div>
        </div>
      </div>

      <Card className="overflow-hidden">
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="flex items-center gap-2"><Upload className="h-4 w-4" /> Upload Dataset <HelpTooltip title="Upload">Upload a CSV, XLSX, JSON or Parquet file. We validate column consistency, check for duplicate headers, and generate a quality score. Max 50MB.</HelpTooltip></CardTitle>
          <span className="text-[11px] rounded-full border bg-slate-50 px-2 py-1 dark:bg-white/5 dark:border-white/10">CSV • XLSX • JSON • Parquet • 50MB</span>
        </CardHeader>
        <CardContent>
          <div onDragOver={e=>{e.preventDefault(); setDragOver(true)}} onDragLeave={()=>setDragOver(false)} onDrop={onDrop} className={`relative rounded-[20px] border-2 border-dashed p-8 text-center transition-all ${dragOver?'bg-[#0b0d18] border-[#0b0d18] text-white dark:bg-white dark:text-[#0b0d18]':'border-slate-200 bg-slate-50/60 dark:bg-white/[0.03] dark:border-white/10'}`}>
            <div className={`mx-auto h-12 w-12 rounded-full border grid place-items-center ${dragOver?'bg-white text-[#0b0d18] dark:bg-[#0b0d18] dark:text-white':'bg-white dark:bg-white/5'}`}><Upload className="h-5 w-5" /></div>
            <p className="text-sm font-medium mt-3">Drag & drop or click to select</p>
            <p className="text-xs text-slate-500 dark:text-white/50 mt-1">Supported: CSV, XLSX, JSON, Parquet — max 50MB. We check for ragged rows and duplicate columns.</p>
            <input type="file" accept=".csv,.xlsx,.xls,.json,.parquet" onChange={(e:any)=>setFile(e.target.files?.[0]||null)} className="mt-4 text-sm file:mr-3 file:rounded-full file:border file:bg-white file:px-4 file:py-1.5 file:text-sm file:font-medium dark:file:bg-white/10 dark:file:border-white/10" />
            {file && <div className="mt-3 inline-flex items-center gap-2 rounded-full border bg-white px-3 py-1.5 text-xs dark:bg-white/5 dark:border-white/10"><FileSpreadsheet className="h-3.5 w-3.5" /> {file.name} • {(file.size/1024).toFixed(1)} KB</div>}
            <div className="mt-4">
              <Button disabled={!file||uploadMut.isPending} onClick={()=>uploadMut.mutate()} className="rounded-full">{uploadMut.isPending?'Uploading…':'Upload dataset'}</Button>
            </div>
            {uploadMut.isPending && <div className="mt-3"><LoadingState message="Uploading dataset..." sub="Validating columns • Profiling • Checking data quality" /></div>}
            {uploadMut.isError && <div className="mt-3 max-w-[560px] mx-auto"><ErrorCard message={(uploadMut.error as any)?.response?.data?.detail||"Upload failed. Check the file matches the header row and has consistent columns."} detail={uploadErrorDetail || undefined} onRetry={()=>uploadMut.mutate()} /></div>}
            {uploadMut.isSuccess && (
              <div className="mt-4 space-y-3 text-left max-w-[560px] mx-auto">
                <div className="rounded-[12px] border bg-emerald-50 border-emerald-200 p-3 text-sm dark:bg-emerald-500/10 dark:border-emerald-500/20 flex items-center gap-2"><Check className="h-4 w-4 text-emerald-600" /> Upload successful — profiling complete</div>
                <div className="grid grid-cols-3 gap-2 text-xs"><span className="rounded-full border bg-white px-2 py-1 text-center dark:bg-white/5 dark:border-white/10 flex items-center justify-center gap-1"><Check className="h-3 w-3 text-emerald-600" /> Dataset uploaded</span><span className="rounded-full border bg-white px-2 py-1 text-center dark:bg-white/5 dark:border-white/10 flex items-center justify-center gap-1"><Check className="h-3 w-3 text-emerald-600" /> Profile generated</span><span className="rounded-full border bg-white px-2 py-1 text-center dark:bg-white/5 dark:border-white/10 flex items-center justify-center gap-1"><Check className="h-3 w-3 text-emerald-600" /> Quality checked</span></div>
                <NextStepCard title="Review Data Health" desc="Check quality score & AI Doctor issues before cleaning." primary={{label:"Review & Clean Data", to: uploadMut.data?.id ? `/datasets/${uploadMut.data.id}` : "/datasets"}} secondary={{label:"Explore Dataset", to: uploadMut.data?.id ? `/datasets/${uploadMut.data.id}` : "/datasets"}} icon={Eye} />
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {isLoading? (
        <div className="grid md:grid-cols-2 gap-4">{Array.from({length:4}).map((_,i)=><div key={i} className="h-[160px] rounded-[16px] border shimmer" />)}</div>
      ) : data?.length===0? (
        <Card><CardContent className="p-10 text-center">
          <div className="mx-auto h-16 w-16 rounded-[20px] border bg-slate-50 grid place-items-center dark:bg-white/5 dark:border-white/10"><Database className="h-6 w-6 text-slate-400" /></div>
          <div className="font-medium mt-4">No datasets yet</div>
          <div className="text-sm text-slate-500 dark:text-white/50">Upload your first dataset to see premium health cards.</div>
          <div className="mt-4 inline-flex items-center gap-2 text-xs text-slate-500"><span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> Ready when you are</div>
        </CardContent></Card>
      ) : (
        <div className="grid md:grid-cols-2 gap-4 stagger">
          {data?.map((d:any)=>(
            <Card key={d.id} className="group relative overflow-hidden">
              <div className="absolute inset-0 bg-gradient-to-br from-transparent to-slate-50/60 dark:to-white/[0.02] opacity-0 group-hover:opacity-100 transition-opacity" />
              <CardHeader className="flex flex-row items-start justify-between gap-3">
                <Link to={`/datasets/${d.id}`} className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className={`h-2 w-2 rounded-full ${healthDot(d.quality_score)} shadow-[0_0_8px_currentColor]`} />
                    <span className="font-semibold text-[15px] truncate hover:underline">{d.name}</span>
                  </div>
                  <div className="text-xs text-slate-500 dark:text-white/50 mt-1 flex flex-wrap gap-2"><span className="inline-flex items-center gap-1 rounded-full border bg-slate-50 px-2 py-0.5 dark:bg-white/5 dark:border-white/10">{d.file_type}</span><span>{d.row_count.toLocaleString()} rows • {d.column_count} cols</span></div>
                </Link>
                <Badge variant={qualityColor(d.quality_score)} className="shrink-0"><Gauge className="h-3 w-3 mr-1" />{d.quality_score}/100</Badge>
              </CardHeader>
              <CardContent className="relative">
                <div className="flex items-center gap-2 text-xs text-slate-500 dark:text-white/50">
                  <span className="inline-flex items-center gap-1"><Database className="h-3 w-3" /> {new Date(d.created_at).toLocaleDateString()}</span>
                  <span>•</span>
                  <span className="inline-flex items-center gap-1"><Sparkles className="h-3 w-3" /> Profiling complete</span>
                </div>
                <div className="mt-4 flex gap-2">
                  <Link to={`/datasets/${d.id}`}><Button variant="outline" size="sm">View <ArrowUpRight className="ml-1 h-3.5 w-3.5" /></Button></Link>
                  <Link to={`/datasets/${d.id}/copilot`}><Button size="sm">Analyze</Button></Link>
                  <Button variant="ghost" size="sm" onClick={()=> { if(confirm('Delete dataset?')) delMut.mutate(d.id)}} className="ml-auto"><Trash2 className="h-3.5 w-3.5 mr-1" /> Delete</Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
