import { useCallback, useEffect, useState } from 'react'
import type { LatLng } from '../types'
import { DEFAULT_CENTER } from '../data/demoVendors'

interface GeoState {
  position: LatLng
  accuracy: number | null
  error: string | null
  loading: boolean
  usingFallback: boolean
}

export function useGeolocation(enabled = true) {
  const [state, setState] = useState<GeoState>({
    position: DEFAULT_CENTER,
    accuracy: null,
    error: null,
    loading: true,
    usingFallback: true,
  })

  const refresh = useCallback(() => {
    if (!enabled || !navigator.geolocation) {
      setState((s) => ({
        ...s,
        loading: false,
        error: 'Location unavailable — showing demo area',
        usingFallback: true,
        position: DEFAULT_CENTER,
      }))
      return
    }

    setState((s) => ({ ...s, loading: true }))
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setState({
          position: { lat: pos.coords.latitude, lng: pos.coords.longitude },
          accuracy: pos.coords.accuracy,
          error: null,
          loading: false,
          usingFallback: false,
        })
      },
      () => {
        setState({
          position: DEFAULT_CENTER,
          accuracy: null,
          error: 'Using demo map area (location denied)',
          loading: false,
          usingFallback: true,
        })
      },
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 15000 },
    )
  }, [enabled])

  useEffect(() => {
    refresh()
  }, [refresh])

  return { ...state, refresh }
}

export function distanceMeters(a: LatLng, b: LatLng): number {
  const R = 6371000
  const toRad = (d: number) => (d * Math.PI) / 180
  const dLat = toRad(b.lat - a.lat)
  const dLng = toRad(b.lng - a.lng)
  const lat1 = toRad(a.lat)
  const lat2 = toRad(b.lat)
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(h))
}

export function formatDistance(meters: number): string {
  if (meters < 1000) return `${Math.round(meters)} m`
  return `${(meters / 1000).toFixed(1)} km`
}
