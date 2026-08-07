import { useCallback, useEffect, useMemo, useState } from 'react'
import { DEMO_VENDORS, DEFAULT_CENTER } from '../data/demoVendors'
import type { LatLng, Role, Vendor, VendorCategory, VendorProfile } from '../types'

const FAVORITES_KEY = 'streetpin.favorites'
const PROFILE_KEY = 'streetpin.vendorProfile'
const ROLE_KEY = 'streetpin.role'
const YOU_ID = 'you-vendor'

const defaultProfile: VendorProfile = {
  name: 'My Cart',
  category: 'ice-cream',
  tagline: 'Rolling through the neighborhood',
  menuHint: 'Ask what’s fresh today',
}

function loadJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return fallback
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

function nudge(vendor: Vendor, t: number): LatLng {
  if (!vendor.isLive || !vendor.isDemo) return vendor.location
  const seed = vendor.id.split('').reduce((a, c) => a + c.charCodeAt(0), 0)
  const radius = 0.0018
  return {
    lat: vendor.location.lat + Math.sin(t / 18 + seed) * radius,
    lng: vendor.location.lng + Math.cos(t / 22 + seed * 0.7) * radius * 1.2,
  }
}

export function useStreetPinStore() {
  const [role, setRoleState] = useState<Role | null>(() =>
    loadJson<Role | null>(ROLE_KEY, null),
  )
  const [favorites, setFavorites] = useState<string[]>(() =>
    loadJson<string[]>(FAVORITES_KEY, ['demo-lotte']),
  )
  const [profile, setProfileState] = useState<VendorProfile>(() =>
    loadJson<VendorProfile>(PROFILE_KEY, defaultProfile),
  )
  const [youLive, setYouLive] = useState(false)
  const [youLocation, setYouLocation] = useState<LatLng>(DEFAULT_CENTER)
  const [tick, setTick] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [categoryFilter, setCategoryFilter] = useState<VendorCategory | 'all'>(
    'all',
  )

  useEffect(() => {
    const id = window.setInterval(() => setTick((t) => t + 1), 1200)
    return () => window.clearInterval(id)
  }, [])

  useEffect(() => {
    if (!toast) return
    const id = window.setTimeout(() => setToast(null), 2800)
    return () => window.clearTimeout(id)
  }, [toast])

  const setRole = useCallback((next: Role | null) => {
    setRoleState(next)
    if (next) localStorage.setItem(ROLE_KEY, JSON.stringify(next))
    else localStorage.removeItem(ROLE_KEY)
  }, [])

  const setProfile = useCallback((next: VendorProfile) => {
    setProfileState(next)
    localStorage.setItem(PROFILE_KEY, JSON.stringify(next))
  }, [])

  const toggleFavorite = useCallback((id: string) => {
    setFavorites((prev) => {
      const next = prev.includes(id)
        ? prev.filter((x) => x !== id)
        : [...prev, id]
      localStorage.setItem(FAVORITES_KEY, JSON.stringify(next))
      return next
    })
  }, [])

  const showToast = useCallback((message: string) => setToast(message), [])

  const vendors: Vendor[] = useMemo(() => {
    const demos = DEMO_VENDORS.map((v) => ({
      ...v,
      location: nudge(v, tick),
      lastSeen: v.isLive ? Date.now() : v.lastSeen,
    }))

    if (!youLive && role !== 'vendor') return demos

    const you: Vendor = {
      id: YOU_ID,
      name: profile.name || 'My Cart',
      category: profile.category,
      tagline: profile.tagline,
      menuHint: profile.menuHint,
      isLive: youLive,
      location: youLocation,
      lastSeen: Date.now(),
      etaHint: youLive ? 'You are live right now' : 'Offline',
      isYou: true,
    }

    return youLive ? [you, ...demos] : demos
  }, [tick, youLive, youLocation, profile, role])

  const liveVendors = useMemo(
    () => vendors.filter((v) => v.isLive),
    [vendors],
  )

  const goLive = useCallback(
    (location: LatLng) => {
      setYouLocation(location)
      setYouLive(true)
      showToast('You’re live — customers can find you')
    },
    [showToast],
  )

  const endShift = useCallback(() => {
    setYouLive(false)
    showToast('Shift ended — you’re off the map')
  }, [showToast])

  const updateYouLocation = useCallback((location: LatLng) => {
    setYouLocation(location)
  }, [])

  return {
    role,
    setRole,
    favorites,
    toggleFavorite,
    profile,
    setProfile,
    youLive,
    youLocation,
    goLive,
    endShift,
    updateYouLocation,
    vendors,
    liveVendors,
    selectedId,
    setSelectedId,
    toast,
    showToast,
    categoryFilter,
    setCategoryFilter,
    YOU_ID,
  }
}

export type StreetPinStore = ReturnType<typeof useStreetPinStore>
