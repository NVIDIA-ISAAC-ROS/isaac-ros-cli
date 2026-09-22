# Verification Ladder

Do not describe a migration as zero-copy based on a green build or the presence of a CUDA tensor. Collect the applicable layers below independently and report unavailable hardware or tooling as an explicit limitation.

## 1. Source and Contract

- Record the starting revision, pre-existing local changes, and exact migration patch.
- Compare topics, QoS, shapes, dtypes, strides, layouts, scaling, and metadata.
- Test preprocessing/postprocessing equivalence on representative and edge-case inputs.
- Confirm that every producer and consumer uses the same generated ROS type and distribution.

## 2. Allocation and Negotiation

- Publisher log/test: the outgoing field reports the producer's intended backend.
- Receiver log/test: each subscriber reports the backend negotiated for that peer and unchanged content.
- Exercise every fallback or promotion that production accepts. Buffer compatibility and backend negotiation are separate from proof that a particular copy was removed.

When CUDA is selected:

- Have the capable subscriber request `acceptable_buffer_backends='cuda'` (Python) or the equivalent subscription option.
- Verify that the received field reports `backend_type == 'cuda'` and that the framework view is CUDA-resident.
- Add an ordinary CPU-only subscriber with default subscription options to the same publication. It should receive `backend_type == 'cpu'` and unchanged content while the CUDA subscriber continues to receive `cuda`.
- Inspect fallback separately. An allowed CPU fallback is not proof of the optimized path, and its expected copy is not a failure of the simultaneous CUDA peer.

Do not compare pointer values between processes. CUDA IPC imports can map the same physical allocation at different virtual addresses. Within one process, pointer aliasing can help validate a framework wrapper, but it does not prove middleware transport by itself.

## 3. Copy and Synchronization Audit

- Ensure Torch subscribers use `clone=False`.
- Search for `.cpu()`, `.numpy()`, `.item()`, `to_tensor_msg`, `.clone()`, host `memcpy`, `cudaMemcpy`, and explicit synchronization.
- Classify each occurrence as removed, unavoidable boundary, device-to-device copy, or unrelated control data.
- Release output views before publish and input views after dependent work is enqueued.

## 4. Process Test

Run publisher and subscriber in separate processes with the production RMW/typesupport. Validate multiple messages, numerical content, negotiated backend identity, and clean shutdown. Add multi-publisher/subscriber or QoS cases when the application uses them.

For a generally consumable CUDA publication, run CUDA and unmodified CPU subscribers simultaneously and correlate their headers/content. Also send a CPU-native publication to the CUDA algorithm: inspect `backend_type == 'cpu'` before acquiring the input handle, then verify the promoted processing result. Delay a subscriber or processing callback long enough to exercise the configured history depth, then fail on stale UID, recycled IPC block, or dropped descriptor. Treat CPU fallback as expected only for the peers that did not negotiate CUDA.

## 5. Profiler Evidence

When claiming that CUDA transport removed copies, capture steady state after model loading and warmup. Use Nsight Systems CUDA memory-operation reports or an equivalent profiler to distinguish host-to-device, device-to-host, and device-to-device operations by size. If profiling is unavailable, do not promote backend negotiation alone into a copy-elimination claim.

Capture the unmodified node too. Keep the source data, dimensions, rate, model or kernel, sink behavior, warmup, trace duration, RMW/typesupport, software image, and GPU identical. Verify that both windows contain the same amount of completed application work before comparing copy counts or time.

Keep optional internal host work identical in matched profiler windows or classify its copies separately from the migrated message edge. Also capture a GPU-only subscriber window and a mixed CPU/CUDA subscriber window: the latter should add the expected CPU materialization without changing the CUDA subscriber's negotiated backend.

For a payload of `N` bytes, the GPU-only optimized ROS hops should not create `N`-byte host-to-device or device-to-host transfers. The mixed window should contain the documented D2H materialization for CPU-only peers. Small scalar transfers at a terminal verifier and an explicitly documented device-to-device copy into message-owned output are expected. Avoid host-only topic tools during the capture because they can intentionally request a CPU materialization.

Profiler summary tables may round small copies to zero megabytes. Export or query individual memory-operation rows when the claim depends on exact sizes; report direction, byte size, count, and how each payload size maps back to a source tensor or message. Keep profiler observations on the tested machine separate from general performance claims.

A process-level capture that follows launch children can use:

```bash
nsys profile --trace=cuda,nvtx,osrt --trace-fork-before-exec=true \
  --force-overwrite=true --output=/tmp/buffer_run \
  ros2 launch <package> <launch-file> <fixed-work-arguments>

python3 scripts/summarize_nsys_memcopies.py /tmp/buffer_run.nsys-rep
```

Run the same command shape for the control and ensure both application logs report the same completed work. The summary helper exports through the installed `nsys` CLI and prints exact operation sizes instead of rounded megabytes.

## 6. Application Result

Run the original success criterion: visual output, action completion, numerical tolerance, rate, latency, or throughput. Report build success, transport proof, profiler proof, and application proof separately. If a required package or hardware path is unreleased, state that as a validation limitation rather than treating source-only tests as full proof.
