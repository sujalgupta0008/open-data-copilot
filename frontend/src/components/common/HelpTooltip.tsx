import { useState } from 'react'
import { Info, X } from 'lucide-react'

export function HelpTooltip({ title, children, side="top" }: { title?: string; children: string; side?: "top" | "right"}) {
  const [open, setOpen] = useState(false)
  return (
    <span className="relative inline-flex">
      <button
        onClick={()=>setOpen(o=>!o)}
        onBlur={()=>setTimeout(()=>setOpen(false),150)}
        className="h-5 w-5 rounded-full border bg-white dark:bg-white/5 dark:border-white/10 inline-flex items-center justify-center hover:bg-slate-50 dark:hover:bg-white/10 transition-colors"
        aria-label="Help"
      >
        <Info className="h-3 w-3 text-slate-500 dark:text-white/60" />
      </button>
      {open && (
        <span className={`absolute z-20 w-[260px] rounded-[12px] border bg-white dark:bg-[#0f1220] dark:border-white/10 shadow-[0_8px_24px_rgba(0,0,0,0.12)] p-3 text-xs leading-relaxed ${side==="top" ? "bottom-full mb-2 left-1/2 -translate-x-1/2" : "left-full ml-2 top-1/2 -translate-y-1/2"}`}>
          {title && <span className="font-semibold block mb-1">{title}</span>}
          <span className="text-slate-600 dark:text-white/70">{children}</span>
          <button onClick={()=>setOpen(false)} className="absolute top-1 right-1 h-6 w-6 grid place-items-center rounded-full hover:bg-slate-100 dark:hover:bg-white/10"><X className="h-3 w-3" /></button>
        </span>
      )}
    </span>
  )
}

export function InfoBadge({ label, help }: { label: string; help: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span>{label}</span>
      <HelpTooltip>{help}</HelpTooltip>
    </span>
  )
}
