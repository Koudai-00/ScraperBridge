import os
import logging
from flask import Flask
from flask_cors import CORS

# Set up logging
logging.basicConfig(level=logging.DEBUG)

# Create the Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")

# Enable CORS for API endpoints
CORS(app, origins="*", allow_headers=["*"], methods=["*"])

# Import and register routes
from api_routes import api_bp
app.register_blueprint(api_bp)

# Import main routes
import main
