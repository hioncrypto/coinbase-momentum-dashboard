import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { DEMO_VENDORS, DEFAULT_CENTER } from '../data/demoVendors'
import { distanceMeters } from './useGeolocation'
import { approachLabel, walkingMinutes } from '../lib/proximity'
import {
  buildInviteUrl,
  clearInviteFromUrl,
  makeInviteCode,
  readInviteFromUrl,
} from '../lib/invites'
import type {
  AlertSettings,
  CustomerProfile,
  InvitePayload,
  InviteTarget,
  LatLng,
  Role,
  Vendor,
  VendorCategory,
  VendorProfile,
  VendorRequest,
} from '../types'

const FAVORITES_KEY = 'streetpin.favorites'
const PROFILE_KEY = 'streetpin.vendorProfile'
const CUSTOMER_KEY = 'streetpin.customerProfile'
const ROLE_KEY = 'streetpin.role'
const CUSTOM_VENDORS_KEY = 'streetpin.customVendors'
const ALERTS_KEY = 'streetpin.alertSettings'
const REQUESTS_KEY = 'streetpin.requests'
const YOU_ID = 'you-vendor'

const defaultProfile: VendorProfile = {
  name: 'My Cart',
  category: 'ice-cream',
  tagline: 'Rolling through the neighborhood',
  menuHint: 'Ask what’s fresh today',
  aroundHint: 'Evenings on my usual loop',
}

const defaultCustomer: CustomerProfile = {
  displayName: 'Neighbor',
}

const defaultAlerts: AlertSettings = {
  enabled: true,
  radiusMeters: 400,
  browserPush: false,
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
  const [profile, setProfileState] = useState<VendorProfile>(() => {
    const loaded = loadJson<Partial<VendorProfile>>(PROFILE_KEY, {})
    return { ...defaultProfile, ...loaded }
  })
  const [customer, setCustomerState] = useState<CustomerProfile>(() =>
    loadJson<CustomerProfile>(CUSTOMER_KEY, defaultCustomer),
  )
  const [customVendors, setCustomVendors] = useState<Vendor[]>(() =>
    loadJson<Vendor[]>(CUSTOM_VENDORS_KEY, []),
  )
  const [alertSettings, setAlertSettingsState] = useState<AlertSettings>(() =>
    loadJson<AlertSettings>(ALERTS_KEY, defaultAlerts),
  )
  const [requests, setRequestsState] = useState<VendorRequest[]>(() =>
    loadJson<VendorRequest[]>(REQUESTS_KEY, []),
  )
  const [youLive, setYouLive] = useState(false)
  const [youLocation, setYouLocation] = useState<LatLng>(DEFAULT_CENTER)
  const [tick, setTick] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [categoryFilter, setCategoryFilter] = useState<VendorCategory | 'all'>(
    'all',
  )
  const [pendingInvite, setPendingInvite] = useState<InvitePayload | null>(null)
  const [shareInvite, setShareInvite] = useState<{
    url: string
    payload: InvitePayload
  } | null>(null)
  const [userPosition, setUserPosition] = useState<LatLng>(DEFAULT_CENTER)
  const [activeRequestId, setActiveRequestId] = useState<string | null>(null)
  const alertedRef = useRef<Set<string>>(new Set())

  useEffect(() => {
    const fromUrl = readInviteFromUrl()
    if (fromUrl) setPendingInvite(fromUrl)
  }, [])

  useEffect(() => {
    const id = window.setInterval(() => setTick((t) => t + 1), 1200)
    return () => window.clearInterval(id)
  }, [])

  useEffect(() => {
    if (!toast) return
    const id = window.setTimeout(() => setToast(null), 3400)
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

  const setCustomer = useCallback((next: CustomerProfile) => {
    setCustomerState(next)
    localStorage.setItem(CUSTOMER_KEY, JSON.stringify(next))
  }, [])

  const setAlertSettings = useCallback((next: AlertSettings) => {
    setAlertSettingsState(next)
    localStorage.setItem(ALERTS_KEY, JSON.stringify(next))
  }, [])

  const persistCustom = useCallback((list: Vendor[]) => {
    setCustomVendors(list)
    localStorage.setItem(CUSTOM_VENDORS_KEY, JSON.stringify(list))
  }, [])

  const persistRequests = useCallback((list: VendorRequest[]) => {
    setRequestsState(list)
    localStorage.setItem(REQUESTS_KEY, JSON.stringify(list))
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

  const ensureFavorite = useCallback((id: string) => {
    setFavorites((prev) => {
      if (prev.includes(id)) return prev
      const next = [...prev, id]
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
    const customs = customVendors.map((v) => ({
      ...v,
      lastSeen: v.isLive ? Date.now() : v.lastSeen,
    }))
    const base = [...customs, ...demos]

    const you: Vendor = {
      id: YOU_ID,
      name: profile.name || 'My Cart',
      category: profile.category,
      tagline: profile.tagline,
      menuHint: profile.menuHint,
      aroundHint: profile.aroundHint,
      isLive: youLive,
      location: youLocation,
      lastSeen: Date.now(),
      etaHint: youLive ? 'You are live right now' : 'Offline',
      isYou: true,
    }

    if (youLive) return [you, ...base.filter((v) => v.id !== YOU_ID)]
    return base
  }, [tick, youLive, youLocation, profile, customVendors])

  const liveVendors = useMemo(
    () => vendors.filter((v) => v.isLive),
    [vendors],
  )

  const proximity = useMemo(() => {
    return vendors
      .filter((v) => favorites.includes(v.id) && v.isLive && !v.isYou)
      .map((v) => {
        const meters = distanceMeters(userPosition, v.location)
        return {
          vendor: v,
          meters,
          minutes: walkingMinutes(meters),
          label: approachLabel(meters, alertSettings.radiusMeters),
          inRange: meters <= alertSettings.radiusMeters,
        }
      })
      .sort((a, b) => a.meters - b.meters)
  }, [vendors, favorites, userPosition, alertSettings.radiusMeters])

  useEffect(() => {
    if (!alertSettings.enabled || role !== 'customer') return
    for (const row of proximity) {
      const id = row.vendor.id
      if (row.inRange) {
        if (!alertedRef.current.has(id)) {
          alertedRef.current.add(id)
          const msg = `${row.vendor.name} is within range (~${row.minutes} min walk)`
          showToast(msg)
          if (
            alertSettings.browserPush &&
            'Notification' in window &&
            Notification.permission === 'granted'
          ) {
            new Notification('StreetPin — vendor nearby', { body: msg })
          }
        }
      } else if (row.meters > alertSettings.radiusMeters * 1.25) {
        alertedRef.current.delete(id)
      }
    }
  }, [
    proximity,
    alertSettings.enabled,
    alertSettings.radiusMeters,
    alertSettings.browserPush,
    role,
    showToast,
  ])

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

  const createInvite = useCallback(
    (target: InviteTarget) => {
      const fromRole: Role = target === 'vendor' ? 'customer' : 'vendor'
      const fromName =
        fromRole === 'vendor'
          ? profile.name || 'A vendor'
          : customer.displayName || 'A neighbor'

      const payload: InvitePayload = {
        code: makeInviteCode(),
        target,
        fromRole,
        fromName,
        createdAt: Date.now(),
        ...(target === 'customer'
          ? { vendorId: YOU_ID, vendorName: profile.name || 'My Cart' }
          : {}),
      }
      const url = buildInviteUrl(payload)
      setShareInvite({ url, payload })
      return { url, payload }
    },
    [profile.name, customer.displayName],
  )

  const dismissShare = useCallback(() => setShareInvite(null), [])

  const dismissPendingInvite = useCallback(() => {
    setPendingInvite(null)
    clearInviteFromUrl()
  }, [])

  const acceptVendorInvite = useCallback(
    (info: {
      name: string
      category: VendorCategory
      tagline: string
      menuHint: string
      aroundHint: string
    }) => {
      const invite = pendingInvite
      const id = `invited-${Date.now().toString(36)}`
      const vendor: Vendor = {
        id,
        name: info.name,
        category: info.category,
        tagline: info.tagline,
        menuHint: info.menuHint,
        aroundHint: info.aroundHint,
        isLive: true,
        location: {
          lat: userPosition.lat + (Math.random() - 0.5) * 0.004,
          lng: userPosition.lng + (Math.random() - 0.5) * 0.004,
        },
        lastSeen: Date.now(),
        etaHint: 'Just joined from your invite',
        invitedBy: 'customer',
      }

      setProfile({
        name: info.name,
        category: info.category,
        tagline: info.tagline,
        menuHint: info.menuHint,
        aroundHint: info.aroundHint,
      })
      persistCustom([vendor, ...customVendors.filter((v) => v.id !== id)])
      ensureFavorite(id)
      setRole('vendor')
      setYouLive(true)
      setYouLocation(userPosition)
      setSelectedId(id)
      dismissPendingInvite()
      showToast(
        invite
          ? `You’re on StreetPin — ${invite.fromName} can track you`
          : 'You’re on StreetPin',
      )
    },
    [
      pendingInvite,
      userPosition,
      setProfile,
      persistCustom,
      customVendors,
      ensureFavorite,
      setRole,
      dismissPendingInvite,
      showToast,
    ],
  )

  const acceptCustomerInvite = useCallback(
    (info: { displayName: string }) => {
      const invite = pendingInvite
      setCustomer({ displayName: info.displayName || 'Neighbor' })
      setRole('customer')

      if (invite?.vendorId) {
        if (invite.vendorId === YOU_ID && youLive) {
          ensureFavorite(YOU_ID)
        } else {
          const id = invite.vendorId.startsWith('invited-')
            ? invite.vendorId
            : `follow-${invite.code}`
          const existing = customVendors.find((v) => v.id === id)
          if (!existing) {
            const stub: Vendor = {
              id,
              name: invite.vendorName || 'Invited vendor',
              category: 'other',
              tagline: `Shared by ${invite.fromName}`,
              menuHint: 'Ask what’s out today',
              aroundHint: 'Watch the map when they’re live',
              isLive: true,
              location: {
                lat: userPosition.lat + 0.002,
                lng: userPosition.lng - 0.0015,
              },
              lastSeen: Date.now(),
              etaHint: 'Linked from invite',
              invitedBy: 'vendor',
            }
            persistCustom([stub, ...customVendors])
          }
          ensureFavorite(id)
          setSelectedId(id)
        }
      }

      dismissPendingInvite()
      showToast(
        invite
          ? `Tracking ${invite.vendorName || invite.fromName} — alerts when close`
          : 'You’re set — favorites alert when close',
      )
    },
    [
      pendingInvite,
      setCustomer,
      setRole,
      youLive,
      ensureFavorite,
      customVendors,
      persistCustom,
      userPosition,
      dismissPendingInvite,
      showToast,
    ],
  )

  const addVendorByCustomer = useCallback(
    (info: {
      name: string
      category: VendorCategory
      tagline: string
      menuHint: string
      aroundHint: string
    }) => {
      const id = `manual-${Date.now().toString(36)}`
      const vendor: Vendor = {
        id,
        name: info.name,
        category: info.category,
        tagline: info.tagline || 'Neighborhood favorite',
        menuHint: info.menuHint,
        aroundHint: info.aroundHint || 'When they’re rolling',
        isLive: false,
        location: {
          lat: userPosition.lat + 0.001,
          lng: userPosition.lng + 0.001,
        },
        lastSeen: Date.now() - 1000 * 60 * 30,
        etaHint: 'Waiting for them to go live',
        invitedBy: 'customer',
      }
      persistCustom([vendor, ...customVendors])
      ensureFavorite(id)
      setSelectedId(id)
      showToast(`${info.name} saved — send them a StreetPin invite to go live`)
      return id
    },
    [userPosition, persistCustom, customVendors, ensureFavorite, showToast],
  )

  const createRequest = useCallback(
    (info: {
      note: string
      category: VendorCategory | 'any'
      placeHint: string
      radiusMeters: number
      location: LatLng
    }) => {
      const req: VendorRequest = {
        id: `req-${Date.now().toString(36)}`,
        clientName: customer.displayName || 'Neighbor',
        note: info.note || 'Come find me!',
        category: info.category,
        location: info.location,
        placeHint: info.placeHint || 'Near me on the map',
        radiusMeters: info.radiusMeters,
        createdAt: Date.now(),
        status: 'open',
      }
      persistRequests([req, ...requests.filter((r) => r.status !== 'open')])
      setActiveRequestId(req.id)

      const nearby = liveVendors.filter(
        (v) =>
          !v.isYou &&
          distanceMeters(info.location, v.location) <= info.radiusMeters &&
          (info.category === 'any' || v.category === info.category),
      ).length

      showToast(
        nearby > 0
          ? `Request sent — ${nearby} live vendor${nearby === 1 ? '' : 's'} in range`
          : 'Request posted — vendors who come into range can pick it up',
      )
      return req
    },
    [customer.displayName, persistRequests, requests, liveVendors, showToast],
  )

  const cancelRequest = useCallback(
    (id: string) => {
      persistRequests(
        requests.map((r) =>
          r.id === id ? { ...r, status: 'canceled' as const } : r,
        ),
      )
      if (activeRequestId === id) setActiveRequestId(null)
      showToast('Request canceled')
    },
    [persistRequests, requests, activeRequestId, showToast],
  )

  const acceptRequest = useCallback(
    (id: string) => {
      const req = requests.find((r) => r.id === id)
      if (!req || req.status !== 'open') return
      persistRequests(
        requests.map((r) =>
          r.id === id
            ? {
                ...r,
                status: 'accepted' as const,
                acceptedByVendorId: YOU_ID,
                acceptedByVendorName: profile.name || 'My Cart',
              }
            : r,
        ),
      )
      setActiveRequestId(id)
      if (!youLive) {
        setYouLive(true)
        setYouLocation(youLocation)
      }
      showToast(`You’re heading to ${req.clientName} — follow the map pin`)
    },
    [requests, persistRequests, profile.name, youLive, youLocation, showToast],
  )

  const completeRequest = useCallback(
    (id: string) => {
      persistRequests(
        requests.map((r) =>
          r.id === id ? { ...r, status: 'done' as const } : r,
        ),
      )
      if (activeRequestId === id) setActiveRequestId(null)
      showToast('Request completed — nice roll')
    },
    [persistRequests, requests, activeRequestId, showToast],
  )

  /** Requests a live vendor can see (within broadcast radius of their pin). */
  const vendorVisibleRequests = useMemo(() => {
    const origin = youLive ? youLocation : userPosition
    return requests
      .filter((r) => r.status === 'open' || r.acceptedByVendorId === YOU_ID)
      .filter((r) => {
        if (r.status === 'accepted' && r.acceptedByVendorId === YOU_ID)
          return true
        if (r.status !== 'open') return false
        const d = distanceMeters(origin, r.location)
        if (d > r.radiusMeters) return false
        if (r.category === 'any') return true
        return r.category === profile.category
      })
      .map((r) => ({
        request: r,
        meters: distanceMeters(origin, r.location),
        minutes: walkingMinutes(distanceMeters(origin, r.location)),
      }))
      .sort((a, b) => a.meters - b.meters)
  }, [requests, youLive, youLocation, userPosition, profile.category])

  const myOpenRequest = useMemo(
    () =>
      requests.find(
        (r) =>
          r.status === 'open' ||
          (r.status === 'accepted' &&
            r.clientName === (customer.displayName || 'Neighbor')),
      ) ?? null,
    [requests, customer.displayName],
  )

  const activeRequest = useMemo(
    () => requests.find((r) => r.id === activeRequestId) ?? myOpenRequest,
    [requests, activeRequestId, myOpenRequest],
  )

  return {
    role,
    setRole,
    favorites,
    toggleFavorite,
    ensureFavorite,
    profile,
    setProfile,
    customer,
    setCustomer,
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
    alertSettings,
    setAlertSettings,
    proximity,
    pendingInvite,
    shareInvite,
    createInvite,
    dismissShare,
    dismissPendingInvite,
    acceptVendorInvite,
    acceptCustomerInvite,
    addVendorByCustomer,
    setUserPosition,
    requests,
    createRequest,
    cancelRequest,
    acceptRequest,
    completeRequest,
    vendorVisibleRequests,
    myOpenRequest,
    activeRequest,
    setActiveRequestId,
  }
}

export type StreetPinStore = ReturnType<typeof useStreetPinStore>
