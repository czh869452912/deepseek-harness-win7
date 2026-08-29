from dsh.cordis.context import Context
from dsh.core.tools import ToolsPlugin
from dsh.team.agent_team import AgentTeamPlugin, TeamService
from dsh.team.tool_agent_team import ToolAgentTeamPlugin
from dsh.team.types import TeamTaskStatus


def test_agent_team_roster_and_tasks():
    ctx = Context()
    ctx.plugin(ToolsPlugin)
    ctx.plugin(AgentTeamPlugin)
    ctx.plugin(ToolAgentTeamPlugin)

    team_svc = ctx.get("agentTeams")
    assert team_svc is not None

    # 1. Register members
    lead = team_svc.register_member("Leader", role="lead")
    worker = team_svc.register_member("Coder", role="teammate")

    members = team_svc.list_members()
    assert len(members) == 2
    assert any(m["name"] == "Leader" for m in members)

    # 2. Task lifecycle
    task = team_svc.create_task("Fix parser", "Fix the AST parser issue")
    assert task["status"] == TeamTaskStatus.PENDING

    claimed = team_svc.claim_task(task["id"], worker.id)
    assert claimed["status"] == TeamTaskStatus.IN_PROGRESS
    assert claimed["ownerId"] == worker.id

    updated = team_svc.update_task(task["id"], status=TeamTaskStatus.COMPLETED)
    assert updated["status"] == TeamTaskStatus.COMPLETED

    # 3. Mailbox
    mail = team_svc.send_mail(
        sender_id=lead.id,
        sender_name="Leader",
        target_id=worker.id,
        content="Please review task 1",
    )
    assert mail["read"] is False

    inbox = team_svc.read_mail(worker.id)
    assert len(inbox) == 1
    assert inbox[0]["content"] == "Please review task 1"


def test_agent_team_tools_invocation():
    ctx = Context()
    ctx.plugin(ToolsPlugin)
    ctx.plugin(AgentTeamPlugin)
    ctx.plugin(ToolAgentTeamPlugin)

    tools_svc = ctx.get("tools")
    assert tools_svc.has_tool("team_member_list")
    assert tools_svc.has_tool("team_task_create")
    assert tools_svc.has_tool("team_task_claim")
    assert tools_svc.has_tool("team_task_update")
    assert tools_svc.has_tool("team_task_list")
    assert tools_svc.has_tool("team_send_mail")
    assert tools_svc.has_tool("team_read_mail")

    # Create task via tool handler
    tool = tools_svc.get_tool("team_task_create")
    assert tool is not None
    res = tool.handler(subject="Tool Task", description="Via Tool")
    assert "task" in res
    tid = res["task"]["id"]

    # List tasks via tool handler
    list_tool = tools_svc.get_tool("team_task_list")
    assert list_tool is not None
    list_res = list_tool.handler()
    assert len(list_res["tasks"]) >= 1

