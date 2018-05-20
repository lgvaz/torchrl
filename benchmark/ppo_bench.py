import os

import torch.nn as nn

import torchrl.utils as U
from bench import MUJOCO_SIMPLE_BENCH, MUJOCO_ESSENTIAL_BENCH, task_gen
from torchrl.agents import PGAgent
from torchrl.envs import GymEnv, ParallelEnv
from torchrl.models import PPOClipModel, ValueModel
from torchrl.nn import ActionLinear
from torchrl.utils import Config
from utils import NoDaemonProcessPool, config2str

CONFIG = Config(
    num_envs=16,
    max_steps=10e6,
    steps_per_batch=2048,
    normalize_advantages=True,
    normalize_states=True,
    scale_rewards=True,
    activation=nn.Tanh,
    ppo_policy_clip=0.2,
    value_clip=0.2,
    policy_opt_params=dict(lr=3e-4, eps=1e-5),
    value_opt_params=dict(lr=3e-4, eps=1e-5),
    value_batch_size=128,
    value_num_epochs=10,
    clip_grad_norm=0.5)

TASK = MUJOCO_ESSENTIAL_BENCH
NUM_WORKERS = 4


def run_bench(config):
    log_dir = config2str(config)
    log_dir = os.path.join('logs', config.env_name, log_dir)

    # Create env
    envs = [
        GymEnv(
            env_name=config.env_name,
            normalize_states=config.normalize_states,
            scale_rewards=config.scale_rewards) for _ in range(config.num_envs)
    ]
    env = ParallelEnv(envs)

    # Define networks configs
    policy_nn_config = Config(
        body=[
            dict(func=nn.Linear, out_features=64),
            dict(func=config.activation),
            dict(func=nn.Linear, in_features=64, out_features=64),
            dict(func=config.activation)
        ],
        head=[dict(func=ActionLinear)])

    value_nn_config = Config(
        body=[
            dict(func=nn.Linear, out_features=64),
            dict(func=config.activation),
            dict(func=nn.Linear, in_features=64, out_features=64),
            dict(func=config.activation)
        ],
        head=[dict(func=nn.Linear, out_features=1)])

    # Create Models
    policy_model_config = Config(nn_config=policy_nn_config)
    policy_model = PPOClipModel.from_config(
        config=policy_model_config,
        env=env,
        ppo_clip_range=config.ppo_policy_clip,
        opt_params=config.policy_opt_params,
        clip_grad_norm=config.clip_grad_norm)

    value_model_config = Config(nn_config=value_nn_config)
    value_model = ValueModel.from_config(
        config=value_model_config,
        env=env,
        clip_range=config.value_clip,
        opt_params=config.value_opt_params,
        batch_size=config.value_batch_size,
        num_epochs=config.value_num_epochs,
        clip_grad_norm=config.clip_grad_norm)

    # Create agent
    agent = PGAgent(
        env=env,
        policy_model=policy_model,
        value_model=value_model,
        normalize_advantages=config.normalize_advantages,
        log_dir=log_dir)

    agent.train(max_steps=config.max_steps, steps_per_batch=config.steps_per_batch)


if __name__ == '__main__':

    p = NoDaemonProcessPool(NUM_WORKERS)
    p.map_async(run_bench, task_gen(TASK, CONFIG)).get()
    p.join()
    p.close()

    p = NoDaemonProcessPool(NUM_WORKERS)
    CONFIG.num_envs = 32
    p.map_async(run_bench, task_gen(TASK, CONFIG)).get()
    p.join()
    p.close()

    p = NoDaemonProcessPool(NUM_WORKERS)
    CONFIG.num_envs = 16
    CONFIG.clip_grad_norm = None
    p.map_async(run_bench, task_gen(TASK, CONFIG)).get()
    p.join()
    p.close()

    p = NoDaemonProcessPool(NUM_WORKERS)
    CONFIG.steps_per_batch = 10000
    p.map_async(run_bench, task_gen(TASK, CONFIG)).get()
    p.join()
    p.close()
