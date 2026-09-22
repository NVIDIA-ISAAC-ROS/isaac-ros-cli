# Plan the Supplied Node's Migration

Use this reference after the user identifies the node or codebase to migrate. Scope the work inside that codebase; do not turn migration planning into a search for a different repository.

## Map the Existing Boundaries

Trace each relevant payload from ROS receipt through processing to ROS publication. Include transitive library calls, enabled optional outputs, asynchronous queues, and local host consumers. Record actual byte counts where practical.

For each message field, record:

| Question | What to capture |
|---|---|
| Existing contract | Topic, message/field type, metadata, QoS, and semantics |
| Current storage | CPU, CUDA, framework-owned tensor, or other backend |
| Algorithm access | Which code reads or writes it, on which stream/thread, and with what stride/layout |
| Target storage | Natural producer backend and acceptable consumer backends |
| Conversion | Avoided copy, required promotion/materialization, or remaining D2D copy |
| Lifetime | Owner and release point for each readable or writable view |
| Action | Migrate directly, migrate with a named conversion, or leave unchanged |

Inspect the generated field type and installed backend API in the target environment. A sequence in a `.msg` file may generate as `rosidl::Buffer<T>` in one build and as `std::vector<T>` in another.

## Choose Per Field

Migrate a field when Buffer storage fits its existing semantics and one or more participants can use the negotiated representation. Typical cases include:

- a GPU algorithm can read a received CUDA allocation through a view;
- a producer can write directly into message-owned CUDA storage;
- a CPU producer or consumer should remain compatible through the CPU representation;
- a framework-owned result needs one explicit device-to-device copy into message storage;
- an existing standard message already carries all required metadata.

Leave a field unchanged when it is small control data, intentionally host-resident, unsupported by the generated type, or outside the user's requested boundary. A compressed decoder, CPU postprocessor, or visualization path can remain a named local host boundary without invalidating useful Buffer migrations elsewhere in the node.

If a helper changes behavior for tensor input, preserve the existing result. Keep that path unchanged or add the smallest semantics-preserving adapter. Do not rewrite preprocessing, the model, or the application architecture merely to make every edge GPU-native.

## Preserve the Interface

Prefer the existing topic and message type when its generated sequence field is Buffer-backed. Preserve headers, encodings, dimensions, strides, timestamps, QoS, parameters, and error behavior. Add a new tensor message or adapter only when the payload contract actually needs to change or the target runtime lacks Buffer support.

For mixed consumers, publish once in the producer's natural backend. Configure only capable subscribers to request CUDA; leave ordinary CPU subscribers at their defaults. Branch inside the application only when semantic outputs differ, not merely because peers request different storage backends.

## Forecast the Patch

Before editing, map expected hunks to these categories:

1. generated type, dependency, or backend configuration;
2. subscription backend options;
3. input view and stride handling;
4. message-owned output allocation and writable view;
5. lifetime or stream ordering;
6. metadata and semantic preservation;
7. transport and fallback tests.

Treat changes outside those categories as separate application work. Explain any prerequisite that prevents the requested boundary from being migrated; do not silently substitute another node or manufacture an optimization.
