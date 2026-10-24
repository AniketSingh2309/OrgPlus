"""Classroom insights (free on every edition; needs ENABLE_CLASSROOM and the Classroom scopes).

Per course we keep a summary only: teachers, student count, assignments and
submission stats. Student work content is never read. Teachers are identified by
user id (emails need an extra scope) and matched to the directory. Activity
(posts, announcements, joins) comes from the Classroom audit log in `events`.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from statistics import median
from typing import Any

from fastapi import Depends
from googleapiclient.errors import HttpError
from sqlalchemy import text
from sqlalchemy.orm import Session

from orgpulse import google_client as g
from orgpulse.api.deps import Viewer, get_db, get_viewer
from orgpulse.features.registry import FeatureModule, UiCard, register
from orgpulse.modules._common import gated_router, load_snapshots, save_snapshots
from orgpulse.sync.mappers import parse_time

log = logging.getLogger(__name__)
router = gated_router("classroom")


def _turnaround_hours(sub: dict[str, Any]) -> float | None:
    """Hours from the student's last turn-in to the teacher returning it."""
    turned_in = returned = None
    for h in sub.get("submissionHistory") or []:
        state = h.get("stateHistory") or {}
        when = parse_time(state.get("stateTimestamp"))
        if state.get("state") == "TURNED_IN":
            turned_in = when
        elif state.get("state") == "RETURNED" and turned_in and when:
            returned = when
    if turned_in and returned and returned > turned_in:
        return (returned - turned_in).total_seconds() / 3600
    return None


def summarise_course(
    course: dict[str, Any],
    teachers: list[dict[str, Any]],
    students: int,
    work: list[dict[str, Any]],
    subs: list[dict[str, Any]],
) -> dict[str, Any]:
    now = datetime.now(UTC)
    due: dict[str, datetime] = {}
    for w in work:
        d = w.get("dueDate")
        if d:
            t = w.get("dueTime") or {}
            due[w["id"]] = datetime(
                d["year"],
                d["month"],
                d["day"],
                t.get("hours", 23),
                t.get("minutes", 59),
                tzinfo=UTC,
            )
    missing_by_student: dict[str, int] = defaultdict(int)
    turnarounds: list[float] = []
    for s in subs:
        if (
            s.get("state") not in ("TURNED_IN", "RETURNED")
            and s.get("courseWorkId") in due
            and due[s["courseWorkId"]] < now
        ):
            missing_by_student[s.get("userId", "?")] += 1
        h = _turnaround_hours(s)
        if h is not None:
            turnarounds.append(h)
    return {
        "id": course["id"],
        "name": course.get("name"),
        "section": course.get("section"),
        "state": course.get("courseState"),
        # userId matches the directory; the profile name works without the email scope
        "teachers": [
            {
                "id": t.get("userId"),
                "name": ((t.get("profile") or {}).get("name") or {}).get("fullName"),
            }
            for t in teachers
        ],
        "owner_id": course.get("ownerId"),
        "created": course.get("creationTime"),
        "updated": course.get("updateTime"),
        "link": course.get("alternateLink"),
        "students": students,
        "assignments": len(work),
        "assignments_this_month": sum(
            1
            for w in work
            if (parse_time(w.get("creationTime")) or now) >= now.replace(day=1, hour=0, minute=0)
        ),
        "median_grading_hours": round(median(turnarounds), 1) if turnarounds else None,
        "students_missing_work": len(missing_by_student),
        "missing_by_student": dict(sorted(missing_by_student.items(), key=lambda kv: -kv[1])[:50]),
    }


def sync_classroom(tenant_id: uuid.UUID) -> int:
    c = g.classroom()
    items = []
    for course in g.paginate(
        c.courses().list,
        "courses",
        what="courses.list",
        courseStates=["ACTIVE", "PROVISIONED", "ARCHIVED"],
        pageSize=100,
    ):
        cid = course["id"]
        try:
            teachers = list(
                g.paginate(
                    c.courses().teachers().list, "teachers", what="teachers.list", courseId=cid
                )
            )
            students = sum(
                1
                for _ in g.paginate(
                    c.courses().students().list, "students", what="students.list", courseId=cid
                )
            )
            work = list(
                g.paginate(
                    c.courses().courseWork().list,
                    "courseWork",
                    what="courseWork.list",
                    courseId=cid,
                )
            )
            subs = list(
                g.paginate(
                    c.courses().courseWork().studentSubmissions().list,
                    "studentSubmissions",
                    what="studentSubmissions.list",
                    courseId=cid,
                    courseWorkId="-",
                )
            )
        except HttpError as err:
            log.warning("classroom course %s skipped (HTTP %s)", cid, err.resp.status)
            continue
        items.append((cid, summarise_course(course, teachers, students, work, subs)))
    return save_snapshots(tenant_id, "classroom", items)


# Classroom audit-log event -> what it counts as
ACTIVITY_KIND = {
    "published_course_work": "posts",
    "created_course_work": "posts",
    "created_post": "posts",
    "published_announcement": "announcements",
    "created_announcement": "announcements",
    "updated_announcement": "announcements",
    "updated_course_work": "edits",
    "user_joined_course": "joins",
    "invited_user": "invites",
    "created_course": "courses_created",
}


@router.get("")
def classroom_summary(
    viewer: Viewer = Depends(get_viewer), db: Session = Depends(get_db)
) -> dict[str, Any]:
    t = viewer.tenant_id
    courses = load_snapshots(t, "classroom")
    people = {
        r.id: {"id": r.id, "name": r.full_name or r.primary_email, "email": r.primary_email}
        for r in db.execute(
            text("SELECT id, primary_email, full_name FROM users WHERE tenant_id = :t"), {"t": t}
        ).all()
    }

    def person(uid: str | None, fallback: str | None = None) -> dict[str, Any]:
        return people.get(uid or "", {"id": None, "name": fallback or "Unknown", "email": None})

    events = db.execute(
        text(
            """SELECT time, user_email, event_name, params FROM events
               WHERE tenant_id = :t AND app = 'classroom' ORDER BY time DESC LIMIT 2000"""
        ),
        {"t": t},
    ).all()
    activity_by_course: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    last_activity: dict[str, str] = {}
    by_actor: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e in events:
        kind = ACTIVITY_KIND.get(e.event_name, "other")
        cid = str(e.params.get("course_id") or "")
        activity_by_course[cid][kind] += 1
        last_activity.setdefault(cid, e.time.isoformat())
        if e.user_email:
            by_actor[e.user_email][kind] += 1

    out_courses = []
    per_teacher: dict[str, dict[str, Any]] = {}
    for co in courses:
        teachers = [
            person(tch.get("id"), tch.get("name")) if isinstance(tch, dict) else person(None, tch)
            for tch in co.get("teachers", [])
        ]
        act = activity_by_course.get(co["id"], {})
        out_courses.append(
            {
                **co,
                "teachers": teachers,
                "owner": person(co.get("owner_id")) if co.get("owner_id") else None,
                "posts": act.get("posts", 0),
                "announcements": act.get("announcements", 0),
                "joins": act.get("joins", 0),
                "last_activity": last_activity.get(co["id"]),
            }
        )
        for tch in teachers:
            key = tch["email"] or tch["name"]
            p = per_teacher.setdefault(
                key, {**tch, "classes": 0, "students": 0, "assignments": 0, "grading": []}
            )
            p["classes"] += 1
            p["students"] += co.get("students", 0)
            p["assignments"] += co.get("assignments", 0)
            if co.get("median_grading_hours") is not None:
                p["grading"].append(co["median_grading_hours"])
    teachers_out = []
    for p in per_teacher.values():
        acts = by_actor.get(p["email"] or "", {})
        teachers_out.append(
            {
                **{k: v for k, v in p.items() if k != "grading"},
                "posts": acts.get("posts", 0),
                "announcements": acts.get("announcements", 0),
                "median_grading_hours": round(median(p["grading"]), 1) if p["grading"] else None,
            }
        )
    totals: dict[str, int] = defaultdict(int)
    for co in out_courses:
        for k in ("students", "assignments", "posts", "announcements"):
            totals[k] += co.get(k, 0)
    return {
        "courses": sorted(
            out_courses,
            key=lambda c: (
                c.get("state") != "ACTIVE",
                -(c.get("students") or 0),
                c.get("name") or "",
            ),
        ),
        "teachers": sorted(teachers_out, key=lambda x: (-x["classes"], x["name"])),
        "students_missing_work": sum(c.get("students_missing_work", 0) for c in courses),
        "totals": {
            **totals,
            "courses": len(out_courses),
            "active_courses": sum(1 for c in out_courses if c.get("state") == "ACTIVE"),
        },
        "recent_activity": [
            {
                "time": e.time.isoformat(),
                "user": e.user_email,
                "event": e.event_name,
                "course": e.params.get("course_title"),
                "title": e.params.get("course_work_title"),
                "kind": ACTIVITY_KIND.get(e.event_name, "other"),
            }
            for e in events[:50]
        ],
    }


register(
    FeatureModule(
        key="classroom",
        title="Classroom insights",
        requires="Classroom turned on (ENABLE_CLASSROOM)",
        description="Classes, teachers, posts and assignments, grading turnaround and students with missing work.",
        how_to_enable="https://support.google.com/edu/classroom/answer/6250906",
        page="/m/classroom",
        paid=False,
        router=router,
        sync=sync_classroom,
        schedule={"trigger": "interval", "hours": 12},
        cards=[
            UiCard("classroom", "Classroom", "Teaching load, grading turnaround and missing work.")
        ],
    )
)
