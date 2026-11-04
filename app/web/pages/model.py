"""Compatibility wrapper for the current model landing page."""

from app.web.pages.model_landing import render_model_landing_page


def render_model_page(user=None) -> str:
    return render_model_landing_page(user)
