from os.path import join

import torch
import torch.nn as nn

from flx.setup.paths import BASE_DIR
from flx.visualization.layer_output_visualization import _visualize_center_loss


class CenterLoss(nn.Module):
    """Center loss.

    Reference:
    Wen et al. A Discriminative Feature Learning Approach for Deep Face Recognition. ECCV 2016.

    Args:
        num_classes (int): number of classes.
        feat_dim (int): feature dimension.
        alpha: "learning rate" of the centers. For each datapoint centers are updated by center + alpha * (datapoint - center)
    """

    def __init__(self, num_classes: int, feat_dim: int, alpha: float = 0.01):
        super(CenterLoss, self).__init__()
        self.alpha = alpha
        self.register_buffer(
            "centers",
            torch.nn.functional.normalize(torch.randn(num_classes, feat_dim), dim=1),
            persistent=True,
        )
        self.counter = 0
        self.nupdate = 0

    @torch.no_grad()
    def _disperse_centers(self) -> None:
        if False and self.counter < 10:
            self.counter += 1
            return
        self.counter = 0
        for factor in range(10):
            name = join(BASE_DIR, "debug", f"centers_factor{3**factor}")
            for i in range(100):
                self.nupdate += 1
                print("Update center loss!")
                outdir = join(name, "before", str(self.nupdate))
                _visualize_center_loss(self.centers, outdir)

                updates_accum = []

                sections = []
                MB_SIZE = 1000
                while (len(sections) + 1) * MB_SIZE < self.centers.shape[0]:
                    sections.append(MB_SIZE)
                sections.append(self.centers.shape[0] - (len(sections) * 2**factor))

                for minibatch in torch.split(self.centers, sections):
                    # Pairwise euclidean distance matrix of centers
                    distmat = torch.cdist(minibatch, self.centers)
                    # This essentially gives very close centers a weight of 1 / distance, If we multiply this
                    # by the vector difference this moves them at maximum 1.0 away from each other in opposite directions
                    simmat_mb = torch.nan_to_num(
                        torch.exp(-distmat) / (distmat * self.centers.shape[1]),
                        posinf=0.0,
                    )
                    # The centers push each other away with a stronger impact if they are closer together
                    update_mb = torch.einsum(
                        "bd,bm,fd->bd", minibatch, simmat_mb, -self.centers
                    )
                    updates_accum.append(update_mb)

                outdir = join(name, "update", str(self.nupdate))
                updates = torch.vstack(updates_accum)
                _visualize_center_loss(updates, outdir)
                with open(outdir + "\\report.txt", "w") as file:
                    cmax = torch.max(updates)
                    cmin = torch.min(updates)
                    file.write(f"max: {cmax} - min: {cmin}")
                self.centers = torch.nn.functional.normalize(
                    self.centers + torch.vstack(updates_accum)
                )
                outdir = join(name, "after", str(self.nupdate))
                _visualize_center_loss(self.centers, outdir)
        exit(0)

    def forward(self, x: torch.Tensor, labels: torch.LongTensor):
        """
        Args:
            x: feature matrix with shape (batch_size, feat_dim).
            labels: ground truth labels with shape (batch_size).
        """
        # Copy the centers into temporary matrix
        with torch.no_grad():
            batch_centers = torch.index_select(self.centers, 0, labels)
        # Get difference of x from batch centers
        diff = x - batch_centers
        # Update current centers
        with torch.no_grad():
            self.centers.index_add_(0, labels, diff, alpha=self.alpha)
            # self._disperse_centers()
        # Return mean loss
        return torch.sum(diff**2)
