import React, {useEffect, useState} from 'react'
import { Dashboard } from './pages/Dashboard'
import { UploadPage } from './pages/Upload'
import { DemoControls } from './pages/DemoControls'
import { api } from './api/client'

export default function App(){
  const [backendOk, setBackendOk] = useState(null)
  const [session, setSession] = useState(null)

  useEffect(()=>{
    let mounted = true
    api.health().then(()=>{ if(mounted) setBackendOk(true)}).catch(()=>{ if(mounted) setBackendOk(false)})
    return ()=> mounted=false
  },[])

  const handleSessionEstablished = (data) => {
    setSession(data)
  }

  const handleReset = async () => {
    try {
      await api.demoReset()
    } catch (error) {
      console.error('Failed to reset session:', error)
    }
    setSession(null)
  }

  return (
    <div className="app-shell font-sans">
      <div className="max-w-7xl mx-auto p-6">
        <header className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mb-6">
          <div>
            <h1 className="text-3xl font-extrabold">Sprint Whisperer</h1>
            <p className="text-sm text-slate-300">Project forecasting & risk dashboard</p>
          </div>
          <div>
            {backendOk===null ? (
              <span className="px-3 py-1 bg-slate-700 text-slate-200 rounded">Checking backend…</span>
            ) : backendOk ? (
              <span className="px-3 py-1 bg-emerald-600 text-white rounded">Backend: OK</span>
            ) : (
              <span className="px-3 py-1 bg-red-600 text-white rounded">Backend unreachable</span>
            )}
          </div>
        </header>

        <main>
          {session ? (
            <Dashboard session={session} onReset={handleReset} />
          ) : (
            <div className="space-y-6">
              <UploadPage onSuccess={handleSessionEstablished} />
              <DemoControls onLoadSuccess={handleSessionEstablished} />
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
