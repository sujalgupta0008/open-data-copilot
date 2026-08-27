import { cn } from '@/lib/utils'
export function Card({ className, hover=true, ...props }: any) {
  return <div className={cn("card-premium", !hover && "hover:transform-none hover:shadow-none", className)} {...props} />
}
export function CardHeader({ className, ...props }: any) { return <div className={cn("flex flex-col space-y-1.5 p-5 pb-3", className)} {...props} /> }
export function CardTitle({ className, ...props }: any) { return <h3 className={cn("font-semibold leading-none tracking-tight text-[14.5px]", className)} {...props} /> }
export function CardDescription({ className, ...props }: any) { return <p className={cn("text-[13px] text-slate-500 dark:text-slate-400 leading-relaxed", className)} {...props} /> }
export function CardContent({ className, ...props }: any) { return <div className={cn("p-5 pt-0", className)} {...props} /> }
export function CardFooter({ className, ...props }: any) { return <div className={cn("flex items-center p-5 pt-0", className)} {...props} /> }

export function Badge({ className, variant="default", ...props }: any) {
  const v: any = {
    default: "bg-slate-900 text-white dark:bg-white dark:text-slate-900 border-transparent",
    outline: "bg-white dark:bg-transparent border-slate-200 dark:border-white/15 text-slate-700 dark:text-slate-200",
    success: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/20",
    warning: "bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/20",
    danger: "bg-red-500/10 text-red-700 dark:text-red-300 border-red-500/20",
    muted: "bg-slate-100 dark:bg-white/5 text-slate-600 dark:text-slate-300 border-transparent",
  }
  return <span className={cn("inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-medium tracking-wide", v[variant], className)} {...props} />
}
export function Surface({ className, level=1, ...props }: any){
  const l:any={1:"surface-1",2:"surface-2",3:"surface-3", elev:"surface-elevated elev-2"}
  return <div className={cn(l[level]||l[1], "rounded-[16px] border", className)} {...props} />
}
export function Skeleton({ className, ...props }: any){ return <div className={cn("shimmer rounded-md", className)} {...props} /> }
export function Divider({ className }: any){ return <div className={cn("hairline", className)} /> }
