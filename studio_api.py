"""JSON API used by the React print studio (frontend/).

Designs are stored in MySQL as JSON; uploaded artwork and thumbnails are
saved under static/uploads/studio/ and referenced by URL.
"""

import json
import os
import re
import shutil
import uuid

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    make_response,
    redirect,
    request,
    send_from_directory,
    session,
    url_for,
)

from models import db, User, Design


studio_api = Blueprint("studio_api", __name__)

FRONTEND_DIST = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "frontend",
    "dist"
)

STUDIO_DEV_SERVER = os.environ.get(
    "STUDIO_DEV_SERVER",
    "http://localhost:5173/studio/"
)

MAX_DESIGN_JSON = 1024 * 1024

# Stickers sent from the studio to the Create Sticker form.
STUDIO_ASSET_PATTERN = re.compile(r"^studio/[0-9a-f]{32}\.png$")

# File signatures, so uploads are checked by content rather than filename.
IMAGE_SIGNATURES = {
    "png": lambda head: head.startswith(b"\x89PNG\r\n\x1a\n"),
    "jpg": lambda head: head.startswith(b"\xff\xd8\xff"),
    "webp": lambda head: head[:4] == b"RIFF" and head[8:12] == b"WEBP",
}


def api_error(message, status=400):
    return jsonify(error=message), status


def fail(message, status=400):
    abort(make_response(jsonify(error=message), status))


def current_user():
    user_id = session.get("user_id")
    return User.query.get(user_id) if user_id else None


@studio_api.before_request
def require_studio_header():
    # Browsers cannot send custom headers cross-site without CORS approval,
    # so this blocks form-based CSRF against the session cookie.
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        if request.headers.get("X-StickerNest-Client") != "studio":
            return api_error("Missing studio client header.", 403)


def image_extension(file):
    head = file.stream.read(12)
    file.stream.seek(0)

    for extension, matches in IMAGE_SIGNATURES.items():
        if matches(head):
            return extension

    return None


def save_upload(file, subfolder, allowed=("png", "jpg", "webp")):
    """Save an uploaded image under static/uploads and return its filename
    relative to the uploads folder, or None if it isn't a valid image."""
    if not file or not file.filename:
        return None

    extension = image_extension(file)
    if extension not in allowed:
        return None

    folder = os.path.join(current_app.static_folder, "uploads", subfolder)
    os.makedirs(folder, exist_ok=True)

    filename = f"{uuid.uuid4().hex}.{extension}"
    file.save(os.path.join(folder, filename))

    return f"{subfolder}/{filename}" if subfolder else filename


def upload_url(relative_path):
    return url_for("static", filename=f"uploads/{relative_path}")


def remove_upload(relative_path):
    if not relative_path:
        return

    path = os.path.join(current_app.static_folder, "uploads", relative_path)
    if os.path.isfile(path):
        os.remove(path)


def studio_asset_exists(relative_path):
    return bool(STUDIO_ASSET_PATTERN.match(relative_path)) and os.path.isfile(
        os.path.join(current_app.static_folder, "uploads", relative_path)
    )


def claim_studio_asset(relative_path):
    """Copy a studio upload into static/uploads/ for a shop listing, so the
    listing keeps its image even if the studio design is deleted. Returns the
    new filename relative to static/uploads/."""
    uploads = os.path.join(current_app.static_folder, "uploads")
    filename = f"{uuid.uuid4().hex}.png"
    shutil.copyfile(
        os.path.join(uploads, relative_path),
        os.path.join(uploads, filename)
    )
    return filename


def design_summary(design):
    return {
        "id": design.id,
        "title": design.title,
        "thumbnail_url": upload_url(design.thumbnail) if design.thumbnail else None,
        "created_at": design.created_at.isoformat() + "Z",
        "updated_at": design.updated_at.isoformat() + "Z",
    }


def read_design_form():
    """Validate title + JSON data from a design form. Returns (title, data_text)
    or raises a 400 with a message."""
    title = (request.form.get("title") or "").strip()[:120] or "Untitled sheet"
    data_text = request.form.get("data") or ""

    if len(data_text) > MAX_DESIGN_JSON:
        fail("Design is too large to save.", 413)

    try:
        data = json.loads(data_text)
    except ValueError:
        fail("Design data is not valid JSON.")

    if not isinstance(data, dict) or not isinstance(data.get("stickers"), list):
        fail("Design data must contain a stickers list.")

    return title, data_text


def get_own_design(design_id):
    user = current_user()
    if not user:
        fail("Please log in.", 401)

    design = Design.query.get_or_404(design_id)
    if design.user_id != user.id:
        fail("Design not found.", 404)

    return design


# ---------- Studio app ----------

@studio_api.route("/studio/")
@studio_api.route("/studio/<path:path>")
def studio(path="index.html"):
    """Serve the built React studio, or point to the Vite dev server."""
    if not os.path.isfile(os.path.join(FRONTEND_DIST, "index.html")):
        return redirect(STUDIO_DEV_SERVER)

    if not os.path.isfile(os.path.join(FRONTEND_DIST, path)):
        path = "index.html"

    return send_from_directory(FRONTEND_DIST, path)


@studio_api.route("/studio")
def studio_root():
    return redirect(url_for("studio_api.studio"))


# ---------- Account ----------

@studio_api.route("/api/me")
def me():
    user = current_user()
    if not user:
        return jsonify(user=None)

    return jsonify(user={
        "id": user.id,
        "name": user.name,
        "role": user.role,
    })


# ---------- Assets ----------

@studio_api.route("/api/studio/assets", methods=["POST"])
def upload_asset():
    if not current_user():
        return api_error("Please log in.", 401)

    relative_path = save_upload(request.files.get("file"), "studio")
    if not relative_path:
        return api_error("Upload a PNG, JPG or WebP image.")

    return jsonify(url=upload_url(relative_path)), 201


# ---------- Designs ----------

@studio_api.route("/api/studio/designs")
def list_designs():
    user = current_user()
    if not user:
        return api_error("Please log in.", 401)

    designs = (
        Design.query
        .filter_by(user_id=user.id)
        .order_by(Design.updated_at.desc())
        .all()
    )

    return jsonify(designs=[design_summary(design) for design in designs])


@studio_api.route("/api/studio/designs", methods=["POST"])
def create_design():
    user = current_user()
    if not user:
        return api_error("Please log in.", 401)

    title, data_text = read_design_form()

    design = Design(
        user_id=user.id,
        title=title,
        data=data_text,
        thumbnail=save_upload(request.files.get("thumbnail"), "studio", ("jpg", "png")),
    )

    db.session.add(design)
    db.session.commit()

    return jsonify(design=design_summary(design)), 201


@studio_api.route("/api/studio/designs/<int:design_id>")
def get_design(design_id):
    design = get_own_design(design_id)

    return jsonify(design={
        **design_summary(design),
        "data": json.loads(design.data),
    })


@studio_api.route("/api/studio/designs/<int:design_id>", methods=["PUT"])
def update_design(design_id):
    design = get_own_design(design_id)
    title, data_text = read_design_form()

    design.title = title
    design.data = data_text

    thumbnail = save_upload(request.files.get("thumbnail"), "studio", ("jpg", "png"))
    if thumbnail:
        remove_upload(design.thumbnail)
        design.thumbnail = thumbnail

    db.session.commit()

    return jsonify(design=design_summary(design))


@studio_api.route("/api/studio/designs/<int:design_id>", methods=["DELETE"])
def delete_design(design_id):
    design = get_own_design(design_id)

    remove_upload(design.thumbnail)
    db.session.delete(design)
    db.session.commit()

    return jsonify(deleted=design_id)
