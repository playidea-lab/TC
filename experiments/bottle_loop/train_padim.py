"""cq 워커용 pcq 통합 — MVTec PaDiM (Patch Distribution Modeling) 이상탐지.

explore-loop Tier2 저술 recipe(gaussian-feature 계열). pretrained backbone(layer1-3)의
patch feature를 random n_features 차원으로 줄여, train/good에서 **각 spatial 위치별
다변량 가우시안(μ, Σ)** 을 적합한다. test patch의 위치별 Mahalanobis 거리를 anomaly
score로 쓰고 image score = 위치 최대값. 학습 파라미터 없음(forward + 통계량).
capacity 축 = n_features(가우시안 표현 차원). MPS linalg 공백 회피 위해 backbone forward만
MPS, 가우시안/역행렬/Mahalanobis는 CPU. CQ_CONFIG_JSON 주입 → describe_run → describe.json.
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
from torchvision.models import (ResNet18_Weights, Wide_ResNet50_2_Weights,
                                resnet18, wide_resnet50_2)

import pcq
from pcq.agent.describe import describe_run

cfg = pcq.config()
# 데이터 루트: cfg.data_root(신규 규약) 우선, 없으면 env DATA_ROOT, 그것도 없으면 MVTec 기본
DATA_ROOT = str(cfg.get("data_root") or os.environ.get(
    "DATA_ROOT", "/Users/changmin/datasets/MVtec-ad/mvtec_anomaly_detection"))
img_size = int(cfg.get("img_size", 256))
backbone_name = str(cfg.get("backbone", "resnet18"))
CATEGORY = str(cfg.get("category", "screw"))
n_features = int(cfg.get("n_features", 100))  # capacity 축: 랜덤 선택 feature 차원
batch_size = int(cfg.get("batch_size", 8))

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
    """backbone layer1, layer2, layer3 feature 추출기 (frozen)."""

    def __init__(self, backbone: str) -> None:
        super().__init__()
        if backbone == "wide_resnet50_2":
            m = wide_resnet50_2(weights=Wide_ResNet50_2_Weights.IMAGENET1K_V1)
        else:
            m = resnet18(weights=ResNet18_Weights.IMAGENET1K_V1)
        self.stem = nn.Sequential(m.conv1, m.bn1, m.relu, m.maxpool)
        self.l1, self.l2, self.l3 = m.layer1, m.layer2, m.layer3

    def forward(self, x: torch.Tensor) -> list[torch.Tensor]:
        x = self.stem(x)
        f1 = self.l1(x)
        f2 = self.l2(f1)
        f3 = self.l3(f2)
        return [f1, f2, f3]


def embed(model: nn.Module, x: torch.Tensor, idx: torch.Tensor) -> torch.Tensor:
    """layer1-3을 layer2 해상도로 맞춰 concat → random n_features 선택 → (B, HW, n_features)."""
    feats = model(x)
    base = feats[1].shape[-2:]  # layer2 해상도(=img/8)로 통일
    resized = [F.interpolate(f, size=base, mode="bilinear", align_corners=False) for f in feats]
    e = torch.cat(resized, dim=1)  # (B, C, H, W)
    b, c, h, w = e.shape
    e = e.permute(0, 2, 3, 1).reshape(b, h * w, c)
    return e.index_select(2, idx)  # random subset


def main() -> None:
    tr = list_train(DATA_ROOT)
    te, lab = list_test(DATA_ROOT)
    trdl = DataLoader(MVTecDS(tr, img_size), batch_size=batch_size, shuffle=False, num_workers=0)
    tedl = DataLoader(MVTecDS(te, img_size), batch_size=batch_size, shuffle=False, num_workers=0)

    model = FeatNet(backbone_name).to(device).eval()
    for p in model.parameters():
        p.requires_grad = False

    # 전체 feature 채널 수 파악 후 random n_features 인덱스 고정(시드)
    with torch.no_grad():
        probe = model(torch.zeros(1, 3, img_size, img_size, device=device))
    total_c = sum(f.shape[1] for f in probe)
    n_sel = min(n_features, total_c)
    g = torch.Generator().manual_seed(1234)
    idx = torch.randperm(total_c, generator=g)[:n_sel].to(device)

    # train: 위치별 임베딩 누적 (CPU)
    embs = []
    with torch.no_grad():
        for x in trdl:
            e = embed(model, x.to(device), idx)  # (B, HW, n_sel)
            embs.append(e.cpu())
    train_e = torch.cat(embs, dim=0)  # (N, HW, C')
    n, hw, c = train_e.shape

    # 위치별 가우시안: μ(HW,C'), Σ(HW,C',C') + εI, 역행렬 (CPU, float64 안정)
    train_e64 = train_e.double()
    mu = train_e64.mean(dim=0)  # (HW, C')
    centered = train_e64 - mu.unsqueeze(0)  # (N, HW, C')
    cov = torch.einsum("nhc,nhd->hcd", centered, centered) / (n - 1)  # (HW, C', C')
    cov += 0.01 * torch.eye(c, dtype=torch.float64).unsqueeze(0)
    inv_cov = torch.linalg.inv(cov)  # (HW, C', C')

    # test: 위치별 Mahalanobis, image score = max
    scores = []
    with torch.no_grad():
        for x in tedl:
            e = embed(model, x.to(device), idx).cpu().double()  # (B, HW, C') — MPS는 float64 미지원, cpu 먼저
            for img_e in e:
                d = img_e - mu  # (HW, C')
                m = torch.einsum("hc,hcd,hd->h", d, inv_cov, d)  # (HW,)
                scores.append(float(torch.sqrt(m.clamp(min=0)).max()))
    auroc = float(roc_auc_score(lab, scores))
    print(f"@image_auroc={auroc:.4f}", flush=True)

    history = [{"epoch": 0, "image_auroc": auroc}]
    pcq.log_config(backbone=backbone_name, img_size=img_size, category=CATEGORY,
                   method="padim_gaussian_mahalanobis", n_features=int(n_sel),
                   total_channels=int(total_c), device=device.type)
    pcq.save_metrics(history)
    pcq.save_run_summary(history=history, status="completed")
    pcq.save_manifest()
    pcq.finalize_run(history=history)
    out = pcq.output_dir()
    with open(f"{out}/describe.json", "w", encoding="utf-8") as f:
        json.dump(describe_run(out).to_dict(), f, ensure_ascii=False)


if __name__ == "__main__":
    main()
