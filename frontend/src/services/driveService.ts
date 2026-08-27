import api from './api'

export interface DriveWorkspace {
  folder_name: string
  path: string
  exists: boolean
  scope: string
  authenticated: boolean
  mock: boolean
  files: Array<{name: string, path: string, size: number}>
}

export const driveService = {
  // Google OAuth 2.0 with scope drive.file
  getAuthUrl: () => api.get('/api/auth/google/login').then(r => r.data),
  mockLogin: () => api.post('/api/auth/google/mock-login').then(r => r.data),
  getStatus: () => api.get('/api/auth/google/status').then(r => r.data),

  // Workspace
  getWorkspace: (): Promise<DriveWorkspace> => api.get('/api/drive/workspace').then(r => r.data),
  listFiles: () => api.get('/api/drive/files').then(r => r.data),
  verify: () => api.get('/api/drive/verify').then(r => r.data),

  // Cleanup hook
  cleanup: (tmp_path: string) => api.post('/api/drive/cleanup', { tmp_path }).then(r => r.data),
}
