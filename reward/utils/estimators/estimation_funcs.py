import torch
import numpy as np
from reward.utils import to_tensor
from copy import deepcopy


def discounted_sum_rs(rs, dones, v_t_last=None, gamma=0.99):
    """
    Expected shape: (num_samples, num_envs)
    """
    rs = deepcopy(rs)

    # TODO: This works but is messy
    is_tensor = lambda x: isinstance(x, torch.Tensor)
    if any(map(is_tensor, (rs, dones, v_t_last))):
        rs, dones = to_tensor(rs), to_tensor(dones)
        v_last = to_tensor(v_t_last) if v_t_last is not None else v_t_last
        tensor = True
    else: tensor = False

    # if v_t_last is None and not all(dones[-1]):
    #     raise AssertionError('If one episode is not finished you must'
    #                          'pass a value to v_t_last to bootstrap from.')

    if v_t_last is not None: rs[-1][dones[-1] == 0] = v_t_last[dones[-1] == 0]

    returns = np.zeros(rs.shape, dtype="float32")
    returns_sum = np.zeros(rs.shape[-1], dtype="float32")
    if tensor: returns, returns_sum = map(to_tensor, (returns, returns_sum))

    for i in reversed(range(rs.shape[0])):
        returns_sum = rs[i] + gamma * returns_sum * (1 - dones[i])
        returns[i] = returns_sum

    return returns

def td_target(*, rs, dones, v_tp1, gamma):
    return rs + (1 - dones) * gamma * v_tp1

# TODO: Test this
def q_learning_target(*, rs, dones, q_tp1, gamma):
    max_q_tp1, _ = q_tp1.max(dim=1)
    return td_target(rs=rs, dones=dones, v_tp1=max_q_tp1, gamma=gamma)

def gae_estimation(rs, dones, v_t, v_tp1, *, gamma, gae_lambda):
    td_target_value = td_target(rs=rs, dones=dones, v_tp1=v_tp1, gamma=gamma)
    td_residual = td_target_value - v_t

    advantages = discounted_sum_rs(
        rs=td_residual, dones=dones, v_t_last=None, gamma=gamma * gae_lambda
    )

    return advantages
