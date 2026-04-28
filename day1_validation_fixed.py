#!/usr/bin/env python3
"""Day 1 Validation Script - 3개 개선사항 검증"""

import pandas as pd

# Load the generated report (Korean column names)
df = pd.read_csv('output/상세리포트_2026-04-25.csv', encoding='utf-8-sig')

print('=' * 60)
print('Day 1 (2026-04-25) 개발 완료 검증')
print('=' * 60)
print()

# 1. Sector diversity (작업 1-1)
sector_col = '섹터그룹'
sector_unique = df[sector_col].nunique()
sector_values = df[sector_col].value_counts()
print('[작업 1-1] 섹터 자동 매핑 (refresh_assumptions.py 통합)')
print(f'  ✓ 고유 섹터 수: {sector_unique} (이전: 1, 목표: 70+)')
print(f'  ✓ Top 5: {", ".join(sector_values.head(5).index.tolist())}')
status1 = 'PASS' if sector_unique >= 50 else 'FAIL'
print(f'  상태: {status1}')
print()

# 2. Loss flag auto-detection (작업 1-2)
loss_col = '적자여부'
loss_count = (df[loss_col] == 1).sum()
print('[작업 1-2] 손실 플래그 자동 계산 (EPS 기반)')
print(f'  ✓ is_loss_making=1 종목: {loss_count} (이전: 0, 목표: 200+)')
status2 = 'PASS' if loss_count > 100 else 'FAIL'
print(f'  상태: {status2}')
print()

# 3. Action-weight consistency (작업 1-3)
action_col = '결합액션'
weight_col = '권장비중(%)'
exclude_with_weight = ((df[action_col] == '제외') & (df[weight_col] > 0)).sum()
print('[작업 1-3] 액션-비중 정합성 검증')
print(f'  ✓ 제외인데 비중>0 종목: {exclude_with_weight} (이전: 365, 목표: 0)')
status3 = 'PASS' if exclude_with_weight == 0 else 'FAIL'
print(f'  상태: {status3}')
print()

# 4. Market regime diversity
regime_col = '마켓레짐'
regime_dist = df[regime_col].value_counts()
print('[추가] 마켓레짐 분포 (Day 2-3에서 개선 예정)')
for regime, count in regime_dist.items():
    print(f'  {regime}: {count}')
print()

# 5. Summary
print('=' * 60)
print('최종 리포트 통계')
print('=' * 60)
print(f'총 종목 수: {len(df)}')
print(f'  최종매수후보: {(df[action_col] == "최종매수후보").sum()}')
print(f'  진입대기: {(df[action_col] == "진입대기").sum()}')
print(f'  관찰: {(df[action_col] == "관찰").sum()}')
print(f'  제외: {(df[action_col] == "제외").sum()}')
print()
print('=' * 60)
