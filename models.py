from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.mysql import MEDIUMTEXT
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

    # Artists with an account show their live user profile, so edits on
    # the profile page appear on the public artist page too.
    @property
    def display_name(self):
        return self.user.name if self.user else self.name

    @property
    def display_bio(self):
        return (self.user.bio if self.user else None) or self.bio

    @property
    def profile_image(self):
        return self.user.profile_image if self.user else None

    @property
    def location(self):
        return self.user.location if self.user else None


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


# Extra details live in their own tables so the existing `sticker` table
# doesn't need altering; db.create_all() adds these on startup.

class StickerPhoto(db.Model):
    """Extra photos of a sticker from other angles (up to 4)."""

    id = db.Column(db.Integer, primary_key=True)

    sticker_id = db.Column(
        db.Integer,
        db.ForeignKey("sticker.id"),
        nullable=False,
        index=True
    )

    filename = db.Column(db.String(255), nullable=False)

    position = db.Column(db.Integer, nullable=False, default=0)

    sticker = db.relationship(
        "Sticker",
        backref=db.backref(
            "photos",
            order_by="StickerPhoto.position",
            cascade="all, delete-orphan"
        )
    )


class StickerSpec(db.Model):
    """Optional product details shown under "About this product"."""

    sticker_id = db.Column(
        db.Integer,
        db.ForeignKey("sticker.id"),
        primary_key=True
    )

    material = db.Column(db.String(120), nullable=True)

    dimensions = db.Column(db.String(60), nullable=True)

    finish = db.Column(db.String(60), nullable=True)

    sticker = db.relationship(
        "Sticker",
        backref=db.backref(
            "spec",
            uselist=False,
            cascade="all, delete-orphan"
        )
    )


class Follow(db.Model):
    """A user following an artist."""

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True
    )

    artist_id = db.Column(
        db.Integer,
        db.ForeignKey("artist.id"),
        nullable=False,
        index=True
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "artist_id",
            name="unique_user_follow_artist"
        ),
    )

    user = db.relationship("User", backref="follows")
    artist = db.relationship("Artist", backref="followers")


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


class Design(db.Model):
    """A sticker sheet saved from the React print studio."""

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True
    )

    title = db.Column(db.String(120), nullable=False)

    # Sheet layout as JSON. Images are stored as upload URLs, not inline.
    data = db.Column(
        db.Text().with_variant(MEDIUMTEXT(), "mysql"),
        nullable=False
    )

    thumbnail = db.Column(db.String(255), nullable=True)

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False
    )

    user = db.relationship("User", backref="designs")
