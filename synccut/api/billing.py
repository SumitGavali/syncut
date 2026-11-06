"""Stripe checkout and subscription webhook routes."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from functools import wraps

import stripe
from flask import Blueprint, current_app, jsonify, request, session

from synccut.api.db import (
    activate_pro_subscription,
    downgrade_subscription,
    get_stripe_customer_id,
    get_subscription_info,
    get_user_by_token,
)

billing_bp = Blueprint("billing", __name__, url_prefix="/api/billing")


def _current_user():
    auth_header = request.headers.get("Authorization", "")
    token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
    token = token or request.args.get("token", "") or session.get("auth_token", "")
    return get_user_by_token(token)


def _require_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not _current_user():
            return jsonify({"error": "Authentication required."}), 401
        return view(*args, **kwargs)

    return wrapped


def _field(value, name: str, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


@billing_bp.route("/subscription", methods=["GET"])
@_require_auth
def subscription_status():
    user = _current_user()
    return jsonify(get_subscription_info(user["id"]))


@billing_bp.route("/checkout", methods=["POST"])
@_require_auth
def checkout():
    secret_key = os.environ.get("STRIPE_SECRET_KEY")
    price_id = os.environ.get("STRIPE_PRO_PRICE_ID")
    if not secret_key or not price_id:
        return jsonify({"error": "Stripe billing is not configured on this server."}), 503

    user = _current_user()
    subscription_info = get_subscription_info(user["id"])
    if subscription_info["tier"] in {"pro", "studio"}:
        return jsonify({"error": "This account already has an active paid subscription."}), 409
    stripe.api_key = secret_key
    studio_url = current_app.config.get("STUDIO_URL", "http://localhost:5173").rstrip("/")
    customer_id = get_stripe_customer_id(user["id"])
    customer = {"customer": customer_id} if customer_id else {"customer_email": user["email"]}
    try:
        checkout_session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            client_reference_id=user["id"],
            metadata={"user_id": user["id"], "tier": "pro"},
            subscription_data={"metadata": {"user_id": user["id"], "tier": "pro"}},
            success_url=f"{studio_url}/dashboard?billing=success&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{studio_url}/pricing?billing=cancelled",
            **customer,
        )
    except stripe.StripeError:
        current_app.logger.exception("Stripe could not create a checkout session.")
        return jsonify({"error": "Could not start Stripe Checkout. Please try again."}), 502

    if not checkout_session.url:
        current_app.logger.error("Stripe returned a checkout session without a URL.")
        return jsonify({"error": "Stripe did not return a checkout URL."}), 502
    return jsonify({"checkout_url": checkout_session.url}), 200


@billing_bp.route("/webhook", methods=["POST"])
def webhook():
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
    if not webhook_secret:
        return jsonify({"error": "Stripe webhook is not configured on this server."}), 503

    signature = request.headers.get("Stripe-Signature", "")
    try:
        event = stripe.Webhook.construct_event(
            request.get_data(cache=False),
            signature,
            webhook_secret,
        )
    except (ValueError, stripe.SignatureVerificationError):
        return jsonify({"error": "Invalid Stripe webhook signature or payload."}), 400

    event_type = _field(event, "type", "")
    event_object = _field(_field(event, "data", {}), "object", {})

    if event_type == "checkout.session.completed":
        if _field(event_object, "mode") != "subscription":
            return jsonify({"received": True}), 200
        subscription_id = _field(event_object, "subscription")
        if isinstance(subscription_id, dict):
            subscription_id = subscription_id.get("id")
        user_id = _field(event_object, "client_reference_id")
        metadata = _field(event_object, "metadata", {}) or {}
        user_id = user_id or _field(metadata, "user_id")
        if not user_id or not subscription_id:
            return jsonify({"error": "Checkout session is missing its user or subscription."}), 400

        stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
        if not stripe.api_key:
            return jsonify({"error": "Stripe billing is not configured on this server."}), 503
        subscription = stripe.Subscription.retrieve(subscription_id)
        status = _field(subscription, "status", "")
        if status not in {"active", "trialing"}:
            return jsonify({"received": True, "subscription_status": status}), 200
        period_end = _field(subscription, "current_period_end")
        expires_at = (
            datetime.fromtimestamp(float(period_end), tz=timezone.utc)
            if period_end is not None
            else None
        )
        customer_id = _field(event_object, "customer")
        if isinstance(customer_id, dict):
            customer_id = customer_id.get("id")
        if not activate_pro_subscription(user_id, customer_id, subscription_id, expires_at):
            return jsonify({"error": "No account matches this checkout session."}), 400

    elif event_type == "customer.subscription.deleted":
        subscription_id = _field(event_object, "id")
        customer_id = _field(event_object, "customer")
        if isinstance(customer_id, dict):
            customer_id = customer_id.get("id")
        downgrade_subscription(subscription_id, customer_id)

    return jsonify({"received": True}), 200
