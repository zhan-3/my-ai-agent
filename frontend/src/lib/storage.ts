// localStorage 键（与旧单文件 index.html 一致，登录态互通）

export const TOKEN_KEY = 'xw_token'
export const USER_KEY = 'xw_user'

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function getStoredUser(): string | null {
  return localStorage.getItem(USER_KEY)
}
