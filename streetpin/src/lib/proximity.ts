/** Rough walking ETA from meters (~5 km/h). */
export function walkingMinutes(meters: number): number {
  return Math.max(1, Math.round(meters / 80))
}

export function approachLabel(meters: number, radiusMeters: number): string | null {
  if (meters > radiusMeters * 3) return null
  if (meters <= radiusMeters) return 'In range — almost on you'
  if (meters <= radiusMeters * 1.5) return 'Getting close'
  if (meters <= radiusMeters * 3) return 'Heading your way'
  return null
}
