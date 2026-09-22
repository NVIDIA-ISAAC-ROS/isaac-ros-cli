---
name: isaac-ros-activate
description: Use when work must enter the Isaac ROS dev container through the canonical host-side Isaac ROS CLI flow, especially when commands must run through a long-lived `isaac-ros activate` shell instead of `docker exec`.
metadata:
  author: Isaac ROS Maintainers <isaac-ros-maintainers@nvidia.com>
---
<!--
Copyright (c) 2026, NVIDIA CORPORATION. All rights reserved.

NVIDIA CORPORATION and its licensors retain all intellectual property
and proprietary rights in and to this software, related documentation
and any modifications thereto. Any use, reproduction, disclosure or
distribution of this software and related documentation without an express
license agreement from NVIDIA CORPORATION is strictly prohibited.
-->


# Isaac ROS Activate

Use the host CLI path unless the user explicitly asks for raw Docker operations.

## Activation decision

Use this skill when the next command depends on the Isaac ROS dev environment rather than the host environment. Common signals include:
- The user asks to build, test, lint, source, or run ROS packages through the Isaac ROS CLI workflow.
- The command needs ROS, CUDA, Bazel, Debian packaging, or workspace dependencies that are normally available inside the Isaac ROS dev container.
- The command must run repeatedly in one prepared container shell, such as an interactive debug session or a build followed by a test.
- A previous local command failed because expected Isaac ROS container tooling or dependencies were missing on the host.

Stay local when the work is plain Git, text editing, GitLab/API inspection, documentation review, or another host-only operation that does not need the Isaac ROS runtime.

## Mode gate

- This skill is Docker-only by default.
- Before running `isaac-ros activate`, validate that Isaac ROS CLI is configured for Docker mode:

```bash
python3 skills/isaac-ros-activate/scripts/check_ircli_mode.py --expected docker
```

- The helper above prefers the public `isaac-ros status --output json` command when available, and falls back to `/etc/isaac-ros-cli/environment.conf` for older CLI versions.
- If that check fails because the mode is `venv` or `baremetal`, stop. Do not continue unless the user explicitly wants a host-affecting flow.
- After `isaac-ros activate` succeeds, prefer verifying inside the activated shell with:

```bash
isaac-ros status --output json
```

- Expect `{"mode":"docker","activation":"active"}` in that activated shell.
- If the `status` command is not available yet, fall back to:

```bash
grep -qx 'ISAAC_ROS_ENVIRONMENT=docker-activated' /etc/isaac-ros-cli/environment.conf
```

- Use the direct file fallback inside the activated shell instead of a repo-local helper script, because `isaac-ros activate` may attach to an already-running container from another checkout.

## Instructions

1. Start a new host shell in the repo root.
2. Ensure `ISAAC_ROS_WS` points at the Isaac monorepo root if it is not already set.
3. Run the Docker-mode gate above and stop if it fails.
4. Run `isaac-ros activate` on the host.
5. Treat the resulting shell as long-running. It may attach to an existing dev container and remain open by design.
6. Send follow-up commands into that same shell session. Do not expect `isaac-ros activate` to exit until the shell is closed.

## Workspace path rule

- In this specific Isaac GitLab monorepo, set `ISAAC_ROS_WS` to the repository root, for example `/workspaces/isaac`. Do not set `ISAAC_ROS_WS` to `/workspaces/isaac/ros_ws`.
- In other ROS workspaces, set `ISAAC_ROS_WS` to the folder where `colcon` should be run.

## Guardrails

- Prefer `isaac-ros activate` over `docker exec` when the user wants the normal Isaac ROS CLI workflow.
- Refuse this skill by default when Isaac ROS CLI is configured for `venv` or `baremetal`.
- Keep the activated shell alive if more than one command must run in the container.
- If automation is needed, open a PTY, run `isaac-ros activate`, wait for the container prompt, then write later commands to the same PTY.
- Verify success from the prompt change. A typical attached prompt looks like `admin@<host>:/workspaces/isaac_ros-dev$`.
- If `isaac-ros activate` fails because the workspace environment variable is missing, export `ISAAC_ROS_WS=<workspace-root>` in that host shell and retry.
- `isaac-ros activate` can print setup noise like `bash: direnv: command not found`; that does not necessarily mean activation failed.

## Examples

From a host shell:

```bash
export ISAAC_ROS_WS=/workspaces/isaac
isaac-ros activate
```

After the prompt switches into the container, run later commands through the same shell:

```bash
touch /workspaces/isaac_ros-dev/.proof
```

## When not to use this

- If the user explicitly asks for `docker exec`, use `docker exec`.
- If a one-off read-only container check is enough and the user does not care about the canonical CLI path, direct Docker commands may be acceptable.
