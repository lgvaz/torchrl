import pdb
import fire
import torch
import numpy as np
import torch.nn as nn
import torch.nn.functional as F
import reward as rw
import reward.utils as U


class PolicyNN(nn.Module):
    def __init__(
        self,
        num_inputs,
        num_outputs,
        hidden_units=256,
        activation=nn.ReLU,
        log_std_range=(-20, 2),
    ):
        super().__init__()
        self.log_std_range = log_std_range

        layers = []
        layers += [nn.Linear(num_inputs, hidden_units), activation()]
        layers += [nn.Linear(hidden_units, hidden_units), activation()]
        self.layers = nn.Sequential(*layers)

        self.mean = nn.Linear(hidden_units, num_outputs)
        self.mean.weight.data.uniform_(-3e-3, 3e-3)
        self.mean.bias.data.uniform_(-3e-3, 3e-3)

        self.log_std = nn.Linear(hidden_units, num_outputs)
        self.log_std.weight.data.uniform_(-3e-3, 3e-3)
        self.log_std.bias.data.uniform_(-3e-3, 3e-3)

    def forward(self, x):
        x = self.layers(x)
        mean = self.mean(x)
        log_std = self.log_std(x).clamp(*self.log_std_range)
        return mean, log_std


class ValueNN(nn.Module):
    def __init__(self, num_inputs, hidden_units=256, activation=nn.ReLU):
        super().__init__()

        layers = []
        layers += [nn.Linear(num_inputs, hidden_units), activation()]
        layers += [nn.Linear(hidden_units, hidden_units), activation()]
        final_layer = nn.Linear(hidden_units, 1)
        final_layer.weight.data.uniform_(-3e-3, 3e-3)
        final_layer.bias.data.uniform_(-3e-3, 3e-3)
        layers += [final_layer]

        self.layers = nn.Sequential(*layers)

    def forward(self, x):
        return self.layers(x)


class QValueNN(nn.Module):
    def __init__(self, num_inputs, num_actions, hidden_units=256, activation=nn.ReLU):
        super().__init__()

        layers = []
        layers += [nn.Linear(num_inputs + num_actions, hidden_units), activation()]
        layers += [nn.Linear(hidden_units, hidden_units), activation()]
        final_layer = nn.Linear(hidden_units, 1)
        final_layer.weight.data.uniform_(-3e-3, 3e-3)
        final_layer.bias.data.uniform_(-3e-3, 3e-3)
        layers += [final_layer]

        self.layers = nn.Sequential(*layers)

    def forward(self, x):
        state, action = x
        x = torch.cat([state, action], dim=1)
        return self.layers(x)


class TanhNormalPolicy(rw.policy.BasePolicy):
    def create_dist(self, state):
        parameters = self.nn(state)
        mean, log_std = parameters
        return rw.distributions.TanhNormal(loc=mean, scale=log_std.exp())

    def get_action(self, state, step):
        dist = self.create_dist(state=state)
        action = U.to_np(dist.sample())
        assert not np.isnan(action).any()
        return action


def run(
    env_name,
    reward_scale,
    log_dir,
    lr=3e-4,
    max_steps=6e6,
    normalize_states=False,
    repar=True,
    target_up_weight=0.005,
    pr_factor_initial=0.7,
    pr_factor_final=0.7,
    is_factor_initial=0.4,
    is_factor_final=1.0,
    batch_size=256,
    replay_buffer_maxlen=1e6,
    learning_freq=1,
    grad_steps_per_batch=1,
    clip_grad=float("inf"),
    gamma=0.99,
    log_freq=4000,
    cuda_default=True,
    gpu=0,
):
    logger = U.Logger(log_dir)
    use_cuda = torch.cuda.is_available() and cuda_default
    device = torch.device("cuda:{}".format(gpu) if use_cuda else "cpu")
    U.device.set_device(device)

    # Create env and batcher
    env = rw.env.GymEnv(env_name)
    env = rw.env.wrappers.ActionBound(env)
    runner = rw.runner.SingleRunner(env)

    tfms = [rw.batcher.transforms.StateRunNorm()] if normalize_states else []
    pr_factor = U.schedules.linear_schedule(
        pr_factor_initial, pr_factor_final, max_steps
    )
    is_factor = U.schedules.linear_schedule(
        is_factor_initial, is_factor_final, max_steps
    )
    batcher = rw.batcher.PrReplayBatcher(
        runner=runner,
        batch_size=batch_size,
        replay_buffer_maxlen=replay_buffer_maxlen,
        learning_freq=learning_freq,
        grad_steps_per_batch=grad_steps_per_batch,
        transforms=tfms,
        pr_factor=pr_factor,
        is_factor=is_factor,
    )
    state_features = batcher.get_state_info().shape[0]
    num_actions = batcher.get_action_info().shape[0]
    # Create NNs
    p_nn = PolicyNN(num_inputs=state_features, num_outputs=num_actions).to(device)
    policy = TanhNormalPolicy(nn=p_nn)

    v_nn = ValueNN(num_inputs=state_features).to(device)
    v_nn_target = ValueNN(num_inputs=state_features).to(device).eval()
    U.copy_weights(from_nn=v_nn, to_nn=v_nn_target, weight=1.)

    q1_nn = QValueNN(num_inputs=state_features, num_actions=num_actions).to(device)
    q2_nn = QValueNN(num_inputs=state_features, num_actions=num_actions).to(device)

    p_opt = torch.optim.Adam(p_nn.parameters(), lr=lr)
    v_opt = torch.optim.Adam(v_nn.parameters(), lr=lr)
    q1_opt = torch.optim.Adam(q1_nn.parameters(), lr=lr)
    q2_opt = torch.optim.Adam(q2_nn.parameters(), lr=lr)

    # Main training loop
    batcher.populate(n=1000)
    for batch in batcher.get_batches(max_steps, policy.get_action):
        batch = batch.to_tensor().concat_batch()
        idx = U.to_np(batch.idx).astype("int")

        ##### Calculate losses ######
        q1_batch = q1_nn((batch.state_t, batch.action))
        q2_batch = q2_nn((batch.state_t, batch.action))
        v_batch = v_nn(batch.state_t)

        dist = policy.create_dist(batch.state_t)
        if repar:
            action, pre_tanh_action = dist.rsample_with_pre()
        else:
            action, pre_tanh_action = dist.sample_with_pre()
        log_prob = dist.log_prob_pre(pre_tanh_action).sum(-1, keepdim=True)
        log_prob /= float(reward_scale)

        # Q loss
        v_target_tp1 = v_nn_target(batch.state_tp1)
        q_t_next = U.estimators.td_target(
            rewards=batch.reward, dones=batch.done, v_tp1=v_target_tp1, gamma=gamma
        )
        # IS weight corrects for bias introduced by prioritized sampling
        is_weight = U.to_tensor(batcher.get_is_weight(idx=idx))
        td1_error = is_weight * (q1_batch - q_t_next.detach())
        td2_error = is_weight * (q2_batch - q_t_next.detach())
        q1_loss = td1_error.pow(2).mean()
        q2_loss = td2_error.pow(2).mean()

        # V loss
        q1_new_t = q1_nn((batch.state_t, action))
        q2_new_t = q2_nn((batch.state_t, action))
        q_new_t = torch.min(q1_new_t, q2_new_t)
        next_value = q_new_t - log_prob
        v_loss = F.mse_loss(v_batch, next_value.detach())

        # Policy loss
        if repar:
            p_losses = log_prob - q_new_t
        else:
            next_log_prob = q_new_t - v_batch
            p_losses = log_prob * (log_prob - next_log_prob).detach()
        # IS weight corrects for bias introduced by prioritized sampling
        p_losses *= is_weight
        p_loss = p_losses.mean()
        # Policy regularization losses
        mean_loss = 1e-3 * dist.loc.pow(2).mean()
        log_std_loss = 1e-3 * dist.scale.log().pow(2).mean()
        pre_tanh_loss = 0 * pre_tanh_action.pow(2).sum(1).mean()
        # Combine all losses
        p_loss_total = p_loss + mean_loss + log_std_loss + pre_tanh_loss

        ###### Optimize ######
        q1_opt.zero_grad()
        q1_loss.backward()
        # torch.nn.utils.clip_grad_norm_(q1_nn.parameters(), clip_grad)
        # q1_grad = U.mean_grad(q1_nn)
        q1_opt.step()

        q2_opt.zero_grad()
        q2_loss.backward()
        torch.nn.utils.clip_grad_norm_(q2_nn.parameters(), clip_grad)
        q2_grad = U.mean_grad(q2_nn)
        q2_opt.step()

        v_opt.zero_grad()
        v_loss.backward()
        # torch.nn.utils.clip_grad_norm_(v_nn.parameters(), clip_grad)
        # v_grad = U.mean_grad(v_nn)
        v_opt.step()

        p_opt.zero_grad()
        p_loss_total.backward()
        # torch.nn.utils.clip_grad_norm_(p_nn.parameters(), clip_grad)
        # p_grad = U.mean_grad(p_nn)
        p_opt.step()

        ###### Update target value network ######
        U.copy_weights(from_nn=v_nn, to_nn=v_nn_target, weight=target_up_weight)

        ###### Update replay batcher priorities #######
        p_priority = U.to_np(p_losses.abs()).squeeze()
        q_priority = U.to_np((q_t_next - q_new_t).abs()).squeeze()
        priority = p_priority + q_priority
        batcher.update_pr(idx=idx, pr=priority)

        ###### Write logs ######
        if batcher.num_steps % int(log_freq) == 0 and batcher.runner.rewards:
            batcher.write_logs(logger)

            logger.add_log("policy/loss", p_loss)
            logger.add_log("v/loss", v_loss)
            logger.add_log("q1/loss", q1_loss)
            logger.add_log("q2/loss", q2_loss)

            # logger.add_log("policy/grad", p_grad)
            # logger.add_log("v/grad", v_grad)
            # logger.add_log("q1/grad", q1_grad)
            # logger.add_log("q2/grad", q2_grad)

            logger.add_histogram("policy/log_prob", log_prob)
            logger.add_histogram("policy/mean", dist.loc)
            logger.add_histogram("policy/std", dist.scale.exp())
            logger.add_histogram("v/value", v_batch)
            logger.add_histogram("q1/value", q1_batch)
            logger.add_histogram("q2/value", q2_batch)

            logger.add_histogram("replay/is_weight", is_weight)
            logger.add_log(
                "replay/alpha", batcher.replay_buffer.get_pr_factor(batcher.num_steps)
            )
            logger.add_log(
                "replay/beta", batcher.replay_buffer.get_is_factor(batcher.num_steps)
            )

            logger.log(step=batcher.num_steps)


if __name__ == "__main__":
    fire.Fire(run)

# run(
#     env_name="Humanoid-v2",
#     reward_scale=20.,
#     log_dir="/tmp/logs/tests",
#     normalize_states=False,
# )
