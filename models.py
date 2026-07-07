from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db, login_manager


class Student(db.Model, UserMixin):
    __tablename__ = 'students'

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    roll_number = db.Column(db.String(50), unique=True, nullable=False)
    department = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    address = db.Column(db.String(300), nullable=True)
    is_blocked = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    image = db.Column(db.String(200), default='default-avatar.svg')

    # Relationships
    issues = db.relationship('IssuedBook', backref='student', cascade='all, delete-orphan', lazy=True)
    requests = db.relationship('BookRequest', backref='student', cascade='all, delete-orphan', lazy=True)
    fines = db.relationship('FineRecord', backref='student', cascade='all, delete-orphan', lazy=True)
    transactions = db.relationship('Transaction', backref='student', cascade='all, delete-orphan', lazy=True)
    notifications = db.relationship('Notification', backref='student', cascade='all, delete-orphan', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        return f'student:{self.id}'

    @property
    def is_admin(self):
        return False

    @property
    def user_type(self):
        return 'Student'


class Admin(db.Model, UserMixin):
    __tablename__ = 'admins'

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    image = db.Column(db.String(200), default='default-avatar.svg')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        return f'admin:{self.id}'

    @property
    def is_admin(self):
        return True

    @property
    def user_type(self):
        return 'Admin'


class Category(db.Model):
    __tablename__ = 'categories'

    id = db.Column(db.Integer, primary_key=True)
    category_name = db.Column(db.String(120), unique=True, nullable=False)
    books = db.relationship('Book', backref='category', lazy=True)


class Book(db.Model):
    __tablename__ = 'books'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    author = db.Column(db.String(150), nullable=False)
    isbn = db.Column(db.String(50), unique=True, nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    publisher = db.Column(db.String(150), nullable=False)
    language = db.Column(db.String(50), nullable=False)
    edition = db.Column(db.String(20), nullable=False)
    total_copies = db.Column(db.Integer, default=1)
    available_copies = db.Column(db.Integer, default=1)
    shelf_number = db.Column(db.String(50), nullable=False)
    image = db.Column(db.String(200), default='default-book.png')
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    copies = db.relationship('BookCopy', backref='book', cascade='all, delete-orphan', lazy=True)
    issues = db.relationship('IssuedBook', backref='book', cascade='all, delete-orphan', lazy=True)
    requests = db.relationship('BookRequest', backref='book', cascade='all, delete-orphan', lazy=True)


class BookCopy(db.Model):
    __tablename__ = 'book_copies'

    id = db.Column(db.Integer, primary_key=True)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id'), nullable=False)
    copy_number = db.Column(db.String(50), nullable=False)  # Barcode or numeric copy e.g. "Copy-1"
    status = db.Column(db.String(30), default='Available')  # 'Available', 'Issued', 'Lost', 'Damaged'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    issues = db.relationship('IssuedBook', backref='copy', lazy=True)


class BookRequest(db.Model):
    __tablename__ = 'book_requests'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id'), nullable=False)
    request_type = db.Column(db.String(30), nullable=False)  # 'Issue', 'Renew', 'Exchange'
    status = db.Column(db.String(30), default='Pending')     # 'Pending', 'Approved', 'Rejected'
    message = db.Column(db.Text, nullable=True)             # Rejection reason or exchange info
    requested_date = db.Column(db.DateTime, default=datetime.utcnow)


class IssuedBook(db.Model):
    __tablename__ = 'issued_books'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    book_id = db.Column(db.Integer, db.ForeignKey('books.id'), nullable=False)
    book_copy_id = db.Column(db.Integer, db.ForeignKey('book_copies.id'), nullable=False)
    issue_date = db.Column(db.DateTime, default=datetime.utcnow)
    due_date = db.Column(db.DateTime, nullable=False)
    return_date = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(30), default='Issued')  # 'Issued', 'Returned', 'Renewed', 'Exchanged'
    fine_amount = db.Column(db.Float, default=0.0)

    returns = db.relationship('ReturnedBook', backref='issued_book', cascade='all, delete-orphan', lazy=True)
    fines = db.relationship('FineRecord', backref='issued_book', cascade='all, delete-orphan', lazy=True)


class ReturnedBook(db.Model):
    __tablename__ = 'returned_books'

    id = db.Column(db.Integer, primary_key=True)
    issued_book_id = db.Column(db.Integer, db.ForeignKey('issued_books.id'), nullable=False)
    return_date = db.Column(db.DateTime, default=datetime.utcnow)
    fine_charged = db.Column(db.Float, default=0.0)
    fine_status = db.Column(db.String(30), default='N/A')  # 'N/A', 'Unpaid', 'Paid'


class FineRecord(db.Model):
    __tablename__ = 'fine_records'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    issued_book_id = db.Column(db.Integer, db.ForeignKey('issued_books.id'), nullable=False)
    amount = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(30), default='Unpaid')  # 'Unpaid', 'Pending Payment', 'Paid'
    paid_date = db.Column(db.DateTime, nullable=True)


class Transaction(db.Model):
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    transaction_type = db.Column(db.String(50), nullable=False)  # 'Issue', 'Return', 'Renew', 'Exchange', 'Fine Payment'
    description = db.Column(db.Text, nullable=False)
    amount = db.Column(db.Float, default=0.0)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


class Notification(db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=True)  # NULL means for Admin
    title = db.Column(db.String(180), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(50), nullable=False)      # e.g. "admin:1" or "student:2"
    user_name = db.Column(db.String(120), nullable=False)
    user_type = db.Column(db.String(30), nullable=False)    # 'Admin' or 'Student'
    action = db.Column(db.String(100), nullable=False)
    details = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Feedback(db.Model):
    __tablename__ = 'feedbacks'

    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), nullable=False)
    feedback_type = db.Column(db.String(50), nullable=False)  # 'General', 'Book Suggestion', 'Report Damage'
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    student = db.relationship('Student', backref=db.backref('feedbacks_list', cascade='all, delete-orphan', lazy=True))



@login_manager.user_loader
def load_user(user_id):
    if not user_id:
        return None
    user_type, _, uid = user_id.partition(':')
    if not uid.isdigit():
        return None
    if user_type == 'student':
        return Student.query.get(int(uid))
    if user_type == 'admin':
        return Admin.query.get(int(uid))
    return None
