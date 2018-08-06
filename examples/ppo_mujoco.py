import torch.nn as nn
from torchrl.agents import PGAgent
from torchrl.batchers import RolloutBatcher
from torchrl.envs import GymEnv
from torchrl.models import PPOClipModel, ValueClipModel
from torchrl.optimizers import JointOpt
from torchrl.runners import PAACRunner, SingleRunner
from torchrl.utils import Config
from torchrl.batchers.transforms import mujoco_transforms
import torchrl.batchers.transforms as tfms

MAX_STEPS = 10e6

activation = nn.Tanh
# Define networks configs
policy_nn_config = Config(
    body=[
        dict(func=nn.Linear, out_features=64),
        dict(func=activation),
        dict(func=nn.Linear, in_features=64, out_features=64),
        dict(func=activation),
    ]
)
value_nn_config = Config(
    body=[
        dict(func=nn.Linear, out_features=64),
        dict(func=activation),
        dict(func=nn.Linear, in_features=64, out_features=64),
        dict(func=activation),
    ]
)

# Create environment
envs = [GymEnv("HalfCheetah-v2") for _ in range(16)]
runner = PAACRunner(envs)
# runner = SingleRunner(envs[0])

batcher = RolloutBatcher(
    runner, batch_size=2048, transforms=[tfms.StateRunNorm(), tfms.RewardRunScaler()]
)

policy_model_config = Config(nn_config=policy_nn_config)
policy_model = PPOClipModel.from_config(config=policy_model_config, batcher=batcher)

value_model_config = Config(nn_config=value_nn_config)
value_model = ValueClipModel.from_config(config=value_model_config, batcher=batcher)

jopt = JointOpt(
    model=[policy_model, value_model],
    num_epochs=4,
    num_mini_batches=4,
    opt_params=dict(lr=3e-4, eps=1e-5),
    clip_grad_norm=0.5,
)

# Create agent
agent = PGAgent(
    batcher=batcher,
    optimizer=jopt,
    policy_model=policy_model,
    value_model=value_model,
    log_dir="tests/nv4/cheetah/single-runtrew-v0-0",
    normalize_advantages=True,
)

agent.train(max_steps=MAX_STEPS)
