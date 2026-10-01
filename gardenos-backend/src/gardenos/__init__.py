from flask import Flask, jsonify
from flask_cors import CORS
from config.config import settings
from gardenos.shared.limiter import limiter

def create_app():
    # Instance of flask app
    app = Flask(__name__)

    CORS(app, resources = {r"/*" : {"origins" : "*"}}) # Allow CORS for all routes

    limiter.init_app(app)

    @app.errorhandler(429)
    def too_many_requests(e):
        return jsonify({"error": {"code": "rate_limited", "message": "Too many requests. Try again later."}}), 429

    # Imported here (not at module top) so importing `gardenos` stays cheap and
    # the auth module can import config/models without circular imports.
    from gardenos.auth.controller import auth_bp
    app.register_blueprint(auth_bp)

    return app