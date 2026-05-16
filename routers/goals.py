import json
from datetime import date, datetime
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db
import models
import auth as auth_utils
import ai_engine

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/onboarding", response_class=HTMLResponse)
async def onboarding_page(
    request: Request,
    user: models.User = Depends(auth_utils.require_user),
    db: Session = Depends(get_db),
):
    state = db.query(models.StrategicState).filter_by(user_id=user.id).first()
    return templates.TemplateResponse("onboarding.html", {
        "request": request,
        "user": user,
        "state": state,
    })


@router.post("/onboarding")
async def save_state(
    request: Request,
    monthly_income: float = Form(...),
    monthly_expenses: float = Form(...),
    savings: float = Form(...),
    skills: str = Form(default=""),
    constraints: str = Form(default=""),
    location: str = Form(default="Lagos, Nigeria"),
    employment_type: str = Form(default="employed"),
    notes: str = Form(default=""),
    user: models.User = Depends(auth_utils.require_user),
    db: Session = Depends(get_db),
):
    skills_list = [s.strip() for s in skills.split(",") if s.strip()]
    constraints_list = [c.strip() for c in constraints.split(",") if c.strip()]

    state = db.query(models.StrategicState).filter_by(user_id=user.id).first()
    if state:
        state.monthly_income = monthly_income
        state.monthly_expenses = monthly_expenses
        state.savings = savings
        state.skills = json.dumps(skills_list)
        state.constraints = json.dumps(constraints_list)
        state.location = location
        state.employment_type = employment_type
        state.notes = notes
        state.updated_at = datetime.utcnow()
    else:
        state = models.StrategicState(
            user_id=user.id,
            monthly_income=monthly_income,
            monthly_expenses=monthly_expenses,
            savings=savings,
            skills=json.dumps(skills_list),
            constraints=json.dumps(constraints_list),
            location=location,
            employment_type=employment_type,
            notes=notes,
        )
        db.add(state)
    db.commit()
    return RedirectResponse(url="/", status_code=303)


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: models.User = Depends(auth_utils.require_user),
    db: Session = Depends(get_db),
):
    state = db.query(models.StrategicState).filter_by(user_id=user.id).first()
    if not state:
        return RedirectResponse(url="/onboarding", status_code=303)

    goals = db.query(models.Goal).filter_by(user_id=user.id, status="active").all()
    today = date.today()

    # Today's tasks across all active goals
    today_tasks = (
        db.query(models.DailyTask)
        .filter_by(user_id=user.id, for_date=today)
        .order_by(models.DailyTask.done, models.DailyTask.priority)
        .all()
    )

    # Completion rate (last 7 days)
    from datetime import timedelta
    week_ago = today - timedelta(days=7)
    week_tasks = db.query(models.DailyTask).filter(
        models.DailyTask.user_id == user.id,
        models.DailyTask.for_date >= week_ago,
    ).all()
    completion_rate = (sum(1 for t in week_tasks if t.done) / len(week_tasks)) if week_tasks else 0

    goal_data = []
    for goal in goals:
        analysis = goal.analysis()
        goal_data.append({
            "goal": goal,
            "analysis": analysis,
            "likelihood": analysis.get("likelihood_score", 0),
            "best_move": analysis.get("best_move_today", ""),
            "on_track": analysis.get("timeline", {}).get("on_track", True),
        })

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": user,
        "state": state,
        "goal_data": goal_data,
        "today_tasks": today_tasks,
        "today": today,
        "completion_rate": round(completion_rate * 100),
    })


@router.get("/goals/new", response_class=HTMLResponse)
async def new_goal_page(
    request: Request,
    user: models.User = Depends(auth_utils.require_user),
    db: Session = Depends(get_db),
):
    state = db.query(models.StrategicState).filter_by(user_id=user.id).first()
    if not state:
        return RedirectResponse(url="/onboarding", status_code=303)
    return templates.TemplateResponse("new_goal.html", {"request": request, "user": user})


@router.post("/goals/new")
async def create_goal(
    request: Request,
    title: str = Form(...),
    description: str = Form(default=""),
    target_date: str = Form(...),
    user: models.User = Depends(auth_utils.require_user),
    db: Session = Depends(get_db),
):
    state = db.query(models.StrategicState).filter_by(user_id=user.id).first()
    if not state:
        return RedirectResponse(url="/onboarding", status_code=303)

    # Create goal first with empty analysis
    goal = models.Goal(
        user_id=user.id,
        title=title.strip(),
        description=description.strip(),
        target_date=target_date,
        ai_analysis="{}",
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)

    # Run AI analysis
    analysis = await ai_engine.analyse_goal(
        goal_title=goal.title,
        goal_description=goal.description,
        target_date=goal.target_date,
        monthly_income=state.monthly_income,
        monthly_expenses=state.monthly_expenses,
        savings=state.savings,
        skills=state.skills_list(),
        constraints=state.constraints_list(),
        location=state.location,
        employment_type=state.employment_type,
        notes=state.notes,
    )

    goal.ai_analysis = json.dumps(analysis)
    db.commit()

    # Seed today's tasks from AI output
    _seed_daily_tasks(db, goal, analysis, user.id)

    # Log
    log_entry = models.ExecutionLog(
        user_id=user.id,
        goal_id=goal.id,
        event="goal_created",
        notes=f"AI analysis complete. Likelihood: {analysis.get('likelihood_score', '?')}%",
    )
    db.add(log_entry)
    db.commit()

    return RedirectResponse(url=f"/goals/{goal.id}", status_code=303)


@router.get("/goals/{goal_id}", response_class=HTMLResponse)
async def goal_detail(
    goal_id: int,
    request: Request,
    user: models.User = Depends(auth_utils.require_user),
    db: Session = Depends(get_db),
):
    goal = db.query(models.Goal).filter_by(id=goal_id, user_id=user.id).first()
    if not goal:
        raise HTTPException(status_code=404)

    analysis = goal.analysis()
    today = date.today()

    today_tasks = (
        db.query(models.DailyTask)
        .filter_by(goal_id=goal_id, for_date=today)
        .order_by(models.DailyTask.done, models.DailyTask.priority)
        .all()
    )

    # Completion stats
    all_tasks = db.query(models.DailyTask).filter_by(goal_id=goal_id).all()
    completed = sum(1 for t in all_tasks if t.done)
    completion_rate = (completed / len(all_tasks)) if all_tasks else 0

    # Days remaining
    try:
        target_dt = datetime.strptime(goal.target_date, "%Y-%m-%d").date()
        days_remaining = (target_dt - today).days
    except ValueError:
        days_remaining = 0

    return templates.TemplateResponse("goal.html", {
        "request": request,
        "user": user,
        "goal": goal,
        "analysis": analysis,
        "today_tasks": today_tasks,
        "completion_rate": round(completion_rate * 100),
        "days_remaining": days_remaining,
        "today": today,
    })


@router.post("/tasks/{task_id}/toggle")
async def toggle_task(
    task_id: int,
    user: models.User = Depends(auth_utils.require_user),
    db: Session = Depends(get_db),
):
    task = db.query(models.DailyTask).filter_by(id=task_id, user_id=user.id).first()
    if not task:
        raise HTTPException(status_code=404)

    task.done = not task.done
    task.done_at = datetime.utcnow() if task.done else None

    log_entry = models.ExecutionLog(
        user_id=user.id,
        goal_id=task.goal_id,
        task_id=task.id,
        event="task_done" if task.done else "task_undone",
    )
    db.add(log_entry)
    db.commit()

    return JSONResponse({"done": task.done, "task_id": task.id})


@router.post("/goals/{goal_id}/refresh-tasks")
async def refresh_tasks(
    goal_id: int,
    user: models.User = Depends(auth_utils.require_user),
    db: Session = Depends(get_db),
):
    """Regenerate today's tasks using AI based on completion history."""
    goal = db.query(models.Goal).filter_by(id=goal_id, user_id=user.id).first()
    if not goal:
        raise HTTPException(status_code=404)

    today = date.today()
    analysis = goal.analysis()
    all_tasks = db.query(models.DailyTask).filter_by(goal_id=goal_id).all()
    completion_rate = (sum(1 for t in all_tasks if t.done) / len(all_tasks)) if all_tasks else 0

    try:
        target_dt = datetime.strptime(goal.target_date, "%Y-%m-%d").date()
        days_remaining = (target_dt - today).days
    except ValueError:
        days_remaining = 0

    new_tasks = await ai_engine.refresh_daily_tasks(
        goal_title=goal.title,
        existing_analysis=analysis,
        completion_rate=completion_rate,
        days_remaining=days_remaining,
    )

    # Delete today's undone tasks and replace
    db.query(models.DailyTask).filter_by(goal_id=goal_id, for_date=today, done=False).delete()
    db.commit()

    priority_order = {"critical": 0, "high": 1, "medium": 2}
    for t in new_tasks:
        task = models.DailyTask(
            goal_id=goal_id,
            user_id=user.id,
            task=t.get("task", ""),
            priority=t.get("priority", "high"),
            time_required=t.get("time_required", ""),
            consequence_if_skipped=t.get("consequence_if_skipped", ""),
            for_date=today,
        )
        db.add(task)
    db.commit()

    return RedirectResponse(url=f"/goals/{goal_id}", status_code=303)


def _seed_daily_tasks(db, goal: models.Goal, analysis: dict, user_id: int):
    today = date.today()
    # Remove any existing tasks for today on this goal
    db.query(models.DailyTask).filter_by(goal_id=goal.id, for_date=today).delete()
    db.commit()

    for t in analysis.get("daily_tasks", []):
        task = models.DailyTask(
            goal_id=goal.id,
            user_id=user_id,
            task=t.get("task", ""),
            priority=t.get("priority", "high"),
            time_required=t.get("time_required", ""),
            consequence_if_skipped=t.get("consequence_if_skipped", ""),
            for_date=today,
        )
        db.add(task)
    db.commit()
