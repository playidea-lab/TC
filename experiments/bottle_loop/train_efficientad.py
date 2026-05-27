"""cq 워커용 pcq 통합 — MVTec bottle student-teacher feature distillation (EfficientAD 계열).

pretrained resnet18 teacher(frozen)의 다중 레이어 feature를 student(scratch)가 정상(train/good)
데이터로만 모방 학습한다. 정상에서는 잘 모방되지만 이상 영역에서는 student가 따라가지 못해
teacher-student feature 불일치(1-cosine)가 커진다 → 그 공간 최대값을 image anomaly score로 쓴다.
CQ_CONFIG_JSON 주입 → pcq.config → log_config(effective) → describe_run → describe.json.
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

DATA_ROOT = os.environ.get(
    "DATA_ROOT", "/Users/changmin/datasets/MVtec-ad/mvtec_anomaly_detection")

cfg = pcq.config()
lr = float(cfg.get("learning_rate", 0.0004))
epochs = int(cfg.get("epochs", 20))
batch_size = int(cfg.get("batch_size", 16))
img_size = int(cfg.get("img_size", 256))
backbone_name = str(cfg.get("backbone", "resnet18"))
CATEGORY = str(cfg.get("category", "bottle"))

device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]


class BottleDS(Dataset):
    """ImageNet 정규화된 size×size RGB 텐서."""

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
    """resnet18 layer1-3 feature 추출기."""

    def __init__(self, pretrained: bool, backbone: str = "resnet18") -> None:
        super().__init__()
        if backbone == "wide_resnet50_2":
            w = Wide_ResNet50_2_Weights.IMAGENET1K_V1 if pretrained else None
            m = wide_resnet50_2(weights=w)
        else:
            w = ResNet18_Weights.IMAGENET1K_V1 if pretrained else None
            m = resnet18(weights=w)
        self.stem = nn.Sequential(m.conv1, m.bn1, m.relu, m.maxpool)
        self.l1, self.l2, self.l3 = m.layer1, m.layer2, m.layer3

    def forward(self, x: torch.Tensor) -> list[torch.Tensor]:
        x = self.stem(x)
        f1 = self.l1(x)
        f2 = self.l2(f1)
        f3 = self.l3(f2)
        return [f1, f2, f3]


def anomaly_scores(teacher: nn.Module, student: nn.Module,
                   dl: DataLoader, size: int) -> list[float]:
    """teacher-student feature 불일치(1-cosine) 공간 최대값 = image score."""
    student.eval()
    out: list[float] = []
    with torch.no_grad():
        for x in dl:
            x = x.to(device)
            tf, sf = teacher(x), student(x)
            amap = torch.zeros(x.size(0), 1, size, size, device=device)
            for t, s in zip(tf, sf):
                d = 1 - (F.normalize(t, dim=1) * F.normalize(s, dim=1)).sum(1, keepdim=True)
                amap += F.interpolate(d, size=size, mode="bilinear", align_corners=False)
            out.extend(amap.amax(dim=(1, 2, 3)).cpu().numpy().tolist())
    return out


def main() -> None:
    tr = list_train(DATA_ROOT)
    te, lab = list_test(DATA_ROOT)
    trdl = DataLoader(BottleDS(tr, img_size), batch_size=batch_size, shuffle=True, num_workers=0)
    tedl = DataLoader(BottleDS(te, img_size), batch_size=batch_size, shuffle=False, num_workers=0)

    teacher = FeatNet(True, backbone_name).to(device).eval()
    for p in teacher.parameters():
        p.requires_grad = False
    student = FeatNet(False, backbone_name).to(device)
    opt = torch.optim.Adam(student.parameters(), lr=lr)

    history = []
    for ep in range(epochs):
        student.train()
        tot = 0.0
        for x in trdl:
            x = x.to(device)
            with torch.no_grad():
                tf = teacher(x)
            sf = student(x)
            loss = sum(F.mse_loss(F.normalize(s, dim=1), F.normalize(t, dim=1))
                       for s, t in zip(sf, tf))
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += loss.item() * x.size(0)
        train_loss = tot / len(tr)
        auroc = float(roc_auc_score(lab, anomaly_scores(teacher, student, tedl, img_size)))
        history.append({"epoch": ep, "image_auroc": auroc, "train_loss": train_loss})
        print(f"@image_auroc={auroc:.4f} @train_loss={train_loss:.6f} epoch={ep}", flush=True)

    pcq.log_config(learning_rate=lr, epochs=epochs, batch_size=batch_size, img_size=img_size,
                   backbone=backbone_name, method="student_teacher_feature_distillation",
                   category=CATEGORY, device=device.type)
    pcq.save_metrics(history)
    pcq.save_run_summary(history=history, status="completed")
    pcq.save_manifest()
    pcq.finalize_run(history=history)
    out = pcq.output_dir()
    with open(f"{out}/describe.json", "w", encoding="utf-8") as f:
        json.dump(describe_run(out).to_dict(), f, ensure_ascii=False)
    print(f"@image_auroc={max(h['image_auroc'] for h in history):.4f}", flush=True)


if __name__ == "__main__":
    main()
