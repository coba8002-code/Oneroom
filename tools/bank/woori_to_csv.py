"""풀린 우리은행 내역 글자(.txt, 탭 구분) → 앱이 읽는 CSV. 사용: python woori_to_csv.py out.csv a.txt b.txt …"""
import csv
import re
import sys

rows = []
for path in sys.argv[2:]:
    for line in open(path, encoding="utf-8"):
        cells = [c.strip() for c in line.rstrip("\n").split("\t")]
        if len(cells) >= 7 and re.match(r"^20\d{2}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2}$", cells[0]):
            rows.append(cells[:7])
with open(sys.argv[1], "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["거래일시", "적요", "기재내용", "출금금액", "입금금액", "잔액", "취급점"])
    for r in sorted(rows, key=lambda r: r[0]):
        w.writerow(r)
print(len(rows))
