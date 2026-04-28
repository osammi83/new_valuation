#!/usr/bin/env python3
"""Day 1 Validation Script - 3개 개선사항 검증"""

import pandas as pd
import numpy as np

# Load the generated report
df = pd.read_csv('output/상세리포트_2026-04-25.csv', encoding='utf-8-sig')

print('=' * 60)
print('Day 1 (2026-04-25) 개발 완료 검증')
print('=' * 60)
print()

# 1. Sector diversity (작업 1-1)
sector_unique = df['sector_group'].nunique()
sector_values = df['sector_group'].value_counts()
print('[작업 1-1] 섹터 자동 매핑 (refresh_assumptions.py 통합)')
print(f'  ✓ 고유 섹터 수: {sector_unique} (이전: 1, 목표: 70+)')
print(f'  ✓ Top 5: {", ".join(sector_values.head(5).index.tolist())}')
print('  상태: ✅ PASS' if sector_unique >= 50 else '  상태: ❌ FAIL')
print()

# 2. Loss flag auto-detection (작업 1-2)
loss_count = (df['is_loss_making'] == 1).sum()
print('[작업 1-2] 손실 플래그 자동 계산 (EPS 기반)')
print(f'  ✓ is_loss_making=1 종목: {loss_count} (이전: 0, 목표: 200+)')
print('  상태: ✅ PASS' if loss_count > 100 else '  상태: ❌ FAIL')
print()

# 3. Action-weight consistency (작업 1-3)
exclude_with_weight = ((df['결합액션'] == '제외') & (df['권장비중(%)'] > 0)).sum()
print('[작업 1-3] 액션-비중 정합성 검증')
print(f'  ✓ 제외인데 비중>0 종목: {exclude_with_weight} (이전: 365, 목표: 0)')
print('  상태: ✅ PASS' if exclude_with_weight == 0 else '  상태: ❌ FAIL')
print()

# 4. Market regime diversity (추가 확인)
regime_dist = df['마켓레짐'].value_counts()
print('[추가] 마켓레짐 분포 (Day 2-3에서 개선 예정)')
for regime, count in regime_dist.items():
    print(f'  • {regime}: {count}')
print()

# 5. Summary
print('=' * 60)
print('최종 리포트 통계')
print('=' * 60)
print(f'총 종목 수: {len(df)}')
print(f'  • 최종매수후보: {(df["결합액션"] == "최종매수후보").sum()} 종목')
print(f'  • 진입대기: {(df["결합액션"] == "진입대기").sum()} 종목')
print(f'  • 관찰: {(df["결합액션"] == "관찰").sum()} 종목')
print(f'  • 제외: {(df["결합액션"] == "제외").sum()} 종목')
print()
print(f'파일 생성 시간: 2026-04-25')
print('다음: Day 2 (마켓레짐 고도화)')
print('=' * 60)
