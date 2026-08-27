import { Card, CardContent, CardHeader, CardTitle } from '@/components/common/Card'
import { Button } from '@/components/common/Button'
import { useAuth } from '@/hooks/useAuth'
import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import api from '@/services/api'
import { User, Palette, Shield, LogOut, Cpu, Info, Check, Bell, Mail, Send } from 'lucide-react'
import { Link } from 'react-router-dom'
import { driveService } from '@/services/driveService'

function DriveBYOSCard(){
  const [ws, setWs] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const load = async()=>{
    try{
      const data = await driveService.getWorkspace()
      setWs(data)
    }catch(e:any){ setMsg(e.response?.data?.detail || 'Drive not connected') }
  }
  useEffect(()=>{ load() },[])
  const connect = async()=>{
    setLoading(true)
    try{
      // Try mock login for dev (no real Google OAuth popup)
      const res = await driveService.mockLogin()
      setMsg(`Connected: ${res.workspace?.folder_name} (${res.workspace?.path}) • scope ${res.scope}`)
      await load()
    }catch(e:any){ setMsg(e.response?.data?.detail || e.message) }
    setLoading(false)
    setTimeout(()=> setMsg(null), 3000)
  }
  return (
    <div className="space-y-2">
      <div className="rounded-[12px] border p-3 bg-slate-50 dark:bg-white/5 dark:border-white/10">
        <div className="text-xs text-slate-500">Workspace Folder</div>
        <div className="font-mono text-xs mt-1">{ws?.folder_name || 'Open_Data_Copilot_Workspace'} — {ws?.path || 'Not initialized'}</div>
        <div className="text-xs mt-1">Scope: <span className="font-mono">{ws?.scope || 'https://www.googleapis.com/auth/drive.file'}</span></div>
        <div className="text-xs">Status: {ws?.exists ? '✓ Created' : '— Not created (will auto-create on login)'} • Mock: {ws?.mock ? 'yes' : 'no'}</div>
        {ws?.files && <div className="text-xs mt-1">Files in Drive: {ws.files.length} {ws.files.slice(0,3).map((f:any)=>f.name).join(', ')}</div>}
      </div>
      <div className="flex gap-2">
        <Button size="sm" onClick={connect} disabled={loading}>{loading ? 'Connecting…' : 'Connect Google Drive (Mock)'}</Button>
        <Button size="sm" variant="outline" onClick={load}>Refresh</Button>
        <Button size="sm" variant="outline" onClick={async()=>{
          try{ const v=await driveService.verify(); setMsg(v.match ? '✓ Write/Read verified' : 'Failed'); }catch(e:any){ setMsg(e.message)}
          setTimeout(()=> setMsg(null),2500)
        }}>Verify Write/Read</Button>
      </div>
      {msg && <div className="text-xs text-emerald-600">{msg}</div>}
      <div className="text-xs text-slate-500 leading-relaxed">Non-destructive: uploads stream to Drive + keep /tmp during analysis, results save directly to Drive, then explicit <span className="font-mono">os.remove</span> cleanup — zero leftover tmp.</div>
    </div>
  )
}

export default function Settings(){
  const { user, logout } = useAuth()
  const [theme,setTheme]=useState(localStorage.getItem('odc-theme')||'dark')
  const [defaultEmail,setDefaultEmail]=useState<string>(()=> localStorage.getItem('odc-default-alert-email')||'')
  const [defaultSlack,setDefaultSlack]=useState<string>(()=> localStorage.getItem('odc-default-slack-webhook')||'')
  const [emailTest,setEmailTest]=useState<string|null>(null)
  const [slackTest,setSlackTest]=useState<string|null>(null)
  useEffect(()=>{
    const root=document.documentElement
    if(theme==='dark') root.classList.add('dark'); else root.classList.remove('dark')
    localStorage.setItem('odc-theme',theme)
  },[theme])
  const { data: aiStatus } = useQuery({ queryKey:['ai-status'], queryFn: async()=> (await api.get('/api/ai/status')).data })
  const mode = aiStatus?.mode || 'Deterministic Analysis'
  const isLLM = mode.toLowerCase().includes('llm')
  const configured = !!aiStatus?.configured
  return (
    <div className="space-y-6 max-w-[720px]">
      <div>
        <h1 className="text-[26px] font-semibold tracking-tight">Settings</h1>
        <p className="text-sm text-slate-600 dark:text-white/60">Profile, appearance, privacy and account.</p>
      </div>
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><User className="h-4 w-4" /> Profile</CardTitle></CardHeader>
        <CardContent className="space-y-2 text-sm">
          <div className="flex justify-between rounded-full border px-4 py-2.5 bg-slate-50 dark:bg-white/5 dark:border-white/10"><span className="text-slate-500">Email</span><span className="font-medium">{user?.email}</span></div>
          <div className="flex justify-between rounded-full border px-4 py-2.5 bg-slate-50 dark:bg-white/5 dark:border-white/10"><span className="text-slate-500">Name</span><span className="font-medium">{user?.name||'—'}</span></div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Palette className="h-4 w-4" /> Appearance</CardTitle><p className="text-xs text-slate-500">Premium light & dark — both crafted, not inverted</p></CardHeader>
        <CardContent className="flex gap-2">
          {[
            {id:'light', label:'Light', desc:'Warm white'},
            {id:'dark', label:'Dark', desc:'Deep navy'},
          ].map(t=>(
            <button key={t.id} onClick={()=>setTheme(t.id)} className={`flex-1 rounded-[16px] border p-4 text-left ${theme===t.id?'bg-[#0b0d18] text-white dark:bg-white dark:text-[#0b0d18] border-transparent':'bg-white dark:bg-white/5 dark:border-white/10 hover:bg-slate-50'}`}>
              <div className="font-medium text-sm">{t.label}</div><div className="text-xs opacity-60">{t.desc}</div>
            </button>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Bell className="h-4 w-4" /> Notifications</CardTitle><p className="text-xs text-slate-500">Default alert channels for monitors</p></CardHeader>
        <CardContent className="space-y-3">
          <div>
            <label className="text-xs font-medium">Default alert email</label>
            <input value={defaultEmail} onChange={e=>{ setDefaultEmail(e.target.value); localStorage.setItem('odc-default-alert-email', e.target.value)}} placeholder="you@company.com" className="w-full h-9 rounded-full border px-3 text-sm mt-1 bg-white dark:bg-white/5 dark:border-white/10" />
          </div>
          <div>
            <label className="text-xs font-medium">Default Slack webhook</label>
            <input value={defaultSlack} onChange={e=>{ setDefaultSlack(e.target.value); localStorage.setItem('odc-default-slack-webhook', e.target.value)}} placeholder="https://hooks.slack.com/..." className="w-full h-9 rounded-full border px-3 text-sm mt-1 bg-white dark:bg-white/5 dark:border-white/10" />
          </div>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" onClick={async()=>{
              try{
                const res=await api.post('/api/notifications/test/email', {email: defaultEmail || user?.email})
                setEmailTest(res.data.sent ? 'Sent ✓' : `Failed: ${res.data.error || 'not configured'}`)
              }catch(e:any){ setEmailTest(e.response?.data?.detail || e.message) }
              setTimeout(()=>setEmailTest(null),3000)
            }}><Mail className="h-3.5 w-3.5 mr-1" />Send test email</Button>
            <Button size="sm" variant="outline" onClick={async()=>{
              try{
                const res=await api.post('/api/notifications/test/slack', {webhook_url: defaultSlack})
                setSlackTest(res.data.sent ? 'Sent ✓' : 'Failed')
              }catch(e:any){ setSlackTest(e.response?.data?.detail || e.message) }
              setTimeout(()=>setSlackTest(null),3000)
            }}><Send className="h-3.5 w-3.5 mr-1" />Send test Slack</Button>
          </div>
          {emailTest && <div className="text-xs text-emerald-600">{emailTest}</div>}
          {slackTest && <div className="text-xs text-emerald-600">{slackTest}</div>}
        </CardContent>
      </Card>

      {/* AI Status - informational only, not provider configuration */}
      <Card className="overflow-hidden">
        <div className={`h-1 ${configured ? 'bg-emerald-500' : 'bg-slate-300 dark:bg-white/10'}`} />
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><Cpu className="h-4 w-4" /> AI Status</CardTitle>
          <p className="text-xs text-slate-500">Informational — provider is controlled server-side.</p>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className={`rounded-[12px] border p-3 flex gap-2 text-sm ${configured ? 'bg-emerald-50 border-emerald-200 dark:bg-emerald-500/10 dark:border-emerald-500/20' : 'bg-slate-50 dark:bg-white/5 dark:border-white/10'}`}>
            {configured ? <Check className="h-4 w-4 text-emerald-600 mt-0.5" /> : <Info className="h-4 w-4 text-slate-500 mt-0.5" />}
            <span className="flex-1">
              <span className="font-medium block">{isLLM ? '● Available — LLM-powered when available' : '● Verified Deterministic Analysis'}</span>
              <span className="text-xs text-slate-600 dark:text-white/70">{configured ? 'LLM-powered explanations when available. Automatically falls back to verified deterministic analysis if unavailable — no error popup.' : 'Deterministic analysis active. All calculations run locally via DuckDB; LLM would only explain results.'}</span>
            </span>
          </div>
          <details className="rounded-[12px] border bg-white dark:bg-white/5 dark:border-white/10 p-3 text-xs">
            <summary className="cursor-pointer font-medium">Technical details</summary>
            <div className="mt-2 text-slate-600 dark:text-white/70 leading-relaxed">
              <div>Mode: {mode} • Status: {aiStatus?.status || 'deterministic'}</div>
              <div className="mt-1">Deterministic metrics are always computed locally. Full raw dataset is never sent to external LLM — only schema, limited samples and results when required.</div>
              <Link to="/privacy" className="underline mt-2 inline-block">Privacy Center</Link>
            </div>
          </details>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Shield className="h-4 w-4" /> Privacy</CardTitle></CardHeader>
        <CardContent className="text-sm space-y-2">
          <p className="text-xs text-slate-600 dark:text-white/60 leading-relaxed">Full raw dataset is never sent to external LLM. Only schema/context/limited samples/results are sent when required. Deterministic calculations happen locally. LLM explains but does not become the numerical source of truth.</p>
          <Link to="/privacy"><Button size="sm" variant="outline">Open Privacy Center</Button></Link>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Shield className="h-4 w-4" /> Bring Your Own Storage (BYOS)</CardTitle><p className="text-xs text-slate-500">Google Drive — stream uploads to your Drive, temporary /tmp during analysis, results saved directly to Drive</p></CardHeader>
        <CardContent className="space-y-3 text-sm">
          <DriveBYOSCard />
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><Shield className="h-4 w-4" /> Account</CardTitle></CardHeader>
        <CardContent><Button variant="outline" onClick={logout}><LogOut className="h-3.5 w-3.5 mr-1.5" />Logout</Button></CardContent>
      </Card>
    </div>
  )
}
