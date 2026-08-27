import { useEffect, useState } from 'react'

type Props = {
  score: number
  details?: string[]
}

export function TrustRing({ score, details }: Props) {
  const isMobile = typeof window !== 'undefined' ? window.innerWidth < 640 : false
  const r = isMobile ? 48 : 64
  const size = isMobile ? 112 : 144
  const stroke = isMobile ? 8 : 10
  const c = 2 * Math.PI * r
  const [offset, setOffset] = useState(c)
  const color = score >= 80 ? '#10b981' : score >= 60 ? '#f59e0b' : '#ef4444'

  useEffect(() => {
    // animate from 0 to score, respect prefers-reduced-motion
    const prefersReduced = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    if (prefersReduced) {
      setOffset(c - (score / 100) * c)
      return
    }
    setOffset(c)
    const t = setTimeout(() => setOffset(c - (score / 100) * c), 50)
    return () => clearTimeout(t)
  }, [score, c])

  const tooltip = `Trust Score: ${score}/100
${details?.join('\n') || '✓ Large sample\n✓ Low missingness\n✓ SQL verified by DuckDB\n⚠ Correlation ≠ causation'}`

  const [showTip, setShowTip] = useState(false)
  return (
    <div className="relative shrink-0 group" style={{ width: size, height: size }} title={tooltip} onClick={() => setShowTip(v => !v)} onMouseLeave={() => setShowTip(false)}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90">
        <circle cx={size/2} cy={size/2} r={r} stroke="currentColor" className="text-slate-100 dark:text-white/10" strokeWidth={stroke} fill="none" />
        <circle
          cx={size/2} cy={size/2} r={r}
          stroke={color}
          strokeWidth={stroke}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={offset}
          className="transition-[stroke-dashoffset] duration-[800ms] ease-[cubic-bezier(.22,1,.36,1)] motion-reduce:transition-none motion-reduce:animate-none"
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center">
        <div className="text-center leading-none">
          <div className="text-[24px] md:text-[28px] font-semibold tracking-tight">{score}</div>
          <div className="text-[11px] text-slate-500 dark:text-white/50">Trust</div>
        </div>
      </div>
      {/* Tooltip on hover — U2: constrain to viewport on mobile */}
      <div className={`pointer-events-none absolute left-1/2 -translate-x-1/2 bottom-full mb-2 z-10 w-56 max-w-[min(14rem,90vw)] rounded-[12px] border bg-white dark:bg-[#0f1220] dark:border-white/10 p-3 text-xs shadow-lg whitespace-pre-line break-words ${showTip ? 'block' : 'hidden group-hover:block'}`}>
        <div className="font-semibold">Trust Score: {score}/100</div>
        <div className="mt-1 text-slate-600 dark:text-white/60 whitespace-pre-line break-words">{details?.join('\n') || '✓ Large sample\n✓ Low missingness\n✓ SQL verified by DuckDB\n⚠ Correlation ≠ causation'}</div>
      </div>
    </div>
  )
}
