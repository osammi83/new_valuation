#!/usr/bin/env python3
"""Day 1 Validation Script - 3媛?媛쒖꽑?ы빆 寃利?""

import pandas as pd

# Load the generated report (Korean column names)
df = pd.read_csv('output/?곸꽭由ы룷??2026-04-25.csv', encoding='utf-8-sig')

print('=' * 60)
print('Day 1 (2026-04-25) 媛쒕컻 ?꾨즺 寃利?)
print('=' * 60)
print()

# 1. Sector diversity (?묒뾽 1-1)
sector_col = '?뱁꽣洹몃９'
sector_unique = df[sector_col].nunique()
sector_values = df[sector_col].value_counts()
print('[?묒뾽 1-1] ?뱁꽣 ?먮룞 留ㅽ븨 (refresh_assumptions.py ?듯빀)')
print(f'  ??怨좎쑀 ?뱁꽣 ?? {sector_unique} (?댁쟾: 1, 紐⑺몴: 70+)')
print(f'  ??Top 5: {", ".join(sector_values.head(5).index.tolist())}')
status1 = 'PASS' if sector_unique >= 50 else 'FAIL'
print(f'  ?곹깭: {status1}')
print()

# 2. Loss flag auto-detection (?묒뾽 1-2)
loss_col = '?곸옄?щ?'
loss_count = (df[loss_col] == 1).sum()
print('[?묒뾽 1-2] ?먯떎 ?뚮옒洹??먮룞 怨꾩궛 (EPS 湲곕컲)')
print(f'  ??is_loss_making=1 醫낅ぉ: {loss_count} (?댁쟾: 0, 紐⑺몴: 200+)')
status2 = 'PASS' if loss_count > 100 else 'FAIL'
print(f'  ?곹깭: {status2}')
print()

# 3. Action-weight consistency (?묒뾽 1-3)
action_col = '寃고빀?≪뀡'
weight_col = '沅뚯옣鍮꾩쨷(%)'
exclude_with_weight = ((df[action_col] == '?쒖쇅') & (df[weight_col] > 0)).sum()
print('[?묒뾽 1-3] ?≪뀡-鍮꾩쨷 ?뺥빀??寃利?)
print(f'  ???쒖쇅?몃뜲 鍮꾩쨷>0 醫낅ぉ: {exclude_with_weight} (?댁쟾: 365, 紐⑺몴: 0)')
status3 = 'PASS' if exclude_with_weight == 0 else 'FAIL'
print(f'  ?곹깭: {status3}')
print()

# 4. Market regime diversity
regime_col = '留덉폆?덉쭚'
regime_dist = df[regime_col].value_counts()
print('[異붽?] 留덉폆?덉쭚 遺꾪룷 (Day 2-3?먯꽌 媛쒖꽑 ?덉젙)')
for regime, count in regime_dist.items():
    print(f'  {regime}: {count}')
print()

# 5. Summary
print('=' * 60)
print('理쒖쥌 由ы룷???듦퀎')
print('=' * 60)
print(f'珥?醫낅ぉ ?? {len(df)}')
print(f'  理쒖쥌留ㅼ닔?꾨낫: {(df[action_col] == "理쒖쥌留ㅼ닔?꾨낫").sum()}')
print(f'  吏꾩엯?湲? {(df[action_col] == "吏꾩엯?湲?).sum()}')
print(f'  愿李? {(df[action_col] == "愿李?).sum()}')
print(f'  ?쒖쇅: {(df[action_col] == "?쒖쇅").sum()}')
print()
print('=' * 60)

