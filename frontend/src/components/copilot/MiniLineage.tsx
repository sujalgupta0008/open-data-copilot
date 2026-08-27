import { useState, useEffect } from 'react'

function useIsMobile(breakpoint = 480) {
  const [isMobile, setIsMobile] = useState(typeof window !== 'undefined' ? window.innerWidth < breakpoint : false)
  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${breakpoint}px)`)
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches)
    setIsMobile(mql.matches)
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [breakpoint])
  return isMobile
}

type Props = {
  datasetName: string
  version?: string
  rowCount?: number
  hasChart: boolean
  hasSql: boolean
  trustScore?: number | null
  onStepClick?: (step: string) => void
}

export function MiniLineage({ datasetName, version, rowCount, hasChart, hasSql, trustScore, onStepClick }: Props) {
  const [collapsed, setCollapsed] = useState(false)
  const isMobile = useIsMobile(480)
  const trustColor = trustScore == null ? 'bg-slate-100' : trustScore >= 80 ? 'bg-emerald-500 text-white' : trustScore >= 60 ? 'bg-amber-500 text-white' : 'bg-red-500 text-white'
  const trustLabel = trustScore != null ? `Trust ${trustScore}` : null

  const steps: { id: string; label: string; icon: string; show: boolean }[] = [
    { id: 'dataset', label: `${datasetName} ${version || 'v1'}`, icon: '📁', show: true },
    { id: 'sql', label: 'SQL', icon: '🔍', show: hasSql },
    { id: 'rows', label: `${rowCount ?? '—'} rows`, icon: '📊', show: rowCount != null },
    { id: 'chart', label: 'Chart', icon: '📈', show: hasChart },
    { id: 'insight', label: 'Insight', icon: '✓', show: true },
  ]
  const visible = steps.filter(s => s.show)

  if (collapsed) {
    return (
      <div className={`flex items-center gap-1 text-[11px] text-slate-500 dark:text-white/50 py-1 ${isMobile ? 'overflow-x-auto whitespace-nowrap scrollbar-thin' : ''}`}>
        <span className="font-medium shrink-0">{datasetName} {version || 'v1'}</span>
        <button onClick={() => setCollapsed(false)} className="px-1 hover:text-slate-900 dark:hover:text-white shrink-0" title="Expand lineage">›</button>
        <span className="shrink-0">Insight</span>
        {trustLabel && <span className={`ml-1 rounded-full px-1.5 py-0.5 text-[10px] shrink-0 ${trustColor}`}>{trustLabel}</span>}
      </div>
    )
  }

  return (
    <div className={`flex items-center gap-1 text-[11px] text-slate-500 dark:text-white/50 py-1 ${isMobile ? 'flex-nowrap overflow-x-auto whitespace-nowrap scrollbar-thin' : 'flex-wrap'}`}>
      {visible.map((s, idx) => (
        <span key={s.id} className="inline-flex items-center gap-1 shrink-0">
          <button
            onClick={() => onStepClick?.(s.id)}
            className="inline-flex items-center gap-1 hover:text-slate-900 dark:hover:text-white rounded px-1 -mx-1"
            title={`Go to ${s.label}`}
          >
            <span>{s.icon}</span>
            <span className="font-medium">{s.label}</span>
          </button>
          {idx < visible.length - 1 && !isMobile && (
            <button onClick={() => setCollapsed(true)} className="px-0.5 hover:text-slate-900 dark:hover:text-white" title="Collapse">›</button>
          )}
          {idx < visible.length - 1 && isMobile && (
            <span className="px-0.5 text-slate-300" aria-hidden>›</span>
          )}
        </span>
      ))}
      {trustLabel && <span className={`ml-1 rounded-full px-1.5 py-0.5 text-[10px] font-medium shrink-0 ${trustColor}`}>{trustLabel}</span>}
    </div>
  )
}
