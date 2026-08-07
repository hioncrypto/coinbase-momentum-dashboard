import type { Vendor } from '../types'

/** Default map center: Echo Park / central LA — good demo neighborhood feel */
export const DEFAULT_CENTER = { lat: 34.0776, lng: -118.2606 }

export const DEMO_VENDORS: Vendor[] = [
  {
    id: 'demo-lotte',
    name: 'Lotte Man Mike',
    category: 'lotte',
    tagline: 'Choco pies, soft serve & summer snacks',
    isLive: true,
    location: { lat: 34.0812, lng: -118.255 },
    lastSeen: Date.now(),
    etaHint: 'Rolling Echo Park loop',
    menuHint: 'Lotte pie · soft serve · drinks',
    isDemo: true,
  },
  {
    id: 'demo-cream',
    name: 'Sunny Scoop Truck',
    category: 'ice-cream',
    tagline: 'Classic soft serve & novelty bars',
    isLive: true,
    location: { lat: 34.0738, lng: -118.268 },
    lastSeen: Date.now(),
    etaHint: 'Near the park edge',
    menuHint: 'Vanilla · chocolate · swirl',
    isDemo: true,
  },
  {
    id: 'demo-taco',
    name: 'Calle Taco',
    category: 'food-truck',
    tagline: 'Street tacos until we sell out',
    isLive: true,
    location: { lat: 34.0705, lng: -118.2525 },
    lastSeen: Date.now(),
    etaHint: 'Stopped for the lunch rush',
    menuHint: 'Asada · al pastor · agua fresca',
    isDemo: true,
  },
  {
    id: 'demo-coffee',
    name: 'Corner Steam',
    category: 'coffee',
    tagline: 'Espresso cart on wheels',
    isLive: false,
    location: { lat: 34.085, lng: -118.262 },
    lastSeen: Date.now() - 1000 * 60 * 45,
    etaHint: 'Usually mornings',
    menuHint: 'Latte · cold brew · pastry',
    isDemo: true,
  },
]
