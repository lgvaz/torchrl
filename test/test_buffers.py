import pytest
import random
import numpy as np
import torchrl.utils as U
from collections import deque
from torchrl.utils.buffers import RingBuffer, ReplayBuffer


@pytest.fixture
def initialized_ring_buffer():
    maxlen = 4
    shape = (8, 1, 16, 16)
    buffer = RingBuffer(input_shape=(shape), maxlen=maxlen)

    for i in range(5):
        frame = i * np.ones((shape))
        buffer.append(frame)

    return buffer


def test_ring_buffer():
    maxlen = 4
    buffer = RingBuffer(input_shape=(8, 1, 16, 16), maxlen=maxlen)

    frame = np.ones((8, 1, 16, 16))
    buffer.append(frame)
    state = np.array(buffer.get_data())
    expected = np.zeros((8, 4, 16, 16))
    expected[:, 3, :, :] = np.ones((8, 16, 16))
    assert state.shape[1] == maxlen
    np.testing.assert_equal(state, expected)

    frame = 2 * np.ones((8, 1, 16, 16))
    buffer.append(frame)
    state = np.array(buffer.get_data())
    expected = np.zeros((8, 4, 16, 16))
    expected[:, 3, :, :] = 2 * np.ones((8, 16, 16))
    expected[:, 2, :, :] = np.ones((8, 16, 16))
    assert state.shape[1] == maxlen
    np.testing.assert_equal(state, expected)

    frame = 3 * np.ones((8, 1, 16, 16))
    buffer.append(frame)
    state = np.array(buffer.get_data())
    expected = np.zeros((8, 4, 16, 16))
    expected[:, 3, :, :] = 3 * np.ones((8, 16, 16))
    expected[:, 2, :, :] = 2 * np.ones((8, 16, 16))
    expected[:, 1, :, :] = np.ones((8, 16, 16))
    assert state.shape[1] == maxlen
    np.testing.assert_equal(state, expected)

    frame = 42 * np.ones((8, 1, 16, 16))
    buffer.append(frame)
    buffer.append(frame)
    buffer.append(frame)
    state = np.array(buffer.get_data())
    expected = np.zeros((8, 4, 16, 16))
    expected[:, 3, :, :] = 42 * np.ones((8, 16, 16))
    expected[:, 2, :, :] = 42 * np.ones((8, 16, 16))
    expected[:, 1, :, :] = 42 * np.ones((8, 16, 16))
    expected[:, 0, :, :] = 3 * np.ones((8, 16, 16))
    assert state.shape[1] == maxlen
    np.testing.assert_equal(state, expected)


def test_ring_buffer_consistency(initialized_ring_buffer):
    buffer = initialized_ring_buffer

    data_before = buffer.get_data()
    frame = 42 * np.ones((buffer.input_shape))
    buffer.append(frame)
    data_after = buffer.get_data()

    # data_before should not be changed by new append
    with pytest.raises(AssertionError):
        np.testing.assert_equal(np.array(data_before), np.array(data_after))


def test_ring_buffer_consistency2(initialized_ring_buffer):
    # Original data should not be modified after np.array is called
    buffer = initialized_ring_buffer

    data = np.array(buffer.get_data())
    data_before = data.copy()
    data += 1
    data_after = np.array(buffer.get_data())

    np.testing.assert_equal(data_before, data_after)


def test_ring_buffer_memory_optmization(initialized_ring_buffer):
    # No additional memory should be needed for stacking the same frame
    # in a different position
    buffer = initialized_ring_buffer

    data_before = buffer.get_data()
    frame = 42 * np.ones((buffer.input_shape))
    buffer.append(frame)
    data_after = buffer.get_data()

    for i_env in range(buffer.input_shape[0]):
        for before, after in zip(data_before.data[i_env][1:],
                                 data_after.data[i_env][:-1]):
            if not np.shares_memory(before, after):
                raise ValueError('Stacked frames should use the same memory')


def test_ring_buffer_error_handling():
    with pytest.raises(ValueError):
        RingBuffer(input_shape=(42, 42), maxlen=1)


@pytest.mark.parametrize('num_envs', [1, 4])
@pytest.mark.parametrize('batch_size', [1, 32])
def test_replay_buffer(num_envs, batch_size, maxlen=1000, seed=None):
    seed = seed or random.randint(0, 10000)
    real_maxlen = maxlen // num_envs

    replay_buffer = ReplayBuffer(maxlen=maxlen)
    memory = deque(maxlen=real_maxlen)

    for i in range(int(maxlen * 1.5 / num_envs)):
        state = i * create_test_array(num_envs=num_envs, shape=(1, 16, 16))
        action = i * create_test_array(num_envs=num_envs)
        reward = i * create_test_array(num_envs=num_envs)
        done = (i * 10 == 0) * np.ones((num_envs, ))

        replay_buffer.add_sample(state=state, action=action, reward=reward, done=done)
        memory.append(
            U.memories.SimpleMemory(state=state, action=action, reward=reward, done=done))

    random.seed(seed)
    batch = replay_buffer.sample(batch_size=batch_size)
    random.seed(seed)
    idxs = random.sample(range(len(memory) * num_envs), k=batch_size)

    for i, idx in enumerate(idxs):
        i_env, i_sample = idx % num_envs, idx // num_envs

        np.testing.assert_equal(batch.state[i], memory[i_sample].state[i_env])
        np.testing.assert_equal(batch.action[i], memory[i_sample].action[i_env])
        np.testing.assert_equal(batch.reward[i], memory[i_sample].reward[i_env])
        np.testing.assert_equal(batch.done[i], memory[i_sample].done[i_env])


@pytest.mark.parametrize('num_envs', [1, 4])
def test_replay_and_ring_buffer_memory_opt(num_envs):
    shape = (num_envs, 1, 3, 3)

    ring_buffer = RingBuffer(input_shape=(shape), maxlen=3)
    replay_buffer = ReplayBuffer(maxlen=5 * num_envs)

    for i in range(5 * num_envs + 3):
        state = create_test_array(num_envs=num_envs, shape=shape[1:])
        ring_buffer.append(state)
        replay_buffer.add_sample(state=ring_buffer.get_data())

    for i_sample in range(0, len(replay_buffer) - num_envs, num_envs):
        for i_env in range(num_envs):
            state = replay_buffer[i_sample + i_env].state.data
            next_state = replay_buffer[i_sample + i_env + num_envs].state.data

            for arr1, arr2 in zip(state[1:], next_state[:-1]):
                if not np.shares_memory(arr1, arr2):
                    raise ValueError('Arrays should share memory')


def create_test_array(num_envs, shape=()):
    return np.array([np.random.uniform(size=shape) for i in range(num_envs)])


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
