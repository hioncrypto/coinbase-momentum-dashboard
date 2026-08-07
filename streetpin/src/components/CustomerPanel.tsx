import type { Vendor, VendorCategory } from '../types'
import { CATEGORY_LABELS } from '../types'
import { distanceMeters, formatDistance } from '../hooks/useGeolocation'
import type { LatLng } from '../types'

interface CustomerPanelProps {
  vendors: Vendor[]
  favorites: string[]
  selectedId: string | null
  userPosition: LatLng
  categoryFilter: VendorCategory | 'all'
  onFilter: (c: VendorCategory | 'all') => void
  onSelect: (id: string) => void
  onToggleFavorite: (id: string) => void
  onSwitchRole: () => void
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
  onFilter,
  onSelect,
  onToggleFavorite,
  onSwitchRole,
}: CustomerPanelProps) {
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
          {selected.menuHint && (
            <p className="detail-line">
              <strong>Menu:</strong> {selected.menuHint}
            </p>
          )}
          {selected.etaHint && (
            <p className="detail-line">
              <strong>Route:</strong> {selected.etaHint}
            </p>
          )}
          <p className="detail-line">
            <strong>Distance:</strong>{' '}
            {formatDistance(distanceMeters(userPosition, selected.location))}
          </p>
        </div>
      )}
    </aside>
  )
}
