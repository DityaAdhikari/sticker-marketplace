from typing import Union

from werkzeug import Response
from werkzeug.utils import secure_filename
import os

from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, make_response, abort
from models import db, User, Sticker, Artist, Category, Wishlist ,Purchase, StickerPhoto, StickerSpec, Follow, NotificationPreference, PrivacyPreference, StickerReview
from studio_api import studio_api, studio_asset_exists, claim_studio_asset, save_upload, remove_upload

from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func
from dotenv import load_dotenv
import secrets

import uuid
from datetime import datetime

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
SEARCH_ARTIST_LIMIT = 8


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


def sticker_is_live():
    """Filter for stickers shoppers can see: approved by an admin, or from
    before reviews existed (no review row)."""
    hidden = db.select(StickerReview.sticker_id).where(
        StickerReview.status != "approved"
    )
    return Sticker.id.notin_(hidden)


def category_summaries():
    """Every category A-Z with its sticker count and thumbnail."""
    rows = (
        db.session.query(Category, func.count(Sticker.id))
        .outerjoin(
            Sticker,
            db.and_(Sticker.category_id == Category.id, sticker_is_live())
        )
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


def render_sticker_list(query, title, active_category=None, search=None, matched_artists=None):
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
        all_count=Sticker.query.filter(sticker_is_live()).count(),
        active_category=active_category,
        search=search,
        matched_artists=matched_artists or [],
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
        .filter(Artist.user_id.isnot(None), sticker_is_live())
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
        query = Sticker.query.join(Category).filter(
            Category.name == category_name, sticker_is_live()
        )
        return render_sticker_list(query, category_name, active_category=category_name)

    return render_sticker_list(Sticker.query.filter(sticker_is_live()), "All Stickers")
@app.route("/sticker/<int:sticker_id>")
def sticker_detail(sticker_id):
    sticker = Sticker.query.get_or_404(sticker_id)

    # Unapproved stickers are only visible to their artist and admins
    if not sticker.is_live:
        viewer = db.session.get(User, session["user_id"]) if "user_id" in session else None
        is_owner = viewer and sticker.artist.user_id == viewer.id
        if not (is_owner or (viewer and viewer.role == "admin")):
            abort(404)

    # Main image first, then any extra angles the artist uploaded
    gallery = [sticker.image] + [photo.filename for photo in sticker.photos]

    # "You may also like": same category first, then more from the artist
    similar = (
        Sticker.query
        .filter(Sticker.category_id == sticker.category_id, Sticker.id != sticker.id, sticker_is_live())
        .order_by(Sticker.id.desc())
        .limit(SIMILAR_LIMIT)
        .all()
    )
    if len(similar) < SIMILAR_LIMIT:
        taken = {sticker.id, *(s.id for s in similar)}
        similar += (
            Sticker.query
            .filter(Sticker.artist_id == sticker.artist_id, Sticker.id.notin_(taken), sticker_is_live())
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
    query = Sticker.query.filter(sticker_is_live())
    matched_artists = []

    if q:
        like = f"%{q}%"

        # Match the sticker, its category, or its artist. Artists with an
        # account show their account name, so search that too.
        query = (
            query.join(Artist, Sticker.artist_id == Artist.id)
            .outerjoin(User, Artist.user_id == User.id)
            .join(Category, Sticker.category_id == Category.id)
            .filter(
                db.or_(
                    Sticker.name.ilike(like),
                    Category.name.ilike(like),
                    Artist.name.ilike(like),
                    Artist.handle.ilike(like),
                    User.name.ilike(like)
                )
            )
        )

        matched_artists = (
            Artist.query.outerjoin(User, Artist.user_id == User.id)
            .filter(
                db.or_(
                    Artist.name.ilike(like),
                    Artist.handle.ilike(like),
                    User.name.ilike(like)
                )
            )
            .order_by(Artist.name)
            .limit(SEARCH_ARTIST_LIMIT)
            .all()
        )

    title = f"Results for “{q}”" if q else "All Stickers"
    return render_sticker_list(query, title, search=q, matched_artists=matched_artists)

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

    stickers = Sticker.query.filter(
        Sticker.artist_id == artist.id, sticker_is_live()
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

    user = User.query.get_or_404(session["user_id"])

    if user.role == "admin":
        flash("Admin accounts cannot apply as artists.")
        return redirect(url_for("profile"))

    if user.role == "artist":
        flash("You are already an artist.")
        return redirect(url_for("profile"))

    # Check whether an Artist profile already exists
    existing_artist = Artist.query.filter_by(
        user_id=user.id
    ).first()

    if existing_artist:
        user.role = "artist"
        user.artist_status = "approved"
    else:
        artist = Artist(
            user_id=user.id,
            name=user.name,
            handle="@" + user.name.lower().replace(" ", "_"),
            bio=user.bio,
            avatar=user.profile_image
        )

        db.session.add(artist)

        user.role = "artist"
        user.artist_status = "approved"

    db.session.commit()

    flash("Congratulations! You are now a StickerNest artist.")
    return redirect(url_for("profile"))


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

            # Assign admin role to the designated admin account.
            if user.email.lower() == ADMIN_EMAIL.lower():
                user.role = "admin"
                db.session.commit()

            # Start a fresh session.
            session.clear()
            session["user_id"] = user.id
            session["user_name"] = user.name

            flash("Welcome back!")

            if user.role == "admin":
                return redirect(url_for("admin_dashboard"))

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
    wishlist_items = (
        Wishlist.query.join(Sticker)
        .filter(Wishlist.user_id == user.id, sticker_is_live())
        .order_by(Wishlist.id.desc())
        .all()
    )
    wishlist_like_counts = like_counts_for([item.sticker for item in wishlist_items])

    artist = Artist.query.filter_by(user_id=user.id).first()

    created_stickers = []
    if artist:
        created_stickers = Sticker.query.filter(
            Sticker.artist_id == artist.id, sticker_is_live()
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

            original_name = secure_filename(file.filename)
            extension = os.path.splitext(original_name)[1].lower()
            filename = f"{uuid.uuid4().hex}{extension}"

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

        # The settings page reuses this form; send the user back there
        if request.form.get("next") == "settings":
            return redirect(url_for("settings", tab="profile"))

        return redirect(url_for("profile"))

    return render_template(
        "profile/edit_profile.html",
        user=user
    )

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

        # The artist's price is a suggestion; the admin sets the final
        # price when approving. Until then the sticker stays hidden.
        sticker = Sticker(
            name=name,
            description=description,
            price=float(price),
            image=filename,
            artist_id=artist.id,
            category_id=int(category_id)
        )
        sticker.review = StickerReview(proposed_price=float(price))

        db.session.add(sticker)
        skipped = save_sticker_details(sticker, request.form, request.files)
        db.session.commit()

        flash("Sticker submitted! It will appear in the shop once an admin approves it.")
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
        sticker.category_id = int(request.form.get("category_id"))

        # Any edit goes back to the admin for review. The live price only
        # changes when the admin approves the suggested one.
        proposed_price = float(request.form.get("price"))
        if not sticker.review:
            sticker.review = StickerReview(proposed_price=proposed_price)
        sticker.review.status = "pending"
        sticker.review.proposed_price = proposed_price
        sticker.review.admin_note = None
        sticker.review.submitted_at = datetime.utcnow()
        sticker.review.reviewed_at = None

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

        flash("Sticker updated and sent for admin review.")
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
    elif not sticker.is_live:
        abort(404)
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

@app.route("/admin/dashboard")
def admin_dashboard():

    # 1. Check whether the user is logged in
    if "user_id" not in session:
        return redirect(url_for("login"))

    # 2. Find the logged-in user
    admin = db.session.get(User, session["user_id"])

    # 3. Verify administrator permission
    if not admin or admin.role != "admin":
        flash("Access denied.")
        return redirect(url_for("home"))

    # 4. Count database records
    total_users = User.query.count()
    total_artists = Artist.query.count()
    total_stickers = Sticker.query.filter(sticker_is_live()).count()
    total_purchases = Purchase.query.count()
    pending_stickers = StickerReview.query.filter_by(status="pending").count()

    # 5. Latest activity for the "Recent activity" panels
    recent_users = User.query.order_by(User.id.desc()).limit(5).all()
    recent_stickers = Sticker.query.order_by(Sticker.id.desc()).limit(5).all()

    # 6. Send statistics to the dashboard
    return render_template(
        "admin/dashboard.html",
        total_users=total_users,
        total_artists=total_artists,
        total_stickers=total_stickers,
        total_purchases=total_purchases,
        pending_stickers=pending_stickers,
        recent_users=recent_users,
        recent_stickers=recent_stickers
    )


STICKER_STATUSES = ["pending", "approved", "rejected"]


def current_admin():
    """Return the logged-in admin, or None if the visitor isn't one."""
    if "user_id" not in session:
        return None

    user = db.session.get(User, session["user_id"])

    if not user or user.role != "admin":
        return None

    return user


@app.route("/admin/artists")
def admin_artists():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if not current_admin():
        flash("Access denied.")
        return redirect(url_for("home"))

    search = request.args.get("search", "").strip()

    query = Artist.query.outerjoin(User, Artist.user_id == User.id)

    # Search by artist name, handle, account name or email
    if search:
        like = f"%{search}%"
        query = query.filter(
            db.or_(
                Artist.name.ilike(like),
                Artist.handle.ilike(like),
                User.name.ilike(like),
                User.email.ilike(like)
            )
        )

    artists = query.order_by(Artist.id.desc()).all()

    artist_ids = [a.id for a in artists]
    sticker_counts = {}
    follower_counts = {}

    if artist_ids:
        sticker_counts = dict(
            db.session.query(Sticker.artist_id, func.count(Sticker.id))
            .filter(Sticker.artist_id.in_(artist_ids))
            .group_by(Sticker.artist_id)
            .all()
        )
        follower_counts = dict(
            db.session.query(Follow.artist_id, func.count(Follow.id))
            .filter(Follow.artist_id.in_(artist_ids))
            .group_by(Follow.artist_id)
            .all()
        )

    return render_template(
        "admin/artists.html",
        artists=artists,
        search=search,
        sticker_counts=sticker_counts,
        follower_counts=follower_counts
    )


@app.route("/admin/stickers")
def admin_stickers():
    if "user_id" not in session:
        return redirect(url_for("login"))

    if not current_admin():
        flash("Access denied.")
        return redirect(url_for("home"))

    search = request.args.get("search", "").strip()
    selected_category = request.args.get("category", type=int)

    # Opens on the review queue; "all" shows every sticker
    selected_status = request.args.get("status", "pending")
    if selected_status not in STICKER_STATUSES + ["all"]:
        selected_status = "pending"

    query = Sticker.query.join(Artist)

    if selected_status == "approved":
        query = query.filter(sticker_is_live())
    elif selected_status != "all":
        query = query.filter(
            Sticker.id.in_(
                db.select(StickerReview.sticker_id).where(
                    StickerReview.status == selected_status
                )
            )
        )

    # Search by sticker or artist name
    if search:
        like = f"%{search}%"
        query = query.filter(
            db.or_(
                Sticker.name.ilike(like),
                Artist.name.ilike(like)
            )
        )

    if selected_category:
        query = query.filter(Sticker.category_id == selected_category)

    stickers = query.order_by(Sticker.id.desc()).all()

    status_counts = dict(
        db.session.query(StickerReview.status, func.count(StickerReview.sticker_id))
        .group_by(StickerReview.status)
        .all()
    )
    status_counts["approved"] = Sticker.query.filter(sticker_is_live()).count()
    status_counts["all"] = Sticker.query.count()

    sticker_ids = [s.id for s in stickers]
    purchase_counts = {}

    if sticker_ids:
        purchase_counts = dict(
            db.session.query(Purchase.sticker_id, func.count(Purchase.id))
            .filter(Purchase.sticker_id.in_(sticker_ids))
            .group_by(Purchase.sticker_id)
            .all()
        )

    return render_template(
        "admin/stickers.html",
        stickers=stickers,
        categories=Category.query.order_by(Category.name).all(),
        search=search,
        selected_category=selected_category,
        selected_status=selected_status,
        status_counts=status_counts,
        like_counts=like_counts_for(stickers),
        purchase_counts=purchase_counts
    )


@app.route("/admin/stickers/<int:sticker_id>/approve", methods=["POST"])
def admin_approve_sticker(sticker_id):
    """Approve a sticker at the admin's price. Also used to change the
    price of a sticker that's already live."""
    if "user_id" not in session:
        return redirect(url_for("login"))

    if not current_admin():
        flash("Access denied.")
        return redirect(url_for("home"))

    sticker = Sticker.query.get_or_404(sticker_id)
    price = request.form.get("price", type=float)

    if price is None or price <= 0:
        flash("Please enter a price greater than 0.")
        return redirect(request.referrer or url_for("admin_stickers"))

    was_live = sticker.is_live
    sticker.price = round(price, 2)

    if not sticker.review:
        sticker.review = StickerReview(proposed_price=sticker.price)
    sticker.review.status = "approved"
    sticker.review.admin_note = None
    sticker.review.reviewed_at = datetime.utcnow()

    db.session.commit()

    if was_live:
        flash(f"Price of \"{sticker.name}\" updated to Rs. {sticker.price:g}.")
    else:
        flash(f"\"{sticker.name}\" approved at Rs. {sticker.price:g}. It's now live in the shop.")
    return redirect(request.referrer or url_for("admin_stickers"))


@app.route("/admin/stickers/<int:sticker_id>/reject", methods=["POST"])
def admin_reject_sticker(sticker_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    if not current_admin():
        flash("Access denied.")
        return redirect(url_for("home"))

    sticker = Sticker.query.get_or_404(sticker_id)
    note = request.form.get("note", "").strip()[:300]

    if not sticker.review:
        sticker.review = StickerReview(proposed_price=sticker.price)
    sticker.review.status = "rejected"
    sticker.review.admin_note = note or None
    sticker.review.reviewed_at = datetime.utcnow()

    db.session.commit()

    flash(f"\"{sticker.name}\" rejected. The artist can edit and resubmit it.")
    return redirect(request.referrer or url_for("admin_stickers"))


@app.route("/admin/stickers/<int:sticker_id>/delete", methods=["POST"])
def admin_delete_sticker(sticker_id):
    if "user_id" not in session:
        return redirect(url_for("login"))

    if not current_admin():
        flash("Access denied.")
        return redirect(url_for("home"))

    sticker = Sticker.query.get_or_404(sticker_id)

    # Same rule as artists: keep order history intact.
    if Purchase.query.filter_by(sticker_id=sticker.id).first():
        flash("This sticker has been purchased, so it can't be deleted.")
        return redirect(request.referrer or url_for("admin_stickers"))

    Wishlist.query.filter_by(sticker_id=sticker.id).delete()
    db.session.delete(sticker)
    db.session.commit()

    flash(f"Sticker \"{sticker.name}\" deleted.")
    return redirect(request.referrer or url_for("admin_stickers"))

@app.route("/admin/users")
def admin_users():
    if "user_id" not in session:
        return redirect(url_for("login"))

    admin = db.session.get(User, session["user_id"])

    if not admin or admin.role != "admin":
        flash("Access denied.")
        return redirect(url_for("home"))

    search = request.args.get("search", "").strip()
    selected_role = request.args.get("role", "").strip().lower()

    query = User.query

    # Search by name or email
    if search:
        query = query.filter(
            db.or_(
                User.name.ilike(f"%{search}%"),
                User.email.ilike(f"%{search}%")
            )
        )

    # Filter by account role
    if selected_role in ["customer", "artist", "admin"]:
        query = query.filter(User.role == selected_role)
    else:
        selected_role = ""

    users = query.order_by(User.id.desc()).all()

    return render_template(
        "admin/users.html",
        users=users,
        search=search,
        selected_role=selected_role
    )

SETTINGS_TABS = ["profile", "notifications", "security", "privacy"]

@app.route("/settings")
def settings():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = db.session.get(User, session["user_id"])

    if not user:
        session.clear()
        return redirect(url_for("login"))

    # Get this user's notification preferences
    notification_preferences = NotificationPreference.query.filter_by(
        user_id=user.id
    ).first()

    # Create default preferences if they don't exist
    if not notification_preferences:
        notification_preferences = NotificationPreference(
            user_id=user.id
        )
        db.session.add(notification_preferences)
        db.session.commit()

    # Open the tab the user was on before saving
    active_tab = request.args.get("tab", "profile")
    if active_tab not in SETTINGS_TABS:
        active_tab = "profile"

    return render_template(
        "settings.html",
        user=user,
        notification_preferences=notification_preferences,
        privacy_preferences=user.privacy_preferences,
        active_tab=active_tab,
        min_password_length=MIN_PASSWORD_LENGTH,
        is_admin_email=user.email.lower() == ADMIN_EMAIL.lower()
    )

@app.route("/settings/notifications", methods=["POST"])
def save_notification_preferences():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = db.session.get(User, session["user_id"])

    if not user:
        session.clear()
        return redirect(url_for("login"))

    preferences = NotificationPreference.query.filter_by(
        user_id=user.id
    ).first()

    if not preferences:
        preferences = NotificationPreference(user_id=user.id)
        db.session.add(preferences)

    preferences.new_followers = "new_followers" in request.form
    preferences.sticker_likes = "sticker_likes" in request.form
    preferences.order_updates = "order_updates" in request.form
    preferences.followed_artist_updates = "followed_artist_updates" in request.form
    preferences.stickernest_announcements = "stickernest_announcements" in request.form

    db.session.commit()

    flash("Notification preferences saved successfully!")

    return redirect(url_for("settings", tab="notifications"))

@app.route("/settings/password", methods=["POST"])
def change_password():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = db.session.get(User, session["user_id"])

    if not user:
        session.clear()
        return redirect(url_for("login"))

    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not check_password_hash(user.password_hash, current_password):
        flash("Your current password is incorrect.")
    elif len(new_password) < MIN_PASSWORD_LENGTH:
        flash(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    elif new_password != confirm_password:
        flash("New passwords do not match.")
    elif check_password_hash(user.password_hash, new_password):
        flash("Your new password must be different from the current one.")
    else:
        user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        flash("Password updated successfully!")

    return redirect(url_for("settings", tab="security"))

@app.route("/settings/email", methods=["POST"])
def change_email():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = db.session.get(User, session["user_id"])

    if not user:
        session.clear()
        return redirect(url_for("login"))

    new_email = request.form.get("email", "").strip().lower()
    current_password = request.form.get("current_password", "")

    # Admin rights are tied to ADMIN_EMAIL at login, so that address can't
    # be moved away from or claimed through this form.
    if user.email.lower() == ADMIN_EMAIL.lower():
        flash("The administrator email can't be changed here.")
    elif not check_password_hash(user.password_hash, current_password):
        flash("Your current password is incorrect.")
    elif not new_email or "@" not in new_email:
        flash("Please enter a valid email address.")
    elif new_email == user.email.lower():
        flash("That's already your email address.")
    elif new_email == ADMIN_EMAIL.lower() or find_user_by_email(new_email):
        flash("Email already exists.")
    else:
        user.email = new_email
        db.session.commit()
        flash("Email updated successfully!")

    return redirect(url_for("settings", tab="security"))

@app.route("/settings/privacy", methods=["POST"])
def save_privacy_preferences():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = db.session.get(User, session["user_id"])

    if not user:
        session.clear()
        return redirect(url_for("login"))

    preferences = user.privacy_preferences

    if not preferences:
        preferences = PrivacyPreference(user_id=user.id)
        db.session.add(preferences)

    preferences.show_location = "show_location" in request.form

    db.session.commit()

    flash("Privacy settings saved successfully!")

    return redirect(url_for("settings", tab="privacy"))

@app.route("/settings/export")
def export_account_data():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user = db.session.get(User, session["user_id"])

    if not user:
        session.clear()
        return redirect(url_for("login"))

    notifications = user.notification_preferences
    privacy = user.privacy_preferences

    data = {
        "account": {
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "bio": user.bio,
            "location": user.location,
        },
        "wishlist": [
            {"sticker_id": item.sticker_id, "sticker": item.sticker.name}
            for item in user.wishlist_items
        ],
        "purchases": [
            {
                "sticker_id": purchase.sticker_id,
                "sticker": purchase.sticker.name,
                "price": purchase.sticker.price,
                "status": purchase.status,
                "date": purchase.purchase_date.isoformat(),
            }
            for purchase in user.purchases
        ],
        "following": [
            {"artist_id": follow.artist_id, "artist": follow.artist.display_name}
            for follow in user.follows
        ],
        "notification_preferences": {
            "new_followers": notifications.new_followers,
            "sticker_likes": notifications.sticker_likes,
            "order_updates": notifications.order_updates,
            "followed_artist_updates": notifications.followed_artist_updates,
            "stickernest_announcements": notifications.stickernest_announcements,
        } if notifications else None,
        "privacy_preferences": {
            "show_location": privacy.show_location if privacy else True,
        },
    }

    response = jsonify(data)
    response.headers["Content-Disposition"] = (
        "attachment; filename=stickernest-account-data.json"
    )
    return response

@app.route("/logout")
def logout():
    session.clear()          # Remove all session data
    flash("Logged out successfully!")
    return redirect(url_for("home"))

if __name__ == "__main__":
   
    app.run(debug=True)
