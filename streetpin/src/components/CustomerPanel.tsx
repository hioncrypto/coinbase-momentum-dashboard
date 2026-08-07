import { useState } from 'react'
import type { LatLng, VendorCategory } from '../types'
import {
  ALERT_PRESETS,
  CATEGORY_LABELS,
  REQUEST_RADIUS_PRESETS,
} from '../types'
import type { Vendor } from '../types'
import { distanceMeters, formatDistance } from '../hooks/useGeolocation'
import { walkingMinutes } from '../lib/proximity'

interface ProximityRow {
  vendor: Vendor
  meters: number
  minutes: number
  label: string | null
  inRange: boolean
}

interface CustomerPanelProps {
  vendors: Vendor[]
  favorites: string[]
  selectedId: string | null
  userPosition: LatLng
  categoryFilter: VendorCategory | 'all'
  customerName: string
  alertEnabled: boolean
  alertRadius: number
  proximity: ProximityRow[]
  myOpenRequest: {
    id: string
    note: string
    placeHint: string
    status: string
    acceptedByVendorName?: string
    radiusMeters: number
  } | null
  onFilter: (c: VendorCategory | 'all') => void
  onSelect: (id: string) => void
  onToggleFavorite: (id: string) => void
  onSwitchRole: () => void
  onInviteVendor: () => void
  onAlertChange: (enabled: boolean, radiusMeters: number) => void
  onEnablePush: () => void
  onCreateRequest: (info: {
    note: string
    category: VendorCategory | 'any'
    placeHint: string
    radiusMeters: number
    location: LatLng
  }) => void
  onCancelRequest: (id: string) => void
  onCustomerName: (name: string) => void
}

const FILTERS: Array<VendorCategory | 'all'> = [
  'all',
  'ice-cream',
  'lotte',
  'food-truck',
  'coffee',
  'snacks',
]

export function CustomerPanel({
  vendors,
  favorites,
  selectedId,
  userPosition,
  categoryFilter,
  customerName,
  alertEnabled,
  alertRadius,
  proximity,
  myOpenRequest,
  onFilter,
  onSelect,
  onToggleFavorite,
  onSwitchRole,
  onInviteVendor,
  onAlertChange,
  onEnablePush,
  onCreateRequest,
  onCancelRequest,
  onCustomerName,
}: CustomerPanelProps) {
  const [showRequest, setShowRequest] = useState(false)
  const [showAlerts, setShowAlerts] = useState(false)
  const [note, setNote] = useState('Ice cream at the park, please!')
  const [placeHint, setPlaceHint] = useState('Near the picnic tables')
  const [reqCategory, setReqCategory] = useState<VendorCategory | 'any'>('any')
  const [reqRadius, setReqRadius] = useState(400)

  const filtered = vendors
    .filter((v) => categoryFilter === 'all' || v.category === categoryFilter)
    .sort((a, b) => {
      if (a.isLive !== b.isLive) return a.isLive ? -1 : 1
      return (
        distanceMeters(userPosition, a.location) -
        distanceMeters(userPosition, b.location)
      )
    })

  const selected = vendors.find((v) => v.id === selectedId) ?? filtered[0]
  const approaching = proximity.filter((p) => p.label)

  return (
    <aside className="panel customer-panel">
      <header className="panel-header">
        <div>
          <p className="brand-mark sm">
            Street<span>Pin</span>
          </p>
          <h2>On the block</h2>
        </div>
        <button type="button" className="link-btn" onClick={onSwitchRole}>
          Vendor mode
        </button>
      </header>

      <div className="action-row">
        <button
          type="button"
          className="btn btn-primary compact"
          onClick={() => setShowRequest((s) => !s)}
        >
          Request a vendor
        </button>
        <button
          type="button"
          className="btn btn-secondary dark compact"
          onClick={onInviteVendor}
        >
          Invite vendor
        </button>
        <button
          type="button"
          className="btn btn-ghost compact"
          onClick={() => setShowAlerts((s) => !s)}
        >
          Alerts
        </button>
      </div>

      {showRequest && (
        <div className="inline-card animate-sheet">
          <h4>Request someone nearby</h4>
          <p className="card-help">
            At the park and craving something? Ping live vendors within your
            radius — they see your pin and can roll to you.
          </p>
          <form
            className="vendor-form"
            onSubmit={(e) => {
              e.preventDefault()
              onCreateRequest({
                note,
                category: reqCategory,
                placeHint,
                radiusMeters: reqRadius,
                location: userPosition,
              })
              setShowRequest(false)
            }}
          >
            <label>
              Your name
              <input
                value={customerName}
                onChange={(e) => onCustomerName(e.target.value)}
                placeholder="Neighbor"
              />
            </label>
            <label>
              What do you want?
              <input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Soft serve for 2…"
                required
              />
            </label>
            <label>
              Where are you?
              <input
                value={placeHint}
                onChange={(e) => setPlaceHint(e.target.value)}
                placeholder="North lawn · by the fountain"
              />
            </label>
            <label>
              Vendor type
              <select
                value={reqCategory}
                onChange={(e) =>
                  setReqCategory(e.target.value as VendorCategory | 'any')
                }
              >
                <option value="any">Anyone nearby</option>
                {FILTERS.filter((f) => f !== 'all').map((c) => (
                  <option key={c} value={c}>
                    {CATEGORY_LABELS[c as VendorCategory]}
                  </option>
                ))}
              </select>
            </label>
            <fieldset className="preset-fieldset">
              <legend>Broadcast distance</legend>
              <div className="filter-row wrap">
                {REQUEST_RADIUS_PRESETS.map((p) => (
                  <button
                    key={p.meters}
                    type="button"
                    className={`chip ${reqRadius === p.meters ? 'active' : ''}`}
                    onClick={() => setReqRadius(p.meters)}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
            </fieldset>
            <button type="submit" className="btn btn-primary btn-block">
              Send request
            </button>
          </form>
        </div>
      )}

      {myOpenRequest && (
        <div className={`inline-card request-status ${myOpenRequest.status}`}>
          <strong>
            {myOpenRequest.status === 'accepted'
              ? `${myOpenRequest.acceptedByVendorName || 'A vendor'} is coming`
              : 'Request is live'}
          </strong>
          <p>
            {myOpenRequest.note}
            {myOpenRequest.placeHint ? ` · ${myOpenRequest.placeHint}` : ''}
          </p>
          {myOpenRequest.status === 'open' && (
            <button
              type="button"
              className="link-btn"
              onClick={() => onCancelRequest(myOpenRequest.id)}
            >
              Cancel request
            </button>
          )}
        </div>
      )}

      {showAlerts && (
        <div className="inline-card animate-sheet">
          <h4>Closer alerts</h4>
          <p className="card-help">
            Get pinged when a favorited vendor enters your chosen distance.
          </p>
          <label className="check-row">
            <input
              type="checkbox"
              checked={alertEnabled}
              onChange={(e) => onAlertChange(e.target.checked, alertRadius)}
            />
            Alerts on for favorites
          </label>
          <div className="filter-row wrap">
            {ALERT_PRESETS.map((p) => (
              <button
                key={p.meters}
                type="button"
                className={`chip ${alertRadius === p.meters ? 'active' : ''}`}
                onClick={() => onAlertChange(alertEnabled, p.meters)}
              >
                {p.label}
              </button>
            ))}
          </div>
          <button type="button" className="link-btn" onClick={onEnablePush}>
            Allow phone notifications
          </button>
        </div>
      )}

      {approaching.length > 0 && (
        <div className="approach-strip">
          {approaching.slice(0, 2).map((p) => (
            <button
              key={p.vendor.id}
              type="button"
              className={`approach-pill ${p.inRange ? 'hot' : ''}`}
              onClick={() => onSelect(p.vendor.id)}
            >
              <strong>{p.vendor.name}</strong>
              <span>
                {p.label} · {formatDistance(p.meters)} · ~{p.minutes} min
              </span>
            </button>
          ))}
        </div>
      )}

      <div className="filter-row" role="tablist" aria-label="Vendor type">
        {FILTERS.map((f) => (
          <button
            key={f}
            type="button"
            role="tab"
            aria-selected={categoryFilter === f}
            className={`chip ${categoryFilter === f ? 'active' : ''}`}
            onClick={() => onFilter(f)}
          >
            {f === 'all' ? 'All' : CATEGORY_LABELS[f]}
          </button>
        ))}
      </div>

      <ul className="vendor-list">
        {filtered.map((v) => {
          const dist = formatDistance(
            distanceMeters(userPosition, v.location),
          )
          const fav = favorites.includes(v.id)
          const prox = proximity.find((p) => p.vendor.id === v.id)
          return (
            <li key={v.id}>
              <button
                type="button"
                className={`vendor-row ${selectedId === v.id ? 'selected' : ''}`}
                onClick={() => onSelect(v.id)}
              >
                <span className={`live-dot ${v.isLive ? 'on' : 'off'}`} />
                <span className="vendor-row-text">
                  <span className="vendor-name">{v.name}</span>
                  <span className="vendor-meta">
                    {CATEGORY_LABELS[v.category]} · {dist}
                    {v.isLive ? ' · Live' : ' · Offline'}
                    {fav ? ' · Fav' : ''}
                    {prox?.label ? ` · ${prox.label}` : ''}
                  </span>
                </span>
              </button>
            </li>
          )
        })}
      </ul>

      {selected && (
        <div className="detail-sheet animate-sheet">
          <div className="detail-top">
            <div>
              <p className={`status-pill ${selected.isLive ? 'live' : ''}`}>
                {selected.isLive ? 'Live now' : 'Offline'}
              </p>
              <h3>{selected.name}</h3>
              <p className="detail-tagline">{selected.tagline}</p>
            </div>
            <button
              type="button"
              className={`btn btn-fav ${favorites.includes(selected.id) ? 'on' : ''}`}
              onClick={() => onToggleFavorite(selected.id)}
              aria-pressed={favorites.includes(selected.id)}
            >
              {favorites.includes(selected.id) ? 'Favorited' : 'Favorite'}
            </button>
          </div>
          <p className="detail-line">
            <strong>Type:</strong> {CATEGORY_LABELS[selected.category]}
          </p>
          {selected.aroundHint && (
            <p className="detail-line">
              <strong>Usually around:</strong> {selected.aroundHint}
            </p>
          )}
          {selected.menuHint && (
            <p className="detail-line">
              <strong>Menu:</strong> {selected.menuHint}
            </p>
          )}
          <p className="detail-line">
            <strong>Distance:</strong>{' '}
            {formatDistance(distanceMeters(userPosition, selected.location))}
            {' · ~'}
            {walkingMinutes(distanceMeters(userPosition, selected.location))}{' '}
            min walk
          </p>
        </div>
      )}
    </aside>
  )
}
