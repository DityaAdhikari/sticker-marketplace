from typing import Union

from werkzeug import Response
from werkzeug.utils import secure_filename
import os

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, make_response
from models import db, User, Sticker, Artist, Category, Wishlist ,Purchase, StickerPhoto, StickerSpec, Follow
from studio_api import studio_api, studio_asset_exists, claim_studio_asset, save_upload, remove_upload

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


# Home page "Featured Stickers": two full rows of five.
FEATURED_LIMIT = 10

# Thumbnails in static/images/category/thumbs/ (made from the full-size
# sticker art in static/images/category/). Unlisted categories show their icon.
CATEGORY_IMAGES = {
    "Animals": "animals.webp",
    "Anime": "anime.webp",
    "Gaming": "gaming.webp",
    "Kathmandu": "kathmandu.webp",
    "Minimal": "minimal.webp",
    "Nature": "nature.webp",
    "Pop Culture": "pop-culture.webp",
    "Quotes": "quotes.webp",
    "Travel": "travel.webp",
}


# Sticker page: extra photos from other angles, and "You may also like"
MAX_EXTRA_PHOTOS = 4
SIMILAR_LIMIT = 5


def save_sticker_details(sticker, form, files):
    """Save the optional product details and extra photos from the create /
    edit sticker forms. Returns how many photo uploads were skipped."""
    material = (form.get("material") or "").strip()[:120] or None
    dimensions = (form.get("dimensions") or "").strip()[:60] or None
    finish = (form.get("finish") or "").strip()[:60] or None

    if material or dimensions or finish or sticker.spec:
        if not sticker.spec:
            sticker.spec = StickerSpec()
        sticker.spec.material = material
        sticker.spec.dimensions = dimensions
        sticker.spec.finish = finish

    remove_ids = set(form.getlist("remove_photo"))
    for photo in list(sticker.photos):
        if str(photo.id) in remove_ids:
            # Only delete files this feature saved, never a shared image
            if photo.filename.startswith("angles/"):
                remove_upload(photo.filename)
            sticker.photos.remove(photo)

    skipped = 0
    for file in files.getlist("photos"):
        if not file or not file.filename:
            continue
        if len(sticker.photos) >= MAX_EXTRA_PHOTOS:
            skipped += 1
            continue
        filename = save_upload(file, "angles")
        if not filename:
            skipped += 1
            continue
        sticker.photos.append(StickerPhoto(filename=filename))

    for position, photo in enumerate(sticker.photos):
        photo.position = position

    return skipped


def category_summaries():
    """Every category A-Z with its sticker count and thumbnail."""
    rows = (
        db.session.query(Category, func.count(Sticker.id))
        .outerjoin(Sticker, Sticker.category_id == Category.id)
        .group_by(Category.id)
        .order_by(Category.name)
        .all()
    )
    return [
        {
            "category": category,
            "count": count,
            "image": CATEGORY_IMAGES.get(category.name),
        }
        for category, count in rows
    ]


# Shop and search load this many stickers at a time; more load on scroll.
SHOP_PAGE_SIZE = 20


def render_sticker_list(query, title, active_category=None, search=None):
    """Render the shop page, or with ?partial=1 just the next batch of cards
    (used by the infinite scroll in static/js/main.js)."""
    page = max(1, request.args.get("page", 1, type=int))
    total = query.count()
    stickers = (
        query.order_by(Sticker.id.desc())
        .offset((page - 1) * SHOP_PAGE_SIZE)
        .limit(SHOP_PAGE_SIZE)
        .all()
    )

    next_url = None
    if page * SHOP_PAGE_SIZE < total:
        args = {k: v for k, v in request.args.items() if k not in ("page", "partial")}
        next_url = url_for(request.endpoint, page=page + 1, **args)

    context = dict(
        stickers=stickers,
        like_counts=like_counts_for(stickers),
        liked_ids=current_liked_ids(),
    )

    if request.args.get("partial"):
        response = make_response(render_template("components/sticker_grid_items.html", **context))
        response.headers["X-Next-Page"] = next_url or ""
        return response

    return render_template(
        "shop.html",
        title=title,
        total=total,
        next_url=next_url,
        categories=category_summaries(),
        all_count=Sticker.query.count(),
        active_category=active_category,
        search=search,
        **context
    )


def like_counts_for(stickers):
    """Map sticker id -> number of likes (wishlist saves)."""
    if not stickers:
        return {}
    return dict(
        db.session.query(Wishlist.sticker_id, func.count(Wishlist.id))
        .filter(Wishlist.sticker_id.in_([s.id for s in stickers]))
        .group_by(Wishlist.sticker_id)
        .all()
    )


def followed_artist_ids():
    """Ids of artists the signed-in user follows."""
    if "user_id" not in session:
        return set()
    return {
        follow.artist_id
        for follow in Follow.query.filter_by(user_id=session["user_id"])
    }


def current_liked_ids():
    """Ids of stickers the signed-in user has liked."""
    if "user_id" not in session:
        return set()
    return {
        item.sticker_id
        for item in Wishlist.query.filter_by(user_id=session["user_id"])
    }


@app.context_processor
def inject_navbar():
    # The navbar's account menu needs the signed-in user's role and photo.
    nav_user = None
    if session.get("user_id"):
        nav_user = User.query.get(session["user_id"])

    return dict(
        nav_categories=Category.query.order_by(Category.name).all(),
        nav_user=nav_user
    )

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
        .limit(FEATURED_LIMIT)
        .all()
    )

    liked_ids = current_liked_ids()

    categories = category_summaries()

    return render_template(
        "index.html",
        featured=featured,
        liked_ids=liked_ids,
        followed_ids=followed_artist_ids(),
        categories=categories
    )

@app.route("/shop")
def shop():
    category_name = request.args.get("category")
    if category_name:
        query = Sticker.query.join(Category).filter(Category.name == category_name)
        return render_sticker_list(query, category_name, active_category=category_name)

    return render_sticker_list(Sticker.query, "All Stickers")
@app.route("/sticker/<int:sticker_id>")
def sticker_detail(sticker_id):
    sticker = Sticker.query.get_or_404(sticker_id)

    # Main image first, then any extra angles the artist uploaded
    gallery = [sticker.image] + [photo.filename for photo in sticker.photos]

    # "You may also like": same category first, then more from the artist
    similar = (
        Sticker.query
        .filter(Sticker.category_id == sticker.category_id, Sticker.id != sticker.id)
        .order_by(Sticker.id.desc())
        .limit(SIMILAR_LIMIT)
        .all()
    )
    if len(similar) < SIMILAR_LIMIT:
        taken = {sticker.id, *(s.id for s in similar)}
        similar += (
            Sticker.query
            .filter(Sticker.artist_id == sticker.artist_id, Sticker.id.notin_(taken))
            .order_by(Sticker.id.desc())
            .limit(SIMILAR_LIMIT - len(similar))
            .all()
        )

    like_counts = like_counts_for([sticker, *similar])

    return render_template(
        "sticker_detail.html",
        sticker=sticker,
        gallery=gallery,
        similar=similar,
        like_counts=like_counts,
        liked_ids=current_liked_ids()
    )

@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    query = Sticker.query.filter(Sticker.name.ilike(f"%{q}%"))
    title = f"Results for “{q}”" if q else "All Stickers"
    return render_sticker_list(query, title, search=q)

@app.route("/artists")
def artists():
    # The artist directory was removed; artists are found through their stickers.
    return redirect(url_for("home"))


@app.route("/artists/<int:artist_id>/follow", methods=["POST"])
def toggle_follow(artist_id):
    # Called with fetch() by the Follow buttons; a plain form post redirects back.
    wants_json = request.headers.get("X-Requested-With") == "fetch"

    if "user_id" not in session:
        if wants_json:
            return jsonify(error="login required", login_url=url_for("login")), 401
        flash("Please log in to follow artists.")
        return redirect(url_for("login"))

    artist = Artist.query.get_or_404(artist_id)

    if artist.user_id == session["user_id"]:
        if wants_json:
            return jsonify(error="You can't follow yourself."), 400
        flash("You can't follow yourself.")
        return redirect(request.referrer or url_for("home"))

    existing = Follow.query.filter_by(
        user_id=session["user_id"],
        artist_id=artist.id
    ).first()

    if existing:
        db.session.delete(existing)
        following = False
    else:
        db.session.add(Follow(user_id=session["user_id"], artist_id=artist.id))
        following = True

    db.session.commit()
    followers = Follow.query.filter_by(artist_id=artist.id).count()

    if wants_json:
        return jsonify(following=following, followers=followers)

    flash(f"You're now following {artist.display_name}." if following else f"You unfollowed {artist.display_name}.")
    return redirect(request.referrer or url_for("artist_profile", artist_id=artist.id))


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
        is_owner=artist.user_id is not None and artist.user_id == session.get("user_id"),
        followers_count=Follow.query.filter_by(artist_id=artist.id).count(),
        is_following=artist.id in followed_artist_ids()
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

    # Newest saves first; counts are total likes from every user
    wishlist_items = Wishlist.query.filter_by(
        user_id=user.id
    ).order_by(Wishlist.id.desc()).all()
    wishlist_like_counts = like_counts_for([item.sticker for item in wishlist_items])

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

    # Artists this user follows, most recently followed first
    following = [
        follow.artist
        for follow in Follow.query.filter_by(user_id=user.id).order_by(Follow.id.desc())
    ]

    return render_template(
    "profile/profile.html",
    user=user,
    wishlist_items=wishlist_items,
    wishlist_like_counts=wishlist_like_counts,
    created_stickers=created_stickers,
    purchases=purchases,
    following=following,
    following_count=len(following),
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
            form=request.values,
            max_photos=MAX_EXTRA_PHOTOS
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
        skipped = save_sticker_details(sticker, request.form, request.files)
        db.session.commit()

        flash("Sticker published successfully!")
        if skipped:
            flash(f"{skipped} extra photo(s) skipped: use PNG, JPG or WebP, up to {MAX_EXTRA_PHOTOS} photos.")
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

        skipped = save_sticker_details(sticker, request.form, request.files)
        db.session.commit()

        flash("Sticker updated successfully!")
        if skipped:
            flash(f"{skipped} extra photo(s) skipped: use PNG, JPG or WebP, up to {MAX_EXTRA_PHOTOS} photos.")
        return redirect(url_for("artist_dashboard"))

    return render_template(
        "artist/edit_sticker.html",
        user=user,
        artist=artist,
        sticker=sticker,
        categories=categories,
        max_photos=MAX_EXTRA_PHOTOS
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
    # The heart button calls this with fetch() to like/unlike without a page
    # reload; a plain form post (no JavaScript) still redirects back.
    wants_json = request.headers.get("X-Requested-With") == "fetch"

    if "user_id" not in session:
        if wants_json:
            return jsonify(error="login required", login_url=url_for("login")), 401
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
        liked = False
    else:
        db.session.add(
            Wishlist(user_id=user.id, sticker_id=sticker.id)
        )
        liked = True

    db.session.commit()

    if wants_json:
        count = Wishlist.query.filter_by(sticker_id=sticker.id).count()
        return jsonify(liked=liked, count=count)

    flash("Sticker added to your wishlist." if liked else "Sticker removed from your wishlist.")
    return redirect(request.referrer or url_for("shop"))

@app.route("/logout")
def logout():
    session.clear()          # Remove all session data
    flash("Logged out successfully!")
    return redirect(url_for("home"))

if __name__ == "__main__":
   
    app.run(debug=True)
