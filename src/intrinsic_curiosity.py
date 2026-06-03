import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
from typing import Dict, Any, Tuple

class IntrinsicCuriosityModule(nn.Module):
    """
    Intrinsic Curiosity Module (ICM) using PyTorch.
    Compares the predicted next state feature vector with the actual next state feature vector.
    The prediction error acts as the intrinsic curiosity reward.
    """
    def __init__(self, 
                 obs_dim: int, 
                 action_dim: int = 5, 
                 feature_dim: int = 16, 
                 eta: float = 10.0, 
                 beta: float = 0.2, 
                 lr: float = 1e-3):
        super(IntrinsicCuriosityModule, self).__init__()
        
        self.eta = eta
        self.beta = beta
        self.action_dim = action_dim
        
        # 1. Feature Extractor: phi(s)
        self.feature_extractor = nn.Sequential(
            nn.Linear(obs_dim, 32),
            nn.ReLU(),
            nn.Linear(32, feature_dim),
            nn.ReLU()
        )
        
        # 2. Forward Dynamics Model: f(phi(s), action) -> predicted phi(s_next)
        self.forward_model = nn.Sequential(
            nn.Linear(feature_dim + action_dim, 32),
            nn.ReLU(),
            nn.Linear(32, feature_dim)
        )
        
        # 3. Inverse Dynamics Model: g(phi(s), phi(s_next)) -> predicted action
        self.inverse_model = nn.Sequential(
            nn.Linear(feature_dim * 2, 32),
            nn.ReLU(),
            nn.Linear(32, action_dim)
        )
        
        self.optimizer = optim.Adam(self.parameters(), lr=lr)
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.to(self.device)

    def _one_hot_action(self, action: int) -> torch.Tensor:
        """Convert scalar discrete action into one-hot tensor."""
        act_tensor = torch.zeros(self.action_dim, device=self.device)
        act_tensor[action] = 1.0
        return act_tensor

    def compute_intrinsic_reward(self, obs: np.ndarray, next_obs: np.ndarray, action: int) -> float:
        """
        Evaluate curiosity reward based on state prediction error.
        R_int = eta * 0.5 * || phi_pred(s_next) - phi(s_next) ||^2
        """
        self.eval()
        with torch.no_grad():
            obs_t = torch.FloatTensor(obs).to(self.device).unsqueeze(0)
            next_obs_t = torch.FloatTensor(next_obs).to(self.device).unsqueeze(0)
            action_onehot = self._one_hot_action(action).unsqueeze(0)
            
            # Encode states
            phi_s = self.feature_extractor(obs_t)
            phi_s_next = self.feature_extractor(next_obs_t)
            
            # Forward model prediction
            forward_input = torch.cat([phi_s, action_onehot], dim=-1)
            phi_s_next_pred = self.forward_model(forward_input)
            
            # Prediction error (Mean Squared Error)
            pred_error = nn.functional.mse_loss(phi_s_next_pred, phi_s_next, reduction="sum")
            
            intrinsic_reward = self.eta * 0.5 * pred_error.item()
            return float(intrinsic_reward)

    def update_icm(self, obs: np.ndarray, next_obs: np.ndarray, action: int) -> Tuple[float, float]:
        """
        Update the forward and inverse model parameters.
        Loss = (1 - beta) * Loss_Inverse + beta * Loss_Forward
        """
        self.train()
        self.optimizer.zero_grad()
        
        obs_t = torch.FloatTensor(obs).to(self.device).unsqueeze(0)
        next_obs_t = torch.FloatTensor(next_obs).to(self.device).unsqueeze(0)
        action_onehot = self._one_hot_action(action).unsqueeze(0)
        action_target = torch.tensor([action], dtype=torch.long, device=self.device)

        # 1. Feature representations
        phi_s = self.feature_extractor(obs_t)
        phi_s_next = self.feature_extractor(next_obs_t)

        # 2. Forward Loss
        forward_input = torch.cat([phi_s, action_onehot], dim=-1)
        phi_s_next_pred = self.forward_model(forward_input)
        forward_loss = nn.functional.mse_loss(phi_s_next_pred, phi_s_next)

        # 3. Inverse Loss
        inverse_input = torch.cat([phi_s, phi_s_next], dim=-1)
        action_logits = self.inverse_model(inverse_input)
        inverse_loss = nn.functional.cross_entropy(action_logits, action_target)

        # Total Loss
        total_loss = (1 - self.beta) * inverse_loss + self.beta * forward_loss
        total_loss.backward()
        self.optimizer.step()

        return forward_loss.item(), inverse_loss.item()
