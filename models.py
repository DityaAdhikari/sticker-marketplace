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
    def live_sticker_count(self):
        return sum(1 for sticker in self.stickers if sticker.is_live)

    @property
    def display_bio(self):
        return (self.user.bio if self.user else None) or self.bio

    @property
    def profile_image(self):
        return self.user.profile_image if self.user else None

    @property
    def location(self):
        if not self.user:
            return None
        privacy = self.user.privacy_preferences
        if privacy and not privacy.show_location:
            return None
        return self.user.location


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

    # Stickers from before admin review existed have no review row and
    # count as approved.
    @property
    def status(self):
        return self.review.status if self.review else "approved"

    @property
    def is_live(self):
        return self.status == "approved"


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


class NotificationPreference(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        unique=True,
        nullable=False
    )

    new_followers = db.Column(db.Boolean, default=True, nullable=False)
    sticker_likes = db.Column(db.Boolean, default=True, nullable=False)
    order_updates = db.Column(db.Boolean, default=True, nullable=False)
    followed_artist_updates = db.Column(db.Boolean, default=True, nullable=False)
    stickernest_announcements = db.Column(db.Boolean, default=True, nullable=False)

    user = db.relationship(
        "User",
        backref=db.backref("notification_preferences", uselist=False)
    )


class PrivacyPreference(db.Model):
    """What a user shows on their public artist page. Its own table so the
    existing `user` table doesn't need altering."""

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        unique=True,
        nullable=False
    )

    show_location = db.Column(db.Boolean, default=True, nullable=False)

    user = db.relationship(
        "User",
        backref=db.backref("privacy_preferences", uselist=False)
    )


class StickerReview(db.Model):
    """Admin approval for a sticker. Artists suggest a price; the admin
    approves it (setting the final price) or rejects it with a note."""

    sticker_id = db.Column(
        db.Integer,
        db.ForeignKey("sticker.id"),
        primary_key=True
    )

    # pending, approved or rejected
    status = db.Column(db.String(20), default="pending", nullable=False, index=True)

    proposed_price = db.Column(db.Float, nullable=False)

    admin_note = db.Column(db.String(300), nullable=True)

    submitted_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    reviewed_at = db.Column(db.DateTime, nullable=True)

    sticker = db.relationship(
        "Sticker",
        backref=db.backref(
            "review",
            uselist=False,
            cascade="all, delete-orphan"
        )
    )


class CartItem(db.Model):
    """A sticker in a signed-in user's cart. Prices are read from the
    sticker at checkout, never stored here."""

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True
    )

    sticker_id = db.Column(
        db.Integer,
        db.ForeignKey("sticker.id", ondelete="CASCADE"),
        nullable=False
    )

    quantity = db.Column(db.Integer, default=1, nullable=False)

    added_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "sticker_id",
            name="unique_user_cart_sticker"
        ),
    )

    user = db.relationship("User", backref="cart_items")
    sticker = db.relationship("Sticker")


class Order(db.Model):
    """One checkout attempt. Amounts are whole paisa (Rs. 1 = 100 paisa) so
    totals add up exactly and match what Khalti expects."""

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True
    )

    # pending, paid or failed
    status = db.Column(db.String(20), default="pending", nullable=False, index=True)

    # khalti or esewa
    payment_method = db.Column(db.String(20), nullable=False)

    total_paisa = db.Column(db.Integer, nullable=False)

    # Khalti pidx or eSewa transaction_uuid: how we find the order when
    # the provider sends the customer back.
    payment_reference = db.Column(db.String(100), unique=True, nullable=True)

    # Provider's own transaction id, once paid
    transaction_id = db.Column(db.String(100), nullable=True)

    failure_reason = db.Column(db.String(255), nullable=True)

    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    paid_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", backref="orders")

    items = db.relationship(
        "OrderItem",
        backref="order",
        cascade="all, delete-orphan"
    )

    @property
    def total(self):
        return self.total_paisa / 100

    @property
    def item_count(self):
        return sum(item.quantity for item in self.items)


class OrderItem(db.Model):
    """A sticker line in an order, with its name and price copied at
    checkout so history stays correct if the sticker changes later."""

    id = db.Column(db.Integer, primary_key=True)

    order_id = db.Column(
        db.Integer,
        db.ForeignKey("order.id"),
        nullable=False,
        index=True
    )

    sticker_id = db.Column(
        db.Integer,
        db.ForeignKey("sticker.id", ondelete="SET NULL"),
        nullable=True
    )

    sticker_name = db.Column(db.String(100), nullable=False)

    sticker_image = db.Column(db.String(200), nullable=True)

    unit_price_paisa = db.Column(db.Integer, nullable=False)

    quantity = db.Column(db.Integer, nullable=False)

    sticker = db.relationship("Sticker")

    @property
    def unit_price(self):
        return self.unit_price_paisa / 100

    @property
    def line_total(self):
        return self.unit_price_paisa * self.quantity / 100


class PaymentCheck(db.Model):
    """One time we asked Khalti / eSewa for an order's status. Kept as an
    audit trail so admins can reconcile orders against the provider."""

    id = db.Column(db.Integer, primary_key=True)

    order_id = db.Column(
        db.Integer,
        db.ForeignKey("order.id"),
        nullable=False,
        index=True
    )

    # return (provider redirect), customer ("check status") or admin
    source = db.Column(db.String(20), nullable=False)

    admin_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=True
    )

    # What the provider said, e.g. "Completed", "COMPLETE", "Error"
    provider_status = db.Column(db.String(40), nullable=False)

    # The order's status after the check
    order_status = db.Column(db.String(20), nullable=False)

    note = db.Column(db.String(255), nullable=True)

    checked_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        nullable=False
    )

    admin = db.relationship("User")

    order = db.relationship(
        "Order",
        backref=db.backref(
            "checks",
            order_by="PaymentCheck.id.desc()",
            cascade="all, delete-orphan"
        )
    )
