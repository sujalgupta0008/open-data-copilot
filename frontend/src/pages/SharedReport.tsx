import { useParams, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import api from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/common/Card'

export default function SharedReport(){
  const { token } = useParams()
  const { data, isLoading, error } = useQuery({
    queryKey:['shared-report', token],
    queryFn: async()=> (await api.get(`/api/shared/r/${token}`)).data,
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
  const content = data.content || {}
  return <div className="min-h-screen bg-[#f8f9fb] dark:bg-[#070914] p-4">
    <div className="max-w-[900px] mx-auto space-y-4">
      <div className="rounded-full bg-amber-50 border border-amber-200 px-4 py-2 text-sm text-amber-700 dark:bg-amber-500/10 dark:border-amber-500/20 text-center">View Only — Shared Report</div>
      <Card>
        <CardHeader>
          <CardTitle>{data.title}</CardTitle>
          <p className="text-xs text-slate-500">Dataset: {data.dataset_name} • Generated: {new Date(data.created_at).toLocaleString()} • Version: {data.dataset_version_number ? `V${data.dataset_version_number}` : ''}</p>
        </CardHeader>
        <CardContent className="space-y-4">
          {content.executive_summary && <div><h3 className="font-semibold text-sm">Executive Summary</h3><p className="text-sm text-slate-600 dark:text-white/60 mt-1">{content.executive_summary}</p></div>}
          {content.key_findings && <div><h3 className="font-semibold text-sm">Key Findings</h3><div className="space-y-2 mt-1">{content.key_findings.map((kf:any,i:number)=><div key={i} className="rounded-[12px] border p-3 text-sm dark:border-white/10"><div className="font-medium">{kf.title}</div><div className="text-slate-600 dark:text-white/60">{kf.description}</div></div>)}</div></div>}
          {content.evidence && <div><h3 className="font-semibold text-sm">Evidence</h3><pre className="text-xs bg-slate-50 p-3 rounded-[12px] overflow-auto dark:bg-white/5 dark:border-white/10 max-h-60">{JSON.stringify(content.evidence, null, 2).slice(0,2000)}</pre></div>}
          {content.recommendations && <div><h3 className="font-semibold text-sm">Recommendations</h3><p className="text-sm">{content.recommendations.recommendation || JSON.stringify(content.recommendations)}</p></div>}
        </CardContent>
      </Card>
      <div className="text-center text-xs text-slate-500 py-4 border-t dark:border-white/10">Powered by Open Data Copilot</div>
    </div>
  </div>
}
