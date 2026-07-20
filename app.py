from flask import Flask, render_template, request
from models import db, Sticker, Artist, Category

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

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

@app.route("/login")
def login():
    return render_template("login.html")

@app.route("/register")
def register():
    return render_template("register.html")



if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)