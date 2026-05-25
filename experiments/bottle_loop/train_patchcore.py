"""cq 워커용 pcq 통합 — MVTec PatchCore 계열 feature-memory 이상탐지.

pretrained backbone(layer2+layer3)의 locally-aware patch feature를 train/good에서 memory
bank로 모으고(coreset 근사 = random subsample), test patch의 memory 최근접 L2 거리를 anomaly
score로 쓴다(image score = patch 거리 최대값). 학습 파라미터 없음(forward만) — 작은 표면
결함(screw 등)에 강한 SOTA 계열. CQ_CONFIG_JSON 주입 → describe_run → describe.json.
"""

import glob
import json
import os

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image
from sklearn.metrics import roc_auc_score
from torch.utils.data import DataLoader, Dataset
from torchvision.models import (ResNet50_Weights, Wide_ResNet50_2_Weights,
                                resnet50, wide_resnet50_2)

import pcq
from pcq.agent.describe import describe_run

DATA_ROOT = os.environ.get(
    "DATA_ROOT", "/Users/changmin/datasets/MVtec-ad/mvtec_anomaly_detection")

cfg = pcq.config()
img_size = int(cfg.get("img_size", 384))
backbone_name = str(cfg.get("backbone", "wide_resnet50_2"))
CATEGORY = str(cfg.get("category", "screw"))
memory_size = int(cfg.get("memory_size", 10000))
batch_size = int(cfg.get("batch_size", 4))

device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]


class MVTecDS(Dataset):
    def __init__(self, paths: list[str], size: int) -> None:
        self.paths = paths
        self.size = size

    def __len__(self) -> int:
        return len(self.paths)

    def __getitem__(self, i: int) -> torch.Tensor:
        im = Image.open(self.paths[i]).convert("RGB").resize((self.size, self.size))
        a = np.asarray(im, dtype=np.float32) / 255.0
        t = torch.from_numpy(a).permute(2, 0, 1)
        for c in range(3):
            t[c] = (t[c] - IMAGENET_MEAN[c]) / IMAGENET_STD[c]
        return t


def list_train(r: str) -> list[str]:
    return sorted(glob.glob(f"{r}/{CATEGORY}/train/good/*.png"))


def list_test(r: str) -> tuple[list[str], list[int]]:
    p = sorted(glob.glob(f"{r}/{CATEGORY}/test/*/*.png"))
    return p, [0 if "/good/" in x else 1 for x in p]


class FeatNet(nn.Module):
    """backbone layer2, layer3 feature 추출기 (frozen)."""

    def __init__(self, backbone: str) -> None:
        super().__init__()
        if backbone == "resnet50":
            m = resnet50(weights=ResNet50_Weights.IMAGENET1K_V2)
        else:
            m = wide_resnet50_2(weights=Wide_ResNet50_2_Weights.IMAGENET1K_V1)
        self.stem = nn.Sequential(m.conv1, m.bn1, m.relu, m.maxpool)
        self.l1, self.l2, self.l3 = m.layer1, m.layer2, m.layer3

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        x = self.stem(x)
        x = self.l1(x)
        f2 = self.l2(x)
        f3 = self.l3(f2)
        return f2, f3


def embed(model: nn.Module, x: torch.Tensor) -> torch.Tensor:
    """locally-aware patch feature (layer2 + upsampled layer3, 3x3 이웃 평균) → (B*H*W, C)."""
    f2, f3 = model(x)
    f2 = F.avg_pool2d(f2, 3, 1, 1)
    f3 = F.avg_pool2d(f3, 3, 1, 1)
    f3 = F.interpolate(f3, size=f2.shape[-2:], mode="bilinear", align_corners=False)
    e = torch.cat([f2, f3], dim=1)
    b, c, h, w = e.shape
    return e.permute(0, 2, 3, 1).reshape(b, h * w, c)


def main() -> None:
    tr = list_train(DATA_ROOT)
    te, lab = list_test(DATA_ROOT)
    trdl = DataLoader(MVTecDS(tr, img_size), batch_size=batch_size, shuffle=False, num_workers=0)
    tedl = DataLoader(MVTecDS(te, img_size), batch_size=batch_size, shuffle=False, num_workers=0)

    model = FeatNet(backbone_name).to(device).eval()
    for p in model.parameters():
        p.requires_grad = False

    # memory bank: train/good 모든 patch → CPU 누적 후 coreset 근사(random subsample)
    mem = []
    with torch.no_grad():
        for x in trdl:
            emb = embed(model, x.to(device))  # (B, HW, C)
            mem.append(emb.reshape(-1, emb.size(-1)).cpu())
    bank = torch.cat(mem, dim=0)
    if bank.size(0) > memory_size:
        bank = bank[torch.randperm(bank.size(0))[:memory_size]]
    bank = bank.to(device)

    # test: 각 이미지 patch의 memory 최근접 거리 → image score = max
    scores = []
    with torch.no_grad():
        for x in tedl:
            x = x.to(device)
            e = embed(model, x)  # (B, HW, C)
            for img_patches in e:
                d = torch.cdist(img_patches, bank)
                scores.append(float(d.min(dim=1).values.max().cpu()))
    auroc = float(roc_auc_score(lab, scores))
    print(f"@image_auroc={auroc:.4f}", flush=True)

    history = [{"epoch": 0, "image_auroc": auroc}]
    pcq.log_config(backbone=backbone_name, img_size=img_size, category=CATEGORY,
                   method="patchcore_feature_memory", memory_size=int(bank.size(0)),
                   device=device.type)
    pcq.save_metrics(history)
    pcq.save_run_summary(history=history, status="completed")
    pcq.save_manifest()
    pcq.finalize_run(history=history)
    out = pcq.output_dir()
    with open(f"{out}/describe.json", "w", encoding="utf-8") as f:
        json.dump(describe_run(out).to_dict(), f, ensure_ascii=False)


if __name__ == "__main__":
    main()
