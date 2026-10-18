import json

from flask import has_request_context, request

from extensions import db
from models import AuditEvent


def record_audit(action, target_type=None, target_id=None, actor="operator", details=None, commit=False):
    event = AuditEvent(
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        request_id=getattr(request, "request_id", None) if has_request_context() else None,
        details_json=json.dumps(details, separators=(",", ":"), sort_keys=True) if details else None,
    )
    db.session.add(event)
    if commit:
        db.session.commit()
    return event
