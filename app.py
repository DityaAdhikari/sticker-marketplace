from typing import Union

from werkzeug import Response
from werkzeug.utils import secure_filename
import os

from flask import Flask, render_template, request, redirect, url_for, flash, session
from models import db, User, Sticker, Artist, Category, Wishlist ,Purchase
from studio_api import studio_api, studio_asset_exists, claim_studio_asset

from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func
from dotenv import load_dotenv
import secrets

load_dotenv()


app = Flask(__name__)


def load_secret_key():
    """Use SECRET_KEY from the environment, otherwise a random key kept in
    instance/secret_key. A known default key would let anyone forge a
    session cookie and log in as any user without a password."""
    key = os.environ.get("SECRET_KEY")
    if key:
        return key

    path = os.path.join(app.instance_path, "secret_key")
    if os.path.exists(path):
        with open(path) as file:
            return file.read().strip()

    os.makedirs(app.instance_path, exist_ok=True)
    key = secrets.token_hex(32)
    with open(path, "w") as file:
        file.write(key)
    return key


app.secret_key = load_secret_key()

MIN_PASSWORD_LENGTH = 8

# Checked when an email isn't registered, so a failed login takes the same
# time either way and doesn't reveal which emails have accounts.
DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_hex(16))


ADMIN_EMAIL = "adhikari2186@gmail.com"

app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL",
    "mysql+pymysql://root:@localhost:3307/sticker_site"
)

# Studio uploads (artwork, thumbnails, published stickers).
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
app.register_blueprint(studio_api)

with app.app_context():
   
    db.create_all()


@app.context_processor
def inject_categories():
    return dict(nav_categories=Category.query.all())

@app.route("/")
def home():
    # Likes are wishlist saves; count them per sticker.
    likes = (
        db.session.query(
            Wishlist.sticker_id,
            func.count(Wishlist.id).label("like_count")
        )
        .group_by(Wishlist.sticker_id)
        .subquery()
    )
    like_count = func.coalesce(likes.c.like_count, 0)

    # Only stickers uploaded by real artist accounts, most liked first.
    featured = (
        db.session.query(Sticker, like_count)
        .join(Artist, Sticker.artist_id == Artist.id)
        .outerjoin(likes, likes.c.sticker_id == Sticker.id)
        .filter(Artist.user_id.isnot(None))
        .order_by(like_count.desc(), Sticker.id.desc())
        .limit(6)
        .all()
    )

    liked_ids = set()
    if "user_id" in session:
        liked_ids = {
            item.sticker_id
            for item in Wishlist.query.filter_by(user_id=session["user_id"])
        }

    categories = Category.query.all()
    return render_template(
        "index.html",
        featured=featured,
        liked_ids=liked_ids,
        categories=categories
    )

@app.route("/shop")
def shop():
    category_name = request.args.get('category')
    if category_name:
        stickers = Sticker.query.join(Category).filter(Category.name == category_name).all()
    else:
        stickers = Sticker.query.all()
    return render_template("shop.html", stickers=stickers)
@app.route("/sticker/<int:sticker_id>")
def sticker_detail(sticker_id):
    sticker = Sticker.query.get_or_404(sticker_id)

    return render_template(
        "sticker_detail.html",
        sticker=sticker
    )

@app.route("/search")
def search():
    q = request.args.get('q', '')
    stickers = Sticker.query.filter(Sticker.name.ilike(f"%{q}%")).all()
    return render_template("shop.html", stickers=stickers)

@app.route("/artists")
def artists():
    artist_list = Artist.query.all()

    return render_template(
        "artists.html",
        artists=artist_list
    )


@app.route("/artists/<int:artist_id>")
def artist_profile(artist_id):
    artist = Artist.query.get_or_404(artist_id)

    stickers = Sticker.query.filter_by(
        artist_id=artist.id
    ).order_by(Sticker.id.desc()).all()

    like_counts = {}
    if stickers:
        like_counts = dict(
            db.session.query(Wishlist.sticker_id, func.count(Wishlist.id))
            .filter(Wishlist.sticker_id.in_([s.id for s in stickers]))
            .group_by(Wishlist.sticker_id)
            .all()
        )

    liked_ids = set()
    if "user_id" in session:
        liked_ids = {
            item.sticker_id
            for item in Wishlist.query.filter_by(user_id=session["user_id"])
        }

    return render_template(
        "artist/profile.html",
        artist=artist,
        stickers=stickers,
        like_counts=like_counts,
        total_likes=sum(like_counts.values()),
        liked_ids=liked_ids,
        is_owner=artist.user_id is not None and artist.user_id == session.get("user_id")
    )

@app.route("/apply-artist", methods=["POST"])
def apply_artist():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = User.query.get(session["user_id"])

    if user.role == "artist":
        flash("You are already an artist.")
        return redirect(url_for("profile"))

    if user.artist_status == "pending":
        flash("Your artist application is already pending.")
        return redirect(url_for("profile"))

    user.artist_status = "pending"
    db.session.commit()

    flash("Artist application submitted. Please wait for admin approval.")
    return redirect(url_for("profile"))


@app.route("/admin/artist-requests")
def artist_requests():
    if "user_id" not in session:
        return redirect(url_for("login"))

    admin = User.query.get(session["user_id"])

    if admin.role != "admin":
        flash("Access denied.")
        return redirect(url_for("home"))

    pending_users = User.query.filter_by(
        artist_status="pending"
    ).all()

    return render_template(
        "admin/artist_requests.html",
        users=pending_users
    )


@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/contact", methods=["GET", "POST"])
def contact():
    return render_template("contact.html")


def find_user_by_email(email):
    return User.query.filter(func.lower(User.email) == email).first()


@app.route("/login", methods=["GET", "POST"])
def login():

    if session.get("user_id"):
        return redirect(url_for("home"))

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = find_user_by_email(email)
        password_hash = user.password_hash if user else DUMMY_PASSWORD_HASH

        if check_password_hash(password_hash, password) and user:

            # Start a fresh session so nothing from before login carries over.
            session.clear()
            session["user_id"] = user.id
            session["user_name"] = user.name

            flash("Welcome back!")
            return redirect(url_for("home"))

        flash("Invalid email or password.")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():

    if session.get("user_id"):
        return redirect(url_for("home"))

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not name or not email or not password:
            flash("Please fill in all fields.")
            return redirect(url_for("register"))

        if len(password) < MIN_PASSWORD_LENGTH:
            flash(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
            return redirect(url_for("register"))

        if password != confirm_password:
            flash("Passwords do not match.")
            return redirect(url_for("register"))

        existing_user = find_user_by_email(email)

        if existing_user:
            flash("Email already exists.")
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(password)

        user = User(
            name=name,
            email=email,
            password_hash=hashed_password
        )

        db.session.add(user)
        db.session.commit()

        flash("Registration successful!")

        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/profile")
def profile():

    if "user_id" not in session:
        flash("Please login to view your profile.")
        return redirect(url_for("login"))

    user = User.query.get_or_404(session["user_id"])

    wishlist_items = Wishlist.query.filter_by(
        user_id=user.id
    ).all()

    artist = Artist.query.filter_by(user_id=user.id).first()

    created_stickers = []
    if artist:
        created_stickers = Sticker.query.filter_by(
            artist_id=artist.id
        ).all()

    purchases = Purchase.query.filter_by(
       user_id=user.id,
       status="completed"
       ).all()

    return render_template(
    "profile/profile.html",
    user=user,
    wishlist_items=wishlist_items,
    created_stickers=created_stickers,
    purchases=purchases,
    wishlist_count=len(wishlist_items),
    purchased_count=len(purchases),
    created_count=len(created_stickers)
)

@app.route("/edit-profile", methods=["GET", "POST"])
def edit_profile():

    if "user_id" not in session:
        return redirect(url_for("login"))

    user = User.query.get(session["user_id"])

    if request.method == "POST":

        user.name = request.form["name"]
        user.bio = request.form["bio"]
        user.location = request.form["location"]

        # Profile picture
        file = request.files.get("profile_image")

        if file and file.filename:

            filename = secure_filename(file.filename)

            upload_folder = os.path.join(
                app.static_folder,
                "uploads"
            )

            os.makedirs(upload_folder, exist_ok=True)

            file.save(
                os.path.join(upload_folder, filename)
            )

            user.profile_image = filename

        db.session.commit()

        flash("Profile updated successfully!")
        return redirect(url_for("profile"))

    return render_template(
        "profile/edit_profile.html",
        user=user
    )
@app.route("/admin/approve-artist/<int:user_id>", methods=["POST"])
def approve_artist(user_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    admin = User.query.get(session["user_id"])

    if admin.role != "admin":
        flash("Access denied.")
        return redirect(url_for("home"))

    user = User.query.get_or_404(user_id)

    if user.artist_status != "pending":
        flash("No pending artist request.")
        return redirect(url_for("artist_requests"))

    artist = Artist(
        user_id=user.id,
        name=user.name,
        handle="@" + user.name.lower().replace(" ", "_"),
        bio=user.bio,
        avatar=user.profile_image
    )

    user.role = "artist"
    user.artist_status = "approved"

    db.session.add(artist)
    db.session.commit()

    flash(f"{user.name} is now an artist.")
    return redirect(url_for("artist_requests"))

@app.route("/admin/reject-artist/<int:user_id>", methods=["POST"])
def reject_artist(user_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    admin = User.query.get(session["user_id"])

    if admin.role != "admin":
        flash("Access denied.")
        return redirect(url_for("home"))

    user = User.query.get_or_404(user_id)

    if user.artist_status != "pending":
        flash("No pending artist request.")
        return redirect(url_for("artist_requests"))

    user.artist_status = "rejected"

    db.session.commit()

    flash(f"{user.name}'s artist request was rejected.")
    return redirect(url_for("artist_requests"))

@app.route("/artist-dashboard")
def artist_dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = User.query.get(session["user_id"])
    artist = Artist.query.filter_by(user_id=user.id).first()

    if not artist or user.role != "artist":
        flash("Access denied.")
        return redirect(url_for("profile"))
    
    stickers = Sticker.query.filter_by(
        artist_id=artist.id
    ).order_by(Sticker.id.desc()).all()

    like_counts = {}
    if stickers:
        like_counts = dict(
            db.session.query(Wishlist.sticker_id, func.count(Wishlist.id))
            .filter(Wishlist.sticker_id.in_([s.id for s in stickers]))
            .group_by(Wishlist.sticker_id)
            .all()
        )

    return render_template(
        "artist/dashboard.html",
        user=user,
        artist=artist,
        stickers=stickers,
        like_counts=like_counts,
        total_likes=sum(like_counts.values())
    )



@app.route("/create-sticker", methods=["GET", "POST"])
def create_sticker():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = User.query.get(session["user_id"])

    if user.role != "artist":
        flash("Access denied.")
        return redirect(url_for("profile"))

    artist = Artist.query.filter_by(user_id=user.id).first()

    if not artist:
        flash("Artist profile not found.")
        return redirect(url_for("profile"))

    categories = Category.query.all()

    # A sticker sent over from the Print Studio, e.g. ?studio_asset=studio/<id>.png
    studio_asset = request.values.get("studio_asset", "")
    if studio_asset and not studio_asset_exists(studio_asset):
        flash("That studio sticker could not be found. Please send it again.")
        studio_asset = ""

    def show_form():
        return render_template(
            "artist/create_sticker.html",
            user=user,
            categories=categories,
            studio_asset=studio_asset,
            form=request.values
        )

    if request.method == "POST":

        name = request.form.get("name")
        description = request.form.get("description")
        price = request.form.get("price")
        category_id = request.form.get("category_id")
        image = request.files.get("image")
        has_upload = bool(image and image.filename)

        if not name or not price or not category_id or not (has_upload or studio_asset):
            flash("Please fill in all required fields.")
            return show_form()

        # An uploaded file wins over the studio sticker.
        if has_upload:
            filename = secure_filename(image.filename)

            if not filename:
                flash("Invalid image file.")
                return show_form()

            upload_folder = os.path.join(
                app.static_folder,
                "uploads"
            )

            os.makedirs(upload_folder, exist_ok=True)

            image.save(
                os.path.join(upload_folder, filename)
            )
        else:
            filename = claim_studio_asset(studio_asset)

        sticker = Sticker(
            name=name,
            description=description,
            price=float(price),
            image=filename,
            artist_id=artist.id,
            category_id=int(category_id)
        )

        db.session.add(sticker)
        db.session.commit()

        flash("Sticker published successfully!")
        return redirect(url_for("artist_dashboard"))

    return show_form()

@app.route("/artist/sticker/edit/<int:sticker_id>", methods=["GET", "POST"])
@app.route("/edit-sticker/<int:sticker_id>", methods=["GET", "POST"])
def edit_sticker(sticker_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    user = User.query.get(session["user_id"])

    if user.role != "artist":
        flash("Access denied.")
        return redirect(url_for("profile"))

    artist = Artist.query.filter_by(user_id=user.id).first()

    if not artist:
        flash("Artist profile not found.")
        return redirect(url_for("profile"))

    sticker = Sticker.query.get_or_404(sticker_id)

    # Make sure this artist owns the sticker
    if sticker.artist_id != artist.id:
        flash("You can only edit your own stickers.")
        return redirect(url_for("artist_dashboard"))

    categories = Category.query.all()

    if request.method == "POST":
        sticker.name = request.form.get("name")
        sticker.description = request.form.get("description")
        sticker.price = float(request.form.get("price"))
        sticker.category_id = int(request.form.get("category_id"))

        image = request.files.get("image")

        if image and image.filename:
            filename = secure_filename(image.filename)

            upload_folder = os.path.join(
                app.static_folder,
                "uploads"
            )

            os.makedirs(upload_folder, exist_ok=True)

            image.save(
                os.path.join(upload_folder, filename)
            )

            sticker.image = filename

        db.session.commit()

        flash("Sticker updated successfully!")
        return redirect(url_for("artist_dashboard"))

    return render_template(
        "artist/edit_sticker.html",
        user=user,
        artist=artist,
        sticker=sticker,
        categories=categories
    )

@app.route("/delete-sticker/<int:sticker_id>", methods=["POST"])
def delete_sticker(sticker_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = User.query.get(session["user_id"])

    if user.role != "artist":
        flash("Access denied.")
        return redirect(url_for("profile"))

    artist = Artist.query.filter_by(user_id=user.id).first()

    if not artist:
        flash("Artist profile not found.")
        return redirect(url_for("profile"))

    sticker = Sticker.query.get_or_404(sticker_id)

    if sticker.artist_id != artist.id:
        flash("You can only delete your own stickers.")
        return redirect(url_for("artist_dashboard"))

    # Keep order history intact: purchased stickers can't be deleted.
    if Purchase.query.filter_by(sticker_id=sticker.id).first():
        flash("This sticker has been purchased, so it can't be deleted. Edit it instead.")
        return redirect(url_for("artist_dashboard"))

    Wishlist.query.filter_by(sticker_id=sticker.id).delete()
    db.session.delete(sticker)
    db.session.commit()

    flash("Sticker deleted successfully!")
    return redirect(url_for("artist_dashboard"))

@app.route("/wishlist/toggle/<int:sticker_id>", methods=["POST"])
def toggle_wishlist(sticker_id):
    if "user_id" not in session:
        flash("Please log in to save stickers to your wishlist.")
        return redirect(url_for("login"))

    user = User.query.get_or_404(session["user_id"])
    sticker = Sticker.query.get_or_404(sticker_id)

    existing_item = Wishlist.query.filter_by(
        user_id=user.id,
        sticker_id=sticker.id
    ).first()

    if existing_item:
        db.session.delete(existing_item)
        flash("Sticker removed from your wishlist.")
    else:
        db.session.add(
            Wishlist(user_id=user.id, sticker_id=sticker.id)
        )
        flash("Sticker added to your wishlist.")

    db.session.commit()
    return redirect(request.referrer or url_for("shop"))

@app.route("/logout")
def logout():
    session.clear()          # Remove all session data
    flash("Logged out successfully!")
    return redirect(url_for("home"))

if __name__ == "__main__":
   
    app.run(debug=True)
