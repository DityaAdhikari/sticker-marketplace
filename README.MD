# StickerNest – Sticker Marketplace Management System

## Overview

StickerNest is a web-based sticker marketplace management system developed as a DBMS project. The system manages users, artists, stickers, categories, shopping carts, and orders through a centralized relational database.

The project demonstrates practical database concepts such as entities, relationships, constraints, CRUD operations, SQL queries, normalization, and transaction management.

## Objectives

- Manage users and artists efficiently.
- Store and manage sticker products and categories.
- Allow users to browse and purchase stickers.
- Manage shopping carts and orders.
- Allow administrators to manage users, products, categories, and orders.
- Demonstrate practical database management concepts.

## Main Modules

### User Management
- User registration and login
- User profile management

### Artist Management
- Artist information management
- Sticker design management
- Product management

### Sticker Management
- Add, update, delete, and view stickers
- Categorize sticker products

### Shopping Cart
- Add stickers to cart
- Update quantities
- Remove items from cart

### Order Management
- Place orders
- Store order details
- Track order status
- View order history

### Admin Management
- Manage users
- Manage artists
- Manage stickers
- Manage categories
- Manage orders

### Print Studio
- Design A5 sticker sheets in the browser (React app in `frontend/`)
- Background removal, die-cut outlines, shadows, backdrops and text stickers
- Exact millimetre sizing, duplicate and layer ordering
- Print-ready PDF (exact A5 size) and 300 DPI PNG export, per-sticker PNG download
- Save sheets to your account (MySQL); artists can send a sticker to Create Sticker to sell it

## Database

The system uses a relational database to store and manage:

- Users
- Artists
- Stickers
- Categories
- Cart Items
- Orders
- Order Details

Primary keys and foreign keys are used to maintain relationships and data integrity.

## Technologies Used

- **Backend:** Python / Flask
- **Database:** MySQL
- **ORM:** SQLAlchemy
- **Frontend:** HTML, CSS, JavaScript
- **Database Driver:** PyMySQL
- **API Testing:** Postman
- **Version Control:** Git & GitHub

## DBMS Concepts Demonstrated

- Relational Database
- ER Model
- Primary Keys
- Foreign Keys
- Constraints
- Relationships
- Normalization
- CRUD Operations
- SQL Queries
- Joins
- Aggregate Functions
- Transactions
- Database Security
- ORM

## Project Structure

```text
sticker-marketplace/
│
├── app.py
├── requirements.txt
├── README.MD
│
├── templates/
├── static/
│
└── instance/

## Running the Print Studio

The studio is a React app served by Flask at `/studio`.

```bash
# Development: run Flask and Vite side by side
python app.py                 # Flask on http://localhost:5000
cd frontend && npm run dev    # Studio on http://localhost:5173/studio/
```

Open the studio at `localhost` (not `127.0.0.1`) so it shares the Flask login
cookie. Vite proxies `/api` and `/static` to Flask.

```bash
# Production: build once, then Flask serves it at /studio
cd frontend && npm run build
```

Set `DATABASE_URL` to use a different database than the default local MySQL.

