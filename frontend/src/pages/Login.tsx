import { useState, useEffect } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { Button } from '@/components/common/Button'
import { Input } from '@/components/common/Input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/common/Card'
import api from '@/services/api'

export default function Login(){
  const [email,setEmail]=useState(''); const [password,setPassword]=useState(''); const [err,setErr]=useState(''); const { login, loginWithToken, refresh } = useAuth(); const nav=useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()

  // SPA OAuth callback handling - Vercel rewrite ensures /login?token=...&status=success is handled without 404
  // Extract token immediately on mount from useSearchParams OR window.location.search to persist session
  useEffect(() => {
    // Check both useSearchParams and window.location.search for robustness (hard redirect vs SPA)
    const urlParams = new URLSearchParams(window.location.search)
    const token = searchParams.get('token') || searchParams.get('access_token') || urlParams.get('token') || urlParams.get('access_token')
    const status = searchParams.get('status') || urlParams.get('status')
    const error = searchParams.get('error') || searchParams.get('detail') || urlParams.get('error') || urlParams.get('detail') || urlParams.get('message')
    const code = searchParams.get('code') || urlParams.get('code')

    const handleToken = async (t: string) => {
      try {
        // Persist session
        localStorage.setItem('token', t)
        // Cleanly update Auth state so isAuthenticated becomes true
        await loginWithToken(t)
        // Also refresh to ensure user is loaded
        await refresh()
        // Clean URL params without hard reload
        setSearchParams({}, { replace: true })
        // Navigate to dashboard
        nav('/dashboard', { replace: true })
      } catch (e) {
        // Fallback: still store and navigate even if /me fails (mock token)
        localStorage.setItem('token', t)
        setSearchParams({}, { replace: true })
        nav('/dashboard', { replace: true })
      }
    }

    if (token) {
      void handleToken(token)
      return
    }

    if (status === 'success' && !token) {
      // Backend redirected with status=success but no token (e.g., Drive linking) - check if we already have token
      const existing = localStorage.getItem('token')
      if (existing) {
        void refresh().then(() => nav('/dashboard', { replace: true }))
      } else {
        // No token yet, maybe backend sent code instead - keep showing login but clear params
        setSearchParams({}, { replace: true })
      }
      return
    }

    if (error || status === 'error') {
      const msg = decodeURIComponent(error || 'OAuth failed')
      setErr(msg)
      // Explicit error toast/alert so user knows what went wrong
      console.error('[oauth] error:', msg)
      setSearchParams({}, { replace: true })
      return
    }

    if (code && !token && !status) {
      console.log('[oauth] code received on /login, waiting for backend redirect...')
      // Optionally exchange code via SPA: call backend callback without hard reload
      // This avoids Vercel 404 on hard reload to /api/auth/google/callback
    }
  }, [searchParams, nav, loginWithToken, refresh, setSearchParams])
  const submit=async(e:any)=>{
    e.preventDefault(); setErr('');
    if (!email.includes('@')) { setErr('Please enter a valid email'); return }
    if (!password) { setErr('Password is required'); return }
    try{ await login(email,password); nav('/dashboard')}catch(ex:any){
      const detail = ex.response?.data?.detail
      const msg = Array.isArray(detail) ? detail.map((d:any)=>d.msg).join(', ') : (detail || 'Login failed')
      if (ex.response?.status === 404 || ex.response?.status === 308) {
        setErr('Login endpoint not found (404/308). Check VITE_API_URL and backend CORS. Backend should be ' + ((import.meta as any).env?.VITE_API_URL || 'proxy via Vite'))
      } else {
        setErr(msg)
      }
      console.error('[login] failed', ex.response?.status, ex.response?.data)
    }
  }
  const handleGoogleLogin = async () => {
    setErr('')
    try {
      // Backend route is GET /api/auth/google/login (no trailing slash) - must match exactly to avoid 308
      const res = await api.get('/api/auth/google/login')
      const auth_url = res.data?.auth_url
      if (auth_url) {
        window.location.href = auth_url
      } else {
        setErr('Failed to get Google auth URL')
      }
    } catch (ex: any) {
      const detail = ex.response?.data?.detail
      const msg = Array.isArray(detail) ? detail.map((d:any)=>d.msg).join(', ') : detail
      if (ex.response?.status === 404 || ex.response?.status === 308) {
        setErr('Google login endpoint not found (404/308). Ensure backend is running and VITE_API_URL='+ ((import.meta as any).env?.VITE_API_URL || 'proxy'))
      } else {
        setErr(msg || 'Google login failed')
      }
      console.error('[google login] failed', ex.response?.status, ex.response?.data)
    }
  }
  return (
    <div className="min-h-screen flex items-center justify-center bg-[#f8f9fb] dark:bg-[#070914] p-4 relative overflow-hidden">
      <div className="absolute inset-0 mesh opacity-60" />
      <div className="absolute inset-0 grid-pattern opacity-20" />
      <Card className="w-full max-w-md relative">
        <div className="h-1 bg-gradient-to-r from-[#6d6af0] to-[#38bdf8] rounded-t-[16px]" />
        <CardHeader className="text-center">
          <div className="mx-auto h-10 w-10 rounded-xl bg-[#0b0d18] dark:bg-white grid place-items-center mb-3"><div className="h-2.5 w-2.5 rounded-full bg-white dark:bg-[#0b0d18]" /></div>
          <CardTitle className="text-[18px]">Welcome back</CardTitle>
          <p className="text-sm text-slate-500">Sign in to your premium workspace</p>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4">
            <Input placeholder="Email" value={email} onChange={(e:any)=>setEmail(e.target.value)} required/>
            <Input placeholder="Password" type="password" value={password} onChange={(e:any)=>setPassword(e.target.value)} required/>
            {err && <div className="text-sm text-red-600 rounded-full bg-red-50 border border-red-200 px-3 py-2 dark:bg-red-500/10 dark:border-red-500/20">{err}</div>}
            <Button className="w-full" type="submit">Sign In</Button>
          </form>
          <div className="relative my-6">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-slate-200 dark:border-white/10" />
            </div>
            <div className="relative flex justify-center text-xs uppercase">
              <span className="bg-white dark:bg-[#13151f] px-2 text-slate-500">Or</span>
            </div>
          </div>
          <Button variant="outline" className="w-full" type="button" onClick={handleGoogleLogin}>
            Sign in with Google
          </Button>
          <div className="mt-6 text-sm text-center text-slate-500">No account? <Link to="/signup" className="underline font-medium text-slate-900 dark:text-white">Sign up</Link></div>
        </CardContent>
      </Card>
    </div>
  )
}
