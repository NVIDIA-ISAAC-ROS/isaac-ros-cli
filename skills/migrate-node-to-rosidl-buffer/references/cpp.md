# C++ rosidl Buffer Patterns for CUDA and LibTorch

Use these patterns for `rclcpp` nodes. Adapt message metadata, QoS, computation, and error policy to the existing contract.

## CPU-Native Buffer Fields

When the exact generated field is `rosidl::Buffer<T>` and the node naturally uses CPU storage, keep the ordinary sequence operations and default subscription options:

```cpp
sensor_msgs::msg::Image msg;
msg.height = height;
msg.width = width;
msg.encoding = encoding;
msg.step = step;
msg.data.resize(byte_count);
std::memcpy(msg.data.data(), source, byte_count);
publisher_->publish(std::move(msg));
```

The generated message header supplies the Buffer field; do not add CUDA, Torch, or tensor-message dependencies for this path. Existing reads through `size()`, `data()`, iterators, and indexing should remain container-like, but compile against the target generated type rather than assuming every distribution exposes the same API. This makes the node Buffer-compatible without claiming that its required host copy or CPU processing disappeared.

## LibTorch Tensor Publisher

```cpp
#include <torch/torch.h>
#include "tensor_msgs/msg/experimental_tensor.hpp"
#include "torch_conversions/torch_conversions.hpp"

auto stream_guard = torch_conversions::set_stream();
auto msg = torch_conversions::allocate_tensor_msg(
  {height, width, channels}, torch::kUInt8, c10::kCUDA);
{
  at::Tensor output = torch_conversions::from_output_tensor_msg(*msg);
  produce_into(output);
}  // The WriteHandle records readiness here.
publisher_->publish(std::move(msg));
```

If the existing library cannot write into `output`, use `output.copy_(result)` and report that device-to-device copy.

## LibTorch Tensor Subscriber

```cpp
rclcpp::SubscriptionOptions options;
options.acceptable_buffer_backends = "cuda";

subscription_ = create_subscription<tensor_msgs::msg::ExperimentalTensor>(
  "tensor_in", qos,
  [this](tensor_msgs::msg::ExperimentalTensor::SharedPtr msg) {
    auto stream_guard = torch_conversions::set_stream();
    at::Tensor input = torch_conversions::from_input_tensor_msg(*msg, false);
    if (!input.is_cuda()) {
      input = input.to(c10::kCUDA);  // Expected promotion for a CPU publisher/fallback.
    }
    at::Tensor result = model_.forward(input);
    input.reset();  // Dependent work is enqueued; release ReadHandle.
    publish_result(result);
  }, options);
```

## Raw Buffer Fields

Keep an existing message contract when it already contains the required `rosidl::Buffer` field:

```cpp
message.data = cuda_buffer_backend::allocate_buffer(byte_count);
{
  auto output = cuda_buffer_backend::from_output_buffer(message.data, stream);
  kernel<<<grid, block, 0, stream>>>(output.get_ptr(), ...);
}
publisher_->publish(message);
```

On the subscriber:

```cpp
const std::string input_backend = message->data.get_backend_type();
RCLCPP_DEBUG(get_logger(), "received backend=%s", input_backend.c_str());
auto input = cuda_buffer_backend::from_input_buffer(message->data, stream);
consume<<<grid, block, 0, stream>>>(input.get_ptr(), ...);
```

`from_input_buffer` can promote CPU storage into CUDA storage. A CUDA algorithm can therefore use one processing path: CUDA input is read directly, while CPU input incurs the necessary host-to-device promotion. Log the received backend in production and assert it in the optimized-path test; do not reject CPU fallback unless the application genuinely cannot accept it.

## Existing ROS Adapters and Strided Data

- Inspect the generated C++ field type for the exact ROS distribution and package build. A schema may still display as `uint8[]` while generated C++ uses `rosidl::Buffer<uint8_t>`; a stock older distribution may still generate `std::vector<uint8_t>`.
- Pass `rclcpp::SubscriptionOptions` through wrappers such as `image_transport::SubscriberFilter`, `message_filters`, and point-cloud transports instead of replacing an otherwise-correct synchronization graph. Verify the wrapper overload actually forwards the options.
- Claim zero-copy input only for transports that preserve the CUDA allocation. A conventional compressed-image decoder normally produces host storage, but the same application path can still promote that CPU buffer before CUDA processing.
- Honor message stride and byte offset. Image rows are addressed with `step`, not `width * channels`; point clouds may have padded `point_step` and `row_step` values. Add a padded-row test even when the common producer is tightly packed.
- If optional debug, visualization, or derived-output code inside the node requires a host view, keep it as a named local boundary. It may add a D2H copy without changing how the published topic is negotiated independently for CPU and CUDA subscribers.

A current `image_transport::SubscriberFilter` path can preserve its synchronizer while forwarding the backend request:

```cpp
rclcpp::SubscriptionOptions options;
options.acceptable_buffer_backends = "cuda";
image_filter.subscribe(
  node, image_base_topic, "raw",
  rclcpp::SensorDataQoS().get_rmw_qos_profile(), options);

camera_info_filter =
  std::make_shared<message_filters::Subscriber<sensor_msgs::msg::CameraInfo>>(
    node, camera_info_topic, rclcpp::SensorDataQoS());
```

Confirm the exact overload in the installed `image_transport`; older source uses `.h` message-filter headers while newer releases use `.hpp`. Conventional compressed plugins normally materialize host images, so report their expected promotion rather than claiming zero-copy input.

For asynchronous worker queues, queue the immutable ROS message owner and metadata. Acquire the CUDA read handle in the worker on the stream that will consume it, then release it after dependent work is enqueued. Do not pass a handle across threads unless that backend explicitly documents the operation as safe. When left/right or producer/model streams differ, retain both message owners and establish explicit events or existing stream synchronization before releasing either handle.

When one published topic has both CUDA and CPU consumers, publish one message in the producer's natural memory domain. A CUDA-aware subscription opts into `cuda`; a conventional subscription remains CPU-only, and the backend serves each peer appropriately. Use separate topics or an adapter only when the payload semantics differ or the backend cannot provide the required transport scope.

In the mixed-consumer test, deliberately leave the CPU subscriber's `SubscriptionOptions` at their default. Only the CUDA test subscriber should set `acceptable_buffer_backends`. This proves an existing host-only consumer does not need an application patch.

## Dependencies

Keep the layers distinct:

- `torch_conversions` adapts `ExperimentalTensor` to LibTorch.
- `cuda_buffer` provides CUDA storage and stream-aware handles.
- `cuda_buffer_backend` is the runtime transport plugin.
- `tensor_msgs` provides the experimental tensor schema.

Confirm exported CMake target names in the installed release. A typical manifest includes `rclcpp`, `tensor_msgs`, `torch_conversions`, and `cuda_buffer`, plus an execution dependency on `cuda_buffer_backend`.

For a raw-buffer target, the common source-build form is:

```cmake
find_package(cuda_buffer REQUIRED)
ament_target_dependencies(my_node cuda_buffer rclcpp sensor_msgs)
```

and:

```xml
<depend>cuda_buffer</depend>
<exec_depend>cuda_buffer_backend</exec_depend>
```

Verify these names against the backend installed in the target environment; experimental exports can change.

## Lifetime Review

- Destroy writable views before publish.
- Keep input views alive until all dependent work is enqueued on the same or explicitly synchronized stream.
- Do not call `cudaDeviceSynchronize`, blocking `cudaMemcpy`, or host inspection between GPU stages.
- Make external-library streams explicit with events when they differ from the ROS buffer handle stream.
