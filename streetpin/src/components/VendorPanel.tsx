import type { VendorCategory, VendorProfile } from '../types'
import { CATEGORY_LABELS } from '../types'

interface VendorPanelProps {
  profile: VendorProfile
  isLive: boolean
  liveCount: number
  onProfileChange: (p: VendorProfile) => void
  onGoLive: () => void
  onEndShift: () => void
  onSwitchRole: () => void
  locationNote: string
}

const CATEGORIES = Object.keys(CATEGORY_LABELS) as VendorCategory[]

export function VendorPanel({
  profile,
  isLive,
  liveCount,
  onProfileChange,
  onGoLive,
  onEndShift,
  onSwitchRole,
  locationNote,
}: VendorPanelProps) {
  return (
    <aside className="panel vendor-panel">
      <header className="panel-header">
        <div>
          <p className="brand-mark sm">
            Street<span>Pin</span>
          </p>
          <h2>Vendor booth</h2>
        </div>
        <button type="button" className="link-btn" onClick={onSwitchRole}>
          Customer mode
        </button>
      </header>

      <div className={`live-banner ${isLive ? 'on' : ''}`}>
        <span className={`live-dot ${isLive ? 'on' : 'off'}`} />
        <div>
          <strong>{isLive ? 'You are live on the map' : 'You are offline'}</strong>
          <p>
            {isLive
              ? `Customers nearby can see your pin · ${liveCount} live vendor${liveCount === 1 ? '' : 's'} total`
              : 'Go live when you start your route'}
          </p>
        </div>
      </div>

      <form
        className="vendor-form"
        onSubmit={(e) => {
          e.preventDefault()
          if (isLive) onEndShift()
          else onGoLive()
        }}
      >
        <label>
          Cart / truck name
          <input
            value={profile.name}
            onChange={(e) =>
              onProfileChange({ ...profile, name: e.target.value })
            }
            placeholder="e.g. Lotte Man Mike"
            required
          />
        </label>

        <label>
          Type
          <select
            value={profile.category}
            onChange={(e) =>
              onProfileChange({
                ...profile,
                category: e.target.value as VendorCategory,
              })
            }
          >
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {CATEGORY_LABELS[c]}
              </option>
            ))}
          </select>
        </label>

        <label>
          Short tagline
          <input
            value={profile.tagline}
            onChange={(e) =>
              onProfileChange({ ...profile, tagline: e.target.value })
            }
            placeholder="What you’re known for"
          />
        </label>

        <label>
          Menu hint
          <input
            value={profile.menuHint}
            onChange={(e) =>
              onProfileChange({ ...profile, menuHint: e.target.value })
            }
            placeholder="Soft serve, choco pies…"
          />
        </label>

        <p className="location-note">{locationNote}</p>

        <button
          type="submit"
          className={`btn ${isLive ? 'btn-danger' : 'btn-primary'} btn-block`}
        >
          {isLive ? 'End shift' : 'Go live'}
        </button>
      </form>

      <p className="vendor-help">
        Tip: keep this tab open while you roll. Your pin updates as your phone
        location updates. Customers favorite you and get a clear Live status.
      </p>
    </aside>
  )
}
