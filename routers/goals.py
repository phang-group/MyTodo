import json
from pathlib import Path
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db
import models
import gateway_auth
import ai_engine

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/onboarding", response_class=HTMLResponse)
async def onboarding_page(
    request: Request,
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]
    state = db.query(models.StrategicState).filter_by(gateway_user_id=uid).first()
    return templates.TemplateResponse("onboarding.html", {
        "request": request,
        "user": identity,
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
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]
    skills_list = [s.strip() for s in skills.split(",") if s.strip()]
    constraints_list = [c.strip() for c in constraints.split(",") if c.strip()]

    state = db.query(models.StrategicState).filter_by(gateway_user_id=uid).first()
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
            gateway_user_id=uid,
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
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]
    state = db.query(models.StrategicState).filter_by(gateway_user_id=uid).first()
    if not state:
        return RedirectResponse(url="/onboarding", status_code=303)

    goals = db.query(models.Goal).filter_by(gateway_user_id=uid, status="active").all()
    today = date.today()

    today_tasks = (
        db.query(models.DailyTask)
        .filter_by(gateway_user_id=uid, for_date=today)
        .order_by(models.DailyTask.done, models.DailyTask.priority)
        .all()
    )

    week_ago = today - timedelta(days=7)
    week_tasks = db.query(models.DailyTask).filter(
        models.DailyTask.gateway_user_id == uid,
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
        "user": identity,
        "state": state,
        "goal_data": goal_data,
        "today_tasks": today_tasks,
        "today": today,
        "completion_rate": round(completion_rate * 100),
    })


@router.get("/goals/new", response_class=HTMLResponse)
async def new_goal_page(
    request: Request,
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]
    state = db.query(models.StrategicState).filter_by(gateway_user_id=uid).first()
    if not state:
        return RedirectResponse(url="/onboarding", status_code=303)
    return templates.TemplateResponse("new_goal.html", {"request": request, "user": identity})


@router.post("/goals/new")
async def create_goal(
    request: Request,
    title: str = Form(...),
    description: str = Form(default=""),
    target_date: str = Form(...),
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]
    state = db.query(models.StrategicState).filter_by(gateway_user_id=uid).first()
    if not state:
        return RedirectResponse(url="/onboarding", status_code=303)

    goal = models.Goal(
        gateway_user_id=uid,
        title=title.strip(),
        description=description.strip(),
        target_date=target_date,
        ai_analysis="{}",
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)

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

    _seed_daily_tasks(db, goal, analysis, uid)

    log_entry = models.ExecutionLog(
        gateway_user_id=uid,
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
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]
    goal = db.query(models.Goal).filter_by(id=goal_id, gateway_user_id=uid).first()
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

    all_tasks = db.query(models.DailyTask).filter_by(goal_id=goal_id).all()
    completed = sum(1 for t in all_tasks if t.done)
    completion_rate = (completed / len(all_tasks)) if all_tasks else 0

    try:
        target_dt = datetime.strptime(goal.target_date, "%Y-%m-%d").date()
        days_remaining = (target_dt - today).days
    except ValueError:
        days_remaining = 0

    return templates.TemplateResponse("goal.html", {
        "request": request,
        "user": identity,
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
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]
    task = db.query(models.DailyTask).filter_by(id=task_id, gateway_user_id=uid).first()
    if not task:
        raise HTTPException(status_code=404)

    task.done = not task.done
    task.done_at = datetime.utcnow() if task.done else None

    log_entry = models.ExecutionLog(
        gateway_user_id=uid,
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
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]
    goal = db.query(models.Goal).filter_by(id=goal_id, gateway_user_id=uid).first()
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

    db.query(models.DailyTask).filter_by(goal_id=goal_id, for_date=today, done=False).delete()
    db.commit()

    for t in new_tasks:
        task = models.DailyTask(
            goal_id=goal_id,
            gateway_user_id=uid,
            task=t.get("task", ""),
            priority=t.get("priority", "high"),
            time_required=t.get("time_required", ""),
            consequence_if_skipped=t.get("consequence_if_skipped", ""),
            for_date=today,
        )
        db.add(task)
    db.commit()

    return RedirectResponse(url=f"/goals/{goal_id}", status_code=303)


@router.get("/goals/{goal_id}/reflect", response_class=HTMLResponse)
async def reflect_page(
    goal_id: int,
    request: Request,
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]
    goal = db.query(models.Goal).filter_by(id=goal_id, gateway_user_id=uid).first()
    if not goal:
        raise HTTPException(status_code=404)

    sessions = (
        db.query(models.ReflectionSession)
        .filter_by(goal_id=goal_id, gateway_user_id=uid)
        .order_by(models.ReflectionSession.session_number)
        .all()
    )

    # Build previous session history for the AI
    previous = [
        {"domain": s.domain, "question": s.question, "answer": s.answer}
        for s in sessions if s.answer
    ]
    session_number = len(sessions) + 1

    # Generate the next question (only if the last session is answered or no sessions yet)
    pending = next((s for s in sessions if not s.answer), None)
    if pending:
        current_session = pending
    else:
        q_data = await ai_engine.generate_reflection_question(
            goal_title=goal.title,
            goal_description=goal.description,
            previous_sessions=previous,
            session_number=session_number,
        )
        if "error" in q_data:
            raise HTTPException(status_code=502, detail=q_data["error"])

        current_session = models.ReflectionSession(
            gateway_user_id=uid,
            goal_id=goal_id,
            session_number=session_number,
            domain=q_data.get("domain", ""),
            question=q_data.get("question", ""),
        )
        db.add(current_session)
        db.commit()
        db.refresh(current_session)

    return templates.TemplateResponse("reflect.html", {
        "request": request,
        "user": identity,
        "goal": goal,
        "current_session": current_session,
        "sessions": sessions,
        "session_number": current_session.session_number,
    })


@router.post("/goals/{goal_id}/reflect/{session_id}")
async def submit_reflection(
    goal_id: int,
    session_id: int,
    answer: str = Form(...),
    identity: dict = Depends(gateway_auth.require_identity),
    db: Session = Depends(get_db),
):
    uid = identity["user_id"]
    session = db.query(models.ReflectionSession).filter_by(
        id=session_id, goal_id=goal_id, gateway_user_id=uid
    ).first()
    if not session:
        raise HTTPException(status_code=404)

    session.answer = answer.strip()
    db.commit()

    # Collect all previous insights across sessions for this goal
    all_sessions = (
        db.query(models.ReflectionSession)
        .filter_by(goal_id=goal_id, gateway_user_id=uid)
        .filter(models.ReflectionSession.processed == True)
        .all()
    )
    previous_insights = []
    for s in all_sessions:
        previous_insights.extend(s.insights_list())

    result = await ai_engine.process_reflection_answer(
        goal_title=session.goal.title,
        question=session.question,
        answer=session.answer,
        previous_insights=previous_insights,
    )

    session.insights = json.dumps(result.get("insights", []))
    session.processed = True
    db.commit()

    # Update CognitiveState
    state = db.query(models.CognitiveState).filter_by(gateway_user_id=uid).first()
    if not state:
        state = models.CognitiveState(gateway_user_id=uid, goal_id=goal_id)
        db.add(state)
    state.last_reflection_at = datetime.utcnow()
    state.updated_at = datetime.utcnow()
    db.commit()

    # If the AI suggested refining the goal title, store it in the analysis blob
    refinement = result.get("suggested_goal_refinement")
    if refinement:
        analysis = session.goal.analysis()
        analysis["suggested_goal_refinement"] = refinement
        session.goal.ai_analysis = json.dumps(analysis)
        db.commit()

    # Log the event
    db.add(models.ExecutionLog(
        gateway_user_id=uid,
        goal_id=goal_id,
        event="reflection_answered",
        notes=f"Domain: {session.domain}. Insights: {len(result.get('insights', []))}",
    ))
    db.commit()

    return RedirectResponse(url=f"/goals/{goal_id}/reflect", status_code=303)


def _seed_daily_tasks(db, goal: models.Goal, analysis: dict, gateway_user_id: int):
    today = date.today()
    db.query(models.DailyTask).filter_by(goal_id=goal.id, for_date=today).delete()
    db.commit()

    for t in analysis.get("daily_tasks", []):
        task = models.DailyTask(
            goal_id=goal.id,
            gateway_user_id=gateway_user_id,
            task=t.get("task", ""),
            priority=t.get("priority", "high"),
            time_required=t.get("time_required", ""),
            consequence_if_skipped=t.get("consequence_if_skipped", ""),
            for_date=today,
        )
        db.add(task)
    db.commit()
