# StreetPin

Find mobile vendors — ice cream trucks, Lotte carts, food trucks, and more — live on a map.

## Who it’s for

- **Customers:** see who’s live nearby, filter by type, favorite a vendor, open details
- **Vendors:** set your cart name, tap **Go live**, share your GPS pin while you roll

## Run locally

```bash
cd streetpin
npm install
npm run dev
```

Open the URL Vite prints (usually `http://localhost:5173`).

## Try the demo

1. Choose **I’m looking for a vendor** — sample live vendors move on the map
2. Tap a pin or list row → Favorite / filter by type
3. Switch to **Vendor mode** → edit your profile → **Go live**
4. Switch back to customer view to see yourself on the map when live

Location falls back to a demo neighborhood (Echo Park / LA) if the browser blocks GPS.

## Stack

- React + TypeScript (Vite)
- Leaflet / React-Leaflet map
- Local storage for favorites, role, and vendor profile

## Next steps

- Real backend (Supabase/Firebase) for multi-user live pins
- Push alerts when a favorite vendor goes live nearby
- Native shell (Expo) for reliable background GPS on the road
