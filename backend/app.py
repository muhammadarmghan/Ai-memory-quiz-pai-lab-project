import os, json, logging
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from dotenv import load_dotenv
from sqlalchemy import create_engine, func, and_
from sqlalchemy.orm import sessionmaker
from groq import Groq
from models import Base, Topic, Question, QuizAttempt, GeneratedQuiz

load_dotenv()
class Config:
    DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///ai_memory_booster.db')
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key')
    GROQ_API_KEY = os.getenv('GROQ_API_KEY', '')
    DEBUG = os.getenv('FLASK_ENV', 'development') == 'development'

engine = create_engine(Config.DATABASE_URL, connect_args={'check_same_thread': False} if 'sqlite' in Config.DATABASE_URL else {})
SessionLocal = sessionmaker(bind=engine)

def init_db(): Base.metadata.create_all(bind=engine)

class AIQuizService:
    def __init__(self):
        self.client = Groq(api_key=os.getenv('GROQ_API_KEY'))
        self.model = "llama-3.1-8b-instant"

    def _chat(self, system, user, tokens=1000):
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=tokens,
            response_format={"type": "json_object"}
        )
        raw = resp.choices[0].message.content.strip()
        return json.loads(raw)

    def generate_from_text(self, topic_name, content):
        system = "You are an expert educator. Generate 5 multiple-choice questions from the provided text. Return a JSON object with a 'questions' key containing a list of objects with: question, choices (list of 4 strings), answer (A, B, C, or D), and explanation."
        return self._chat(system, f"Topic: {topic_name}\n\nContent: {content}")['questions']

def get_ai():
    return AIQuizService() if os.getenv('GROQ_API_KEY') else None

app = Flask(__name__)
app.config.from_object(Config)
CORS(app)

@app.before_request
def before(): init_db()

@app.route('/')
def dashboard(): return render_template('dashboard.html', active_page='dashboard')

@app.route('/topics')
def topics_page(): return render_template('topics.html', active_page='topics')

@app.route('/quiz')
def quiz_page(): return render_template('quiz.html', active_page='quiz')

@app.route('/smart-paste')
def smart_paste_page(): return render_template('smart_paste.html', active_page='smart-paste')

# --- API ROUTES ---
@app.route('/api/topics', methods=['GET', 'POST'])
def handle_topics():
    db = SessionLocal()
    if request.method == 'POST':
        data = request.json
        if db.query(Topic).filter(Topic.name.ilike(data['name'])).first():
            return jsonify({'error': 'Exists'}), 409
        topic = Topic(name=data['name'], description=data.get('description', ''))
        db.add(topic); db.commit()
        return jsonify(topic.to_dict()), 201
    topics = db.query(Topic).all()
    return jsonify([t.to_dict() for t in topics])

@app.route('/api/topics/<int:tid>')
def topic_detail(tid):
    db = SessionLocal()
    t = db.query(Topic).get(tid)
    if not t: return jsonify({'error': 'Not found'}), 404
    d = t.to_dict()
    d['question_count'] = db.query(Question).filter_by(topic_id=tid).count()
    return jsonify(d)

@app.route('/api/quiz/questions')
def get_questions():
    db = SessionLocal()
    tid = request.args.get('topic_id', type=int)
    q = db.query(Question)
    if tid: q = q.filter_by(topic_id=tid)
    return jsonify([x.to_dict() for x in q.limit(request.args.get('limit', 10, type=int)).all()])

@app.route('/api/quiz/answer', methods=['POST'])
def submit_answer():
    db = SessionLocal()
    data = request.json
    q = db.query(Question).get(data['question_id'])
    is_correct = data['user_answer'].upper() == q.correct_answer.upper()
    att = QuizAttempt(question_id=q.id, user_answer=data['user_answer'], is_correct=is_correct)
    att.calculate_next_review()
    db.add(att); db.commit()
    return jsonify({'is_correct': is_correct, 'correct_answer': q.correct_answer, 'explanation': q.combined_fact, 'next_review': att.next_review_date.isoformat()})

@app.route('/api/quiz/progress')
def get_progress():
    db = SessionLocal()
    total = db.query(func.count(QuizAttempt.id)).scalar() or 0
    correct = db.query(func.count(QuizAttempt.id)).filter_by(is_correct=True).scalar() or 0
    due = db.query(func.count(QuizAttempt.id)).filter(QuizAttempt.next_review_date <= datetime.utcnow()).scalar() or 0
    topics = []
    for t in db.query(Topic).all():
        ta = db.query(func.count(QuizAttempt.id)).join(Question).filter(Question.topic_id == t.id).scalar() or 0
        tc = db.query(func.count(QuizAttempt.id)).join(Question).filter(and_(QuizAttempt.is_correct == True, Question.topic_id == t.id)).scalar() or 0
        if ta > 0: topics.append({'topic_id': t.id, 'topic_name': t.name, 'total_questions': ta, 'correct': tc, 'accuracy': (tc/ta)*100})
    return jsonify({'total_attempts': total, 'correct_answers': correct, 'overall_accuracy': (correct/total*100) if total else 0, 'due_for_review': due, 'topics': topics})

@app.route('/api/quiz/generate-from-text', methods=['POST'])
def generate_from_text():
    ai = get_ai()
    if not ai: return jsonify({'error': 'AI not configured'}), 503
    data = request.json
    try:
        qs = ai.generate_from_text(data['topic'], data['content'])
        db = SessionLocal()
        topic = db.query(Topic).filter(Topic.name.ilike(data['topic'])).first()
        if not topic:
            topic = Topic(name=data['topic'])
            db.add(topic); db.flush()
        
        for q in qs:
            db.add(Question(
                external_id=f"ai_{datetime.now().timestamp()}_{os.urandom(4).hex()}",
                topic_id=topic.id,
                question_text=q['question'],
                choices={'text': q['choices'], 'label': ['A', 'B', 'C', 'D']},
                correct_answer=q['answer'],
                combined_fact=q.get('explanation', '')
            ))
        db.commit()
        return jsonify({'success': True, 'count': len(qs)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=Config.DEBUG)
