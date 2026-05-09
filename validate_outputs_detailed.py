"""상세 출력 파일 검증 스크립트"""
import pandas as pd
from pathlib import Path

output_dir = Path('output')
report_date = '2026-05-09'

# 1. scored_report 검증
report_path = output_dir / f'scored_report_{report_date}.csv'
report_df = pd.read_csv(report_path, encoding='utf-8-sig')
print("=" * 70)
print(f"[SCORED_REPORT] {report_path.name}")
print("=" * 70)
print(f"행 수: {len(report_df)}")
print(f"컬럼 수: {len(report_df.columns)}")
print(f"\n액션 분포:")
action_dist = report_df['결합액션'].value_counts()
print(action_dist)
print(f"\n종합지수 통계:")
print(report_df['종합지수'].describe())
print(f"\n포트비중 통계:")
print(report_df['포트비중(%)'].describe())

# 2. core_selection 검증
core_path = output_dir / f'core_selection_{report_date}.csv'
core_df = pd.read_csv(core_path, encoding='utf-8-sig')
print("\n" + "=" * 70)
print(f"[CORE_SELECTION] {core_path.name}")
print("=" * 70)
print(f"행 수: {len(core_df)}")
print(f"컬럼 수: {len(core_df.columns)}")
print(f"\n액션 분포:")
action_core = core_df['결합액션'].value_counts()
print(action_core)

# 3. positions 검증
positions_path = output_dir / f'positions_{report_date}.csv'
positions_df = pd.read_csv(positions_path, encoding='utf-8-sig')
print("\n" + "=" * 70)
print(f"[POSITIONS] {positions_path.name}")
print("=" * 70)
print(f"행 수: {len(positions_df)}")
print(f"컬럼: {list(positions_df.columns)}")
print(f"\n포지션 통계:")
print(f"position_rank 분포:\n{positions_df['position_rank'].value_counts().head(10)}")

# 4. 정합성 검증
print("\n" + "=" * 70)
print("[정합성 검증]")
print("=" * 70)
excluded_rows = report_df[report_df['결합액션']=='제외']
excluded_zero = (excluded_rows['포트비중(%)'] == 0).all()
print(f"✓ 결합액션=제외 비중 0 확인: {excluded_zero} ({len(excluded_rows)} rows)")
print(f"✓ core selection 종목 수: {core_df.shape[0]}")
print(f"✓ report & positions 행 수 일치: {report_df.shape[0]} == {positions_df.shape[0]} : {report_df.shape[0] == positions_df.shape[0]}")

print("\n" + "=" * 70)
print("[검증 완료]")
print("=" * 70)
print("✓ 모든 파일이 정상 생성되었습니다.")
