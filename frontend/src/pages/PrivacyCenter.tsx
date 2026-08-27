import { useQuery } from '@tanstack/react-query'
import api from '@/services/api'
import { Card, CardContent, CardHeader, CardTitle, Badge } from '@/components/common/Card'
import { ShieldCheck, Lock, Database, EyeOff } from 'lucide-react'

export default function PrivacyCenter(){
  const { data } = useQuery({ queryKey:['privacy'], queryFn: async()=> (await api.get('/api/privacy')).data })
  if(!data) return <div className="p-6 space-y-3"><div className="h-8 w-48 shimmer rounded-full" /><div className="h-[200px] shimmer rounded-[16px]" /></div>
  return (
    <div className="space-y-6 max-w-[900px]">
      <div>
        <h1 className="text-[26px] font-semibold tracking-tight flex items-center gap-2"><ShieldCheck className="h-6 w-6 text-emerald-600" /> Privacy Center</h1>
        <p className="text-sm text-slate-600 dark:text-white/60">Schema-first AI • no raw rows by default • audit-grade trust</p>
      </div>

      <Card className="overflow-hidden">
        <div className="h-1 bg-gradient-to-r from-emerald-500 to-teal-500" />
        <CardHeader><CardTitle className="flex items-center gap-2"><Database className="h-4 w-4" /> AI Data Processing</CardTitle></CardHeader>
        <CardContent className="text-sm space-y-3">
          <div className="grid md:grid-cols-3 gap-3">
            <div className="rounded-[16px] border bg-slate-50 p-3 dark:bg-white/5 dark:border-white/10"><div className="text-xs text-slate-500">Provider</div><div className="font-medium mt-1">{data.privacy_center.ai_processing}</div></div>
            <div className="rounded-[16px] border bg-slate-50 p-3 dark:bg-white/5 dark:border-white/10 md:col-span-2"><div className="text-xs text-slate-500">What is sent</div><div className="mt-1 leading-relaxed">{data.privacy_center.what_is_sent}</div></div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-full border px-4 py-2.5 flex justify-between dark:border-white/10"><span>Raw rows</span><Badge variant={data.privacy_center.raw_rows_sent?'danger':'success'}>{String(data.privacy_center.raw_rows_sent)}</Badge></div>
            <div className="rounded-full border px-4 py-2.5 flex justify-between dark:border-white/10"><span>Schema sent</span><Badge variant="success">{String(data.privacy_center.schema_sent)}</Badge></div>
            <div className="rounded-full border px-4 py-2.5 flex justify-between dark:border-white/10"><span>Sample rows</span><Badge variant="success">{String(data.privacy_center.sample_rows_sent)}</Badge></div>
            <div className="rounded-full border px-4 py-2.5 flex justify-between dark:border-white/10"><span>Full dataset</span><Badge variant={data.privacy_center.full_dataset_sent?'danger':'success'}>{String(data.privacy_center.full_dataset_sent ?? false)}</Badge></div>
          </div>
          {data.privacy_center.model && <div className="text-xs rounded-full border bg-white px-3 py-1 inline-flex dark:bg-white/5 dark:border-white/10">Model: {data.privacy_center.model}</div>}
        </CardContent>
      </Card>

      <Card><CardHeader><CardTitle className="flex items-center gap-2"><Lock className="h-4 w-4" /> Security Guarantees</CardTitle></CardHeader><CardContent className="text-sm space-y-2">
        {[data.data_isolation, data.file_validation, data.sql_sandbox, data.python_sandbox, data.secrets].map((t:any,i:number)=><div key={i} className="flex gap-2 rounded-full border px-4 py-2.5 bg-emerald-50 border-emerald-200 dark:bg-emerald-500/10 dark:border-emerald-500/20"><ShieldCheck className="h-4 w-4 text-emerald-600 shrink-0" />{t}</div>)}
      </CardContent></Card>

      <Card><CardHeader><CardTitle className="flex items-center gap-2"><EyeOff className="h-4 w-4" /> Recommendations</CardTitle></CardHeader><CardContent className="text-sm text-slate-600 dark:text-white/60 leading-relaxed">
        For sensitive datasets, use <code className="rounded-full border bg-slate-50 px-2 py-0.5 dark:bg-white/5 dark:border-white/10">AI_PROVIDER=mock</code> locally — no external call. For production with OpenAI, ensure DPA and avoid uploading PII. Schema-only mode is default.
      </CardContent></Card>
    </div>
  )
}
