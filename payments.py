"""Cart, checkout, Khalti / eSewa payments and order history.

Prices always come from the database: the browser only sends which
stickers and how many. An order is marked paid only after the provider's
own server confirms the payment (Khalti lookup API / eSewa status API);
the redirect back to our site is never trusted on its own.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from sqlalchemy import func

from models import db, User, Sticker, CartItem, Order, OrderItem, Purchase, PaymentCheck
from currency import format_paisa


payments = Blueprint("payments", __name__)

MAX_QUANTITY = 20

# Khalti won't take payments under Rs. 10
KHALTI_MIN_PAISA = 1000

# Sandbox by default; set these in .env for live payments.
KHALTI_BASE_URL = os.environ.get("KHALTI_BASE_URL", "https://dev.khalti.com/api/v2/")
KHALTI_SECRET_KEY = os.environ.get("KHALTI_SECRET_KEY", "")

ESEWA_FORM_URL = os.environ.get("ESEWA_FORM_URL", "https://rc-epay.esewa.com.np/api/epay/main/v2/form")
ESEWA_STATUS_URL = os.environ.get("ESEWA_STATUS_URL", "https://rc.esewa.com.np/api/epay/transaction/status/")
ESEWA_PRODUCT_CODE = os.environ.get("ESEWA_PRODUCT_CODE", "EPAYTEST")
# eSewa's public test key; live merchants get their own.
ESEWA_SECRET_KEY = os.environ.get("ESEWA_SECRET_KEY", "8gBm/:&EnhH.1/q")


class PaymentError(Exception):
    """The provider couldn't be reached or sent back something unusable."""


def to_paisa(rupees):
    return int(round(rupees * 100))


def current_user():
    if "user_id" not in session:
        return None
    return db.session.get(User, session["user_id"])


def login_required_redirect():
    flash("Please log in to continue.")
    return redirect(url_for("login", next=request.path))


def cart_lines(user):
    """The user's cart with live prices. Stickers that were deleted,
    unlisted or sent back for review are dropped from the cart."""
    lines = []
    removed = []

    for item in CartItem.query.filter_by(user_id=user.id).order_by(CartItem.added_at):
        sticker = item.sticker
        if not sticker or not sticker.is_live:
            removed.append(sticker.name if sticker else "A sticker")
            db.session.delete(item)
            continue

        unit_paisa = to_paisa(sticker.price)
        lines.append({
            "item": item,
            "sticker": sticker,
            "quantity": item.quantity,
            "unit_paisa": unit_paisa,
            "line_paisa": unit_paisa * item.quantity,
        })

    if removed:
        db.session.commit()
        flash(f"Removed from your cart because it's no longer available: {', '.join(removed)}.")

    return lines


def buy_now_lines(user, sticker_id, quantity):
    """A single sticker for "Buy Now", priced from the database. Leaves the
    cart untouched. Returns None if it can't be bought."""
    sticker = db.session.get(Sticker, sticker_id)

    if not sticker or not sticker.is_live:
        flash("That sticker isn't available.")
        return None

    if sticker.artist.user_id == user.id:
        flash("You can't buy your own sticker.")
        return None

    quantity = max(1, min(MAX_QUANTITY, quantity or 1))
    unit_paisa = to_paisa(sticker.price)
    return [{
        "item": None,
        "sticker": sticker,
        "quantity": quantity,
        "unit_paisa": unit_paisa,
        "line_paisa": unit_paisa * quantity,
    }]


def mark_paid(order, transaction_id):
    # One provider transaction can only ever pay for one order
    if transaction_id and Order.query.filter(
        Order.id != order.id,
        Order.payment_method == order.payment_method,
        Order.transaction_id == transaction_id
    ).first():
        mark_failed(order, "This transaction was already used to pay for another order.")
        return

    # A conditional UPDATE rather than checking order.status in Python: if
    # two requests confirm the same order at once (the provider redirect
    # and a "check status" click, or an admin reconcile), the database lets
    # only one of them through, so purchases are never recorded twice.
    claimed = Order.query.filter(
        Order.id == order.id,
        Order.status != "paid"
    ).update({
        "status": "paid",
        "transaction_id": transaction_id,
        "failure_reason": None,
        "paid_at": datetime.utcnow(),
    }, synchronize_session=False)

    if not claimed:
        db.session.commit()
        return

    # Purchases power the profile "Purchased" tab and sales counts
    for line in order.items:
        if line.sticker_id:
            db.session.add(Purchase(user_id=order.user_id, sticker_id=line.sticker_id))

    # Empty the cart of what was just bought
    bought = [line.sticker_id for line in order.items if line.sticker_id]
    if bought:
        CartItem.query.filter(
            CartItem.user_id == order.user_id,
            CartItem.sticker_id.in_(bought)
        ).delete(synchronize_session=False)

    db.session.commit()


def mark_failed(order, reason):
    # Only pending orders fail; the condition is checked by the database so
    # an order paid by a request running at the same time stays paid.
    Order.query.filter(
        Order.id == order.id,
        Order.status == "pending"
    ).update({
        "status": "failed",
        "failure_reason": reason[:255],
    }, synchronize_session=False)
    db.session.commit()


def record_check(order, source, provider_status, admin=None, note=None):
    db.session.add(PaymentCheck(
        order_id=order.id,
        source=source,
        admin_id=admin.id if admin else None,
        provider_status=(provider_status or "No status")[:40],
        order_status=order.status,
        note=note[:255] if note else None
    ))
    db.session.commit()


def call_json(url, data=None, headers=None):
    """GET (or POST JSON when data is given) and return (status, body)."""
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers or {})
    if body is not None:
        req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.loads(error.read() or b"{}")
        except ValueError:
            return error.code, {}
    except (urllib.error.URLError, TimeoutError, ValueError) as error:
        raise PaymentError(f"Couldn't reach the payment provider ({error}).")


# ---------------------------------------------------------------- Khalti

def khalti_headers():
    if not KHALTI_SECRET_KEY:
        raise PaymentError("Khalti isn't configured yet (KHALTI_SECRET_KEY is missing).")
    return {"Authorization": f"Key {KHALTI_SECRET_KEY}"}


def khalti_start(order):
    user = order.user
    status, body = call_json(
        KHALTI_BASE_URL + "epayment/initiate/",
        {
            "return_url": url_for("payments.khalti_return", _external=True),
            "website_url": url_for("home", _external=True),
            "amount": order.total_paisa,
            "purchase_order_id": f"SN-{order.id}",
            "purchase_order_name": f"StickerNest order #{order.id}",
            "customer_info": {"name": user.name, "email": user.email},
        },
        khalti_headers()
    )

    if status != 200 or "payment_url" not in body:
        detail = body.get("detail") or body.get("error_key") or body
        raise PaymentError(f"Khalti couldn't start the payment: {detail}")

    order.payment_reference = body["pidx"]
    db.session.commit()
    return body["payment_url"]


def khalti_verify(order):
    status, body = call_json(
        KHALTI_BASE_URL + "epayment/lookup/",
        {"pidx": order.payment_reference},
        khalti_headers()
    )

    if status == 401:
        raise PaymentError("Khalti rejected our secret key.")

    state = body.get("status")

    if state == "Completed" and body.get("pidx") != order.payment_reference:
        mark_failed(order, "Khalti's confirmation was for a different payment.")
    elif state == "Completed" and body.get("total_amount") == order.total_paisa:
        mark_paid(order, body.get("transaction_id"))
    elif state == "Completed":
        mark_failed(order, "Paid amount didn't match the order total.")
    elif state in ("User canceled", "Expired", "Refunded", "Partially Refunded", "Failed"):
        mark_failed(order, f"Khalti: {state}")
    # Initiated / Pending: leave the order pending and check again later

    return state


# ---------------------------------------------------------------- eSewa

def esewa_amount(paisa):
    """eSewa takes rupees; the exact same string has to be signed."""
    return str(paisa // 100) if paisa % 100 == 0 else f"{paisa / 100:.2f}"


def esewa_sign(fields, names):
    message = ",".join(f"{name}={fields[name]}" for name in names)
    digest = hmac.new(ESEWA_SECRET_KEY.encode(), message.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def esewa_form(order):
    order.payment_reference = f"SN-{order.id}-{secrets.token_hex(4)}"
    db.session.commit()

    amount = esewa_amount(order.total_paisa)
    fields = {
        "amount": amount,
        "tax_amount": "0",
        "total_amount": amount,
        "transaction_uuid": order.payment_reference,
        "product_code": ESEWA_PRODUCT_CODE,
        "product_service_charge": "0",
        "product_delivery_charge": "0",
        "success_url": url_for("payments.esewa_success", _external=True),
        "failure_url": url_for("payments.esewa_failure", order_id=order.id, _external=True),
        "signed_field_names": "total_amount,transaction_uuid,product_code",
    }
    fields["signature"] = esewa_sign(fields, ["total_amount", "transaction_uuid", "product_code"])
    return fields


def esewa_verify(order):
    status, body = call_json(
        ESEWA_STATUS_URL + "?" + urllib.parse.urlencode({
            "product_code": ESEWA_PRODUCT_CODE,
            "total_amount": esewa_amount(order.total_paisa),
            "transaction_uuid": order.payment_reference,
        })
    )

    state = body.get("status")

    try:
        paid_paisa = to_paisa(float(body.get("total_amount") or 0))
    except (TypeError, ValueError):
        raise PaymentError("eSewa sent back an unreadable amount.")

    if state == "COMPLETE" and body.get("transaction_uuid") != order.payment_reference:
        mark_failed(order, "eSewa's confirmation was for a different payment.")
    elif state == "COMPLETE" and paid_paisa == order.total_paisa:
        mark_paid(order, body.get("ref_id"))
    elif state == "COMPLETE":
        mark_failed(order, "Paid amount didn't match the order total.")
    elif state in ("CANCELED", "NOT_FOUND"):
        mark_failed(order, "Payment was cancelled on eSewa.")
    elif state in ("FULL_REFUND", "PARTIAL_REFUND"):
        mark_failed(order, "eSewa refunded this payment.")
    # PENDING / AMBIGUOUS: leave pending and check again later

    return state


def verify_order(order, source, admin=None, note=None):
    """Ask the provider for the order's real status, update the order to
    match and log the check. Returns the provider's status."""
    if not order.payment_reference:
        return None

    try:
        if order.payment_method == "khalti":
            state = khalti_verify(order)
        else:
            state = esewa_verify(order)
    except PaymentError as error:
        db.session.rollback()
        record_check(order, source, "Error", admin, str(error))
        raise

    record_check(order, source, state, admin, note)
    return state


# ---------------------------------------------------------------- Cart

@payments.route("/cart")
def cart():
    user = current_user()
    if not user:
        return login_required_redirect()

    lines = cart_lines(user)

    return render_template(
        "cart.html",
        lines=lines,
        total=sum(line["line_paisa"] for line in lines) / 100,
        max_quantity=MAX_QUANTITY
    )


@payments.route("/cart/add/<int:sticker_id>", methods=["POST"])
def add_to_cart(sticker_id):
    user = current_user()
    if not user:
        return login_required_redirect()

    sticker = Sticker.query.get_or_404(sticker_id)

    if not sticker.is_live:
        abort(404)

    if sticker.artist.user_id == user.id:
        flash("You can't buy your own sticker.")
        return redirect(url_for("sticker_detail", sticker_id=sticker.id))

    quantity = max(1, min(MAX_QUANTITY, request.form.get("quantity", 1, type=int) or 1))

    item = CartItem.query.filter_by(user_id=user.id, sticker_id=sticker.id).first()
    if item:
        item.quantity = min(MAX_QUANTITY, item.quantity + quantity)
    else:
        db.session.add(CartItem(user_id=user.id, sticker_id=sticker.id, quantity=quantity))
    db.session.commit()

    flash(f"Added \"{sticker.name}\" to your cart.")
    return redirect(request.referrer or url_for("payments.cart"))


@payments.route("/cart/update/<int:item_id>", methods=["POST"])
def update_cart(item_id):
    user = current_user()
    if not user:
        return login_required_redirect()

    item = CartItem.query.filter_by(id=item_id, user_id=user.id).first_or_404()
    quantity = request.form.get("quantity", type=int)

    if not quantity or quantity < 1:
        db.session.delete(item)
    else:
        item.quantity = min(MAX_QUANTITY, quantity)
    db.session.commit()

    return redirect(url_for("payments.cart"))


@payments.route("/cart/remove/<int:item_id>", methods=["POST"])
def remove_from_cart(item_id):
    user = current_user()
    if not user:
        return login_required_redirect()

    item = CartItem.query.filter_by(id=item_id, user_id=user.id).first_or_404()
    db.session.delete(item)
    db.session.commit()

    flash("Removed from your cart.")
    return redirect(url_for("payments.cart"))


# ---------------------------------------------------------------- Checkout

@payments.route("/checkout", methods=["GET", "POST"])
def checkout():
    user = current_user()
    if not user:
        return login_required_redirect()

    # "Buy Now" checks out one sticker (?buy=<id>) without using the cart
    buy_id = request.values.get("buy", type=int)
    quantity = request.values.get("quantity", 1, type=int)

    if buy_id:
        lines = buy_now_lines(user, buy_id, quantity)
        if not lines:
            return redirect(request.referrer or url_for("shop"))
        back = url_for("payments.checkout", buy=buy_id, quantity=lines[0]["quantity"])
    else:
        lines = cart_lines(user)
        if not lines:
            flash("Your cart is empty.")
            return redirect(url_for("payments.cart"))
        back = url_for("payments.checkout")

    total_paisa = sum(line["line_paisa"] for line in lines)

    if request.method == "GET":
        return render_template(
            "checkout.html",
            lines=lines,
            total=total_paisa / 100,
            buy_now=lines[0] if buy_id else None,
            khalti_ready=bool(KHALTI_SECRET_KEY),
            khalti_min=KHALTI_MIN_PAISA / 100
        )

    method = request.form.get("payment_method")

    if method not in ("khalti", "esewa"):
        flash("Please choose Khalti or eSewa.")
        return redirect(back)

    if method == "khalti" and total_paisa < KHALTI_MIN_PAISA:
        flash(f"Khalti needs an order of at least {format_paisa(KHALTI_MIN_PAISA)}. Try eSewa or add more stickers.")
        return redirect(back)

    # The total is worked out here from database prices, never taken from
    # the form.
    order = Order(user_id=user.id, payment_method=method, total_paisa=total_paisa)
    for line in lines:
        order.items.append(OrderItem(
            sticker_id=line["sticker"].id,
            sticker_name=line["sticker"].name,
            sticker_image=line["sticker"].image,
            unit_price_paisa=line["unit_paisa"],
            quantity=line["quantity"]
        ))
    db.session.add(order)
    db.session.commit()

    try:
        if method == "khalti":
            return redirect(khalti_start(order))

        return render_template(
            "esewa_redirect.html",
            form_url=ESEWA_FORM_URL,
            fields=esewa_form(order),
            order=order
        )
    except PaymentError as error:
        mark_failed(order, str(error))
        flash(str(error))
        return redirect(url_for("payments.order_detail", order_id=order.id))


# ---------------------------------------------------------------- Provider returns

@payments.route("/payment/khalti/return")
def khalti_return():
    pidx = request.args.get("pidx", "")
    order = Order.query.filter_by(payment_method="khalti", payment_reference=pidx).first_or_404()

    try:
        verify_order(order, "return")
    except PaymentError as error:
        flash(f"{error} We'll keep checking; refresh this page in a moment.")

    return redirect(url_for("payments.order_detail", order_id=order.id))


@payments.route("/payment/esewa/success")
def esewa_success():
    try:
        data = json.loads(base64.b64decode(request.args.get("data", "")))
        names = data["signed_field_names"].split(",")
        signature_ok = hmac.compare_digest(esewa_sign(data, names), data.get("signature", ""))
    except (ValueError, KeyError, TypeError):
        abort(400)

    order = Order.query.filter_by(
        payment_method="esewa",
        payment_reference=data.get("transaction_uuid")
    ).first_or_404()

    if not signature_ok:
        flash("We couldn't verify eSewa's response. Checking with eSewa directly.")

    # The signed redirect is a hint; eSewa's status API decides.
    try:
        verify_order(order, "return", note=None if signature_ok else "Redirect signature didn't match.")
    except PaymentError as error:
        flash(f"{error} We'll keep checking; refresh this page in a moment.")

    return redirect(url_for("payments.order_detail", order_id=order.id))


@payments.route("/payment/esewa/failure/<int:order_id>")
def esewa_failure(order_id):
    user = current_user()
    if not user:
        return login_required_redirect()

    order = Order.query.filter_by(id=order_id, user_id=user.id, payment_method="esewa").first_or_404()

    # Ask eSewa rather than assuming: the customer may have paid anyway
    try:
        verify_order(order, "return")
    except PaymentError:
        pass

    if order.status == "pending":
        mark_failed(order, "Payment was cancelled on eSewa.")

    return redirect(url_for("payments.order_detail", order_id=order.id))


# ---------------------------------------------------------------- Orders

@payments.route("/orders")
def orders():
    user = current_user()
    if not user:
        return login_required_redirect()

    return render_template(
        "orders.html",
        orders=Order.query.filter_by(user_id=user.id).order_by(Order.id.desc()).all()
    )


@payments.route("/orders/<int:order_id>")
def order_detail(order_id):
    user = current_user()
    if not user:
        return login_required_redirect()

    order = Order.query.filter_by(id=order_id, user_id=user.id).first_or_404()

    return render_template("order_detail.html", order=order)


@payments.route("/orders/<int:order_id>/verify", methods=["POST"])
def verify_order_status(order_id):
    user = current_user()
    if not user:
        return login_required_redirect()

    order = Order.query.filter_by(id=order_id, user_id=user.id).first_or_404()

    if order.status != "pending":
        return redirect(url_for("payments.order_detail", order_id=order.id))

    try:
        verify_order(order, "customer")
    except PaymentError as error:
        flash(str(error))
    else:
        if order.status == "pending":
            flash("The payment is still being processed. Please check again shortly.")

    return redirect(url_for("payments.order_detail", order_id=order.id))


# ---------------------------------------------------------------- Admin

ORDER_STATUSES = ["pending", "paid", "failed"]
PAYMENT_METHODS = ["khalti", "esewa"]
ORDERS_PER_PAGE = 20

# Pending orders younger than this may still have a customer on the
# provider's page, so reconciling leaves them alone.
RECONCILE_AFTER = timedelta(minutes=15)

# Each order is one call to the provider, so keep a single run short.
RECONCILE_BATCH = 15


def current_admin():
    user = current_user()
    return user if user and user.role == "admin" else None


def admin_denied():
    if "user_id" not in session:
        return redirect(url_for("login"))
    flash("Access denied.")
    return redirect(url_for("home"))


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def stale_pending_orders():
    return Order.query.filter(
        Order.status == "pending",
        Order.created_at < datetime.utcnow() - RECONCILE_AFTER
    )


@payments.route("/admin/orders")
def admin_orders():
    if not current_admin():
        return admin_denied()

    search = request.args.get("search", "").strip()
    method = request.args.get("method", "")
    status = request.args.get("status", "")
    date_from = parse_date(request.args.get("from"))
    date_to = parse_date(request.args.get("to"))

    query = Order.query.join(User, Order.user_id == User.id)

    if search:
        # "12", "#12" and "SN-12" find order 12; anything else matches the
        # customer or a Khalti / eSewa reference.
        order_id = re.fullmatch(r"(?:#|SN-)?(\d+)", search, re.IGNORECASE)
        if order_id:
            query = query.filter(Order.id == int(order_id.group(1)))
        else:
            like = f"%{search}%"
            query = query.filter(
                db.or_(
                    User.name.ilike(like),
                    User.email.ilike(like),
                    Order.payment_reference.ilike(like),
                    Order.transaction_id.ilike(like)
                )
            )

    if method in PAYMENT_METHODS:
        query = query.filter(Order.payment_method == method)
    else:
        method = ""

    if status in ORDER_STATUSES:
        query = query.filter(Order.status == status)
    else:
        status = ""

    if date_from:
        query = query.filter(Order.created_at >= date_from)
    if date_to:
        query = query.filter(Order.created_at < date_to + timedelta(days=1))

    pagination = query.order_by(Order.id.desc()).paginate(
        page=request.args.get("page", 1, type=int),
        per_page=ORDERS_PER_PAGE,
        error_out=False
    )

    # Overview figures cover every order, not just the filtered ones
    status_counts = dict(
        db.session.query(Order.status, func.count(Order.id))
        .group_by(Order.status)
        .all()
    )
    revenue_paisa = (
        db.session.query(func.coalesce(func.sum(Order.total_paisa), 0))
        .filter(Order.status == "paid")
        .scalar()
    )

    # Kept in pagination links so changing page keeps the filters
    filters = {
        "search": search,
        "method": method,
        "status": status,
        "from": date_from.strftime("%Y-%m-%d") if date_from else "",
        "to": date_to.strftime("%Y-%m-%d") if date_to else "",
    }

    return render_template(
        "admin/orders.html",
        pagination=pagination,
        orders=pagination.items,
        filters=filters,
        active_filters={key: value for key, value in filters.items() if value},
        status_counts=status_counts,
        total_orders=sum(status_counts.values()),
        revenue=revenue_paisa / 100,
        stale_count=stale_pending_orders().count(),
        reconcile_minutes=int(RECONCILE_AFTER.total_seconds() // 60)
    )


@payments.route("/admin/orders/<int:order_id>")
def admin_order_detail(order_id):
    if not current_admin():
        return admin_denied()

    order = db.get_or_404(Order, order_id)

    customer_orders = Order.query.filter_by(user_id=order.user_id)
    customer_spent_paisa = (
        db.session.query(func.coalesce(func.sum(Order.total_paisa), 0))
        .filter(Order.user_id == order.user_id, Order.status == "paid")
        .scalar()
    )

    return render_template(
        "admin/order_detail.html",
        order=order,
        checks=order.checks[:20],
        customer_order_count=customer_orders.count(),
        customer_paid_count=customer_orders.filter_by(status="paid").count(),
        customer_spent=customer_spent_paisa / 100
    )


@payments.route("/admin/orders/<int:order_id>/verify", methods=["POST"])
def admin_verify_order(order_id):
    """Re-check any order with the provider. Pending orders get settled,
    failed ones are switched to paid if the provider says the money
    arrived, and paid ones show up refunds in the check history."""
    admin = current_admin()
    if not admin:
        return admin_denied()

    order = db.get_or_404(Order, order_id)
    back = redirect(url_for("payments.admin_order_detail", order_id=order.id))

    if not order.payment_reference:
        flash("This order never reached the payment provider, so there's nothing to check.")
        return back

    before = order.status

    try:
        state = verify_order(order, "admin", admin)
    except PaymentError as error:
        flash(str(error))
        return back

    if order.status != before:
        flash(f"Order #{order.id} changed from {before} to {order.status}. The provider reports \"{state}\".")
    else:
        flash(f"No change: the provider reports \"{state or 'no status'}\", so order #{order.id} stays {order.status}.")

    return back


@payments.route("/admin/orders/reconcile", methods=["POST"])
def admin_reconcile_orders():
    """Settle orders stuck in pending (customer closed the tab, the
    provider never redirected back, ...) by asking the provider."""
    admin = current_admin()
    if not admin:
        return admin_denied()

    # Least recently checked first, so orders the provider keeps calling
    # pending can't hold up the rest of the queue between runs.
    last_check = (
        db.session.query(PaymentCheck.order_id, func.max(PaymentCheck.checked_at).label("at"))
        .group_by(PaymentCheck.order_id)
        .subquery()
    )
    stale = (
        stale_pending_orders()
        .outerjoin(last_check, last_check.c.order_id == Order.id)
        .order_by(last_check.c.at.is_(None).desc(), last_check.c.at, Order.created_at)
        .limit(RECONCILE_BATCH)
        .all()
    )
    results = {"paid": 0, "failed": 0, "pending": 0, "error": 0}

    for order in stale:
        if not order.payment_reference:
            mark_failed(order, "The payment was never started.")
            record_check(order, "admin", "Not started", admin)
        else:
            try:
                verify_order(order, "admin", admin)
            except PaymentError:
                results["error"] += 1
                continue
        results[order.status] += 1

    if not stale:
        flash("No stuck orders to reconcile.")
        return redirect(url_for("payments.admin_orders"))

    summary = f"Checked {len(stale)} pending {'order' if len(stale) == 1 else 'orders'}: " \
              f"{results['paid']} paid, {results['failed']} failed, {results['pending']} still pending"
    if results["error"]:
        summary += f", {results['error']} couldn't reach the provider (see each order's history)"
    flash(summary + ".")

    remaining = stale_pending_orders().count() - results["pending"] - results["error"]
    if remaining > 0:
        flash(f"{remaining} more stuck {'order is' if remaining == 1 else 'orders are'} left; run reconcile again.")

    return redirect(url_for("payments.admin_orders", status="pending"))
