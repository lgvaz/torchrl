import pytest
import random
import numpy as np
import reward.utils as U
from collections import deque
from reward.utils.buffers import RingBuffer, ReplayBuffer
from .utils import create_test_array


def test_ring_buffer():
    maxlen = 4
    shape = (8, 1, 16, 16)
    expected_shape = (maxlen,) + shape
    buffer = RingBuffer(input_shape=shape, maxlen=maxlen)

    frame = np.ones(shape)
    buffer.append(frame)
    s = U.to_np(buffer.get_data())
    expected = np.zeros(expected_shape)
    expected[3] = np.ones(shape)
    assert s.shape[0] == maxlen
    np.testing.assert_equal(s, expected)

    frame = 2 * np.ones(shape)
    buffer.append(frame)
    s = np.array(buffer.get_data())
    expected = np.zeros(expected_shape)
    expected[3] = 2 * np.ones(shape)
    expected[2] = np.ones(shape)
    assert s.shape[0] == maxlen
    np.testing.assert_equal(s, expected)

    frame = 3 * np.ones(shape)
    buffer.append(frame)
    s = np.array(buffer.get_data())
    expected = np.zeros(expected_shape)
    expected[3] = 3 * np.ones(shape)
    expected[2] = 2 * np.ones(shape)
    expected[1] = np.ones(shape)
    assert s.shape[0] == maxlen
    np.testing.assert_equal(s, expected)

    frame = 42 * np.ones(shape)
    buffer.append(frame)
    buffer.append(frame)
    buffer.append(frame)
    s = np.array(buffer.get_data())
    expected = np.zeros(expected_shape)
    expected[3] = 42 * np.ones(shape)
    expected[2] = 42 * np.ones(shape)
    expected[1] = 42 * np.ones(shape)
    expected[0] = 3 * np.ones(shape)
    assert s.shape[0] == maxlen
    np.testing.assert_equal(s, expected)


@pytest.mark.parametrize("num_envs", [1, 8])
@pytest.mark.parametrize("shape", [(1, 16, 16), (1, 3, 4), (1, 1, 1)])
def test_ring_buffer_consistency(num_envs, shape):
    maxlen = 4
    shape = (num_envs,) + shape
    buffer = RingBuffer(input_shape=(shape), maxlen=maxlen)

    data_before = buffer.get_data()
    frame = 42 * np.ones((buffer.input_shape))
    buffer.append(frame)
    data_after = buffer.get_data()

    # data_before should not be changed by new append
    with pytest.raises(AssertionError):
        np.testing.assert_equal(np.array(data_before), np.array(data_after))


@pytest.mark.parametrize("num_envs", [1, 8])
@pytest.mark.parametrize("shape", [(1, 16, 16), (1, 3, 4), (1, 1, 1)])
def test_ring_buffer_consistency2(num_envs, shape):
    # Original data should not be modified after np.array is called
    maxlen = 4
    shape = (num_envs,) + shape
    buffer = RingBuffer(input_shape=(shape), maxlen=maxlen)

    data = np.array(buffer.get_data())
    data_before = data.copy()
    data += 1
    data_after = np.array(buffer.get_data())

    np.testing.assert_equal(data_before, data_after)


@pytest.mark.parametrize("num_envs", [1, 8])
@pytest.mark.parametrize("shape", [(1, 3, 3), (1, 3, 4), (1, 1, 1)])
def test_ring_buffer_nested_lazyframe(num_envs, shape):
    maxlen = 4
    shape = (num_envs,) + shape
    buffer = RingBuffer(input_shape=(shape), maxlen=maxlen)
    transform = lambda x: x / 10

    frames = deque(maxlen=maxlen)
    for _ in range(maxlen + 2):
        frame = 42 * np.random.normal(size=buffer.input_shape)
        lazy_frame = U.LazyArray(frame, transform=transform)
        frames.append(frame)
        buffer.append(lazy_frame)

    actual = U.to_np(buffer.get_data())
    expected = transform(U.to_np(frames))

    np.testing.assert_equal(actual, expected)


@pytest.mark.parametrize("num_envs", [1, 8])
def test_ring_buffer_memory_optmization(num_envs):
    # No additional memory should be needed for stacking the same frame
    # in a different position
    maxlen = 4
    shape = (num_envs, 1, 16, 16)
    buffer = RingBuffer(input_shape=(shape), maxlen=maxlen)

    data_before = buffer.get_data()
    frame = 42 * np.ones((buffer.input_shape))
    buffer.append(frame)
    data_after = buffer.get_data()

    for before, after in zip(data_before.data[1:], data_after.data[:-1]):
        if not np.shares_memory(before, after):
            raise ValueError("Stacked frames should use the same memory")


def test_ring_buffer_error_handling():
    with pytest.raises(ValueError):
        RingBuffer(input_shape=(42, 42), maxlen=1)


@pytest.mark.parametrize("num_envs", [1, 4])
@pytest.mark.parametrize("batch_size", [1, 32])
@pytest.mark.parametrize("shape", [(1, 16, 16), (1, 3, 6), (1, 1, 1)])
def test_rbuff(num_envs, shape, batch_size, maxlen=1000, seed=None):
    seed = seed or random.randint(0, 10000)
    real_maxlen = maxlen // num_envs

    rbuff = ReplayBuffer(maxlen=maxlen, num_envs=num_envs)
    memory = deque(maxlen=real_maxlen)

    for i in range(int(maxlen * 1.5 / num_envs)):
        s = i * create_test_array(num_envs=num_envs, shape=shape)
        ac = i * create_test_array(num_envs=num_envs)
        r = i * create_test_array(num_envs=num_envs)
        d = (i * 10 == 0) * np.ones((num_envs,))

        rbuff.add_sample(s=s, ac=ac, r=r, d=d)
        memory.append(U.memories.SimpleMemory(s=s, ac=ac, r=r, d=d))
    assert len(rbuff) == real_maxlen

    random.seed(seed)
    batch = rbuff.sample(batch_size=batch_size).concat_batch()
    random.seed(seed)
    env = random.choices(range(num_envs), k=batch_size)
    idxs = random.sample(range(len(memory)), k=batch_size)

    for i, (i_env, i_idx) in enumerate(zip(env, idxs)):
        np.testing.assert_equal(batch.s[i], memory[i_idx].s[i_env])
        np.testing.assert_equal(batch.ac[i], memory[i_idx].ac[i_env])
        np.testing.assert_equal(batch.r[i], memory[i_idx].r[i_env])
        np.testing.assert_equal(batch.d[i], memory[i_idx].d[i_env])


# TODO: Doesn't work with new RingBuffer, should be substituted by StackFrames test
# @pytest.mark.parametrize('num_envs', [1, 4])
# def test_replay_and_ring_buffer_memory_opt(num_envs):
#     shape = (num_envs, 1, 3, 3)

#     ring_buffer = RingBuffer(input_shape=(shape), maxlen=3)
#     rbuff = ReplayBuffer(maxlen=5 * num_envs)

#     for i in range(5 * num_envs + 3):
#         s = create_test_array(num_envs=num_envs, shape=shape[1:])
#         ring_buffer.append(s)
#         rbuff.add_sample(s=ring_buffer.get_data())

#     for i_sample in range(0, len(rbuff) - num_envs, num_envs):
#         for i_env in range(num_envs):
#             s = rbuff[i_sample + i_env].s.data
#             sn = rbuff[i_sample + i_env + num_envs].s.data

#             for arr1, arr2 in zip(s[1:], sn[:-1]):
#                 if not np.shares_memory(arr1, arr2):
#                     raise ValueError('Arrays should share memory')

# def test_strided_axis_simple():
#     WINDOW = 3

#     arr1 = np.arange(10 * 4).reshape(10, 4)
#     arr2 = 10 * np.arange(10 * 4).reshape(10, 4)

#     # (num_samples, num_envs, *features)
#     arr = np.stack((arr1, arr2), axis=1)
#     # (windows, num_envs, window_len, *features)
#     strided = strided_axis(arr=arr, window_size=WINDOW)

#     num_rolling_windows = (arr.shape[0] - WINDOW + 1)
#     for i in range(num_rolling_windows):
#         expected1 = arr1[i:i + WINDOW]
#         expected2 = arr2[i:i + WINDOW]

#         np.testing.assert_equal(strided[i * 2], expected1)
#         np.testing.assert_equal(strided[i * 2 + 1], expected2)

# def test_strided_axis_complex():
#     WINDOW = 7
#     NUM_ENVS = 10

#     arrs = create_test_array(num_envs=NUM_ENVS, shape=(1000, 1, 16, 16))

#     # (num_samples, num_envs, *features)
#     arr = np.stack(arrs, axis=1)
#     # (windows, num_envs, window_len, *features)
#     strided = strided_axis(arr=arr, window_size=WINDOW)

#     num_rolling_windows = (arr.shape[0] - WINDOW + 1)
#     for i in range(num_rolling_windows):
#         for i_env in range(NUM_ENVS):
#             expected = arrs[i_env][i:i + WINDOW]

#             np.testing.assert_equal(strided[i * NUM_ENVS + i_env], expected)
