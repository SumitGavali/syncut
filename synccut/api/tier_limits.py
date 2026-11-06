"""Flask decorators for enforcing account-tier capabilities."""
from __future__ import annotations

from functools import wraps

from flask import g, jsonify, request

from synccut.core.quota import TIER_LIMITS


def _resolution_height(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"4k", "uhd"}:
            return 2160
        if normalized in {"hd", "1080p"}:
            return 1080
        if normalized == "720p":
            return 720
        try:
            return int(normalized)
        except ValueError:
            return None
    return None


def check_tier_limits(feature: str):
    """Gate an API feature using the authenticated user's current subscription."""
    if feature not in {"upload", "ai_cuts", "export"}:
        raise ValueError(f"Unknown tier-limited feature: {feature}")

    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            user = getattr(g, "current_user", None)
            if not user:
                from synccut.api.db import get_user_by_token

                auth_header = request.headers.get("Authorization", "")
                token = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
                token = token or request.args.get("token", "")
                user = get_user_by_token(token)
            if not user:
                return jsonify({"error": "Authentication required."}), 401

            tier = user.get("tier", "free")
            limits = TIER_LIMITS.get(tier, TIER_LIMITS["free"])
            if feature == "upload":
                uploaded_files = [
                    file
                    for file in request.files.getlist("files")
                    if file and file.filename
                ]
                if not uploaded_files:
                    reference = request.files.get("reference")
                    inputs = request.files.getlist("inputs")
                    uploaded_files = [
                        file
                        for file in [reference, *inputs]
                        if file and file.filename
                    ]
                file_count = len(uploaded_files)
                if file_count > limits["max_cameras"]:
                    return jsonify(
                        {
                            "error": (
                                f"The {tier.title()} tier allows up to "
                                f"{limits['max_cameras']} cameras."
                            )
                        }
                    ), 403
            elif feature == "ai_cuts" and not limits["full_ai_cuts"]:
                return jsonify(
                    {"error": "Full AI camera cuts are available on Pro and Studio."}
                ), 403
            elif feature == "export":
                data = request.get_json(silent=True) or {}
                if not isinstance(data, dict):
                    return jsonify({"error": "An export JSON object is required."}), 400
                export_format = str(data.get("format", "fcpxml")).lower()
                if tier == "free" and export_format in {"aaf", "fcpxml", "fcpxm"}:
                    return jsonify(
                        {"error": "AAF and FCPXML exports are available on Pro and Studio."}
                    ), 403
                requested_height = next(
                    (
                        height
                        for height in (
                            _resolution_height(data.get("resolution")),
                            _resolution_height(data.get("height")),
                            _resolution_height(data.get("export_height")),
                        )
                        if height is not None
                    ),
                    None,
                )
                if requested_height and requested_height > limits["max_export_height"]:
                    return jsonify(
                        {
                            "error": (
                                f"The {tier.title()} tier supports exports up to "
                                f"{limits['max_export_height']}p."
                            )
                        }
                    ), 403

            g.tier_limits = limits
            return view(*args, **kwargs)

        return wrapped

    return decorate
