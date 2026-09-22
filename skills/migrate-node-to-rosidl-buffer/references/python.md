# Python and PyTorch Patterns

Use these patterns for `rclpy` nodes. Confirm the exact API in the installed `torch_conversions_py` and `cuda_buffer_py` packages because experimental releases can differ.

## CPU-Native Buffer Fields

If the node is CPU-native, keep the generated sequence assignment and access patterns supported by the target `rclpy` message binding. Do not add Torch, CUDA conversion packages, or backend options merely because the field is Buffer-backed. Build and run against the exact generated binding, preserve the field's Python value contract, and report the observed CPU backend separately from any acceleration claim.

## Tensor Publisher

```python
from tensor_msgs.msg import ExperimentalTensor
import torch
from torch_conversions import allocate_tensor_msg
from torch_conversions import from_output_tensor_msg

self._stream = torch.cuda.Stream()
self._publisher = self.create_publisher(ExperimentalTensor, 'tensor_out', qos)

def publish_result(self, result: torch.Tensor) -> None:
    with torch.cuda.stream(self._stream), torch.inference_mode():
        msg = allocate_tensor_msg(result.shape, result.dtype, 'cuda')
        output = from_output_tensor_msg(msg)
        output.copy_(result)  # A device-to-device copy; document it.
        del output            # Release WriteHandle before publish.
    self._publisher.publish(msg)
```

Prefer computing directly into `output` when the library supports an output argument. Many models return framework-owned storage, so one device-to-device copy into message storage is an honest and useful intermediate result: it still removes full-payload device-to-host and later host-to-device copies.

`to_tensor_msg(result)` is shorter but also copies. Use the explicit allocation and output view in instructional migrations so the remaining copy is visible.

The ROS publish call normally ends application ownership of the message. Verify that the installed experimental backend retains the exported CUDA allocation until a remote reader imports it. A warning such as `IPC block recycled before import (stale UID)` is direct evidence that this lifetime failed. For affected builds, retain only a bounded history equal to the publisher QoS depth while the backend is fixed:

```python
from collections import deque

self._published_messages = deque(maxlen=qos.depth)
# After releasing the writable output view:
self._publisher.publish(msg)
self._published_messages.append(msg)
```

Do not add this workaround without reproducing the stale-descriptor failure, and remove it when the selected backend owns the DDS-history lifetime correctly.

## Tensor Subscriber

```python
from tensor_msgs.msg import ExperimentalTensor
import torch
from torch_conversions import from_input_tensor_msg

self._stream = torch.cuda.Stream()
self._subscription = self.create_subscription(
    ExperimentalTensor,
    'tensor_in',
    self._receive,
    qos,
    acceptable_buffer_backends='cuda',
)

def _receive(self, msg: ExperimentalTensor) -> None:
    with torch.cuda.stream(self._stream), torch.inference_mode():
        value = from_input_tensor_msg(msg, clone=False)
        if not value.is_cuda:
            value = value.to('cuda', non_blocking=True)
        result = self._model(value)  # Treat value as read-only.
        del value                    # Dependent work is now enqueued.
        self._publish_result(result)
```

The tensor returned with `clone=False` owns the backend read handle through its DLPack lifetime. A CUDA-backed message remains a view; a CPU fallback takes the expected promotion before the CUDA model. Assert the CUDA backend in the optimized-path test rather than rejecting fallback in the production callback. Derived views can extend the handle lifetime. Do not retain views indefinitely, and do not destroy them before dependent work has been placed on the selected stream.

## Existing Buffer-Backed Messages

When an existing message such as `sensor_msgs/Image` already has a buffer-backed `data` field, keep the message type if its metadata is useful. Acquire the field with `cuda_buffer.CudaBuffer.from_input_buffer`, wrap the pointer through DLPack or CUDA Array Interface, and retain the ROS message plus read handle for the full tensor-view lifetime. Allocate output fields with `CudaBuffer.allocate_buffer` and release the write handle before publishing.

This lower-level path is appropriate for arbitrary buffer fields. Prefer `torch_conversions` for `ExperimentalTensor`; it already implements metadata validation and DLPack lifetime ownership.

## Inspect Transitive Framework Semantics

Do not assume a library handles NumPy and CUDA tensors equivalently. Inspect the pinned dispatch path through preprocessing and postprocessing before changing the input type. In particular, check whether the tensor path:

- expects RGB instead of the wrapper's BGR input;
- expects BCHW float values instead of HWC bytes;
- skips resize, letterbox, normalization, or coordinate transforms performed for NumPy/PIL inputs;
- converts the original CUDA image back to NumPy for mask or box scaling;
- calls a helper such as `convert_torch2numpy_batch`, `.cpu()`, `cp.asnumpy`, or `.get()`.

If preserving the public result would require reimplementing a model processor or substantial postprocessor, keep that path unchanged and report it as outside the transport retrofit. Continue with other useful fields; if none can be migrated, explain the concrete prerequisite instead of forcing an algorithm rewrite.

## Boundary Adapters

For an existing public image topic whose generated field is `rosidl::Buffer`:

1. Validate the original encoding, dimensions, and step.
2. Allocate CUDA message storage.
3. Write the GPU result into that storage.
4. Publish once on the existing topic; CUDA-aware and CPU-only subscribers negotiate their representations independently.

Use a separate internal topic or adapter only when the public deployment uses an older generated message/RMW without Buffer support, or when the payload semantics actually differ. Preserve headers and other non-tensor metadata in the existing message or a documented companion contract.

## Dependencies

For an `ament_python` tensor node, declare at least:

```xml
<exec_depend>rclpy</exec_depend>
<exec_depend>tensor_msgs</exec_depend>
<exec_depend>torch_conversions_py</exec_depend>
<exec_depend>cuda_buffer_backend</exec_depend>
```

Add `cuda_buffer_py` when the code imports `cuda_buffer` directly. The conversion library provides tensor views; `cuda_buffer_backend` is the runtime transport plugin.
