from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from models import db, User, Question, Answer, AwardOption, AwardVote, AwardSuggestion, StudyLog, StudyPlan
from datetime import datetime
from sqlalchemy import func, extract
import os

app = Flask(__name__)

# 🔐 生产环境安全配置：从环境变量读取密钥
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-change-this-in-production')

# 🗄️ 数据库配置：优先使用环境变量（Render提供），否则使用本地SQLite
database_url = os.environ.get('DATABASE_URL', 'sqlite:///database.db')

# ⚠️ Render提供的链接格式修正（postgres:// 改为 postgresql://）
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 生产环境禁用调试模式
app.config['DEBUG'] = os.environ.get('FLASK_ENV') != 'production'

db.init_app(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# 数据库初始化（仅在表不存在时执行）
with app.app_context():
    db.create_all()

    # 初始化默认奖项选项
    if AwardOption.query.count() == 0:
        default_options = [
            "Shortest study time buys dinner for longest study time",
            "Top 3 learners get a special badge for the month",
            "Bottom 3 learners must share study tips next week",
            "Longest streak gets to choose next month's challenge",
            "Most improved learner gets bonus recognition",
            "Weekend study warriors get extra credits",
            "Early morning learners get breakfast voucher",
            "Night owls get coffee shop gift card",
            "Most helpful answers get a prize",
            "Consistent daily learners get special privileges"
        ]
        for desc in default_options:
            option = AwardOption(description=desc)
            db.session.add(option)
        db.session.commit()


@app.route('/')
def index():
    if current_user.is_authenticated:
        return render_template('index.html')
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')

        if User.query.filter_by(username=username).first():
            flash('Username already exists!', 'error')
            return redirect(url_for('register'))

        if User.query.filter_by(email=email).first():
            flash('Email already registered!', 'error')
            return redirect(url_for('register'))

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        user = User(username=username, email=email, password=hashed_password)
        db.session.add(user)
        db.session.commit()

        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()
        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('index'))
        else:
            flash('Invalid username or password!', 'error')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/qa')
@login_required
def qa():
    category = request.args.get('category', 'all')
    if category == 'all':
        questions = Question.query.order_by(Question.created_at.desc()).all()
    else:
        questions = Question.query.filter_by(category=category).order_by(Question.created_at.desc()).all()

    return render_template('qa.html', questions=questions, current_category=category)


@app.route('/qa/create', methods=['POST'])
@login_required
def create_question():
    title = request.form.get('title')
    content = request.form.get('content')
    category = request.form.get('category')

    question = Question(title=title, content=content, category=category, user_id=current_user.id)
    db.session.add(question)
    db.session.commit()

    flash('Question posted successfully!', 'success')
    return redirect(url_for('qa'))


@app.route('/qa/delete/<int:question_id>', methods=['POST'])
@login_required
def delete_question(question_id):
    question = Question.query.get_or_404(question_id)
    db.session.delete(question)
    db.session.commit()

    flash('Question deleted successfully!', 'success')
    return redirect(url_for('qa'))


@app.route('/qa/answer/<int:question_id>', methods=['POST'])
@login_required
def answer_question(question_id):
    content = request.form.get('content')

    answer = Answer(content=content, question_id=question_id, user_id=current_user.id)
    db.session.add(answer)
    db.session.commit()

    flash('Answer posted successfully!', 'success')
    return redirect(url_for('qa'))


@app.route('/awards')
@login_required
def awards():
    current_month = datetime.now().month
    current_year = datetime.now().year

    monthly_stats = db.session.query(
        User.id,
        User.username,
        func.sum(StudyLog.study_time).label('total_time')
    ).join(StudyLog).filter(
        extract('month', StudyLog.log_date) == current_month,
        extract('year', StudyLog.log_date) == current_year
    ).group_by(User.id).order_by(func.sum(StudyLog.study_time).desc()).all()

    top_3 = monthly_stats[:3] if len(monthly_stats) >= 3 else monthly_stats
    bottom_3 = monthly_stats[-3:] if len(monthly_stats) >= 3 else []

    options = AwardOption.query.order_by(AwardOption.vote_count.desc()).all()
    user_votes = [vote.option_id for vote in AwardVote.query.filter_by(user_id=current_user.id).all()]
    suggestions = AwardSuggestion.query.order_by(AwardSuggestion.created_at.desc()).all()

    return render_template('awards.html', top_3=top_3, bottom_3=bottom_3,
                           options=options, user_votes=user_votes, suggestions=suggestions)


@app.route('/awards/vote', methods=['POST'])
@login_required
def vote_award():
    option_ids = request.form.getlist('options')

    if len(option_ids) > 3:
        flash('You can only select up to 3 options!', 'error')
        return redirect(url_for('awards'))

    AwardVote.query.filter_by(user_id=current_user.id).delete()

    for option in AwardOption.query.all():
        option.vote_count = AwardVote.query.filter_by(option_id=option.id).count()

    for option_id in option_ids:
        vote = AwardVote(user_id=current_user.id, option_id=int(option_id))
        db.session.add(vote)

        option = AwardOption.query.get(int(option_id))
        option.vote_count += 1

    db.session.commit()
    flash('Votes submitted successfully!', 'success')
    return redirect(url_for('awards'))


@app.route('/awards/suggest', methods=['POST'])
@login_required
def suggest_award():
    suggestion = request.form.get('suggestion')

    new_suggestion = AwardSuggestion(suggestion=suggestion, user_id=current_user.id)
    db.session.add(new_suggestion)
    db.session.commit()

    flash('Suggestion submitted successfully!', 'success')
    return redirect(url_for('awards'))


@app.route('/calendar')
@login_required
def calendar():
    return render_template('calendar.html')


@app.route('/calendar/plan', methods=['GET', 'POST'])
@login_required
def manage_plan():
    if request.method == 'POST':
        date_str = request.form.get('date')
        content = request.form.get('content')
        plan_date = datetime.strptime(date_str, '%Y-%m-%d').date()

        plan = StudyPlan.query.filter_by(user_id=current_user.id, plan_date=plan_date).first()
        if plan:
            plan.plan_content = content
        else:
            plan = StudyPlan(user_id=current_user.id, plan_date=plan_date, plan_content=content)
            db.session.add(plan)

        db.session.commit()
        return jsonify({'success': True})

    date_str = request.args.get('date')
    plan_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    plan = StudyPlan.query.filter_by(user_id=current_user.id, plan_date=plan_date).first()

    return jsonify({
        'content': plan.plan_content if plan else '',
        'is_completed': plan.is_completed if plan else False
    })


@app.route('/calendar/complete', methods=['POST'])
@login_required
def complete_plan():
    date_str = request.form.get('date')
    plan_date = datetime.strptime(date_str, '%Y-%m-%d').date()

    plan = StudyPlan.query.filter_by(user_id=current_user.id, plan_date=plan_date).first()
    if plan:
        plan.is_completed = True
        db.session.commit()
        return jsonify({'success': True})

    return jsonify({'success': False, 'error': 'No plan found'})


@app.route('/ranking')
@login_required
def ranking():
    today = datetime.now().date()

    rankings = db.session.query(
        User.username,
        StudyLog.study_time,
        StudyLog.study_content
    ).join(StudyLog).filter(
        StudyLog.log_date == today
    ).order_by(StudyLog.study_time.desc()).all()

    return render_template('ranking.html', rankings=rankings)


@app.route('/ranking/log', methods=['POST'])
@login_required
def log_study():
    study_time = int(request.form.get('study_time'))
    study_content = request.form.get('study_content')

    today = datetime.now().date()
    existing_log = StudyLog.query.filter_by(user_id=current_user.id, log_date=today).first()

    if existing_log:
        existing_log.study_time = study_time
        existing_log.study_content = study_content
    else:
        log = StudyLog(user_id=current_user.id, study_time=study_time, study_content=study_content)
        db.session.add(log)

    db.session.commit()
    flash('Study log submitted successfully!', 'success')
    return redirect(url_for('ranking'))


if __name__ == '__main__':
    # 仅用于本地测试，生产环境由Gunicorn接管
    app.run(debug=True)
