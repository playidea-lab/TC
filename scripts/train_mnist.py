"""MNIST 1-epoch baseline — cq 원격 워커에서 실행될 entry script (현 PoC에선 sha256 source).

다음 사이클에서 cq workers로 디스패치 시 그대로 사용. 본 스크립트가 stdout에
`@key=value` 라인을 찍으면 cq MetricWriter가 파싱해 메트릭으로 보낸다.
"""

from __future__ import annotations

import argparse
import os
import sys

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader
from torchvision import datasets, transforms


class TinyMLP(nn.Module):
    """28*28 -> 128 -> 10 softmax. MNIST baseline 최소 모델."""

    def __init__(self) -> None:
        super().__init__()
        self.fc1 = nn.Linear(28 * 28, 128)
        self.fc2 = nn.Linear(128, 10)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x.view(x.size(0), -1)
        x = F.relu(self.fc1(x))
        return self.fc2(x)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lr", type=float, required=True)
    parser.add_argument("--batch_size", type=int, default=128)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--data_root", type=str, default=os.environ.get("MNIST_ROOT", "./data"))
    args = parser.parse_args()

    torch.manual_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # 데이터 준비
    transform = transforms.Compose([transforms.ToTensor(), transforms.Normalize((0.1307,), (0.3081,))])
    train_ds = datasets.MNIST(args.data_root, train=True, download=True, transform=transform)
    test_ds = datasets.MNIST(args.data_root, train=False, download=True, transform=transform)
    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    test_loader = DataLoader(test_ds, batch_size=512, shuffle=False)

    model = TinyMLP().to(device)
    opt = torch.optim.SGD(model.parameters(), lr=args.lr, momentum=0.9)

    # 학습 루프
    model.train()
    last_loss = 0.0
    for epoch in range(args.epochs):
        for batch_idx, (x, y) in enumerate(train_loader):
            x, y = x.to(device), y.to(device)
            opt.zero_grad()
            logits = model(x)
            loss = F.cross_entropy(logits, y)
            loss.backward()
            opt.step()
            last_loss = loss.item()
        print(f"epoch={epoch} @train_loss={last_loss:.4f}")

    # 평가
    model.eval()
    correct, total = 0, 0
    with torch.no_grad():
        for x, y in test_loader:
            x, y = x.to(device), y.to(device)
            pred = model(x).argmax(dim=1)
            correct += (pred == y).sum().item()
            total += y.size(0)
    acc = correct / total
    print(f"final @test_acc={acc:.4f} @train_loss={last_loss:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
