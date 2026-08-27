import { useEffect, useRef, useState } from 'react'

export type SubTab = {
  id: string
  label: string
  badge?: number | string
  dot?: boolean
}

export type PrimaryTab = {
  id: string
  label: string
  subTabs?: SubTab[]
  dot?: boolean
}

type Props = {
  primaryTabs: PrimaryTab[]
  activePrimary: string
  activeSub: string | null
  onPrimaryChange: (id: string) => void
  onSubChange: (id: string) => void
}

// Reusable two-level tab component - Level 1 larger/bolder with underline, Level 2 pill-style with fade indicator
export function TwoLevelTabs({ primaryTabs, activePrimary, activeSub, onPrimaryChange, onSubChange }: Props) {
  const subTabsRef = useRef<HTMLDivElement>(null)
  const [showFade, setShowFade] = useState(false)

  const activePrimaryObj = primaryTabs.find(p => p.id === activePrimary)
  const subTabs = activePrimaryObj?.subTabs || []

  const checkFade = () => {
    const el = subTabsRef.current
    if (!el) return
    const hasOverflow = el.scrollWidth > el.clientWidth + 4
    const atEnd = el.scrollLeft + el.clientWidth >= el.scrollWidth - 8
    setShowFade(hasOverflow && !atEnd)
  }

  useEffect(() => {
    checkFade()
    const el = subTabsRef.current
    if (!el) return
    el.addEventListener('scroll', checkFade)
    window.addEventListener('resize', checkFade)
    const ro = new ResizeObserver(checkFade)
    ro.observe(el)
    return () => {
      el.removeEventListener('scroll', checkFade)
      window.removeEventListener('resize', checkFade)
      ro.disconnect()
    }
  }, [activePrimary, subTabs.length])

  useEffect(() => {
    // re-check after subTabs change
    const t = setTimeout(checkFade, 50)
    return () => clearTimeout(t)
  }, [activePrimary])

  return (
    <div className="space-y-0">
      {/* Level 1 - Primary tabs: responsive — equal width on desktop, scrollable on mobile to avoid truncation */}
      <div className="flex w-full border-b border-slate-200 dark:border-white/10 overflow-x-auto scrollbar-thin">
        {primaryTabs.map(p => {
          const isActive = p.id === activePrimary
          return (
            <button
              key={p.id}
              onClick={() => onPrimaryChange(p.id)}
              className={`shrink-0 flex-1 sm:flex-1 min-w-[70px] sm:min-w-0 min-h-[44px] flex items-center justify-center gap-1 sm:gap-1.5 px-2 sm:px-4 py-3 text-[12px] sm:text-[15px] font-semibold tracking-tight whitespace-nowrap truncate transition-colors border-b-2 -mb-px relative ${
                isActive
                  ? 'text-[#0b0d18] dark:text-white border-[#0b0d18] dark:border-white font-bold'
                  : 'text-slate-500 dark:text-white/60 border-transparent hover:text-slate-700 dark:hover:text-white/80 font-medium'
              }`}
            >
              {p.label}
              {p.dot && (
                <span className="ml-1 h-2 w-2 rounded-full bg-red-500 inline-block shrink-0" aria-label="needs attention" />
              )}
            </button>
          )
        })}
      </div>

      {/* Level 2 - Sub-tabs: pill-style, only when parent has subs */}
      {subTabs.length > 0 && (
        <div className="relative mt-3">
          <div
            ref={subTabsRef}
            onScroll={checkFade}
            className="flex gap-1.5 overflow-auto pb-1 scrollbar-thin scroll-smooth"
          >
            {subTabs.map(s => {
              const isActive = s.id === activeSub
              return (
                <button
                  key={s.id}
                  onClick={() => onSubChange(s.id)}
                  className={`inline-flex items-center gap-1.5 min-h-[44px] px-3.5 py-2 rounded-full text-[13px] font-medium border whitespace-nowrap transition-colors shrink-0 ${
                    isActive
                      ? 'bg-[#0b0d18] text-white border-[#0b0d18] dark:bg-white dark:text-[#0b0d18] shadow-sm'
                      : 'bg-white hover:bg-slate-50 border-slate-200 text-slate-700 dark:bg-white/5 dark:border-white/10 dark:text-white/70'
                  }`}
                >
                  {s.label}
                  {s.badge !== undefined && s.badge !== null && s.badge !== '' && (
                    <span className={`ml-1 inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full text-[11px] font-semibold ${isActive ? 'bg-white text-[#0b0d18] dark:bg-[#0b0d18] dark:text-white' : 'bg-slate-100 dark:bg-white/10 text-slate-600 dark:text-white/70'}`}>
                      {s.badge}
                    </span>
                  )}
                  {s.dot && !s.badge && (
                    <span className="ml-1 h-2 w-2 rounded-full bg-red-500 inline-block" />
                  )}
                </button>
              )
            })}
          </div>
          {/* Right-edge fade gradient when overflow */}
          {showFade && (
            <div className="pointer-events-none absolute right-0 top-0 bottom-1 w-10 bg-gradient-to-l from-white dark:from-[#0b0d18] to-transparent" aria-hidden />
          )}
        </div>
      )}
    </div>
  )
}
