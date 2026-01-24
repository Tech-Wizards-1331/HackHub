from flask import Blueprint

faculty_bp = Blueprint('faculty', __name__)

from . import routes
