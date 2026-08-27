import api from '@/services/api'

export async function authenticatedDownload(path: string, filename?: string){
  const res = await api.get(path, { responseType: 'blob' })
  const blob = res.data as Blob
  const contentDisp = (res.headers as any)['content-disposition'] || (res.headers as any)['Content-Disposition']
  let outName = filename || 'download'
  if(contentDisp){
    const m = /filename="?([^"]+)"?/.exec(contentDisp)
    if(m) outName = m[1]
  }
  if(!outName.includes('.')){
    // try to guess from content-type
    const ct = (res.headers as any)['content-type'] || ''
    if(ct.includes('json')) outName += '.json'
    else if(ct.includes('csv')) outName += '.csv'
    else if(ct.includes('pdf')) outName += '.pdf'
  }
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = outName
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(()=> URL.revokeObjectURL(url), 2000)
}

export async function authenticatedPowerBiDownload(datasetId: string){
  // Power BI endpoint returns JSON - fetch via api and download as JSON file
  const res = await api.get(`/api/datasets/${datasetId}/export/powerbi`)
  const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `powerbi_${datasetId}.json`
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(()=> URL.revokeObjectURL(url), 2000)
}
