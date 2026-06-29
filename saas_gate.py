"""
Subscription gate placeholder for SaaS launch.

Default: disabled — app runs as today (Streamlit Cloud / open access).

When SAAS_GATE_ENABLED=true, blocks the scanner until Stripe + auth are wired.
Set SAAS_GATE_ENABLED=false (or unset) until you configure payments.
"""

from __future__ import annotations

import os

import streamlit as st


def saas_gate_enabled() -> bool:
    return os.getenv("SAAS_GATE_ENABLED", "").strip().lower() in ("1", "true", "yes")


def stripe_configured() -> bool:
    key = (os.getenv("STRIPE_SECRET_KEY") or os.getenv("STRIPE_API_KEY") or "").strip()
    return bool(key)


def enforce_saas_gate() -> None:
    """Call once before the main scanner UI. Uses st.stop() when access denied."""
    if not saas_gate_enabled():
        return

    st.markdown("### hioncrypto Scanner")
    st.warning("Subscription access is required.")

    if not stripe_configured():
        st.info(
            "The subscription gate is enabled but Stripe is not configured yet. "
            "Add `STRIPE_SECRET_KEY` (and webhook handler) on your host, or set "
            "`SAAS_GATE_ENABLED=false` until launch."
        )
    else:
        st.info(
            "Stripe is configured. Next step: wire Checkout + login so paid users "
            "unlock the scanner automatically."
        )

    price = (os.getenv("PUBLIC_PRICE_LABEL") or "").strip()
    if price:
        st.caption(f"Plan: {price}")

    checkout = (os.getenv("STRIPE_CHECKOUT_URL") or "").strip()
    if checkout:
        st.link_button("Subscribe", checkout, type="primary")
    else:
        st.caption("Set `STRIPE_CHECKOUT_URL` to your Stripe Payment Link or Checkout URL.")

    st.stop()
