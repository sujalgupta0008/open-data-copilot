import { useQuery } from '@tanstack/react-query'
import api from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/common/Card'
import { Link, useParams } from 'react-router-dom'
import { Button } from '@/components/common/Button'
import { MessageSquare, Database, Clock, ArrowUpRight, Sparkles } from 'lucide-react'

export default function AnalysisHistory(){
  const { data, isLoading } = useQuery({ queryKey:['analysis'], queryFn: async()=> (await api.get('/api/analysis')).data })
  if(isLoading) return <div className="space-y-3">{Array.from({length:3}).map((_,i)=><div key={i} className="h-[120px] shimmer rounded-[16px]" />)}</div>
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-[26px] font-semibold tracking-tight">Analysis</h1>
          <p className="text-sm text-slate-600 dark:text-white/60">All Copilot sessions — every insight is traceable.</p>
        </div>
        <Link to="/datasets"><Button variant="outline">New Analysis</Button></Link>
      </div>

      {data?.length===0? (
        <Card><CardContent className="p-10 text-center">
          <div className="mx-auto h-12 w-12 rounded-full border bg-slate-50 grid place-items-center dark:bg-white/5 dark:border-white/10"><MessageSquare className="h-5 w-5 text-slate-400" /></div>
          <div className="font-medium mt-3">No analyses yet</div>
          <div className="text-sm text-slate-500 dark:text-white/50">Go to a dataset and open Copilot to start.</div>
          <Link to="/datasets"><Button size="sm" className="mt-4">Browse Datasets</Button></Link>
        </CardContent></Card>
      ) : (
        <div className="grid md:grid-cols-2 gap-4 stagger">
          {data?.map((s:any)=>(
            <Card key={s.id} className="group">
              <CardHeader className="pb-2">
                <CardTitle className="text-[15px] flex justify-between items-start gap-3">
                  <span className="flex items-center gap-2"><span className="h-8 w-8 rounded-full bg-[#0b0d18] dark:bg-white grid place-items-center text-white dark:text-[#0b0d18]"><Sparkles className="h-3.5 w-3.5" /></span>{s.title}</span>
                  <span className="text-xs font-normal text-slate-500 rounded-full border bg-slate-50 px-2 py-1 dark:bg-white/5 dark:border-white/10 shrink-0">{new Date(s.updated_at).toLocaleString()}</span>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="text-sm text-slate-600 dark:text-white/60 flex items-center gap-2"><Database className="h-3.5 w-3.5" /> {s.dataset_name} • {s.message_count} messages</div>
                <Link to={`/analysis/${s.id}`}><Button variant="outline" size="sm" className="mt-3">Open <ArrowUpRight className="ml-1 h-3.5 w-3.5" /></Button></Link>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

export function AnalysisDetail(){
  const { id } = useParams<{ id: string }>()
  const { data, isLoading } = useQuery({ queryKey:['analysisDetail',id], queryFn: async()=> (await api.get(`/api/analysis/${id}`)).data, enabled: !!id })
  if(isLoading) return <div className="space-y-3 p-4">{Array.from({length:3}).map((_,i)=><div key={i} className="h-20 shimmer rounded-[16px]" />)}</div>
  if(!data) return <div>Not found</div>
  return (
    <div className="space-y-4 max-w-[860px] mx-auto">
      <div className="rounded-[20px] border bg-white dark:bg-white/[0.04] dark:border-white/10 p-5">
        <h1 className="text-[22px] font-semibold tracking-tight">{data.title}</h1>
        <div className="text-xs text-slate-500 mt-1 flex items-center gap-2"><Clock className="h-3 w-3" /> {new Date(data.updated_at).toLocaleString()} • {data.messages.length} messages</div>
      </div>
      <div className="space-y-3">
        {data.messages.map((m:any)=>(
          <div key={m.id} className={`rounded-[16px] border p-4 ${m.role==='user'?'bg-[#0b0d18] text-white dark:bg-white dark:text-[#0b0d18] border-transparent ml-auto max-w-[640px]':'bg-white dark:bg-white/[0.04] dark:border-white/10'}`}>
            <div className="text-xs opacity-60 mb-1 flex items-center gap-1.5">{m.role==='user'?'You':'Assistant'} • {new Date(m.created_at).toLocaleTimeString()}</div>
            <div className="text-sm whitespace-pre-wrap leading-relaxed">{m.content}</div>
            {m.generated_code && <pre className="mt-3 text-xs bg-black/80 text-white p-3 rounded-[12px] overflow-auto border border-white/10">{m.generated_code}</pre>}
          </div>
        ))}
      </div>
      <Link to={`/datasets/${data.dataset_id}/copilot`}><Button>Continue in Copilot <ArrowUpRight className="ml-1 h-3.5 w-3.5" /></Button></Link>
    </div>
  )
}
