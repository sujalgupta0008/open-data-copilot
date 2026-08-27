import { cn } from '@/lib/utils'
export function Input(props: any) {
  return <input className={cn("flex h-10 w-full rounded-full border border-slate-200 bg-white px-4 py-2 text-[13.5px] shadow-[0_1px_2px_rgba(0,0,0,0.04)] placeholder:text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900/10 focus-visible:border-slate-300 transition-all dark:border-white/10 dark:bg-white/[0.06] dark:text-white dark:placeholder:text-white/40", props.className)} {...props} />
}
export function Textarea(props: any) {
  return <textarea className={cn("flex min-h-[80px] w-full rounded-[16px] border border-slate-200 bg-white px-3.5 py-3 text-[13.5px] placeholder:text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-900/10 dark:border-white/10 dark:bg-white/[0.06] dark:text-white", props.className)} {...props} />
}
export function Select({ className, children, ...props}: any){
  return <select className={cn("h-10 rounded-full border border-slate-200 bg-white px-3 pr-8 text-[13.5px] focus:outline-none focus:ring-2 focus:ring-slate-900/10 dark:border-white/10 dark:bg-white/[0.06] dark:text-white", className)} {...props}>{children}</select>
}
