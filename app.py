from werkzeug.utils import secure_filename
import os

from flask import Flask, render_template, request, redirect, url_for, flash, session
from models import db, Sticker, Artist, Category

from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Sticker, Artist, Category
import os



app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-fallback-key")


ADMIN_EMAIL = "adhikari2186@gmail.com"

app.config["SQLALCHEMY_DATABASE_URI"] = (
    "mysql+pymysql://root:@localhost:3307/sticker_site"
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

with app.app_context():
   
    db.create_all()

@app.context_processor
def inject_categories():
    return dict(nav_categories=Category.query.all())

@app.route("/")
def home():
      
    stickers = Sticker.query.limit(6).all()
    categories = Category.query.all()
    return render_template("index.html", stickers=stickers, categories=categories)

@app.route("/shop")
def shop():
    category_name = request.args.get('category')
    if category_name:
        stickers = Sticker.query.join(Category).filter(Category.name == category_name).all()
    else:
        stickers = Sticker.query.all()
    return render_template("shop.html", stickers=stickers)

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
    ).all()

    return render_template(
        "artist/profile.html",
        artist=artist,
        stickers=stickers
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

    if session.get("user_id"):
        return redirect(url_for("home"))

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password_hash, password):

            session["user_id"] = user.id
            session["user_name"] = user.name

            flash("Welcome back!")
            return redirect(url_for("home"))

        flash("Invalid email or password.")

    return render_template("login.html")

    if session.get("user_id"):
        return redirect(url_for("home"))
@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]

        existing_user = User.query.filter_by(email=email).first()

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

    user = User.query.get(session["user_id"])

    return render_template(
        "profile/profile.html",
        user=user,
        saved_count=0,
        wishlist_count=0,
        purchased_count=0,
        created_count=0
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

    if user.role != "artist":
        flash("Access denied.")
        return redirect(url_for("profile"))

    artist = Artist.query.filter_by(user_id=user.id).first()

    if not artist:
        flash("Artist profile not found.")
        return redirect(url_for("profile"))

    stickers = Sticker.query.filter_by(artist_id=artist.id).all()

    return render_template(
        "artist/dashboard.html",
        user=user,
        artist=artist,
        stickers=stickers
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

    if request.method == "POST":

        name = request.form.get("name")
        description = request.form.get("description")
        price = request.form.get("price")
        category_id = request.form.get("category_id")
        image = request.files.get("image")

        if not name or not price or not category_id or not image:
            flash("Please fill in all required fields.")
            return render_template(
                "artist/create_sticker.html",
                user=user,
                categories=categories
            )

        filename = secure_filename(image.filename)

        if not filename:
            flash("Invalid image file.")
            return render_template(
                "artist/create_sticker.html",
                user=user,
                categories=categories
            )

        upload_folder = os.path.join(
            app.static_folder,
            "uploads"
        )

        os.makedirs(upload_folder, exist_ok=True)

        image.save(
            os.path.join(upload_folder, filename)
        )

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

    return render_template(
        "artist/create_sticker.html",
        user=user,
        categories=categories
    )

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

    db.session.delete(sticker)
    db.session.commit()

    flash("Sticker deleted successfully!")
    return redirect(url_for("artist_dashboard"))


@app.route("/logout")
def logout():
    session.clear()          # Remove all session data
    flash("Logged out successfully!")
    return redirect(url_for("home"))

if __name__ == "__main__":
   
    app.run(debug=True)
