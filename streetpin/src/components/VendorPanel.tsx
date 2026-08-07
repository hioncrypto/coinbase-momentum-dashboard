import type { VendorCategory, VendorProfile, VendorRequest } from '../types'
import { CATEGORY_LABELS } from '../types'
import { formatDistance } from '../hooks/useGeolocation'

interface RequestRow {
  request: VendorRequest
  meters: number
  minutes: number
}

interface VendorPanelProps {
  profile: VendorProfile
  isLive: boolean
  liveCount: number
  locationNote: string
  visibleRequests: RequestRow[]
  onProfileChange: (p: VendorProfile) => void
  onGoLive: () => void
  onEndShift: () => void
  onSwitchRole: () => void
  onInviteCustomer: () => void
  onAcceptRequest: (id: string) => void
  onCompleteRequest: (id: string) => void
  onFocusRequest: (id: string) => void
}

const CATEGORIES = Object.keys(CATEGORY_LABELS) as VendorCategory[]

export function VendorPanel({
  profile,
  isLive,
  liveCount,
  locationNote,
  visibleRequests,
  onProfileChange,
  onGoLive,
  onEndShift,
  onSwitchRole,
  onInviteCustomer,
  onAcceptRequest,
  onCompleteRequest,
  onFocusRequest,
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

      <div className="action-row">
        <button
          type="button"
          className="btn btn-secondary dark compact"
          onClick={onInviteCustomer}
        >
          Invite customers
        </button>
      </div>

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

      {visibleRequests.length > 0 && (
        <div className="inline-card request-inbox">
          <h4>Client requests</h4>
          <p className="card-help">
            Someone nearby wants you — accept and follow their pin on the map.
          </p>
          <ul className="request-list">
            {visibleRequests.map(({ request: r, meters, minutes }) => (
              <li key={r.id} className={`request-item ${r.status}`}>
                <div>
                  <strong>{r.clientName}</strong>
                  <span>
                    {r.note}
                    {r.placeHint ? ` · ${r.placeHint}` : ''}
                  </span>
                  <em>
                    {formatDistance(meters)} · ~{minutes} min
                    {r.status === 'accepted' ? ' · heading there' : ''}
                  </em>
                </div>
                <div className="request-actions">
                  <button
                    type="button"
                    className="btn btn-ghost compact"
                    onClick={() => onFocusRequest(r.id)}
                  >
                    Map
                  </button>
                  {r.status === 'open' && (
                    <button
                      type="button"
                      className="btn btn-primary compact"
                      onClick={() => onAcceptRequest(r.id)}
                    >
                      Accept
                    </button>
                  )}
                  {r.status === 'accepted' && (
                    <button
                      type="button"
                      className="btn btn-secondary dark compact"
                      onClick={() => onCompleteRequest(r.id)}
                    >
                      Done
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

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
          When you’re usually around
          <input
            value={profile.aroundHint}
            onChange={(e) =>
              onProfileChange({ ...profile, aroundHint: e.target.value })
            }
            placeholder="Saturdays · park loop · after 3pm"
          />
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
        Tip: stay live while you roll. Customers can favorite you, get closer
        alerts, and send “come find me” requests from the park.
      </p>
    </aside>
  )
}
