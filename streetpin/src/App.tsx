import { useEffect, useMemo, useState } from 'react'
import { Welcome } from './components/Welcome'
import { MapView } from './components/MapView'
import { CustomerPanel } from './components/CustomerPanel'
import { VendorPanel } from './components/VendorPanel'
import { useGeolocation } from './hooks/useGeolocation'
import { useStreetPinStore } from './hooks/useStreetPinStore'
import { DEFAULT_CENTER } from './data/demoVendors'

export default function App() {
  const {
    role,
    setRole,
    favorites,
    toggleFavorite,
    profile,
    setProfile,
    youLive,
    youLocation,
    goLive,
    endShift,
    updateYouLocation,
    vendors,
    liveVendors,
    selectedId,
    setSelectedId,
    toast,
    showToast,
    categoryFilter,
    setCategoryFilter,
  } = useStreetPinStore()

  const geo = useGeolocation(true)
  const [mapFocus, setMapFocus] = useState(DEFAULT_CENTER)

  useEffect(() => {
    if (youLive && !geo.usingFallback) {
      updateYouLocation(geo.position)
    }
  }, [
    geo.position.lat,
    geo.position.lng,
    geo.usingFallback,
    youLive,
    updateYouLocation,
    geo.position,
  ])

  useEffect(() => {
    if (role === 'vendor' && youLive) {
      setMapFocus(youLocation)
      return
    }
    const selected = vendors.find((v) => v.id === selectedId)
    if (selected) {
      setMapFocus(selected.location)
      return
    }
    setMapFocus(geo.position)
  }, [selectedId, role, youLive, youLocation, geo.position, vendors])

  const visibleVendors = useMemo(() => {
    if (categoryFilter === 'all') return vendors
    return vendors.filter((v) => v.category === categoryFilter)
  }, [vendors, categoryFilter])

  if (!role) {
    return <Welcome onChoose={(next) => setRole(next)} />
  }

  const locationNote = geo.usingFallback
    ? 'Demo location active (browser location denied or unavailable). Your pin uses the sample map area.'
    : `Sharing your GPS · accuracy ~${Math.round(geo.accuracy ?? 0)} m`

  return (
    <div className="app-shell">
      <div className="map-stage">
        <MapView
          center={mapFocus}
          userPosition={
            role === 'vendor' && youLive ? youLocation : geo.position
          }
          vendors={visibleVendors}
          selectedId={selectedId}
          onSelect={setSelectedId}
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

      {role === 'customer' ? (
        <CustomerPanel
          vendors={vendors}
          favorites={favorites}
          selectedId={selectedId}
          userPosition={geo.position}
          categoryFilter={categoryFilter}
          onFilter={setCategoryFilter}
          onSelect={setSelectedId}
          onToggleFavorite={(id) => {
            const was = favorites.includes(id)
            toggleFavorite(id)
            showToast(was ? 'Removed from favorites' : 'Saved to favorites')
          }}
          onSwitchRole={() => setRole('vendor')}
        />
      ) : (
        <VendorPanel
          profile={profile}
          isLive={youLive}
          liveCount={liveVendors.length}
          onProfileChange={setProfile}
          onGoLive={() => goLive(geo.position)}
          onEndShift={endShift}
          onSwitchRole={() => setRole('customer')}
          locationNote={locationNote}
        />
      )}

      {toast && (
        <div className="toast animate-rise" role="status">
          {toast}
        </div>
      )}
    </div>
  )
}
