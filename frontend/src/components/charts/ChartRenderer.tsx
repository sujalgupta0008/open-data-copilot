import { useState, useMemo, useEffect } from 'react'
import { BarChart, Bar, LineChart, Line, ScatterChart, Scatter, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, LabelList } from 'recharts'
import { ArrowUpDown, ArrowUp, ArrowDown, Link as LinkIcon } from 'lucide-react'

function useIsMobile(breakpoint = 480) {
  const [isMobile, setIsMobile] = useState(typeof window !== 'undefined' ? window.innerWidth < breakpoint : false)
  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${breakpoint}px)`)
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches)
    // initial
    setIsMobile(mql.matches)
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [breakpoint])
  return isMobile
}

function isDarkMode(): boolean {
  if (typeof document === 'undefined') return false
  return document.documentElement.classList.contains('dark')
}

// Smart value formatting as per spec
export function formatValue(value: any, hint?: string, yKey?: string): string {
  if (value === null || value === undefined || value === '') return String(value ?? '')
  const num = Number(value)
  if (isNaN(num)) return String(value)
  const key = (hint || yKey || '').toLowerCase()
  const isCurrency = hint === 'currency' || /price|revenue|sales|cost|amount|fare/.test(key)
  const isPercent = hint === 'percent' || /rate|ratio|pct|percent/.test(key)
  if (isPercent) {
    // if value is 0-1 ratio, convert to percent; if already 1-100, keep
    const pct = num > 0 && num <= 1.5 ? num * 100 : num
    return `${pct.toLocaleString(undefined, { maximumFractionDigits: 1 })}%`
  }
  if (isCurrency) {
    if (Math.abs(num) >= 1_000_000) return `$${(num / 1_000_000).toFixed(1)}M`
    // for currency, use $ with comma
    if (Number.isInteger(num)) return `$${num.toLocaleString(undefined, { maximumFractionDigits: 0 })}`
    return `$${num.toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`
  }
  if (Math.abs(num) >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`
  if (Math.abs(num) >= 1_000) return `${(num / 1_000).toFixed(1)}K`
  return num.toLocaleString(undefined, { maximumFractionDigits: 2 })
}

function truncateLabel(label: string, max = 20): string {
  if (!label) return ''
  const s = String(label)
  return s.length > max ? s.slice(0, max) + '…' : s
}

export function ChartRenderer({ chart, onDrillDown }: { chart: any; onDrillDown?: (value: any, column: string) => void }) {
  // Hooks must be called unconditionally and in the same order on every render
  const [sortOrder, setSortOrder] = useState<'original' | 'asc' | 'desc'>('original')
  const [legendExpanded, setLegendExpanded] = useState(false)
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null)
  const [copied, setCopied] = useState(false)
  const isMobile = useIsMobile(480)
  const isMobileLegend = useIsMobile(640)

  const cfg = chart?.configuration
  const rawData: any[] = useMemo(() => cfg?.data || [], [cfg?.data])
  const type = chart?.chart_type
  const dark = isDarkMode()
  const gridStroke = dark ? "rgba(255,255,255,0.08)" : "#eef2f7"
  const tickFill = dark ? "#9aa0b3" : "#64748b"
  const tooltipStyle: any = dark ? { backgroundColor: "#0f1220", border: "1px solid rgba(255,255,255,0.10)", color: "#e2e8f0", borderRadius: "12px" } : { backgroundColor: "#ffffff", border: "1px solid #e2e8f0", color: "#0f172a", borderRadius: "12px" }

  const yKey: string = cfg?.yKey || cfg?.y_key || ''
  const xKey: string = cfg?.xKey || cfg?.x_key || ''
  const hint = yKey // use yKey for hint detection

  const sortedData = useMemo(() => {
    if (type !== 'bar' || sortOrder === 'original') return rawData
    const copy = [...rawData]
    copy.sort((a: any, b: any) => {
      const av = Number(a[yKey] ?? 0)
      const bv = Number(b[yKey] ?? 0)
      return sortOrder === 'asc' ? av - bv : bv - av
    })
    return copy
  }, [rawData, sortOrder, yKey, type])

  if (!chart || !cfg) return null
  const handleCopyChartLink = () => {
    const url = window.location.href.split('#')[0] + `#chart-${chart.id || yKey || 'chart'}`
    navigator.clipboard.writeText(url).then(()=>{ setCopied(true); setTimeout(()=>setCopied(false),2000)}).catch(()=>{})
  }

  const cycleSort = () => {
    setSortOrder(prev => prev === 'original' ? 'asc' : prev === 'asc' ? 'desc' : 'original')
  }

  const handleBarClick = (data: any, index: number) => {
    if (!onDrillDown) return
    const col = xKey || 'category'
    const val = data?.activePayload?.[0]?.payload?.[xKey] ?? data?.payload?.[xKey] ?? data?.name ?? data?.payload?.name
    // fallback for simple bar click
    const clickedVal = data?.payload ? data.payload[xKey] : val
    if (clickedVal !== undefined) {
      setSelectedIndex(index)
      onDrillDown(clickedVal, col)
    }
  }

  const handlePieClick = (data: any, index: number) => {
    if (!onDrillDown) return
    const val = data?.payload?.[xKey] ?? data?.name ?? data?.payload?.name
    if (val !== undefined) {
      setSelectedIndex(index)
      onDrillDown(val, xKey)
    }
  }

  // Custom legend with truncation and +N more
  const renderLegend = (props: any) => {
    const payload = props.payload || []
    const maxItems = 8
    const visible = legendExpanded ? payload : payload.slice(0, maxItems)
    const remaining = payload.length - maxItems
    return (
      <div className={`flex flex-wrap gap-2 justify-center ${isMobileLegend ? 'text-[10px]' : 'text-xs'} mt-2`}>
        {visible.map((entry: any, i: number) => {
          const label = String(entry.value ?? entry.payload?.name ?? '')
          const truncated = truncateLabel(label, 20)
          return (
            <span key={i} className="inline-flex items-center gap-1.5" title={label}>
              <span className="h-2.5 w-2.5 rounded-full inline-block" style={{ background: entry.color }} />
              <span className="max-w-[20ch] truncate" title={label}>{truncated}</span>
            </span>
          )
        })}
        {!legendExpanded && remaining > 0 && (
          <button onClick={() => setLegendExpanded(true)} className="text-xs underline text-slate-500">+{remaining} more</button>
        )}
        {legendExpanded && payload.length > maxItems && (
          <button onClick={() => setLegendExpanded(false)} className="text-xs underline text-slate-500">Show less</button>
        )}
      </div>
    )
  }

  if (type === 'bar') {
    // Ranked horizontal bar for approval-rate segments
    if (xKey === 'segment') {
      const dataForSegment = sortOrder === 'original' ? [...rawData].sort((a: any, b: any) => (b[yKey] || 0) - (a[yKey] || 0)) : sortedData
      return (
        <div className="space-y-2" id={`chart-${chart.id || 'segment'}`}>
          <div className="flex justify-end gap-1 items-center">
            <button onClick={handleCopyChartLink} className="h-7 w-7 inline-flex items-center justify-center rounded-full border bg-white hover:bg-slate-50 dark:bg-white/5 dark:border-white/10" title="Copy chart link"><LinkIcon className="h-3.5 w-3.5" /></button>
            {copied && <span className="text-xs text-emerald-600">Copied!</span>}
            <button onClick={cycleSort} className="h-7 px-2 text-xs rounded-full border bg-white hover:bg-slate-50 dark:bg-white/5 dark:border-white/10 inline-flex items-center gap-1">
              {sortOrder === 'original' ? <><ArrowUpDown className="h-3 w-3" /> Original</> : sortOrder === 'asc' ? <><ArrowUp className="h-3 w-3" /> Sort ↑</> : <><ArrowDown className="h-3 w-3" /> Sort ↓</>}
            </button>
          </div>
          <ResponsiveContainer width="100%" height={Math.max(300, dataForSegment.length * (isMobile ? 32 : 40) + 60)}>
            <BarChart data={dataForSegment} layout="vertical" margin={{ left: isMobile ? 4 : 12, right: 16, top: 8, bottom: 8 }} onClick={(e: any) => e && e.activePayload && handleBarClick(e, e.activeTooltipIndex)}>
              <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} />
              <XAxis type="number" domain={[0, 100]} tick={{ fill: tickFill, fontSize: isMobile ? 10 : 12 }} axisLine={{ stroke: gridStroke }} tickLine={{ stroke: gridStroke }} unit="%" tickFormatter={(v: any) => formatValue(v, 'percent', yKey)} />
              <YAxis dataKey={xKey} type="category" width={isMobile ? 110 : 200} tick={{ fill: tickFill, fontSize: isMobile ? 10 : 11 }} tickFormatter={(v: any) => truncateLabel(String(v), isMobile ? 14 : 20)} axisLine={{ stroke: gridStroke }} tickLine={{ stroke: gridStroke }} interval={0} />
              <Tooltip contentStyle={tooltipStyle} cursor={{ fill: dark ? 'rgba(255,255,255,0.03)' : 'rgba(15,23,42,0.04)' }} formatter={(value: any, name: any, props: any) => [`${formatValue(value, 'percent', yKey)} (n=${props.payload.application_count || props.payload.n || ''})`, name]} />
              <Legend content={renderLegend} />
              <Bar dataKey={yKey} fill={dark ? "#8b8cf0" : "#0b0d18"} radius={[0, 8, 8, 0]} barSize={18} onClick={handleBarClick as any}>
                {dataForSegment.map((_: any, idx: number) => (
                  <Cell key={idx} opacity={selectedIndex !== null && selectedIndex !== idx ? 0.5 : 1} />
                ))}
                {dataForSegment.length <= 8 && <LabelList dataKey={yKey} position="right" formatter={(v: any) => formatValue(v, 'percent', yKey)} style={{ fontSize: 11, fill: tickFill }} />}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )
    }
    return (
      <div className="space-y-2" id={`chart-${chart.id || yKey || 'bar'}`}>
        <div className="flex justify-end gap-1 items-center">
          <button onClick={handleCopyChartLink} className="h-7 w-7 inline-flex items-center justify-center rounded-full border bg-white hover:bg-slate-50 dark:bg-white/5 dark:border-white/10" title="Copy chart link"><LinkIcon className="h-3.5 w-3.5" /></button>
          {copied && <span className="text-xs text-emerald-600">Copied!</span>}
          <button onClick={cycleSort} className="h-7 px-2 text-xs rounded-full border bg-white hover:bg-slate-50 dark:bg-white/5 dark:border-white/10 inline-flex items-center gap-1">
            {sortOrder === 'original' ? <><ArrowUpDown className="h-3 w-3" /> Original</> : sortOrder === 'asc' ? <><ArrowUp className="h-3 w-3" /> Sort ↑</> : <><ArrowDown className="h-3 w-3" /> Sort ↓</>}
          </button>
        </div>
        <ResponsiveContainer width="100%" height={sortedData.length > 8 ? Math.max(300, sortedData.length * (isMobile ? 28 : 32) + 60) : 300}>
          <BarChart data={sortedData} onClick={(e: any) => e && e.activePayload && handleBarClick(e, e.activeTooltipIndex)}>
            <CartesianGrid strokeDasharray="3 3" stroke={gridStroke} />
            <XAxis dataKey={xKey} tick={{ fill: tickFill, fontSize: isMobile ? 10 : 12 }} axisLine={{ stroke: gridStroke }} tickLine={{ stroke: gridStroke }} interval={0} angle={sortedData.length > 6 ? -20 : 0} textAnchor={sortedData.length > 6 ? "end" : "middle"} height={sortedData.length > 6 ? 60 : 30} />
            <YAxis tick={{ fill: tickFill, fontSize: isMobile ? 10 : 12 }} axisLine={{ stroke: gridStroke }} tickLine={{ stroke: gridStroke }} tickFormatter={(v: any) => formatValue(v, hint, yKey)} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ fill: dark ? 'rgba(255,255,255,0.03)' : 'rgba(15,23,42,0.04)' }} formatter={(value: any) => formatValue(value, hint, yKey)} />
            <Legend content={renderLegend} wrapperStyle={isMobileLegend ? { fontSize: 10 } : { fontSize: 12, color: tickFill }} />
            <Bar dataKey={yKey} fill={dark ? "#8b8cf0" : "#0b0d18"} radius={[8, 8, 0, 0]} barSize={isMobile ? 18 : 22} onClick={handleBarClick as any}>
              {sortedData.map((_: any, idx: number) => (
                <Cell key={idx} opacity={selectedIndex !== null && selectedIndex !== idx ? 0.5 : 1} cursor={onDrillDown ? 'pointer' : undefined} />
              ))}
              {sortedData.length <= 8 && <LabelList dataKey={yKey} position="top" formatter={(v: any) => formatValue(v, hint, yKey)} style={{ fontSize: 11, fill: tickFill }} />}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    )
  }
  if (type === 'line') {
    return <ResponsiveContainer width="100%" height={300}><LineChart data={rawData}><CartesianGrid strokeDasharray="3 3" stroke={gridStroke} /><XAxis dataKey={xKey} tick={{ fill: tickFill, fontSize: 12 }} axisLine={{ stroke: gridStroke }} tickLine={{ stroke: gridStroke }} /><YAxis tick={{ fill: tickFill, fontSize: 12 }} axisLine={{ stroke: gridStroke }} tickLine={{ stroke: gridStroke }} tickFormatter={(v: any) => formatValue(v, hint, yKey)} /><Tooltip contentStyle={tooltipStyle} formatter={(value: any) => formatValue(value, hint, yKey)} /><Legend content={renderLegend} wrapperStyle={{ color: tickFill, fontSize: 12 }} /><Line type="monotone" dataKey={yKey} stroke={dark ? "#8b8cf0" : "#0b0d18"} strokeWidth={2.4} dot={{ r: 3, strokeWidth: 2, fill: dark ? "#0f1220" : "white" }} activeDot={{ r: 5 }} /></LineChart></ResponsiveContainer>
  }
  if (type === 'scatter') {
    return <ResponsiveContainer width="100%" height={300}><ScatterChart><CartesianGrid stroke={gridStroke} /><XAxis dataKey={xKey} tick={{ fill: tickFill }} axisLine={{ stroke: gridStroke }} tickFormatter={(v: any) => formatValue(v, hint, xKey)} /><YAxis dataKey={yKey} tick={{ fill: tickFill }} axisLine={{ stroke: gridStroke }} tickFormatter={(v: any) => formatValue(v, hint, yKey)} /><Tooltip contentStyle={tooltipStyle} formatter={(value: any) => formatValue(value, hint, yKey)} /><Scatter data={rawData} fill={dark ? "#8b8cf0" : "#0b0d18"} /></ScatterChart></ResponsiveContainer>
  }
  if (type === 'pie') {
    const colors = dark ? ["#8b8cf0", "#38bdf8", "#34d399", "#f59e0b", "#f43f5e"] : ["#0b0d18", "#334155", "#64748b", "#8b8cf0", "#38bdf8"]
    return (
      <div className="space-y-2" id={`chart-${chart.id || yKey || 'pie'}`}>
        <div className="flex justify-end gap-1 items-center">
          <button onClick={handleCopyChartLink} className="h-7 w-7 inline-flex items-center justify-center rounded-full border bg-white hover:bg-slate-50 dark:bg-white/5 dark:border-white/10" title="Copy chart link"><LinkIcon className="h-3.5 w-3.5" /></button>
          {copied && <span className="text-xs text-emerald-600">Copied!</span>}
        </div>
        <ResponsiveContainer width="100%" height={300}>
          <PieChart>
            <Pie data={rawData} dataKey={yKey} nameKey={xKey} cx="50%" cy="50%" outerRadius={100} label={({ payload, value }: any) => `${truncateLabel(String(payload[xKey]), 12)}: ${formatValue(value, hint, yKey)}`} labelLine={false} onClick={handlePieClick as any}>
              {rawData.map((_: any, i: number) => <Cell key={i} fill={colors[i % colors.length]} opacity={selectedIndex !== null && selectedIndex !== i ? 0.5 : 1} cursor={onDrillDown ? 'pointer' : undefined} />)}
            </Pie>
            <Tooltip contentStyle={tooltipStyle} formatter={(value: any) => formatValue(value, hint, yKey)} />
            <Legend content={renderLegend} />
          </PieChart>
        </ResponsiveContainer>
      </div>
    )
  }
  if (type === 'heatmap') {
    return <div className="text-sm p-4 rounded-[12px] border bg-slate-50 dark:bg-white/5 dark:border-white/10">Heatmap: {JSON.stringify(rawData.slice(0,3))}</div>
  }
  return <div className="text-sm text-slate-600 dark:text-white/60">Chart type {type} not rendered</div>
}
