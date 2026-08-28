import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'

/**
 * SPA-friendly OAuth callback handler for Vercel.
 * Handles Google OAuth redirect without hard server reload.
 * 
 * Backend redirects here after OAuth: /auth/callback?code=...&state=... or /settings?status=success
 * This component parses token/code and navigates via React Router (no full reload to avoid Vercel 404).
 */
export default function OAuthCallback() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const { loginWithToken, refresh } = useAuth()
  const [msg, setMsg] = useState('Processing OAuth callback...')
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    // Extract from both useSearchParams and window.location.search for hard redirect robustness
    const urlParams = new URLSearchParams(window.location.search)
    const code = searchParams.get('code') || urlParams.get('code')
    const state = searchParams.get('state') || urlParams.get('state')
    const status = searchParams.get('status') || urlParams.get('status')
    const detail = searchParams.get('detail') || urlParams.get('detail') || searchParams.get('error') || urlParams.get('error') || urlParams.get('message')
    const token = searchParams.get('token') || searchParams.get('access_token') || urlParams.get('token') || urlParams.get('access_token')
    void state // keep for future use

    const handleSuccessWithToken = async (t: string) => {
      try {
        setMsg('Authentication successful, persisting session...')
        localStorage.setItem('token', t)
        // Cleanly update Auth state so isAuthenticated becomes true
        await loginWithToken(t)
        await refresh()
        setMsg('Welcome! Redirecting to dashboard...')
        // Clean URL and navigate without hard reload
        setSearchParams({}, { replace: true })
        navigate('/dashboard', { replace: true })
      } catch (e: any) {
        // Fallback: still persist token and navigate
        localStorage.setItem('token', t)
        setSearchParams({}, { replace: true })
        navigate('/dashboard', { replace: true })
      }
    }

    const handleError = (message: string) => {
      const decoded = decodeURIComponent(message)
      setErr(decoded)
      setMsg(`OAuth failed: ${decoded}`)
      // Explicit error toast/alert so user knows what went wrong
      console.error('[oauth] error:', decoded)
      setTimeout(() => {
        setSearchParams({}, { replace: true })
        navigate(`/login?error=${encodeURIComponent(decoded)}`, { replace: true })
      }, 2500)
    }

    // Priority 1: token present (e.g., /login?token=...&status=success or /auth/callback?token=...)
    if (token) {
      void handleSuccessWithToken(token)
      return
    }

    // Priority 2: status param
    if (status) {
      if (status === 'success') {
        // Check if token was also in URL but missed (already handled) - otherwise try to use existing token
        const existing = localStorage.getItem('token')
        if (existing) {
          void handleSuccessWithToken(existing)
          return
        }
        setMsg('Google Drive connected successfully!')
        setTimeout(() => {
          setSearchParams({}, { replace: true })
          navigate('/settings?status=success', { replace: true })
        }, 1000)
      } else {
        handleError(detail || status)
      }
      return
    }

    // Priority 3: error param without status
    if (detail && !token && !status) {
      handleError(detail)
      return
    }

    // If code + state present and frontend needs to exchange via backend (SPA flow)
    if (code) {
      setMsg('Completing OAuth...')
      setTimeout(() => {
        setSearchParams({}, { replace: true })
        navigate('/settings', { replace: true })
      }, 500)
      return
    }

    setMsg('No OAuth data found, redirecting to login...')
    setTimeout(() => {
      setSearchParams({}, { replace: true })
      navigate('/login', { replace: true })
    }, 1500)
  }, [searchParams, navigate, loginWithToken, refresh, setSearchParams])

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#f8f9fb] dark:bg-[#070914] p-4">
      <div className="text-center space-y-4 max-w-md">
        <div className="h-8 w-8 border-2 border-slate-300 border-t-[#6d6af0] rounded-full animate-spin mx-auto" />
        <p className="text-sm text-slate-600 dark:text-white/60">{msg}</p>
        {err && (
          <div className="text-sm text-red-600 rounded-full bg-red-50 border border-red-200 px-4 py-3 dark:bg-red-500/10 dark:border-red-500/20">
            {err}
          </div>
        )}
      </div>
    </div>
  )
}
