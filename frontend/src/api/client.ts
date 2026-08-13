// API 客户端：统一 fetch 封装（JSON 头、Bearer、错误归一化）
// 401 → ApiError(401)；网络失败 → Error（友好文案）；其余非 2xx → ApiError(status, detail)

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, detail?: string) {
    super(detail || `请求失败（${status}）`)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function request<T>(
  path: string,
  opts: { method?: string; body?: unknown; token?: string | null } = {},
): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (opts.token) headers['Authorization'] = `Bearer ${opts.token}`
  let res: Response
  try {
    res = await fetch(path, {
      method: opts.method ?? 'GET',
      headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    })
  } catch {
    throw new Error('网络错误，请确认服务已启动')
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new ApiError(res.status, body?.detail)
  }
  return res.json() as Promise<T>
}
