"""cq 워커용 pcq 통합 train.py — MVTec bottle conv autoencoder 이상탐지.

CQ_CONFIG_JSON 주입(learning_rate/latent_dim/optimizer/batch_size/epochs/img_size)을
pcq.config()로 읽어, 정상(train/good)만으로 conv AE를 학습한다. test 이미지의
reconstruction MSE를 image-level anomaly score로 써 roc_auc_score(image_auroc)를 계산.
log_config로 effective hyperparam(P5)을 선언하고 describe_run을 describe.json으로 저장 →
cq_dispatch가 회수 → tc_ingest_pcq(정본 적재).
"""

import glob
import json
import os

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from sklearn.metrics import roc_auc_score
from torch.utils.data import DataLoader, Dataset

import pcq
from pcq.agent.describe import describe_run

DATA_ROOT = os.environ.get(
    "DATA_ROOT", "/Users/changmin/datasets/MVtec-ad/mvtec_anomaly_detection")
CATEGORY = "bottle"

# CQ_CONFIG_JSON 주입값 (next_config + smoke override)
cfg = pcq.config()
lr = float(cfg.get("learning_rate", 0.0005))
latent_dim = int(cfg.get("latent_dim", 64))
optimizer_name = str(cfg.get("optimizer", "Adam"))
batch_size = int(cfg.get("batch_size", 32))
epochs = int(cfg.get("epochs", 30))
img_size = int(cfg.get("img_size", 256))

device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")


class BottleDataset(Dataset):
    """bottle 이미지를 size×size RGB [0,1] 텐서로 로드."""

    def __init__(self, paths: list[str], size: int) -> None:
        self.paths = paths
        self.size = size

    def __len__(self) -> int:
        return len(self.paths)

    def __getitem__(self, i: int) -> torch.Tensor:
        im = Image.open(self.paths[i]).convert("RGB").resize((self.size, self.size))
        arr = np.asarray(im, dtype=np.float32) / 255.0
        return torch.from_numpy(arr).permute(2, 0, 1)


def list_train(root: str) -> list[str]:
    return sorted(glob.glob(f"{root}/{CATEGORY}/train/good/*.png"))


def list_test(root: str) -> tuple[list[str], list[int]]:
    """test 이미지 경로 + label(good=0, anomaly=1)."""
    paths = sorted(glob.glob(f"{root}/{CATEGORY}/test/*/*.png"))
    labels = [0 if "/good/" in p else 1 for p in paths]
    return paths, labels


class ConvAE(nn.Module):
    """256→16 다운샘플 conv 오토인코더. bottleneck 채널 = latent_dim."""

    def __init__(self, latent: int) -> None:
        super().__init__()
        self.enc = nn.Sequential(
            nn.Conv2d(3, 32, 4, 2, 1), nn.ReLU(True),
            nn.Conv2d(32, 64, 4, 2, 1), nn.ReLU(True),
            nn.Conv2d(64, 128, 4, 2, 1), nn.ReLU(True),
            nn.Conv2d(128, latent, 4, 2, 1), nn.ReLU(True),
        )
        self.dec = nn.Sequential(
            nn.ConvTranspose2d(latent, 128, 4, 2, 1), nn.ReLU(True),
            nn.ConvTranspose2d(128, 64, 4, 2, 1), nn.ReLU(True),
            nn.ConvTranspose2d(64, 32, 4, 2, 1), nn.ReLU(True),
            nn.ConvTranspose2d(32, 3, 4, 2, 1), nn.Sigmoid(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.dec(self.enc(x))


def evaluate(model: nn.Module, dl: DataLoader, labels: list[int]) -> float:
    """test recon MSE를 anomaly score로 image_auroc 계산."""
    model.eval()
    scores: list[float] = []
    with torch.no_grad():
        for x in dl:
            x = x.to(device)
            rec = model(x)
            err = ((rec - x) ** 2).mean(dim=[1, 2, 3])
            scores.extend(err.cpu().numpy().tolist())
    return float(roc_auc_score(labels, scores))


def main() -> None:
    train_paths = list_train(DATA_ROOT)
    test_paths, test_labels = list_test(DATA_ROOT)
    train_dl = DataLoader(BottleDataset(train_paths, img_size),
                          batch_size=batch_size, shuffle=True)
    test_dl = DataLoader(BottleDataset(test_paths, img_size),
                         batch_size=batch_size, shuffle=False)

    model = ConvAE(latent_dim).to(device)
    opt_cls = {"Adam": torch.optim.Adam, "AdamW": torch.optim.AdamW,
               "SGD": torch.optim.SGD}.get(optimizer_name, torch.optim.Adam)
    opt = opt_cls(model.parameters(), lr=lr)
    loss_fn = nn.MSELoss()

    history = []
    for ep in range(epochs):
        model.train()
        tot = 0.0
        for x in train_dl:
            x = x.to(device)
            opt.zero_grad()
            loss = loss_fn(model(x), x)
            loss.backward()
            opt.step()
            tot += loss.item() * x.size(0)
        train_loss = tot / len(train_paths)
        auroc = evaluate(model, test_dl, test_labels)
        history.append({"epoch": ep, "image_auroc": auroc, "train_loss": train_loss})
        print(f"@image_auroc={auroc:.4f} @train_loss={train_loss:.6f} epoch={ep}", flush=True)

    # P5: 실제 소비한 effective hyperparam 선언
    pcq.log_config(learning_rate=lr, latent_dim=latent_dim, optimizer=optimizer_name,
                   batch_size=batch_size, epochs=epochs, img_size=img_size,
                   backbone="conv_ae", category=CATEGORY, device=device.type)
    pcq.save_metrics(history)
    pcq.save_run_summary(history=history, status="completed")
    pcq.save_manifest()
    pcq.finalize_run(history=history)
    out = pcq.output_dir()
    with open(f"{out}/describe.json", "w", encoding="utf-8") as f:
        json.dump(describe_run(out).to_dict(), f, ensure_ascii=False)
    best = max(h["image_auroc"] for h in history)
    print(f"@image_auroc={best:.4f}", flush=True)


if __name__ == "__main__":
    main()
