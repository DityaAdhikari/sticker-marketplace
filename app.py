

from flask import Flask, render_template, request, redirect, url_for, flash, session
from models import db, Sticker, Artist, Category

from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Sticker, Artist, Category
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-fallback-key")


app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
    "DATABASE_URL",
    "sqlite:///database.db"
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
    return render_template("artists.html", artists=artist_list)

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

@app.route("/logout")
def logout():
    session.clear()          # Remove all session data
    flash("Logged out successfully!")
    return redirect(url_for("home"))

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)