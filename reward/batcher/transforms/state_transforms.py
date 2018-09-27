import reward.utils as U
from .base_transform import BaseTransform


class StackStates(BaseTransform):
    def __init__(self, n, dim=1):
        super().__init__()
        self.n = n
        self.dim = dim
        self.ring_buffer = None
        self.eval_ring_buffer = None

        if dim != 1:
            err_msg = (
                "Because of the way of the way the replay_buffer is currently"
                "implemented, we're only allowed to stack in the first dimension"
                "(which should be the case for image stacking). Support for other"
                "options will be added in the future"
            )
            raise ValueError(err_msg)

    def transform(self, state):
        state = U.to_np(state)
        assert (
            state.shape[self.dim + 1] == 1
        ), "Dimension to stack must be 1 but it is {}".format(
            state.shape[self.dim + 1]
        )

        return state.swapaxes(0, self.dim + 1)[0]

    def transform_state(self, state, training=True):
        if self.ring_buffer is None:
            self.ring_buffer = U.buffers.RingBuffer(
                input_shape=state.shape, maxlen=self.n
            )
        if self.eval_ring_buffer is None:
            # First dimension (num_envs) for evaluation is always 1
            eval_shape = (1,) + state.shape[1:]
            self.eval_ring_buffer = U.buffers.RingBuffer(
                input_shape=eval_shape, maxlen=self.n
            )

        if training:
            self.ring_buffer.append(state)
            state = self.ring_buffer.get_data()
        else:
            self.eval_ring_buffer.append(state)
            state = self.eval_ring_buffer.get_data()

        return self.transform(state)


class StateRunNorm(BaseTransform):
    def __init__(self, clip_range=5):
        super().__init__()
        self.filt = None
        self.clip_range = clip_range

    def transform_state(self, state, training=True):
        if self.filt is None:
            shape = state.shape
            if len(shape) != 2:
                msg = "state shape must (num_envs, num_features, got {})".format(shape)
                raise ValueError(msg)
            self.filt = U.filter.MeanStdFilter(
                num_features=state.shape[-1], clip_range=self.clip_range
            )

        state = self.filt.normalize(state, add_sample=training)
        return state

    def transform_batch(self, batch, training=True):
        if training:
            self.filt.update()
        return batch

    def write_logs(self, logger):
        logger.add_tf_only_log("Env/State/mean", self.filt.mean.mean())
        logger.add_tf_only_log("Env/State/std", self.filt.std.mean())


class Frame2Float(BaseTransform):
    def transform_state(self, state, training=True):
        return state.astype("float32") / 255.