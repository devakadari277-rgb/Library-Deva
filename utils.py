import os
import uuid
from datetime import datetime
from werkzeug.utils import secure_filename

from config import Config
from extensions import db


ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_image(image_file):
    if image_file and allowed_file(image_file.filename):
        filename = secure_filename(image_file.filename)
        unique_name = f"{uuid.uuid4().hex}_{filename}"
        filepath = os.path.join(Config.UPLOAD_FOLDER, unique_name)
        # Create folder if it doesn't exist
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        image_file.save(filepath)
        return unique_name
    return 'default-book.png'


def calculate_fine(due_date, return_date):
    if return_date and due_date and return_date > due_date:
        days_late = (return_date - due_date).days
        return max(0.0, float(days_late * 1.0))
    return 0.0


def update_outstanding_fines():
    """
    On-demand fine calculator for currently issued overdue books.
    Ensures dashboard statistics and fine displays are always fully synchronized.
    """
    from models import IssuedBook, FineRecord
    now = datetime.utcnow()
    # Query all active issues that are past due
    overdue_issues = IssuedBook.query.filter(
        IssuedBook.status == 'Issued',
        IssuedBook.due_date < now
    ).all()
    
    for issue in overdue_issues:
        days_late = (now - issue.due_date).days
        if days_late > 0:
            fine_amount = float(days_late * 1.0)  # ₹1 per day
            issue.fine_amount = fine_amount
            
            # Find or create FineRecord
            fine_rec = FineRecord.query.filter_by(issued_book_id=issue.id).first()
            if not fine_rec:
                fine_rec = FineRecord(
                    student_id=issue.student_id,
                    issued_book_id=issue.id,
                    amount=fine_amount,
                    status='Unpaid'
                )
                db.session.add(fine_rec)
            else:
                if fine_rec.status == 'Unpaid':
                    fine_rec.amount = fine_amount
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
