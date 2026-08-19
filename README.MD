# StickerNest – Sticker Marketplace Management System

##  Overview

StickerNest is a web-based sticker marketplace management system developed as a DBMS project. The system manages users, artists, stickers, categories, shopping carts, and orders through a centralized relational database.

The project demonstrates practical database concepts such as entities, relationships, constraints, CRUD operations, SQL queries, normalization, and transaction management.

##  Objectives

- Manage users and artists efficiently.
- Store and manage sticker products and categories.
- Allow users to browse and purchase stickers.
- Manage shopping carts and orders.
- Allow administrators to manage users, products, categories, and orders.
- Demonstrate practical database management concepts.

##  Main Modules

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

##  Database

The system uses a relational database to store and manage:

- Users
- Artists
- Stickers
- Categories
- Cart Items
- Orders
- Order Details

Primary keys and foreign keys are used to maintain relationships and data integrity.

##  Technologies Used

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

## sticker-marketplace/
│
├── app.py
├── requirements.txt
├── README.md
│
├── templates/
├── static/
│
└── instance/
    └── database.db

Future Improvements
Online payment integration
Product reviews and ratings
Advanced search and filtering
Inventory management
Sales reports and analytics
Contributors
Ditya Adhikari
Sadhana Gautam
Kendra Pokhrel
##  Installation

### 1. Clone the repository

```bash
git clone <your-repository-url>
cd sticker-marketplace
