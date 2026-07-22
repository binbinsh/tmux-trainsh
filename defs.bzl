"""Local Bazel command shims for tmux-trainsh."""

def _shq(value):
    return "'" + str(value).replace("'", "'\"'\"'") + "'"

def uv_run(name, cmd = None):
    args = cmd if cmd else ["uv", "sync"]
    script = "\n".join([
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        'root="${BUILD_WORKSPACE_DIRECTORY:-$PWD}"',
        "cd \"$root\"",
        " ".join([_shq(arg) for arg in args]),
    ])
    native.genrule(
        name = name + "_script",
        outs = [name + ".sh"],
        cmd = "cat > $@ <<'EOF'\n%s\nEOF\nchmod +x $@" % script,
        visibility = ["//visibility:private"],
    )
    native.sh_binary(
        name = name,
        srcs = [":" + name + "_script"],
    )
