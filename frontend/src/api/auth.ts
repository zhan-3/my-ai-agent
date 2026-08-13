import { request } from './client'
import type { AuthResult } from './contract'

export type { AuthResult }

export function login(username: string, password: string): Promise<AuthResult> {
  return request<AuthResult>('/api/auth/login', { method: 'POST', body: { username, password } })
}

export function register(username: string, password: string): Promise<AuthResult> {
  return request<AuthResult>('/api/auth/register', { method: 'POST', body: { username, password } })
}
