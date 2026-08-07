# StreetPin

Find mobile vendors — ice cream trucks, Lotte carts, food trucks — live on a map. Street vibe UI for customers and vendors.

## Try it

```bash
cd streetpin
npm install
npm run dev
```

## What’s in this build

### Customer
- Live map of nearby vendors + favorites
- **Closer alerts** when a favorite enters your distance (1 block → 1 mile)
- **Request a vendor** — ping live carts within a radius (e.g. you’re at the park)
- **Invite a vendor** — share a link so they enter cart info and go live

### Vendor
- Profile (name, type, menu, when you’re usually around)
- **Go live / End shift**
- **Invite customers** — share a track link
- **Client request inbox** — accept and jump to their pin on the map

### Demo
Sample vendors move on the map so you can try without GPS. Location falls back to Echo Park / LA if the browser blocks geolocation.

## Stack
React + TypeScript (Vite), Leaflet map, localStorage for demo state.
