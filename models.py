"""
MyTodo Founder OS — Data Model

Phase 2: Multi-user workspace with roles and invitation-based access.

WorkspaceUser   — approved team members (founder, coo, staff, viewer)
WorkspaceInvite — single-use invite tokens created by founder

Core entity: Initiative
  An initiative is anything the founder is building, distributing, or monetising.
  visibility: private (founder only) | team (coo+) | public (all members)

Every initiative tracks three dimensions:
  Build Score        (0-100) — how much of the product is built
  Distribution Score (0-100) — how actively it's being published/shared
  Revenue Score      (0-100) — how much revenue it generates

Forward compat: gateway_user_id will link to phang_member_id when Gateway JWT
integration is complete. The workspace_users table will grow a phang_member_id FK.
"""

import json
from datetime import datetime, date
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Date, Float, ForeignKey
from sqlalchemy.orm import relationship
from database import Base


# ── Identity ──────────────────────────────────────────────────────────────────

class WorkspaceUser(Base):
    """
    Approved member of the MyTodo workspace.
    Founder is auto-created on first startup from env vars.
    All other users are invite-only.
    """
    __tablename__ = "workspace_users"

    id           = Column(Integer, primary_key=True)
    email        = Column(String(255), unique=True, nullable=False, index=True)
    full_name    = Column(String(255), nullable=False, default="")
    role         = Column(String(20),  nullable=False, default="viewer")
    # role values: "founder" | "coo" | "staff" | "viewer"
    status       = Column(String(20),  nullable=False, default="pending")
    # status values: "approved" | "pending" | "suspended"
    password_hash = Column(String(255), nullable=False, default="")
    created_at   = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WorkspaceInvite(Base):
    """
    Single-use invite token. Founder creates; team member uses it to set password.
    Expires 72 hours after creation.
    """
    __tablename__ = "workspace_invites"

    id          = Column(Integer, primary_key=True)
    token       = Column(String(64), unique=True, nullable=False, index=True)
    email       = Column(String(255), nullable=False)
    role        = Column(String(20),  nullable=False, default="viewer")
    created_by  = Column(Integer, nullable=False)   # WorkspaceUser.id of founder
    used        = Column(Boolean, nullable=False, default=False)
    expires_at  = Column(DateTime, nullable=False)
    created_at  = Column(DateTime, default=datetime.utcnow)


class Initiative(Base):
    """
    The atomic unit of founder execution.
    One Initiative = one product, project, or bet the founder is running.

    visibility controls who can see this initiative:
      private — founder only (default, protects planning from team)
      team    — founder + coo
      public  — all approved workspace members
    """
    __tablename__ = "initiatives"

    id = Column(Integer, primary_key=True)
    gateway_user_id = Column(Integer, nullable=False, index=True)

    # Phase 2: visibility control
    visibility = Column(String(20), nullable=False, default="private")
    # "private" | "team" | "public"

    name = Column(String, nullable=False)           # "InfoPro", "NextDoor", "Foodie AI"
    description = Column(Text, default="")
    category = Column(String, default="product")    # product / infra / platform / content / personal
    stage = Column(String, default="building")      # ideation / building / launched / distributing / revenue / paused

    # The three scores — each 0-100, manually set or AI-suggested
    build_score = Column(Integer, default=0)
    distribution_score = Column(Integer, default=0)
    revenue_score = Column(Integer, default=0)

    # Qualitative notes per dimension
    build_notes = Column(Text, default="")           # what's been built
    distribution_notes = Column(Text, default="")    # which channels are active
    revenue_notes = Column(Text, default="")         # revenue sources and model

    # Quantitative actuals
    revenue_total = Column(Float, default=0.0)       # NGN, sum of all RevenueRecords
    users_count = Column(Integer, default=0)         # active users

    # AI intelligence from PHANT
    bottleneck = Column(String, default="distribution")   # build / distribution / revenue
    ai_brief = Column(Text, default="{}")            # JSON — latest PHANT analysis
    ai_suggested_actions = Column(Text, default="[]")     # JSON list of pending PHANT suggestions

    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tasks = relationship("Task", back_populates="initiative", cascade="all, delete-orphan")
    revenue_records = relationship("RevenueRecord", back_populates="initiative", cascade="all, delete-orphan")
    distribution_actions = relationship("DistributionAction", back_populates="initiative", cascade="all, delete-orphan")
    reflections = relationship("Reflection", back_populates="initiative", cascade="all, delete-orphan")

    def ai_data(self) -> dict:
        return json.loads(self.ai_brief or "{}")

    def pending_actions(self) -> list:
        return json.loads(self.ai_suggested_actions or "[]")

    def compute_bottleneck(self) -> str:
        """The dimension furthest below build_score is typically the bottleneck."""
        build = self.build_score or 0
        dist = self.distribution_score or 0
        rev = self.revenue_score or 0
        if build > dist and build > rev:
            if dist <= rev:
                return "distribution"
            return "revenue"
        if dist < rev:
            return "distribution"
        return "distribution"  # distribution is almost always the gap


class Task(Base):
    """
    A discrete action tied to an initiative (or standalone).
    Categories map directly to initiative dimensions.

    gateway_user_id = the user who created/owns this task.
    visibility controls who else can see it.
    """
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True)
    initiative_id = Column(Integer, ForeignKey("initiatives.id"), nullable=True)
    gateway_user_id = Column(Integer, nullable=False, index=True)

    # Visibility: "private" (owner only) | "team" (all approved) | "public"
    visibility = Column(String(20), nullable=False, default="team")

    # Optional assignment to a specific workspace member
    assigned_to_user_id = Column(Integer, ForeignKey("workspace_users.id"), nullable=True, index=True)

    title = Column(String, nullable=False)
    notes = Column(Text, default="")
    category = Column(String, default="build")    # build / distribution / revenue / ops / learning
    priority = Column(String, default="high")     # critical / high / medium / low
    status = Column(String, default="open")       # open / in_progress / done / skipped

    for_date = Column(Date, default=date.today)
    done_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    initiative = relationship("Initiative", back_populates="tasks")


class RevenueRecord(Base):
    """
    A discrete revenue event. Summed into initiative.revenue_total on every write.

    visibility defaults to "private" — revenue is sensitive.
    Founder can share entries with the team by setting visibility="team".
    """
    __tablename__ = "revenue_records"

    id = Column(Integer, primary_key=True)
    initiative_id = Column(Integer, ForeignKey("initiatives.id"), nullable=False)
    gateway_user_id = Column(Integer, nullable=False, index=True)

    # "private" (owner only) | "team" (all approved workspace members)
    visibility = Column(String(20), nullable=False, default="private")

    amount = Column(Float, nullable=False)         # NGN
    source = Column(String, default="")            # "subscription" / "consulting" / "client_payment"
    notes = Column(Text, default="")
    recorded_at = Column(DateTime, default=datetime.utcnow)

    initiative = relationship("Initiative", back_populates="revenue_records")


class DistributionAction(Base):
    """
    A single distribution action: one post, one video, one broadcast.
    Closing the gap between Build Score and Distribution Score means completing these.

    visibility defaults to "team" — campaigns are collaborative knowledge.
    """
    __tablename__ = "distribution_actions"

    id = Column(Integer, primary_key=True)
    initiative_id = Column(Integer, ForeignKey("initiatives.id"), nullable=True)
    gateway_user_id = Column(Integer, nullable=False, index=True)

    # "private" (owner only) | "team" (all approved) | "public"
    visibility = Column(String(20), nullable=False, default="team")

    channel = Column(String, nullable=False)       # x_post / reddit / youtube / devlog / whatsapp_broadcast / linkedin / producthunt / newsletter / other
    description = Column(Text, default="")         # what to post/share
    status = Column(String, default="pending")     # pending / completed / skipped
    ai_suggested = Column(Boolean, default=False)  # PHANT-generated suggestion?
    impact_notes = Column(Text, default="")        # filled after: what happened

    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    initiative = relationship("Initiative", back_populates="distribution_actions")


class Reflection(Base):
    """A strategic reflection session tied to an initiative."""
    __tablename__ = "reflections"

    id = Column(Integer, primary_key=True)
    initiative_id = Column(Integer, ForeignKey("initiatives.id"), nullable=False)
    gateway_user_id = Column(Integer, nullable=False, index=True)

    question = Column(Text, nullable=False)
    answer = Column(Text, default="")
    domain = Column(String, default="")            # build / distribution / revenue / motivation / constraints
    insights = Column(Text, default="[]")          # JSON list of extracted insights
    session_number = Column(Integer, default=1)
    processed = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)

    initiative = relationship("Initiative", back_populates="reflections")

    def insights_list(self) -> list:
        return json.loads(self.insights or "[]")


class DailyBrief(Base):
    """One PHANT brief per calendar day, displayed on the dashboard."""
    __tablename__ = "daily_briefs"

    id = Column(Integer, primary_key=True)
    gateway_user_id = Column(Integer, nullable=False, index=True)
    brief_date = Column(Date, nullable=False)

    headline = Column(Text, default="")
    content = Column(Text, default="{}")            # full JSON from PHANT engine
    recommended_actions = Column(Text, default="[]")

    deployments_count = Column(Integer, default=0)
    new_users_count = Column(Integer, default=0)
    ai_analyses_count = Column(Integer, default=0)
    whatsapp_inquiries_count = Column(Integer, default=0)
    revenue_events_count = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)

    def content_data(self) -> dict:
        return json.loads(self.content or "{}")

    def actions_list(self) -> list:
        return json.loads(self.recommended_actions or "[]")


class ChatMessage(Base):
    """Persistent conversation history for the Copilot chat interface."""
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True)
    gateway_user_id = Column(Integer, nullable=False, index=True)
    role = Column(String, nullable=False)           # "user" | "assistant"
    content = Column(Text, nullable=False)
    intent = Column(String, nullable=True)          # detected intent, if user message
    actions_taken = Column(Text, default="[]")      # JSON list of state changes made
    created_at = Column(DateTime, default=datetime.utcnow)

    def actions_list(self) -> list:
        return json.loads(self.actions_taken or "[]")
