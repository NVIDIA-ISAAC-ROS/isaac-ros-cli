---
name: migrate-node-to-rosidl-buffer
description: Guide source-code changes that make an existing ROS 2 C++ or Python node use rosidl::Buffer-backed fields while preserving its interface and behavior. Use for publisher, subscriber, backend, lifetime, or transport-proof changes; not algorithm redesigns or unrelated new nodes. This skill is early access; review every change and validate it in the target environment before production use.
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

# Migrate an Existing Node to rosidl::Buffer

## Purpose

Start with the node and codebase supplied by the user. Preserve its computation, interfaces, and observable behavior while making applicable message fields use `rosidl::Buffer` storage and backend negotiation. Do not substitute a different codebase unless the user asks.

This is an agent-guided source migration: when the user requests implementation, use the available workspace editing and build/test tools to change their node. The bundled Python scripts are intentionally read-only evidence helpers; they inventory possible copy boundaries and summarize profiler traces but do not perform the migration themselves.

A Buffer-ready node should publish one semantic output once in its natural memory domain, with each subscriber receiving the representation negotiated for that peer. For example, a CUDA publication can remain CUDA-backed for a capable GPU subscriber while an ordinary CPU subscriber receives the per-peer CPU representation. Do not create application-level publication branches merely to serve different storage backends.

The node does not need to be GPU-enabled already. Select storage backends from the node's real producers and consumers and from what the target runtime supports. A CPU-native field can remain CPU-backed and Buffer-compatible; do not invent an acceleration claim.

Treat `tensor_msgs/msg/ExperimentalTensor` and unreleased Buffer bindings as experimental. Record the exact ROS distribution and package revisions used because generated field types and APIs can differ.

## Instructions

1. Inspect the supplied workspace before editing. Record the starting revision and local changes, identify the requested node and boundaries, and preserve unrelated user work.
2. Inspect the exact generated message field types, Buffer APIs, RMW/typesupport, and installed backends for the target environment. Do not infer Buffer support from the `.msg` schema alone.
3. Record the existing contract: topics, message types, dtype, shape, strides, channel order, scaling, QoS, parameters, headers/metadata, rates, and application success criteria.
4. Run `scripts/audit_copy_boundaries.py <source paths>` for a first-pass inventory, then inspect every reported line and any transitive helpers in context. The script finds evidence; it does not decide whether a copy is avoidable.
5. Read [references/migration-planning.md](references/migration-planning.md) and make a per-field migration plan. Keep CPU-native fields on CPU when appropriate, migrate useful Buffer boundaries, and name any unavoidable promotion or materialization. Do not reject the entire supplied node merely because only some edges benefit.
6. Choose the smallest compatible topology:
   - Keep an existing message such as `sensor_msgs/Image` when its buffer-backed field and metadata already fit.
   - Use `tensor_msgs/ExperimentalTensor` for a DLPack-shaped internal tensor edge.
   - Prefer one topic and one publication for mixed CPU/CUDA subscribers; backend negotiation is per subscription and CPU remains implicitly acceptable.
   - Add an adapter or dual topic only when application semantics differ or the chosen backend cannot provide the required fallback.
   - Leave small state, commands, and CPU-only control paths on the host.
7. Read [references/python.md](references/python.md) for `rclpy` and optional PyTorch/CUDA patterns, or [references/cpp.md](references/cpp.md) for `rclcpp` and optional LibTorch/raw-CUDA patterns. Change the publishers, subscribers, dependencies, launch files, and tests together.
8. Preserve handle lifetimes and any required stream ordering. Release writable views before publish and retain read-only views until dependent work has been accepted by the consumer. For CUDA IPC, exercise the configured QoS depth under backlog and inspect for stale or recycled descriptors.
9. Validate with [references/verification.md](references/verification.md). Use a separate-process publisher/subscriber test for transport claims. If the required backend, hardware, or profiler is unavailable, complete the checks that are possible and state exactly which optimization claims remain unproven.

## Available Scripts

| Script | Purpose | Arguments |
| --- | --- | --- |
| `scripts/audit_copy_boundaries.py` | Inventory possible host/device copies and Buffer API usage for manual review. | One or more source files or directories. |
| `scripts/summarize_nsys_memcopies.py` | Summarize CUDA memcpy direction, size, count, and bytes from an Nsight Systems report or SQLite export. | One `.nsys-rep` or `.sqlite` trace. |

For example:

```bash
python3 <skill-dir>/scripts/audit_copy_boundaries.py <node-source-dir>
python3 <skill-dir>/scripts/summarize_nsys_memcopies.py buffer.sqlite
```

## Backend-Neutral Contract

- Allocate message-owned storage in the producer's natural backend and write into it before publishing.
- Configure capable subscribers to accept the backend they can consume. Leave ordinary CPU-only subscribers at their defaults so they require no Buffer-specific source changes.
- Publish once and let the RMW/backend provide the representation negotiated by each peer. Add application branches only when message semantics differ.
- Treat borrowed input views as immutable. Transformations allocate a separate output buffer.
- Preserve the owner of every input and output view until the backend's documented release point.
- Preserve dtype, shape, element strides, byte offset, layout, scaling, and metadata. Transport success does not prove semantic equivalence.
- Name all required conversions between storage domains. Buffer compatibility does not imply that every producer and consumer is copy-free.

## CUDA and Torch Contract

Apply these rules only when the selected migration edge uses CUDA or Torch:

- If an existing CUDA output tensor cannot be redirected into message-owned storage, document the remaining device-to-device copy.
- Read with `from_input_tensor_msg(msg, clone=False)` or the raw CUDA input handle. The default Torch conversion clone is a copy.
- Set `acceptable_buffer_backends` explicitly on CUDA-capable subscriptions. Production code should normally accept the CPU fallback and promote it when the algorithm requires CUDA; reserve a hard backend assertion for validation or a genuine no-fallback application contract. Do not infer transport placement from `torch.cuda.is_available()` or a later `.cuda()` call.
- Remove intermediate `.cpu()`, `.numpy()`, `.item()`, blocking host `memcpy`, device-wide synchronization, and default-stream synchronization. Keep and label the final host boundary when one is required.
- Do not compare raw device pointer values across processes. CUDA IPC can map the same allocation at different virtual addresses.
- Confirm which component owns a published allocation until a remote reader imports it. Reproduce any stale or recycled allocation failure under backlog before adopting a version-specific workaround; never retain an unbounded stream of messages.

## Keep the Patch Explainable

Every code hunk should implement one of these necessities: use the generated Buffer field, select an acceptable backend, acquire or release a buffer view, preserve equivalent processing, allocate message-owned output, preserve metadata, declare a dependency, or verify the new boundary. Do not rewrite the model or unrelated application architecture unless the user requested that broader work. Leave non-beneficial paths unchanged and report their boundaries.

Keep compatibility-only changes and baseline setup fixes visibly separate from the Buffer mechanism. They may be necessary for the user's target environment, but they must not obscure what the transport retrofit itself requires.

## Output

Report:

- starting revision, local-state caveats, and target environment;
- before/after topic and memory-boundary tables;
- the minimal patch and why each hunk exists;
- fields deliberately left unchanged and why;
- unavoidable copies and exact synchronization boundaries;
- build, semantic, process-transport, profiler, and application tests run;
- observed backend type and any CPU fallback behavior;
- mixed-backend subscriber behavior, including simultaneous CPU/CUDA consumers when CUDA is selected;
- prerequisites that are unreleased, source-only, or tied to a particular RMW/typesupport;
- validation not run and the reason.
