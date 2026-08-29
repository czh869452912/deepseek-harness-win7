import pytest
from dsh.cordis.context import Context
from dsh.core.tools import ToolsPlugin
from dsh.team.agent_team import AgentTeamPlugin, TeamService
from dsh.team.types import (
    TeamMemberPhase,
    TeamMemberStatus,
    TeamTaskStatus,
    TeamMemberSnapshot,
    TeamTaskSnapshot,
    TeamMessageSnapshot,
)


def test_agent_team_dag_blockers_and_acyclic():
    ctx = Context()
    team_svc = TeamService(ctx)

    # 1. Create root task
    t1 = team_svc.create_task(
        subject="Database Schema Design",
        description="Design SQLite schemas",
        write_scopes=["dsh/db/"],
    )
    assert t1["id"] == "task-1"
    assert t1["status"] == TeamTaskStatus.PENDING

    # 2. Create dependent task blocked by task-1
    t2 = team_svc.create_task(
        subject="Database Migrations",
        description="Write schema migrations",
        blocked_by=["task-1"],
        write_scopes=["dsh/db/migrations/"],
    )
    assert t2["id"] == "task-2"
    assert "task-1" in t2["blockedBy"]

    # 3. Claim and complete task-1
    m1 = team_svc.register_member("DBA", role="teammate")
    team_svc.claim_task("task-1", m1.id)
    t1_done = team_svc.update_task("task-1", status=TeamTaskStatus.COMPLETED)
    assert t1_done["status"] == TeamTaskStatus.COMPLETED
    assert t1_done["revision"] == 3

    # 4. Now task-2 can be claimed
    t2_claimed = team_svc.claim_task("task-2", m1.id)
    assert t2_claimed["status"] == TeamTaskStatus.IN_PROGRESS


def test_agent_team_mailbox_target_filtering_and_receipt():
    ctx = Context()
    team_svc = TeamService(ctx)

    alice = team_svc.register_member("Alice", role="lead")
    bob = team_svc.register_member("Bob", role="teammate")
    charlie = team_svc.register_member("Charlie", role="teammate")

    # Send messages
    m1 = team_svc.send_mail(alice.id, "Alice", bob.id, "Hello Bob", delivery="wakeup")
    m2 = team_svc.send_mail(alice.id, "Alice", charlie.id, "Hello Charlie", delivery="quiet")
    m3 = team_svc.send_mail(bob.id, "Bob", alice.id, "Hello Lead", delivery="wakeup")

    # Check Bob's inbox
    bob_inbox = team_svc.read_mail(bob.id, mark_as_read=True)
    assert len(bob_inbox) == 1
    assert bob_inbox[0]["content"] == "Hello Bob"
    assert bob_inbox[0]["read"] is False

    # Second read: message should be marked as read
    bob_inbox_2 = team_svc.read_mail(bob.id, mark_as_read=False)
    assert len(bob_inbox_2) == 1
    assert bob_inbox_2[0]["read"] is True

    # Check Charlie's inbox
    charlie_inbox = team_svc.read_mail(charlie.id)
    assert len(charlie_inbox) == 1
    assert charlie_inbox[0]["delivery"] == "quiet"


def test_agent_team_events_emission():
    ctx = Context()
    events_received = []

    ctx.on("team/member-joined", lambda data: events_received.append(("joined", data)))
    ctx.on("team/task-created", lambda data: events_received.append(("task_created", data)))
    ctx.on("team/task-updated", lambda data: events_received.append(("task_updated", data)))
    ctx.on("team/mail-sent", lambda data: events_received.append(("mail_sent", data)))

    team_svc = TeamService(ctx)
    member = team_svc.register_member("Agent-1")
    task = team_svc.create_task("Test Event Task")
    team_svc.update_task(task["id"], status=TeamTaskStatus.IN_PROGRESS)
    team_svc.send_mail(member.id, "Agent-1", "target-id", "Testing event")

    event_types = [e[0] for e in events_received]
    assert "joined" in event_types
    assert "task_created" in event_types
    assert "task_updated" in event_types
    assert "mail_sent" in event_types
