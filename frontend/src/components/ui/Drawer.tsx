import { useEffect, useRef } from 'react'
import { X } from 'lucide-react'

type Props = {
  isOpen: boolean
  onClose: () => void
  title?: string
  children: React.ReactNode
  width?: "60%" | "full"
  isPending?: boolean
}

export function Drawer({ isOpen, onClose, title, children, width = "60%", isPending = false }: Props) {
  const drawerRef = useRef<HTMLDivElement>(null)
  const previousActiveRef = useRef<HTMLElement | null>(null)

  // Close on Escape — C15: prevent close when pending
  useEffect(() => {
    if (!isOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (isPending) return
        onClose()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [isOpen, onClose, isPending])

  // Trap focus + restore focus
  useEffect(() => {
    if (isOpen) {
      previousActiveRef.current = document.activeElement as HTMLElement
      // focus drawer
      setTimeout(() => drawerRef.current?.focus(), 50)
      document.body.style.overflow = 'hidden'
    } else {
      document.body.style.overflow = ''
      if (previousActiveRef.current) {
        previousActiveRef.current.focus()
      }
    }
    return () => { document.body.style.overflow = '' }
  }, [isOpen])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== 'Tab' || !drawerRef.current) return
    const focusable = drawerRef.current.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])'
    )
    if (focusable.length === 0) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (e.shiftKey) {
      if (document.activeElement === first) {
        e.preventDefault()
        last.focus()
      }
    } else {
      if (document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
  }

  if (!isOpen) return null

  const widthClass = width === "full" ? "w-full" : "w-full md:w-[60%]"

  // prefers-reduced-motion: skip animation if set
  const motionClass = "transition-transform duration-300 ease-out motion-reduce:transition-none motion-reduce:duration-0"

  return (
    <div className="fixed inset-0 z-50 flex justify-end" aria-modal="true" role="dialog" aria-label={title}>
      {/* Overlay — C15: block click when pending */}
      <div
        className={`absolute inset-0 bg-black/40 backdrop-blur-[2px] motion-reduce:transition-none ${isPending ? 'cursor-not-allowed' : ''}`}
        onClick={() => { if (!isPending) onClose() }}
        aria-hidden="true"
      />
      {/* Drawer */}
      <div
        ref={drawerRef}
        tabIndex={-1}
        onKeyDown={handleKeyDown}
        className={`relative h-full ${widthClass} max-w-full bg-white dark:bg-[#0f1220] shadow-2xl flex flex-col border-l dark:border-white/10 overflow-hidden outline-none ${motionClass}`}
        style={{ transform: isOpen ? 'translateX(0)' : 'translateX(100%)' }}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b dark:border-white/10 shrink-0 bg-white dark:bg-[#0f1220]">
          <h2 className="text-sm font-semibold truncate pr-2">{title}</h2>
          <button
            onClick={() => { if (!isPending) onClose() }}
            disabled={isPending}
            title={isPending ? 'Apply in progress — please wait' : 'Close drawer'}
            className={`h-9 w-9 inline-flex items-center justify-center rounded-full border bg-white hover:bg-slate-50 dark:bg-white/5 dark:border-white/10 dark:hover:bg-white/10 shrink-0 ${isPending ? 'opacity-50 cursor-not-allowed' : ''}`}
            aria-label="Close drawer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {/* Content */}
        <div className="flex-1 overflow-auto p-4 bg-[#f8f9fb] dark:bg-[#070914]">
          {children}
        </div>
      </div>
    </div>
  )
}
