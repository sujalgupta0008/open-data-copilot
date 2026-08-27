import axios from 'axios'

const api = axios.create({
  baseURL: (import.meta as unknown as { env: Record<string, string> }).env?.VITE_API_URL || '',
  // Default 60s; heavy analysis (data-quality audit, full profiling) can exceed 30s on large datasets
  timeout: 60000,
})

// SPA-friendly 401 handling: allow App to inject React Router navigation
// Falls back to window.location.href only when no SPA navigator is registered
let spaNavigate: ((path: string) => void) | null = null
export const setSpaNavigate = (fn: (path: string) => void) => { spaNavigate = fn }

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      if (window.location.pathname !== '/login' && window.location.pathname !== '/signup') {
        if (spaNavigate) {
          spaNavigate('/login')
        } else {
          window.location.href = '/login'
        }
      }
    }
    return Promise.reject(err)
  }
)

export default api
