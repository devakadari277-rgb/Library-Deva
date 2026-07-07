import os
import json
import queue
from datetime import datetime, timedelta

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
    send_from_directory,
    abort,
    Response,
    jsonify,
)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func, or_

basedir = os.path.abspath(os.path.dirname(__file__))

from extensions import db, csrf
from config import Config
from forms import (
    LoginForm,
    StudentRegistrationForm,
    AdminRegistrationForm,
    BookForm,
    CategoryForm,
    IssueBookForm,
    StudentProfileForm,
    AdminProfileForm,
)
from models import (
    Student,
    Admin,
    Book,
    BookCopy,
    BookRequest,
    IssuedBook,
    ReturnedBook,
    FineRecord,
    Transaction,
    Notification,
    ActivityLog,
    Category,
)
from utils import save_image, calculate_fine, update_outstanding_fines

main = Blueprint('main', __name__)


# --- Thread-Safe Event Broker (SSE) ---
class PubSubHub:
    def __init__(self):
        self.listeners = []

    def subscribe(self):
        q = queue.Queue(maxsize=100)
        self.listeners.append(q)
        return q

    def unsubscribe(self, q):
        if q in self.listeners:
            try:
                self.listeners.remove(q)
            except ValueError:
                pass

    def publish(self, data):
        for q in list(self.listeners):
            try:
                q.put_nowait(data)
            except queue.Full:
                self.unsubscribe(q)


pubsub_hub = PubSubHub()


def publish_sync_event(event_type, details=""):
    """Publishes a synchronization signal to all connected dashboards."""
    pubsub_hub.publish({
        'type': 'SYNC',
        'event_type': event_type,
        'details': details,
        'timestamp': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    })


def create_notification(student_id, title, message):
    """Creates a database notification and broadcasts it immediately."""
    notif = Notification(student_id=student_id, title=title, message=message)
    db.session.add(notif)
    db.session.commit()
    
    # Broadcast through SSE
    pubsub_hub.publish({
        'type': 'NOTIFICATION',
        'student_id': student_id,
        'title': title,
        'message': message,
        'created_at': notif.created_at.strftime('%Y-%m-%d %H:%M:%S')
    })


def log_activity(user_id, user_name, user_type, action, details):
    """Logs system activity and broadcasts it to the Live Activity log."""
    log = ActivityLog(user_id=user_id, user_name=user_name, user_type=user_type, action=action, details=details)
    db.session.add(log)
    db.session.commit()
    
    # Broadcast to listeners
    pubsub_hub.publish({
        'type': 'ACTIVITY_LOG',
        'user_name': user_name,
        'user_type': user_type,
        'action': action,
        'details': details,
        'timestamp': log.timestamp.strftime('%H:%M:%S')
    })


# --- Admin Authorization Decorator ---
def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Access denied. Administrator privileges required.', 'danger')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function
def check_reservations(book_id):
    """Checks if there is a pending reservation for a book and notifies the next student in queue."""
    next_reserve = BookRequest.query.filter_by(
        book_id=book_id,
        request_type='Reserve',
        status='Pending'
    ).order_by(BookRequest.requested_date.asc()).first()
    
    if next_reserve:
        create_notification(
            next_reserve.student_id,
            "Reserved Book Available",
            f"The book '{next_reserve.book.title}' you reserved is now available! You can request to borrow it now."
        )
        next_reserve.status = 'Approved'
        db.session.commit()
        publish_sync_event('RESERVATION_NOTIFIED')


# --- Routing & Authentication Views ---

@main.route('/')
def home():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return send_from_directory('.', 'login.html')


@main.route('/style.css')
def root_style():
    return send_from_directory('.', 'style.css')


@main.route('/script.js')
def root_script():
    return send_from_directory('.', 'script.js')


@main.route('/login')
def login_root():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return send_from_directory('.', 'login.html')


@main.route('/register')
def register_root():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return send_from_directory('.', 'register.html')


@main.route('/student/login', methods=['GET', 'POST'])
def student_login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        student = Student.query.filter_by(email=form.email.data.lower()).first()
        if student and student.check_password(form.password.data):
            if student.is_blocked:
                flash('Your account has been blocked. Please contact the Admin.', 'danger')
                return render_template('login.html', form=form, auth_type='Student')
            login_user(student, remember=form.remember.data)
            log_activity(student.get_id(), student.full_name, 'Student', 'Login', 'Log in success')
            flash('Logged in successfully.', 'success')
            return redirect(url_for('main.dashboard'))
        flash('Invalid email or password.', 'danger')
    return render_template('login.html', form=form, auth_type='Student')


@main.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        admin = Admin.query.filter_by(email=form.email.data.lower()).first()
        if admin and admin.check_password(form.password.data):
            login_user(admin, remember=form.remember.data)
            log_activity(admin.get_id(), admin.full_name, 'Admin', 'Login', 'Log in success')
            flash('Admin logged in successfully.', 'success')
            return redirect(url_for('main.dashboard'))
        flash('Invalid email or password.', 'danger')
    return render_template('login.html', form=form, auth_type='Admin')


@main.route('/student/register', methods=['GET', 'POST'])
def student_register():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    form = StudentRegistrationForm()
    if form.validate_on_submit():
        img_name = 'default-avatar.png'
        if form.image.data:
            img_saved = save_image(form.image.data)
            if img_saved and img_saved != 'default-book.png':
                img_name = img_saved
        student = Student(
            full_name=form.full_name.data,
            email=form.email.data.lower(),
            roll_number=form.roll_number.data.strip(),
            department=form.department.data.strip(),
            phone=form.phone.data.strip(),
            address=form.address.data.strip(),
            image=img_name
        )
        student.set_password(form.password.data)
        db.session.add(student)
        db.session.commit()
        
        # Logs
        log_activity(student.get_id(), student.full_name, 'Student', 'Register', 'Self-registered student account')
        create_notification(None, "New Student Registered", f"Student {student.full_name} ({student.roll_number}) registered.")
        publish_sync_event('STUDENT_REGISTERED')
        
        flash('Registration successful. Please log in.', 'success')
        return redirect(url_for('main.student_login'))
    return render_template('register.html', form=form, auth_type='Student')


@main.route('/admin/register', methods=['GET', 'POST'])
def admin_register():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    form = AdminRegistrationForm()
    if form.validate_on_submit():
        img_name = 'default-avatar.png'
        if form.image.data:
            img_saved = save_image(form.image.data)
            if img_saved and img_saved != 'default-book.png':
                img_name = img_saved
        admin = Admin(
            full_name=form.full_name.data,
            email=form.email.data.lower(),
            image=img_name
        )
        admin.set_password(form.password.data)
        db.session.add(admin)
        db.session.commit()
        
        log_activity(admin.get_id(), admin.full_name, 'Admin', 'Register', 'Self-registered admin account')
        flash('Admin registration successful. Please log in.', 'success')
        return redirect(url_for('main.admin_login'))
    return render_template('register.html', form=form, auth_type='Admin')


# --- JSON API Endpoints for Lamp Frontends ---

@main.route('/api/login', methods=['POST'])
@csrf.exempt
def api_login():
    data = request.get_json() or {}
    email = data.get('email')
    full_name = data.get('full_name')
    password = data.get('password')
    user_type = data.get('user_type', 'Student')
    
    identifier = email or full_name
    if not identifier or not password:
        return {'success': False, 'message': 'Missing credentials'}
        
    user = None
    if user_type == 'Admin':
        user = Admin.query.filter(
            (Admin.email == identifier.lower()) | (Admin.full_name == identifier)
        ).first()
    else:
        user = Student.query.filter(
            (Student.email == identifier.lower()) | (Student.full_name == identifier)
        ).first()
        
    if user and user.check_password(password):
        if user_type == 'Student' and user.is_blocked:
            return {'success': False, 'message': 'Your account has been blocked.'}
        login_user(user)
        log_activity(user.get_id(), user.full_name, user_type, 'Login', 'API login successful')
        return {'success': True}
    return {'success': False, 'message': 'Invalid credentials'}


@main.route('/api/register', methods=['POST'])
@csrf.exempt
def api_register():
    data = request.get_json() or {}
    full_name = data.get('full_name')
    email = data.get('email')
    password = data.get('password')
    user_type = data.get('user_type', 'Student')
    
    # Extra student fields can be sent, otherwise default
    roll_number = data.get('roll_number') or f"R-{int(datetime.utcnow().timestamp())}"
    department = data.get('department', 'General')
    phone = data.get('phone', '0000000000')
    address = data.get('address', '')
    
    if not all([full_name, email, password]):
        return {'success': False, 'message': 'Missing required fields'}
        
    if Student.query.filter_by(email=email.lower()).first() or Admin.query.filter_by(email=email.lower()).first():
        return {'success': False, 'message': 'Email already registered'}
        
    if user_type == 'Admin':
        user = Admin(full_name=full_name, email=email.lower())
    else:
        if Student.query.filter_by(roll_number=roll_number).first():
            return {'success': False, 'message': 'Roll number already registered'}
        user = Student(
            full_name=full_name,
            email=email.lower(),
            roll_number=roll_number,
            department=department,
            phone=phone,
            address=address
        )
        
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    
    log_activity(user.get_id(), user.full_name, user_type, 'Register', 'API Registration successful')
    if user_type == 'Student':
        create_notification(None, "New Student Registered", f"Student {user.full_name} registered via API.")
        publish_sync_event('STUDENT_REGISTERED')
        
    return {'success': True}


@main.route('/logout')
@login_required
def logout():
    log_activity(current_user.get_id(), current_user.full_name, current_user.user_type, 'Logout', 'Logged out')
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('main.home'))


# --- Core Dashboards ---

@main.route('/dashboard')
@login_required
def dashboard():
    update_outstanding_fines()
    
    if current_user.is_admin:
        total_books = Book.query.count()
        available_books = db.session.query(func.sum(Book.available_copies)).scalar() or 0
        issued_books = IssuedBook.query.filter_by(status='Issued').count()
        returned_books = IssuedBook.query.filter_by(status='Returned').count()
        total_students = Student.query.count()
        overdue_books = IssuedBook.query.filter(
            IssuedBook.status == 'Issued',
            IssuedBook.due_date < datetime.utcnow()
        ).count()
        
        total_fine_collected = db.session.query(func.sum(FineRecord.amount)).filter_by(status='Paid').scalar() or 0.0
        pending_requests = BookRequest.query.filter_by(status='Pending').count()
        
        categories = Category.query.all()
        category_data = [{
            'label': cat.category_name,
            'count': Book.query.filter_by(category_id=cat.id).count()
        } for cat in categories]
        
        # Monthly charts
        monthly_issues = []
        monthly_returns = []
        for offset in range(5, -1, -1):
            month = datetime.utcnow().replace(day=1) - timedelta(days=offset * 30)
            month_label = month.strftime('%b %Y')
            monthly_issues.append({
                'label': month_label,
                'count': IssuedBook.query.filter(
                    func.strftime('%Y-%m', IssuedBook.issue_date) == month.strftime('%Y-%m')
                ).count(),
            })
            monthly_returns.append({
                'label': month_label,
                'count': IssuedBook.query.filter(
                    IssuedBook.return_date != None,
                    func.strftime('%Y-%m', IssuedBook.return_date) == month.strftime('%Y-%m'),
                ).count(),
            })
            
        recent_activity = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).limit(10).all()
        
        return render_template(
            'dashboard.html',
            total_books=total_books,
            available_books=available_books,
            total_issued=issued_books,
            total_returned=returned_books,
            total_students=total_students,
            overdue_books=overdue_books,
            total_fine=total_fine_collected,
            pending_requests=pending_requests,
            category_data=category_data,
            monthly_issues=monthly_issues,
            monthly_returns=monthly_returns,
            recent_activity=recent_activity
        )
    else:
        # Student Dashboard
        active_issues = IssuedBook.query.filter_by(student_id=current_user.id, status='Issued').all()
        pending_reqs = BookRequest.query.filter_by(student_id=current_user.id, status='Pending').all()
        fine_due = db.session.query(func.sum(FineRecord.amount)).filter(
            FineRecord.student_id == current_user.id,
            FineRecord.status != 'Paid'
        ).scalar() or 0.0
        
        borrow_history = IssuedBook.query.filter_by(student_id=current_user.id).order_by(IssuedBook.issue_date.desc()).limit(10).all()
        notifs = Notification.query.filter_by(student_id=current_user.id).order_by(Notification.created_at.desc()).limit(5).all()
        
        return render_template(
            'dashboard.html',
            active_issues=active_issues,
            pending_requests_list=pending_reqs,
            fine_due=fine_due,
            borrow_history=borrow_history,
            notifications_list=notifs
        )


# --- Books Management Modules ---

@main.route('/books')
@login_required
def books():
    update_outstanding_fines()
    query = Book.query
    search = request.args.get('search', '').strip()
    if search:
        query = query.join(Category).filter(
            or_(
                Book.title.ilike(f'%{search}%'),
                Book.author.ilike(f'%{search}%'),
                Book.isbn.ilike(f'%{search}%'),
                Category.category_name.ilike(f'%{search}%')
            )
        )
    category_filter = request.args.get('category')
    if category_filter:
        query = query.join(Category).filter(Category.category_name == category_filter)
        
    books = query.order_by(Book.created_at.desc()).all()
    categories = Category.query.all()
    
    # Track student requested books
    student_requested_ids = []
    if not current_user.is_admin:
        student_requested_ids = [
            req.book_id for req in BookRequest.query.filter_by(student_id=current_user.id, status='Pending').all()
        ]
        
    return render_template(
        'books.html',
        books=books,
        categories=categories,
        student_requested_ids=student_requested_ids
    )


@main.route('/books/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_book():
    form = BookForm()
    form.category.choices = [(c.id, c.category_name) for c in Category.query.all()]
    if form.validate_on_submit():
        filename = save_image(form.image.data) if form.image.data else 'default-book.png'
        
        book = Book(
            title=form.title.data.strip(),
            author=form.author.data.strip(),
            isbn=form.isbn.data.strip(),
            category_id=form.category.data,
            publisher=form.publisher.data.strip(),
            language=form.language.data.strip(),
            edition=form.edition.data.strip(),
            total_copies=form.total_copies.data,
            available_copies=form.total_copies.data,
            shelf_number=form.shelf_number.data.strip(),
            image=filename,
            description=form.description.data.strip() if form.description.data else "",
        )
        db.session.add(book)
        db.session.commit()
        
        # Generate copies
        for idx in range(1, book.total_copies + 1):
            copy = BookCopy(
                book_id=book.id,
                copy_number=f"{book.isbn}-C{idx}",
                status='Available'
            )
            db.session.add(copy)
        db.session.commit()
        
        log_activity(current_user.get_id(), current_user.full_name, 'Admin', 'Add Book', f"Added book: '{book.title}' with {book.total_copies} copies.")
        publish_sync_event('BOOK_ADDED')
        
        flash('Book added and copies generated successfully.', 'success')
        return redirect(url_for('main.books'))
    return render_template('add_book.html', form=form)


@main.route('/books/<int:book_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_book(book_id):
    book = Book.query.get_or_404(book_id)
    form = BookForm(obj=book)
    form.category.choices = [(c.id, c.category_name) for c in Category.query.all()]
    
    if form.validate_on_submit():
        filename = book.image
        if form.image.data:
            filename = save_image(form.image.data)
            
        old_copies = book.total_copies
        new_copies = form.total_copies.data
        
        book.title = form.title.data.strip()
        book.author = form.author.data.strip()
        book.isbn = form.isbn.data.strip()
        book.category_id = form.category.data
        book.publisher = form.publisher.data.strip()
        book.language = form.language.data.strip()
        book.edition = form.edition.data.strip()
        book.shelf_number = form.shelf_number.data.strip()
        book.image = filename
        book.description = form.description.data.strip() if form.description.data else ""
        
        if new_copies > old_copies:
            # Create new copies
            diff = new_copies - old_copies
            for idx in range(old_copies + 1, new_copies + 1):
                copy = BookCopy(
                    book_id=book.id,
                    copy_number=f"{book.isbn}-C{idx}",
                    status='Available'
                )
                db.session.add(copy)
            book.available_copies += diff
            book.total_copies = new_copies
        elif new_copies < old_copies:
            # Remove available copies
            diff = old_copies - new_copies
            available_copies_list = BookCopy.query.filter_by(book_id=book.id, status='Available').all()
            if len(available_copies_list) < diff:
                flash(f'Cannot decrease total copies. {diff} copies need to be removed, but only {len(available_copies_list)} copies are currently available (not issued).', 'danger')
                return render_template('edit_book.html', form=form, book=book)
            for idx in range(diff):
                db.session.delete(available_copies_list[idx])
            book.available_copies -= diff
            book.total_copies = new_copies
            
        db.session.commit()
        log_activity(current_user.get_id(), current_user.full_name, 'Admin', 'Edit Book', f"Updated details for book: '{book.title}'.")
        publish_sync_event('BOOK_EDITED')
        
        flash('Book details updated successfully.', 'success')
        return redirect(url_for('main.books'))
    return render_template('edit_book.html', form=form, book=book)


@main.route('/books/<int:book_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_book(book_id):
    book = Book.query.get_or_404(book_id)
    # Check if any copy is issued
    issued_count = BookCopy.query.filter_by(book_id=book_id, status='Issued').count()
    if issued_count > 0:
        flash('Cannot delete book because copies of it are currently issued to students.', 'danger')
        return redirect(url_for('main.books'))
        
    title = book.title
    db.session.delete(book)
    db.session.commit()
    
    log_activity(current_user.get_id(), current_user.full_name, 'Admin', 'Delete Book', f"Deleted book: '{title}'.")
    publish_sync_event('BOOK_DELETED')
    
    flash('Book deleted successfully.', 'success')
    return redirect(url_for('main.books'))


@main.route('/categories/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_category():
    form = CategoryForm()
    if form.validate_on_submit():
        name = form.category_name.data.strip()
        if Category.query.filter_by(category_name=name).first():
            flash('Category already exists.', 'danger')
            return redirect(url_for('main.books'))
        cat = Category(category_name=name)
        db.session.add(cat)
        db.session.commit()
        
        log_activity(current_user.get_id(), current_user.full_name, 'Admin', 'Add Category', f"Added category '{name}'")
        flash('Category added successfully.', 'success')
        return redirect(url_for('main.books'))
    # If rendering inside books dashboard, otherwise flash error
    flash('Invalid input.', 'danger')
    return redirect(url_for('main.books'))


# --- Student Management Modules ---

@main.route('/students')
@login_required
@admin_required
def students_view():
    update_outstanding_fines()
    query = Student.query
    search = request.args.get('search', '').strip()
    if search:
        query = query.filter(
            or_(
                Student.full_name.ilike(f'%{search}%'),
                Student.email.ilike(f'%{search}%'),
                Student.roll_number.ilike(f'%{search}%'),
                Student.department.ilike(f'%{search}%')
            )
        )
    students = query.order_by(Student.created_at.desc()).all()
    return render_template('students.html', students=students)


@main.route('/students/add', methods=['GET', 'POST'])
@login_required
@admin_required
def add_student():
    form = StudentRegistrationForm()
    if form.validate_on_submit():
        img_name = 'default-avatar.png'
        if form.image.data:
            img_saved = save_image(form.image.data)
            if img_saved and img_saved != 'default-book.png':
                img_name = img_saved
        student = Student(
            full_name=form.full_name.data,
            email=form.email.data.lower(),
            roll_number=form.roll_number.data.strip(),
            department=form.department.data.strip(),
            phone=form.phone.data.strip(),
            address=form.address.data.strip(),
            image=img_name
        )
        student.set_password(form.password.data)
        db.session.add(student)
        db.session.commit()
        
        log_activity(current_user.get_id(), current_user.full_name, 'Admin', 'Add Student', f"Registered student '{student.full_name}' ({student.roll_number})")
        publish_sync_event('STUDENT_ADDED')
        
        flash('Student registered successfully.', 'success')
        return redirect(url_for('main.students_view'))
    return render_template('register.html', form=form, auth_type='Student', admin_creation=True)


@main.route('/students/<int:student_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_student(student_id):
    student = Student.query.get_or_404(student_id)
    form = StudentProfileForm(obj=student)
    
    if form.validate_on_submit():
        student.full_name = form.full_name.data
        student.email = form.email.data.lower()
        student.roll_number = form.roll_number.data.strip()
        student.department = form.department.data.strip()
        student.phone = form.phone.data.strip()
        student.address = form.address.data.strip()
        
        if form.new_password.data:
            student.set_password(form.new_password.data)
            
        db.session.commit()
        log_activity(current_user.get_id(), current_user.full_name, 'Admin', 'Edit Student', f"Updated details for student '{student.full_name}'")
        flash('Student details updated successfully.', 'success')
        return redirect(url_for('main.students_view'))
    return render_template('profile.html', form=form, profile_user=student)


@main.route('/students/<int:student_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_student(student_id):
    student = Student.query.get_or_404(student_id)
    name = student.full_name
    
    # Check for active issues
    active_issues = IssuedBook.query.filter_by(student_id=student_id, status='Issued').count()
    if active_issues > 0:
        flash('Cannot delete student account. Student has active issued books.', 'danger')
        return redirect(url_for('main.students_view'))
        
    db.session.delete(student)
    db.session.commit()
    
    log_activity(current_user.get_id(), current_user.full_name, 'Admin', 'Delete Student', f"Deleted student account: '{name}'")
    publish_sync_event('STUDENT_DELETED')
    
    flash('Student account deleted successfully.', 'success')
    return redirect(url_for('main.students_view'))


@main.route('/students/<int:student_id>/block', methods=['POST'])
@login_required
@admin_required
def toggle_block_student(student_id):
    student = Student.query.get_or_404(student_id)
    student.is_blocked = not student.is_blocked
    db.session.commit()
    
    status = "blocked" if student.is_blocked else "unblocked"
    log_activity(current_user.get_id(), current_user.full_name, 'Admin', 'Block Student' if student.is_blocked else 'Unblock Student', f"Student '{student.full_name}' was {status}.")
    create_notification(student.id, "Account Status Updated", f"Your account has been {status} by the Administrator.")
    publish_sync_event('STUDENT_BLOCKED')
    
    flash(f"Student account has been {status}.", 'warning' if student.is_blocked else 'success')
    return redirect(url_for('main.students_view'))


# --- Student Borrowing History (Admin View) ---
@main.route('/students/<int:student_id>/history')
@login_required
@admin_required
def student_history(student_id):
    student = Student.query.get_or_404(student_id)
    history = IssuedBook.query.filter_by(student_id=student_id).order_by(IssuedBook.issue_date.desc()).all()
    return render_template('history.html', student=student, issues=history)


# --- Library Issue / Requests Modules ---

@main.route('/requests')
@login_required
@admin_required
def admin_requests():
    reqs = BookRequest.query.order_by(BookRequest.requested_date.desc()).all()
    return render_template('requests.html', requests=reqs)


@main.route('/student/request_issue/<int:book_id>', methods=['POST'])
@login_required
def student_request_issue(book_id):
    if current_user.is_admin:
        flash('Administrators cannot request book issues.', 'danger')
        return redirect(url_for('main.books'))
        
    if current_user.is_blocked:
        flash('Your account is blocked. You cannot request books.', 'danger')
        return redirect(url_for('main.books'))
        
    book = Book.query.get_or_404(book_id)
    
    # Check if student already has a pending request or active issue for the same book
    existing_req = BookRequest.query.filter_by(student_id=current_user.id, book_id=book_id, status='Pending').first()
    if existing_req:
        flash('You already have a pending request for this book.', 'warning')
        return redirect(url_for('main.books'))
        
    existing_issue = IssuedBook.query.filter_by(student_id=current_user.id, book_id=book_id, status='Issued').first()
    if existing_issue:
        flash('You already have an active copy of this book issued.', 'warning')
        return redirect(url_for('main.books'))
        
    if book.available_copies < 1:
        flash('This book is currently out of stock. You can still place a request, but it will be approved when restocked.', 'info')
        
    req = BookRequest(
        student_id=current_user.id,
        book_id=book_id,
        request_type='Issue',
        status='Pending'
    )
    db.session.add(req)
    db.session.commit()
    
    log_activity(current_user.get_id(), current_user.full_name, 'Student', 'Request Issue', f"Requested book '{book.title}'")
    create_notification(None, "New Request Received", f"Student {current_user.full_name} requested '{book.title}'.")
    publish_sync_event('REQUEST_CREATED')
    
    flash('Book request sent successfully.', 'success')
    return redirect(url_for('main.dashboard'))


@main.route('/student/request_renew/<int:issue_id>', methods=['POST'])
@login_required
def student_request_renew(issue_id):
    if current_user.is_admin:
        flash('Administrators cannot renew books.', 'danger')
        return redirect(url_for('main.dashboard'))
        
    if current_user.is_blocked:
        flash('Your account is blocked. Renewal denied.', 'danger')
        return redirect(url_for('main.dashboard'))
        
    issue = IssuedBook.query.get_or_404(issue_id)
    if issue.student_id != current_user.id or issue.status != 'Issued':
        flash('Invalid request parameters.', 'danger')
        return redirect(url_for('main.dashboard'))
        
    # Prevent renewal if another student has reserved the book
    reserve_exists = BookRequest.query.filter(
        BookRequest.book_id == issue.book_id,
        BookRequest.request_type == 'Reserve',
        BookRequest.status == 'Pending',
        BookRequest.student_id != current_user.id
    ).first()
    if reserve_exists:
        flash('Cannot request renewal. Another student has reserved this book.', 'danger')
        return redirect(url_for('main.dashboard'))

    # Check for pending renew requests
    existing = BookRequest.query.filter(
        BookRequest.student_id == current_user.id,
        BookRequest.book_id == issue.book_id,
        BookRequest.status == 'Pending',
        BookRequest.request_type == 'Renew'
    ).first()
    if existing:
        flash('You already have a pending renewal request for this book.', 'warning')
        return redirect(url_for('main.dashboard'))
        
    req = BookRequest(
        student_id=current_user.id,
        book_id=issue.book_id,
        request_type='Renew',
        status='Pending',
        message=f"renew_issue_id:{issue.id}"
    )
    db.session.add(req)
    db.session.commit()
    
    log_activity(current_user.get_id(), current_user.full_name, 'Student', 'Request Renew', f"Requested renewal for '{issue.book.title}'")
    create_notification(None, "Renewal Request Received", f"Student {current_user.full_name} requested renewal for '{issue.book.title}'.")
    publish_sync_event('REQUEST_CREATED')
    
    flash('Renewal request sent successfully.', 'success')
    return redirect(url_for('main.dashboard'))


@main.route('/student/request_exchange', methods=['POST'])
@login_required
def request_exchange():
    if current_user.is_admin:
        flash('Administrators cannot request exchanges.', 'danger')
        return redirect(url_for('main.dashboard'))
        
    if current_user.is_blocked:
        flash('Your account is blocked. Exchange denied.', 'danger')
        return redirect(url_for('main.dashboard'))
        
    issued_id = request.form.get('issued_book_id', type=int)
    new_book_id = request.form.get('new_book_id', type=int)
    
    if not issued_id or not new_book_id:
        flash('Please select an issued book and a new book to exchange.', 'danger')
        return redirect(url_for('main.dashboard'))
        
    issued_book = IssuedBook.query.get_or_404(issued_id)
    if issued_book.student_id != current_user.id or issued_book.status != 'Issued':
        flash('Invalid exchange details.', 'danger')
        return redirect(url_for('main.dashboard'))
        
    new_book = Book.query.get_or_404(new_book_id)
    if new_book.available_copies < 1:
        flash(f"Book '{new_book.title}' is currently unavailable for exchange.", 'danger')
        return redirect(url_for('main.dashboard'))
        
    req = BookRequest(
        student_id=current_user.id,
        book_id=new_book_id,
        request_type='Exchange',
        status='Pending',
        message=f"exchange_issue_id:{issued_id}"
    )
    db.session.add(req)
    db.session.commit()
    
    log_activity(current_user.get_id(), current_user.full_name, 'Student', 'Request Exchange', f"Requested exchange: return '{issued_book.book.title}', get '{new_book.title}'")
    create_notification(None, "Exchange Request Received", f"Student {current_user.full_name} wants to exchange '{issued_book.book.title}' for '{new_book.title}'.")
    publish_sync_event('REQUEST_CREATED')
    
    flash('Exchange request submitted successfully.', 'success')
    return redirect(url_for('main.dashboard'))


@main.route('/requests/<int:req_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_request(req_id):
    req = BookRequest.query.get_or_404(req_id)
    student = Student.query.get(req.student_id)
    
    if student.is_blocked:
        flash('Cannot approve. Student is currently blocked.', 'danger')
        return redirect(url_for('main.admin_requests'))
        
    duration = request.form.get('duration', default=14, type=int)
    if duration < 1:
        duration = 14
        
    if req.request_type == 'Issue':
        # Find available copy
        copy = BookCopy.query.filter_by(book_id=req.book_id, status='Available').first()
        if not copy:
            # Maybe total copies was decreased
            flash('No copies available in library stock to issue this book.', 'danger')
            return redirect(url_for('main.admin_requests'))
            
        due_date = datetime.utcnow() + timedelta(days=duration)
        issue = IssuedBook(
            student_id=req.student_id,
            book_id=req.book_id,
            book_copy_id=copy.id,
            due_date=due_date,
            status='Issued'
        )
        copy.status = 'Issued'
        req.book.available_copies -= 1
        req.status = 'Approved'
        db.session.add(issue)
        
        # Transaction Log
        trans = Transaction(
            student_id=student.id,
            transaction_type='Issue',
            description=f"Issued book '{req.book.title}' (Copy: {copy.copy_number})"
        )
        db.session.add(trans)
        db.session.commit()
        
        create_notification(student.id, "Book Issued", f"Your request for '{req.book.title}' has been approved. Due date: {due_date.strftime('%Y-%m-%d')}.")
        log_activity(current_user.get_id(), current_user.full_name, 'Admin', 'Approve Issue', f"Approved issue of '{req.book.title}' to {student.full_name}")
        
    elif req.request_type == 'Renew':
        issue_id = int(req.message.split(':')[1])
        issue = IssuedBook.query.get_or_404(issue_id)
        
        # Calculate existing fine first
        update_outstanding_fines()
        
        issue.due_date = datetime.utcnow() + timedelta(days=duration)
        issue.status = 'Issued'  # Ensure it reset Overdue status if applicable
        req.status = 'Approved'
        
        trans = Transaction(
            student_id=student.id,
            transaction_type='Renew',
            description=f"Renewed issue for book '{req.book.title}' (Copy: {issue.copy.copy_number})"
        )
        db.session.add(trans)
        db.session.commit()
        
        create_notification(student.id, "Issue Renewed", f"Your renewal for '{req.book.title}' has been approved. New due date: {issue.due_date.strftime('%Y-%m-%d')}.")
        log_activity(current_user.get_id(), current_user.full_name, 'Admin', 'Approve Renewal', f"Renewed '{req.book.title}' for {student.full_name}")
        
    elif req.request_type == 'Return':
        issue_id = int(req.message.split(':')[1])
        issue = IssuedBook.query.get_or_404(issue_id)
        
        issue.return_date = datetime.utcnow()
        issue.status = 'Returned'
        issue.fine_amount = calculate_fine(issue.due_date, issue.return_date)
        issue.copy.status = 'Available'
        issue.book.available_copies += 1
        
        ret_book = ReturnedBook(
            issued_book_id=issue.id,
            return_date=issue.return_date,
            fine_charged=issue.fine_amount,
            fine_status='Paid' if issue.fine_amount == 0 else 'Unpaid'
        )
        db.session.add(ret_book)
        
        if issue.fine_amount > 0:
            fine_rec = FineRecord(
                student_id=issue.student_id,
                issued_book_id=issue.id,
                amount=issue.fine_amount,
                status='Unpaid'
            )
            db.session.add(fine_rec)
            
        trans = Transaction(
            student_id=issue.student_id,
            transaction_type='Return',
            description=f"Returned book '{issue.book.title}' (Copy: {issue.copy.copy_number}) via request approval"
        )
        db.session.add(trans)
        req.status = 'Approved'
        db.session.commit()
        
        create_notification(student.id, "Return Approved", f"Your return request for '{req.book.title}' has been approved. Fine charged: ₹{issue.fine_amount}.")
        log_activity(current_user.get_id(), current_user.full_name, 'Admin', 'Approve Return', f"Approved return of '{req.book.title}' from {student.full_name}")
        check_reservations(issue.book_id)

    elif req.request_type == 'Exchange':
        issue_id = int(req.message.split(':')[1])
        old_issue = IssuedBook.query.get_or_404(issue_id)
        
        # 1. Return old book
        old_issue.return_date = datetime.utcnow()
        old_issue.status = 'Returned'
        old_issue.fine_amount = calculate_fine(old_issue.due_date, old_issue.return_date)
        old_issue.copy.status = 'Available'
        old_issue.book.available_copies += 1
        check_reservations(old_issue.book_id)
        
        # Add to returned history
        ret_book = ReturnedBook(
            issued_book_id=old_issue.id,
            return_date=old_issue.return_date,
            fine_charged=old_issue.fine_amount,
            fine_status='Paid' if old_issue.fine_amount == 0 else 'Unpaid'
        )
        db.session.add(ret_book)
        
        if old_issue.fine_amount > 0:
            fine_rec = FineRecord(
                student_id=student.id,
                issued_book_id=old_issue.id,
                amount=old_issue.fine_amount,
                status='Unpaid'
            )
            db.session.add(fine_rec)
            
        trans_ret = Transaction(
            student_id=student.id,
            transaction_type='Return',
            description=f"Returned book '{old_issue.book.title}' (Copy: {old_issue.copy.copy_number}) via Exchange"
        )
        db.session.add(trans_ret)
        
        # 2. Issue new book
        new_copy = BookCopy.query.filter_by(book_id=req.book_id, status='Available').first()
        if not new_copy:
            flash(f"No copies of '{req.book.title}' are available for the exchange.", 'danger')
            db.session.rollback()
            return redirect(url_for('main.admin_requests'))
            
        due_date = datetime.utcnow() + timedelta(days=duration)
        new_issue = IssuedBook(
            student_id=req.student_id,
            book_id=req.book_id,
            book_copy_id=new_copy.id,
            due_date=due_date,
            status='Issued'
        )
        new_copy.status = 'Issued'
        req.book.available_copies -= 1
        req.status = 'Approved'
        db.session.add(new_issue)
        
        trans_iss = Transaction(
            student_id=student.id,
            transaction_type='Issue',
            description=f"Issued book '{req.book.title}' (Copy: {new_copy.copy_number}) via Exchange"
        )
        db.session.add(trans_iss)
        db.session.commit()
        
        # Notify
        submission_date_str = old_issue.return_date.strftime('%Y-%m-%d %H:%M')
        create_notification(student.id, "Exchange Completed", f"Successfully exchanged '{old_issue.book.title}' (returned/submitted on {submission_date_str}) for '{req.book.title}'. New due date: {due_date.strftime('%Y-%m-%d')}.")
        log_activity(current_user.get_id(), current_user.full_name, 'Admin', 'Exchange Book', f"Exchanged '{old_issue.book.title}' for '{req.book.title}' for {student.full_name}")
        
    db.session.commit()
    publish_sync_event('REQUEST_APPROVED')
    flash('Request approved and updated successfully.', 'success')
    return redirect(url_for('main.admin_requests'))


@main.route('/requests/<int:req_id>/reject', methods=['POST'])
@login_required
@admin_required
def reject_request(req_id):
    req = BookRequest.query.get_or_404(req_id)
    reason = request.form.get('reason', '').strip()
    
    req.status = 'Rejected'
    req.message = reason
    db.session.commit()
    
    student = Student.query.get(req.student_id)
    create_notification(student.id, "Request Rejected", f"Your request for '{req.book.title}' was rejected. Reason: {reason or 'Not specified'}.")
    log_activity(current_user.get_id(), current_user.full_name, 'Admin', 'Reject Request', f"Rejected request from {student.full_name} for '{req.book.title}'")
    
    publish_sync_event('REQUEST_REJECTED')
    flash('Request has been rejected.', 'warning')
    return redirect(url_for('main.admin_requests'))


# --- Admin Manual Actions ---

@main.route('/issue', methods=['GET', 'POST'])
@login_required
@admin_required
def issue_book():
    form = IssueBookForm()
    form.book.choices = [(b.id, f"{b.title} by {b.author} ({b.available_copies} available)") for b in Book.query.filter(Book.available_copies > 0).all()]
    form.student.choices = [(s.id, f"{s.full_name} ({s.roll_number})") for s in Student.query.filter_by(is_blocked=False).all()]
    
    if form.validate_on_submit():
        book = Book.query.get(form.book.data)
        student = Student.query.get(form.student.data)
        
        copy = BookCopy.query.filter_by(book_id=book.id, status='Available').first()
        if not copy:
            flash('No copies available to issue.', 'danger')
        else:
            due_date = datetime.utcnow() + timedelta(days=form.duration.data)
            issue = IssuedBook(
                student_id=student.id,
                book_id=book.id,
                book_copy_id=copy.id,
                due_date=due_date,
                status='Issued'
            )
            copy.status = 'Issued'
            book.available_copies -= 1
            db.session.add(issue)
            
            # Log & Transaction
            trans = Transaction(
                student_id=student.id,
                transaction_type='Issue',
                description=f"Issued book '{book.title}' (Copy: {copy.copy_number}) manually by Admin"
            )
            db.session.add(trans)
            db.session.commit()
            
            create_notification(student.id, "Book Issued", f"Book '{book.title}' was issued to you by the Admin. Due date: {due_date.strftime('%Y-%m-%d')}.")
            log_activity(current_user.get_id(), current_user.full_name, 'Admin', 'Issue Book', f"Manually issued '{book.title}' to student {student.full_name}")
            publish_sync_event('BOOK_ISSUED')
            
            flash('Book issued successfully.', 'success')
            return redirect(url_for('main.history'))
            
    return render_template('issue_book.html', form=form)


@main.route('/return/<int:issue_id>', methods=['POST'])
@login_required
@admin_required
def return_book(issue_id):
    issue = IssuedBook.query.get_or_404(issue_id)
    if issue.status == 'Returned':
        flash('Book is already marked returned.', 'warning')
        return redirect(url_for('main.history'))
        
    issue.return_date = datetime.utcnow()
    issue.status = 'Returned'
    issue.fine_amount = calculate_fine(issue.due_date, issue.return_date)
    
    issue.copy.status = 'Available'
    issue.book.available_copies += 1
    
    # Create Return Record
    ret_book = ReturnedBook(
        issued_book_id=issue.id,
        return_date=issue.return_date,
        fine_charged=issue.fine_amount,
        fine_status='Paid' if issue.fine_amount == 0 else 'Unpaid'
    )
    db.session.add(ret_book)
    
    if issue.fine_amount > 0:
        fine_rec = FineRecord(
            student_id=issue.student_id,
            issued_book_id=issue.id,
            amount=issue.fine_amount,
            status='Unpaid'
        )
        db.session.add(fine_rec)
        
    trans = Transaction(
        student_id=issue.student_id,
        transaction_type='Return',
        description=f"Returned book '{issue.book.title}' (Copy: {issue.copy.copy_number})"
    )
    db.session.add(trans)
    db.session.commit()
    
    student = Student.query.get(issue.student_id)
    submission_date_str = issue.return_date.strftime('%Y-%m-%d %H:%M')
    create_notification(student.id, "Book Returned", f"Book '{issue.book.title}' was successfully returned/submitted on {submission_date_str}. Fine charged: ₹{issue.fine_amount}.")
    log_activity(current_user.get_id(), current_user.full_name, 'Admin', 'Return Book', f"Accepted return of '{issue.book.title}' from {student.full_name}")
    publish_sync_event('BOOK_RETURNED')
    check_reservations(issue.book_id)
    
    flash(f"Book returned. Fine: ₹{issue.fine_amount}", 'success')
    return redirect(url_for('main.history'))


@main.route('/history')
@login_required
def history():
    update_outstanding_fines()
    if current_user.is_admin:
        issues = IssuedBook.query.order_by(IssuedBook.issue_date.desc()).all()
    else:
        issues = IssuedBook.query.filter_by(student_id=current_user.id).order_by(IssuedBook.issue_date.desc()).all()
    return render_template('history.html', issues=issues)


# --- Fines Management (Admin Only) ---

@main.route('/fines')
@login_required
@admin_required
def fines_view():
    update_outstanding_fines()
    fines = FineRecord.query.order_by(FineRecord.status.desc(), FineRecord.amount.desc()).all()
    active_issues = IssuedBook.query.filter_by(status='Issued').all()
    return render_template('fines.html', fines=fines, active_issues_for_fine=active_issues)


@main.route('/fines/charge', methods=['POST'])
@login_required
@admin_required
def charge_fine():
    issued_book_id = request.form.get('issued_book_id', type=int)
    amount = request.form.get('amount', type=float)
    reason = request.form.get('reason', '').strip()
    
    if not issued_book_id or amount is None or amount < 0:
        flash('Invalid fine amount or book copy selection.', 'danger')
        return redirect(url_for('main.fines_view'))
        
    issue = IssuedBook.query.get_or_404(issued_book_id)
    issue.fine_amount += amount
    
    fine_rec = FineRecord.query.filter_by(issued_book_id=issue.id).first()
    if not fine_rec:
        fine_rec = FineRecord(
            student_id=issue.student_id,
            issued_book_id=issue.id,
            amount=issue.fine_amount,
            status='Unpaid'
        )
        db.session.add(fine_rec)
    else:
        if fine_rec.status == 'Paid':
            fine_rec.status = 'Unpaid'
            fine_rec.paid_date = None
        fine_rec.amount = issue.fine_amount
        
    trans = Transaction(
        student_id=issue.student_id,
        transaction_type='Fine Charge',
        description=f"Charged manual fine of ₹{amount} on book '{issue.book.title}'. Reason: {reason or 'Manual fee assessment'}",
        amount=amount
    )
    db.session.add(trans)
    db.session.commit()
    
    create_notification(issue.student_id, "Fine Charged", f"A fine of ₹{amount} has been charged to your account for book '{issue.book.title}'. Reason: {reason or 'Manual fee assessment'}.")
    log_activity(current_user.get_id(), current_user.full_name, 'Admin', 'Charge Fine', f"Charged manual fine of ₹{amount} on {issue.student.full_name} for '{issue.book.title}'")
    publish_sync_event('FINE_CHARGED')
    
    flash(f"Successfully charged manual fine of ₹{amount} to student.", 'success')
    return redirect(url_for('main.fines_view'))


@main.route('/fines/<int:fine_id>/collect', methods=['POST'])
@login_required
@admin_required
def collect_fine(fine_id):
    fine = FineRecord.query.get_or_404(fine_id)
    fine.status = 'Paid'
    fine.paid_date = datetime.utcnow()
    
    # Update issued book fine status or returned book fine status if needed
    ret = ReturnedBook.query.filter_by(issued_book_id=fine.issued_book_id).first()
    if ret:
        ret.fine_status = 'Paid'
        
    trans = Transaction(
        student_id=fine.student_id,
        transaction_type='Fine Payment',
        description=f"Paid fine of ₹{fine.amount} for issued book ID #{fine.issued_book_id}",
        amount=fine.amount
    )
    db.session.add(trans)
    db.session.commit()
    
    student = Student.query.get(fine.student_id)
    create_notification(student.id, "Fine Paid Successfully", f"Your fine payment of ₹{fine.amount} has been verified and marked as PAID.")
    log_activity(current_user.get_id(), current_user.full_name, 'Admin', 'Collect Fine', f"Collected fine of ₹{fine.amount} from student {student.full_name}")
    publish_sync_event('FINE_COLLECTED')
    
    flash('Fine collected and payment status updated.', 'success')
    return redirect(url_for('main.fines_view'))


@main.route('/student/pay_fine/<int:fine_id>', methods=['POST'])
@login_required
def student_pay_fine(fine_id):
    if current_user.is_admin:
        flash('Admins cannot pay fines.', 'danger')
        return redirect(url_for('main.dashboard'))
        
    fine = FineRecord.query.get_or_404(fine_id)
    if fine.student_id != current_user.id:
        abort(403)
        
    fine.status = 'Pending Payment'
    db.session.commit()
    
    create_notification(None, "Fine Payment Verification", f"Student {current_user.full_name} marked fine of ₹{fine.amount} as paid. Verification required.")
    log_activity(current_user.get_id(), current_user.full_name, 'Student', 'Pay Fine', f"Submitted fine payment request of ₹{fine.amount}")
    publish_sync_event('FINE_PAYMENT_REQUEST')
    
    flash('Fine marked as paid. Waiting for administrator verification.', 'success')
    return redirect(url_for('main.dashboard'))


# --- Logs Management (Admin Only) ---

@main.route('/logs')
@login_required
@admin_required
def logs_view():
    logs = ActivityLog.query.order_by(ActivityLog.timestamp.desc()).all()
    return render_template('logs.html', logs=logs)


# --- Reports Management (Admin Only) ---

@main.route('/reports')
@login_required
@admin_required
def reports_view():
    update_outstanding_fines()
    return render_template('reports.html')


@main.route('/reports/export/<string:report_type>')
@login_required
@admin_required
def export_report(report_type):
    update_outstanding_fines()
    import csv
    from io import StringIO
    
    output = StringIO()
    writer = csv.writer(output)
    
    if report_type == 'books':
        writer.writerow(['Book ID', 'Title', 'Author', 'ISBN', 'Category', 'Total Copies', 'Available Copies', 'Shelf Number'])
        books = Book.query.all()
        for b in books:
            writer.writerow([b.id, b.title, b.author, b.isbn, b.category.category_name, b.total_copies, b.available_copies, b.shelf_number])
        filename = "book_inventory_report.csv"
        
    elif report_type == 'students':
        writer.writerow(['Student ID', 'Full Name', 'Email', 'Roll Number', 'Department', 'Phone', 'Blocked Status', 'Registered Date'])
        students = Student.query.all()
        for s in students:
            writer.writerow([s.id, s.full_name, s.email, s.roll_number, s.department, s.phone, 'Yes' if s.is_blocked else 'No', s.created_at])
        filename = "registered_students_report.csv"
        
    elif report_type == 'fines':
        writer.writerow(['Fine ID', 'Student Roll Number', 'Student Name', 'Issued Book Title', 'Fine Amount', 'Status', 'Paid Date'])
        fines = FineRecord.query.all()
        for f in fines:
            student = Student.query.get(f.student_id)
            issue = IssuedBook.query.get(f.issued_book_id)
            writer.writerow([f.id, student.roll_number, student.full_name, issue.book.title, f.amount, f.status, f.paid_date or 'N/A'])
        filename = "fines_and_overdues_report.csv"
        
    elif report_type == 'history':
        writer.writerow(['Record ID', 'Student Roll Number', 'Student Name', 'Book Title', 'Copy Barcode', 'Issue Date', 'Due Date', 'Return Date', 'Status', 'Fine Charged'])
        issues = IssuedBook.query.all()
        for i in issues:
            writer.writerow([i.id, i.student.roll_number, i.student.full_name, i.book.title, i.copy.copy_number, i.issue_date, i.due_date, i.return_date or 'N/A', i.status, i.fine_amount])
        filename = "borrowing_transactions_report.csv"
        
    else:
        abort(400)
        
    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


# --- Profile Management ---

@main.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if current_user.is_admin:
        form = AdminProfileForm(obj=current_user)
        if form.validate_on_submit():
            current_user.full_name = form.full_name.data
            current_user.email = form.email.data.lower()
            if form.image.data:
                img_name = save_image(form.image.data)
                if img_name and img_name != 'default-book.png':
                    current_user.image = img_name
            if form.new_password.data:
                current_user.set_password(form.new_password.data)
            db.session.commit()
            log_activity(current_user.get_id(), current_user.full_name, 'Admin', 'Edit Profile', 'Updated profile details')
            flash('Profile updated successfully.', 'success')
            return redirect(url_for('main.profile'))
        return render_template('profile.html', form=form)
    else:
        form = StudentProfileForm(obj=current_user)
        if form.validate_on_submit():
            # Check unique fields
            dup_email = Student.query.filter(Student.email == form.email.data.lower(), Student.id != current_user.id).first()
            if dup_email or Admin.query.filter_by(email=form.email.data.lower()).first():
                flash('Email already registered by another account.', 'danger')
                return render_template('profile.html', form=form)
                
            dup_roll = Student.query.filter(Student.roll_number == form.roll_number.data.strip(), Student.id != current_user.id).first()
            if dup_roll:
                flash('Roll number already registered by another account.', 'danger')
                return render_template('profile.html', form=form)
                
            current_user.full_name = form.full_name.data
            current_user.email = form.email.data.lower()
            current_user.roll_number = form.roll_number.data.strip()
            current_user.department = form.department.data.strip()
            current_user.phone = form.phone.data.strip()
            current_user.address = form.address.data.strip()
            
            if form.image.data:
                img_name = save_image(form.image.data)
                if img_name and img_name != 'default-book.png':
                    current_user.image = img_name
            if form.new_password.data:
                current_user.set_password(form.new_password.data)
                
            db.session.commit()
            log_activity(current_user.get_id(), current_user.full_name, 'Student', 'Edit Profile', 'Updated profile details')
            flash('Profile updated successfully.', 'success')
            return redirect(url_for('main.profile'))
        return render_template('profile.html', form=form)


# --- Settings (Placeholder logic mapped to Admin profile) ---
@main.route('/settings')
@login_required
def settings():
    return redirect(url_for('main.profile'))


# --- Notifications System ---

@main.route('/notifications')
@login_required
def notifications():
    if current_user.is_admin:
        # Admin gets notifications targeted at None (meaning general broadcast/admin updates)
        notes = Notification.query.filter_by(student_id=None).order_by(Notification.created_at.desc()).all()
    else:
        notes = Notification.query.filter_by(student_id=current_user.id).order_by(Notification.created_at.desc()).all()
    return render_template('notifications.html', notifications=notes)


@main.route('/notifications/read-all', methods=['POST'])
@login_required
def mark_all_read():
    if current_user.is_admin:
        notes = Notification.query.filter_by(student_id=None, is_read=False).all()
    else:
        notes = Notification.query.filter_by(student_id=current_user.id, is_read=False).all()
        
    for n in notes:
        n.is_read = True
    db.session.commit()
    return jsonify({'success': True})


# --- Fast Sync JSON endpoint for AJAX fallbacks ---

@main.route('/api/sync')
@login_required
def api_sync():
    update_outstanding_fines()
    if current_user.is_admin:
        pending_requests = BookRequest.query.filter_by(status='Pending').count()
        overdue_books = IssuedBook.query.filter(
            IssuedBook.status == 'Issued',
            IssuedBook.due_date < datetime.utcnow()
        ).count()
        total_fine = db.session.query(func.sum(FineRecord.amount)).filter_by(status='Paid').scalar() or 0.0
        
        # Get unread notification counts
        unread_notifs = Notification.query.filter_by(student_id=None, is_read=False).count()
        
        return jsonify({
            'success': True,
            'pending_requests': pending_requests,
            'overdue_books': overdue_books,
            'total_fine': total_fine,
            'unread_notifications': unread_notifs
        })
    else:
        # Student stats
        fine_due = db.session.query(func.sum(FineRecord.amount)).filter(
            FineRecord.student_id == current_user.id,
            FineRecord.status != 'Paid'
        ).scalar() or 0.0
        unread_notifs = Notification.query.filter_by(student_id=current_user.id, is_read=False).count()
        pending_reqs = BookRequest.query.filter_by(student_id=current_user.id, status='Pending').count()
        
        return jsonify({
            'success': True,
            'fine_due': fine_due,
            'unread_notifications': unread_notifs,
            'pending_requests': pending_reqs
        })


@main.route('/api/books/available')
@login_required
def api_available_books():
    books = Book.query.filter(Book.available_copies > 0).all()
    books_data = [{'id': b.id, 'title': b.title, 'author': b.author, 'shelf': b.shelf_number} for b in books]
    return jsonify({'success': True, 'books': books_data})


# --- Server Sent Events stream endpoint ---

@main.route('/api/events')
@login_required
def sse_events():
    def event_stream():
        q = pubsub_hub.subscribe()
        try:
            # Connect ping
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"
            while True:
                # Blocks until message enters the queue
                msg = q.get()
                yield f"data: {json.dumps(msg)}\n\n"
        except GeneratorExit:
            pass
        finally:
            pubsub_hub.unsubscribe(q)
            
    return Response(event_stream(), mimetype='text/event-stream')


# --- 15 Student Features Additional Routes ---

@main.route('/books/<int:book_id>')
@login_required
def book_detail(book_id):
    book = Book.query.get_or_404(book_id)
    student_requested = False
    if not current_user.is_admin:
        existing_req = BookRequest.query.filter_by(student_id=current_user.id, book_id=book_id, status='Pending').first()
        if existing_req:
            student_requested = True
    return render_template('book_detail.html', book=book, student_requested=student_requested)


@main.route('/borrow-requests')
@login_required
def borrow_requests_view():
    if current_user.is_admin:
        return redirect(url_for('main.admin_requests'))
    reqs = BookRequest.query.filter_by(student_id=current_user.id, request_type='Issue').order_by(BookRequest.requested_date.desc()).all()
    return render_template('borrow_requests.html', requests=reqs)


@main.route('/return-books')
@login_required
def return_requests_view():
    if current_user.is_admin:
        return redirect(url_for('main.history'))
    active_issues = IssuedBook.query.filter_by(student_id=current_user.id, status='Issued').all()
    reqs = BookRequest.query.filter_by(student_id=current_user.id, request_type='Return').order_by(BookRequest.requested_date.desc()).all()
    returned_books = ReturnedBook.query.join(IssuedBook).filter(IssuedBook.student_id == current_user.id).order_by(ReturnedBook.return_date.desc()).all()
    return render_template('return_requests.html', active_issues=active_issues, requests=reqs, returned_books=returned_books)


@main.route('/student/request_return/<int:issue_id>', methods=['POST'])
@login_required
def student_request_return(issue_id):
    if current_user.is_admin:
        flash('Admins cannot request returns.', 'danger')
        return redirect(url_for('main.dashboard'))
    issue = IssuedBook.query.get_or_404(issue_id)
    if issue.student_id != current_user.id or issue.status != 'Issued':
        flash('Invalid request parameters.', 'danger')
        return redirect(url_for('main.dashboard'))
        
    existing = BookRequest.query.filter_by(
        student_id=current_user.id,
        book_id=issue.book_id,
        request_type='Return',
        status='Pending'
    ).first()
    if existing:
        flash('You already have a pending return request for this book.', 'warning')
        return redirect(url_for('main.dashboard'))
        
    req = BookRequest(
        student_id=current_user.id,
        book_id=issue.book_id,
        request_type='Return',
        status='Pending',
        message=f"return_issue_id:{issue.id}"
    )
    db.session.add(req)
    db.session.commit()
    
    log_activity(current_user.get_id(), current_user.full_name, 'Student', 'Request Return', f"Requested return for book '{issue.book.title}'")
    create_notification(None, "Return Request Received", f"Student {current_user.full_name} requested return for '{issue.book.title}'.")
    publish_sync_event('REQUEST_CREATED')
    
    flash('Return request submitted successfully.', 'success')
    return redirect(url_for('main.return_requests_view'))


@main.route('/renew-books')
@login_required
def renew_requests_view():
    if current_user.is_admin:
        return redirect(url_for('main.admin_requests'))
    active_issues = IssuedBook.query.filter_by(student_id=current_user.id, status='Issued').all()
    reqs = BookRequest.query.filter_by(student_id=current_user.id, request_type='Renew').order_by(BookRequest.requested_date.desc()).all()
    return render_template('renew_requests.html', active_issues=active_issues, requests=reqs)


@main.route('/reservations')
@login_required
def reserve_requests_view():
    if current_user.is_admin:
        return redirect(url_for('main.admin_requests'))
    reqs = BookRequest.query.filter_by(student_id=current_user.id, request_type='Reserve').order_by(BookRequest.requested_date.desc()).all()
    return render_template('reserve_requests.html', requests=reqs)


@main.route('/student/request_reserve/<int:book_id>', methods=['POST'])
@login_required
def student_request_reserve(book_id):
    if current_user.is_admin:
        flash('Admins cannot reserve books.', 'danger')
        return redirect(url_for('main.books'))
    if current_user.is_blocked:
        flash('Your account is blocked. Reservation denied.', 'danger')
        return redirect(url_for('main.books'))
        
    book = Book.query.get_or_404(book_id)
    
    existing = BookRequest.query.filter_by(
        student_id=current_user.id,
        book_id=book_id,
        request_type='Reserve',
        status='Pending'
    ).first()
    if existing:
        flash('You already have a pending reservation for this book.', 'warning')
        return redirect(url_for('main.books'))
        
    req = BookRequest(
        student_id=current_user.id,
        book_id=book_id,
        request_type='Reserve',
        status='Pending'
    )
    db.session.add(req)
    db.session.commit()
    
    log_activity(current_user.get_id(), current_user.full_name, 'Student', 'Reserve Book', f"Reserved book '{book.title}'")
    create_notification(None, "New Reservation Request", f"Student {current_user.full_name} reserved '{book.title}'.")
    publish_sync_event('REQUEST_CREATED')
    
    flash('Book reserved successfully. You will be notified when it becomes available.', 'success')
    return redirect(url_for('main.reserve_requests_view'))


@main.route('/my-borrowed-books')
@login_required
def my_borrowed_books_view():
    if current_user.is_admin:
        return redirect(url_for('main.history'))
    active_issues = IssuedBook.query.filter_by(student_id=current_user.id, status='Issued').all()
    return render_template('my_borrowed.html', active_issues=active_issues)


@main.route('/my-fines')
@login_required
def student_fines_view():
    if current_user.is_admin:
        return redirect(url_for('main.fines_view'))
    fines = FineRecord.query.filter_by(student_id=current_user.id).order_by(FineRecord.status.desc(), FineRecord.amount.desc()).all()
    fine_due = db.session.query(func.sum(FineRecord.amount)).filter(
        FineRecord.student_id == current_user.id,
        FineRecord.status != 'Paid'
    ).scalar() or 0.0
    return render_template('my_fines.html', fines=fines, fine_due=fine_due)


@main.route('/receipts')
@login_required
def receipts_view():
    if current_user.is_admin:
        issues = IssuedBook.query.order_by(IssuedBook.issue_date.desc()).all()
    else:
        issues = IssuedBook.query.filter_by(student_id=current_user.id).order_by(IssuedBook.issue_date.desc()).all()
    return render_template('receipts.html', issues=issues)


@main.route('/receipt/<int:issue_id>')
@login_required
def download_receipt(issue_id):
    issue = IssuedBook.query.get_or_404(issue_id)
    if not current_user.is_admin and issue.student_id != current_user.id:
        abort(403)
    return render_template('receipt.html', issue=issue)


@main.route('/feedback', methods=['GET', 'POST'])
@login_required
def feedback_view():
    if current_user.is_admin:
        return redirect(url_for('main.admin_feedback_view'))
    feedbacks = Feedback.query.filter_by(student_id=current_user.id).order_by(Feedback.created_at.desc()).all()
    return render_template('feedback.html', feedbacks=feedbacks)


@main.route('/feedback/submit', methods=['POST'])
@login_required
def submit_feedback():
    if current_user.is_admin:
        flash('Admins cannot submit feedback.', 'danger')
        return redirect(url_for('main.dashboard'))
    fb_type = request.form.get('feedback_type', 'General').strip()
    message = request.form.get('message', '').strip()
    if not message:
        flash('Feedback message cannot be empty.', 'danger')
        return redirect(url_for('main.feedback_view'))
        
    fb = Feedback(
        student_id=current_user.id,
        feedback_type=fb_type,
        message=message
    )
    db.session.add(fb)
    db.session.commit()
    
    log_activity(current_user.get_id(), current_user.full_name, 'Student', 'Submit Feedback', f"Submitted feedback of type: {fb_type}")
    create_notification(None, "New Feedback Received", f"Student {current_user.full_name} submitted feedback/suggestion.")
    publish_sync_event('FEEDBACK_SUBMITTED')
    
    flash('Feedback submitted successfully. Thank you!', 'success')
    return redirect(url_for('main.feedback_view'))


@main.route('/admin/feedback')
@login_required
@admin_required
def admin_feedback_view():
    feedbacks = Feedback.query.order_by(Feedback.created_at.desc()).all()
    return render_template('admin_feedback.html', feedbacks=feedbacks)


@main.route('/admin/feedback/<int:feedback_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_feedback(feedback_id):
    fb = Feedback.query.get_or_404(feedback_id)
    db.session.delete(fb)
    db.session.commit()
    log_activity(current_user.get_id(), current_user.full_name, 'Admin', 'Delete Feedback', f"Deleted feedback ID #{feedback_id}")
    flash('Feedback deleted successfully.', 'success')
    return redirect(url_for('main.admin_feedback_view'))


# --- Error handlers ---

@main.errorhandler(403)
def access_forbidden(error):
    return render_template('error.html', error_code=403, message='Access forbidden. Administrator credentials required.'), 403


@main.errorhandler(404)
def not_found(error):
    return render_template('error.html', error_code=404, message='Page not found.'), 404


@main.errorhandler(500)
def server_error(error):
    return render_template('error.html', error_code=500, message='Internal server error.'), 500
