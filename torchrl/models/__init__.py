"""
| A model encapsulate two PyTorch networks (body and head).
| It defines how actions are sampled from the network and a training procedure.
|
"""
from .base_model import BaseModel
from .base_pg_model import BasePGModel
from .base_value_model import BaseValueModel
from .value_model import ValueModel
from .value_clip_model import ValueClipModel
from .vanilla_pg_model import VanillaPGModel
from .a2c_model import A2CModel
from .surrogate_pg_model import SurrogatePGModel
from .ppo_clip_model import PPOClipModel
from .ppo_adaptive_model import PPOAdaptiveModel
from .q_model import QModel
from .dqn_model import DQNModel

__all__ = [
    "BaseModel",
    "ValueModel",
    "BasePGModel",
    "VanillaPGModel",
    "SurrogatePGModel",
    "PPOClipModel",
    "PPOAdaptiveModel",
    "A2CModel",
    "ValueClipModel",
    "QModel",
    "DQNModel",
]
