import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import api from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/common/Card'

export default function SharedAnalysis(){
  const { token } = useParams()
  const { data, isLoading, error } = useQuery({
    queryKey:['shared-analysis', token],
    queryFn: async()=> (await api.get(`/api/shared/a/${token}`)).data,
    retry: false
  })
  if(isLoading) return <div className="min-h-screen grid place-items-center p-8"><div className="h-8 w-8 border-2 border-slate-300 border-t-[#6d6af0] rounded-full animate-spin" /></div>
  if(error){
    return <div className="min-h-screen flex flex-col items-center justify-center p-8 bg-[#f8f9fb] dark:bg-[#070914]">
      <div className="max-w-md text-center rounded-[16px] border bg-white dark:bg-[#0f1220] dark:border-white/10 p-8">
        <div className="text-lg font-semibold">This link has expired or is no longer active</div>
        <p className="text-sm text-slate-500 mt-2">The share link is invalid, expired, or was revoked.</p>
        <Link to="/signup" className="inline-block mt-4 rounded-full bg-[#0b0d18] text-white dark:bg-white dark:text-[#0b0d18] px-6 py-2 text-sm">Sign up free</Link>
        <div className="mt-4 text-xs text-slate-500">Powered by Open Data Copilot</div>
      </div>
    </div>
  }
  if(!data) return null
  return <div className="min-h-screen bg-[#f8f9fb] dark:bg-[#070914] p-4">
    <div className="max-w-[900px] mx-auto space-y-4">
      <div className="rounded-full bg-amber-50 border border-amber-200 px-4 py-2 text-sm text-amber-700 dark:bg-amber-500/10 dark:border-amber-500/20 text-center">View Only — Shared Analysis</div>
      <Card>
        <CardHeader><CardTitle>{data.title}</CardTitle><p className="text-xs text-slate-500">Session: {data.id} • Created: {new Date(data.created_at).toLocaleString()}</p></CardHeader>
        <CardContent className="space-y-3">
          {data.messages?.map((m:any)=>(
            <div key={m.id} className={`rounded-[12px] border p-3 ${m.role==='user'?'bg-slate-50 dark:bg-white/5':'bg-white dark:bg-white/[0.04]'} dark:border-white/10`}>
              <div className="text-xs font-medium">{m.role}</div>
              <div className="text-sm mt-1 whitespace-pre-wrap">{m.content}</div>
              {m.generated_code && <pre className="text-xs bg-[#0b0d18] text-slate-100 p-2 rounded-[8px] mt-2 overflow-auto">{m.generated_code.slice(0,600)}</pre>}
              {m.charts?.length>0 && <div className="text-xs mt-2 text-slate-500">{m.charts.length} chart(s)</div>}
            </div>
          ))}
        </CardContent>
      </Card>
      <div className="text-center text-xs text-slate-500 py-4 border-t dark:border-white/10">Powered by Open Data Copilot</div>
    </div>
  </div>
}
