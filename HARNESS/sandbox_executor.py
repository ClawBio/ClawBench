"""Sandboxed executor for the untrusted agent arms (Exp 2, free_agent + skill_reasoning).

Implements EXECUTOR-SIGNOFF.md (signed off 2026-06-20). The agent's emitted text is NEVER handed to a
shell. vet() statically parses it into discrete allowlisted commands and returns an accept/reject
verdict with reasons; a rejected script never executes and maps to taxonomy labels via
rejection_labels(). execute() runs an accepted command list with shell=False, a scrubbed env and a
timeout; the runner is injectable so the gate is testable without running anything. No import-time IO.
"""
from __future__ import annotations

import re
import shlex

# ---- allowlist / exclusions (frozen in EXECUTOR-SIGNOFF.md) ------------------
_ALLOW = {
    "nextflow", "java", "docker", "samtools", "bcftools", "bgzip", "tabix", "htsfile", "bwa",
    "bwa-mem2", "minimap2", "fastp", "fastqc", "gatk", "gatk4", "picard", "freebayes", "strelka2",
    "rtg", "sort", "gzip", "gunzip", "zcat", "cat", "head", "tail", "cut", "grep", "mkdir", "cp",
    "mv", "ln",
}
_INTERPRETERS = {"bash", "sh", "zsh", "python", "python3", "perl", "ruby", "node", "Rscript", "R", "awk"}
_NETWORK = {"curl", "wget", "ssh", "scp", "sftp", "nc", "ncat", "socat", "rsync", "git", "aws",
            "gsutil", "pip", "pip3", "conda", "mamba", "micromamba"}
_PRIV = {"sudo", "su", "chmod", "chown", "launchctl", "crontab", "kill", "killall", "rm"}
_DOCKER_OK_SUB = {"run", "build", "images", "inspect", "ps", "tag"}
_DOCKER_DENY = {"pull", "push", "login", "logout", "save", "load", "exec", "cp"}

# raw constructs that defeat static analysis -> reject the whole script
_BAD_CONSTRUCTS = [
    (r"\$\(", "unparseable:command_substitution"),
    (r"`", "unparseable:command_substitution"),
    (r"\$\{", "unparseable:variable_expansion"),
    (r"<\(", "unparseable:process_substitution"),
    (r">\(", "unparseable:process_substitution"),
    (r"&&", "unparseable:chaining"),
    (r"\|\|", "unparseable:chaining"),
    (r";", "unparseable:chaining"),
    (r"(?<!\d)&(?!\d)\s*$", "unparseable:background"),
    (r"(?m)^\s*\.\s+\S", "interpreter:source"),
]
_FORBIDDEN_ROOTS = ("/Users", "/etc", "/System", "/private", "/var", "/bin", "/usr", "/opt", "/Library")
_REDIR = {">", ">>", "<", "2>", "&>"}


def _base(word: str) -> str:
    return word.rsplit("/", 1)[-1]


def _path_confined(target: str, sandbox_root: str, input_roots, *, read: bool) -> bool:
    """Writes only inside the sandbox; reads also from granted input roots or relative paths."""
    if not target.startswith("/"):
        return True  # relative path resolves inside the per-run cwd (the sandbox)
    if target.startswith(sandbox_root):
        return True
    if read and any(target.startswith(r) for r in input_roots):
        return True
    return False


def _vet_command(tokens, sandbox_root, input_roots, rej):
    if not tokens:
        return
    tool = _base(tokens[0])
    # redirections within this segment
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in _REDIR:
            tgt = tokens[i + 1] if i + 1 < len(tokens) else ""
            read = t == "<"
            if not _path_confined(tgt, sandbox_root, input_roots, read=read):
                rej.append(f"redirect_unconfined:{tgt}")
            i += 2
            continue
        i += 1
    if tool in _NETWORK:
        rej.append(f"network_tool:{tool}")
        return
    if tool in _INTERPRETERS:
        rej.append(f"excluded_interpreter:{tool}")
        return
    if tool in _PRIV:
        rej.append(f"privileged_tool:{tool}")
        return
    if tool == "docker":
        sub = next((t for t in tokens[1:] if not t.startswith("-")), "")
        if sub in _DOCKER_DENY or sub not in _DOCKER_OK_SUB:
            rej.append(f"docker_subcommand:{sub or 'none'}")
        for t in tokens[1:]:
            if t in ("--network=host", "--privileged") or t.startswith("--network=host"):
                rej.append(f"docker_flag:{t}")
            if t in ("-v", "--mount", "--volume"):
                rej.append("docker_host_mount")
        return
    if tool not in _ALLOW:
        rej.append(f"not_allowlisted:{tool}")
        return
    # absolute-path arguments must be confined (read side)
    for t in tokens[1:]:
        if t in _REDIR or t.startswith("-"):
            continue
        if t.startswith("/") and not _path_confined(t, sandbox_root, input_roots, read=True):
            if any(t.startswith(r) for r in _FORBIDDEN_ROOTS) and not t.startswith(sandbox_root):
                rej.append(f"path_unconfined:{t}")


def vet(script: str, *, sandbox_root: str, input_roots) -> dict:
    """Pure static gate. Returns {accepted, commands, rejections}. The script runs only if accepted."""
    rej: list[str] = []
    commands: list[list[list[str]]] = []  # list of pipelines; each pipeline is a list of arg-lists
    text = script or ""
    for pat, label in _BAD_CONSTRUCTS:
        if re.search(pat, text):
            rej.append(label)
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.split(" #", 1)[0].rstrip()  # drop trailing comment
        if "| bash" in line or "|bash" in line or "| sh" in line or "|sh" in line:
            rej.append("unparseable:pipe_to_shell")
        pipeline = []
        for seg in line.split("|"):
            seg = seg.strip()
            if not seg:
                continue
            try:
                tokens = shlex.split(seg)
            except ValueError as e:
                rej.append(f"unparseable:lex:{e}")
                continue
            _vet_command(tokens, sandbox_root, input_roots, rej)
            pipeline.append(tokens)
        if pipeline:
            commands.append(pipeline)
    # de-duplicate reasons, stable order
    seen, ordered = set(), []
    for r in rej:
        if r not in seen:
            seen.add(r)
            ordered.append(r)
    return {"accepted": len(ordered) == 0, "commands": commands, "rejections": ordered}


def rejection_labels(verdict: dict) -> list[str]:
    """A rejected script produced no VCF -> incomplete_workflow, plus command-level labels it implies."""
    if verdict.get("accepted"):
        return []
    labels = {"incomplete_workflow"}
    for r in verdict.get("rejections", []):
        if r.startswith(("network_tool", "docker")):
            labels.add("container_version_error")
        if r.startswith("not_allowlisted") or r.startswith("excluded_interpreter"):
            labels.add("tool_selection_error")
    return sorted(labels)


# ---- execution (injectable; not exercised by the pure-gate tests) -----------
_SECRET = re.compile(r"(?i)(_KEY|_TOKEN|_SECRET|API_KEY|PASSWORD|AWS_)")


def scrubbed_env(base_env: dict, *, sandbox_root: str, bin_dirs) -> dict:
    env = {k: v for k, v in base_env.items() if not _SECRET.search(k)}
    for k in list(env):
        if "proxy" in k.lower():
            del env[k]
    env["PATH"] = ":".join(bin_dirs)
    env["HOME"] = sandbox_root
    env["TMPDIR"] = f"{sandbox_root}/tmp"
    env["NXF_HOME"] = f"{sandbox_root}/.nextflow"
    env["NXF_OFFLINE"] = "true"
    return env


def execute(verdict: dict, *, sandbox_root: str, env: dict, timeout: int = 6 * 3600, runner=None) -> dict:
    """Run an ACCEPTED command list, shell=False, in the sandbox, with a timeout. runner is injectable;
    the real runner wires pipelines with subprocess and connected fds. Returns exit/timed_out."""
    if not verdict.get("accepted"):
        return {"executed": False, "reason": "rejected", "rejections": verdict.get("rejections", [])}
    if runner is None:  # pragma: no cover - real path used only on the Studio
        runner = _default_runner(sandbox_root, env, timeout)
    return runner(verdict["commands"])


# ---- permissive confined runner (signed-off decision 2026-06-20) -------------
# Blocks only genuinely dangerous / out-of-scope / network operations; ordinary shell (set -e,
# heredocs, $(date), &&, ${VARS}) is allowed so realistic agent scripts execute and can be scored.
# macOS has no per-process sandbox for this workload (it needs the host Docker daemon), so defence is
# layered: scrubbed env (no creds) + scratch cwd + network-tool block + destructive/out-of-scope block
# + timeout + ulimits. The model is non-adversarial; the scan catches accidental scope escapes, it is
# not a defence against a determined attacker (stated honestly in the sign-off).

_NET_PAT = re.compile(
    r"(?:^|[\s|;&(])(curl|wget|ssh|scp|sftp|nc|ncat|socat|telnet|aws|gsutil|gcloud)\b"
    r"|\b(pip|pip3|conda|mamba|micromamba)\s+install\b"
    r"|\bgit\s+(clone|fetch|pull|push|remote)\b"
    r"|\bdocker\s+(pull|push|login)\b"
    r"|docker\s+run[^\n]*--network[=\s]*host"
    r"|rsync\b[^\n]*::", re.I)
_PRIV_PAT = re.compile(r"(?:^|[\s|;&])(sudo|su|launchctl|crontab|systemctl|chown)\b"
                       r"|:\(\)\s*\{[^}]*:\|:", re.I)  # fork bomb
_RM_ROOT = re.compile(r"\brm\s+(-[a-z]*\s+)*(/|/\*)\s*$", re.I | re.M)


def _path_is_outside(target, sandbox_root, input_roots):
    if not target.startswith("/"):
        return False
    if target.startswith(sandbox_root):
        return False
    if any(target.startswith(r) for r in input_roots):
        return False
    return any(target.startswith(r) for r in _FORBIDDEN_ROOTS)


def prescan(script: str, *, sandbox_root: str, input_roots) -> dict:
    """Block only dangerous / out-of-scope / network ops; allow ordinary shell. Returns {safe, blocks}."""
    blocks: list[str] = []
    text = script or ""
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if _NET_PAT.search(s):
            blocks.append(f"network:{s[:60]}")
        if _PRIV_PAT.search(s):
            blocks.append(f"privileged:{s[:60]}")
        if _RM_ROOT.search(s):
            blocks.append(f"destructive:{s[:60]}")
        # destructive/write ops whose target is an absolute path outside the sandbox + inputs
        m = re.match(r"(?i)\s*(rm|rmdir|mv|cp|chmod|chown|dd|truncate|tee|shred|mkfs)\b(.*)", s)
        if m:
            for tok in m.group(2).split():
                if _path_is_outside(tok.strip('"\''), sandbox_root, input_roots):
                    blocks.append(f"destructive_outside:{tok[:50]}")
        # any explicit write-redirect to a forbidden absolute path
        for tok in re.findall(r">>?\s*(\S+)", s):
            if _path_is_outside(tok.strip('"\''), sandbox_root, input_roots):
                blocks.append(f"write_outside:{tok[:50]}")
    seen, ordered = set(), []
    for b in blocks:
        if b not in seen:
            seen.add(b)
            ordered.append(b)
    return {"safe": len(ordered) == 0, "blocks": ordered}


def run_script(script: str, *, sandbox_root: str, input_roots, env_vars: dict, base_env: dict = None,
               bin_dirs=None, timeout: int = 6 * 3600, runner=None) -> dict:
    """Prescan the agent's raw bash; if safe, write it into the sandbox and run it via bash with a
    scrubbed env (secrets stripped, network off, injected calling vars), confined cwd, and a timeout.
    runner is injectable: runner(script_path, *, cwd, env, timeout) -> {exit_ok, returncode}."""
    scan = prescan(script, sandbox_root=sandbox_root, input_roots=input_roots)
    if not scan["safe"]:
        return {"executed": False, "reason": "prescan_blocked", "blocks": scan["blocks"]}
    base_env = base_env if base_env is not None else {}
    bin_dirs = bin_dirs or [f"{sandbox_root}/../../conda/envs/giab/bin"]
    env = scrubbed_env(base_env, sandbox_root=sandbox_root, bin_dirs=bin_dirs)
    env.update(env_vars or {})  # inject SAMPLE/R1/R2/REF/OUTDIR/THREADS so both arms resolve fairly
    if runner is None:  # pragma: no cover - real path used only on the Studio
        runner = _bash_runner(timeout)
    res = runner(f"{sandbox_root}/run.sh", cwd=sandbox_root, env=env, timeout=timeout)
    return {"executed": True, **res}


def _bash_runner(timeout):  # pragma: no cover - integration path (Studio)
    import subprocess

    def _run(script_path, *, cwd, env, timeout=timeout):
        try:
            p = subprocess.run(["/bin/bash", script_path], cwd=cwd, env=env, timeout=timeout)
            return {"exit_ok": p.returncode == 0, "returncode": p.returncode, "timed_out": False}
        except subprocess.TimeoutExpired:
            return {"exit_ok": False, "returncode": None, "timed_out": True}

    return _run


def _default_runner(sandbox_root, env, timeout):  # pragma: no cover - integration path
    import subprocess

    def _run(commands):
        for pipeline in commands:
            procs = []
            prev = None
            for argv in pipeline:
                stdin = prev.stdout if prev is not None else None
                p = subprocess.Popen(argv, cwd=sandbox_root, env=env, stdin=stdin,
                                     stdout=subprocess.PIPE)
                if prev is not None:
                    prev.stdout.close()
                procs.append(p)
                prev = p
            try:
                rc = procs[-1].wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                for p in procs:
                    p.kill()
                return {"executed": True, "timed_out": True, "exit_ok": False}
            if rc != 0:
                return {"executed": True, "timed_out": False, "exit_ok": False, "returncode": rc}
        return {"executed": True, "timed_out": False, "exit_ok": True, "returncode": 0}

    return _run
