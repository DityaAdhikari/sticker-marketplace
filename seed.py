from app import app
from models import db, Artist, Category, Sticker

with app.app_context():
    db.create_all()


    # --- Categories ---
    categories = [
        Category(name="Anime", icon="fa-solid fa-face-smile"),
        Category(name="Gaming", icon="fa-solid fa-gamepad"),
        Category(name="Nature", icon="fa-solid fa-leaf"),
        Category(name="Kathmandu", icon="fa-solid fa-hat-cowboy"),
        Category(name="Minimal", icon="fa-solid fa-circle"),
        Category(name="Quotes", icon="fa-solid fa-quote-left"),
        Category(name="Pop Culture", icon="fa-solid fa-skull-crossbones"),
        Category(name="Animals", icon="fa-solid fa-paw"),
        Category(name="Travel", icon="fa-solid fa-plane"),
    ]
    db.session.add_all(categories)
    db.session.commit()

    # --- Artists ---
    artists = [
        Artist(name="San", handle="@art_by_san", bio="Illustrator blending street art with pop culture.", avatar="artist1.jpg"),
        Artist(name="Sunar Designs", handle="@sunar_designs", bio="Bold line work inspired by Japanese woodblock prints.", avatar="artist2.jpg"),
        Artist(name="Nepal Illustrates", handle="@nepal_illustrates", bio="Capturing Kathmandu's streets and temples.", avatar="artist3.jpg"),
        Artist(name="Void Creates", handle="@void.creates", bio="Space and sci-fi themed sticker art.", avatar="artist4.jpg"),
        Artist(name="Illustrate KTM", handle="@illustrate.ktm", bio="Cute animal characters with a local twist.", avatar="artist5.jpg"),
        Artist(name="The Wandering Brush", handle="@the_wanderingbrush", bio="Mountain and landscape line art.", avatar="artist6.jpg"),
    ]
    db.session.add_all(artists)
    db.session.commit()

    # --- Stickers ---
    stickers = [
        Sticker(name="Cool Cat", price=199, image="cat.jpg", rating=4.9, review_count=86,
                artist_id=artists[0].id, category_id=categories[0].id),
        Sticker(name="Great Wave", price=149, image="catoverthinker.jpg", rating=4.8, review_count=64,
                artist_id=artists[1].id, category_id=categories[4].id),
        Sticker(name="KTM Streets", price=199, image="I Am Sorry Sticker.jpg", rating=5.0, review_count=92,
                artist_id=artists[2].id, category_id=categories[3].id),
        Sticker(name="Space Drift", price=179, image="stick it up stickers _ Cat On Fire, Burn Madafaka Sticker.jpg", rating=4.9, review_count=77,
                artist_id=artists[3].id, category_id=categories[6].id),
        Sticker(name="Cozy Fox", price=149, image="stickers_anime_5_cat_fan_sticker.jpg", rating=4.8, review_count=53,
                artist_id=artists[4].id, category_id=categories[7].id),
        Sticker(name="Himalaya", price=199, image="cat.jpg", rating=4.9, review_count=68,
                artist_id=artists[5].id, category_id=categories[8].id),
    ]
    db.session.add_all(stickers)
    db.session.commit()

    print("Seed complete: categories, artists, and stickers added.")

   