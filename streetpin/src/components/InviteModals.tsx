import { useState } from 'react'
import type { InvitePayload, VendorCategory } from '../types'
import { CATEGORY_LABELS } from '../types'
import { inviteHeadline } from '../lib/invites'

interface ShareInviteModalProps {
  url: string
  payload: InvitePayload
  onClose: () => void
  onCopied: () => void
}

export function ShareInviteModal({
  url,
  payload,
  onClose,
  onCopied,
}: ShareInviteModalProps) {
  const forVendor = payload.target === 'vendor'

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <div className="modal-card animate-sheet">
        <p className="street-kicker modal-kicker">
          {forVendor ? 'Invite a vendor' : 'Invite a customer'}
        </p>
        <h3>
          {forVendor
            ? 'Send StreetPin so they can list their cart'
            : 'Send StreetPin so they can track you live'}
        </h3>
        <p className="modal-copy">
          Code <strong>{payload.code}</strong> — they open the link, enter their
          info, and you’re connected.
        </p>
        <div className="invite-link-box">{url}</div>
        <div className="modal-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(url)
                onCopied()
              } catch {
                onCopied()
              }
            }}
          >
            Copy invite link
          </button>
          {'share' in navigator && (
            <button
              type="button"
              className="btn btn-secondary dark"
              onClick={async () => {
                try {
                  await navigator.share({
                    title: 'StreetPin invite',
                    text: forVendor
                      ? 'List your cart on StreetPin so I can find you live.'
                      : 'Track me on StreetPin when I’m rolling.',
                    url,
                  })
                } catch {
                  /* user canceled */
                }
              }}
            >
              Share…
            </button>
          )}
          <button type="button" className="link-btn" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

interface AcceptInviteModalProps {
  invite: InvitePayload
  onDismiss: () => void
  onAcceptVendor: (info: {
    name: string
    category: VendorCategory
    tagline: string
    menuHint: string
    aroundHint: string
  }) => void
  onAcceptCustomer: (info: { displayName: string }) => void
}

const CATEGORIES = Object.keys(CATEGORY_LABELS) as VendorCategory[]

export function AcceptInviteModal({
  invite,
  onDismiss,
  onAcceptVendor,
  onAcceptCustomer,
}: AcceptInviteModalProps) {
  const [name, setName] = useState(
    invite.target === 'vendor' ? '' : invite.fromName ? '' : '',
  )
  const [displayName, setDisplayName] = useState('')
  const [category, setCategory] = useState<VendorCategory>('ice-cream')
  const [tagline, setTagline] = useState('')
  const [menuHint, setMenuHint] = useState('')
  const [aroundHint, setAroundHint] = useState('')

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <div className="modal-card animate-sheet">
        <p className="street-kicker modal-kicker">You’re invited</p>
        <h3>{inviteHeadline(invite.target, invite.fromName)}</h3>
        <p className="modal-copy">
          Enter your info so {invite.fromName} can{' '}
          {invite.target === 'vendor'
            ? 'see when you’re around'
            : 'ping you and follow your pin'}
          .
        </p>

        {invite.target === 'vendor' ? (
          <form
            className="vendor-form"
            onSubmit={(e) => {
              e.preventDefault()
              onAcceptVendor({
                name,
                category,
                tagline: tagline || 'Rolling the neighborhood',
                menuHint,
                aroundHint: aroundHint || 'When I’m live on the map',
              })
            }}
          >
            <label>
              Cart / truck name
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Lotte Man Mike"
                required
              />
            </label>
            <label>
              Type
              <select
                value={category}
                onChange={(e) =>
                  setCategory(e.target.value as VendorCategory)
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
                value={aroundHint}
                onChange={(e) => setAroundHint(e.target.value)}
                placeholder="Saturdays · park loop · after 3pm"
              />
            </label>
            <label>
              Menu hint
              <input
                value={menuHint}
                onChange={(e) => setMenuHint(e.target.value)}
                placeholder="Soft serve, choco pies…"
              />
            </label>
            <label>
              Tagline
              <input
                value={tagline}
                onChange={(e) => setTagline(e.target.value)}
                placeholder="What you’re known for"
              />
            </label>
            <button type="submit" className="btn btn-primary btn-block">
              Join StreetPin & go live
            </button>
          </form>
        ) : (
          <form
            className="vendor-form"
            onSubmit={(e) => {
              e.preventDefault()
              onAcceptCustomer({
                displayName: displayName || 'Neighbor',
              })
            }}
          >
            <label>
              Your name
              <input
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="What vendors should call you"
              />
            </label>
            <p className="modal-copy">
              You’ll favorite{' '}
              <strong>{invite.vendorName || invite.fromName}</strong> and get
              alerts when they’re close.
            </p>
            <button type="submit" className="btn btn-primary btn-block">
              Start tracking
            </button>
          </form>
        )}

        <button type="button" className="link-btn modal-skip" onClick={onDismiss}>
          Not now
        </button>
      </div>
    </div>
  )
}
