import { useState, useEffect } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { Button } from '@/components/common/Button'
import { Input } from '@/components/common/Input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/common/Card'
import api from '@/services/api'

export default function Signup(){
  const [email,setEmail]=useState(''); const [password,setPassword]=useState(''); const [name,setName]=useState(''); const [err,setErr]=useState(''); const { signup } = useAuth(); const nav=useNavigate()
  const [searchParams] = useSearchParams()

  // SPA OAuth callback handling - Vercel rewrite ensures /signup?code=... is handled client-side without 404
  useEffect(() => {
    const token = searchParams.get('token') || searchParams.get('access_token')
    const status = searchParams.get('status')
    const error = searchParams.get('error') || searchParams.get('detail')
    if (token) {
      localStorage.setItem('token', token)
      nav('/dashboard', { replace: true })
    } else if (status === 'success') {
      nav('/dashboard', { replace: true })
    } else if (error || status === 'error') {
      setErr(decodeURIComponent(error || 'OAuth failed'))
    }
  }, [searchParams, nav])
  const submit=async(e:any)=>{
    e.preventDefault(); setErr('');
    // Frontend validation to avoid 422
    if (!email.includes('@')) { setErr('Please enter a valid email'); return }
    if (password.length < 6) { setErr('Password must be at least 6 characters'); return }
    try{ await signup(email,password,name); nav('/dashboard')}catch(ex:any){
      const detail = ex.response?.data?.detail
      // FastAPI 422 returns array [{loc, msg}], 400 returns string
      const msg = Array.isArray(detail) ? detail.map((d:any)=>d.msg).join(', ') : (detail || 'Signup failed')
      // Also handle 308/404 due to trailing slash mismatch
      if (ex.response?.status === 404 || ex.response?.status === 308) {
        setErr('Signup endpoint not found (404/308). Check VITE_API_URL and ensure backend is running on '+ ( (import.meta as any).env?.VITE_API_URL || 'proxy'))
      } else {
        setErr(msg)
      }
      console.error('[signup] failed', ex.response?.status, ex.response?.data)
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
          <CardTitle className="text-[18px]">Create your workspace</CardTitle>
          <p className="text-sm text-slate-500">Premium data intelligence — free to start</p>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="space-y-4">
            <Input placeholder="Name" value={name} onChange={(e:any)=>setName(e.target.value)} />
            <Input placeholder="Email" value={email} onChange={(e:any)=>setEmail(e.target.value)} required/>
            <Input placeholder="Password (min 6)" type="password" value={password} onChange={(e:any)=>setPassword(e.target.value)} required/>
            {err && <div className="text-sm text-red-600 rounded-full bg-red-50 border border-red-200 px-3 py-2 dark:bg-red-500/10 dark:border-red-500/20">{err}</div>}
            <Button className="w-full" type="submit">Create Account</Button>
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
          <div className="mt-6 text-sm text-center text-slate-500">Have account? <Link to="/login" className="underline font-medium text-slate-900 dark:text-white">Sign in</Link></div>
        </CardContent>
      </Card>
    </div>
  )
}
