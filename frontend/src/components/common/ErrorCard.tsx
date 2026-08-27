import { useState } from 'react'
import { AlertTriangle, RefreshCw, ChevronDown } from 'lucide-react'
import { Button } from '@/components/common/Button'

export function ErrorCard({ title="Something went wrong", message, detail, onRetry }: { title?: string; message: string; detail?: string; onRetry?: ()=>void }) {
  const [showDetail, setShowDetail] = useState(false)
  return (
    <div className="rounded-[16px] border border-red-200 bg-red-50 dark:bg-red-500/10 dark:border-red-500/20 p-4">
      <div className="flex gap-3">
        <span className="h-8 w-8 rounded-full bg-red-500 text-white grid place-items-center shrink-0"><AlertTriangle className="h-4 w-4" /></span>
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-sm text-red-900 dark:text-red-200">{title}</div>
          <div className="text-sm text-red-800 dark:text-red-200/90 mt-1 leading-relaxed">{message}</div>
          <div className="flex gap-2 mt-3">
            {onRetry && <Button size="sm" variant="outline" className="bg-white dark:bg-white/10 border-red-200 dark:border-red-500/20" onClick={onRetry}><RefreshCw className="h-3.5 w-3.5 mr-1" />Retry</Button>}
            {detail && <button onClick={()=>setShowDetail(v=>!v)} className="inline-flex items-center gap-1 text-xs rounded-full border bg-white px-3 py-1.5 dark:bg-white/5 dark:border-white/10">View details <ChevronDown className={`h-3 w-3 transition ${showDetail?'rotate-180':''}`} /></button>}
          </div>
          {showDetail && detail && (
            <pre className="mt-3 bg-white dark:bg-black/30 border dark:border-white/10 rounded-[12px] p-3 text-xs overflow-auto max-h-[160px] whitespace-pre-wrap">{detail}</pre>
          )}
        </div>
      </div>
    </div>
  )
}

export function LoadingState({ message="Loading...", sub }: { message: string; sub?: string }) {
  return (
    <div className="rounded-[16px] border bg-white dark:bg-white/[0.04] dark:border-white/10 p-6 flex items-center gap-4">
      <span className="h-10 w-10 rounded-full border-2 border-slate-200 dark:border-white/10 border-t-[#6d6af0] animate-spin shrink-0" />
      <span>
        <span className="font-medium text-sm block">{message}</span>
        {sub && <span className="text-xs text-slate-500 dark:text-white/50">{sub}</span>}
      </span>
    </div>
  )
}
