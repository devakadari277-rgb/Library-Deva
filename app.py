from flask import Flask

from config import Config
from extensions import db, login_manager, csrf


def create_app():
    app = Flask(__name__, static_folder='static', template_folder='templates')
    app.config.from_object(Config)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    @app.context_processor
    def inject_datetime():
        import datetime
        return {'datetime': datetime.datetime}

    from routes import main as main_bp
    app.register_blueprint(main_bp)

    with app.app_context():
        from models import (
            Student, Admin, Category, Book, BookCopy, BookRequest, 
            IssuedBook, ReturnedBook, FineRecord, Transaction, Notification, ActivityLog, Feedback
        )
        db.create_all()

        if not Admin.query.filter_by(email='admin@example.com').first():
            admin = Admin(
                full_name='Admin User',
                email='admin@example.com',
            )
            admin.set_password('password123')
            db.session.add(admin)

        if not Student.query.filter_by(email='student@example.com').first():
            student = Student(
                full_name='Library Student',
                email='student@example.com',
                roll_number='STU-001',
                department='Computer Science',
                phone='555-0199',
                address='Campus Dorm A, Room 104'
            )
            student.set_password('password123')
            db.session.add(student)

        default_categories = ['Fiction', 'Science', 'History', 'Technology', 'Children']
        for name in default_categories:
            if not Category.query.filter_by(category_name=name).first():
                db.session.add(Category(category_name=name))

        db.session.commit()

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
