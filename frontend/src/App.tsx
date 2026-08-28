import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider, useAuth } from '@/hooks/useAuth'
import { Sidebar } from '@/components/layout/Sidebar'
import { CommandPalette } from '@/components/common/CommandPalette'
import { useState, useEffect, lazy, Suspense } from 'react'
import { useParams, Navigate as RouterNavigate } from 'react-router-dom'
import { setSpaNavigate } from '@/services/api'

const Landing = lazy(()=> import('@/pages/Landing'))
const Login = lazy(()=> import('@/pages/Login'))
const Signup = lazy(()=> import('@/pages/Signup'))
const Dashboard = lazy(()=> import('@/pages/Dashboard'))
const Datasets = lazy(()=> import('@/pages/Datasets'))
const DatasetDetail = lazy(()=> import('@/pages/DatasetDetail'))
const Copilot = lazy(()=> import('@/pages/Copilot'))
const AnalysisHistory = lazy(()=> import('@/pages/AnalysisHistory').then(m=> ({ default: m.default })))
const AnalysisDetail = lazy(()=> import('@/pages/AnalysisHistory').then(m=> ({ default: m.AnalysisDetail })))
const Reports = lazy(()=> import('@/pages/Reports'))
const Settings = lazy(()=> import('@/pages/Settings'))
const PrivacyCenter = lazy(()=> import('@/pages/PrivacyCenter'))
const SharedReport = lazy(()=> import('@/pages/SharedReport'))
const SharedAnalysis = lazy(()=> import('@/pages/SharedAnalysis'))
const OAuthCallback = lazy(()=> import('@/pages/OAuthCallback'))

const qc = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 0,
      gcTime: 5 * 60 * 1000,
      refetchOnWindowFocus: false,
      refetchOnMount: true,
      retry: 1,
    },
    mutations: {
      retry: 0,
    },
  },
})

function Protected({ children }: any){
  const { user, loading } = useAuth()
  const [collapsed,setCollapsed]=useState(false)
  const [dark,setDark]=useState<boolean>(()=> {
    if(typeof window==='undefined') return true
    const v=localStorage.getItem('odc-theme')
    if(v) return v==='dark'
    return true
  })
  useEffect(()=>{ document.documentElement.classList.toggle('dark', dark); localStorage.setItem('odc-theme', dark?'dark':'light') },[dark])

  if(loading) return (
    <div className="min-h-screen grid place-items-center bg-white dark:bg-[#0a0c14]">
      <div className="flex flex-col items-center gap-3">
        <div className="h-8 w-8 rounded-xl bg-[#0b0d18] dark:bg-white animate-pulse" />
        <div className="h-3 w-24 shimmer rounded-full" />
        <div className="text-xs text-slate-500">Loading workspace…</div>
      </div>
    </div>
  )
  if(!user) return <Navigate to="/login" replace/>
  return (
    <div className="min-h-screen bg-[#f8f9fb] dark:bg-[#070914] text-slate-900 dark:text-white">
      <div className="flex min-h-screen">
        <Sidebar collapsed={collapsed} onToggle={()=>setCollapsed(c=>!c)} />
        <div className="flex-1 min-w-0 flex flex-col">
          <div className="sticky top-0 z-30 flex h-[64px] items-center justify-between border-b bg-white/80 backdrop-blur-xl dark:bg-[#0a0c14]/70 dark:border-white/[0.06] px-4 lg:px-6">
            <div className="flex items-center gap-3">
              <button onClick={()=>setCollapsed(c=>!c)} className="lg:hidden h-9 w-9 inline-flex items-center justify-center rounded-full border bg-white dark:bg-white/5">≡</button>
              <div className="hidden md:flex items-center gap-2 text-[12px]">
                <span className="inline-flex items-center gap-1.5 rounded-full border bg-white px-2.5 py-1 dark:bg-white/5 dark:border-white/10">
                  <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" /> Live
                </span>
                <span className="text-slate-500 dark:text-white/50">Workspace • Trusted Intelligence</span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <button onClick={()=>setDark(d=>!d)} className="h-9 px-3 rounded-full border bg-white text-xs font-medium hover:bg-slate-50 dark:bg-white/5 dark:border-white/10 dark:hover:bg-white/10">
                {dark ? '☾ Dark' : '☀ Light'}
              </button>
              <button onClick={()=> window.dispatchEvent(new KeyboardEvent('keydown',{key:'k', ctrlKey:true}))} className="hidden md:inline-flex items-center gap-2 rounded-full border bg-white px-3 py-1.5 text-xs dark:bg-white/5 dark:border-white/10">
                ⌘K
              </button>
              <HeaderUserBadge />
            </div>
          </div>
          <div className="flex-1 p-4 lg:p-6 bg-[#f8f9fb] dark:bg-[#070914]">{children}</div>
        </div>
      </div>
      <CommandPalette />
    </div>
  )
}

function HeaderUserBadge(){
  const { user } = useAuth()
  const name = user?.name?.trim() ? user.name : (user?.email ? user.email.split('@')[0] : 'User')
  const initial = name.charAt(0).toUpperCase()
  return <div title={user?.email || ''} className="h-8 w-8 rounded-full bg-[#0b0d18] dark:bg-white text-white dark:text-[#0b0d18] grid place-items-center text-xs font-semibold border dark:border-white/10">{initial}</div>
}

function Fallback(){
  return <div className="p-8 space-y-3"><div className="h-6 w-32 shimmer rounded-full" /><div className="h-[200px] shimmer rounded-[16px]" /></div>
}

function CleaningStudioRedirect(){
  const { id } = useParams()
  return <RouterNavigate to={`/datasets/${id}?tab=prepare&sub=clean&drawer=studio`} replace />
}

function SpaNavigateSetup(){
  const navigate = useNavigate()
  useEffect(()=>{
    setSpaNavigate((path:string)=> navigate(path))
  },[navigate])
  return null
}

export default function App(){
  return (
    <QueryClientProvider client={qc}>
      <AuthProvider>
        <BrowserRouter>
          <SpaNavigateSetup />
          <Suspense fallback={<Fallback/>}>
          <Routes>
            <Route path="/" element={<Landing/>}/>
            <Route path="/login" element={<Login/>}/>
            <Route path="/signup" element={<Signup/>}/>
            {/* OAuth callback - handles Google OAuth redirect via SPA without Vercel 404 */}
            <Route path="/auth/callback" element={<OAuthCallback/>}/>
            <Route path="/oauth/callback" element={<OAuthCallback/>}/>
            <Route path="/shared/r/:token" element={<SharedReport/>}/>
            <Route path="/shared/a/:token" element={<SharedAnalysis/>}/>
            <Route path="/dashboard" element={<Protected><Dashboard/></Protected>}/>
            <Route path="/datasets" element={<Protected><Datasets/></Protected>}/>
            <Route path="/datasets/:id" element={<Protected><DatasetDetail/></Protected>}/>
            <Route path="/datasets/:id/clean" element={<Protected><CleaningStudioRedirect/></Protected>}/>
            <Route path="/datasets/:id/copilot" element={<Protected><Copilot/></Protected>}/>
            <Route path="/analysis" element={<Protected><AnalysisHistory/></Protected>}/>
            <Route path="/analysis/:id" element={<Protected><AnalysisDetail/></Protected>}/>
            <Route path="/reports" element={<Protected><Reports/></Protected>}/>
            <Route path="/privacy" element={<Protected><PrivacyCenter/></Protected>}/>
            <Route path="/settings" element={<Protected><Settings/></Protected>}/>
            <Route path="*" element={<Navigate to="/" replace/>}/>
          </Routes>
          </Suspense>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}
