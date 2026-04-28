# Deep-Research-Report v1.0 적용 계획서

**작성일**: 2026-04-25  
**대상**: 03.new_valuation 프로젝트  
**전략**: CSV 기반 구조 유지 + 고도화 단계 적용

---

## 1. 분석 요약

### 1.1 Deep-Research-Report vs 현재 시스템 Gap 분석

| 영역 | 현재 상태 | Deep-Report 요구사항 | Gap | CSV 구현 방식 |
|------|---------|-------------------|-----|-------------|
| 데이터 모델 | 순간 스냅샷 | PIT + effective_from | 치명적 | fundamentals_pti.csv 추가 |
| 피처 수 | ~30개 | 60+ (재무/수급/거시/뉴스) | 매우큼 | features_daily_*.csv 분리저장 |
| 모델 구조 | 단일점수 | 3계층 (종목선별/진입/청산) | 큼 | 별도 CSV 컬럼 추가 |
| 백테스트 | 미흡 | Walk-forward + RC/SPA + DSR | 매우큼 | backtest_*.csv + 분석 스크립트 |
| 모니터링 | 없음 | Drift/slippage 추적 | 큼 | monitoring_daily.csv |
| 저장소 | DB 필요(권장) | **CSV 기반으로 변경** | ✅ | 명시적으로 CSV 전용 설계 |

### 1.2 현재 시스템의 강점

✅ CSV 기반 배치 구조 (DB 없이도 운영 가능)  
✅ DART 공시 일일 반영  
✅ EPS 캐시 메커니즘  
✅ 자동화된 파이프라인 (run_daily.ps1)  
✅ 운영 매뉴얼 완성  

**→ 이것을 baseline으로 단계적 고도화 진행**

### 1.3 Deep-Report 적용 우선순위 재분류 (CSV 기반)

#### Phase 0: 기초 데이터 정합성 (현재 5일 일정에 포함)
| 작업 | 현황 | 대응 |
|------|------|------|
| 적자여부 자동 계산 | ❌ | Day 1에서 구현 |
| 섹터 자동 매핑 | ❌ | Day 1에서 구현 |
| 마켓레짐 다중신호 | ❌ | Day 2에서 구현 |

#### Phase 1: PIT 데이터 계층 (신규 추가, Week 2)
| 작업 | 내용 | 산출물 |
|------|------|--------|
| fundamentals_pti.csv | 공시 기반 재무정보 + effective_from | 760 rows × 20 cols |
| 공시시차 반영 | filing_date → effective_from 변환 | 룰셋 정의 |
| 포인트인타임 조인 | run_id + data_snapshot_id 기록 | join_log.csv |

#### Phase 2: 피처 스토어 구축 (Week 2-3)
| 범주 | 피처명 | 원천 | CSV 저장 형태 |
|------|--------|------|-------------|
| **재무** | TTM EPS 성장률 | eps_cache + 252일 히스토리 | features_fundamental_*.csv |
| | Forward EPS revision | DART 트렌드 | |
| | ROE, ROIC, FCF | fundamentals_pti.csv | |
| **기술** | ATR14, ADX14, BB | OHLCV | features_technical_*.csv |
| | OBV, MFI | 거래량 누적 | |
| **수급** | 외국인·기관 순매수 | KRX API (신규) | features_flow_*.csv |
| | 공매도 잔고 | KRX API (신규) | |
| **거시** | 금리, 환율, 신용스프레드 | ECOS/KOSIS (신규) | features_macro_*.csv |
| **유동성** | ADV20, turnover | 기존 | features_liquidity_*.csv |

#### Phase 3: 모델 분리 (Week 3-4)
| 모델 | 출력 | CSV 저장 |
|------|------|---------|
| Base Alpha | 10/20일 기대수익, 상단도달 확률 | predictions_alpha_*.csv |
| Meta Label | 진입 확률, 신뢰도 | predictions_meta_*.csv |
| Exit Engine | 손절/익절/추적 수위 | predictions_exits_*.csv |

#### Phase 4: 백테스트 프레임워크 (Week 4-5)
| 항목 | 내용 | CSV 산출물 |
|------|------|-----------|
| Orders | 매매 신호 + 체결가정 | backtest_orders_*.csv |
| Fills | 체결 기록 + 슬리피지 | backtest_fills_*.csv |
| Positions | 포지션 추적 + PnL | backtest_positions_*.csv |
| Metrics | Sharpe/Sortino/MDD/DSR | backtest_metrics_*.csv |

---

## 2. 현재 프로그램 변경 범위

### 2.1 파일별 수정 요약

#### build_daily_report.py (1748 라인)

| 섹션 | 현재 기능 | 변경 사항 | 라인 범위 | 복잡도 |
|------|---------|---------|---------|--------|
| 데이터 로드 | universe/assumptions/eps_cache | **+ fundamentals_pti 로드** | 100-200 | 🟡 |
| PIT 조인 | X | **신규: effective_from 기반 조인** | 신규 추가 | 🔴 |
| 피처 엔지니어링 | 현재 ~30개 피처 | **+ 재무/수급/거시/유동성 피처** | 600-800 | 🔴 |
| 점수 계산 | total_score = 0.4*val + 0.6*tech | **→ 3개 별도 모델로 분리** | 1300-1400 | 🔴 |
| 액션 로직 | hard filter (총점 기반) | **→ 확률 기반 + 신뢰도** | 1500-1600 | 🟡 |
| 매도 엔진 | 없음 | **신규: stop/trail/time-exit** | 신규 추가 | 🔴 |
| 출력 | 기존 컬럼 | **+ 새 모델/예측/기대값 컬럼** | 1700-1800 | 🟡 |

**추정 증가 라인**: 1748 → 2500+ (750+ 라인 추가)

#### refresh_assumptions.py (86 라인)

| 변경 | 내용 |
|------|------|
| PIT 업데이트 | fundamentals_pti.csv 새 행 추가 후 effective_from 계산 |
| 섹터 강화 | eps_cache에서 sector_code → sector_group 매핑 (기존) |
| 신규 추가 | fundamentals_pti 동기화 로직 |

**추정 증가**: +30 라인

#### preprocess_daily_updates.py (210 라인)

| 변경 | 내용 |
|------|------|
| 피처 생성 | 기술 피처 + 수급 피처 계산 추가 |
| CSV 저장 | features_daily_*.csv 분리 저장 |
| PIT 메타 | data_snapshot_id 생성 및 기록 |

**추정 증가**: +150 라인 → 총 360 라인

#### run_daily.ps1 (83 라인)

| 변경 | 내용 |
|------|------|
| 순서 재조정 | refresh_fundamentals.py 추가 (선택사항) |
| 에러 처리 | 신규 py 파일 실행 에러 처리 |
| 로깅 | data_snapshot_id 기록 |

**추정 증가**: +20 라인 → 총 103 라인

#### 신규 추가 파일 (4개)

1. **refresh_fundamentals.py** (100 라인)  
   - fundamentals_pti.csv 갱신 (DART 분기보고서 반영)
   - effective_from 계산

2. **build_features.py** (300 라인)  
   - 재무/기술/수급/거시/유동성 피처 일괄 계산
   - 분리 저장 (features_daily_*.csv)

3. **train_models.py** (250 라인)  
   - Base Alpha 모델 학습/저장
   - Meta Label 모델 학습/저장
   - Exit Engine 규칙/모델 저장

4. **backtest_engine.py** (400 라인)  
   - 과거 데이터 기반 백테스트
   - Walk-forward 구현
   - Walk-forward + purge/embargo

5. **monitoring.py** (150 라인)  
   - Drift 감지 (PSI/KS)
   - Slippage 추적
   - Model monitoring

### 2.2 데이터 구조 변경

#### 기존 CSV 구조 (변경 없음)
```
✓ universe.csv (788 rows)
✓ assumptions.csv (779 rows)
✓ eps_cache.csv (779 rows)
✓ 출력물 (상세리포트, 종목선정_핵심근거 등)
```

#### 신규 추가 CSV 구조 (PIT 기반)

```
fundamentals_pti.csv (포인트인타임 재무 데이터)
├─ ticker, company_name
├─ source: DART|API|MANUAL
├─ filing_date (공시 접수일)
├─ filing_ts (공시 시각)
├─ effective_from (효력 발생일 = 다음 거래일)
├─ fiscal_period (기간)
├─ eps_ttm, forward_eps, sales_ttm
├─ net_income_ttm, roe, roic, fcf_yield
├─ debt_to_equity, accrual_ratio, piotroski_f

features_daily_{DATE}.csv (일일 피처 통합)
├─ ticker, date
├─ data_snapshot_id (run_id)
├─ 기존 피처: close, ma20, rsi14, volume_ratio 등
├─ 신규 피처: atr14, adx14, bollinger_bw, obv, mfi
├─ 신규 피처: foreign_net_buy_ratio, short_balance_change
├─ 신규 피처: gdp_nowcast, credit_spread, usd_krw
├─ 신규 피처: news_sentiment_3d, search_trend_zscore

predictions_alpha_{DATE}.csv (Base Alpha 모델 출력)
├─ ticker
├─ prob_up_10d (상단 도달 확률)
├─ prob_up_20d
├─ expected_return_10d (기대수익률)
├─ expected_return_20d
├─ expected_drawdown_10d (기대낙폭)
├─ alpha_score (0~100)
├─ alpha_rank (상위도)

predictions_meta_{DATE}.csv (Meta Label 모델 출력)
├─ ticker
├─ prob_entry_today (오늘 진입 확률)
├─ prob_entry_tomorrow (내일 진입 확률)
├─ entry_score (0~100)
├─ entry_confidence (신뢰도)

predictions_exits_{DATE}.csv (Exit Engine 출력)
├─ ticker
├─ initial_stop_pct (초기손절 %)
├─ trail_atr_mult (트레일링 배수)
├─ take_profit_1_pct (부분익절 1차)
├─ take_profit_2_pct (부분익절 2차)
├─ time_stop_days (시간종료 일수)
├─ exit_score (매도 정합성)

backtest_metrics_{DATE_RANGE}.csv (백테스트 성능)
├─ model_version, run_date
├─ train_start, train_end, test_start, test_end
├─ total_return_pct, cagr_pct, sharpe, sortino
├─ max_drawdown_pct, calmar, hit_rate
├─ expectancy_pct, turnover_pct, trades_total
├─ dsr (deflated sharpe ratio)
├─ white_rc_pvalue, hansen_spa_pvalue

monitoring_daily.csv (모니터링 지표)
├─ date, data_snapshot_id
├─ feature_psi (피처 drift)
├─ prediction_ks (예측 분포 변화)
├─ slippage_realized_vs_backtest_pct
├─ model_drawdown_live_vs_backtest
├─ alerts (경보 메시지)

model_registry.csv (모델 메타데이터)
├─ model_id, model_name (alpha_v3.1.0 등)
├─ model_type (GBDT|TFT|ensemble)
├─ train_date, accuracy_val, accuracy_oos
├─ status (active|archived|failed)
├─ git_commit_sha, config_hash
```

---

## 3. 개발 구현 로드맵 (재구성)

### 3.1 단계별 구조

```
Phase 0: 기초 정합성 (Week 1, 현재 일정 5일 포함)
├─ 적자여부 자동 계산 (Day 1)
├─ 섹터 다중값 매핑 (Day 1)
├─ 마켓레짐 고도화 (Day 2)
└─ 액션-비중 검증 (Day 1)

Phase 1: PIT + 피처 확장 (Week 2-3, 10일)
├─ fundamentals_pti.csv 구축
├─ 포인트인타임 조인 로직
├─ 재무/기술/수급 피처 추가
└─ 피처 저장 자동화

Phase 2: 모델 분리 (Week 3-4, 8일)
├─ Base Alpha 모델 학습
├─ Meta Label 모델
├─ Exit Engine 규칙 정의
└─ 3계층 통합 API

Phase 3: 백테스트 (Week 5, 5일)
├─ Walk-forward 구현
├─ 거래비용 반영
├─ 유의성 검정 (RC/SPA/DSR)
└─ 성능 리포트

Phase 4: 모니터링 + 운영화 (Week 5-6, 5일)
├─ Drift 감지
├─ Slippage 추적
├─ Paper trading 대시보드
└─ 본 운영 전환

총 예상: 33일 (약 5주)
```

---

## 4. CSV 기반 설계의 장점 (vs DB)

| 비교 항목 | DB 기반 | **CSV 기반** |
|---------|--------|-----------|
| 초기 구축 비용 | 높음 | ✅ 낮음 |
| 배움 곡선 | 높음 | ✅ 낮음 |
| 운영 의존성 | DB 서버 필요 | ✅ 파일시스템만 |
| 재현성 | 복잡함 | ✅ 버전 관리 용이 |
| 스케일 (800종목) | 무제한 | ✅ 충분 (~1GB 년/종목) |
| 감사 추적 | 별도 구현 | ✅ 파일 버전 관리로 자동 |
| 백업/복구 | 복잡함 | ✅ 간단 |
| Git 통합 | 어려움 | ✅ 용이 |
| 임시 분석 | 쿼리 | ✅ pandas 직접 사용 |
| 협업 | 권한 관리 필요 | ✅ 파일 공유로 충분 |

---

## 5. 현재 프로그램 변경 체크리스트

### Phase 0 (현재 5일 일정)

- [x] 적자여부 자동 계산 (build_daily_report.py Line 1534)
- [x] 섹터 자동 매핑 (run_daily.ps1에 refresh_assumptions.py 추가)
- [x] 마켓레짐 다중신호 (build_daily_report.py Line 1301)
- [x] 액션-비중 검증 (build_daily_report.py Line 1565)
- [x] 시그널 신뢰도 검증 (build_daily_report.py Line 1656)

### Phase 1 (Week 2-3)

- [ ] fundamentals_pti.csv 스키마 정의
- [ ] refresh_fundamentals.py 신규 생성
- [ ] build_daily_report.py: PIT 조인 로직 추가
- [ ] build_features.py 신규 생성
- [ ] preprocess_daily_updates.py: 피처 생성 통합
- [ ] features_daily_*.csv 저장 자동화

### Phase 2 (Week 3-4)

- [ ] train_models.py 신규 생성
- [ ] Base Alpha 모델 학습 로직
- [ ] Meta Label 모델 학습 로직
- [ ] Exit Engine 규칙 정의
- [ ] predictions_*.csv 생성 로직
- [ ] build_daily_report.py: 3계층 모델 통합

### Phase 3 (Week 5)

- [ ] backtest_engine.py 신규 생성
- [ ] Walk-forward 구현
- [ ] 거래비용 시뮬레이션
- [ ] 유의성 검정 (RC/SPA/DSR)
- [ ] backtest_metrics_*.csv 생성

### Phase 4 (Week 5-6)

- [ ] monitoring.py 신규 생성
- [ ] Drift 감지 로직
- [ ] Slippage 추적 로직
- [ ] monitoring_daily.csv 생성
- [ ] 운영 매뉴얼 업데이트

---

## 6. 구현 우선순위 기준

```
Critical (반드시):
  ✓ PIT 데이터 모델 + effective_from
  ✓ 재무 피처 (TTM EPS 성장률, revision, ROE, FCF)
  ✓ 기술 피처 (ATR, ADX, BB, OBV)
  ✓ 수급 피처 (외국인, 기관, 공매도)
  ✓ Base Alpha + Meta Label 모델 분리
  ✓ Exit Engine (stop/trail/time)

High (권장):
  ○ 거시 피처 (금리, 환율, 신용스프레드)
  ○ 유동성 피처 상세화
  ○ Walk-forward 백테스트
  ○ 모니터링 대시보드

Medium (확장):
  ○ 뉴스 감성 분석 (NLP)
  ○ VPIN, OFI 고빈도 신호
  ○ RL 기반 포지션 사이징
  ○ 30분봉 intraday 모델
```

---

## 7. 위험 및 완화책

| 위험 | 영향 | 완화책 |
|------|------|--------|
| PIT 조인 로직 오류 | 데이터 누수 (leakage) | Unit test + 과거 데이터로 재현 검증 |
| 피처 스토어 용량 | 저장공간 부족 | 일일 갱신 정책 (60일 롤링) |
| 모델 학습 시간 | 일일 배치 지연 | 병렬 학습 + caching |
| 거래비용 추정 | 백테스트-현실 gap | 실제 거래 이력 기반 보정 |
| 공시시차 누락 | 신호 생성 오류 | effective_from 엄격한 검증 |

---

## 8. 성공 기준

### Phase 0 완료 시
- 적자여부 분포 정상화 (0 → 200+)
- 섹터 다양화 (1 → 70+)
- 마켓레짐 변화 (BULL only → 분산)
- 액션-비중 일관성 100%

### Phase 1 완료 시
- 피처 수 30 → 60+
- 피처 스토어 일일 자동 생성
- PIT 조인 검증 성공 (과거 데이터 재현 가능)

### Phase 2 완료 시
- Base Alpha model AUC > 0.60
- Meta Label model Precision@20% > 0.70
- Exit rules 백테스트 hit_rate > 0.52

### Phase 3 완료 시
- Walk-forward Sharpe > 1.0
- DSR > 0 (과최적화 없음)
- RC/SPA p-value < 0.05 (통계 유의성)

### Phase 4 완료 시
- 모니터링 drift 실시간 경보
- Paper trading paper loss < 1% vs backtest
- 본 운영 전환 준비 완료

---

## 9. 참고 파일 위치

- **현재 프로젝트**: /03.new_valuation/
- **코드**: build_daily_report.py, preprocess_daily_updates.py 등
- **데이터**: universe.csv, assumptions.csv, eps_cache.csv
- **출력**: output/*.csv
- **매뉴얼**: 문서/*.md

---

**다음 단계**: 이 계획을 바탕으로 개발일정표_2026-04.md를 수정합니다.
