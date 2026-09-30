from flask import Flask
from flask_cors import CORS
from config.config import settings

def create_app():
    # Instance of flask app
    app = Flask(__name__)

    CORS(app, resources = {r"/*" : {"origins" : "*"}}) # Allow CORS for all routes

    return app