"""Home and shared pages."""

from flask import Blueprint, current_app, render_template, send_from_directory

main_bp = Blueprint("main", __name__)


@main_bp.get("/")
def index():
    return render_template("main/index.html")


@main_bp.get("/uploads/<path:filename>")
def uploaded_file(filename: str):
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename)
