import type { Role } from '../types'

interface WelcomeProps {
  onChoose: (role: Role) => void
}

export function Welcome({ onChoose }: WelcomeProps) {
  return (
    <section className="welcome">
      <div className="welcome-glow" aria-hidden />
      <div className="street-grid" aria-hidden />
      <div className="paint-splash splash-a" aria-hidden />
      <div className="paint-splash splash-b" aria-hidden />
      <div className="crosswalk" aria-hidden>
        <span />
        <span />
        <span />
        <span />
        <span />
      </div>

      <div className="welcome-inner">
        <p className="street-kicker animate-rise">Live on the block</p>
        <p className="brand-mark animate-rise delay-1">
          Street<span>Pin</span>
        </p>
        <h1 className="welcome-title animate-rise delay-2">
          Chase the truck. Catch the cart. Know who’s rolling.
        </h1>
        <p className="welcome-sub animate-rise delay-3">
          A loud little map for ice cream runs, Lotte stops, taco trucks, and
          whoever’s out grinding the neighborhood tonight.
        </p>

        <div className="role-actions animate-rise delay-4">
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => onChoose('customer')}
          >
            Find someone nearby
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => onChoose('vendor')}
          >
            I’m rolling — go live
          </button>
        </div>

        <p className="welcome-note animate-rise delay-5">
          Demo vendors are already out on the map — tap in and play.
        </p>
      </div>
    </section>
  )
}
