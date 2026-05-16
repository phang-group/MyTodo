import json
from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Date, Float, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


# No local User model. Identity comes from the PHANG gateway (user_id = gateway int).
# All models use gateway_user_id (Integer, no FK to a local users table).


class StrategicState(Base):
    """User's current real-world state — the ground truth the AI reasons against."""
    __tablename__ = "strategic_state"

    id = Column(Integer, primary_key=True)
    gateway_user_id = Column(Integer, unique=True, nullable=False, index=True)
    monthly_income = Column(Float, default=0)        # NGN
    monthly_expenses = Column(Float, default=0)      # NGN
    savings = Column(Float, default=0)               # NGN total
    skills = Column(Text, default="[]")              # JSON list of strings
    constraints = Column(Text, default="[]")         # JSON list of strings
    location = Column(String, default="Lagos, Nigeria")
    employment_type = Column(String, default="employed")  # employed/self-employed/unemployed/student
    notes = Column(Text, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def skills_list(self):
        return json.loads(self.skills or "[]")

    def constraints_list(self):
        return json.loads(self.constraints or "[]")


class Goal(Base):
    __tablename__ = "goals"

    id = Column(Integer, primary_key=True, index=True)
    gateway_user_id = Column(Integer, nullable=False, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, default="")
    target_date = Column(String, nullable=False)      # ISO date string
    status = Column(String, default="active")         # active/paused/completed/abandoned
    ai_analysis = Column(Text, default="{}")          # JSON blob from DeepSeek
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    daily_tasks = relationship("DailyTask", back_populates="goal", cascade="all, delete-orphan")

    def analysis(self):
        return json.loads(self.ai_analysis or "{}")


class DailyTask(Base):
    __tablename__ = "daily_tasks"

    id = Column(Integer, primary_key=True, index=True)
    goal_id = Column(Integer, ForeignKey("goals.id"), nullable=False)
    gateway_user_id = Column(Integer, nullable=False, index=True)
    task = Column(String, nullable=False)
    priority = Column(String, default="high")           # critical/high/medium
    time_required = Column(String, default="")
    consequence_if_skipped = Column(Text, default="")
    for_date = Column(Date, default=date.today)
    done = Column(Boolean, default=False)
    done_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    goal = relationship("Goal", back_populates="daily_tasks")


class ExecutionLog(Base):
    __tablename__ = "execution_log"

    id = Column(Integer, primary_key=True)
    gateway_user_id = Column(Integer, nullable=False, index=True)
    goal_id = Column(Integer, ForeignKey("goals.id"), nullable=True)
    task_id = Column(Integer, ForeignKey("daily_tasks.id"), nullable=True)
    event = Column(String, nullable=False)   # task_done / task_skipped / goal_created / analysis_run
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
