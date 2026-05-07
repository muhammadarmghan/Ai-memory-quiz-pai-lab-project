from datetime import datetime, timedelta
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, Text, ForeignKey, JSON
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Topic(Base):
    """Study topics/courses"""
    __tablename__ = 'topics'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False, index=True)
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    questions = relationship('Question', back_populates='topic', cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
        }


class Question(Base):
    """Quiz questions from dataset"""
    __tablename__ = 'questions'
    
    id = Column(Integer, primary_key=True)
    external_id = Column(String(100), unique=True, nullable=False, index=True)
    topic_id = Column(Integer, ForeignKey('topics.id'), nullable=False)
    question_text = Column(Text, nullable=False)
    choices = Column(JSON, nullable=False)  # Array of choice objects
    correct_answer = Column(String(2), nullable=False)  # Answer key like 'A', 'B', etc
    fact1 = Column(Text)
    fact2 = Column(Text)
    combined_fact = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    topic = relationship('Topic', back_populates='questions')
    attempts = relationship('QuizAttempt', back_populates='question', cascade='all, delete-orphan')
    
    def to_dict(self):
        return {
            'id': self.id,
            'external_id': self.external_id,
            'question_text': self.question_text,
            'choices': self.choices,
            'fact1': self.fact1,
            'fact2': self.fact2,
            'combined_fact': self.combined_fact,
        }


class QuizAttempt(Base):
    """Track individual quiz attempts (learning history for spaced repetition)"""
    __tablename__ = 'quiz_attempts'
    
    id = Column(Integer, primary_key=True)
    question_id = Column(Integer, ForeignKey('questions.id'), nullable=False)
    user_answer = Column(String(2))
    is_correct = Column(Boolean, nullable=False)
    attempted_at = Column(DateTime, default=datetime.utcnow)
    
    # Spaced Repetition Tracking
    interval = Column(Integer, default=1)  # days until next review
    ease_factor = Column(Float, default=2.5)  # difficulty multiplier
    repetition_count = Column(Integer, default=0)
    next_review_date = Column(DateTime)
    
    # Relationships
    question = relationship('Question', back_populates='attempts')
    
    def calculate_next_review(self):
        """SM-2 Algorithm: Calculate next review date based on performance"""
        # q = quality of response (0-5): 0=complete blackout, 5=perfect response
        quality = 5 if self.is_correct else 0
        
        # Ensure defaults are set (SQLAlchemy defaults not available pre-flush)
        if self.repetition_count is None:
            self.repetition_count = 0
        if self.ease_factor is None:
            self.ease_factor = 2.5
        if self.interval is None:
            self.interval = 1
        
        # First attempt
        if self.repetition_count == 0:
            self.interval = 1
            self.ease_factor = 2.5
        # Second attempt
        elif self.repetition_count == 1:
            self.interval = 3
        # Subsequent attempts
        else:
            new_ease = self.ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
            self.ease_factor = max(1.3, new_ease)  # Minimum ease factor
            self.interval = int(self.interval * self.ease_factor)
        
        self.repetition_count += 1
        self.next_review_date = datetime.now() + timedelta(days=self.interval)
    
    def to_dict(self):
        return {
            'id': self.id,
            'question_id': self.question_id,
            'user_answer': self.user_answer,
            'is_correct': self.is_correct,
            'attempted_at': self.attempted_at.isoformat(),
            'interval': self.interval,
            'ease_factor': self.ease_factor,
            'next_review_date': self.next_review_date.isoformat() if self.next_review_date else None,
        }


class GeneratedQuiz(Base):
    """Track AI-generated quizzes for analytics"""
    __tablename__ = 'generated_quizzes'
    
    id = Column(Integer, primary_key=True)
    topic_id = Column(Integer, ForeignKey('topics.id'), nullable=False)
    prompt = Column(Text)
    ai_response = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    model_used = Column(String(50))  # e.g., 'gpt-4', 'claude-3'
