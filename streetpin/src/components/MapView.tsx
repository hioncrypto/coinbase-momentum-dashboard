import { useEffect, useMemo } from 'react'
import {
  MapContainer,
  TileLayer,
  Marker,
  CircleMarker,
  Popup,
  useMap,
} from 'react-leaflet'
import L from 'leaflet'
import type { LatLng, Vendor, VendorCategory } from '../types'
import { CATEGORY_LABELS } from '../types'
import { formatDistance, distanceMeters } from '../hooks/useGeolocation'
import 'leaflet/dist/leaflet.css'

const categoryColor: Record<VendorCategory, string> = {
  'ice-cream': '#00d6b0',
  lotte: '#ffe566',
  'food-truck': '#ff5a36',
  coffee: '#ff9f1c',
  snacks: '#7cf5ff',
  other: '#c9c4b8',
}

function pinIcon(color: string, live: boolean, selected: boolean) {
  const size = selected ? 46 : 38
  const pulse = live
    ? `<circle cx="18" cy="18" r="14" fill="${color}" opacity="0.3">
        <animate attributeName="r" values="12;18;12" dur="1.8s" repeatCount="indefinite"/>
        <animate attributeName="opacity" values="0.4;0.05;0.4" dur="1.8s" repeatCount="indefinite"/>
      </circle>`
    : ''
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 36 36">
      ${pulse}
      <path d="M18 3.5c-6.6 0-12 5.2-12 12 0 8.4 12 17 12 17s12-8.6 12-17c0-6.8-5.4-12-12-12z"
        fill="${live ? color : '#6e6a62'}" stroke="#121214" stroke-width="2"/>
      <circle cx="18" cy="15" r="4.4" fill="#121214"/>
      <circle cx="18" cy="15" r="1.6" fill="${live ? color : '#c9c4b8'}"/>
    </svg>`
  return L.divIcon({
    className: 'streetpin-marker',
    html: svg,
    iconSize: [size, size],
    iconAnchor: [size / 2, size - 2],
    popupAnchor: [0, -size + 8],
  })
}

function Recenter({
  center,
  zoom,
}: {
  center: LatLng
  zoom: number
}) {
  const map = useMap()
  useEffect(() => {
    map.setView([center.lat, center.lng], zoom, { animate: true })
  }, [center.lat, center.lng, zoom, map])
  return null
}

interface MapViewProps {
  center: LatLng
  userPosition: LatLng
  vendors: Vendor[]
  selectedId: string | null
  onSelect: (id: string) => void
  showUser?: boolean
}

export function MapView({
  center,
  userPosition,
  vendors,
  selectedId,
  onSelect,
  showUser = true,
}: MapViewProps) {
  const icons = useMemo(() => {
    const map = new Map<string, L.DivIcon>()
    for (const v of vendors) {
      map.set(
        v.id,
        pinIcon(categoryColor[v.category], v.isLive, selectedId === v.id),
      )
    }
    return map
  }, [vendors, selectedId])

  return (
    <MapContainer
      center={[center.lat, center.lng]}
      zoom={14}
      className="street-map"
      zoomControl={false}
      attributionControl={false}
    >
      <TileLayer
        url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
        attribution="&copy; OpenStreetMap &copy; CARTO"
      />
      <Recenter center={center} zoom={14} />

      {showUser && (
        <CircleMarker
          center={[userPosition.lat, userPosition.lng]}
          radius={8}
          pathOptions={{
            color: '#121214',
            fillColor: '#ffe566',
            fillOpacity: 1,
            weight: 2,
          }}
        >
          <Popup>You are here</Popup>
        </CircleMarker>
      )}

      {vendors.map((v) => (
        <Marker
          key={v.id}
          position={[v.location.lat, v.location.lng]}
          icon={icons.get(v.id)}
          eventHandlers={{ click: () => onSelect(v.id) }}
          opacity={v.isLive ? 1 : 0.55}
        >
          <Popup>
            <strong>{v.name}</strong>
            <br />
            {CATEGORY_LABELS[v.category]}
            <br />
            {v.isLive ? 'Live now' : 'Offline'}
            {' · '}
            {formatDistance(distanceMeters(userPosition, v.location))}
          </Popup>
        </Marker>
      ))}
    </MapContainer>
  )
}
