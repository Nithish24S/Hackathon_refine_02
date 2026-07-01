import React, {useState} from 'react'
import { api } from '../api/client'

const ALLOWED_EXTENSIONS = ['.xlsx']
const ACCEPT_ATTR = ALLOWED_EXTENSIONS.join(',')

function SummaryMetric({label, value}){
  return (
    <div className="rounded-2xl bg-slate-900 p-4 flex flex-col gap-2 border border-slate-700">
      <span className="text-sm uppercase tracking-[0.2em] text-slate-400">{label}</span>
      <span className="text-2xl font-semibold text-white">{value}</span>
    </div>
  )
}

export function UploadPage({onSuccess}){
  const [file, setFile] = useState(null)
  const [status, setStatus] = useState({loading:false, error:null})

  const handleFileChange = (event) => {
    setStatus({loading:false, error:null})
    const selected = event.target.files[0]
    setFile(selected || null)
  }

  const handleUpload = async (event) => {
    event.preventDefault()
    setStatus({loading:false, error:null})
    if (!file) {
      setStatus({loading:false, error:new Error('Select a .xlsx workbook before uploading.')})
      return
    }
    const lower = file.name.toLowerCase()
    if (!ALLOWED_EXTENSIONS.some(ext => lower.endsWith(ext))) {
      setStatus({loading:false, error:new Error(`File must be one of: ${ACCEPT_ATTR}`)})
      return
    }

    setStatus({loading:true, error:null})
    try {
      const formData = new FormData()
      formData.append('file', file)
      const result = await api.upload(formData)
      setStatus({loading:false, error:null})
      onSuccess?.(result)
    } catch (error) {
      setStatus({loading:false, error})
    }
  }

  const {loading,error} = status

  return (
    <section className="space-y-6">
      <div className="rounded-3xl bg-slate-900/95 border border-slate-700 p-6 shadow-xl">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <p className="text-sm uppercase tracking-[0.3em] text-amber-400">Workbook upload</p>
            <h2 className="mt-2 text-3xl font-extrabold text-white">Upload your validated project file</h2>
            <p className="mt-3 max-w-2xl text-slate-300">Use the backend parser directly. The upload only accepts <span className="font-semibold text-white">.xlsx</span>.</p>
          </div>
          <div className="rounded-3xl border border-slate-700 bg-slate-950 p-4">
            <form onSubmit={handleUpload} className="flex flex-col gap-4 sm:flex-row sm:items-center">
              <label className="overflow-hidden rounded-xl border border-slate-700 bg-slate-900 px-4 py-3 text-sm text-slate-200 shadow-inner shadow-black/10 cursor-pointer hover:bg-slate-800">
                <span>{file ? file.name : 'Choose .xlsx file'}</span>
                <input type="file" accept={ACCEPT_ATTR} onChange={handleFileChange} className="sr-only" />
              </label>
              <button type="submit" disabled={loading} className="rounded-xl bg-emerald-500 px-5 py-3 text-sm font-semibold text-slate-950 transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60">
                {loading ? 'Uploading…' : 'Upload workbook'}
              </button>
            </form>
            <p className="mt-2 text-xs text-slate-500">Allowed file type: {ACCEPT_ATTR}</p>
          </div>
        </div>

        {error && (
          <div className="mt-6 rounded-2xl border border-amber-700 bg-amber-950/80 p-4 text-amber-100">
            <strong>Error uploading file:</strong> {error.message}
          </div>
        )}

        {!loading && !error && (
          <div className="mt-6 rounded-2xl border border-slate-700 bg-slate-900 p-4 text-slate-300">
            Select a valid workbook and submit to proceed.
          </div>
        )}
      </div>
    </section>
  )
}
