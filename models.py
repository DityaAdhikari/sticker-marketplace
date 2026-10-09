from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(120), nullable=False)

    email = db.Column(db.String(120), unique=True, nullable=False)

    password_hash = db.Column(db.String(255), nullable=False)

    role = db.Column(db.String(20), default="customer")

    artist_status = db.Column(
        db.String(20),
        default="none"
    )

    profile_image = db.Column(db.String(255), nullable=True)

    bio = db.Column(db.String(255), nullable=True)

    location = db.Column(db.String(100), nullable=True)

    artist = db.relationship(
        "Artist",
        backref="user",
        uselist=False
    )


class Artist(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=True
    )

    name = db.Column(db.String(100), nullable=False)

    handle = db.Column(db.String(100))

    bio = db.Column(db.String(300))

    avatar = db.Column(db.String(200))

    stickers = db.relationship(
        "Sticker",
        backref="artist",
        lazy=True
    )


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )

    icon = db.Column(db.String(50))

    stickers = db.relationship(
        "Sticker",
        backref="category",
        lazy=True
    )

class Sticker(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    price = db.Column(db.Float, nullable=False)
    image = db.Column(db.String(200), nullable=False)
    rating = db.Column(db.Float, default=0.0)
    review_count = db.Column(db.Integer, default=0)
    artist_id = db.Column(db.Integer, db.ForeignKey("artist.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"), nullable=False)

    
class Wishlist(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    sticker_id = db.Column(
        db.Integer,
        db.ForeignKey("sticker.id"),
        nullable=False
    )

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "sticker_id",
            name="unique_user_wishlist_sticker"
        ),
    )

    user = db.relationship("User", backref="wishlist_items")
    sticker = db.relationship("Sticker")


class Purchase(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    sticker_id = db.Column(
        db.Integer,
        db.ForeignKey("sticker.id"),
        nullable=False
    )

    purchase_date = db.Column(
        db.DateTime,
        default=db.func.current_timestamp(),
        nullable=False
    )

    status = db.Column(
        db.String(20),
        default="completed",
        nullable=False
    )

    user = db.relationship("User", backref="purchases")
    sticker = db.relationship("Sticker")