import type { InvitePayload, InviteTarget, Role } from '../types'

const alphabet = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'

export function makeInviteCode(): string {
  let out = ''
  for (let i = 0; i < 6; i++) {
    out += alphabet[Math.floor(Math.random() * alphabet.length)]
  }
  return out
}

export function encodeInvite(payload: InvitePayload): string {
  const json = JSON.stringify(payload)
  return btoa(unescape(encodeURIComponent(json)))
}

export function decodeInvite(raw: string): InvitePayload | null {
  try {
    const json = decodeURIComponent(escape(atob(raw)))
    const data = JSON.parse(json) as InvitePayload
    if (!data?.code || !data?.target || !data?.fromRole) return null
    return data
  } catch {
    return null
  }
}

export function buildInviteUrl(payload: InvitePayload): string {
  const token = encodeInvite(payload)
  const url = new URL(window.location.href)
  url.searchParams.set('invite', token)
  return url.toString()
}

export function readInviteFromUrl(): InvitePayload | null {
  const params = new URLSearchParams(window.location.search)
  const token = params.get('invite')
  if (!token) return null
  return decodeInvite(token)
}

export function clearInviteFromUrl() {
  const url = new URL(window.location.href)
  if (!url.searchParams.has('invite')) return
  url.searchParams.delete('invite')
  window.history.replaceState({}, '', url.pathname + url.search + url.hash)
}

export function inviteHeadline(target: InviteTarget, fromName: string): string {
  if (target === 'vendor') {
    return `${fromName || 'A neighbor'} invited you to list your cart on StreetPin`
  }
  return `${fromName || 'A vendor'} invited you to track them on StreetPin`
}

export function defaultFromName(role: Role, vendorName: string, customerName: string) {
  if (role === 'vendor') return vendorName || 'A vendor'
  return customerName || 'A neighbor'
}
