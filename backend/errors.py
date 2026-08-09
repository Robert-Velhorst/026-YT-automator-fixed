from uuid import uuid4

from flask import jsonify, request
from werkzeug.exceptions import HTTPException


class ApiError(Exception):
    def __init__(self, message, status=400, code="bad_request", details=None):
        super().__init__(message)
        self.message, self.status, self.code, self.details = message, status, code, details


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def api_error(error):
        try:
            from extensions import db
            from models import ErrorLog
            db.session.rollback()
            db.session.add(ErrorLog(request_id=getattr(request, "request_id", None), code=error.code,
                                    message=error.message, details_json=None)); db.session.commit()
        except Exception:
            app.logger.exception("Could not persist API error")
        return jsonify({"error": {"code": error.code, "message": error.message, "details": error.details,
                                  "request_id": getattr(request, "request_id", None)}}), error.status

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify({"error": {"code": error.name.lower().replace(" ", "_"), "message": error.description,
                                  "request_id": getattr(request, "request_id", None)}}), error.code

    @app.errorhandler(Exception)
    def unexpected(error):
        app.logger.exception("Unhandled request error")
        try:
            from extensions import db
            from models import ErrorLog
            db.session.rollback()
            db.session.add(ErrorLog(request_id=getattr(request, "request_id", None), code="internal_error",
                                    message=type(error).__name__)); db.session.commit()
        except Exception:
            app.logger.exception("Could not persist internal error")
        return jsonify({"error": {"code": "internal_error", "message": "An unexpected error occurred",
                                  "request_id": getattr(request, "request_id", str(uuid4()))}}), 500
