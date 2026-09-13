"""Transactional project task/contract graph. Stdlib only, Python 3.8."""
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def components(graph):
    """Tarjan SCC; runtime cycles are scheduled as one atomic change group."""
    stack, active, indexes, low, result = [], set(), {}, {}, []

    def visit(node):
        indexes[node] = low[node] = len(indexes)
        stack.append(node)
        active.add(node)
        for dep in graph.get(node, []):
            if dep not in graph:
                continue
            if dep not in indexes:
                visit(dep)
                low[node] = min(low[node], low[dep])
            elif dep in active:
                low[node] = min(low[node], indexes[dep])
        if low[node] == indexes[node]:
            group = []
            while True:
                member = stack.pop()
                active.remove(member)
                group.append(member)
                if member == node:
                    break
            result.append(sorted(group))

    for node in sorted(graph):
        if node not in indexes:
            visit(node)
    return result


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks(
                id TEXT PRIMARY KEY, spec TEXT NOT NULL, state TEXT NOT NULL,
                created REAL NOT NULL, updated REAL NOT NULL, owner TEXT,
                worktree TEXT, base TEXT, head TEXT, run_dir TEXT,
                feedback TEXT, error TEXT, round INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS edges(
                task TEXT NOT NULL, dependency TEXT NOT NULL, kind TEXT NOT NULL,
                evidence TEXT NOT NULL, PRIMARY KEY(task,dependency,kind));
            CREATE TABLE IF NOT EXISTS contracts(
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, spec TEXT NOT NULL, hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS evidence(
                task TEXT PRIMARY KEY, upstream TEXT NOT NULL, head TEXT NOT NULL,
                contracts TEXT NOT NULL, tests TEXT NOT NULL, environment TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(
                seq INTEGER PRIMARY KEY AUTOINCREMENT, time REAL NOT NULL,
                task TEXT, kind TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS writes(
                task TEXT NOT NULL, path TEXT NOT NULL, PRIMARY KEY(task,path));
            """)

    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def event(db, task, kind, data):
        db.execute("INSERT INTO events(time,task,kind,data) VALUES(?,?,?,?)",
                   (time.time(), task, kind, json.dumps(data, ensure_ascii=False)))

    def meta(self, key, value=None):
        with self.connect() as db:
            if value is not None:
                db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, json.dumps(value)))
                return value
            row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def apply_plan(self, plan):
        """Validate all references before one atomic update; never reset completed work."""
        tasks = plan.get("tasks", [])
        if not isinstance(tasks, list) or not tasks:
            raise ValueError("Plan requires tasks")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            known = {r[0] for r in db.execute("SELECT id FROM tasks")}
            ids = [t.get("id") for t in tasks]
            if any(not isinstance(i, str) or not i.strip() for i in ids) or len(set(ids)) != len(ids):
                raise ValueError("Task IDs must be unique nonempty strings")
            known.update(ids)
            definitions = plan.get("contracts", [])
            contract_ids = [c.get("id") for c in definitions]
            if any(not isinstance(c, str) or not c.strip() for c in contract_ids) or len(set(contract_ids)) != len(contract_ids):
                raise ValueError("Contract IDs must be unique nonempty strings")
            contracts = {r[0] for r in db.execute("SELECT id FROM contracts")}
            contracts.update(contract_ids)
            missing = {}
            for task in tasks:
                for dep in task.get("dependencies", []):
                    if dep.get("task") not in known or not dep.get("evidence"):
                        raise ValueError("Unknown dependency or missing evidence: " + str(dep))
                for cid in task.get("consumes", []) + task.get("provides", []):
                    if cid not in contracts:
                        missing.setdefault(cid, []).append(task["id"])
            if missing:
                raise ValueError("Unknown contracts (define each in contracts with owner, evidence and paths): " +
                                 json.dumps(missing, sort_keys=True))
            changed_tasks = set()
            changed_owners = set()
            for task in tasks:
                for field in ("owner", "goal", "evidence"):
                    if not isinstance(task.get(field), str) or not task[field].strip():
                        raise ValueError("Task requires " + field)
                if not isinstance(task.get("wave", 5), int) or not isinstance(task.get("priority", 0), int):
                    raise ValueError("Wave and priority must be integers")
                if not isinstance(task.get("atomic_group", ""), str):
                    raise ValueError("atomic_group must be a string")
                if not isinstance(task.get("write_paths", []), list):
                    raise ValueError("write_paths must be a list")
                for path in task.get("write_paths", []):
                    if (not isinstance(path, str) or not path or path.startswith(("/", "\\")) or
                            ":" in path or "\\" in path or ".." in path.split("/")):
                        raise ValueError("write_paths must be repository-relative paths")
                for dep in task.get("dependencies", []):
                    if dep.get("task") not in known or not dep.get("evidence"):
                        raise ValueError("Unknown dependency or missing evidence: " + str(dep))
                    if dep.get("kind") not in ("implementation", "contract", "acceptance", "change"):
                        raise ValueError("Unknown edge kind")
                for contract in task.get("consumes", []) + task.get("provides", []):
                    if contract not in contracts:
                        raise ValueError("Unknown contract " + contract)
                old = db.execute("SELECT spec,state FROM tasks WHERE id=?", (task["id"],)).fetchone()
                if old and json.loads(old[0]) != task and old[1] == "RUNNING":
                    raise ValueError("Cannot change the acceptance contract of a running task")
                now = time.time()
                if not old:
                    db.execute("INSERT INTO tasks(id,spec,state,created,updated) VALUES(?,?,?,?,?)",
                               (task["id"], json.dumps(task), "READY", now, now))
                elif json.loads(old[0]) != task:
                    changed_tasks.add(task["id"])
                    db.execute("UPDATE tasks SET spec=?,state='NEEDS_REVALIDATION',updated=? WHERE id=?",
                               (json.dumps(task), now, task["id"]))
                db.execute("DELETE FROM edges WHERE task=?", (task["id"],))
                for dep in task.get("dependencies", []):
                    db.execute("INSERT INTO edges VALUES(?,?,?,?)",
                               (task["id"], dep["task"], dep["kind"], dep["evidence"]))
                self.event(db, task["id"], "plan", task)
            for contract in plan.get("contracts", []):
                if contract.get("owner") not in known or not contract.get("evidence"):
                    raise ValueError("Contract requires existing owner and source evidence")
                old = db.execute("SELECT hash,spec FROM contracts WHERE id=?", (contract["id"],)).fetchone()
                # Implementation fingerprints belong to the controller, not the planner.
                contract = dict(contract)
                contract.pop("implementation", None)
                if old and "implementation" in json.loads(old[1]):
                    contract["implementation"] = json.loads(old[1])["implementation"]
                version = digest(contract)
                db.execute("INSERT OR REPLACE INTO contracts VALUES(?,?,?,?)",
                           (contract["id"], contract["owner"], json.dumps(contract), version))
                if old and old[0] != version:
                    changed_owners.update((contract["owner"], json.loads(old[1])["owner"]))
            # Recompute implicit edges for all consumers if ownership was moved.
            db.execute("DELETE FROM edges WHERE evidence LIKE 'consumes %'")
            for stored in db.execute("SELECT spec FROM tasks").fetchall():
                task = json.loads(stored[0])
                for cid in task.get("consumes", []):
                    owner = db.execute("SELECT owner FROM contracts WHERE id=?", (cid,)).fetchone()[0]
                    if owner != task["id"]:
                        db.execute("INSERT OR IGNORE INTO edges VALUES(?,?,?,?)",
                                   (task["id"], owner, "contract", "consumes " + cid))
            self.invalidate(db, changed_tasks, "Upstream task acceptance changed")
            self.invalidate(db, changed_owners, "Contract specification changed")
            # Persist explicit cyclic groups for inspection, not mutual BLOCKED states.
            self.event(db, None, "groups", self.groups(db))

    @staticmethod
    def invalidate(db, owners, reason):
        affected = set(owners)
        while True:
            extra = {r[0] for r in db.execute("SELECT task,dependency FROM edges") if r[1] in affected}
            if extra <= affected:
                break
            affected.update(extra)
        for task in affected:
            # In-flight evidence is checked against captured contract hashes on completion.
            db.execute("UPDATE tasks SET state='NEEDS_REVALIDATION',error=? WHERE id=? "
                       "AND state IN ('INTEGRATED','VERIFIED')", (reason, task))
        return affected

    def rows(self):
        with self.connect() as db:
            result = [dict(r) for r in db.execute("SELECT * FROM tasks ORDER BY id")]
            for row in result:
                row["spec"] = json.loads(row["spec"])
                row["feedback"] = json.loads(row["feedback"]) if row["feedback"] else None
            return result

    @staticmethod
    def groups(db):
        """Cycles require an explicit shared atomic group; never swallow a product."""
        graph = {r[0]: [] for r in db.execute("SELECT id FROM tasks")}
        specs = {r[0]: json.loads(r[1]) for r in db.execute("SELECT id,spec FROM tasks")}
        atomic = {}
        for task, spec in specs.items():
            if spec.get("atomic_group"):
                atomic.setdefault(spec["atomic_group"], []).append(task)
        for members in atomic.values():
            for task in members:
                graph[task].extend(t for t in members if t != task)
        for task, dependency in db.execute("SELECT task,dependency FROM edges"):
            graph[task].append(dependency)
        result = []
        for group in components(graph):
            names = {specs[t].get("atomic_group") for t in group}
            if len(group) == 1 or (len(names) == 1 and next(iter(names))):
                result.append(group)
            else:
                result.extend([[t] for t in group])
        return result

    @staticmethod
    def resources(db, ids):
        specs = [json.loads(r[0]) for t in ids for r in db.execute("SELECT spec FROM tasks WHERE id=?", (t,))]
        contracts = {c for s in specs for c in s.get("provides", [])}
        paths = {p for s in specs for p in s.get("write_paths", [])}
        paths.update(r[0] for t in ids for r in db.execute("SELECT path FROM writes WHERE task=?", (t,)))
        for cid in contracts:
            row = db.execute("SELECT spec FROM contracts WHERE id=?", (cid,)).fetchone()
            if row:
                paths.update(p for p in json.loads(row[0]).get("paths", []) if not p.startswith("reference/"))
        return contracts, {p.replace("\\", "/").strip("/").lower() for p in paths}

    @staticmethod
    def overlapping(left, right):
        return bool(left[0] & right[0]) or any(
            a == b or a.startswith(b + "/") or b.startswith(a + "/")
            for a in left[1] for b in right[1])

    def observe_writes(self, group, paths):
        """Persist discovered cross-module writes; defer review if another writer owns them.

        Workers may expand their scope. Changes stay isolated, and scope acquisition
        precedes review/integration rather than discarding useful work on conflict.
        """
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for task in group["ids"]:
                if db.execute("SELECT owner FROM tasks WHERE id=?", (task,)).fetchone()[0] != group["token"]:
                    raise ValueError("Lost task ownership")
                for path in paths:
                    db.execute("INSERT OR IGNORE INTO writes VALUES(?,?)", (task, path))
            own = self.resources(db, group["ids"])
            peers = [r[0] for r in db.execute("SELECT id FROM tasks WHERE state IN ('RUNNING','VERIFIED')")
                     if r[0] not in group["ids"]]
            return [t for t in peers if self.overlapping(own, self.resources(db, [t]))]

    def claim(self, worker, only_task=None, allowed_group=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = {r["id"]: dict(r) for r in db.execute("SELECT * FROM tasks")}
            edges = list(db.execute("SELECT task,dependency FROM edges"))
            active = [r for r in rows.values() if r["state"] in ("RUNNING", "VERIFIED", "INTEGRATION_REPAIR")]
            resources = {t: self.resources(db, [t]) for t in rows}
            candidates = []
            pending = set()
            claim_time = time.time()
            for row in rows.values():
                if row["state"] == "WAITING_PLAN" and row["feedback"]:
                    proposal = json.loads(row["feedback"]).get("proposed_work_plan", {})
                    pending.update(t["id"] for t in proposal.get("tasks", []))
            for group in self.groups(db):
                if only_task is not None and only_task not in group:
                    continue
                if allowed_group is not None and not set(group).issubset(allowed_group):
                    reason = 'Pilot group expanded beyond its starting scope: ' + ', '.join(group)
                    db.execute("UPDATE tasks SET state='NEEDS_ARBITRATION',error=? WHERE id=?",
                               (reason, only_task))
                    self.event(db, only_task, 'pilot_scope_expansion', reason)
                    continue
                if pending.intersection(group):
                    continue
                members = [rows[t] for t in group]
                if any(r["state"] not in ("READY", "NEEDS_REVALIDATION", "INTEGRATED", "INTEGRATION_REPAIR") for r in members):
                    continue
                if any(r['state'] == 'INTEGRATION_REPAIR' for r in members) and any(
                        r['id'] not in group and r['state'] in ('RUNNING', 'VERIFIED') and
                        (json.loads(r['feedback']) if r['feedback'] else {}).get('integration_handoff') for r in active):
                    continue  # One integrator owns combined-candidate repair at a time.
                if all(r["state"] == "INTEGRATED" for r in members):
                    continue
                external = {dep for task, dep in edges if task in group and dep not in group}
                if any(rows[d]["state"] != "INTEGRATED" for d in external):
                    continue
                specs = [json.loads(r["spec"]) for r in members]
                if any(self.overlapping(resources[t], resources[r["id"]]) or
                       (rows[t]["worktree"] and rows[t]["worktree"] == r["worktree"])
                       for t in group for r in active if r["id"] not in group):
                    continue
                downstream = {t for t, dep in edges if dep in group}
                while True:
                    expanded = {t for t, dep in edges if dep in downstream} | downstream
                    if expanded == downstream:
                        break
                    downstream = expanded
                age = (claim_time - min(r["created"] for r in members)) / 3600
                score = max(s.get("priority", 0) for s in specs) + len(downstream) * 10 + age
                candidates.append((min(s.get("wave", 5) for s in specs), -score, group))
            if not candidates:
                return None
            group = min(candidates)[2]
            token = worker + ":" + uuid.uuid4().hex
            for task in group:
                db.execute("UPDATE tasks SET state='RUNNING',owner=?,updated=?,error=NULL WHERE id=?",
                           (token, time.time(), task))
                self.event(db, task, "claimed", token)
            return {"ids": group, "token": token, "tasks": [json.loads(rows[t]["spec"]) for t in group],
                    "records": [rows[t] for t in group]}

    def update(self, group, state=None, **fields):
        allowed = {"worktree", "base", "head", "run_dir", "feedback", "error", "round"}
        if set(fields) - allowed:
            raise ValueError("Unknown fields")
        if "feedback" in fields:
            fields["feedback"] = json.dumps(fields["feedback"])
        if state:
            fields["state"] = state
        fields["updated"] = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for task in group["ids"]:
                owner = db.execute("SELECT owner FROM tasks WHERE id=?", (task,)).fetchone()
                if not owner or owner[0] != group["token"]:
                    raise ValueError("Lost task ownership")
                db.execute("UPDATE tasks SET " + ",".join(k + "=?" for k in fields) + " WHERE id=?",
                           list(fields.values()) + [task])
                self.event(db, task, "state", {"state": state, **fields})

    def contract_hashes(self):
        with self.connect() as db:
            return {r[0]: r[1] for r in db.execute("SELECT id,hash FROM contracts")}

    def plan_is_current(self, plan):
        with self.connect() as db:
            for task in plan.get("tasks", []):
                row = db.execute("SELECT spec FROM tasks WHERE id=?", (task.get("id"),)).fetchone()
                if not row or json.loads(row[0]) != task:
                    return False
            for contract in plan.get("contracts", []):
                row = db.execute("SELECT spec FROM contracts WHERE id=?", (contract.get("id"),)).fetchone()
                if not row:
                    return False
                current = json.loads(row[0])
                current.pop("implementation", None)
                proposed = dict(contract)
                proposed.pop("implementation", None)
                if current != proposed:
                    return False
            return bool(plan.get("tasks"))

    def record_evidence(self, group, upstream, head, hashes, tests):
        import platform
        with self.connect() as db:
            for task in group["ids"]:
                self.event(db, task, "evidence", {"upstream": upstream, "head": head,
                           "contracts": hashes, "tests": tests,
                           "environment": {"python": platform.python_version(), "os": platform.platform()}})
                db.execute("INSERT OR REPLACE INTO evidence VALUES(?,?,?,?,?,?)",
                           (task, upstream, head, json.dumps(hashes), json.dumps(tests),
                            json.dumps({"python": platform.python_version(), "os": platform.platform()})))

    def integrate(self, group, head, changes, worktree=None):
        """Invalidates reverse consumers when a provided implementation changes."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            owners = set()
            for task in group["ids"]:
                row = db.execute("SELECT owner FROM tasks WHERE id=?", (task,)).fetchone()
                if not row or row[0] != group["token"]:
                    raise ValueError("Lost task ownership")
            provided = {cid for spec in group["tasks"] for cid in spec.get("provides", [])}
            for row in db.execute("SELECT id,spec,hash,owner FROM contracts").fetchall():
                cid = row[0]
                data = json.loads(row[1])
                previous = data.get("implementation", {})
                matched = {p: h for p, h in changes.items()
                           if any(p == q or p.startswith(q.rstrip('/') + '/') for q in data.get("paths", []))}
                if not data.get("paths") and cid in provided:
                    matched = changes  # Unknown mapping: conservatively invalidate.
                if matched:
                    data["implementation"] = dict(previous, **matched)
                    version = digest(data)
                    if version != row[2]:
                        owners.add(row[3])
                        db.execute("UPDATE contracts SET spec=?,hash=? WHERE id=?", (json.dumps(data), version, cid))
            self.invalidate(db, owners, "Provider implementation changed at " + head)
            for task in group["ids"]:
                db.execute("UPDATE tasks SET state='INTEGRATED',head=?,error=NULL,updated=? WHERE id=?",
                           (head, time.time(), task))
                self.event(db, task, "integrated", head)
                if worktree is not None:
                    db.execute("UPDATE tasks SET worktree=?,base=? WHERE id=?",
                               (worktree, head, task))

    def recover(self, task):
        """Explicit operator recovery after checking the former owner's processes."""
        with self.connect() as db:
            row = db.execute("SELECT owner FROM tasks WHERE id=?", (task,)).fetchone()
            if not row:
                raise ValueError("Unknown task")
            members = db.execute("SELECT id FROM tasks WHERE owner=?", (row[0],)).fetchall() if row[0] else [(task,)]
            for member in members:
                db.execute("UPDATE tasks SET state='READY',owner=NULL,error=NULL WHERE id=?", (member[0],))
                self.event(db, member[0], "recovered", "Retain worktree/results; resume at saved phase")

    def view(self):
        rows = self.rows()
        with self.connect() as db:
            edges = [dict(r) for r in db.execute("SELECT * FROM edges")]
            groups = self.groups(db)
            resources = {r["id"]: self.resources(db, [r["id"]]) for r in rows}
        states = {r["id"]: r["state"] for r in rows}
        for row in rows:
            own_group = next(g for g in groups if row["id"] in g)
            row["waiting_on"] = sorted({e["dependency"] for e in edges if e["task"] == row["id"]
                                         and e["dependency"] not in own_group and states[e["dependency"]] != "INTEGRATED"})
            own = resources[row["id"]]
            row["write_paths"] = sorted(own[1])
            row["waiting_for_writer"] = [r["id"] for r in rows
                if r["id"] not in own_group and r["state"] in ("RUNNING", "VERIFIED")
                and (self.overlapping(own, resources[r["id"]]) or
                     (row["worktree"] and row["worktree"] == r["worktree"]))]
        graph = {r["id"]: [] for r in rows}
        for edge in edges:
            graph[edge["task"]].append(edge["dependency"])
        cycles = [g for g in components(graph) if len(g) > 1 and not any(set(g) <= set(a) for a in groups)]
        return {"tasks": rows, "edges": edges, "groups": groups,
                "scheduler": self.meta("scheduler"), "publication": self.meta("publication"),
                "unresolved_cycles": cycles, "contracts": self.contract_hashes(), "updated": time.time()}
