from flask_wtf import FlaskForm
from wtforms import (
    FileField,
    StringField,
    PasswordField,
    SubmitField,
    BooleanField,
    SelectField,
    TextAreaField,
    IntegerField,
)
from wtforms.validators import (
    DataRequired,
    Email,
    EqualTo,
    Length,
    ValidationError,
    NumberRange,
)
from flask_wtf.file import FileAllowed

from models import Student, Admin, Category


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    remember = BooleanField('Remember Me')
    submit = SubmitField('Login')


class StudentRegistrationForm(FlaskForm):
    full_name = StringField('Full Name', validators=[DataRequired(), Length(min=3, max=120)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    roll_number = StringField('Roll Number', validators=[DataRequired(), Length(min=2, max=50)])
    department = StringField('Department', validators=[DataRequired(), Length(min=2, max=120)])
    phone = StringField('Phone', validators=[DataRequired(), Length(min=5, max=20)])
    address = TextAreaField('Address', validators=[Length(max=300)])
    image = FileField('Profile Picture', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Images only!')])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Create Student Account')

    def validate_email(self, email):
        if Student.query.filter_by(email=email.data.lower()).first() or Admin.query.filter_by(email=email.data.lower()).first():
            raise ValidationError('Email already registered.')

    def validate_roll_number(self, roll_number):
        if Student.query.filter_by(roll_number=roll_number.data).first():
            raise ValidationError('Roll Number already registered.')


class AdminRegistrationForm(FlaskForm):
    full_name = StringField('Full Name', validators=[DataRequired(), Length(min=3, max=120)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    image = FileField('Profile Picture', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Images only!')])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Create Admin Account')

    def validate_email(self, email):
        if Student.query.filter_by(email=email.data.lower()).first() or Admin.query.filter_by(email=email.data.lower()).first():
            raise ValidationError('Email already registered.')


class StudentProfileForm(FlaskForm):
    full_name = StringField('Full Name', validators=[DataRequired(), Length(min=3, max=120)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    roll_number = StringField('Roll Number', validators=[DataRequired(), Length(min=2, max=50)])
    department = StringField('Department', validators=[DataRequired(), Length(min=2, max=120)])
    phone = StringField('Phone', validators=[DataRequired(), Length(min=5, max=20)])
    address = TextAreaField('Address', validators=[Length(max=300)])
    image = FileField('Profile Picture', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Images only!')])
    new_password = PasswordField('New Password (leave blank to keep current)', validators=[Length(max=50)])
    confirm_password = PasswordField('Confirm New Password', validators=[EqualTo('new_password')])
    submit = SubmitField('Update Profile')


class AdminProfileForm(FlaskForm):
    full_name = StringField('Full Name', validators=[DataRequired(), Length(min=3, max=120)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    new_password = PasswordField('New Password (leave blank to keep current)', validators=[Length(max=50)])
    confirm_password = PasswordField('Confirm New Password', validators=[EqualTo('new_password')])
    image = FileField('Profile Picture', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Images only!')])
    submit = SubmitField('Update Profile')


class BookForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired()])
    author = StringField('Author', validators=[DataRequired()])
    isbn = StringField('ISBN', validators=[DataRequired()])
    category = SelectField('Category', coerce=int, validators=[DataRequired()])
    publisher = StringField('Publisher', validators=[DataRequired()])
    language = StringField('Language', validators=[DataRequired()])
    edition = StringField('Edition', validators=[DataRequired()])
    total_copies = IntegerField('Total Copies', validators=[DataRequired(), NumberRange(min=1)])
    shelf_number = StringField('Shelf Number', validators=[DataRequired()])
    image = FileField('Book Cover', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Images only!')])
    description = TextAreaField('Description')
    submit = SubmitField('Save Book')


class CategoryForm(FlaskForm):
    category_name = StringField('Category Name', validators=[DataRequired(), Length(min=2, max=120)])
    submit = SubmitField('Save Category')


class IssueBookForm(FlaskForm):
    student = SelectField('Student', coerce=int, validators=[DataRequired()])
    book = SelectField('Book', coerce=int, validators=[DataRequired()])
    duration = IntegerField('Days until due', validators=[DataRequired(), NumberRange(min=1, max=60)], default=14)
    submit = SubmitField('Issue Book')
