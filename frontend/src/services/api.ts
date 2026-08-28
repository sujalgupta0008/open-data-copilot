import axios from 'axios'

const rawBaseURL = (import.meta as unknown as { env: Record<string, string> }).env?.VITE_API_URL || ''
const api = axios.create({
  // Strip trailing slash from VITE_API_URL to avoid double-slash or mismatch with FastAPI prefix
  baseURL: rawBaseURL.replace(/\/+$/, ''),
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
  // Fix 308 Permanent Redirect (trailing slash mismatch):
  // FastAPI with redirect_slashes=True will 308-redirect /path/ <-> /path, which
  // axios/fetch follows but strips auth headers / changes POST to GET leading to 404.
  // Ensure frontend ALWAYS uses exact path defined by backend (without trailing slash).
  // Strip trailing slashes from request URL (except root) so no 308 is triggered.
  if (config.url && config.url !== '/' && config.url.endsWith('/')) {
    // Keep query params intact: split on ? before stripping
    const qIndex = config.url.indexOf('?')
    if (qIndex === -1) {
      config.url = config.url.replace(/\/+$/, '')
    } else {
      const path = config.url.substring(0, qIndex).replace(/\/+$/, '')
      const query = config.url.substring(qIndex)
      config.url = path + query
    }
  }
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
