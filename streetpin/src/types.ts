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
  aroundHint?: string
  isDemo?: boolean
  isYou?: boolean
  invitedBy?: Role
}

export interface VendorProfile {
  name: string
  category: VendorCategory
  tagline: string
  menuHint: string
  aroundHint: string
}

export interface CustomerProfile {
  displayName: string
}

/** Who the invite is meant to onboard */
export type InviteTarget = 'vendor' | 'customer'

export interface InvitePayload {
  code: string
  target: InviteTarget
  fromRole: Role
  fromName: string
  vendorId?: string
  vendorName?: string
  createdAt: number
}

export interface AlertSettings {
  enabled: boolean
  radiusMeters: number
  browserPush: boolean
}

export type RequestStatus = 'open' | 'accepted' | 'done' | 'canceled'

/** Client ping: “come find me at the park” */
export interface VendorRequest {
  id: string
  clientName: string
  note: string
  category: VendorCategory | 'any'
  location: LatLng
  placeHint: string
  /** How far out to broadcast the request */
  radiusMeters: number
  createdAt: number
  status: RequestStatus
  acceptedByVendorId?: string
  acceptedByVendorName?: string
}

export const ALERT_PRESETS: { label: string; meters: number; hint: string }[] = [
  { label: '1 block', meters: 80, hint: '~1 min walk' },
  { label: '2 blocks', meters: 160, hint: '~2 min walk' },
  { label: '¼ mile', meters: 400, hint: '~5 min walk' },
  { label: '½ mile', meters: 800, hint: '~10 min walk' },
  { label: '1 mile', meters: 1600, hint: 'wider net' },
]

export const REQUEST_RADIUS_PRESETS = ALERT_PRESETS

export const CATEGORY_LABELS: Record<VendorCategory, string> = {
  'ice-cream': 'Ice Cream',
  lotte: 'Lotte / Treats',
  'food-truck': 'Food Truck',
  coffee: 'Coffee Cart',
  snacks: 'Snacks',
  other: 'Other',
}

export const APP_NAME = 'StreetPin'
export const APP_TAGLINE = 'Live pins for the block'
