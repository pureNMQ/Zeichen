import { useEffect, useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ErrorNotification } from '@/components/ui/notification'
import { api, ApiError, type CogneeConfiguration, type CogneeRestartJob, type CogneeRuntimeStatus } from '@/lib/api'

type FormState = {
  llm_provider: string
  llm_model: string
  llm_endpoint: string
  llm_api_key: string
  embedding_provider: string
  embedding_model: string
  embedding_dimensions: string
}

function toForm(configuration: CogneeConfiguration): FormState {
  return {
    llm_provider: configuration.llm_provider,
    llm_model: configuration.llm_model,
    llm_endpoint: configuration.llm_endpoint ?? '',
    llm_api_key: '',
    embedding_provider: configuration.embedding_provider,
    embedding_model: configuration.embedding_model,
    embedding_dimensions: configuration.embedding_dimensions?.toString() ?? '',
  }
}

export function CogneePage() {
  const qc = useQueryClient()
  const [form, setForm] = useState<FormState | null>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [restartError, setRestartError] = useState<string | null>(null)
  const [restartJob, setRestartJob] = useState<CogneeRestartJob | null>(null)

  const configuration = useQuery({
    queryKey: ['cognee-configuration'],
    queryFn: () => api.get<CogneeConfiguration>('/cognee/configuration'),
  })
  const runtimeStatus = useQuery({
    queryKey: ['cognee-runtime-status'],
    queryFn: () => api.get<CogneeRuntimeStatus>('/cognee/configuration/status'),
  })

  useEffect(() => {
    if (configuration.data) setForm(toForm(configuration.data))
  }, [configuration.data])

  useEffect(() => {
    if (!restartJob || !['queued', 'running'].includes(restartJob.status)) return
    const timer = window.setInterval(() => {
      void api.get<{ job: CogneeRestartJob }>(`/cognee/configuration/restarts/${restartJob.id}`)
        .then(({ job }) => {
          setRestartJob(job)
          if (job.status === 'completed') void qc.invalidateQueries({ queryKey: ['cognee-configuration'] })
        })
        .catch((error: unknown) => setRestartError(error instanceof ApiError ? error.message : '无法查询重启状态'))
    }, 1500)
    return () => window.clearInterval(timer)
  }, [qc, restartJob])

  function update(field: keyof FormState, value: string) {
    setForm((current) => current ? { ...current, [field]: value } : current)
  }

  async function save(event: FormEvent) {
    event.preventDefault()
    if (!form) return
    setSaveError(null)
    setSaving(true)
    try {
      const body: Record<string, string | number | null> = {
        llm_provider: form.llm_provider.trim(),
        llm_model: form.llm_model.trim(),
        llm_endpoint: form.llm_endpoint.trim() || null,
        embedding_provider: form.embedding_provider.trim(),
        embedding_model: form.embedding_model.trim(),
        embedding_dimensions: form.embedding_dimensions.trim() ? Number(form.embedding_dimensions) : null,
      }
      if (form.llm_api_key) body.llm_api_key = form.llm_api_key
      const saved = await api.put<CogneeConfiguration>('/cognee/configuration', body)
      setForm(toForm(saved))
      qc.setQueryData(['cognee-configuration'], saved)
    } catch (error) {
      setSaveError(error instanceof ApiError ? error.message : '保存 Cognee 配置失败')
    } finally {
      setSaving(false)
    }
  }

  async function restart() {
    setRestartError(null)
    try {
      const response = await api.post<{ job: CogneeRestartJob }>('/cognee/configuration/restarts', { confirmed: true })
      setRestartJob(response.job)
      setConfirmOpen(false)
    } catch (error) {
      setRestartError(error instanceof ApiError ? error.message : '无法启动 Cognee 重启')
      setConfirmOpen(false)
    }
  }

  const busy = restartJob?.status === 'queued' || restartJob?.status === 'running'
  const currentConfiguration = configuration.data
  const configurationError = configuration.error as Error | null
  const runtimeError = runtimeStatus.error as Error | null
  if (configuration.isLoading) return <p className="text-sm text-muted-foreground">正在加载 Cognee 配置…</p>
  if (configuration.isError || !currentConfiguration || !form) {
    return (
      <div className="space-y-3">
        <ErrorNotification message={configurationError?.message ?? '无法加载 Cognee 配置'} />
        <p className="text-sm text-muted-foreground">无法加载 Cognee 配置。</p>
        <Button variant="outline" onClick={() => void configuration.refetch()}>重试</Button>
      </div>
    )
  }
  const configurationStatus = currentConfiguration.pending_restart ? '配置已保存，等待重启生效' : '当前保存配置已应用'

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <ErrorNotification message={saveError} />
      <ErrorNotification message={restartError} />
      <ErrorNotification message={runtimeError?.message ?? null} />
      <ErrorNotification message={runtimeStatus.data?.runtime.detail ?? null} />
      <div>
        <h1 className="text-2xl font-semibold">Cognee 管理</h1>
        <p className="mt-1 text-sm text-muted-foreground">配置仅在成功重启 Cognee 后生效。</p>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>运行状态</CardTitle>
          <CardDescription>查看 Cognee 服务健康状态并执行重启。</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {runtimeStatus.isLoading ? <p className="text-sm text-muted-foreground">正在检查 Cognee 服务…</p> : runtimeStatus.data ? (
            <div className="space-y-1 text-sm">
              <p><span className="text-muted-foreground">服务状态：</span>{runtimeStatus.data.runtime.availability === 'reachable' ? '可用' : '不可达'}</p>
              <p><span className="text-muted-foreground">最近检查：</span>{new Date(runtimeStatus.data.runtime.checked_at).toLocaleString()}</p>
              {runtimeStatus.data.latest_restart ? <>
                <p><span className="text-muted-foreground">最近重启：</span>{runtimeStatus.data.latest_restart.status_label}</p>
              </> : <p className="text-muted-foreground">尚无重启记录</p>}
            </div>
          ) : <p className="text-sm text-muted-foreground">无法取得 Cognee 服务状态。</p>}
          <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => setConfirmOpen(true)} disabled={busy}>
            {busy ? '重启进行中…' : '重启 Cognee'}
          </Button>
          <Button variant="outline" onClick={() => void runtimeStatus.refetch()} disabled={runtimeStatus.isFetching}>刷新状态</Button>
          {restartJob?.status === 'completed' && <span className="text-sm text-emerald-700 dark:text-emerald-400">最近一次重启已完成</span>}
          {restartJob?.status === 'failed' && <span className="text-sm text-destructive">最近一次重启失败</span>}
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>模型配置</CardTitle>
          <CardDescription>API Key 只可写入或替换，保存后不会回显。</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-5" onSubmit={save}>
            <section className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5"><Label htmlFor="cognee-llm-provider">语言模型提供方</Label><Input id="cognee-llm-provider" autoComplete="off" value={form.llm_provider} onChange={(e) => update('llm_provider', e.target.value)} required /></div>
              <div className="space-y-1.5"><Label htmlFor="cognee-llm-model">语言模型</Label><Input id="cognee-llm-model" autoComplete="off" placeholder="provider/model，如 deepseek/deepseek-v4-flash" value={form.llm_model} onChange={(e) => update('llm_model', e.target.value)} required /></div>
              <div className="space-y-1.5 sm:col-span-2"><Label htmlFor="cognee-llm-endpoint">语言模型接口地址</Label><Input id="cognee-llm-endpoint" autoComplete="url" value={form.llm_endpoint} onChange={(e) => update('llm_endpoint', e.target.value)} /></div>
              <div className="space-y-1.5 sm:col-span-2">
                <Label htmlFor="cognee-llm-key">语言模型 API 密钥（留空以保留现有密钥）</Label>
                <Input
                  id="cognee-llm-key"
                  type="text"
                  autoComplete="off"
                  placeholder={currentConfiguration.llm_api_key_display ?? '未配置；输入新 Key 后由 Zeichen 托管'}
                  value={form.llm_api_key}
                  onChange={(e) => update('llm_api_key', e.target.value)}
                />
              </div>
            </section>
            <section className="grid gap-4 sm:grid-cols-2 border-t pt-5">
              <div className="space-y-1.5"><Label htmlFor="cognee-embedding-provider">向量模型提供方</Label><Input id="cognee-embedding-provider" autoComplete="off" value={form.embedding_provider} onChange={(e) => update('embedding_provider', e.target.value)} required /></div>
              <div className="space-y-1.5"><Label htmlFor="cognee-embedding-model">向量模型</Label><Input id="cognee-embedding-model" autoComplete="off" value={form.embedding_model} onChange={(e) => update('embedding_model', e.target.value)} required /></div>
              <div className="space-y-1.5"><Label htmlFor="cognee-embedding-dimensions">向量维度</Label><Input id="cognee-embedding-dimensions" type="number" min="1" autoComplete="off" value={form.embedding_dimensions} onChange={(e) => update('embedding_dimensions', e.target.value)} /></div>
            </section>
            <div className="flex flex-wrap items-center gap-3">
              <Button type="submit" disabled={saving}>{saving ? '保存中…' : '保存配置'}</Button>
              <span className={currentConfiguration.pending_restart ? 'text-sm text-amber-700 dark:text-amber-400' : 'text-sm text-emerald-700 dark:text-emerald-400'}>
                {configurationStatus}
              </span>
            </div>
          </form>
        </CardContent>
      </Card>
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader><DialogTitle>确认重启 Cognee？</DialogTitle><DialogDescription>重启期间，记忆查询、写入和蒸馏功能不可用。保存的待应用配置将在重启时生效。</DialogDescription></DialogHeader>
          <DialogFooter><Button variant="outline" onClick={() => setConfirmOpen(false)}>取消</Button><Button onClick={() => void restart()}>确认重启</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
