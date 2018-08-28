import torch
import torch.nn as nn
import torchrl as tr
import torch.nn.functional as F
from torchrl.models import TargetModel
from torchrl.nn import FlattenLinear


class DDPGCritic(TargetModel):
    @property
    def batch_keys(self):
        return ["state_t", "q_target"]

    @property
    def body(self):
        raise NotImplementedError

    @property
    def head(self):
        raise NotImplementedError

    def register_losses(self):
        self.register_loss(self.critic_loss)

    # TODO: Can be removed?? Look at others QModel too
    # TODO: Using memory instead of batch will have problems with mini_batches
    # def add_target_value(self, batch):
    #     with torch.no_grad():
    #         self.memory.target_value = self.target_nn(
    #             input=(batch.state_tp1, batch.target_action)
    #         )

    def critic_loss(self, batch):
        pred = self((batch.state_t, batch.action)).squeeze()
        loss = F.mse_loss(input=pred, target=batch.q_target)
        return loss

    @classmethod
    def from_config(cls, *args, **kwargs):
        raise NotImplementedError

    @staticmethod
    def output_layer(input_shape, action_shape, action_space):
        if action_space != "continuous":
            raise ValueError(
                "Only works with continuous actions, got {}".format(action_space)
            )
        layer = FlattenLinear(in_features=input_shape, out_features=1)
        layer.weight.data.uniform_(-3e-3, 3e-3)
        return layer