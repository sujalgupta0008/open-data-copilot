import { cn } from '@/lib/utils'
export function Button({ className, variant="default", size="default", ...props }: any) {
  const base = "inline-flex items-center justify-center rounded-full text-[13.5px] font-medium tracking-tight transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:opacity-50 disabled:pointer-events-none active:scale-[0.98]"
  const variants: any = {
    default: "bg-[#0b0d18] text-white hover:bg-black dark:bg-white dark:text-[#0b0d18] dark:hover:bg-zinc-100 shadow-[0_1px_2px_rgba(0,0,0,0.08),0_4px_12px_rgba(0,0,0,0.08)] dark:shadow-none",
    primary: "bg-[#0b0d18] text-white hover:bg-black dark:bg-white dark:text-[#0b0d18]",
    outline: "border border-slate-200 bg-white hover:bg-slate-50 hover:border-slate-300 text-slate-900 dark:border-white/10 dark:bg-white/[0.06] dark:hover:bg-white/[0.10] dark:text-white rounded-full",
    ghost: "hover:bg-slate-100 dark:hover:bg-white/10 text-slate-700 dark:text-slate-200",
    secondary: "bg-slate-100 text-slate-900 hover:bg-slate-200 dark:bg-white/10 dark:text-white dark:hover:bg-white/15",
    subtle: "bg-white border border-slate-200 hover:bg-slate-50 dark:bg-white/5 dark:border-white/10 dark:hover:bg-white/10",
  }
  const sizes: any = { default: "h-9 px-4", sm: "h-8 px-3.5 text-[13px]", lg: "h-10 px-6", xl: "h-11 px-7 text-[14px]", icon:"h-9 w-9 rounded-full" }
  return <button className={cn(base, variants[variant], sizes[size], className)} {...props} />
}
export function IconButton({ className, ...props}: any){
  return <button className={cn("h-8 w-8 inline-flex items-center justify-center rounded-full border border-slate-200 bg-white hover:bg-slate-50 dark:border-white/10 dark:bg-white/5 dark:hover:bg-white/10 transition-colors", className)} {...props} />
}
