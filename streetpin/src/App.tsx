import { useEffect, useMemo, useState } from 'react'
import { Welcome } from './components/Welcome'
import { MapView } from './components/MapView'
import { CustomerPanel } from './components/CustomerPanel'
import { VendorPanel } from './components/VendorPanel'
import {
  AcceptInviteModal,
  ShareInviteModal,
} from './components/InviteModals'
import { useGeolocation } from './hooks/useGeolocation'
import { useStreetPinStore } from './hooks/useStreetPinStore'
import { DEFAULT_CENTER } from './data/demoVendors'

export default function App() {
  const store = useStreetPinStore()
  const geo = useGeolocation(true)
  const [mapFocus, setMapFocus] = useState(DEFAULT_CENTER)

  useEffect(() => {
    store.setUserPosition(geo.position)
  }, [geo.position.lat, geo.position.lng])

  useEffect(() => {
    if (store.youLive && !geo.usingFallback) {
      store.updateYouLocation(geo.position)
    }
  }, [geo.position.lat, geo.position.lng, geo.usingFallback, store.youLive])

  useEffect(() => {
    if (store.role === 'vendor' && store.activeRequest) {
      setMapFocus(store.activeRequest.location)
      return
    }
    if (store.role === 'vendor' && store.youLive) {
      setMapFocus(store.youLocation)
      return
    }
    const selected = store.vendors.find((v) => v.id === store.selectedId)
    if (selected) {
      setMapFocus(selected.location)
      return
    }
    setMapFocus(geo.position)
  }, [
    store.selectedId,
    store.role,
    store.youLive,
    store.youLocation,
    store.activeRequest,
    geo.position,
    store.vendors,
  ])

  const visibleVendors = useMemo(() => {
    if (store.categoryFilter === 'all') return store.vendors
    return store.vendors.filter((v) => v.category === store.categoryFilter)
  }, [store.vendors, store.categoryFilter])

  if (!store.role) {
    return (
      <>
        <Welcome onChoose={(next) => store.setRole(next)} />
        {store.pendingInvite && (
          <AcceptInviteModal
            invite={store.pendingInvite}
            onDismiss={store.dismissPendingInvite}
            onAcceptVendor={store.acceptVendorInvite}
            onAcceptCustomer={store.acceptCustomerInvite}
          />
        )}
        {store.toast && (
          <div className="toast animate-rise" role="status">
            {store.toast}
          </div>
        )}
      </>
    )
  }

  const locationNote = geo.usingFallback
    ? 'Demo location active (browser location denied or unavailable). Your pin uses the sample map area.'
    : `Sharing your GPS · accuracy ~${Math.round(geo.accuracy ?? 0)} m`

  const requestPins =
    store.role === 'vendor'
      ? store.vendorVisibleRequests.map((r) => ({
          id: r.request.id,
          location: r.request.location,
          label: r.request.clientName,
          active: store.activeRequest?.id === r.request.id,
        }))
      : store.myOpenRequest
        ? [
            {
              id: store.myOpenRequest.id,
              location: store.myOpenRequest.location,
              label: 'Your request',
              active: true,
            },
          ]
        : []

  return (
    <div className="app-shell">
      <div className="map-stage">
        <MapView
          center={mapFocus}
          userPosition={
            store.role === 'vendor' && store.youLive
              ? store.youLocation
              : geo.position
          }
          vendors={visibleVendors}
          selectedId={store.selectedId}
          onSelect={store.setSelectedId}
          requestPins={requestPins}
        />
        <div className="map-chrome">
          <button
            type="button"
            className="btn btn-ghost map-locate"
            onClick={() => {
              geo.refresh()
              setMapFocus(geo.position)
            }}
          >
            Recenter
          </button>
          {geo.error && <span className="geo-pill">{geo.error}</span>}
        </div>
      </div>

      {store.role === 'customer' ? (
        <CustomerPanel
          vendors={store.vendors}
          favorites={store.favorites}
          selectedId={store.selectedId}
          userPosition={geo.position}
          categoryFilter={store.categoryFilter}
          customerName={store.customer.displayName}
          alertEnabled={store.alertSettings.enabled}
          alertRadius={store.alertSettings.radiusMeters}
          proximity={store.proximity}
          myOpenRequest={store.myOpenRequest}
          onFilter={store.setCategoryFilter}
          onSelect={store.setSelectedId}
          onToggleFavorite={(id) => {
            const was = store.favorites.includes(id)
            store.toggleFavorite(id)
            store.showToast(
              was ? 'Removed from favorites' : 'Saved to favorites',
            )
          }}
          onSwitchRole={() => store.setRole('vendor')}
          onInviteVendor={() => store.createInvite('vendor')}
          onAlertChange={(enabled, radiusMeters) =>
            store.setAlertSettings({
              ...store.alertSettings,
              enabled,
              radiusMeters,
            })
          }
          onEnablePush={async () => {
            if (!('Notification' in window)) {
              store.showToast('Notifications not supported here')
              return
            }
            const perm = await Notification.requestPermission()
            store.setAlertSettings({
              ...store.alertSettings,
              browserPush: perm === 'granted',
            })
            store.showToast(
              perm === 'granted'
                ? 'Phone notifications allowed'
                : 'Notifications blocked',
            )
          }}
          onCreateRequest={store.createRequest}
          onCancelRequest={store.cancelRequest}
          onCustomerName={(name) =>
            store.setCustomer({ displayName: name || 'Neighbor' })
          }
        />
      ) : (
        <VendorPanel
          profile={store.profile}
          isLive={store.youLive}
          liveCount={store.liveVendors.length}
          locationNote={locationNote}
          visibleRequests={store.vendorVisibleRequests}
          onProfileChange={store.setProfile}
          onGoLive={() => store.goLive(geo.position)}
          onEndShift={store.endShift}
          onSwitchRole={() => store.setRole('customer')}
          onInviteCustomer={() => store.createInvite('customer')}
          onAcceptRequest={store.acceptRequest}
          onCompleteRequest={store.completeRequest}
          onFocusRequest={(id) => {
            store.setActiveRequestId(id)
            const req = store.requests.find((r) => r.id === id)
            if (req) setMapFocus(req.location)
          }}
        />
      )}

      {store.shareInvite && (
        <ShareInviteModal
          url={store.shareInvite.url}
          payload={store.shareInvite.payload}
          onClose={store.dismissShare}
          onCopied={() => store.showToast('Invite link copied')}
        />
      )}

      {store.pendingInvite && (
        <AcceptInviteModal
          invite={store.pendingInvite}
          onDismiss={store.dismissPendingInvite}
          onAcceptVendor={store.acceptVendorInvite}
          onAcceptCustomer={store.acceptCustomerInvite}
        />
      )}

      {store.toast && (
        <div className="toast animate-rise" role="status">
          {store.toast}
        </div>
      )}
    </div>
  )
}
