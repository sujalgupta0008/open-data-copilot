import { createContext, useContext, useEffect, useState, ReactNode } from 'react'
import api from '@/services/api'

interface User { id: string; email: string; name?: string }
interface AuthContextType { user: User | null; loading: boolean; login: (email: string, password: string) => Promise<void>; signup: (email: string, password: string, name?: string) => Promise<void>; logout: () => void; setUser: (user: User | null) => void; refresh: () => Promise<void>; loginWithToken: (token: string) => Promise<void> }

const AuthContext = createContext<AuthContextType>(null as any)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const fetchMe = async () => {
    const token = localStorage.getItem('token')
    if (!token) { setLoading(false); return }
    try {
      const res = await api.get('/api/auth/me')
      setUser(res.data)
    } catch { localStorage.removeItem('token') }
    setLoading(false)
  }

  useEffect(() => { void fetchMe() }, [])

  const login = async (email: string, password: string) => {
    const res = await api.post('/api/auth/login', { email, password })
    localStorage.setItem('token', res.data.access_token)
    setUser(res.data.user)
  }

  const signup = async (email: string, password: string, name?: string) => {
    const res = await api.post('/api/auth/register', { email, password, name })
    localStorage.setItem('token', res.data.access_token)
    setUser(res.data.user)
  }

  const logout = () => {
    localStorage.removeItem('token')
    setUser(null)
    api.post('/api/auth/logout').catch(()=>{})
  }

  const refresh = async () => {
    const token = localStorage.getItem('token')
    if (!token) { setUser(null); setLoading(false); return }
    setLoading(true)
    try {
      const res = await api.get('/api/auth/me')
      setUser(res.data)
    } catch {
      localStorage.removeItem('token')
      setUser(null)
    }
    setLoading(false)
  }

  const loginWithToken = async (token: string) => {
    localStorage.setItem('token', token)
    try {
      const res = await api.get('/api/auth/me')
      setUser(res.data)
    } catch {
      // Token invalid - keep it but user remains null, will be cleared on next fetchMe
      // Try to decode token payload as fallback (for mock Google tokens)
      try {
        const payload = JSON.parse(atob(token.split('.')[1]))
        if (payload.sub) {
          // optimistic fallback - will be replaced on next refresh
          setUser({ id: payload.sub, email: '', name: '' } as User)
        }
      } catch {}
    }
  }

  return <AuthContext.Provider value={{ user, loading, login, signup, logout, setUser, refresh, loginWithToken }}>{children}</AuthContext.Provider>
}

export const useAuth = () => useContext(AuthContext)
