export type Role = 'customer' | 'vendor'

export type VendorCategory =
  | 'ice-cream'
  | 'lotte'
  | 'food-truck'
  | 'coffee'
  | 'snacks'
  | 'other'

export interface LatLng {
  lat: number
  lng: number
}

export interface Vendor {
  id: string
  name: string
  category: VendorCategory
  tagline: string
  isLive: boolean
  location: LatLng
  lastSeen: number
  etaHint?: string
  menuHint?: string
  isDemo?: boolean
  isYou?: boolean
}

export interface VendorProfile {
  name: string
  category: VendorCategory
  tagline: string
  menuHint: string
}

export const CATEGORY_LABELS: Record<VendorCategory, string> = {
  'ice-cream': 'Ice Cream',
  lotte: 'Lotte / Treats',
  'food-truck': 'Food Truck',
  coffee: 'Coffee Cart',
  snacks: 'Snacks',
  other: 'Other',
}
