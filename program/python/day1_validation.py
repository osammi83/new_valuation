#!/usr/bin/env python3
"""Day 1 Validation Script - 3媛?媛쒖꽑?ы빆 寃利?""

import pandas as pd
import numpy as np

# Load the generated report
df = pd.read_csv('output/?곸꽭由ы룷??2026-04-25.csv', encoding='utf-8-sig')

print('=' * 60)
print('Day 1 (2026-04-25) 媛쒕컻 ?꾨즺 寃利?)
print('=' * 60)
print()

# 1. Sector diversity (?묒뾽 1-1)
sector_unique = df['sector_group'].nunique()
sector_values = df['sector_group'].value_counts()
print('[?묒뾽 1-1] ?뱁꽣 ?먮룞 留ㅽ븨 (refresh_assumptions.py ?듯빀)')
print(f'  ??怨좎쑀 ?뱁꽣 ?? {sector_unique} (?댁쟾: 1, 紐⑺몴: 70+)')
print(f'  ??Top 5: {", ".join(sector_values.head(5).index.tolist())}')
print('  ?곹깭: ??PASS' if sector_unique >= 50 else '  ?곹깭: ??FAIL')
print()

# 2. Loss flag auto-detection (?묒뾽 1-2)
loss_count = (df['is_loss_making'] == 1).sum()
print('[?묒뾽 1-2] ?먯떎 ?뚮옒洹??먮룞 怨꾩궛 (EPS 湲곕컲)')
print(f'  ??is_loss_making=1 醫낅ぉ: {loss_count} (?댁쟾: 0, 紐⑺몴: 200+)')
print('  ?곹깭: ??PASS' if loss_count > 100 else '  ?곹깭: ??FAIL')
print()

# 3. Action-weight consistency (?묒뾽 1-3)
exclude_with_weight = ((df['寃고빀?≪뀡'] == '?쒖쇅') & (df['沅뚯옣鍮꾩쨷(%)'] > 0)).sum()
print('[?묒뾽 1-3] ?≪뀡-鍮꾩쨷 ?뺥빀??寃利?)
print(f'  ???쒖쇅?몃뜲 鍮꾩쨷>0 醫낅ぉ: {exclude_with_weight} (?댁쟾: 365, 紐⑺몴: 0)')
print('  ?곹깭: ??PASS' if exclude_with_weight == 0 else '  ?곹깭: ??FAIL')
print()

# 4. Market regime diversity (異붽? ?뺤씤)
regime_dist = df['留덉폆?덉쭚'].value_counts()
print('[異붽?] 留덉폆?덉쭚 遺꾪룷 (Day 2-3?먯꽌 媛쒖꽑 ?덉젙)')
for regime, count in regime_dist.items():
    print(f'  ??{regime}: {count}')
print()

# 5. Summary
print('=' * 60)
print('理쒖쥌 由ы룷???듦퀎')
print('=' * 60)
print(f'珥?醫낅ぉ ?? {len(df)}')
print(f'  ??理쒖쥌留ㅼ닔?꾨낫: {(df["寃고빀?≪뀡"] == "理쒖쥌留ㅼ닔?꾨낫").sum()} 醫낅ぉ')
print(f'  ??吏꾩엯?湲? {(df["寃고빀?≪뀡"] == "吏꾩엯?湲?).sum()} 醫낅ぉ')
print(f'  ??愿李? {(df["寃고빀?≪뀡"] == "愿李?).sum()} 醫낅ぉ')
print(f'  ???쒖쇅: {(df["寃고빀?≪뀡"] == "?쒖쇅").sum()} 醫낅ぉ')
print()
print(f'?뚯씪 ?앹꽦 ?쒓컙: 2026-04-25')
print('?ㅼ쓬: Day 2 (留덉폆?덉쭚 怨좊룄??')
print('=' * 60)

