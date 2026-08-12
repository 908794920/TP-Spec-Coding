# V5.1.0 P4 single-contract regression: build a real 5.1.0 task and drive the
# full L1 chain (NEW->DEVELOPING->VERIFYING->CLOSING->COMPLETED) through the CLI,
# then validate with Test-AiWorkTask.ps1. Plus negative tests.
import os, sys, shutil, sqlite3, subprocess, tempfile, re
from pathlib import Path

BASE = str(Path(__file__).resolve().parent.parent.parent)
sys.path.insert(0, BASE)
from cli import db as dbmod
from cli import main as climain

RESULTS = []
def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(("PASS" if cond else "FAIL"), name, detail)

work = tempfile.mkdtemp(prefix="v510p4-")
proj_root = os.path.join(work, "proj")
task_id = "TASK-20260729-905"
task_dir = os.path.join(proj_root, ".ai-work", "tasks", task_id)
os.makedirs(task_dir, exist_ok=True)
db_path = os.path.join(proj_root, ".ai-work", "db", "p4.db")
os.makedirs(os.path.dirname(db_path), exist_ok=True)

# 1. init DB + project (base_version 5.1.0)
conn = dbmod.connect(db_path)
dbmod.init_schema(conn)
with dbmod.transactional(conn):
    conn.execute("INSERT INTO project (project_id, project_name, root_path, base_version, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                 ("p4proj", "p4proj", proj_root, "5.1.0", dbmod.now_iso(), dbmod.now_iso()))
conn.close()

# 2. copy 5.1.3 template into task dir, set task_id + acceptance PASS
tpl = os.path.join(BASE, "templates", "5.1.3")
for fn in os.listdir(tpl):
    shutil.copy(os.path.join(tpl, fn), os.path.join(task_dir, fn))
sp = os.path.join(task_dir, "status.yaml")
s = open(sp, encoding="utf-8").read()
s = s.replace('task_id: "TASK-YYYYMMDD-XXX"', f'task_id: "{task_id}"').replace('created: "YYYY-MM-DD"', 'created: "2026-07-29"')
open(sp, "w", encoding="utf-8", newline="\n").write(s)
ap = os.path.join(task_dir, "acceptance.md")
a = open(ap, encoding="utf-8").read()
a = a.replace("| AC-01 |  | `task.md` |  |  |  |  | PENDING |",
              "| AC-01 | 鍩虹鍔熻兘鍙敤 | `task.md` | L1 | 闈炴祻瑙堝櫒楠岃瘉 | evidence/ac01.md | none | PASS |")
open(ap, "w", encoding="utf-8", newline="\n").write(a)
os.makedirs(os.path.join(task_dir, "evidence"), exist_ok=True)
open(os.path.join(task_dir, "evidence", "ac01.md"), "w", encoding="utf-8").write("ac01 evidence\n")

def run(argv):
    return climain.main(argv)

def validate():
    r = subprocess.run(["powershell.exe","-NoProfile","-ExecutionPolicy","Bypass","-File",
                        os.path.join(BASE,"scripts","Test-AiWorkTask.ps1"),"-TaskPath",task_dir],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr

# 3. create task (L1)
rc = run(["task","create","--id",task_id,"--project","p4proj","--title","p4 test","--risk","L1","--flow","L1","--db",db_path])
check("task_create_rc0", rc == 0, str(rc))

# 4. NEW -> DEVELOPING (architecture hands to dev)
rc = run(["commit","--task",task_id,"--task-dir",task_dir,"--actor","tp-architecture-design","--to","DEVELOPING","--summary","risk L1 -> dev","--db",db_path])
check("commit_NEW_DEVELOPING_rc0", rc == 0, str(rc))

# 5. DEVELOPING -> VERIFYING (dev done)
rc = run(["commit","--task",task_id,"--task-dir",task_dir,"--actor","tp-development-engineering","--to","VERIFYING","--summary","impl done","--db",db_path])
check("commit_DEV_VERIFYING_rc0", rc == 0, str(rc))

# 6. review-only PASS (verification)
rc = run(["commit","--task",task_id,"--task-dir",task_dir,"--actor","tp-verification-engineering","--review-only","--decision","PASS","--summary","review pass","--evidence","evidence/ac01.md","--db",db_path])
check("commit_review_only_PASS_rc0", rc == 0, str(rc))

# 7. VERIFYING -> CLOSING (delivery, human confirmation)
rc = run(["commit","--task",task_id,"--task-dir",task_dir,"--actor","tp-delivery-convergence","--to","CLOSING","--summary","closing","--human-confirmation","approved","--db",db_path])
check("commit_VERIFYING_CLOSING_rc0", rc == 0, str(rc))

# 8. CLOSING -> COMPLETED (delivery)
rc = run(["commit","--task",task_id,"--task-dir",task_dir,"--actor","tp-delivery-convergence","--to","COMPLETED","--summary","completed","--db",db_path])
check("commit_CLOSING_COMPLETED_rc0", rc == 0, str(rc))

# 9. validator must pass at COMPLETED
vrc, vout = validate()
check("validator_completed_0errors", vrc == 0, vout.strip().splitlines()[-6:] if vrc != 0 else "")

# --- Negative tests (fresh task each) ---
def fresh(tid, risk="L1"):
    td = os.path.join(proj_root, ".ai-work", "tasks", tid)
    os.makedirs(td, exist_ok=True)
    for fn in os.listdir(tpl):
        shutil.copy(os.path.join(tpl, fn), os.path.join(td, fn))
    ss = open(os.path.join(td,"status.yaml"), encoding="utf-8").read().replace('task_id: "TASK-YYYYMMDD-XXX"', f'task_id: "{tid}"')
    open(os.path.join(td,"status.yaml"),"w",encoding="utf-8",newline="\n").write(ss)
    run(["task","create","--id",tid,"--project","p4proj","--title","neg","--risk",risk,"--flow",risk,"--db",db_path])
    return td

# N1: old/unknown actor rejected by commit allowlist
tdn = fresh("TASK-20260729-911")
try:
    rc = run(["commit","--task","TASK-20260729-911","--task-dir",tdn,"--actor","legacy-tool-actor","--to","DEVELOPING","--summary","x","--db",db_path])
    check("neg_old_actor_rejected", rc != 0, "argparse/validation should reject")
except SystemExit as e:
    check("neg_old_actor_rejected", True, "argparse rejected choice")

# N2: direct VERIFYING->COMPLETED rejected (invalid transition, no direct edge)
tdn2 = fresh("TASK-20260729-912")
run(["commit","--task","TASK-20260729-912","--task-dir",tdn2,"--actor","tp-architecture-design","--to","DEVELOPING","--summary","x","--db",db_path])
run(["commit","--task","TASK-20260729-912","--task-dir",tdn2,"--actor","tp-development-engineering","--to","VERIFYING","--summary","x","--db",db_path])
rc = run(["commit","--task","TASK-20260729-912","--task-dir",tdn2,"--actor","tp-delivery-convergence","--to","COMPLETED","--summary","x","--db",db_path])
check("neg_verifying_to_completed_rejected", rc != 0, str(rc))

# N3: non-delivery actor cannot enter CLOSING
tdn3 = fresh("TASK-20260729-913")
run(["commit","--task","TASK-20260729-913","--task-dir",tdn3,"--actor","tp-architecture-design","--to","DEVELOPING","--summary","x","--db",db_path])
run(["commit","--task","TASK-20260729-913","--task-dir",tdn3,"--actor","tp-development-engineering","--to","VERIFYING","--summary","x","--db",db_path])
run(["commit","--task","TASK-20260729-913","--task-dir",tdn3,"--actor","tp-verification-engineering","--review-only","--decision","PASS","--summary","r","--evidence","events.jsonl","--db",db_path])
rc = run(["commit","--task","TASK-20260729-913","--task-dir",tdn3,"--actor","tp-development-engineering","--to","CLOSING","--summary","x","--human-confirmation","approved","--db",db_path])
check("neg_nondelivery_closing_rejected", rc != 0, str(rc))

print("\n=== SUMMARY ===")
failed = [r for r in RESULTS if not r[1]]
print(f"total={len(RESULTS)} passed={len(RESULTS)-len(failed)} failed={len(failed)}")
print("WORKDIR", work)
sys.exit(1 if failed else 0)
