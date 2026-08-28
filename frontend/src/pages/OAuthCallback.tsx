import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

/**
 * SPA-friendly OAuth callback handler for Vercel.
 * Handles Google OAuth redirect without hard server reload.
 * 
 * Backend redirects here after OAuth: /auth/callback?code=...&state=... or /settings?status=success
 * This component parses token/code and navigates via React Router (no full reload to avoid Vercel 404).
 */
export default function OAuthCallback() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [msg, setMsg] = useState('Processing OAuth callback...')

  useEffect(() => {
    const code = searchParams.get('code')
    const state = searchParams.get('state')
    const status = searchParams.get('status')
    const detail = searchParams.get('detail')
    const token = searchParams.get('token') || searchParams.get('access_token')

    // If backend already exchanged code and redirected to settings, just handle status
    if (status) {
      if (status === 'success') {
        setMsg('Google Drive connected successfully!')
        setTimeout(() => navigate('/settings?status=success', { replace: true }), 1000)
      } else {
        setMsg(`OAuth failed: ${detail || status}`)
        setTimeout(() => navigate(`/login?error=${encodeURIComponent(detail || status)}`, { replace: true }), 2000)
      }
      return
    }

    // If token returned directly (e.g., JWT from backend)
    if (token) {
      localStorage.setItem('token', token)
      setMsg('Authentication successful, redirecting...')
      setTimeout(() => navigate('/dashboard', { replace: true }), 500)
      return
    }

    // If code + state present and frontend needs to exchange via backend (SPA flow)
    if (code) {
      // For mock/dev, we can just redirect to settings - backend already handles exchange
      // If code present without status, navigate to login with code to let backend handle
      setMsg('Completing OAuth...')
      // Use SPA navigation, not hard reload - call backend via fetch
      // Backend endpoint /api/auth/google/callback expects code & state
      // We navigate to settings which will show success - backend already did redirect
      setTimeout(() => navigate('/settings', { replace: true }), 500)
      return
    }

    setMsg('No OAuth data found, redirecting to login...')
    setTimeout(() => navigate('/login', { replace: true }), 1500)
  }, [searchParams, navigate])

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#f8f9fb] dark:bg-[#070914]">
      <div className="text-center space-y-4">
        <div className="h-8 w-8 border-2 border-slate-300 border-t-[#6d6af0] rounded-full animate-spin mx-auto" />
        <p className="text-sm text-slate-600 dark:text-white/60">{msg}</p>
      </div>
    </div>
  )
}
